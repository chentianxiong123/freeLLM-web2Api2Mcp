"""DeepSeek 上游协议实现。

职责：把 deepseek_api.py 的同步 generator 包装成 UpstreamProtocol 接口。
"""

from __future__ import annotations

import asyncio
from typing import Generator

from providers.base import UpstreamProtocol
from . import deepseek_api as ds_api


class DeepSeekProtocol(UpstreamProtocol):
    """DeepSeek 网页端协议。"""

    # 模型 → model_type 映射
    _MODEL_TYPE_MAP = {
        "deepseek-v4-flash": "default",
        "deepseek-v4-pro": "expert",
    }

    def authenticate(self, credentials: dict) -> dict | None:
        """DeepSeek 认证（暂不实现，依赖 accounts.py）。"""
        return credentials.get("token")

    async def create_conversation(self, token: str, model: str) -> str | None:
        """创建 DeepSeek 会话。"""
        cfg = {"token": token}
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, ds_api.create_new_session, cfg)

    async def delete_conversation(self, token: str, conversation_id: str) -> bool:
        """删除 DeepSeek 会话。"""
        cfg = {"token": token, "session_id": conversation_id}
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, ds_api.delete_session, cfg, conversation_id)

    async def get_history(self, token: str, conversation_id: str) -> list[dict] | None:
        """获取 DeepSeek 会话历史（暂不实现）。"""
        return None

    async def send_message(
        self,
        token: str,
        conversation_id: str,
        messages: list[dict],
        *,
        continuation_id: str | None = None,
        model: str = "",
        thinking_enabled: bool = True,
        search_enabled: bool = False,
    ) -> Generator:
        """发送消息，返回同步 (etype, val) generator。"""
        cfg = {"token": token, "session_id": conversation_id}
        model_type = self._resolve_model_type(model)

        loop = asyncio.get_running_loop()
        gen = await loop.run_in_executor(
            None,
            _create_gen,
            cfg, messages, model, model_type, thinking_enabled, search_enabled,
        )
        return gen

    def _resolve_model_type(self, model: str) -> str:
        if not model:
            return "default"
        return self._MODEL_TYPE_MAP.get(model, "default")


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
