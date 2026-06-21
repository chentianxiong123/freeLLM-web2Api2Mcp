"""Backend 注册。"""

from __future__ import annotations

import os

from backends.deepseek_web import DeepSeekWebBackend

_BACKENDS: dict[str, DeepSeekWebBackend] = {
    "deepseek": DeepSeekWebBackend(),
}


def get_backend(backend_id: str | None = None) -> DeepSeekWebBackend:
    bid = (backend_id or os.environ.get("WEB_BACKEND", "deepseek")).strip().lower()
    if bid not in _BACKENDS:
        bid = "deepseek"
    return _BACKENDS[bid]


def list_backends() -> list[dict]:
    return [{"id": b.id, "display_name": b.display_name} for b in _BACKENDS.values()]