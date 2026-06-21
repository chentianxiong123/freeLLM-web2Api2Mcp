"""DeepSeek 网页端 Backend。"""

from __future__ import annotations

from typing import AsyncIterator

import accounts
import session as sess
from providers.base import Event
from .provider import DeepSeekProvider


class DeepSeekWebBackend:
    id = "deepseek"
    display_name = "DeepSeek Web"

    def __init__(self):
        self._provider = DeepSeekProvider()

    def get_provider(self):
        return self._provider

    def tool_codec_id(self) -> str:
        return "deepseek_natural"

    async def chat_turn(
        self,
        user_content: str,
        *,
        model: str,
        account_config: dict | None = None,
        thinking_enabled: bool = True,
        search_enabled: bool = False,
    ) -> AsyncIterator[Event]:
        messages = [{"role": "user", "content": user_content}]
        async for ev in self._provider.chat(
            messages,
            model=model,
            account_config=account_config,
            thinking_enabled=thinking_enabled,
            search_enabled=search_enabled,
        ):
            yield ev

    def is_authenticated(self) -> bool:
        cfg = accounts.get_account_config()
        return bool(cfg.get("token"))

    def active_model(self) -> str:
        return sess.get_active_model()