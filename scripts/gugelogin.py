# -*- coding:utf8 -*-
import os
import csv
import json
import time

from DrissionPage import ChromiumOptions, ChromiumPage
from DrissionPage.common import Keys, Actions

# 配置信息
AUTH_FILE = 'drission_auth.json'
TARGET_URL = 'https://search.google.com/u/0/search-console/video-index?resource_id=https%3A%2F%2Fwww.litmedia.ai%2F'
PROPERTY_URL = 'https://www.litmedia.ai/'  # 你的 GSC 资源（站点属性）URL，通常以 / 结尾
SUCCESS_SHOTS_DIR = ''  # 运行时在 main() 自动赋值，例如 success_shots_20260211_120000
FAILURE_SHOTS_DIR = ''  # 运行时在 main() 自动赋值，例如 failure_shots_20260211_120000

# 登录态判断：优先用 URL 是否重定向到 accounts.google.com（最稳定）
# 其次再用登录页特征元素兜底（邮箱输入框）
LOGIN_REDIRECT_DOMAIN = 'accounts.google.com'
LOGIN_PAGE_EMAIL_INPUT_XPATH = 'xpath://input[@type="email" or @id="identifierId"]'


def check_login(page):
    cur_url = getattr(page, "url", "") or ""
    if LOGIN_REDIRECT_DOMAIN in cur_url:
        return False
    try:
        if page.ele(LOGIN_PAGE_EMAIL_INPUT_XPATH, timeout=2):
            return False
    except Exception:
        pass
    return True


def save_login_data(page):
    print("--- 登录态失效或不存在，请在浏览器中完成登录 ---")
    page.get(TARGET_URL)
    input("登录成功并跳转到主页后，请在此处按回车键保存...")

    cookies = page.cookies()
    ls_raw = page.run_js('return JSON.stringify(localStorage);')
    ls_data = json.loads(ls_raw)

    auth_data = {"cookies": cookies, "local_storage": ls_data}
    with open(AUTH_FILE, 'w', encoding='utf-8') as f:
        json.dump(auth_data, f, ensure_ascii=False, indent=2)
    print(f"✅ 状态已保存至 {AUTH_FILE}")


def inject_auth(page):
    """读取并注入本地存储的数据（Cookie + localStorage）"""
    if not os.path.exists(AUTH_FILE):
        return False
    with open(AUTH_FILE, 'r', encoding='utf-8') as f:
        auth_data = json.load(f)

    # 先到 google 域再写 cookie（更稳）
    page.get('https://www.google.com/')
    cookies_list = auth_data.get('cookies', []) if isinstance(auth_data, dict) else []
    if isinstance(cookies_list, list):
        for cookie in cookies_list:
            if hasattr(page, "set") and hasattr(page.set, "cookies"):
                page.set.cookies(cookie)
            elif hasattr(page, "set_cookies"):
                page.set_cookies(cookie)

    # localStorage 强绑定域名，需要先进入 search.google.com
    page.get('https://search.google.com/')
    ls_dict = auth_data.get('local_storage', {}) if isinstance(auth_data, dict) else {}
    if isinstance(ls_dict, dict):
        for k, v in ls_dict.items():
            page.run_js(f'localStorage.setItem({json.dumps(k)}, {json.dumps(v)});')

    page.get(TARGET_URL)
    page.refresh()
    print("🚀 登录凭证注入完成，正在验证...")
    return True


def get_urls():
    """读取 表格.csv 文件（列名：网址）"""
    file_path = input('请输入表格.csv文件路径：')
    if not file_path:
        file_path = '表格.csv'
    while 1:
        file_path = file_path.strip('"')
        if not os.path.exists(os.path.abspath(file_path)):
            file_path = input('文件不存在或路径错误，请重新输入：\n')
        else:
            break

    # 兼容常见编码：utf-8-sig / gbk
    last_err = None
    for enc in ('utf-8-sig', 'gbk', 'utf-8'):
        try:
            with open(file_path, 'r', encoding=enc, newline='') as f:
                reader = csv.DictReader(f)
                urls = []
                for row in reader:
                    u = (row.get('网址') or '').strip()
                    if u:
                        urls.append(u)
                print(f'已读取 URL 数量：{len(urls)}，开始逐条处理...')
                return urls
        except Exception as e:
            last_err = e
    raise last_err


def write_report(rows: list[dict], filename: str | None = None) -> str:
    """
    输出报告 CSV：url、是否请求成功、失败原因
    - 编码：utf-8-sig（Excel 直接打开不乱码）
    """
    ts = time.strftime('%Y%m%d_%H%M%S', time.localtime())
    if not filename:
        filename = f'gsc_report_{ts}.csv'
    fields = ['url', '是否请求成功', '失败原因']
    with open(filename, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, '') for k in fields})
    return filename


def safe_click_last(selector_text, by_js: bool = True):
    """安全点击最后一个元素（找不到不报错）"""
    try:
        btns = cp.eles(selector_text)
        if btns:
            btns[-1].click(by_js=by_js)
            return True
    except Exception:
        pass
    return False


def close_popups(skip_on_oops: bool = False, aggressive_close: bool = True):
    """
    关闭可能遮挡输入框/按钮的弹窗。
    :return:
      - 2 表示出现“糟糕！出了点问题”（本次请求已给出反馈但异常），关闭后应直接跳过当前 URL
      - 1 表示已出现“超出配额”，建议停止后续任务
      - 0 表示正常/仅做了常规关闭
    """
    return close_popups_with_timeout(skip_on_oops=skip_on_oops, timeout=1, aggressive_close=aggressive_close)


def close_popups_with_timeout(skip_on_oops: bool, timeout: float, aggressive_close: bool = True):
    """与 close_popups 相同，但允许在高频轮询场景传入更小的 timeout。"""
    try:
        if cp.wait.ele_displayed('@tx()=糟糕！出了点问题', timeout):
            # 只在“确认结果/提交请求”等关键阶段打印，避免每条 URL 开始清理弹窗时刷屏
            if skip_on_oops:
                print('检测到弹窗：糟糕！出了点问题（已关闭）')
            safe_click_last('tx:关闭')
            # 只有在“确认结果/提交请求”阶段才把它当作本次请求的最终反馈；
            # 在输入下一条 URL 前，它更可能是上一条残留弹窗，此时不应跳过本条。
            return 2 if skip_on_oops else 0
    except Exception:
        pass

    # 配额弹窗：优先处理
    try:
        # 配额弹窗：只在 dialog/弹窗层内判断，避免误把页面其它区域的“超出/配额”文本当作配额弹窗
        # 兼容不同文案（可能是“超出了配额 / 超出配额 / 已超出...配额”等）
        xp_quota_dialog = (
            "xpath://*[( @role='dialog' or @aria-modal='true' or contains(@class,'dialog') )]"
            "//*[contains(normalize-space(.),'超出') and contains(normalize-space(.),'配额')]"
        )
        if cp.wait.ele_displayed(xp_quota_dialog, timeout) or cp.wait.ele_displayed('@tx()=超出了配额', timeout):
            # 配额属于“全局终止”事件：无论在哪个阶段检测到，都应打印出来
            print('当日超出配额（停止后续任务）')
            safe_click_last('tx:关闭')
            return 1
    except Exception:
        pass

    # 常见错误弹窗（“出了点问题”）
    try:
        if cp.wait.ele_displayed('@tx()=出了点问题', timeout):
            if skip_on_oops:
                print('检测到弹窗：出了点问题（已关闭）')
            safe_click_last('tx:关闭')
    except Exception:
        pass

    # 其他常见确认弹窗（有时是“知道了”，有时只有“关闭”）
    # 注意：在“提交索引请求等待反馈”阶段，不能无脑点关闭，否则可能把“已请求编入索引”的成功弹窗提前关掉。
    if aggressive_close:
        safe_click_last('tx:知道了')
        safe_click_last('tx:关闭')
    return 0


def get_url_input():
    """每次现取 URL 输入框，避免复用旧元素句柄导致“元素对象已失效”"""
    return cp.ele('x://input[@type="text"]')

def any_dialog_text_displayed_contains(text: str) -> bool:
    """仅在对话框/弹窗层里查找文案（避免页面其他区域的同文案误命中）。"""
    try:
        xp = (
            "xpath://*[( @role='dialog' or @aria-modal='true' or contains(@class,'dialog') )]"
            f"//*[contains(normalize-space(.), {json.dumps(text)})]"
        )
        return bool(cp.wait.ele_displayed(xp, 0.2))
    except Exception:
        return False


def wait_result():
    """
    :return: 1,已录入；2，尚未收到；-1，超时未识别到结果
    """
    print('确认录入结果')
    # 按 searchGoogle.py 的逻辑：刷新 -> 判断“已收录/未收录”两种文案
    for _ in range(5):
        cp.refresh()
        pop = close_popups_with_timeout(skip_on_oops=True, timeout=0.2, aggressive_close=True)
        if pop == 1:
            return -1
        if pop == 2:
            return 0
        record = cp.wait.ele_displayed('@tx()=网址已收录到 Google', 1)
        if record:
            print('已收录 ~')
            return 1
        not_yet = cp.wait.ele_displayed('@tx()=网址尚未收录到 Google', 1)
        if not_yet:
            print('未收录，准备提交 ~')
            return 2
        time.sleep(1)
    else:
        return -1


def _safe_filename_part(s: str, max_len: int = 80) -> str:
    """把 URL/文本变成适合做文件名的一段（尽量可读）。"""
    out = []
    for ch in s:
        if ch.isalnum():
            out.append(ch)
        else:
            out.append('_')
    p = ''.join(out).strip('_')
    if len(p) > max_len:
        p = p[:max_len].rstrip('_')
    return p or 'item'

def ensure_success_shots_dir() -> str:
    """确保成功截图目录存在。"""
    global SUCCESS_SHOTS_DIR
    if SUCCESS_SHOTS_DIR:
        try:
            os.makedirs(SUCCESS_SHOTS_DIR, exist_ok=True)
        except Exception:
            pass
        return SUCCESS_SHOTS_DIR
    ts = time.strftime('%Y%m%d_%H%M%S', time.localtime())
    SUCCESS_SHOTS_DIR = f'success_shots_{ts}'
    try:
        os.makedirs(SUCCESS_SHOTS_DIR, exist_ok=True)
    except Exception:
        pass
    return SUCCESS_SHOTS_DIR

def ensure_failure_shots_dir() -> str:
    """确保失败截图目录存在。"""
    global FAILURE_SHOTS_DIR
    if FAILURE_SHOTS_DIR:
        try:
            os.makedirs(FAILURE_SHOTS_DIR, exist_ok=True)
        except Exception:
            pass
        return FAILURE_SHOTS_DIR
    ts = time.strftime('%Y%m%d_%H%M%S', time.localtime())
    FAILURE_SHOTS_DIR = f'failure_shots_{ts}'
    try:
        os.makedirs(FAILURE_SHOTS_DIR, exist_ok=True)
    except Exception:
        pass
    return FAILURE_SHOTS_DIR

def screenshot_success(url: str):
    """成功时截图留证（截图包含“已请求编入索引”弹窗）。"""
    try:
        folder = ensure_success_shots_dir()
        ts = int(time.time())
        fn = os.path.join(folder, f"success_{ts}_{_safe_filename_part(url)}.png")
        cp.get_screenshot(fn)
        print(f'成功截图已保存：{fn}')
    except Exception:
        # 截图失败不影响主流程
        pass

def screenshot_failure(url: str, reason: str):
    """失败时截图留证（例如：请求遭拒）。"""
    try:
        folder = ensure_failure_shots_dir()
        ts = int(time.time())
        fn = os.path.join(folder, f"fail_{ts}_{_safe_filename_part(reason, 24)}_{_safe_filename_part(url)}.png")
        cp.get_screenshot(fn)
        print(f'失败截图已保存：{fn}')
    except Exception:
        pass


def wait_submit_res(url: str):
    record_btn = cp.eles('@tx()=请求编入索引')
    if record_btn:
        # 用换行 + flush，避免控制台看起来像“卡住”
        print('提交 ...', flush=True)
        record_btn[-1].click(by_js=True)
        # 点击后状态不会立刻出现，先给页面一点时间进入“正在测试/弹窗反馈”状态
        time.sleep(1)
    else:
        print(f'未找到提“请求编入索引”按钮')
        return {"request_success": False, "failure_reason": "未找到“请求编入索引”按钮", "stop_all": False}

    # 关键：先等“正在测试实际网址可否编入索引”（带“取消”按钮）阶段结束，再判定成功/失败。
    start = time.time()
    last_progress = 0.0
    max_wait_s = 120.0  # 最多等约 2 分钟
    poll_s = 0.5
    progress_every_s = 10.0
    while time.time() - start < max_wait_s:
        elapsed = time.time() - start
        # 0) 任何时刻都优先处理“超出配额 / 糟糕”等终止类弹窗（优先级高于“正在测试中”）
        pop = close_popups_with_timeout(skip_on_oops=True, timeout=0.2, aggressive_close=False)
        if pop == 1:
            return {"request_success": False, "failure_reason": "超出配额", "stop_all": True}
        if pop == 2:
            print('索引请求：失败（糟糕！出了点问题）')
            return {"request_success": False, "failure_reason": "糟糕！出了点问题", "stop_all": False}

        # 1) 仍在测试中：继续等待（不要做 success 判定）
        if (
            cp.wait.ele_displayed('@tx()=正在测试实际网址可否编入索引', 0.2)
            or any_dialog_text_displayed_contains('正在测试实际网址可否编入索引')
            or any_dialog_text_displayed_contains('这可能需要花费')
            or any_dialog_text_displayed_contains('取消')
        ):
            if elapsed - last_progress >= progress_every_s:
                print(f'索引请求：正在测试中（已等待 {int(elapsed)}s）')
                last_progress = elapsed
            time.sleep(poll_s)
            continue

        # 2) 拒绝
        if any_dialog_text_displayed_contains('索引编制请求遭拒') or cp.wait.ele_displayed('@tx()=索引编制请求遭拒', 0.2):
            print('索引请求：失败（请求遭拒）')
            # 先截图留证，再关闭弹窗
            screenshot_failure(url, '请求遭拒')
            safe_click_last('tx:关闭')
            return {"request_success": False, "failure_reason": "请求遭拒", "stop_all": False}

        # 3) 成功：必须在同一个对话框里“精确命中标题 + 存在关闭按钮”
        try:
            xp_ok = (
                "xpath://*[( @role='dialog' or @aria-modal='true' )]"
                "//*[normalize-space(.)='已请求编入索引']"
                "/ancestor::*[( @role='dialog' or @aria-modal='true' )][1]"
                "//*[normalize-space(.)='关闭' or normalize-space(.)='知道了']"
            )
            ok = bool(cp.wait.ele_displayed(xp_ok, 0.2))
        except Exception:
            ok = False
        if ok:
            print('索引请求：成功（已请求编入索引）')
            # 先截图留证，再关闭弹窗
            screenshot_success(url)
            safe_click_last('tx:知道了')
            safe_click_last('tx:关闭')
            return {"request_success": True, "failure_reason": "", "stop_all": False}

        # 4) 本轮没命中任何状态：稍等再看
        time.sleep(poll_s)

    # 超时：视为明确失败（给出原因 + 截图留证）
    try:
        ts = int(time.time())
        fn = f"submit_timeout_{ts}_{_safe_filename_part(url)}.png"
        cp.get_screenshot(fn)
        print(f'索引请求：失败（超时未拿到反馈），已截图 {fn}')
        return {"request_success": False, "failure_reason": f"超时未拿到反馈（已截图 {fn}）", "stop_all": False}
    except Exception:
        print('索引请求：失败（超时未拿到反馈）')
        return {"request_success": False, "failure_reason": "超时未拿到反馈", "stop_all": False}


def check_url(url):
    last_step = 'start'
    try:
        # flush=True：避免“没换行导致看起来卡很久”的错觉
        print(f'url:{url}', end='', flush=True)

        # 每条 URL 开始前刷新一次，尽量清掉上一条留下的遮罩/弹窗/旧元素状态
        # 注意：这里是在“准备输入下一条 URL”之前 refresh，不会影响已提交的上一条结果。
        last_step = 'pre_refresh'
        try:
            cp.refresh()
            cp.wait.doc_loaded()
        except Exception:
            # 刷新失败不影响继续，后续仍会尝试清弹窗与输入
            pass

        # 处理上一条残留弹窗，避免第二条无法聚焦输入框
        last_step = 'close_popups(before)'
        pop = close_popups(skip_on_oops=False, aggressive_close=True)
        if pop == 1:
            return {"url": url, "是否请求成功": "否", "失败原因": "超出配额（前置弹窗）", "stop_all": True}

        last_step = 'get_url_input(1)'
        url_input = get_url_input()
        if url_input:
            ac = Actions(cp)
            last_step = 'url_input.click(1)'
            url_input.click()
            # 某些弹窗会在点击后才浮出，抢走焦点；再关一次并重新聚焦
            last_step = 'close_popups(after_click)'
            pop = close_popups(skip_on_oops=False, aggressive_close=True)
            if pop == 1:
                return {"url": url, "是否请求成功": "否", "失败原因": "超出配额（点击输入框后弹窗）", "stop_all": True}
            last_step = 'get_url_input(2)'
            url_input = get_url_input()
            if not url_input:
                print('未找到输入框')
                return {"url": url, "是否请求成功": "否", "失败原因": "未找到输入框", "stop_all": False}
            last_step = 'url_input.click(2)'
            url_input.click()
            # 全选清空再输入（第二条开始更稳）
            last_step = 'ctrl+a'
            ac.key_down(Keys.CTRL).type('a').key_up(Keys.CTRL)
            last_step = 'type(url)'
            ac.type(url)
            time.sleep(1)
            last_step = 'press(enter)'
            ac.key_down(Keys.ENTER)
            print(f'已键入')
            # 键入后先稍等，让 GSC 进入检测流程；再 refresh 一次把最新状态刷出来
            time.sleep(2)
            try:
                cp.refresh()
            except Exception:
                pass
            last_step = 'wait.doc_loaded'
            cp.wait.doc_loaded()

        last_step = 'wait_result'
        result = wait_result()
        if result == 1:
            return {"url": url, "是否请求成功": "无需（已收录）", "失败原因": "", "stop_all": False}
        elif result == 2:
            last_step = 'wait_submit_res'
            submit = wait_submit_res(url)
            if submit.get("request_success"):
                return {"url": url, "是否请求成功": "是", "失败原因": "", "stop_all": False}
            # quota
            if submit.get("stop_all"):
                return {"url": url, "是否请求成功": "否", "失败原因": submit.get("failure_reason", "超出配额"), "stop_all": True}
            return {"url": url, "是否请求成功": "否", "失败原因": submit.get("failure_reason", "失败"), "stop_all": False}
        elif result == 0:
            # “糟糕！出了点问题”在确认结果阶段出现，视为失败并进入下一条
            return {"url": url, "是否请求成功": "否", "失败原因": "糟糕！出了点问题（收录结果阶段）", "stop_all": False}
        else:
            return {"url": url, "是否请求成功": "否", "失败原因": "未识别到收录结果（超时/页面未刷新出结果）", "stop_all": False}
    except Exception as e:
        print(f'未知异常（step={last_step}），继续后面的请求:\n{e}')
        return {"url": url, "是否请求成功": "否", "失败原因": f"异常(step={last_step}): {type(e).__name__}: {e}", "stop_all": False}


# 初始化浏览器（单独启动，不依赖远程端口）
co = ChromiumOptions()
co.set_argument('--start-maximized')
print('初始化浏览器...')
cp = ChromiumPage(addr_or_opts=co)
print('浏览器初始化正常 ...')


def main():
    try:
        # 每次运行创建一个成功截图目录（仅成功时会写文件）
        ensure_success_shots_dir()
        ensure_failure_shots_dir()

        # 先访问目标页，再判断是否需要注入（避免“本来已登录”却被旧快照覆盖）
        cp.get(TARGET_URL)
        logged_in = check_login(cp)
        if logged_in:
            print('已登录')
        else:
            ok = inject_auth(cp)
            if ok and check_login(cp):
                print("登录成功！")
            else:
                save_login_data(cp)
                cp.get(TARGET_URL)

        # 进入“网址检查”页面（不强依赖 id 参数）
        base_url = 'https://search.google.com/search-console/inspect?resource_id=' + PROPERTY_URL
        cp.get(base_url)
        cp.wait.doc_loaded()
        if cp.wait.ele_displayed('@tx()=出了点问题', 1):
            safe_click_last('tx:关闭')

        urls = get_urls()
        rows: list[dict] = []
        for url in urls:
            r = check_url(url)
            rows.append({"url": r.get("url", url), "是否请求成功": r.get("是否请求成功", ""), "失败原因": r.get("失败原因", "")})
            if r.get("stop_all"):
                print('已超出配额，停止后续任务。')
                break

        report_file = write_report(rows)
        ok_cnt = sum(1 for x in rows if x.get('是否请求成功') == '是')
        no_need_cnt = sum(1 for x in rows if str(x.get('是否请求成功', '')).startswith('无需'))
        fail_cnt = len(rows) - ok_cnt - no_need_cnt
        print(f'📄 报告已生成：{report_file}')
        print(f'汇总：成功请求 {ok_cnt} 条；无需请求(已收录) {no_need_cnt} 条；失败 {fail_cnt} 条；总计 {len(rows)} 条')
    finally:
        try:
            cp.quit()
        except Exception:
            pass


if __name__ == '__main__':
    main()