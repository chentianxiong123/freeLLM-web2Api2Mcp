"""工具调用配置

存储：proxy/tool_config.json
{
    "sections": [
        {"id": "role", "enabled": true, "title": "角色定义", "content": "..."},
        ...
    ],
    "tools": { ... }
}

每个 section 可独立开关、编辑，按顺序拼接成初始化消息。
支持占位符：{auto_tools} → 自动生成工具列表, {working_directory} → 工作目录
"""

import json
import time
from pathlib import Path

_FILE = Path(__file__).parent / "tool_config.json"


DEFAULT_SECTIONS = [
    {
        "id": "role",
        "enabled": True,
        "title": "角色定义",
        "content": "我们来玩一个协作游戏。\n\n你是我的技术搭档，通过终端一起完成任务。\n你负责思考和发指令，我负责执行并告诉你结果。",
    },
    {
        "id": "workspace",
        "enabled": True,
        "title": "工作目录",
        "content": "当前工作目录: {working_directory}",
    },
    {
        "id": "project",
        "enabled": False,
        "title": "项目背景",
        "content": "",
    },
    {
        "id": "tools",
        "enabled": True,
        "title": "可用工具",
        "content": "{auto_tools}",
    },
    {
        "id": "format",
        "enabled": True,
        "title": "格式要求",
        "content": "重要格式要求：\n- \"工具 名称\" 必须在行首，前面不能有空格\n- \"工具结束\" 必须在行首\n- 参数格式必须是 key=\"value\"，一行一个\n- 可以一次调用多个工具，每个工具块单独一行",
    },
    {
        "id": "escape",
        "enabled": True,
        "title": "引号转义规则",
        "content": "引号转义规则（非常重要）：\n- 命令中如果包含双引号，必须转义为反斜杠+双引号\n- 例如 PowerShell 命令：command=\"powershell -Command \\\"Get-ChildItem\\\"\"\n- 例如简单命令：command=\"dir C:\\Users /ad /b\"\n- 不要嵌套双引号，否则解析会失败",
    },
    {
        "id": "example",
        "enabled": True,
        "title": "完整对话示例",
        "content": "完整对话示例：\n\n用户：帮我看看桌面有什么文件，然后创建一个 test.txt 写入文件列表\n\n你：好的，我先看看桌面。\n\n工具 Bash\ncommand=\"Get-ChildItem C:\\Users\\A1\\Desktop | Select-Object -ExpandProperty Name\"\n工具结束\n\n用户：\nDesktop.ini\ntest.docx\n111.txt\n\n你：桌面有这些文件，我现在创建 test.txt 写入列表。\n\n工具 Write\nfile_path=\"C:\\Users\\A1\\Desktop\\test.txt\"\ncontent=\"Desktop.ini\\ntest.docx\\n111.txt\"\n工具结束\n\n用户：\n成功\n\n你：完成了！已创建 test.txt，包含 Desktop.ini、test.docx、111.txt。",
    },
    {
        "id": "rules",
        "enabled": True,
        "title": "规则",
        "content": "规则：\n1. 一次只发一条指令\n2. 收到结果再决定下一步\n3. 任务完成后主动总结并结束\n4. 指令块前后可以有你的分析\n5. 失败了告诉我为什么，我来决定是否重试",
    },
]

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
        "sections": DEFAULT_SECTIONS.copy(),
        "tools": DEFAULT_TOOLS,
        "updated_at": int(time.time()),
    }


def _build_tools_text(tools: dict) -> str:
    """从 tools 定义生成自然语言工具列表。"""
    lines = ["可用工具："]
    idx = 1
    for name, spec in tools.items():
        desc = spec.get("description", "")
        req = spec.get("required", [])
        opt = spec.get("optional", {})
        lines.append(f"\n{idx}. {name} - {desc}")
        if req:
            lines.append(f"   参数：{', '.join(f'{p} (必填)' for p in req)}")
        if opt:
            lines.append(f"   可选：{', '.join(f'{k} - {v}' for k, v in opt.items())}")
        idx += 1
    return "\n".join(lines)


def _migrate_if_needed(data: dict) -> dict:
    """将旧的 template 格式迁移到 sections 格式。"""
    if "sections" in data:
        return data
    template = data.get("template", "")
    if not template:
        data["sections"] = DEFAULT_SECTIONS.copy()
        return data

    for sec in DEFAULT_SECTIONS:
        if sec["id"] == "tools":
            sec["enabled"] = True
        elif sec["id"] == "workspace":
            sec["enabled"] = True
    data["sections"] = DEFAULT_SECTIONS.copy()
    return data


def _load() -> dict:
    if not _FILE.exists():
        data = _default_data()
        _save(data)
        return data
    try:
        data = json.loads(_FILE.read_text(encoding="utf-8"))
        data = _migrate_if_needed(data)
        return data
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
    if "sections" in patch:
        data["sections"] = patch["sections"]
    if "tools" in patch:
        data["tools"] = patch["tools"]
    data["updated_at"] = int(time.time())
    _save(data)
    return data


def build_init_prompt(working_directory: str = "") -> str:
    """构造完整的初始化提示词：拼接所有 enabled section，替换占位符。"""
    data = _load()
    sections = data.get("sections", DEFAULT_SECTIONS)
    tools = data.get("tools", DEFAULT_TOOLS)

    parts = []
    for sec in sections:
        if not sec.get("enabled", True):
            continue
        content = sec.get("content", "")

        content = content.replace("{working_directory}", working_directory or ".")
        content = content.replace("{auto_tools}", _build_tools_text(tools))

        content = content.strip()
        if content:
            parts.append(content)

    return "\n\n".join(parts)
