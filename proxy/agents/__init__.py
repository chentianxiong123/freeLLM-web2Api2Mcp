"""下游 Agent 适配器。"""

from agents.base import BaseAgent
from agents.registry import get_agent, resolve_agent_id

__all__ = ["BaseAgent", "get_agent", "resolve_agent_id"]
