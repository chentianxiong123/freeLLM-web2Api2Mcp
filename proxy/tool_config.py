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


DEFAULT_TEMPLATE = """我们来玩一个游戏。

现在你是一个"幕后黑手"，你戴着耳麦，通过一台终端机操控一个叫 Claude Code 的智能体。

你不需要自己做任何操作，你只需要"发指令"给 Claude Code，它会帮你执行。
每次只能发一条指令，收到执行结果后你再决定下一步。

指令格式：

工具 工具名
参数名="参数值"
工具结束

—— 规则 ——
1. 需要操作时用 "工具 名称" 开头，"工具结束" 结尾
2. 参数写成 key="value"，一行一个
3. 不需要操作就只回复想法，不带指令
4. 指令块前后可以有你的分析"""


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
    """构造完整的初始化提示词 = 模板 + 工具列表"""
    data = _load()
    template = data.get("template", DEFAULT_TEMPLATE)

    # 自动生成工具列表块
    tools = data.get("tools", DEFAULT_TOOLS)
    tool_lines = ["\n—— 可用工具 ——"]
    for name, spec in tools.items():
        tool_lines.append(f"\n{name}")
        tool_lines.append(f"  用途：{spec.get('description', '')}")
        req = spec.get("required", [])
        if req:
            tool_lines.append(f"  必填参数：{', '.join(req)}")
        opt = spec.get("optional", {})
        if opt:
            for k, v in opt.items():
                tool_lines.append(f"  可选参数：{k}（{v}）")

    return template + "\n" + "\n".join(tool_lines)