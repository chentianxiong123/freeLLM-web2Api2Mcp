"""6 个核心工具定义（Anthropic input_schema 格式）"""

import json

TOOLS_ANTHROPIC = [
    {
        "name": "read_file",
        "description": "读取文件内容",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "文件绝对路径",
                }
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "write_file",
        "description": "写入/创建文件",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "文件绝对路径",
                },
                "content": {
                    "type": "string",
                    "description": "要写入的内容",
                },
            },
            "required": ["file_path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": "编辑文件（精确文本替换）",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "文件绝对路径",
                },
                "old_string": {
                    "type": "string",
                    "description": "被替换的原文",
                },
                "new_string": {
                    "type": "string",
                    "description": "替换后的新文本",
                },
            },
            "required": ["file_path", "old_string", "new_string"],
        },
    },
    {
        "name": "bash",
        "description": "执行 Shell 命令",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "要执行的命令",
                }
            },
            "required": ["command"],
        },
    },
    {
        "name": "grep",
        "description": "在文件中搜索文本（支持正则）",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "正则表达式",
                },
                "path": {
                    "type": "string",
                    "description": "搜索路径（文件或目录）",
                },
                "glob": {
                    "type": "string",
                    "description": "可选的 glob 过滤，如 *.py",
                },
            },
            "required": ["pattern", "path"],
        },
    },
    {
        "name": "glob",
        "description": "按 glob 模式查找文件",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "glob 模式，如 **/*.py",
                },
                "path": {
                    "type": "string",
                    "description": "根目录路径",
                },
            },
            "required": ["pattern"],
        },
    },
]

TOOL_NAMES = [t["name"] for t in TOOLS_ANTHROPIC]


def tools_to_openai(anthropic_tools: list[dict] | None = None) -> list[dict]:
    """Anthropic 格式 → OpenAI function calling 格式。"""
    tools = anthropic_tools or TOOLS_ANTHROPIC
    result = []
    for t in tools:
        result.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        })
    return result


def tools_to_prompt_json(anthropic_tools: list[dict] | None = None) -> str:
    """工具定义 → 纯 JSON 字符串（用于嵌入 prompt）。"""
    tools = anthropic_tools or TOOLS_ANTHROPIC
    return json.dumps(tools, ensure_ascii=False, indent=2)