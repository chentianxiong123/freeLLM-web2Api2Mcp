# 架构问题与未来规划

## 当前核心问题

### 1. main.py 是上帝模块
路由、Provider 初始化、审批流程、账号、会话、工具配置全部塞在一起。
改一处可能牵连其他，不利于扩展。

### 2. handler.py 责任过载
同时处理：DS 消息构建、React 循环、SSE 流式、工具块检测、响应收集。
换模型或换 agent 需要动这个文件，风险高。

### 3. Provider 抽象虚设
虽然有 `base.py` 的 `ChatProvider`，但 handler 和 main 到处直接依赖
DeepSeek 的 event 机制（`Event(type="content")` 等）。
换模型（Gemini / Ollama / Anthropic）必须重写 handler。

### 4. 上下文全靠 DS 网页端
无本地上下文管理。session_id、message_id 全是 DeepSeek 内部概念。
换模型、换会话方式、或不用 DeepSeek 时全部失效。

### 5. React 循环写死在 handler 里
不支持嵌套 agent、不支持并行、不支持子 agent。
以后想扩展成多 agent 协作架构必须重写。

### 6. 工具系统散落四处
- 定义在 `tool_config.json`
- 解析在 `tool_format.py`
- 执行在 `local_executor.py`
- 调用在 `handler.py`

加一个工具要改 4 个地方，没有插件化机制。

### 7. 会话和账号不同步
`sessions.py` 和 `accounts.py` 各自维护状态。
新建 session 后未同步到 account config，导致 "invalid message id" 错误。

### 8. 缺乏 agent 适配层
当前硬编码适配 Claude Code 的 OpenAI API 格式。
未来要适配不同 agent（OpenCode、Claude Code、Pi、Codex 等），
它们的请求格式、响应要求、工具系统不同，需要抽象层。

## 未来重构方向

### 分层架构
| 层 | 职责 |
|---|---|
| **路由层** | FastAPI routes only，纯粹请求分发 |
| **Agent 适配层** | 统一 agent 请求格式 → 内部标准格式 |
| **Provider 抽象** | `chat(messages) → response`，屏蔽 DS/Gemini/Ollama 差异 |
| **Context 管理器** | 独立管理历史消息，不依赖外部 session_id |
| **工具系统** | 定义+解析+执行+注册，插件化，增删工具不改其他代码 |
| **Agent 引擎** | 支持 React 循环、子 agent、嵌套调用的可扩展引擎 |
| **评估/记录层** | Token 统计、调用记录、错误追踪 |

### 优先级
1. Provider 抽象（换模型）
2. Agent 适配层（换 agent）
3. Context 管理器（摆脱 DS session）
4. 工具系统插件化
5. Agent 引擎（子 agent / multi-agent）
