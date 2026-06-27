"""Qwen Provider — 把 qwen_api.py 接入 ChatProvider 协议。

与 DeepSeek Provider 一致，chat_id 跨轮复用，通过 session.py 管理生命周期。
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

from providers.base import Event

from . import qwen_api as api


class QwenProvider:
    def __init__(self, app_config: dict | None = None, account_config: dict | None = None):
        self._app_config = app_config
        self._account_config = account_config
        self._last_message_id: str | None = None

    def _build_cfg(self, account_config: dict | None) -> dict:
        cfg = dict(self._app_config) if self._app_config is not None else {}
        if self._account_config is not None:
            for k in ("id", "token", "model", "session_id", "headers", "cookie"):
                v = self._account_config.get(k)
                if v is not None:
                    cfg.setdefault(k, v)
        if account_config is not None:
            for k in ("id", "token", "model", "session_id", "headers", "cookie"):
                v = account_config.get(k)
                if v is not None:
                    cfg[k] = v
        return cfg

    def _resolve_token(self, cfg: dict) -> str | None:
        return cfg.get("token")

    def _resolve_model(self, model: str, cfg: dict) -> str:
        if model and model != "default":
            return model
        return cfg.get("model", "qwen3.7-plus")

    async def chat(
        self,
        messages: list[dict],
        *,
        model: str = "default",
        account_config: dict | None = None,
        thinking_enabled: bool = True,
        search_enabled: bool = False,
    ) -> AsyncIterator[Event]:
        cfg = self._build_cfg(account_config)
        token = self._resolve_token(cfg)
        if not token:
            yield Event("error", {"message": "未配置 Qwen token"})
            return

        actual_model = self._resolve_model(model, cfg)
        loop = asyncio.get_running_loop()

        chat_id = cfg.get("session_id") or ""

        if chat_id:
            # 验证会话是否仍有效（Qwen 服务端可能已删除）
            history = await loop.run_in_executor(None, api.get_chat_history, token, chat_id)
            if history is None:
                print(f"[Qwen] Chat {chat_id[:12]}... invalid/deleted, will create new")
                chat_id = ""
                acc_id = cfg.get("id")
                if acc_id:
                    import accounts as _accounts
                    _accounts.update_account(acc_id, {"session_id": ""})

        if not chat_id:
            chat_id = await loop.run_in_executor(None, api.create_chat, token, actual_model)
            if not chat_id:
                yield Event("error", {"message": "创建 Qwen 会话失败"})
                return
            # 保存 session_id 到账号或全局
            acc_id = cfg.get("id")
            if acc_id:
                import accounts as _accounts
                _accounts.update_account(acc_id, {"session_id": chat_id, "model": actual_model})
            import session as _sess
            _sess.register_session(chat_id, model=actual_model)
            _sess.activate_session(chat_id)
            print(f"[Qwen] Session {chat_id[:12]}... created for model={actual_model}")

        has_tools = any(
            m.get("role") in ("tool", "assistant") and "tool_calls" in m
            for m in messages
        )

        parent_id = self._last_message_id

        gen = await loop.run_in_executor(
            None,
            _create_gen,
            token, chat_id, actual_model, messages, thinking_enabled, search_enabled, has_tools, parent_id,
        )

        for etype, val in gen:
            if etype == "content":
                yield Event("content", val)
            elif etype == "thinking":
                yield Event("thinking", val)
            elif etype == "tool_call":
                yield Event("tool_call", val)
            elif etype == "error":
                yield Event("error", val)
            elif etype == "usage":
                yield Event("token_usage", val)
            elif etype == "message_id":
                self._last_message_id = val
                yield Event("message_id", val)
            elif etype == "done":
                yield Event("done", val)

    async def list_sessions(self) -> list[dict]:
        import session as _sess
        import accounts as _accounts
        active_acc = _accounts.get_active_account()
        account_id = active_acc.get("id", "") if active_acc else ""
        return _sess.list_sessions(account_id=account_id)

    async def create_session(self, label: str = "", model: str = "") -> str | None:
        import accounts as _accounts
        acc = _accounts.get_active_account()
        if not acc:
            return None
        token = acc.get("token")
        if not token:
            return None
        actual_model = model or acc.get("model", "qwen3.7-plus")
        loop = asyncio.get_running_loop()
        chat_id = await loop.run_in_executor(None, api.create_chat, token, actual_model)
        if chat_id:
            _accounts.update_account(acc["id"], {"session_id": chat_id, "model": actual_model})
            import session as _sess
            _sess.register_session(chat_id, label=label, model=actual_model, account_id=acc["id"])
        return chat_id

    async def activate_session(self, session_id: str) -> bool:
        # 更新账号的 session_id
        cfg = self._build_cfg(account_config=None)
        acc_id = cfg.get("id")
        if acc_id:
            import accounts as _accounts
            _accounts.update_account(acc_id, {"session_id": session_id})
        import session as sess
        ok = sess.activate_session(session_id)
        if ok:
            self._last_message_id = None
        return ok

    async def get_active_session(self) -> str | None:
        cfg = self._build_cfg(account_config=None)
        sid = cfg.get("session_id")
        if sid:
            return sid
        import session as sess
        return sess.get_current_session_id()

    async def delete_session(self, session_id: str) -> bool:
        cfg = self._build_cfg(account_config=None)
        token = cfg.get("token")
        if token:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, api.delete_chat, token, session_id)
        # 如果删除的是当前账号的 session，清理账号记录
        acc_id = cfg.get("id")
        if acc_id and cfg.get("session_id") == session_id:
            import accounts as _accounts
            _accounts.update_account(acc_id, {"session_id": ""})
        import session as sess
        ok, _ = sess.delete_session(session_id)
        return ok


def _create_gen(token, chat_id, model, messages, thinking_enabled, search_enabled, has_tools, parent_id):
    return api.chat_completion(
        token, chat_id, model, messages,
        thinking_enabled=thinking_enabled,
        search_enabled=search_enabled,
        has_tools=has_tools,
        parent_id=parent_id,
    )
