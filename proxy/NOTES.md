# 架构（重构后 v0.4）

## 分层

| 层 | 目录 | 职责 |
|---|---|---|
| 路由 | `main.py` | FastAPI 路由、中间件、管理 API |
| 编排 | `pipeline/chat.py` | chat 全流程 |
| 下游 | `agents/*` | CC / generic：stream、housekeeping、末条提取 |
| 上游 | `backends/*` | 网页端：DeepSeek（可扩展） |
| 协议 | `handler.py` + `tool_format.py` | OpenAI 响应、DS 暗语解析 |
| 网页 API | `deepseek_api.py` | DS HTTP（仅 deepseek backend 用） |

## 环境变量

- `WEB_BACKEND=deepseek`（默认）
- `DOWNSTREAM_AGENT=claude_code|generic`（空则按 header 自动）

## 扩展

- 新网页端：`backends/foo_web/` + `registry._BACKENDS`
- 新下游：`agents/foo.py` + `registry._AGENTS`

## 历史问题（部分已缓解）

- main 上帝模块 → chat 已迁至 pipeline
- admin 保存丢 id/title → merge_sections_with_defaults + hidden fields
- Provider 抽象 → backends.WebBackend 包装 DeepSeekProvider
