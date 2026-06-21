"""DeepSeek Provider — 把 deepseek_api.py 接入 ChatProvider 协议。

转换器：
  - deepseek_api.chat_completion() 返回同步 generator of (type, val) 元组
  - ChatProvider.chat() 返回 AsyncIterator[Event]

核心工作：把同步生成器桥接到异步 Event 流。
"""

import asyncio
from typing import AsyncIterator

from . import deepseek_api as ds_api
from providers.base import Event


class DeepSeekProvider:
    """真正的 DeepSeek 网页端 Provider。

    把 deepseek_api.chat_completion() 的同步流包装成 async Event 流。
    """

    def __init__(self, app_config: dict | None = None):
        self._app_config = app_config
        self._model_type_map = {
            "deepseek-v4-flash": "default",
            "deepseek-v4-pro": "expert",
        }

    def _resolve_model_type(self, model: str | None) -> str:
        if not model:
            return "default"
        return self._model_type_map.get(model, "default")

    def _build_cfg(self, account_config: dict | None) -> dict:
        if self._app_config is not None:
            cfg = dict(self._app_config)
        else:
            import config as _config
            cfg = _config.load_config()
        if account_config is not None:
            cfg["token"] = account_config.get("token", cfg.get("token", ""))
            cfg["session_id"] = account_config.get("session_id", cfg.get("session_id", ""))
            cfg["headers"] = account_config.get("headers", cfg.get("headers", {}))
            if account_config.get("cookie"):
                cfg["cookie"] = account_config["cookie"]
        return cfg

    async def chat(
        self,
        messages: list[dict],
        *,
        model: str = "deepseek-default",
        account_config: dict | None = None,
        thinking_enabled: bool = True,
        search_enabled: bool = False,
    ) -> AsyncIterator[Event]:
        """调用 DeepSeek API，转成 Event 流。"""
        cfg = self._build_cfg(account_config)

        if not cfg.get("token"):
            yield Event("error", {"message": "未登录 DeepSeek"})
            return

        if not cfg.get("session_id"):
            loop = asyncio.get_running_loop()
            sid = await loop.run_in_executor(None, ds_api.create_new_session, cfg)
            if sid:
                acc_id = cfg.get("id")
                if acc_id:
                    import accounts as _accounts
                    _accounts.update_account(acc_id, {"session_id": sid})
                else:
                    import session as sess
                    sess.on_new_session(sid, model)
                cfg["session_id"] = sid

        model_type = self._resolve_model_type(model)

        # deepseek_api.chat_completion 是同步 generator（curl_cffi 阻塞 I/O）
        # 在线程池里运行，免得阻塞事件循环
        loop = asyncio.get_running_loop()
        gen = await loop.run_in_executor(
            None,
            _create_gen,
            cfg, messages, model, model_type, thinking_enabled, search_enabled,
        )

        # 异步遍历同步 generator
        for etype, val in gen:
            if etype == "content":
                yield Event("content", val)
            elif etype == "thinking":
                yield Event("thinking", val)
            elif etype == "error":
                yield Event("error", val)
            elif etype == "done":
                yield Event("done", val)
            elif etype == "token_usage":
                yield Event("token_usage", val)
            elif etype == "message_id":
                yield Event("message_id", val)
            else:
                yield Event("content", val)  # 兜底

    async def list_sessions(self) -> list[dict]:
        import session as sess
        try:
            return sess.list_sessions()
        except Exception:
            return []

    async def create_session(self, label: str = "") -> str | None:
        cfg = self._build_cfg(account_config=None)
        sid = ds_api.create_new_session(cfg)
        if sid and label:
            import session as sess
            sess.register_session(sid, label=label)
            sess.activate_session(sid)
        return sid

    async def activate_session(self, session_id: str) -> bool:
        import session as sess
        return sess.activate_session(session_id)

    async def get_active_session(self) -> str | None:
        cfg = self._build_cfg(account_config=None)
        return cfg.get("session_id")


def _create_gen(cfg, messages, model, model_type, thinking_enabled, search_enabled):
    """Helper: 在 executor 中创建同步 generator。"""
    return ds_api.chat_completion(
        cfg,
        messages,
        model=model,
        model_type=model_type,
        thinking_enabled=thinking_enabled,
        search_enabled=search_enabled,
        stream=True,
    )
