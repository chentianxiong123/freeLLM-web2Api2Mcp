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

import os
import re
from typing import Any

# 工具块匹配
# 匹配 "工具 名称" 到 "工具结束" 中间的所有 key=value 行（兼容带/不带引号、内嵌转义、前导空白）
TOOL_BLOCK_RE = re.compile(
    r'^[ \t]*工具[ \t]+([A-Za-z_]\w*)[ \t]*$'           # 工具名行（允许 tab/空格缩进）
    r'((?:\n[ \t]*[A-Za-z_]\w*[ \t]*=[ \t]*(?:"(?:\\.|[^"\\])*"|\S+)[ \t]*)*)'  # key=value 行（允许缩进）
    r'\n?[ \t]*工具结束[ \t]*$',                          # 工具结束行（允许缩进）
    re.MULTILINE,
)

# 单个 key="value" 行（兼容：带引号 / 不带引号 / 引号内嵌转义 / 前导空白）
#   - key="value"           标准
#   - key="val\"ue"         value 里嵌转义引号
#   - key=10000             数字无引号
#   - key=value             简单无空格无引号
#   -   key="value"         带缩进
KEY_VALUE_RE = re.compile(
    r'^[ \t]*([A-Za-z_]\w*)[ \t]*=[ \t]*(?:"((?:\\.|[^"\\])*)"|(\S+))\s*$',
    re.MULTILINE,
)


def _unescape(s: str) -> str:
    """还原字符串里的转义。"""
    return s.replace('\\"', '"').replace('\\\\', '\\').replace('\\n', '\n').replace('\\t', '\t')


def _expand_tilde(args: dict) -> dict:
    """把参数值里的 ~/X 或 ~ 展开成绝对路径。

    DeepSeek 经常写 `~/Desktop` 这种 Unix 风格路径，但 Claude Code（尤其 Windows 上）
    跑 Bash 时 `~` 不展开 → 命令返回空 → DeepSeek 误判超时 → 无限循环。

    在工具块解析阶段直接展开，DeepSeek 完全无感。

    规则：
    - ~/X  →  {user_home}/X
    - ~    →  {user_home}
    - 已经绝对路径（盘符 C:/ 或 /）的，不动
    - 非字符串值（数字、布尔），不动
    """
    if not isinstance(args, dict):
        return args
    home = None
    for v in args.values():
        if isinstance(v, str) and ("~/" in v or v.startswith("~")):
            if home is None:
                home = os.path.expanduser("~")
            break
    if home is None:
        return args
    out = {}
    for k, v in args.items():
        if isinstance(v, str):
            if v == "~":
                out[k] = home
            elif v.startswith("~/"):
                out[k] = home + v[1:]  # 保留开头的 /
            else:
                out[k] = v
        else:
            out[k] = v
    return out


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
            # group(2) = 带引号的值（支持内嵌转义），group(3) = 不带引号的值
            raw_args[km.group(1)] = km.group(2) if km.group(2) is not None else km.group(3)

        # 找对应 schema
        schema = None
        if tools_schema:
            for t in tools_schema:
                if t.get("function", {}).get("name") == name:
                    schema = t["function"]
                    break

        blocks.append({
            "name": name,
            "arguments": _expand_tilde(_coerce_arguments(raw_args, schema)),
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
