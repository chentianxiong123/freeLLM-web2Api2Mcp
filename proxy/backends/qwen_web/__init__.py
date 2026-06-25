"""Qwen 网页端 Backend。"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

from providers.base import Event, ConfigResolver, EventBridge
from backends.base import BaseBackend
from .protocol import QwenProtocol


class QwenWebBackend(BaseBackend):
    id = "qwen"
    display_name = "Qwen Web"
    _default_model = "qwen3.7-max"
    _tool_codec_id = "openai_json"

    def __init__(self, account_config: dict | None = None, app_config: dict | None = None):
        super().__init__(account_config=account_config, app_config=app_config)
        self._protocol = QwenProtocol()

    async def chat(
        self,
        messages: list[dict],
        *,
        model: str,
        account_config: dict | None = None,
        thinking_enabled: bool = True,
        search_enabled: bool = False,
    ) -> AsyncIterator[Event]:
        """Qwen 特有的 chat：会话验证 + 自动创建。"""
        cfg = ConfigResolver.resolve(self._app_config, account_config or self._account_config)
        token = cfg.get("token")
        if not token:
            yield Event("error", {"message": "未配置 Qwen token"})
            return

        actual_model = model or cfg.get("model", self._default_model)
        conversation_id = cfg.get("session_id") or ""

        # 验证会话是否仍有效（Qwen 服务端可能已删除）
        if conversation_id:
            history = await self._protocol.get_history(token, conversation_id)
            if history is None:
                print(f"[Qwen] Chat {conversation_id[:12]}... invalid/deleted, will create new")
                conversation_id = ""
                acc_id = cfg.get("id")
                if acc_id:
                    import accounts as _accounts
                    _accounts.update_account(acc_id, {"session_id": ""})

        # 自动创建会话
        if not conversation_id:
            conversation_id = await self._protocol.create_conversation(token, actual_model)
            if not conversation_id:
                yield Event("error", {"message": "创建 Qwen 会话失败"})
                return
            # 保存到账号
            acc_id = cfg.get("id")
            if acc_id:
                import accounts as _accounts
                _accounts.update_account(acc_id, {"session_id": conversation_id, "model": actual_model})
            import session as _sess
            _sess.register_session(conversation_id, model=actual_model)
            _sess.activate_session(conversation_id)
            print(f"[Qwen] Session {conversation_id[:12]}... created for model={actual_model}")

        # 调用协议
        continuation_id = self._continuation.get_continuation_id(conversation_id)
        gen = await self._protocol.send_message(
            token,
            conversation_id,
            messages,
            continuation_id=continuation_id,
            model=actual_model,
            thinking_enabled=thinking_enabled,
            search_enabled=search_enabled,
        )

        # 桥接事件
        async for ev in EventBridge.bridge(gen):
            if ev.type == "message_id" and isinstance(ev.val, str):
                self._continuation.update(conversation_id, ev.val)
            yield ev

    async def create_session(self, label: str = "", model: str = "") -> str | None:
        """创建 Qwen 会话。"""
        import accounts as _accounts
        acc = _accounts.get_active_account()
        if not acc:
            return None
        token = acc.get("token")
        if not token:
            return None
        actual_model = model or acc.get("model", self._default_model)
        chat_id = await self._protocol.create_conversation(token, actual_model)
        if chat_id:
            _accounts.update_account(acc["id"], {"session_id": chat_id, "model": actual_model})
            import session as _sess
            _sess.register_session(chat_id, label=label, model=actual_model, account_id=acc["id"])
        return chat_id

    async def activate_session(self, session_id: str) -> bool:
        """激活 Qwen 会话（同步到账号）。"""
        cfg = ConfigResolver.resolve(self._app_config, self._account_config)
        acc_id = cfg.get("id")
        if acc_id:
            import accounts as _accounts
            _accounts.update_account(acc_id, {"session_id": session_id})
        return await super().activate_session(session_id)

    async def delete_session(self, session_id: str) -> bool:
        """删除 Qwen 会话（同步到上游 + 账号）。"""
        cfg = ConfigResolver.resolve(self._app_config, self._account_config)
        token = cfg.get("token")
        if token:
            await self._protocol.delete_conversation(token, session_id)
        # 如果删除的是当前账号的 session，清理账号记录
        acc_id = cfg.get("id")
        if acc_id and cfg.get("session_id") == session_id:
            import accounts as _accounts
            _accounts.update_account(acc_id, {"session_id": ""})
        import session as sess
        ok, _ = sess.delete_session(session_id)
        return ok

    def get_provider(self):
        """兼容旧接口。"""
        return self._protocol

    def supported_models(self) -> list[str]:
        return ["qwen3.7-max", "qwen3.0-plus", "qwq-32b"]
