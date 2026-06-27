"""工具调用响应解析器

从模型输出中提取工具块，内部拼成 JSON 用 json.loads() 解析。
"""

import json
import os
import re
from typing import Any

_TOOL_LINE_RE = re.compile(r'^(?:工具|Tool)\s+([A-Za-z_]\w*)\s*$')
_KV_RE = re.compile(r'^[ \t]*([A-Za-z_]\w*)[ \t]*=[ \t]*(.*)[ \t]*$')


def _parse_kv_line(line: str) -> tuple[str, str] | None:
    m = _KV_RE.match(line)
    if not m:
        return None
    key = m.group(1)
    raw = m.group(2).strip()
    if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
        raw = raw[1:-1]
    elif len(raw) >= 2 and raw[0] == '"' and '"' not in raw[1:]:
        raw = raw[1:]
    return key, raw


def _unescape_string(s: str) -> str:
    """状态机反转义：把字面量 \\n \\t \\\\ \\\" 还原为实际控制字符。

    模型输出的工具参数中，转义序列是两个字面字符（如反斜杠+n），
    需要还原为真实字符（如换行符 0x0A）。
    """
    result: list[str] = []
    i = 0
    n = len(s)
    while i < n:
        if s[i] == '\\' and i + 1 < n:
            ch = s[i + 1]
            if ch == 'n':
                result.append('\n')
            elif ch == 't':
                result.append('\t')
            elif ch == '"':
                result.append('"')
            elif ch == "'":
                result.append("'")
            elif ch == '\\':
                result.append('\\')
            else:
                result.append(s[i])
                result.append(ch)
            i += 2
        else:
            result.append(s[i])
            i += 1
    return ''.join(result)


def _build_json_and_parse(tool_name: str, kv_lines: list[str]) -> dict | None:
    pairs: dict[str, str] = {}
    for line in kv_lines:
        result = _parse_kv_line(line)
        if result:
            pairs[result[0]] = _unescape_string(result[1])
    if not pairs:
        return None
    json_obj = {"name": tool_name, **pairs}
    try:
        return json.loads(json.dumps(json_obj, ensure_ascii=False))
    except (json.JSONDecodeError, ValueError):
        return None


def _apply_schema_types(args: dict, tool_schema: dict | None) -> dict:
    if not tool_schema:
        return args
    props = (tool_schema.get("parameters") or {}).get("properties") or {}
    out = {}
    for k, v in args.items():
        if not isinstance(v, str):
            out[k] = v
            continue
        t = (props.get(k) or {}).get("type")
        if t == "integer":
            try:
                out[k] = int(v)
                continue
            except (ValueError, TypeError):
                pass
        elif t == "number":
            try:
                f = float(v)
                out[k] = int(f) if f.is_integer() else f
                continue
            except (ValueError, TypeError):
                pass
        elif t == "boolean":
            if v == "true":
                out[k] = True
                continue
            elif v == "false":
                out[k] = False
                continue
        out[k] = v
    return out


def _expand_tilde(args: dict) -> dict:
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


def _find_schema(name: str, tools_schema: list[dict] | None) -> dict | None:
    if not tools_schema:
        return None
    for t in tools_schema:
        if t.get("function", {}).get("name") == name:
            return t["function"]
    return None


def parse_tool_blocks(text: str, tools_schema: list[dict] | None = None) -> tuple[str, list[dict]]:
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
        schema = _find_schema(current_name, tools_schema)
        parsed = _build_json_and_parse(current_name, current_kv_lines)
        if parsed:
            parsed.pop("name", None)
            parsed = _apply_schema_types(parsed, schema)
            parsed = _expand_tilde(parsed)
            blocks.append({"name": current_name, "arguments": parsed})
        current_name = None
        current_kv_lines = []

    for i, line in enumerate(lines):
        ls = line.rstrip('\r')
        tm = _TOOL_LINE_RE.match(ls)
        if tm:
            _commit()
            current_name = tm.group(1)
            current_kv_lines = []
            continue
        if current_name is not None:
            kv = _parse_kv_line(ls)
            if kv:
                current_kv_lines.append(ls)
                continue
            if ls.strip() == '':
                # 空行：预览下一行，如果是 key=value 或工具名则继续
                next_ls = lines[i + 1].rstrip('\r') if i + 1 < len(lines) else ''
                if _parse_kv_line(next_ls) or _TOOL_LINE_RE.match(next_ls):
                    continue
                # 否则提交工具块
                _commit()
            else:
                _commit()
        content_lines.append(ls)

    _commit()
    remaining = '\n'.join(content_lines).strip()
    remaining = re.sub(r'\n{3,}', '\n\n', remaining).strip()
    return remaining, blocks


def build_openai_tool_call(call_id: str, name: str, arguments: dict, idx: int = 0) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(arguments, ensure_ascii=False),
        },
    }


if __name__ == "__main__":
    tests = [
        ("无引号", "工具 Bash\ncommand=echo hello world"),
        ("有引号", '工具 Write\nfile_path="C:/tmp/test.txt"\ncontent="hello"'),
        ("content 含 \\n", "工具 Write\nfile_path=C:/tmp/test.txt\ncontent=line1\\nline2\\nline3"),
        ("反斜杠路径", "工具 Bash\ncommand=D:\\files\\test.py"),
        ("content 含工具关键词", "工具 Bash\ncommand=echo 不要使用 工具 Write\n\n这里有个陷阱"),
        ("多行 content + 空行", "工具 Write\nfile_path=C:/tmp/test.md\ncontent=# 标题\n\n## 第一节\n内容"),
        ("多工具", "工具 Bash\ncommand=echo 1\n\n工具 Bash\ncommand=echo 2"),
        ("空值", "工具 Write\nfile_path=C:/tmp/test.txt\ncontent="),
        ("Tool 大写", "Tool Bash\ncommand=echo hello"),
        ("混合引号", '工具 Write\nfile_path="C:/tmp/test.txt"\ncontent=hello world'),
        ("多工具连续", "工具 Bash\ncommand=echo 1\n工具 Read\nfile_path=C:/tmp/test.txt"),
        ("正文+工具+正文", "这是正文\n\n工具 Bash\ncommand=echo 1\n\n这是更多正文"),
    ]
    for name, text in tests:
        remaining, calls = parse_tool_blocks(text)
        print(f"=== {name} ===")
        print(f"  remaining: {repr(remaining[:80])}")
        print(f"  calls: {calls}")
        print()
