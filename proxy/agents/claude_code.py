"""Claude Code（OpenAI 模式）适配。"""

from __future__ import annotations

import gateway
from agents.base import BaseAgent


class ClaudeCodeAgent(BaseAgent):
    id = "claude_code"
    display_name = "Claude Code"

    def detect(self, headers: dict[str, str], body: dict) -> bool:
        ua = (headers.get("user-agent") or headers.get("User-Agent") or "").lower()
        if "claude-cli" in ua or "claude-code" in ua:
            return True
        if headers.get("x-claude-code-session-id") or headers.get("X-Claude-Code-Session-Id"):
            return True
        return False

    def is_housekeeping(self, body: dict) -> bool:
        return gateway.is_claude_housekeeping_request(body)
