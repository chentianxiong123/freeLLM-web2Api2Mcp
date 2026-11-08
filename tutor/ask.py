"""调用编排：单平台提问 / auto 自动挑平台 / 登录检测 / 状态持久化。"""

from __future__ import annotations

import json
import random
import threading
import time

from tutor.browser import BrowserSession
from tutor.config import DATA_DIR, get_interval, get_provider, load_providers
from tutor.driver import WebDriver

STATE_FILE = DATA_DIR / "state.json"

# 风控：提问串行化 + 随机间隔（同一时间只发一个问题）
_last_call = [0.0]
_rate_lock = threading.Lock()


def _rate_limit() -> None:
    """提问前随机等待，保证串行 + 间隔 uniform(min_interval, max_interval)。"""
    lo, hi = get_interval()
    with _rate_lock:
        now = time.monotonic()
        wait = random.uniform(lo, hi) - (now - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.monotonic()


def _state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - 无状态文件则新建
        return {"verified": {}, "login": {}}


def _save(s: dict) -> None:
    STATE_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")


def list_llms() -> list[dict]:
    """全部平台 + 登录态 + 验证态。"""
    s = _state()
    return [
        {
            "key": k,
            "name": p.name,
            "url": p.url,
            "logged_in": bool(s["login"].get(k)),
            "verified": bool(s["verified"].get(k)),
        }
        for k, p in load_providers().items()
    ]


def _open_ready(page, provider) -> None:
    """跳转平台页并等就绪元素。"""
    page.goto(provider.url, wait_until="domcontentloaded", timeout=45000)
    if provider.ready_selector:
        try:
            page.locator(provider.ready_selector).first.wait_for(
                state="visible", timeout=30000
            )
        except Exception:  # noqa: BLE001 - 就绪缺失不阻塞（未登录也能进登录页）
            pass


def _enabled_map() -> dict[str, bool]:
    """供应商启停：已验证+已登录的平台参与轮换。"""
    s = _state()
    return {k: bool(s["verified"].get(k) and s["login"].get(k)) for k in load_providers()}


def ask_llm(platform: str, prompt: str, conversation_id: str = "", consumer: str = "") -> dict:
    """向网页版大模型提问（调度核心）。

    调度（tutor.scheduler，CLIProxyAPI 蓝图）：
    - 缓存路由：key=consumer+platform+hash(prompt) 命中直接返回（不调LLM）
    - 平台选择：auto 时加权轮换（排除冷却/禁用）
    - 会话亲和：consumer+platform → conversation_id 续聊
    - 严格串行：一次一个（绝不并发）
    - 冷却：失败平台冷却（降风控）
    返回 {"answer", "conversation_id", "platform", "cached"}。
    """
    if not prompt.strip():
        raise ValueError("prompt 不能为空")
    from tutor.scheduler import scheduler

    d = scheduler.route(consumer, platform, prompt, enabled=_enabled_map(), weights={})
    if d.cached:
        return {"answer": d.answer, "conversation_id": d.conversation_id,
                "platform": d.platform, "cached": True}
    platform = d.platform
    cid = d.conversation_id or conversation_id
    with scheduler.queue:  # 严格串行（绝不并发）
        try:
            _rate_limit()  # 风控：随机间隔
            provider = get_provider(platform)
            bs = BrowserSession()
            with bs.session() as ctx:
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                _open_ready(page, provider)
                drv = WebDriver(page, provider)
                if cid:
                    drv.resume(cid)
                else:
                    drv.new_chat()
                drv.send(prompt)
                answer = drv.wait_answer(prompt, timeout=90.0)
                result_cid = cid or drv.current_cid()
            scheduler.commit(consumer, platform, prompt, result_cid, answer)
            return {"answer": answer, "conversation_id": result_cid,
                    "platform": platform, "cached": False}
        except Exception as exc:  # noqa: BLE001 - 失败冷却该平台（降风控）
            scheduler.on_error(platform)
            raise


def auto_ask(prompt: str) -> dict:
    """auto：按配置顺序，取已登录+已验证的平台逐个试（兜底）。"""
    if not prompt.strip():
        raise ValueError("prompt 不能为空")
    s = _state()
    candidates = [
        (k, p) for k, p in load_providers().items()
        if s["verified"].get(k) and s["login"].get(k)
    ]
    if not candidates:
        raise RuntimeError("没有已登录且已验证的平台，请先登录并测试")
    last: Exception | None = None
    for key, _ in candidates:
        try:
            return ask_llm(key, prompt)
        except Exception as exc:  # noqa: BLE001 - 试下一个
            last = exc
    raise RuntimeError(f"所有可用平台均失败: {last}")


def check_login(platform: str) -> dict:
    """真实检测平台登录态（打开页面看选择器命中），并持久化。"""
    provider = get_provider(platform)
    bs = BrowserSession()
    with bs.session() as ctx:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        _open_ready(page, provider)
        page.wait_for_timeout(2000)
        d = WebDriver(page, provider)
        logged = d.check_logged_in()
    s = _state()
    s["login"][platform] = logged
    _save(s)
    return {"key": platform, "logged_in": logged, "name": provider.name}


def mark_verified(platform: str) -> None:
    s = _state()
    s["verified"][platform] = True
    _save(s)


def check_all() -> list[dict]:
    """全自动健康检查：连 CDP/持久化浏览器，遍历所有平台检测登录态。

    返回 [{key, name, url, logged_in, error?}]，供一键巡检/启动自动报告。
    """
    results = []
    for key, p in load_providers().items():
        try:
            r = check_login(key)
            results.append({
                "key": key, "name": p.name, "url": p.url,
                "logged_in": bool(r.get("logged_in")),
            })
        except Exception as exc:  # noqa: BLE001 - 单平台失败不中断巡检
            results.append({
                "key": key, "name": p.name, "url": p.url,
                "logged_in": False, "error": str(exc)[:120],
            })
    return results
