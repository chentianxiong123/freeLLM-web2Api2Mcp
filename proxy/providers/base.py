"""ChatProvider 抽象接口。

所有后端（DeepSeek / OpenAI / Claude / Mock）都实现这个接口。
业务代码（react_loop / main.py）只依赖这个接口，不依赖具体后端。
"""

from typing import Protocol, runtime_checkable, AsyncIterator, Any


class Event:
    """Provider 流式输出的事件单元。

    type 取值：
      - "content"     : 文本 token（val=str）
      - "thinking"    : 内部思考（val=str），不发给用户
      - "tool_call"   : 工具调用（val={"name": str, "arguments": dict}）
      - "token_usage" : token 统计（val=int）
      - "message_id"  : Provider 给的 message_id，用于续接（val=Any）
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


@runtime_checkable
class ChatProvider(Protocol):
    """Chat 提供方接口。

    实现示例：
      - DeepSeekProvider: providers/deepseek.py
      - OpenAIProvider:   providers/openai.py（未来）
      - MockProvider:     providers/mock.py（测试用）
    """

    async def chat(
        self,
        messages: list[dict],
        *,
        model: str = "default",
        thinking_enabled: bool = True,
        search_enabled: bool = False,
    ) -> AsyncIterator[Event]:
        """发送对话，返回 Event 流。

        messages: 发送给后端的消息列表（OpenAI 格式）
        model:    后端模型名
        thinking_enabled: 是否启用思考
        search_enabled:   是否启用联网搜索

        Yields: Event 实例
        """
        ...

    def list_sessions(self) -> list[dict]:
        """列出所有 session。"""
        ...

    def create_session(self) -> str | None:
        """创建新 session，返回 session_id。"""
        ...

    def activate_session(self, session_id: str) -> bool:
        """切换 active session。"""
        ...

    def get_active_session(self) -> str | None:
        """获取当前 active session_id。"""
        ...
