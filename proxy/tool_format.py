"""工具调用响应解析器

从模型输出中提取工具块，转成 {name, arguments} 结构。
支持格式错乱、截断、工具混在正文里等边界情况。
"""

import os
import re
from typing import Any

# 单个 key="value" 行
KEY_VALUE_RE = re.compile(
    r'^[ \t]*([A-Za-z_]\w*)[ \t]*=[ \t]*(?:"((?:\\.|[^"\\])*)"|(\S+)|"((?:\\.|[^"\\])*?)\s*$)',
    re.MULTILINE,
)

# 工具名行：行首 "工具 名称"
_TOOL_LINE_RE = re.compile(r'^工具\s+([A-Za-z_]\w*)\s*$')


def _unescape(s: str) -> str:
    """还原转义。处理 \\n → 换行, \\t → 制表符, \\\" → 引号, \\\\ → 反斜杠。"""
    return s.replace('\\n', '\n').replace('\\t', '\t').replace('\\"', '"').replace('\\\\', '\\')


def _expand_tilde(args: dict) -> dict:
    """展开 ~/X 为绝对路径。"""
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
                out[k] = home + v[1:]
            else:
                out[k] = v
        else:
            out[k] = v
    return out


def _infer_type(value: str, schema_type: str | None) -> Any:
    """按 schema 类型推断值。"""
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
    return value


def _coerce_arguments(raw_args: dict[str, str], tool_schema: dict | None) -> dict:
    """按 schema 转换参数类型。"""
    if not tool_schema:
        return {k: _unescape(v) for k, v in raw_args.items()}
    props = (tool_schema.get("parameters") or {}).get("properties") or {}
    out = {}
    for k, v in raw_args.items():
        unescaped = _unescape(v)
        schema_type = (props.get(k) or {}).get("type")
        out[k] = _infer_type(unescaped, schema_type)
    return out


def _parse_kv_lines(text: str) -> dict[str, str]:
    """从文本中提取所有 key=value 对。"""
    raw_args: dict[str, str] = {}
    for m in KEY_VALUE_RE.finditer(text):
        if m.group(2) is not None:
            raw_args[m.group(1)] = m.group(2)
        elif m.group(4) is not None:
            raw_args[m.group(1)] = m.group(4)
        else:
            raw_args[m.group(1)] = m.group(3)
    return raw_args


def _find_schema(name: str, tools_schema: list[dict] | None) -> dict | None:
    """按名称查找工具 schema。"""
    if not tools_schema:
        return None
    for t in tools_schema:
        if t.get("function", {}).get("name") == name:
            return t["function"]
    return None


def parse_tool_blocks(text: str, tools_schema: list[dict] | None = None) -> tuple[str, list[dict]]:
    """从模型输出中提取所有工具块。

    逐行状态机扫描：
    - 遇到 "工具 名称" → 开始新工具块
    - 遇到 key="value" → 累积参数
    - 遇到非参数行或下一个工具 → 提交当前工具块

    返回 (剩余文本, 工具调用列表)。
    """
    if not text:
        return "", []

    lines = text.split('\n')
    blocks: list[dict] = []
    content_lines: list[str] = []

    current_name: str | None = None
    current_kv_lines: list[str] = []

    def _commit():
        nonlocal current_name, current_kv_lines
        if current_name is None:
            return
        raw_args = _parse_kv_lines('\n'.join(current_kv_lines))
        schema = _find_schema(current_name, tools_schema)
        blocks.append({
            "name": current_name,
            "arguments": _expand_tilde(_coerce_arguments(raw_args, schema)),
        })
        current_name = None
        current_kv_lines = []

    for line in lines:
        # 检查是否是工具名行
        tm = _TOOL_LINE_RE.match(line)
        if tm:
            _commit()
            current_name = tm.group(1)
            current_kv_lines = []
            continue

        # 如果在工具块内，检查是否是参数行
        if current_name is not None:
            kv_match = KEY_VALUE_RE.match(line)
            if kv_match:
                current_kv_lines.append(line)
                continue
            # 非参数行 → 提交工具块，当前行归 content
            _commit()

        # 空的"工具结束"行直接跳过
        if line.strip() == '工具结束':
            continue

        content_lines.append(line)

    # 流结束，提交最后一个工具块
    _commit()

    remaining = '\n'.join(content_lines).strip()
    # 压缩连续空行
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
    """JSON 序列化（ensure_ascii=False）。"""
    import json
    return json.dumps(obj, ensure_ascii=False)


# ── 单元测试 ─────────────────────────────────────────

if __name__ == "__main__":
    # 1. 格式规范：多工具
    sample1 = """好的，我先看看。

工具 Bash
command="Get-ChildItem -Name"
工具 Read
file_path="C:/Users/a1/Desktop/111.txt"
offset="5"
limit="6"

读取完毕。

工具 Write
file_path="C:/tmp/test.txt"
content="hello"
"""
    schema = [
        {"function": {"name": "Bash", "parameters": {"properties": {"command": {"type": "string"}}}}},
        {"function": {"name": "Read", "parameters": {"properties": {"file_path": {"type": "string"}, "offset": {"type": "integer"}, "limit": {"type": "integer"}}}}},
    ]
    text, calls = parse_tool_blocks(sample1, schema)
    print("=== 测试1: 格式规范 ===")
    print("剩余:", repr(text))
    print("调用:", calls)

    # 2. 工具混在正文里
    sample2 = """我先看一下目录工具 Bash
command="Get-ChildItem -Name"
工具结束"""
    text2, calls2 = parse_tool_blocks(sample2)
    print("\n=== 测试2: 混在正文里 ===")
    print("剩余:", repr(text2))
    print("调用:", calls2)

    # 3. 截断（无闭合引号）
    sample3 = '工具 Write\nfile_path="C:/tmp/test.txt"\ncontent="hello'
    text3, calls3 = parse_tool_blocks(sample3)
    print("\n=== 测试3: 截断 ===")
    print("剩余:", repr(text3))
    print("调用:", calls3)

    # 4. 两个工具挤一行
    sample4 = '工具 Bash\ncommand="ls" Write\nfile_path="C:/tmp/test.txt"\ncontent="hello"'
    text4, calls4 = parse_tool_blocks(sample4)
    print("\n=== 测试4: 两个工具挤一行 ===")
    print("剩余:", repr(text4))
    print("调用:", calls4)
