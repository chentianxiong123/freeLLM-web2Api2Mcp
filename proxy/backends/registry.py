"""Backend 注册。"""

from __future__ import annotations

import os

from backends.deepseek_web import DeepSeekWebBackend
from backends.qwen_web import QwenWebBackend

from backends.base import BaseBackend

_BACKENDS: dict[str, BaseBackend] = {
    "deepseek": DeepSeekWebBackend(),
    "qwen": QwenWebBackend(),
}


def get_backend(backend_id: str | None = None) -> BaseBackend:
    if backend_id:
        bid = backend_id.strip().lower()
    else:
        import config as _config
        cfg = _config.load_config()
        bid = (cfg.get("backend") or os.environ.get("WEB_BACKEND", "deepseek")).strip().lower()
    if bid not in _BACKENDS:
        bid = "deepseek"
    return _BACKENDS[bid]


def list_backends() -> list[dict]:
    return [{"id": b.id, "display_name": b.display_name} for b in _BACKENDS.values()]