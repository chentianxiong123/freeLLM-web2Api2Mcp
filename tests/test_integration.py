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
