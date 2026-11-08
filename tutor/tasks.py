"""轮询任务：提交即返回 task_id，后台串行执行，客户端轮询结果。

「并发靠轮询」（用户确认）：多个消费者可同时提交任务（挂着轮询），
但服务端严格串行（scheduler.queue，一次一个）——体验并发，实际串行。
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any

from tutor.scheduler import scheduler

_TTL = 3600.0  # 任务结果保留 1h


class TaskStore:
    """task_id → {status, result, error, ts}，TTL 回收。"""

    def __init__(self, ttl: float = _TTL) -> None:
        self._ttl = ttl
        self._tasks: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def create(self) -> str:
        tid = uuid.uuid4().hex[:16]
        with self._lock:
            self._tasks[tid] = {"status": "pending", "result": None, "error": "", "ts": time.time()}
            if len(self._tasks) > 4096:
                self._gc()
        return tid

    def update(self, tid: str, **kw: Any) -> None:
        with self._lock:
            task = self._tasks.get(tid)
            if task is not None:
                task.update(kw)
                task["ts"] = time.time()

    def get(self, tid: str) -> dict[str, Any] | None:
        with self._lock:
            task = self._tasks.get(tid)
            if task is None:
                return None
            if time.time() - task["ts"] > self._ttl:
                del self._tasks[tid]
                return None
            return {k: v for k, v in task.items() if k != "ts"}

    def _gc(self) -> None:
        now = time.time()
        expired = [k for k, t in self._tasks.items() if now - t["ts"] > self._ttl]
        for k in expired:
            del self._tasks[k]


task_store = TaskStore()


def submit(platform: str, prompt: str, consumer: str = "") -> str:
    """提交一个提问任务：返回 task_id，后台串行执行。"""
    tid = task_store.create()
    threading.Thread(
        target=_run,
        args=(tid, platform, prompt, consumer),
        daemon=True,
        name=f"task-{tid}",
    ).start()
    return tid


def _run(tid: str, platform: str, prompt: str, consumer: str) -> None:
    """后台执行：严格串行（scheduler.queue），结果写回 task。"""
    task_store.update(tid, status="running")
    try:
        from tutor.ask import ask_llm

        with scheduler.queue:  # 严格串行（绝不并发，与直接 ask 同锁）
            result = ask_llm(platform, prompt, consumer=consumer)
        task_store.update(tid, status="done", result=result)
    except Exception as exc:  # noqa: BLE001 - 失败写回 task（含平台冷却）
        task_store.update(tid, status="error", error=str(exc))


def get_task(tid: str) -> dict[str, Any] | None:
    """轮询任务状态：{status: pending/running/done/error, result, error}。"""
    return task_store.get(tid)
