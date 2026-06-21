"""工具输出编解码（按上游网页端协议）。"""

from __future__ import annotations

from typing import Any

# DeepSeek 自然语言暗语 → 在 handler.collect_response 内通过 tool_format 完成
CODEC_DEEPSEEK_NATURAL = "deepseek_natural"


def codec_for_backend(backend_id: str) -> str:
    if backend_id == "deepseek":
        return CODEC_DEEPSEEK_NATURAL
    return CODEC_DEEPSEEK_NATURAL