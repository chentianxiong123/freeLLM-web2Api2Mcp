"""DeepSeek 网页端 Backend。"""

from __future__ import annotations

from typing import AsyncIterator

from providers.base import Event
from .provider import DeepSeekProvider


class DeepSeekWebBackend:
    id = "deepseek"
    display_name = "DeepSeek Web"

    def __init__(self, account_config: dict | None = None, app_config: dict | None = None):
        self._account_config = account_config
        self._provider = DeepSeekProvider(app_config=app_config)

    def _resolve_account(self) -> dict:
        if self._account_config is not None:
            return self._account_config
        import accounts
        return accounts.get_account_config()

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
            account_config=account_config or self._account_config,
            thinking_enabled=thinking_enabled,
            search_enabled=search_enabled,
        ):
            yield ev

    def is_authenticated(self) -> bool:
        cfg = self._resolve_account()
        return bool(cfg.get("token"))

    def active_model(self) -> str:
        if self._account_config is not None:
            return self._account_config.get("model", "deepseek-v4-flash")
        import session as sess
        return sess.get_active_model()