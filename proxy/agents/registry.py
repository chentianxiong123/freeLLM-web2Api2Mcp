"""Agent 注册与解析。"""

from __future__ import annotations

import os

from agents.claude_code import ClaudeCodeAgent
from agents.generic import GenericOpenAIAgent

_AGENTS = {
    "claude_code": ClaudeCodeAgent(),
    "generic": GenericOpenAIAgent(),
}

_DEFAULT_ORDER = ("claude_code", "generic")


def resolve_agent_id(headers: dict[str, str], body: dict) -> str:
    forced = os.environ.get("DOWNSTREAM_AGENT", "").strip().lower()
    if forced and forced in _AGENTS:
        return forced
    for aid in _DEFAULT_ORDER:
        agent = _AGENTS[aid]
        if agent.detect(headers, body):
            return aid
    return "generic"


def get_agent(agent_id: str | None = None, *, headers: dict | None = None, body: dict | None = None):
    if agent_id:
        return _AGENTS.get(agent_id, _AGENTS["generic"])
    if headers is not None and body is not None:
        return _AGENTS[resolve_agent_id(headers, body)]
    return _AGENTS["generic"]


def list_agents() -> list[dict]:
    return [{"id": a.id, "display_name": a.display_name} for a in _AGENTS.values()]