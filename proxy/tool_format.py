"""工具调用响应解析器

从模型输出中提取工具块，转成 {name, arguments} 结构。
支持格式错乱、截断、工具混在正文里等边界情况。
"""

import os
import re
from typing import Any

# 单个 key="value" 行
KEY_VALUE_RE = re.compile(
    r'^[ \t]*([A-Za-z_]\w*)[ \t]*=[ \t]*(?:"((?:\\.|[^"\\])*)"|"((?:\\.|[^"\\])*?)[ \t]*\Z|(\S+))',
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
        elif m.group(3) is not None:
            raw_args[m.group(1)] = m.group(3)
        else:
            raw_args[m.group(1)] = m.group(4)
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

    逐行状态机扫描（支持引号内换行）：
    - 遇到 "工具 名称" → 开始新工具块
    - 遇到 key="value" 或 key="value（未闭合） → 累积参数
    - 引号未闭合时继续读行直到遇到闭合 "
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
    in_quote = False       # 正在收集引号内的多行值
    quote_key = ""         # 当前引号值对应的 key
    quote_lines: list[str] = []  # 引号内收集的行

    def _commit():
        nonlocal current_name, current_kv_lines, in_quote, quote_key, quote_lines
        if in_quote:
            # 引号未闭合，把收集的内容拼回去
            full_line = quote_key + '="' + '\n'.join(quote_lines)
            current_kv_lines.append(full_line)
            in_quote = False
            quote_key = ""
            quote_lines = []
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
        line = line.rstrip('\r')
        # 如果正在收集引号内的多行值
        if in_quote:
            if '"' in line:
                # 找到闭合引号 → 结束引号收集
                quote_lines.append(line)
                full_line = quote_key + '="' + '\n'.join(quote_lines)
                current_kv_lines.append(full_line)
                in_quote = False
                quote_key = ""
                quote_lines = []
            else:
                quote_lines.append(line)
            continue

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
                # 检查引号是否闭合：group(2) 有值说明闭合了
                if kv_match.group(2) is not None:
                    # 正常闭合的 key="value"
                    current_kv_lines.append(line)
                elif kv_match.group(3) is not None:
                    # 未闭合的 key="value（到行尾）
                    in_quote = True
                    quote_key = kv_match.group(1)
                    quote_lines = [kv_match.group(3)]
                else:
                    # 无引号的值
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
