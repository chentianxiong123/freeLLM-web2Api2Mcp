"""DeepSeek 网页端 Backend。"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

from providers.base import Event, ConfigResolver
from backends.base import BaseBackend
from .protocol import DeepSeekProtocol


class DeepSeekWebBackend(BaseBackend):
    id = "deepseek"
    display_name = "DeepSeek Web"
    _default_model = "deepseek-v4-flash"
    _tool_codec_id = "deepseek_natural"

    def __init__(self, account_config: dict | None = None, app_config: dict | None = None):
        super().__init__(account_config=account_config, app_config=app_config)
        self._protocol = DeepSeekProtocol()

    async def chat(
        self,
        messages: list[dict],
        *,
        model: str,
        account_config: dict | None = None,
        thinking_enabled: bool = True,
        search_enabled: bool = False,
    ) -> AsyncIterator[Event]:
        """DeepSeek 特有的 chat：自动创建会话。"""
        cfg = ConfigResolver.resolve(self._app_config, account_config or self._account_config)
        token = cfg.get("token")
        if not token:
            yield Event("error", {"message": "未登录 DeepSeek"})
            return

        # DeepSeek 需要先有会话才能发消息
        conversation_id = cfg.get("session_id") or ""
        if not conversation_id:
            sid = await self._protocol.create_conversation(token, model)
            if sid:
                conversation_id = sid
                # 保存到账号
                acc_id = cfg.get("id")
                if acc_id:
                    import accounts as _accounts
                    _accounts.update_account(acc_id, {"session_id": sid})
                else:
                    import session as sess
                    sess.on_new_session(sid, model)
            else:
                yield Event("error", {"message": "创建 DeepSeek 会话失败"})
                return

        # 调用协议
        continuation_id = self._continuation.get_continuation_id(conversation_id)
        gen = await self._protocol.send_message(
            token,
            conversation_id,
            messages,
            continuation_id=continuation_id,
            model=model,
            thinking_enabled=thinking_enabled,
            search_enabled=search_enabled,
        )

        # 桥接事件
        from providers.base import EventBridge
        async for ev in EventBridge.bridge(gen):
            if ev.type == "message_id" and isinstance(ev.val, str):
                self._continuation.update(conversation_id, ev.val)
            yield ev

    def get_provider(self):
        """兼容旧接口。"""
        return self._protocol

    def supported_models(self) -> list[str]:
        return ["deepseek-v4-flash", "deepseek-v4-pro"]
