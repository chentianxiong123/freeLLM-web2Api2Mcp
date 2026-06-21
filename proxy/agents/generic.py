"""通用 OpenAI 兼容客户端（不特殊处理 stream / housekeeping）。"""

from __future__ import annotations

import gateway
from request_parser import build_ds_input


class GenericOpenAIAgent:
    id = "generic"
    display_name = "Generic OpenAI Client"

    def detect(self, headers: dict[str, str], body: dict) -> bool:
        return True

    def extract_upstream_turn(self, body: dict) -> tuple[str, bool, list[str]]:
        req = build_ds_input(body)
        return req.user_content, req.is_react_continuation, req.tool_call_ids

    def is_housekeeping(self, body: dict) -> bool:
        return False

    def clean_prompt_for_rules(self, body: dict) -> str:
        return gateway.extract_clean_user_prompt(body)