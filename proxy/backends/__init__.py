"""上游网页端 Backend。"""

from backends.base import WebBackend
from backends.registry import get_backend, list_backends

__all__ = ["WebBackend", "get_backend", "list_backends"]