"""内部请求/响应类型（OpenAI body 之上的薄封装）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TokenUsage:
    """统一 token 用量结构。

    所有上游协议返回的 usage 都归一化成这个结构。
    handler 用它构建 OpenAI 响应，session 用它存储统计。
    """
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0

    def to_openai_usage(self) -> dict:
        """转换为 OpenAI 响应的 usage 字段。"""
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "prompt_tokens_details": {
                "cached_tokens": self.cached_tokens,
            },
            "completion_tokens_details": {
                "reasoning_tokens": self.reasoning_tokens,
            },
        }


@dataclass
class TurnRequest:
    """一次 chat completion 在适配器归一化后的输入。"""

    body: dict
    headers: dict[str, str]
    model: str
    tools: list[dict]
    request_id: str
    rid: str  # 日志用 R1, R2…

    # 发给上游网页端的一条 user/tool 文本
    upstream_user_content: str
    is_react_continuation: bool
    tool_call_ids: list[str] = field(default_factory=list)

    working_directory: str = ""


@dataclass
class ProviderTurn:
    """上游返回后、转成 OpenAI 响应前的中间态（可选扩展）。"""

    openai_response: dict