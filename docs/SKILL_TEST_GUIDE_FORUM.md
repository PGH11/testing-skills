# Skill 自动化测试实战总结

> 说明：本文为公开分享的脱敏版本，重点展示可复用的方法论与工程落地，不包含业务敏感信息（账号、接口密钥、内部模型策略等）。

## 1. 我解决的问题是什么

很多团队做 Skill 测试时，常见误区是“能跑通一次就算通过”。  
我在项目里重点解决的是下面这 4 个稳定性问题：

- 用户显式参数在多轮对话中被改写（参数漂移）
- 脚本只给 warning，不做硬阻断（错误参数被继续提交）
- 只测 happy path，异常恢复链路几乎空白
- 测试缺少分层，定位问题时分不清脚本层还是 Agent 层

我的最终做法是：**三层分治 + 统一测试基建 + 可量化指标**。

## 2. 分层测试架构（核心）

### L1：CLI 单元测试（快、稳、每天跑）

目标：验证脚本本身“可控、可回归”。

- 参数解析与分发是否正确
- 必填参数缺失是否立即失败（`SystemExit`）
- 非法组合是否被阻断（而非 warning 后继续）
- 输出结构和退出码是否稳定（便于 CI）

### L2：集成测试（真实调用、夜间或发版前跑）

目标：验证真实链路可用性与结果质量。

- 真登录态下提交真实任务
- 轮询直到完成/失败/超时
- 校验关键输出字段（状态、结果 URL/ID、费用等）

### L3：Agent 黑盒回归（规则一致性）

目标：验证“对话行为”是否始终遵循规则。

- 显式参数不改写
- 缺参先追问
- 默认流程命中（如新任务优先 `run`，超时转 `query`）
- 异常恢复路径正确（鉴权失效、超时、额度不足等）

## 3. CLI 测试技巧（我认为最实用的一条）

推荐主方案：

- `monkeypatch.setattr(sys, "argv", [...])`
- 直接调用脚本 `main()`
- `capsys.readouterr()` 断言 `stdout/stderr`
- `pytest.raises(SystemExit)` 断言退出码

为什么选这个：

- 比 `subprocess` 更快、更稳定、定位更准
- 对“参数分发”和“异常分支”覆盖效率最高
- 适合作为大规模回归的主力手段

`subprocess.run(...)` 只建议保留少量冒烟用例，用来验证进程级入口行为。

## 4. pytest 示例（可直接改造）

下面给 3 个最常用模板，基本覆盖 80% 的 Skill 脚本测试需求。

### 4.1 CLI 单元：参数透传 + 输出断言

```python
import sys
import pytest
import your_cli_module

def test_run_passes_args(monkeypatch, capsys):
    monkeypatch.setattr(
        sys, "argv",
        ["tool.py", "run", "--type", "text2xxx", "--model", "model-a", "--count", "2"]
    )
    your_cli_module.main()

    out = capsys.readouterr().out
    assert "status:" in out
```

适用点：

- 验证 `main()` 参数解析是否生效
- 验证输出关键字段是否稳定

### 4.2 逆向单元：缺参阻断 + 退出码

```python
import sys
import pytest
import your_cli_module

def test_missing_required_arg_should_exit(monkeypatch):
    monkeypatch.setattr(
        sys, "argv",
        ["tool.py", "run", "--type", "image_edit"]  # 故意缺必填参数
    )
    with pytest.raises(SystemExit) as exc_info:
        your_cli_module.main()
    assert exc_info.value.code == 2
```

适用点：

- 验证必填参数缺失是否被硬阻断
- 验证失败退出码是否稳定

### 4.3 集成测试：真实调用 + 凭证前置 + 关键字段断言

```python
import sys
import pytest
import your_cli_module
from your_test_helpers import require_credentials

def test_real_generation(monkeypatch, capsys):
    require_credentials()  # 无凭证时 skip，避免环境问题导致假失败

    monkeypatch.setattr(
        sys, "argv",
        [
            "tool.py", "run",
            "--type", "text2xxx",
            "--model", "stable-model",
            "--prompt", "fixed prompt for regression",
            "--timeout", "900",
            "--interval", "20",
        ]
    )
    your_cli_module.main()

    out = capsys.readouterr().out
    assert "status: completed" in out
    assert "url" in out or "taskId" in out
```

适用点：

- 验证真实提交链路
- 用固定参数降低波动
- 避免整段文案断言造成脆弱测试

## 5. 集成测试怎么写才不脆

我总结了 4 条强约束：

- **固定参数**：减少模型或文案波动导致的误报
- **固定素材**：统一测试图片/视频，避免外部 URL 不稳定
- **关键字段断言**：断状态和结构字段，不断整段文案
- **凭证前置检查**：无凭证直接 `skip`，避免环境问题污染结果

示例断言策略：

- 成功态：`status`、`video_url` / `image_url` / `taskId`
- 失败态：错误码 + 可诊断信息（不要只看文案）

## 6. 我补齐的逆向测试矩阵

很多团队只做正向，我重点补了逆向：

- 缺参阻断（必填缺失 -> `SystemExit code=2`）
- 超时恢复（`TimeoutError` 后兜底查询 -> `code=2`）
- 服务端错误透传（如限流码、任务失败码）
- 估价/查询类边界输入（未知模型、空结果）

一句话：  
**正向验证“能跑通”，逆向验证“错得对”。**

## 7. 并发执行的坑与处理

并发命令常用：

- `pytest -q -m integration -n auto`

并发后最常见的两类失败：

- 频率限制（如 `code=1048`）
- 提交成功但任务执行失败（`TASK_FAILED`）

我在工程侧做了两件事提升稳定性：

- 在集成测试入口增加随机抖动（降低瞬时峰值）
- 统一使用本地稳定测试素材，减少外链输入带来的不确定性

## 8. 可复制的测试目录模板

建议结构：

- `tests/test_xxx_cli.py`：CLI 单元
- `tests/test_xxx_integration.py`：真实调用集成
- `tests/test_xxx_negative.py`：逆向/异常路径
- `tests/integration_helpers.py`：集成辅助层（凭证、素材、CLI 调用封装）

推荐标记：

- `@pytest.mark.unit`
- `@pytest.mark.integration`
- `@pytest.mark.agent`

CI 建议：

- PR：仅 `unit`
- nightly：`unit + integration`
- Skill 规则更新：强制加跑 `agent`

## 9. 指标化验收（体现测试成熟度）

我建议把下面指标长期化：

- 参数一致率（显式参数是否原样执行）
- 缺参先追问率
- 非法参数阻断率
- 同指令多次执行漂移率
- 异常恢复成功率

这几项比“通过率”更能反映 Skill 的真实可控性。

## 10. 最容易被忽略的经验

- 脚本层没有硬约束，黑盒层一定会漂
- 输出断言尽量结构化，少断整段文本
- 真实集成测试必须控制输入（素材、参数、超时）
- 没有逆向用例，线上故障定位成本会指数级上升

## 11. 结论

Skill 测试要真正有含金量，不在于“能不能跑通”，而在于三件事：

- **边界守得住**（CLI 硬约束）
- **行为不跑偏**（Agent 一致性）
- **失败可诊断**（逆向与异常恢复）

我的实践结论是：  
**先把 CLI 钉死，再做集成闭环，最后用 Agent 黑盒验一致性。**  
这样定位效率和回归稳定性都会明显提升。
