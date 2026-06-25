"""统一 JSON 文件读写。

替代 session.py / accounts.py / rules.py 中重复的 _load/_save 模式。
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Callable


class JsonStore:
    """线程安全的 JSON 文件存储。"""

    def __init__(
        self,
        path: Path,
        default_factory: Callable[[], dict],
        migrate: Callable[[dict], dict] | None = None,
    ):
        """
        Args:
            path: JSON 文件路径
            default_factory: 当文件不存在或解析失败时调用的默认值工厂
            migrate: 可选的数据迁移函数，加载后调用
        """
        self._path = path
        self._default = default_factory
        self._migrate = migrate
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> dict:
        """加载 JSON 文件。"""
        with self._lock:
            if not self._path.exists():
                return self._default()
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return self._default()
            if self._migrate:
                raw = self._migrate(raw)
            return raw

    def save(self, data: dict) -> None:
        """保存 JSON 文件。"""
        with self._lock:
            self._path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
