"""工具调用结果缓冲器

当 Qwen 一次输出多个工具块时，Claude Code 并行发回多个 tool result。
本模块负责：
1. 提前创建缓冲（响应发送前），设定期望数量
2. 缓冲陆续到达的 tool result
3. 全部到齐后合并返回给 Qwen
"""

import asyncio
from dataclasses import dataclass, field


@dataclass
class _PendingBuffer:
    """一个 session 的待处理缓冲。"""
    expected: int = 0
    results: list[dict] = field(default_factory=list)
    event: asyncio.Event = field(default_factory=lambda: asyncio.Event())
    flushed: bool = False


class ToolResultBuffer:
    """asyncio 安全的 tool result 缓冲管理器。"""

    def __init__(self):
        self._buffers: dict[str, _PendingBuffer] = {}

    def create(self, session_id: str, expected: int) -> None:
        """提前创建缓冲（在响应发送前调用）。"""
        if expected <= 1:
            return
        self._buffers[session_id] = _PendingBuffer(expected=expected)
        print(f"[TOOL-BUF] session={session_id[:8]} created, expect={expected}")

    async def add_and_wait(self, session_id: str, tool_result: dict) -> list[dict] | None:
        """添加 tool result 并等待全部到齐。

        返回：
          - list[dict]: 全部到齐时返回所有 results
          - None: 缓冲已 flush（重复请求），调用方应跳过
        """
        buf = self._buffers.get(session_id)
        if buf is None:
            # 没有缓冲 — 单工具场景，直接返回
            return [tool_result]

        if buf.flushed:
            # 已经 flush 了，忽略
            return None

        buf.results.append(tool_result)
        print(f"[TOOL-BUF] session={session_id[:8]} got={len(buf.results)}/{buf.expected}")

        if len(buf.results) >= buf.expected:
            # 全部到齐，唤醒等待者
            buf.flushed = True
            buf.event.set()
            return buf.results

        # 还没到齐，等待
        await buf.event.wait()
        return buf.results


# 全局单例
buffer = ToolResultBuffer()
