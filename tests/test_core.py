"""单元测试：核心纯逻辑（不依赖浏览器/网络/登录，可 CI 跑）。"""

import re
import tempfile
import os

import pytest

from tutor.config import load_providers, get_browser, get_provider
from tutor.driver import WebDriver


def test_enabled_switch(tmp_path, monkeypatch):
    """供应商启停：set_enabled 持久化 + list_llms 返回 enabled（默认开）。"""
    from tutor import ask

    monkeypatch.setattr(ask, "STATE_FILE", tmp_path / "state.json")
    r = ask.set_enabled("deepseek", False)
    assert r == {"platform": "deepseek", "enabled": False}
    llms = {x["key"]: x for x in ask.list_llms()}
    assert llms["deepseek"]["enabled"] is False
    assert llms["doubao"]["enabled"] is True  # 默认全开
    ask.set_enabled("deepseek", True)
    llms = {x["key"]: x for x in ask.list_llms()}
    assert llms["deepseek"]["enabled"] is True


def test_enabled_map_and_login(tmp_path, monkeypatch):
    """_enabled_map：启停开关(默认开) 且 已登录 才参与轮换。"""
    from tutor import ask

    monkeypatch.setattr(ask, "STATE_FILE", tmp_path / "state.json")
    # 未登录 → 全 False（login 为空）
    m = ask._enabled_map()
    assert all(v is False for v in m.values())
    # 登录 deepseek + 关 doubao
    s = ask._state()
    s["login"] = {"deepseek": True, "doubao": True}
    s["enabled"] = {"doubao": False}
    ask._save(s)
    m = ask._enabled_map()
    assert m["deepseek"] is True
    assert m["doubao"] is False  # 启停关 → 不参与
    assert m["kimi"] is False  # 未登录 → 不参与
from tutor.lock import ProfileLock


def test_load_providers():
    ps = load_providers()
    assert len(ps) == 6
    assert set(ps) == {"doubao", "deepseek", "kimi", "qwen", "zhipu", "yuanbao"}
    for key, p in ps.items():
        assert p.url.startswith("http"), f"{key} url"
        assert p.name, f"{key} name"


def test_provider_fields():
    ps = load_providers()
    assert ps["deepseek"].input_selector == "textarea"
    assert ps["doubao"].input_selector == '[contenteditable="true"]'
    assert ps["doubao"].supports_image is True
    assert ps["deepseek"].conversation_id_pattern
    assert ps["doubao"].genimage_prefix == "生成图片："


def test_get_provider_unknown():
    with pytest.raises(KeyError):
        get_provider("nope")


def test_browser_setting_default():
    assert get_browser() in ("chrome", "msedge", "chromium")


def test_conversation_url():
    p = load_providers()["deepseek"]
    u = p.conversation_url_fmt.format(base=p.url.rstrip("/"), id="abc-123")
    assert u.endswith("/abc-123")


@pytest.mark.parametrize(
    "key,url,expect",
    [
        ("deepseek", "https://chat.deepseek.com/a/chat/s/abc-123", "abc-123"),
        ("doubao", "https://www.doubao.com/chat/12345", "12345"),
        ("kimi", "https://www.kimi.com/chat/abc-def", "abc-def"),
    ],
)
def test_cid_regex(key, url, expect):
    p = load_providers()[key]
    m = re.search(p.conversation_id_pattern, url)
    assert m, f"{key} 正则未匹配 {url}"
    assert m.group(1) == expect


def test_extract_answer():
    d = WebDriver(None, load_providers()["doubao"])
    ans = d._extract_answer("帮我看看天气 今天晴朗 适合出行", "帮我看看天气")
    assert ans == "今天晴朗 适合出行"


def test_extract_answer_missing_prompt():
    """提问已被清出列表时，返回整段文本。"""
    d = WebDriver(None, load_providers()["doubao"])
    assert d._extract_answer("只有回答", "不存在的提问") == "只有回答"


def test_normalize():
    d = WebDriver(None, load_providers()["doubao"])
    assert d._normalize("a  b\nc") == "a b c"


def test_image_regex():
    p = load_providers()["doubao"]
    assert re.search(p.image_id_pattern, "https://x.com/rc_gen_image/abc~tplv-1")
    assert not re.search(p.image_id_pattern, "https://x.com/plain.jpg")


def test_profile_lock():
    fd, path = tempfile.mkstemp()
    os.close(fd)
    l1 = ProfileLock(path, timeout=1.0)
    l1.acquire()
    l2 = ProfileLock(path, timeout=0.5)
    with pytest.raises(TimeoutError):
        l2.acquire()  # 被 l1 占用，超时
    l1.release()
    l2.acquire()  # l1 释放后可获取
    l2.release()
    os.unlink(path)


def test_mode_default():
    from tutor.config import set_cdp_url, get_mode, set_mode

    set_mode("persistent")
    set_cdp_url("")
    assert get_mode() == "persistent"


def test_mode_invalid():
    from tutor.config import set_mode

    with pytest.raises(ValueError):
        set_mode("bogus")


def test_interval_roundtrip():
    from tutor.config import get_interval, set_interval

    set_interval(3.0, 7.0)
    lo, hi = get_interval()
    assert (lo, hi) == (3.0, 7.0)


def test_interval_swapped():
    from tutor.config import get_interval, set_interval

    set_interval(9.0, 2.0)  # hi<lo 自动交换
    lo, hi = get_interval()
    assert lo <= hi
