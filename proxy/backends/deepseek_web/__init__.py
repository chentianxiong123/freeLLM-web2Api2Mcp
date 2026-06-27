"""DeepSeek 网页端 Backend。"""

from __future__ import annotations

from providers.base import Event
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

    async def _resolve_config(self, cfg: dict, model: str) -> tuple[dict, str]:
        """DeepSeek 特有：自动创建会话。"""
        conversation_id = cfg.get("session_id") or ""
        if not conversation_id:
            token = cfg.get("token")
            sid = await self._protocol.create_conversation(token, model)
            if sid:
                conversation_id = sid
                acc_id = cfg.get("id")
                if acc_id:
                    import accounts as _accounts
                    _accounts.update_account(acc_id, {"session_id": sid})
                else:
                    import session as sess
                    sess.on_new_session(sid, model)
            else:
                raise RuntimeError("创建 DeepSeek 会话失败")
        return cfg, conversation_id

    async def _call_protocol(
        self,
        token: str,
        conversation_id: str,
        messages: list[dict],
        cfg: dict,
        *,
        continuation_id: str | None = None,
        model: str = "",
        thinking_enabled: bool = True,
        search_enabled: bool = False,
    ):
        """DeepSeek 特有：传 headers（含 authorization）。"""
        return await self._protocol.send_message(
            token, conversation_id, messages,
            continuation_id=continuation_id,
            model=model,
            thinking_enabled=thinking_enabled,
            search_enabled=search_enabled,
            headers=cfg.get("headers"),
        )

    def get_provider(self):
        return self._protocol

    def supported_models(self) -> list[str]:
        return ["deepseek-v4-flash", "deepseek-v4-pro"]
