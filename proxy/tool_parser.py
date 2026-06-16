"""DSML 工具调用解析 → Anthropic tool_use 格式

使用 tool_dsml.py 的解析能力，但将 OpenAI 格式输出转为 Anthropic 格式。
"""

import json
import re
import uuid


def parse_tool_calls(
    text: str,
    tool_names: list[str] | None = None,
) -> tuple[list[dict] | None, str]:
    """从 DeepSeek 回复文本中解析工具调用。

    Args:
        text: 原始回复文本（可能含 DSML 标签）
        tool_names: 可用的工具名列表（用于过滤）

    Returns:
        (tool_calls_or_None, cleaned_text)
        tool_calls: Anthropic 格式的 tool_use 列表
            [{"id": "tu_xxx", "type": "tool_use",
              "name": "read_file", "input": {"file_path": "/path"}}, ...]
        cleaned_text: 移除 DSML 标签后的纯文本
    """
    # 先尝试解析 DSML
    try:
        dsml_calls, cleaned = _parse_dsml_to_anthropic(text, tool_names)
        if dsml_calls:
            return dsml_calls, cleaned.strip()
    except Exception:
        pass

    # 尝试 JSON 格式
    try:
        json_calls, cleaned = _parse_json_tool_calls(text, tool_names)
        if json_calls:
            return json_calls, cleaned.strip()
    except Exception:
        pass

    return None, text.strip()


def _parse_dsml_to_anthropic(
    text: str,
    tool_names: list[str] | None,
) -> tuple[list[dict] | None, str]:
    """解析 DSML 格式为 Anthropic tool_use。"""
    # 先用 tool_dsml 的解析器（输出 OpenAI 格式）
    cleaned = strip_dsml_markup(text)
    result = parse_dsml_tool_calls(text, tool_names or [])

    if not result:
        return None, cleaned

    # result 是 OpenAI 格式: [{"name": "x", "arguments": {...}}, ...]
    anthropic_calls = []
    for call in result:
        if isinstance(call, dict):
            name = call.get("name", "")
            arguments = call.get("arguments", {})
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {"raw": arguments}
            anthropic_calls.append({
                "id": f"tu_{uuid.uuid4().hex[:24]}",
                "type": "tool_use",
                "name": name,
                "input": arguments,
            })

    return anthropic_calls if anthropic_calls else None, cleaned


def _parse_json_tool_calls(
    text: str,
    tool_names: list[str] | None,
) -> tuple[list[dict] | None, str]:
    """尝试从 JSON 块中解析工具调用。"""
    # 查找 JSON 代码块
    json_pattern = re.compile(
        r'```(?:json)?\s*(\{.*?"name".*?"arguments".*?\})\s*```',
        re.DOTALL,
    )
    match = json_pattern.search(text)
    if not match:
        return None, text

    try:
        data = json.loads(match.group(1))
        calls = data.get("tool_calls", [data] if "name" in data else [])
        anthropic_calls = []
        for call in calls:
            name = call.get("name", "")
            arguments = call.get("arguments", {})
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {"raw": arguments}
            anthropic_calls.append({
                "id": f"tu_{uuid.uuid4().hex[:24]}",
                "type": "tool_use",
                "name": name,
                "input": arguments,
            })
        return anthropic_calls, text.replace(match.group(0), "").strip()
    except json.JSONDecodeError:
        return None, text


