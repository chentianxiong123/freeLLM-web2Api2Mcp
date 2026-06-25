"""下游客户端适配器基类。

职责：下游适配器的公共逻辑。
- extract_upstream_turn: 从 OpenAI body 提取用户内容
- clean_prompt_for_rules: 供规则引擎使用的干净 prompt
- detect / is_housekeeping: 子类必须实现
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from core.types import TurnRequest


class BaseAgent:
    """Agent 基类。所有下游适配器继承这个类。"""

    id: str = ""
    display_name: str = ""

    def detect(self, headers: dict[str, str], body: dict) -> bool:
        """识别这是哪种客户端。子类必须实现。"""
        raise NotImplementedError

    def is_housekeeping(self, body: dict) -> bool:
        """是否是后台维护请求。子类必须实现。"""
        raise NotImplementedError

    def extract_upstream_turn(self, body: dict) -> tuple[str, bool, list[str]]:
        """从客户端请求中提取：(用户内容, 是否续接, tool_call_ids)。

        默认实现委托给 request_parser.build_ds_input。
        """
        from request_parser import build_ds_input
        req = build_ds_input(body)
        return req.user_content, req.is_react_continuation, req.tool_call_ids

    def clean_prompt_for_rules(self, body: dict) -> str:
        """供规则引擎使用的干净 prompt。

        默认实现委托给 gateway.extract_clean_user_prompt。
        """
        import gateway
        return gateway.extract_clean_user_prompt(body)
