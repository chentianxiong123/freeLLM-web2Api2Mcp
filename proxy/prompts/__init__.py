"""提示词管理包。

统一管理 sections（系统提示词）、tools（工具定义）、compact（压缩指令+摘要）。

用法：
    from prompts import manager
    manager.build_system_prompt()
    manager.get_compact_summary()
    manager.set_compact_summary("...")
"""
from .manager import (
    build_system_prompt,
    build_init_prompt,
    build_messages,
    build_compact_user_content,
    list_sections,
    get_section,
    update_section,
    load_tools,
    save_tools,
    get_compact_instruction,
    get_compact_summary,
    set_compact_summary,
    clear_compact_summary,
    set_compact_instruction,
    get_all_prompts,
    set_prompt,
    get_config,
    update_config,
    reset_to_defaults,
)
