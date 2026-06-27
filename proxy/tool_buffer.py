"""工具调用结果缓冲器

当 Qwen 一次输出多个工具块时，Claude Code 可能并行发回多个 tool result。
本模块负责：
1. 记录上一次响应中发出的工具调用数量
2. 缓冲陆续到达的 tool result
3. 全部到齐后合并返回给 Qwen
"""

import time
import threading
from dataclasses import dataclass, field


@dataclass
class _PendingBuffer:
    """一个 session 的待处理缓冲。"""
    expected: int = 0              # 期望收到的 tool result 数量
    results: list[dict] = field(default_factory=list)  # 已收到的 tool result
    created_at: float = 0.0        # 缓冲创建时间


class ToolResultBuffer:
    """线程安全的 tool result 缓冲管理器。"""

    TIMEOUT_SECONDS = 30  # 等待超时

    def __init__(self):
        self._lock = threading.Lock()
        # session_id → _PendingBuffer
        self._buffers: dict[str, _PendingBuffer] = {}

    def record_tool_calls_sent(self, session_id: str, count: int) -> None:
        """记录上一次响应中发出的工具调用数量。"""
        if count <= 1:
            return  # 单工具不需要缓冲
        with self._lock:
            self._buffers[session_id] = _PendingBuffer(
                expected=count,
                results=[],
                created_at=time.time(),
            )
            print(f"[TOOL-BUF] session={session_id[:8]} expect={count}")

    def add_result(self, session_id: str, tool_result: dict) -> bool:
        """添加一个 tool result。返回 True 表示全部到齐。"""
        with self._lock:
            buf = self._buffers.get(session_id)
            if buf is None:
                # 没有预期缓冲 — 单工具场景，直接放行
                return True

            buf.results.append(tool_result)
            print(f"[TOOL-BUF] session={session_id[:8]} got={len(buf.results)}/{buf.expected}")

            return len(buf.results) >= buf.expected

    def get_and_clear(self, session_id: str) -> list[dict] | None:
        """获取并清空缓冲。返回 None 表示无缓冲。"""
        with self._lock:
            buf = self._buffers.pop(session_id, None)
            if buf is None:
                return None
            return buf.results

    def cleanup_expired(self) -> int:
        """清理超时缓冲，返回清理数量。"""
        now = time.time()
        cleaned = 0
        with self._lock:
            expired = [
                sid for sid, buf in self._buffers.items()
                if now - buf.created_at > self.TIMEOUT_SECONDS
            ]
            for sid in expired:
                del self._buffers[sid]
                cleaned += 1
        if cleaned:
            print(f"[TOOL-BUF] cleaned {cleaned} expired buffers")
        return cleaned


# 全局单例
buffer = ToolResultBuffer()
