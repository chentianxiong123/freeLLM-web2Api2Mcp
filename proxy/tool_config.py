"""工具调用配置

存储：proxy/tool_config.json
{
    "template": "我们来玩一个游戏...",
    "tools": {
        "Read": {
            "description": "读文件",
            "required": ["file_path"],
            "optional": {"offset": "起始行（数字）", "limit": "读多少行（数字）"}
        },
        ...
    }
}
"""

import json
import time
from pathlib import Path

_FILE = Path(__file__).parent / "tool_config.json"


DEFAULT_TEMPLATE = """好的，我来帮你处理。

比如你说"看看桌面上有什么"，我会这样做：

我先看看桌面有什么文件。

工具 Bash
command="Get-ChildItem C:/Users/a1/Desktop"
工具结束

然后等你告诉我执行结果，我再决定下一步。"""


DEFAULT_TOOLS = {
    "Bash": {
        "description": "执行 shell 命令",
        "required": ["command"],
        "optional": {
            "description": "命令说明",
            "timeout": "超时毫秒（数字）",
        },
    },
    "Read": {
        "description": "读文件",
        "required": ["file_path"],
        "optional": {
            "offset": "起始行号（数字）",
            "limit": "读取行数（数字）",
        },
    },
    "Write": {
        "description": "写文件（覆盖写入）",
        "required": ["file_path", "content"],
        "optional": {},
    },
    "Edit": {
        "description": "精确替换文件内容",
        "required": ["file_path", "old_string", "new_string"],
        "optional": {},
    },
}


def _default_data() -> dict:
    return {
        "template": DEFAULT_TEMPLATE,
        "tools": DEFAULT_TOOLS,
        "updated_at": int(time.time()),
    }


def _load() -> dict:
    if not _FILE.exists():
        data = _default_data()
        _save(data)
        return data
    try:
        return json.loads(_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _default_data()


def _save(data: dict) -> None:
    _FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_config() -> dict:
    return _load()


def update_config(patch: dict) -> dict:
    data = _load()
    if "template" in patch:
        data["template"] = patch["template"]
    if "tools" in patch:
        data["tools"] = patch["tools"]
    data["updated_at"] = int(time.time())
    _save(data)
    return data


def build_init_prompt() -> str:
    """构造完整的初始化提示词 = 模板 + 工具列表（自然语言版）"""
    data = _load()
    template = data.get("template", DEFAULT_TEMPLATE)

    # 自然语言工具列表（简洁版）
    tools = data.get("tools", DEFAULT_TOOLS)
    tool_lines = ["\n我能用的："]
    for name, spec in tools.items():
        desc = spec.get("description", "")
        tool_lines.append(f"  {name} - {desc}")

    return template + "\n" + "\n".join(tool_lines)