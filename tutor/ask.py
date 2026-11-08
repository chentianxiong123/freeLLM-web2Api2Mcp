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


def ask_llm(platform: str, prompt: str, conversation_id: str = "") -> dict:
    """向网页版大模型提问，返回 {"answer", "conversation_id", "platform"}。"""
    if not prompt.strip():
        raise ValueError("prompt 不能为空")
    _rate_limit()  # 风控：串行 + 随机间隔
    provider = get_provider(platform)
    bs = BrowserSession()
    with bs.session() as ctx:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        _open_ready(page, provider)
        d = WebDriver(page, provider)
        if conversation_id:
            d.resume(conversation_id)
        else:
            d.new_chat()
        d.send(prompt)
        answer = d.wait_answer(prompt, timeout=90.0)
        cid = conversation_id or d.current_cid()
        return {"answer": answer, "conversation_id": cid, "platform": platform}


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
