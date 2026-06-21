"""内部请求/响应类型（OpenAI body 之上的薄封装）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TurnRequest:
    """一次 chat completion 在适配器归一化后的输入。"""

    body: dict
    headers: dict[str, str]
    stream: bool
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