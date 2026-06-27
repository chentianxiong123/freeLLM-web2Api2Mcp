"""Qwen 网页端 Backend。"""

from __future__ import annotations

from providers.base import Event, ConfigResolver
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

    async def _resolve_config(self, cfg: dict, model: str) -> tuple[dict, str]:
        """Qwen 特有：验证会话 + 自动创建。"""
        token = cfg.get("token")
        actual_model = model or cfg.get("model", self._default_model)
        conversation_id = cfg.get("session_id") or ""

        # 验证会话是否仍有效
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
                raise RuntimeError("创建 Qwen 会话失败")
            acc_id = cfg.get("id")
            if acc_id:
                import accounts as _accounts
                _accounts.update_account(acc_id, {"session_id": conversation_id, "model": actual_model})
            import session as _sess
            _sess.register_session(conversation_id, model=actual_model)
            _sess.activate_session(conversation_id)
            print(f"[Qwen] Session {conversation_id[:12]}... created for model={actual_model}")

        return cfg, conversation_id

    async def activate_session(self, session_id: str) -> bool:
        cfg = ConfigResolver.resolve(self._app_config, self._account_config)
        acc_id = cfg.get("id")
        if acc_id:
            import accounts as _accounts
            _accounts.update_account(acc_id, {"session_id": session_id})
        return await super().activate_session(session_id)

    async def delete_session(self, session_id: str) -> bool:
        cfg = ConfigResolver.resolve(self._app_config, self._account_config)
        token = cfg.get("token")
        if token:
            await self._protocol.delete_conversation(token, session_id)
        acc_id = cfg.get("id")
        if acc_id and cfg.get("session_id") == session_id:
            import accounts as _accounts
            _accounts.update_account(acc_id, {"session_id": ""})
        import session as sess
        ok, _ = sess.delete_session(session_id)
        return ok

    def get_provider(self):
        return self._protocol

    def supported_models(self) -> list[str]:
        return ["qwen3.7-max", "qwen3.0-plus", "qwq-32b"]
