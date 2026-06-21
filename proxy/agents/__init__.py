"""下游 Agent 适配器。"""

from agents.base import DownstreamAgent
from agents.registry import get_agent, resolve_agent_id

__all__ = ["DownstreamAgent", "get_agent", "resolve_agent_id"]