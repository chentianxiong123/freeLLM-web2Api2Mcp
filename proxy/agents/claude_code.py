"""Claude Code（OpenAI 模式）适配。"""

from __future__ import annotations

import time

import gateway
from handler import build_ds_input


class ClaudeCodeAgent:
    id = "claude_code"
    display_name = "Claude Code"

    def detect(self, headers: dict[str, str], body: dict) -> bool:
        ua = (headers.get("user-agent") or headers.get("User-Agent") or "").lower()
        if "claude-cli" in ua or "claude-code" in ua:
            return True
        if headers.get("x-claude-code-session-id") or headers.get("X-Claude-Code-Session-Id"):
            return True
        return False

    def should_handle_stream(self, body: dict) -> bool:
        return False

    def empty_stream_response(self, body: dict, request_id: str) -> dict:
        return {
            "id": request_id,
            "object": "chat.completion",
            "created": int(time.time()),
            "model": body.get("model", "deepseek-v4-flash"),
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": ""},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    def extract_upstream_turn(self, body: dict) -> tuple[str, bool, list[str]]:
        req = build_ds_input(body)
        return req.user_content, req.is_react_continuation, req.tool_call_ids

    def is_housekeeping(self, body: dict) -> bool:
        return gateway.is_claude_housekeeping_request(body)

    def clean_prompt_for_rules(self, body: dict) -> str:
        return gateway.extract_clean_user_prompt(body)