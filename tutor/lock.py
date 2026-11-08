"""profile 会话锁：多进程互斥（MCP 工具调用 vs 登录窗口）。

基于 flock（POSIX）。同一 profile 目录同时只允许一个进程持有，
避免浏览器持久化上下文冲突。
"""

from __future__ import annotations

import fcntl
import os
import time


class ProfileLock:
    def __init__(self, path: str, timeout: float = 60.0) -> None:
        self.path = path
        self.timeout = timeout
        self._fd: int | None = None

    def acquire(self) -> None:
        self._fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o644)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"获取 profile 锁超时: {self.path}")
                time.sleep(0.5)

    def release(self) -> None:
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            except OSError:
                pass
            os.close(self._fd)
            self._fd = None
