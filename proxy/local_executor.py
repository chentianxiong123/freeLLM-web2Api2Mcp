"""本地工具执行器

当 DeepSeek 响应包含 tool_calls 时，本地执行这些工具并返回结果。
供 React 循环使用：proxy 代替 CC 执行 DeepSeek 的工具调用。

支持的工具：
  - Bash: 执行 shell 命令
  - Read: 读取文件
  - Write: 写入文件
  - Edit: 精确替换文件内容
"""

import subprocess
import os
import config


def _get_shell():
    """根据配置返回 shell 命令。"""
    cfg = config.load_config()
    terminal = cfg.get("terminal", "powershell")
    if terminal == "cmd":
        return ["cmd", "/c"]
    elif terminal == "bash":
        return ["bash", "-c"]
    else:  # powershell (default)
        return ["powershell", "-Command"]


def execute_bash(command: str, timeout: int = 30, cwd: str = None) -> str:
    """执行 shell 命令，返回 stdout+stderr。"""
    shell = _get_shell()
    if cwd is None:
        cwd = os.getcwd()
    try:
        result = subprocess.run(
            shell + [command],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
        output = result.stdout
        if result.stderr:
            output += ("\n" if output else "") + result.stderr
        return output.strip() if output else "(no output)"
    except subprocess.TimeoutExpired:
        return f"[错误] 命令超时（{timeout}秒）"
    except Exception as e:
        return f"[错误] {e}"


def read_file(file_path: str, offset: int = None, limit: int = None) -> str:
    """读取文件内容。"""
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        if offset is not None:
            start = max(0, offset - 1)  # 转为 0-indexed
            lines = lines[start:]
        if limit is not None:
            lines = lines[:limit]
        return "".join(lines) if lines else "(empty file)"
    except FileNotFoundError:
        return f"[错误] 文件不存在: {file_path}"
    except Exception as e:
        return f"[错误] {e}"


def write_file(file_path: str, content: str) -> str:
    """写入文件（覆盖）。"""
    try:
        os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        return "成功"
    except Exception as e:
        return f"[错误] {e}"


def edit_file(file_path: str, old_string: str, new_string: str) -> str:
    """精确替换文件内容。"""
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        if old_string not in content:
            return f"[错误] old_string 未找到 in {file_path}"
        new_content = content.replace(old_string, new_string, 1)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        return "成功"
    except FileNotFoundError:
        return f"[错误] 文件不存在: {file_path}"
    except Exception as e:
        return f"[错误] {e}"


def execute_tool(name: str, arguments: dict, cwd: str = None) -> str:
    """执行单个工具调用，返回结果文本。"""
    try:
        if name == "Bash":
            cmd = arguments.get("command", "")
            timeout = int(arguments.get("timeout", 30))
            return execute_bash(cmd, timeout=timeout, cwd=cwd)
        elif name == "Read":
            fp = arguments.get("file_path", "")
            offset = arguments.get("offset")
            limit = arguments.get("limit")
            if offset is not None:
                offset = int(offset)
            if limit is not None:
                limit = int(limit)
            return read_file(fp, offset=offset, limit=limit)
        elif name == "Write":
            fp = arguments.get("file_path", "")
            content = arguments.get("content", "")
            return write_file(fp, content)
        elif name == "Edit":
            fp = arguments.get("file_path", "")
            old = arguments.get("old_string", "")
            new = arguments.get("new_string", "")
            return edit_file(fp, old, new)
        else:
            return f"[错误] 未知工具: {name}"
    except Exception as e:
        return f"[错误] 执行 {name} 失败: {e}"


def execute_tool_calls(tool_calls: list[dict], cwd: str = None) -> list[str]:
    """执行多个工具调用，返回结果列表（按顺序）。"""
    results = []
    for tc in tool_calls:
        name = tc.get("name", "")
        args = tc.get("arguments", {})
        result = execute_tool(name, args, cwd=cwd)
        results.append(result)
    return results
