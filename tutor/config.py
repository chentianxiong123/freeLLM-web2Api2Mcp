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
DEFAULT_SETTINGS = {"browser": "chrome", "headless": False}
ALLOWED_BROWSERS = ("chrome", "msedge", "chromium")


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


def profile_dir() -> str:
    """当前浏览器对应的持久化 profile 目录（切换浏览器互不影响）。"""
    name = get_browser()
    return str(PROFILES_DIR / ("chromium" if name == "chromium" else name))
