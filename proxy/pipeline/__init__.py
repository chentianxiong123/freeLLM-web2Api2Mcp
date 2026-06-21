"""Chat 编排：Agent 适配 + Backend 上游 + OpenAI 响应。"""

from pipeline.chat import run_chat_completion, stream_empty_sse

__all__ = ["run_chat_completion", "stream_empty_sse"]