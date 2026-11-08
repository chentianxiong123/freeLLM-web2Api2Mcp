# freeLLM-web2Api2Mcp

> ⚠️ **本仓库为新代码线起点**（2026-11-08 起）。此前的代码已完成归档，历史与贡献全部保留。
>
> **主线方向已转向：Web 搜索 MCP + 外援老师 MCP。**

## 版本状态（旧版已过时）

| 版本 | 形态 | 状态 |
|---|---|---|
| **v1** | DeepSeek/Qwen 网页端 → OpenAI Chat Completions API 代理（供 Claude Code） | 🪦 **已过时/归档** |
| **v2** | 同一项目改造为 MCP Server（Streamable HTTP） | 🪦 **已过时/归档** |
| **v3（主线）** | **Web 搜索 MCP + 外援老师 MCP** | 🟢 **当前主线** |

> ⚠️ **v1 / v2 均已过时**，请勿再基于旧代码开发。
> v1 的详细工作与架构（含复刻中间层对接 React Agent 的每一环节）见 **[LEGACY.md](./LEGACY.md)** —— 那是大量心血，务必保留、不要丢。

## 旧代码去哪了？

| 位置 | 内容 |
|---|---|
| `archive/legacy-2026-08-mcp` | v2（MCP 版，2026-08-23） |
| `archive/go-rewrite` | 早期废弃分支（2026-06-28） |
| tag `legacy/0.4.0-mcp` | v2 固化的保险 tag |
| tag `python-legacy` | 早期 Python 版归档 tag |

**恢复旧代码**：`git checkout archive/legacy-2026-08-mcp`
**查看完整历史**：`git log --all --oneline`（63 commits，2 位贡献者：chentianxiong123 / dllm）

## 新主线（v3）：Web 搜索 MCP + 外援老师 MCP

- **Web 搜索 MCP**：为 AI 提供网页/科研/技术搜索能力（见现有 `searxng-mcp` 雏形，将升级为多 provider）
- **外援老师 MCP**：把外部 LLM（老师/专家）包装成 MCP 工具，供 coding agent 获取评审、教学、第二意见

（待填写：新项目说明、架构、使用方式）
