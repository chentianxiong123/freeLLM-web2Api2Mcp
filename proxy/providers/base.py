"""上游协议抽象层。

职责分离：
- UpstreamProtocol: 上游协议接口（每个上游实现）
- ContinuationState: 续接点管理（共享）
- EventBridge: 同步 generator → AsyncIterator[Event]（共享）
- ConfigResolver: 配置组装（共享）
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Generator, Protocol, runtime_checkable

from core.types import TokenUsage


# ── Event ──────────────────────────────────────────────────


class Event:
    """Provider 流式输出的事件单元。

    type 取值：
      - "content"     : 文本 token（val=str）
      - "thinking"    : 内部思考（val=str）
      - "tool_call"   : 工具调用（val={"name": str, "arguments": dict/str}）
      - "token_usage" : token 统计（val=TokenUsage 或 dict 或 int）
      - "message_id"  : Provider 给的 message_id，用于续接（val=str）
      - "error"       : 错误（val=str 或 dict）
      - "done"        : 流结束（val=None）
    """
    __slots__ = ("type", "val")

    def __init__(self, type: str, val: Any):
        self.type = type
        self.val = val

    def __repr__(self):
        v = self.val
        if isinstance(v, str) and len(v) >= 50:
            v = v[:50] + "…"
        return "Event(" + repr(self.type) + ", " + repr(v) + ")"


class ProviderError(Exception):
    """Provider 抛出的错误。"""
    pass


# ── 续接点管理 ─────────────────────────────────────────────


class ContinuationState:
    """续接点管理。支持多会话。

    上游协议实现负责：
    1. 在事件流中提取 message_id 并调用 update()
    2. 发消息时通过 get_continuation_id() 获取续接点

    续接点会从 sessions.json 恢复，服务重启后不会丢失。
    """

    def __init__(self):
        self._cache: dict[str, str] = {}  # conversation_id → message_id
        self._loaded = False

    def _ensure_loaded(self):
        """确保从 sessions.json 加载续接点。"""
        if self._loaded:
            return
        try:
            import session as sess
            db = sess._load()
            for sid, s in db.get("sessions", {}).items():
                mid = s.get("last_message_id")
                if mid:
                    self._cache[sid] = str(mid)
        except Exception:
            pass
        self._loaded = True

    def get_continuation_id(self, conversation_id: str) -> str | None:
        """获取指定会话的续接点。"""
        self._ensure_loaded()
        return self._cache.get(conversation_id)

    def update(self, conversation_id: str, message_id: str):
        """更新指定会话的续接点（同时写入 sessions.json）。"""
        self._cache[conversation_id] = message_id
        # 持久化到 sessions.json
        try:
            import session as sess
            sess.set_specific_last_message_id(conversation_id, message_id)
        except Exception:
            pass

    def reset(self, conversation_id: str | None = None):
        """重置续接点。conversation_id=None 时重置所有。"""
        if conversation_id:
            self._cache.pop(conversation_id, None)
            try:
                import session as sess
                sess.set_specific_last_message_id(conversation_id, None)
            except Exception:
                pass
        else:
            self._cache.clear()


# ── 配置组装 ──────────────────────────────────────────────


class ConfigResolver:
    """从 app_config + account_config 组装最终配置。"""

    # 需要从 account_config 中继承的字段
    _ACCOUNT_FIELDS = ("id", "token", "model", "session_id", "headers", "cookie")

    @classmethod
    def resolve(
        cls,
        app_config: dict | None,
        account_config: dict | None,
        override: dict | None = None,
    ) -> dict:
        """组装最终配置。

        优先级：override > account_config > app_config
        """
        cfg = dict(app_config) if app_config else {}
        if account_config:
            for k in cls._ACCOUNT_FIELDS:
                v = account_config.get(k)
                if v is not None:
                    cfg[k] = v
        if override:
            for k in cls._ACCOUNT_FIELDS:
                v = override.get(k)
                if v is not None:
                    cfg[k] = v
        return cfg


# ── 事件桥接 ──────────────────────────────────────────────


# 同步 (etype, val) → Event 的映射表
_EVENT_MAP = {
    "content": "content",
    "thinking": "thinking",
    "tool_call": "tool_call",
    "usage": "token_usage",
    "token_usage": "token_usage",
    "message_id": "message_id",
    "error": "error",
    "done": "done",
}


class EventBridge:
    """同步 generator → AsyncIterator[Event]。"""

    @staticmethod
    async def bridge(gen: Generator) -> AsyncIterator[Event]:
        """把同步 (etype, val) generator 桥接为异步 Event 流。"""
        for etype, val in gen:
            mapped = _EVENT_MAP.get(etype, "content")
            yield Event(mapped, val)


# ── 上游协议接口 ──────────────────────────────────────────


@runtime_checkable
class UpstreamProtocol(Protocol):
    """上游协议接口。每个上游实现这个接口。

    职责：
    - 认证（authenticate）
    - 会话管理（create/delete/get_history）
    - 消息发送（send_message）— 含续接
    """

    def authenticate(self, credentials: dict) -> dict | None:
        """认证，返回 token 或 None。"""
        ...

    async def create_conversation(self, token: str, model: str) -> str | None:
        """创建会话，返回 conversation_id。"""
        ...

    async def delete_conversation(self, token: str, conversation_id: str) -> bool:
        """删除会话。"""
        ...

    async def get_history(self, token: str, conversation_id: str) -> list[dict] | None:
        """获取会话历史。"""
        ...

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
        """发送消息，返回同步 (etype, val) generator。

        上游实现负责：
        1. 把 continuation_id 翻译成自己的字段名
        2. 在事件流中返回 ("message_id", str) 供续接
        3. 返回 ("usage", TokenUsage/dict/int) 供统计
        """
        ...
