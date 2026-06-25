"""Qwen 上游协议实现。

职责：把 qwen_api.py 的同步 generator 包装成 UpstreamProtocol 接口。
"""

from __future__ import annotations

import asyncio
from typing import Generator

from providers.base import UpstreamProtocol
from . import qwen_api as api


class QwenProtocol(UpstreamProtocol):
    """Qwen 网页端协议。"""

    def authenticate(self, credentials: dict) -> dict | None:
        """Qwen 认证（暂不实现，依赖 accounts.py）。"""
        return credentials.get("token")

    async def create_conversation(self, token: str, model: str) -> str | None:
        """创建 Qwen 会话。"""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, api.create_chat, token, model)

    async def delete_conversation(self, token: str, conversation_id: str) -> bool:
        """删除 Qwen 会话。"""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, api.delete_chat, token, conversation_id)

    async def get_history(self, token: str, conversation_id: str) -> list[dict] | None:
        """获取 Qwen 会话历史。"""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, api.get_chat_history, token, conversation_id)

    async def send_message(
        self,
        token: str,
        conversation_id: str,
        messages: list[dict],
        *,
        continuation_id: str | None = None,
        model: str = "",
        thinking_enabled: bool = True,
        search_enabled: bool = False,
    ) -> Generator:
        """发送消息，返回同步 (etype, val) generator。"""
        has_tools = any(
            m.get("role") in ("tool", "assistant") and "tool_calls" in m
            for m in messages
        )

        # Qwen 的续接点：优先用传入的 continuation_id，否则从 API 缓存获取
        parent_id = continuation_id or api.get_last_message_id(conversation_id)

        loop = asyncio.get_running_loop()
        gen = await loop.run_in_executor(
            None,
            _create_gen,
            token, conversation_id, model, messages, thinking_enabled, search_enabled, has_tools, parent_id,
        )
        return gen


def _create_gen(token, chat_id, model, messages, thinking_enabled, search_enabled, has_tools, parent_id):
    """Helper: 在 executor 中创建同步 generator。"""
    return api.chat_completion(
        token, chat_id, model, messages,
        thinking_enabled=thinking_enabled,
        search_enabled=search_enabled,
        has_tools=has_tools,
        parent_id=parent_id,
    )
