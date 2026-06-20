"""单账号配置管理（取代 deepseek-free-api 的多账号 ConfigManager）"""

import json
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.json"

DEFAULT_CONFIG = {
    "token": "",
    "session_id": "",
    "headers": {},
    "cookie": "",
    "login_type": "",
    "_password": "",
    "_email": "",
    "_mobile": "",
    "_area_code": "+86",
    "port": 48391,
    "thinking_enabled": True,
    "proxy": "",
    "account_label": "default",
    "terminal": "powershell",  # cmd / powershell / bash
    "model": "deepseek-v4-flash",  # deepseek-v4-flash / deepseek-v4-pro
}


def load_config() -> dict:
    """加载配置，不存在则返回默认值。"""
    if not CONFIG_PATH.exists():
        return dict(DEFAULT_CONFIG)
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return {**DEFAULT_CONFIG, **data}
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULT_CONFIG)


def save_config(cfg: dict) -> None:
    """保存配置到文件。"""
    CONFIG_PATH.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def update_config(**kwargs) -> dict:
    """更新配置项并持久化。"""
    cfg = load_config()
    cfg.update(kwargs)
    save_config(cfg)
    return cfg


def get_cfg() -> dict:
    """获取当前配置缓存。"""
    return load_config()
