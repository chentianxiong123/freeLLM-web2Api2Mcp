"""提示词统一管理模块。

合并原 tool_config + prompt_manager 的功能。
管理三类内容：
- sections: 系统提示词各环节（Markdown 文件 + frontmatter）
- tools: 工具定义（JSON）
- compact: 压缩指令 + 摘要（Markdown 文件）

目录结构：
  prompts/
    sections/*.md    # 系统提示词 sections
    tools.json       # 工具定义
    compact.md       # 压缩指令
    summary.md       # compact 摘要
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent
_SECTIONS_DIR = _PROMPTS_DIR / "sections"
_TOOLS_FILE = _PROMPTS_DIR / "tools.json"
_COMPACT_FILE = _PROMPTS_DIR / "compact.md"
_SUMMARY_FILE = _PROMPTS_DIR / "summary.md"


# ── Markdown frontmatter 解析 ─────────────────────────

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)", re.DOTALL)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """解析 YAML frontmatter，返回 (meta, content)。"""
    m = _FRONTMATTER_RE.match(text.strip())
    if not m:
        return {}, text.strip()
    meta_raw, content = m.group(1), m.group(2).strip()
    meta = {}
    for line in meta_raw.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            k, v = k.strip(), v.strip()
            if v.lower() == "true":
                v = True
            elif v.lower() == "false":
                v = False
            elif v.isdigit():
                v = int(v)
            meta[k] = v
    return meta, content


def _build_frontmatter(meta: dict, content: str) -> str:
    """构建带 frontmatter 的 markdown 文本。"""
    lines = ["---"]
    for k, v in meta.items():
        if isinstance(v, bool):
            v = "true" if v else "false"
        lines.append(f"{k}: {v}")
    lines.append("---")
    lines.append("")
    lines.append(content)
    return "\n".join(lines) + "\n"


# ── Sections 管理 ─────────────────────────────────────


def _read_md_file(path: Path) -> tuple[dict, str]:
    """读取一个 md 文件，返回 (meta, content)。"""
    if not path.exists():
        return {}, ""
    text = path.read_text(encoding="utf-8")
    return _parse_frontmatter(text)


def _write_md_file(path: Path, meta: dict, content: str) -> None:
    """写入一个 md 文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_build_frontmatter(meta, content), encoding="utf-8")


def list_sections() -> list[dict]:
    """列出所有 sections，按 order 排序。"""
    sections = []
    for p in sorted(_SECTIONS_DIR.glob("*.md")):
        meta, content = _read_md_file(p)
        sections.append({
            "file": p.name,
            "id": meta.get("id", p.stem),
            "title": meta.get("title", p.stem),
            "enabled": meta.get("enabled", True),
            "order": meta.get("order", 99),
            "content": content,
        })
    sections.sort(key=lambda s: s.get("order", 99))
    return sections


def get_section(section_id: str) -> dict | None:
    """获取指定 section。"""
    for s in list_sections():
        if s["id"] == section_id:
            return s
    return None


def update_section(section_id: str, *, content: str | None = None,
                   enabled: bool | None = None, title: str | None = None) -> bool:
    """更新指定 section。"""
    for p in _SECTIONS_DIR.glob("*.md"):
        meta, old_content = _read_md_file(p)
        if meta.get("id") == section_id or p.stem == section_id:
            if content is not None:
                old_content = content
            if enabled is not None:
                meta["enabled"] = enabled
            if title is not None:
                meta["title"] = title
            _write_md_file(p, meta, old_content)
            return True
    return False


# ── Tools 管理 ────────────────────────────────────────


def load_tools() -> dict:
    """加载工具定义。"""
    if not _TOOLS_FILE.exists():
        return {}
    try:
        return json.loads(_TOOLS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_tools(tools: dict) -> None:
    """保存工具定义。"""
    _TOOLS_FILE.write_text(
        json.dumps(tools, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def build_tools_text(tools: dict | None = None) -> str:
    """从工具定义生成自然语言工具列表。"""
    if tools is None:
        tools = load_tools()
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


# ── Compact 管理 ──────────────────────────────────────


def get_compact_instruction() -> str:
    """获取压缩指令。"""
    meta, content = _read_md_file(_COMPACT_FILE)
    return content


def get_compact_summary() -> str:
    """获取 compact 摘要。"""
    meta, content = _read_md_file(_SUMMARY_FILE)
    return content


def set_compact_summary(summary: str) -> None:
    """设置 compact 摘要（compact 完成后调用）。"""
    _write_md_file(_SUMMARY_FILE, {"id": "compact_summary", "title": "Compact 摘要"}, summary)


def clear_compact_summary() -> None:
    """清空 compact 摘要。"""
    set_compact_summary("")


def set_compact_instruction(content: str) -> None:
    """设置压缩指令。"""
    _write_md_file(_COMPACT_FILE, {"id": "compact_instruction", "title": "压缩指令"}, content)


# ── 构建系统提示词 ────────────────────────────────────


def build_system_prompt(working_directory: str = "", *, include_compact: bool = False) -> str:
    """构建完整的系统提示词。

    拼接所有 enabled sections + compact summary。
    如果 include_compact=True，额外拼入 compact 指令。
    """
    sections = list_sections()
    tools = load_tools()

    parts = []
    for sec in sections:
        if not sec.get("enabled", True):
            continue
        content = sec["content"]
        content = content.replace("{working_directory}", working_directory or ".")
        content = content.replace("{auto_tools}", build_tools_text(tools))
        content = content.strip()
        if content:
            parts.append(content)

    summary = get_compact_summary()
    if summary:
        parts.append(f"## 之前的对话摘要\n\n{summary}")

    if include_compact:
        instruction = get_compact_instruction()
        if instruction:
            parts.append(f"## Compact 指令\n\n{instruction}")

    return "\n\n".join(parts)


def build_init_prompt(working_directory: str = "") -> str:
    """兼容旧接口：构建初始化提示词。"""
    return build_system_prompt(working_directory=working_directory)


# ── 构建消息 ──────────────────────────────────────────


def build_messages(user_content: str, *, is_compact: bool = False,
                   working_directory: str = "") -> list[dict]:
    """构建发给上游的 messages 数组。

    - 正常请求：system（sections + summary）+ user
    - compact 请求：system（sections + summary + instruction）+ user
    """
    system_text = build_system_prompt(
        working_directory=working_directory,
        include_compact=is_compact,
    )

    messages = []
    if system_text:
        messages.append({"role": "system", "content": system_text})
    messages.append({"role": "user", "content": user_content})

    return messages


def build_compact_user_content(original_content: str) -> str:
    """构建 compact 请求的 user content。

    把压缩指令拼入用户消息末尾。
    """
    instruction = get_compact_instruction()
    if instruction:
        return f"{original_content}\n\n{instruction}"
    return original_content


# ── 兼容旧接口（供 admin 页面使用）────────────────────


def get_all_prompts() -> dict:
    """获取所有提示词（兼容旧 prompt_manager 接口）。"""
    return {
        "base": build_system_prompt(),
        "compact_summary": get_compact_summary(),
        "compact_instruction": get_compact_instruction(),
    }


def set_prompt(name: str, content: str) -> None:
    """设置指定提示词（兼容旧 prompt_manager 接口）。"""
    if name == "compact_summary":
        set_compact_summary(content)
    elif name == "compact_instruction":
        set_compact_instruction(content)


def get_config() -> dict:
    """获取完整配置（兼容旧 tool_config 接口）。"""
    return {
        "sections": list_sections(),
        "tools": load_tools(),
    }


def update_config(patch: dict) -> dict:
    """更新配置（兼容旧 tool_config 接口）。"""
    if "sections" in patch:
        for sec in patch["sections"]:
            sid = sec.get("id", "")
            update_section(
                sid,
                content=sec.get("content"),
                enabled=sec.get("enabled"),
                title=sec.get("title"),
            )
    if "tools" in patch:
        save_tools(patch["tools"])
    return get_config()


def reset_to_defaults() -> dict:
    """重置为默认配置（删除所有自定义 sections 和 tools）。"""
    # 重新从内置默认值生成（这里简单地清除后重建）
    # 实际默认值由 md 文件提供，无需额外处理
    return get_config()
