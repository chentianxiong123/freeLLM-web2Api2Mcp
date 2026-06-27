"""Backend 基类。

职责：上游适配器的公共逻辑。
- chat_turn: 发一条 user 消息（续接由 ContinuationState 负责）
- is_authenticated: 认证状态
- active_model: 当前模型
- session 生命周期: 委托给 session.py
"""

from __future__ import annotations

from typing import AsyncIterator

from providers.base import Event, ContinuationState, ConfigResolver, EventBridge


class BaseBackend:
    """Backend 基类。所有上游适配器继承这个类。"""

    id: str = ""
    display_name: str = ""
    _default_model: str = ""
    _tool_codec_id: str = "deepseek_natural"

    def __init__(self, account_config: dict | None = None, app_config: dict | None = None):
        self._account_config = account_config
        self._app_config = app_config
        self._continuation = ContinuationState()
        self._protocol = None  # 子类设置（UpstreamProtocol 实现）

    def get_protocol(self):
        """返回上游协议实现。"""
        return self._protocol

    def tool_codec_id(self) -> str:
        """工具格式 ID（如 deepseek_natural / openai_json）。"""
        return self._tool_codec_id

    async def chat_turn(
        self,
        user_content: str,
        *,
        model: str,
        account_config: dict | None = None,
        thinking_enabled: bool = True,
        search_enabled: bool = False,
        system_prompt: str = "",
    ) -> AsyncIterator[Event]:
        """发一条 user 消息，返回事件流。

        续接由 ContinuationState 自动管理。
        system_prompt: 可选的系统提示词，会作为 system message 发送给上游。
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_content})
        async for ev in self.chat(
            messages,
            model=model,
            account_config=account_config,
            thinking_enabled=thinking_enabled,
            search_enabled=search_enabled,
        ):
            yield ev

    async def chat(
        self,
        messages: list[dict],
        *,
        model: str,
        account_config: dict | None = None,
        thinking_enabled: bool = True,
        search_enabled: bool = False,
    ) -> AsyncIterator[Event]:
        """发送对话请求，返回标准事件流。

        续接由本方法自动管理，子类不需要处理。
        子类可覆盖 _resolve_config() 和 _call_protocol() 添加自定义逻辑。
        """
        cfg = ConfigResolver.resolve(self._app_config, account_config or self._account_config)
        token = cfg.get("token")
        if not token:
            yield Event("error", {"message": f"未配置 {self.display_name} token"})
            return

        # 子类可覆盖：验证/创建会话、修改 cfg
        try:
            cfg, conversation_id = await self._resolve_config(cfg, model)
        except RuntimeError as e:
            yield Event("error", {"message": str(e)})
            return

        # 自动获取续接点
        continuation_id = self._continuation.get_continuation_id(conversation_id)

        # 子类可覆盖：实际调用上游 API
        gen = await self._call_protocol(
            token, conversation_id, messages, cfg,
            continuation_id=continuation_id,
            model=model or cfg.get("model", self._default_model),
            thinking_enabled=thinking_enabled,
            search_enabled=search_enabled,
        )

        # 桥接事件 + 自动更新续接点
        async for ev in EventBridge.bridge(gen):
            if ev.type == "message_id" and isinstance(ev.val, str):
                self._continuation.update(conversation_id, ev.val)
            yield ev

    async def _resolve_config(self, cfg: dict, model: str) -> tuple[dict, str]:
        """子类覆盖：验证/创建会话，返回 (cfg, conversation_id)。

        默认实现：直接从 cfg 取 session_id。
        """
        return cfg, cfg.get("session_id") or ""

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
        """子类覆盖：实际调用 self._protocol.send_message()。

        默认实现：直接调用协议。
        """
        return await self._protocol.send_message(
            token, conversation_id, messages,
            continuation_id=continuation_id,
            model=model,
            thinking_enabled=thinking_enabled,
            search_enabled=search_enabled,
        )

    # ── session 生命周期（委托给 session.py）──────────────

    async def list_sessions(self) -> list[dict]:
        import session as sess
        return sess.list_sessions()

    async def create_session(self, label: str = "", model: str = "") -> str | None:
        """创建新会话。通过 self._protocol.create_conversation() 调用上游 API。"""
        if not self._protocol:
            return None
        import accounts as _accounts
        acc = _accounts.get_active_account()
        if not acc:
            return None
        token = acc.get("token")
        if not token:
            return None
        actual_model = model or acc.get("model", self._default_model)
        sid = await self._protocol.create_conversation(token, actual_model)
        if sid:
            _accounts.update_account(acc["id"], {"session_id": sid, "model": actual_model})
            import session as _sess
            _sess.register_session(sid, label=label, model=actual_model, account_id=acc["id"])
        return sid

    async def activate_session(self, session_id: str) -> bool:
        import session as sess
        ok = sess.activate_session(session_id)
        if ok:
            self._continuation.reset(session_id)
        return ok

    async def delete_session(self, session_id: str) -> bool:
        import session as sess
        ok, _ = sess.delete_session(session_id)
        return ok

    async def get_active_session(self) -> str | None:
        cfg = ConfigResolver.resolve(self._app_config, self._account_config)
        return cfg.get("session_id")

    # ── 认证状态 ────────────────────────────────────────

    def is_authenticated(self) -> bool:
        cfg = self._account_config or {}
        return bool(cfg.get("token"))

    def active_model(self) -> str:
        if self._account_config:
            return self._account_config.get("model", self._default_model)
        import session as sess
        return sess.get_active_model()

    def supported_models(self) -> list[str]:
        """该上游支持的模型列表。子类应覆盖。"""
        return []
