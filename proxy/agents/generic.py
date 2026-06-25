"""通用 OpenAI 兼容客户端（不特殊处理 stream / housekeeping）。"""

from __future__ import annotations

from agents.base import BaseAgent


class GenericOpenAIAgent(BaseAgent):
    id = "generic"
    display_name = "Generic OpenAI Client"

    def detect(self, headers: dict[str, str], body: dict) -> bool:
        return True

    def is_housekeeping(self, body: dict) -> bool:
        return False
