"""
视频创作助手 Agent。

职责边界：
- Agent 负责理解用户创意、构思视频内容、整理/修改 prompt、生成 negative_prompt。
- 前端负责选择比例、时长、模型、清晰度、生成数量等 UI 参数。
- 用户确认后，后端合并 Agent 内容参数和前端 UI 参数，再调用生成接口。

运行前请安装依赖并配置环境变量：
    pip install langgraph langchain-core langchain-openai pydantic python-dotenv

.env 示例：
    ARK_API_KEY=你的 Ark API Key
    ARK_MODEL=ark-code-latest
    ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/coding/v3
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Literal, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv 是可选依赖，未安装时直接读取系统环境变量。
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv()


DEFAULT_ARK_API_KEY = os.getenv("ARK_API_KEY", "")  # 请在 .env 中配置你的 Ark API Key
LITMEDIA_API_URL = "https://litvideo-api.litmedia.ai/lit-video/do-text-video"
LITMEDIA_TOKEN = os.getenv("LITMEDIA_TOKEN", "")  # 请在 .env 中配置你的 LitMedia Token
DEFAULT_LITMEDIA_API_SECRET = os.getenv("LITMEDIA_API_SECRET", "")  # 请在 .env 中配置你的 API Secret
DEFAULT_LITMEDIA_FINGERPRINT = os.getenv("LITMEDIA_FINGERPRINT", "")  # 请在 .env 中配置你的 Fingerprint
DEBUG_AI_OUTPUT = os.getenv("DEBUG_AI_OUTPUT", "0") != "0"


def debug_print(title: str, payload: Any) -> None:
    """打印 AI 调试信息；设置 DEBUG_AI_OUTPUT=0 可关闭。"""

    if not DEBUG_AI_OUTPUT:
        return

    if isinstance(payload, BaseModel):
        payload_text = payload.model_dump_json(ensure_ascii=False, indent=2)
    else:
        payload_text = json.dumps(payload, ensure_ascii=False, indent=2)

    print(f"\n[DEBUG] {title}:\n{payload_text}\n")


class CreativeParams(BaseModel):
    """Agent 负责维护的内容参数。"""

    prompt: str | None = Field(default=None, description="最终视频提示词")
    negative_prompt: str | None = Field(default=None, description="负向提示词")


class FrontendParams(BaseModel):
    """前端页面选择的 UI 参数；CLI 里用默认值模拟。"""

    video_model: str = Field(default="54", description="前端选择的视频模型")
    video_num: int = Field(default=1, ge=1, le=4, description="前端选择的生成数量")
    ratio: str = Field(default="16:9", description="前端选择的视频比例")
    quality: str = Field(default="360p", description="前端选择的视频清晰度")
    duration: int = Field(default=5, ge=5, le=15, description="前端选择的视频时长")
    open_filter: int = Field(default=0, ge=0, le=1, description="是否开启过滤")
    sound_effect_switch: int = Field(default=1, ge=0, le=1, description="是否开启音效")
    seed: str = Field(default="", description="随机种子")
    is_feed: int = Field(default=0, ge=0, le=1, description="是否进入 feed")


class CreativeParamsPatch(BaseModel):
    """LLM 本轮识别到的内容参数补丁。"""

    prompt: str | None = Field(default=None, description="本轮新增或修改的视频提示词")
    negative_prompt: str | None = Field(default=None, description="本轮新增或修改的负向提示词")


class CreativeUnderstanding(BaseModel):
    """LLM 对用户输入的结构化理解。"""

    intent: Literal[
        "chat",
        "brainstorm",
        "create_prompt",
        "update_prompt",
        "update_negative_prompt",
        "confirm",
        "cancel",
    ] = Field(description="用户当前意图")
    params_patch: CreativeParamsPatch = Field(
        default_factory=CreativeParamsPatch,
        description="需要合并到当前内容参数的补丁",
    )
    merge_strategy: Literal["fill_missing", "overwrite"] = Field(
        default="fill_missing",
        description="fill_missing 只填空字段；overwrite 表示用户明确要求修改已有内容",
    )
    reply: str = Field(description="要回复用户的自然语言内容")
    needs_clarification: bool = Field(default=False, description="是否需要继续追问")
    clarification_question: str | None = Field(default=None, description="需要追问的问题")
    ready_for_submit: bool = Field(default=False, description="内容参数是否已经足够提交")
    confirm_submit: bool = Field(default=False, description="用户是否明确确认提交")


class ChatTurn(BaseModel):
    """命令行会话历史。"""

    role: Literal["user", "assistant"]
    content: str


class CreativeState(TypedDict):
    """LangGraph 状态。"""

    user_input: str
    params: CreativeParams
    chat_history: list[ChatTurn]
    route: Literal["chat", "creative"]
    reply: str
    is_ready: bool
    awaiting_confirmation: bool


ROUTER_PROMPT = """你是 LangGraph 路由节点，负责判断用户当前输入走哪条路径。

可选 route：
- chat：寒暄、询问能力、询问上下文、问你能做什么、普通解释。
- creative：用户在表达视频创意、要求构思、选择方案、修改 prompt、确认提交、取消提交。

判断规则：
1. 如果用户问“你能帮我干嘛”“你记得我说了什么”，route=chat。
2. 如果用户说“我想生成一个视频”“帮我想几个方向”“第二种”“改成更搞笑”，route=creative。
3. 如果系统正在等待确认，用户表达确认、继续、取消或修改，route=creative。
"""

CREATIVE_PROMPT = """你是一个专业的视频创作助手。

产品边界：
- 你只负责内容创作：构思视频方向、整理 prompt、修改 prompt、生成 negative_prompt。
- 不要追问比例、时长、模型、清晰度、生成数量，这些都由前端页面选择。
- 不要调用接口，不要声称已经生成视频。

你需要输出结构化结果：
- intent：用户意图。
- params_patch：本轮要写入或修改的 prompt / negative_prompt。
- merge_strategy：用户明确修改已有 prompt 时用 overwrite，否则用 fill_missing。
- reply：给用户看的自然语言回复。
- needs_clarification：如果用户想做视频但内容太泛，设为 true。
- clarification_question：需要追问时的问题。
- ready_for_submit：当 prompt 已具体到可提交时设为 true。
- confirm_submit：用户明确确认“就这样/确认/开始生成”时设为 true。

创作标准：
1. 如果用户只说“小狗视频”“美食视频”这类很泛的主题，不要直接提交，给 2-3 个创意方向让用户选。
2. 如果用户选择“第二种/就这个”，结合最近对话把对应方案整理成完整 prompt。
3. 如果用户要求“改成/更/不要/加入”，要修改现有 prompt，并在回复里明确告诉用户已改成什么。
4. prompt 要包含主体、动作、场景、氛围或镜头感，尽量可直接用于文生视频。
5. 回复要自然、简洁，先告诉用户你做了什么，再给下一步建议。
"""

CHAT_PROMPT = """你是一个视频创作助手。

你可以帮助用户：
1. 根据一句想法扩展成视频提示词。
2. 设计短视频剧情、镜头和风格。
3. 优化已有 prompt，让画面更具体。
4. 根据要求改写 prompt，比如更治愈、更搞笑、更电影感。
5. 生成 negative_prompt，例如不要文字、不要模糊、不要变形。

注意：
- 前端会负责比例、时长、模型、清晰度、生成数量。
- 你不要说已经生成了视频。
- 如果用户问上下文，要根据最近对话和当前参数回答。
"""


def build_llm() -> ChatOpenAI:
    """创建支持 with_structured_output 的聊天模型。"""

    if load_dotenv is not None:
        load_dotenv()

    ark_api_key = os.getenv("ARK_API_KEY") or DEFAULT_ARK_API_KEY
    if not ark_api_key:
        raise ValueError("未检测到 ARK_API_KEY，请先配置环境变量后再运行。")

    return ChatOpenAI(
        api_key=ark_api_key,
        base_url=os.getenv(
            "ARK_BASE_URL",
            "https://ark.cn-beijing.volces.com/api/coding/v3",
        ),
        model=os.getenv("ARK_MODEL", "ark-code-latest"),
        temperature=0,
    )


llm = build_llm()
router_llm = llm.with_structured_output(
    type(
        "RouteDecision",
        (BaseModel,),
        {
            "__annotations__": {
                "route": Literal["chat", "creative"],
                "reason": str,
            },
            "route": Field(description="chat 或 creative"),
            "reason": Field(description="路由原因"),
        },
    )
)
creative_llm = llm.with_structured_output(CreativeUnderstanding)


def history_to_text(history: list[ChatTurn], limit: int = 10) -> str:
    """把最近对话转成提示词上下文。"""

    return "\n".join(f"{turn.role}: {turn.content}" for turn in history[-limit:])


def intent_router(state: CreativeState) -> CreativeState:
    """判断当前输入是普通聊天还是创作任务。"""

    messages = [
        SystemMessage(content=ROUTER_PROMPT),
        HumanMessage(
            content=(
                "当前内容参数：\n"
                f"{state['params'].model_dump_json(ensure_ascii=False, exclude_none=True)}\n\n"
                f"是否正在等待最终确认：{state['awaiting_confirmation']}\n\n"
                "最近对话：\n"
                f"{history_to_text(state['chat_history'], limit=8) or '暂无'}\n\n"
                "用户最新输入：\n"
                f"{state['user_input']}"
            )
        ),
    ]
    decision = router_llm.invoke(messages)
    debug_print("intent_router AI 返回", decision)

    return {
        **state,
        "route": decision.route,
        "reply": "",
    }


def route_by_intent(state: CreativeState) -> Literal["chat", "creative"]:
    """映射 LangGraph 分支。"""

    return state["route"]


def chat_responder(state: CreativeState) -> CreativeState:
    """处理闲聊、能力介绍和上下文问答。"""

    messages = [
        SystemMessage(
            content=(
                f"{CHAT_PROMPT}\n\n"
                "当前内容参数：\n"
                f"{state['params'].model_dump_json(ensure_ascii=False, exclude_none=True)}"
            )
        )
    ]
    for turn in state["chat_history"][-10:]:
        if turn.role == "user":
            messages.append(HumanMessage(content=turn.content))
        else:
            messages.append(AIMessage(content=turn.content))
    messages.append(HumanMessage(content=state["user_input"]))

    response = llm.invoke(messages)
    debug_print("chat_responder AI 返回", {"content": str(response.content)})

    return {
        **state,
        "reply": str(response.content),
        "is_ready": False,
    }


def creative_worker(state: CreativeState) -> CreativeState:
    """理解用户创意，更新 prompt，并生成回复。"""

    current_params = state["params"]
    messages = [
        SystemMessage(content=CREATIVE_PROMPT),
        HumanMessage(
            content=(
                "当前内容参数：\n"
                f"{current_params.model_dump_json(ensure_ascii=False, exclude_none=True)}\n\n"
                "最近对话：\n"
                f"{history_to_text(state['chat_history'], limit=10) or '暂无'}\n\n"
                f"是否正在等待最终确认：{state['awaiting_confirmation']}\n\n"
                "用户最新输入：\n"
                f"{state['user_input']}"
            )
        ),
    ]
    understanding = creative_llm.invoke(messages)
    debug_print("creative_worker AI 返回", understanding)

    updated_params = current_params.model_copy(deep=True)
    patch = understanding.params_patch
    allow_overwrite = understanding.merge_strategy == "overwrite"

    if patch.prompt and (updated_params.prompt is None or allow_overwrite):
        updated_params.prompt = patch.prompt.strip()
    if patch.negative_prompt and (
        updated_params.negative_prompt is None or allow_overwrite
    ):
        updated_params.negative_prompt = patch.negative_prompt.strip()

    is_ready = bool(
        state["awaiting_confirmation"]
        and understanding.confirm_submit
        and updated_params.prompt
    )
    awaiting_confirmation = bool(
        understanding.ready_for_submit
        and updated_params.prompt
        and not is_ready
    )

    return {
        **state,
        "params": updated_params,
        "reply": understanding.reply,
        "is_ready": is_ready,
        "awaiting_confirmation": awaiting_confirmation,
    }


def build_graph():
    """构建视频创作助手状态机。"""

    graph = StateGraph(CreativeState)
    graph.add_node("intent_router", intent_router)
    graph.add_node("chat_responder", chat_responder)
    graph.add_node("creative_worker", creative_worker)

    graph.add_edge(START, "intent_router")
    graph.add_conditional_edges(
        "intent_router",
        route_by_intent,
        {
            "chat": "chat_responder",
            "creative": "creative_worker",
        },
    )
    graph.add_edge("chat_responder", END)
    graph.add_edge("creative_worker", END)

    return graph.compile()


def format_final_params(params: CreativeParams) -> str:
    """输出最终内容参数。"""

    return (
        "内容已确认，准备合并前端 UI 参数后提交：\n"
        f"{params.model_dump_json(ensure_ascii=False, exclude_none=True, indent=2)}"
    )


def generate_signature_params() -> dict[str, str]:
    """生成 LitMedia 接口所需动态签名字段。"""

    api_secret = os.getenv("LITMEDIA_API_SECRET") or DEFAULT_LITMEDIA_API_SECRET
    timestamp = str(int(time.time() * 1000))
    random_str = str(random.randint(0, 100_000_000))
    sha1_hex = hashlib.sha1(f"{timestamp}{random_str}{api_secret}".encode()).hexdigest()
    signature = hashlib.md5(sha1_hex.encode()).hexdigest().upper()
    sign = hashlib.sha1(
        f"{timestamp}{random_str}{api_secret}{signature}".encode()
    ).hexdigest().upper()
    fingerprint = os.getenv("LITMEDIA_DEVICE_CODE") or DEFAULT_LITMEDIA_FINGERPRINT

    return {
        "timeStamp": timestamp,
        "randomStr": random_str,
        "signature": signature,
        "fingerprint": fingerprint,
        "sign": sign,
    }


def build_litmedia_payload(
    creative_params: CreativeParams,
    frontend_params: FrontendParams,
) -> dict[str, str]:
    """合并 Agent 内容参数和前端 UI 参数，构建接口表单。"""

    if not creative_params.prompt:
        raise ValueError("缺少 prompt，无法提交生成。")

    signature_params = generate_signature_params()
    return {
        "video_model": frontend_params.video_model,
        "video_num": str(frontend_params.video_num),
        "prompt": creative_params.prompt,
        "open_filter": str(frontend_params.open_filter),
        "sound_effect_switch": str(frontend_params.sound_effect_switch),
        "ratio": frontend_params.ratio,
        "quality": frontend_params.quality,
        "duration": str(frontend_params.duration),
        "seed": frontend_params.seed,
        "negative_prompt": creative_params.negative_prompt or "",
        "is_feed": str(frontend_params.is_feed),
        **signature_params,
    }


def build_litmedia_headers(fingerprint: str) -> dict[str, str]:
    """构建 LitMedia 请求头。"""

    return {
        "accept": "application/json",
        "accept-language": "zh-HK,zh;q=0.9,en-US;q=0.8,en;q=0.7,zh-CN;q=0.6",
        "content-type": "application/x-www-form-urlencoded;charset=UTF-8",
        "lang": "ZH-HANT",
        "monimaster-device-code": fingerprint,
        "monimaster-device-type": "3",
        "monimaster-token": LITMEDIA_TOKEN,
        "nation-code": "EN",
        "origin": "https://www.litmedia.ai",
        "referer": "https://www.litmedia.ai/",
        "timezone": "Asia/Shanghai",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/147.0.0.0 Safari/537.36"
        ),
    }


def call_litmedia_text_video(
    creative_params: CreativeParams,
    frontend_params: FrontendParams,
) -> dict[str, Any]:
    """调用 LitMedia 文生视频接口。"""

    payload = build_litmedia_payload(creative_params, frontend_params)
    debug_print("LitMedia payload", {**payload, "monimaster-token": "***"})

    request = urllib.request.Request(
        LITMEDIA_API_URL,
        data=urllib.parse.urlencode(payload).encode("utf-8"),
        headers=build_litmedia_headers(payload["fingerprint"]),
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            response_text = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LitMedia 接口返回 HTTP {exc.code}: {error_body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"LitMedia 接口请求失败: {exc.reason}") from exc

    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        return {"raw": response_text}


def run_cli() -> None:
    """命令行多轮对话入口。"""

    app = build_graph()
    # CLI 没有前端页面，这里用默认值模拟前端已选择的 UI 参数。
    frontend_params = FrontendParams()
    state: CreativeState = {
        "user_input": "",
        "params": CreativeParams(),
        "chat_history": [],
        "route": "chat",
        "reply": "",
        "is_ready": False,
        "awaiting_confirmation": False,
    }

    print("视频创作助手已启动，输入 exit 或 quit 退出。")

    while not state["is_ready"]:
        user_input = input("User: ").strip()
        if user_input.lower() in {"exit", "quit"}:
            print("已退出。")
            return
        if not user_input:
            print("Agent: 可以告诉我你想做什么类型的视频，或者问我能帮你做什么。")
            continue

        state = {
            **state,
            "user_input": user_input,
            "reply": "",
            "is_ready": False,
        }
        state = app.invoke(state)

        print(f"Agent: {state['reply']}")
        state["chat_history"].extend(
            [
                ChatTurn(role="user", content=user_input),
                ChatTurn(role="assistant", content=state["reply"]),
            ]
        )

    print(f"Agent: {format_final_params(state['params'])}")
    print(
        "Agent: 当前使用的前端 UI 参数："
        f"{frontend_params.model_dump_json(ensure_ascii=False)}"
    )
    try:
        result = call_litmedia_text_video(state["params"], frontend_params)
    except Exception as exc:
        print(f"Agent: 接口调用失败：{exc}")
        return
    print(f"Agent: 接口响应：{json.dumps(result, ensure_ascii=False, indent=2)}")


if __name__ == "__main__":
    run_cli()
