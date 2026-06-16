"""DeepSeek 工具调用响应解析器

DeepSeek 用 "自然语言暗语" 输出工具调用：
    工具 名称
    key="value"
    key2="value2"
    工具结束

我们的任务：
1. 从 DeepSeek 完整回复中切出所有"工具块"
2. 每个块转成 {name, arguments} 结构
3. 残留的普通文本作为 content
4. 多个工具块按出现顺序

依赖：调用方传入工具 schema（用于类型推断）
"""

import re
from typing import Any

# 工具块匹配
# 匹配 "工具 名称" 到 "工具结束" 中间的所有 key="value" 行
TOOL_BLOCK_RE = re.compile(
    r'^\s*工具\s+([A-Za-z_]\w*)\s*$'           # 工具名行
    r'((?:\n\s*[A-Za-z_]\w*\s*=\s*"[^"]*"\s*)*)'  # key="value" 行
    r'\n?\s*工具结束\s*$',
    re.MULTILINE,
)

# 单个 key="value" 行
KEY_VALUE_RE = re.compile(
    r'^\s*([A-Za-z_]\w*)\s*=\s*"((?:\\.|[^"\\])*)"\s*$',
    re.MULTILINE,
)


def _unescape(s: str) -> str:
    """还原字符串里的转义。"""
    return s.replace('\\"', '"').replace('\\\\', '\\').replace('\\n', '\n').replace('\\t', '\t')


def _infer_type(value: str, schema_type: str | None) -> Any:
    """根据 JSON schema 类型推断 Python 值。"""
    if schema_type == "integer":
        try:
            return int(value)
        except (ValueError, TypeError):
            return value
    if schema_type == "number":
        try:
            v = float(value)
            return int(v) if v.is_integer() else v
        except (ValueError, TypeError):
            return value
    if schema_type == "boolean":
        if value == "true":
            return True
        if value == "false":
            return False
        return value
    # string / object / array / 默认：保持字符串（object/array 暂不解析 JSON，让 Claude Code 端去解析）
    return value


def _coerce_arguments(raw_args: dict[str, str], tool_schema: dict | None) -> dict:
    """按 schema 把字符串值转成正确类型。"""
    if not tool_schema:
        return {k: _unescape(v) for k, v in raw_args.items()}
    props = (tool_schema.get("parameters") or {}).get("properties") or {}
    out = {}
    for k, v in raw_args.items():
        unescaped = _unescape(v)
        schema_type = (props.get(k) or {}).get("type")
        out[k] = _infer_type(unescaped, schema_type)
    return out


def parse_tool_blocks(text: str, tools_schema: list[dict] | None = None) -> tuple[str, list[dict]]:
    """从 DeepSeek 文本里切出所有工具块，返回 (剩余文本, 工具调用列表)。

    参数：
        text: 完整 DeepSeek 回复
        tools_schema: OpenAI 格式的 tools 列表（用于类型推断），形如
            [{'function': {'name': 'Read', 'parameters': {...}}}, ...]

    返回：
        remaining_text: 去掉所有工具块之后的纯文本
        tool_calls: [{'name': 'Bash', 'arguments': {...}}, ...]
    """
    if not text:
        return "", []

    # 按出现顺序找到所有工具块
    blocks: list[dict] = []
    for m in TOOL_BLOCK_RE.finditer(text):
        name = m.group(1).strip()
        kv_text = m.group(2)
        raw_args: dict[str, str] = {}
        for km in KEY_VALUE_RE.finditer(kv_text):
            raw_args[km.group(1)] = km.group(2)

        # 找对应 schema
        schema = None
        if tools_schema:
            for t in tools_schema:
                if t.get("function", {}).get("name") == name:
                    schema = t["function"]
                    break

        blocks.append({
            "name": name,
            "arguments": _coerce_arguments(raw_args, schema),
        })

    # 剩余文本：把所有工具块 + 前后紧邻空行去掉
    remaining = TOOL_BLOCK_RE.sub("", text)
    # 把连续空行压成单个空行
    remaining = re.sub(r'\n{3,}', '\n\n', remaining).strip()

    return remaining, blocks


def build_openai_tool_call(call_id: str, name: str, arguments: dict, idx: int = 0) -> dict:
    """构造 OpenAI tool_calls 单个元素。"""
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": json_dumps(arguments),
        },
    }


def json_dumps(obj: Any) -> str:
    """JSON 序列化（统一 ensure_ascii=False，避免中文被转义）。"""
    import json
    return json.dumps(obj, ensure_ascii=False)


# ── 单元测试（仅直接运行时执行）─────────────────────────

if __name__ == "__main__":
    # 模拟一个 DeepSeek 回复
    sample = """好的，我先看看。

工具 Bash
command="Get-ChildItem -Force"
description="列出文件"
工具结束

工具 Read
file_path="C:/Users/a1/Desktop/111.txt"
offset="5"
limit="6"
工具结束

读取完毕。
"""
    # 工具 schema 用于类型推断
    schema = [
        {"function": {"name": "Bash", "parameters": {"properties": {"command": {"type": "string"}, "description": {"type": "string"}}}}},
        {"function": {"name": "Read", "parameters": {"properties": {"file_path": {"type": "string"}, "offset": {"type": "integer"}, "limit": {"type": "integer"}}}}},
    ]

    text, calls = parse_tool_blocks(sample, schema)
    print("=== 剩余文本 ===")
    print(text)
    print("\n=== 工具调用 ===")
    for c in calls:
        print(c)
