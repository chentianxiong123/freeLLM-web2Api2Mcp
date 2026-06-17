"""Mock ChatProvider — 测试用，按脚本返回 Event 序列。

两个变体：
  - ScriptedProvider：按固定列表返回 Event（用于单测边界条件）
  - BashListProvider：永远返回 Bash(ls -la) 的 tool_call（用于端到端 mock server）
"""

import asyncio
from typing import AsyncIterator
from providers.base import Event, ChatProvider, ProviderError


class ScriptedProvider:
    """按预定义 Event 列表返回。

    用于单测：可以精确控制每个 Event 的顺序/类型/内容。
    """
    def __init__(self, events: list[Event], session_id: str = "mock-session-001"):
        self._events = list(events)
        self._session_id = session_id

    async def chat(self, messages, *, model="default", thinking_enabled=True, search_enabled=False) -> AsyncIterator[Event]:
        for ev in self._events:
            # 模拟一点点延迟
            await asyncio.sleep(0)
            yield ev

    def list_sessions(self) -> list[dict]:
        return [{"session_id": self._session_id, "label": "mock", "active": True}]

    def create_session(self) -> str:
        return self._session_id

    def activate_session(self, session_id: str) -> bool:
        return session_id == self._session_id

    def get_active_session(self) -> str:
        return self._session_id


class BashListProvider:
    """永远返回 Bash(Get-ChildItem C:/Users/a1/Desktop) 的 tool_call。

    用于 mock_server.py — 验证 Claude Code 拿到 tool_calls 是否真执行。
    """
    def __init__(self, command: str = "Get-ChildItem -Force C:/Users/a1/Desktop", session_id: str = "mock-bash"):
        self._command = command
        self._session_id = session_id

    async def chat(self, messages, *, model="default", thinking_enabled=True, search_enabled=False) -> AsyncIterator[Event]:
        yield Event("content", "我来")
        yield Event("content", "查")
        yield Event("content", "桌面")
        yield Event("content", "\n\n")
        yield Event("tool_call", {
            "name": "Bash",
            "arguments": {"command": self._command, "description": "列出桌面"},
        })
        yield Event("token_usage", 120)
        yield Event("done", None)

    def list_sessions(self) -> list[dict]:
        return [{"session_id": self._session_id, "label": "mock-bash", "active": True}]

    def create_session(self) -> str:
        return self._session_id

    def activate_session(self, session_id: str) -> bool:
        return session_id == self._session_id

    def get_active_session(self) -> str:
        return self._session_id
