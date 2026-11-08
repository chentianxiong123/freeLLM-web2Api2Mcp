"""集成测试：需要真实浏览器/网络（默认跳过，用 `pytest -m browser` 手动跑）。"""

import pytest

pytestmark = pytest.mark.browser


def test_browser_start():
    """系统浏览器（复用本机）能启动并释放锁。"""
    from tutor.browser import BrowserSession
    from tutor.config import set_headless

    set_headless(True)
    try:
        bs = BrowserSession()
        with bs.session() as ctx:
            assert ctx is not None
    finally:
        set_headless(False)


def test_check_login():
    """打开平台页检测登录态（不要求已登录）。"""
    from tutor import ask
    from tutor.config import set_headless

    set_headless(True)
    try:
        r = ask.check_login("deepseek")
        assert r["key"] == "deepseek"
        assert "logged_in" in r
    finally:
        set_headless(False)


def test_mcp_list_tool():
    """MCP 工具 list_web_llms 可返回平台列表。"""
    from tutor import ask

    out = ask.list_llms()
    assert len(out) == 6
    assert all({"key", "name", "url", "logged_in", "verified"} <= set(o) for o in out)


def test_cdp_mode():
    """CDP 模式连接真浏览器（需 Chrome --remote-debugging-port=9222）。"""
    from tutor.browser import BrowserSession
    from tutor.config import set_cdp_url, set_headless, set_mode

    set_headless(True)
    set_mode("cdp")
    set_cdp_url("http://127.0.0.1:9222")
    try:
        bs = BrowserSession()
        with bs.session() as ctx:
            assert ctx is not None
    finally:
        set_mode("persistent")
        set_cdp_url("")
        set_headless(False)


def test_rate_limit():
    """频率控制：串行+随机间隔（1~1.5s）。"""
    import time

    from tutor.ask import _rate_limit
    from tutor.config import set_interval

    set_interval(1.0, 1.5)
    _rate_limit()
    t0 = time.monotonic()
    _rate_limit()
    dt = time.monotonic() - t0
    assert 0.8 <= dt <= 2.0, f"间隔异常: {dt}"
