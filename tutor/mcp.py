"""MCP 工具：把网页版大模型包装成「外援老师」工具。

暴露给 coding agent 调用：提问（外援老师）/ 列平台。
transport 支持 stdio 与 streamable-http。
"""

from __future__ import annotations

import json

from mcp.server.mcpserver import MCPServer

from tutor import ask

mcp = MCPServer("tutor")


@mcp.tool()
def ask_web_llm(platform: str, prompt: str, conversation_id: str = "") -> str:
    """向网页版大模型（外援老师）提问，返回回答文本。

    Args:
        platform: 平台 key（doubao/deepseek/kimi/qwen/zhipu/yuanbao），或 "auto" 自动挑可用。
        prompt: 提问内容（可让模型自行联网搜索）。
        conversation_id: 续聊会话 id（可空=新会话）。

    Returns:
        模型回答文本。
    """
    if platform == "auto":
        r = ask.auto_ask(prompt)
    else:
        r = ask.ask_llm(platform, prompt, conversation_id)
    return r["answer"]


@mcp.tool()
def list_web_llms() -> str:
    """列出全部平台及登录/验证状态（JSON 字符串）。"""
    return json.dumps(ask.list_llms(), ensure_ascii=False, indent=2)


def run_stdio() -> None:
    mcp.run(transport="stdio")


def run_http(host: str = "127.0.0.1", port: int = 8787) -> None:
    mcp.run(transport="streamable-http", host=host, port=port)
