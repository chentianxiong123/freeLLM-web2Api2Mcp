"""下游客户端适配器协议。

不同 Agent 的差异：
- housekeeping 检测
- 从 OpenAI messages 提取发给上游的末条内容
- 可选：规则/清洗用的 clean_prompt
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from core.types import TurnRequest


@runtime_checkable
class DownstreamAgent(Protocol):
    id: str
    display_name: str

    def detect(self, headers: dict[str, str], body: dict) -> bool:
        """是否匹配该客户端（用于自动选择）。"""
        ...

    def extract_upstream_turn(self, body: dict) -> tuple[str, bool, list[str]]:
        """返回 (upstream_user_content, is_react_continuation, tool_call_ids)。"""
        ...

    def is_housekeeping(self, body: dict) -> bool:
        ...

    def clean_prompt_for_rules(self, body: dict) -> str:
        """供 rules 引擎使用的干净用户 prompt。"""