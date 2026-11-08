"""平台配置与全局设置。

数据来源：tutor_platforms_data.json（功能性事实：各网页版平台的选择器/URL/正则，
实测回填，不含任何受版权保护的表达性代码）。本模块只做数据结构定义与加载。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

ROOT: Path = Path(__file__).resolve().parent.parent
DATA_DIR: Path = ROOT / "data"
PROFILES_DIR: Path = DATA_DIR / "profiles"
LOGS_DIR: Path = DATA_DIR / "logs"
PLATFORM_DATA: Path = ROOT / "tutor_platforms_data.json"

for _d in (DATA_DIR, PROFILES_DIR, LOGS_DIR):
    _d.mkdir(parents=True, exist_ok=True)


@dataclass
class Provider:
    """一个网页版平台的配置（全部来自纯数据 JSON）。"""

    key: str = ""
    name: str = ""
    url: str = ""
    verified: bool = False
    input_selector: str = ""
    pick_largest_input: bool = False
    open_new_chat: bool = True
    new_chat_button_text: str = "新对话"
    new_chat_shortcut: str = "Control+j"
    send_enter: bool = True
    send_selector: str = ""
    message_list_selector: str = ""
    exclude_selectors: tuple = ()
    generating_selector: str = '[class*="loading" i]'
    anchor_normalize: bool = True
    answer_max_len: int = 4000
    supports_image: bool = False
    genimage_prefix: str = ""
    fallback_stable_rounds: int = 0
    image_referer: str = ""
    image_id_pattern: str = r"/rc_gen_image/([^?~]+)"
    headless: bool | None = None
    ready_selector: str = ""
    conversation_id_pattern: str = r"/chat/(\d+)"
    conversation_url_fmt: str = "{base}/{id}"
    logged_in_selector: str = ""
    logged_out_selector: str = ""
    answer_selector: str = ""
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_json(cls, key: str, data: dict) -> "Provider":
        p = cls(key=key)
        for k, v in data.items():
            if hasattr(p, k) and k not in ("key",):
                setattr(p, k, v)
        return p


_cache: dict[str, Provider] | None = None


def load_providers() -> dict[str, Provider]:
    """加载全部平台配置（进程内缓存）。"""
    global _cache
    if _cache is None:
        raw = json.loads(PLATFORM_DATA.read_text(encoding="utf-8"))
        _cache = {k: Provider.from_json(k, v) for k, v in raw.items()}
    return _cache


def get_provider(key: str) -> Provider:
    providers = load_providers()
    if key not in providers:
        raise KeyError(f"未知平台: {key}（可用: {', '.join(providers)}）")
    return providers[key]


# ---------------------------------------------------------------------------
# 全局设置（data/settings.json）：浏览器选择 / 无头模式
# ---------------------------------------------------------------------------

SETTINGS_FILE: Path = DATA_DIR / "settings.json"
DEFAULT_SETTINGS = {
    "browser": "chrome",
    "headless": False,
    "mode": "persistent",  # persistent=自带profile / cdp=连真浏览器
    "connect_cdp": "",      # CDP 地址，mode=cdp 时用，如 http://127.0.0.1:9222
    "min_interval": 5.0,     # 提问最小间隔（秒，风控：串行+随机延迟）
    "max_interval": 15.0,    # 提问最大间隔（秒，随机上限）
}
ALLOWED_BROWSERS = ("chrome", "msedge", "chromium")
ALLOWED_MODES = ("persistent", "cdp")


def _settings() -> dict:
    try:
        return {**DEFAULT_SETTINGS, **json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))}
    except Exception:  # noqa: BLE001 - 设置损坏回退默认
        return dict(DEFAULT_SETTINGS)


def _save_settings(s: dict) -> None:
    SETTINGS_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")


def get_browser() -> str:
    return _settings()["browser"]


def set_browser(value: str) -> None:
    if value not in ALLOWED_BROWSERS:
        raise ValueError(f"不支持的浏览器: {value}（可选: {ALLOWED_BROWSERS}）")
    s = _settings()
    s["browser"] = value
    _save_settings(s)


def get_headless() -> bool:
    return bool(_settings()["headless"])


def set_headless(flag: bool) -> None:
    s = _settings()
    s["headless"] = bool(flag)
    _save_settings(s)


def get_cdp_url() -> str:
    """CDP 连接地址；非空 = 连接已打开的真浏览器（复用其登录态）。"""
    return str(_settings().get("connect_cdp", ""))


def set_cdp_url(url: str) -> None:
    s = _settings()
    s["connect_cdp"] = url.strip()
    _save_settings(s)


def get_mode() -> str:
    """运行模式：persistent=自带profile / cdp=连真浏览器。"""
    m = str(_settings().get("mode", "persistent"))
    return m if m in ALLOWED_MODES else "persistent"


def set_mode(value: str) -> None:
    if value not in ALLOWED_MODES:
        raise ValueError(f"不支持的模式: {value}（可选: {ALLOWED_MODES}）")
    s = _settings()
    s["mode"] = value
    _save_settings(s)


def get_interval() -> tuple[float, float]:
    """提问间隔（秒）：(min, max)，每次提问前随机等待，风控降频。"""
    s = _settings()
    lo = float(s.get("min_interval", 5.0))
    hi = float(s.get("max_interval", 15.0))
    if hi < lo:
        lo, hi = hi, lo
    return lo, hi


def set_interval(min_sec: float, max_sec: float) -> None:
    s = _settings()
    s["min_interval"] = float(min_sec)
    s["max_interval"] = float(max_sec)
    _save_settings(s)


def profile_dir() -> str:
    """当前浏览器对应的持久化 profile 目录（切换浏览器互不影响）。"""
    name = get_browser()
    return str(PROFILES_DIR / ("chromium" if name == "chromium" else name))
