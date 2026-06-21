"""上游网页端协议。

每个 Backend 绑定：
- ToolCodec：解析助手输出中的工具调用（DeepSeek 暗语等）
- ChatProvider：实际 HTTP/SSE 对话
- init_prompt：发给网页端的系统说明（tool_config）
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Protocol, runtime_checkable

from providers.base import Event


@runtime_checkable
class WebBackend(Protocol):
    id: str
    display_name: str

    def get_provider(self) -> Any:
        """返回 ChatProvider 实例。"""
        ...

    def tool_codec_id(self) -> str:
        """如 deepseek_natural / openai_json。"""
        ...

    async def chat_turn(
        self,
        user_content: str,
        *,
        model: str,
        account_config: dict | None = None,
        thinking_enabled: bool = True,
        search_enabled: bool = False,
    ) -> AsyncIterator[Event]:
        """只发一条 user 消息（续接由 session/parent 负责）。"""
        ...

    def is_authenticated(self) -> bool:
        ...

    def active_model(self) -> str:
        ...