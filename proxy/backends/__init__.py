"""上游网页端 Backend。"""

from backends.base import BaseBackend
from backends.registry import get_backend, list_backends

__all__ = ["BaseBackend", "get_backend", "list_backends"]