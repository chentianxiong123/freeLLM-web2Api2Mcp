# LEGACY —— v1 / v2 历史存档（DeepSeek Web Agent Proxy）

> **这是一份存档文档，记录旧版本的全部工作与架构。**
> ⚠️ **v1 与 v2 均已过时**，主线已转向 **Web 搜索 MCP + 外援老师 MCP**（见 README）。
> 本文件的价值：**把当年"复刻中间层对接 React Agent 每一环节"的大量心血完整保留下来**，供回顾、复用、吸取教训。

---

## 0. 一句话总览

这个仓库原是一个 **DeepSeek/Qwen 网页端免费对话 → OpenAI Chat Completions API 的本地反代**，专门给 **Claude Code（OpenAI 模式）** 当后端模型用。核心难点不在"调 DeepSeek"，而在**中间层**：要把 Claude Code 这种 React（Agentic 循环）客户端的每一个环节，翻译成上游网页端协议能理解的形式，再把上游的流式/tool 输出翻译回客户端能用的形式。**这个中间层是全部工作量所在，且极度耦合、可移植性差**——正是这份文档要保存的东西。

---

## 1. 版本沿革

| 版本 | 时间 | 形态 | 状态 |
|---|---|---|---|
| **v1** | 2026-06-16 ~ 06-28 | DeepSeek/Qwen 网页端 → OpenAI API 代理（分层架构 + React Agent 中间层） | 🪦 过时/归档 |
| **v2** | 2026-08-23 | 同一项目改造为 **MCP Server**（Streamable HTTP + fastmcp） | 🪦 过时/归档 |
| **v3** | 2026-11-08 起 | **Web 搜索 MCP + 外援老师 MCP** | 🟢 主线 |

- v1 的完整代码：`archive/legacy-2026-08-mcp`（分支）＝ v2 减去 8 月 MCP 改动
- v2 的完整代码：`archive/legacy-2026-08-mcp`、tag `legacy/0.4.0-mcp`
- 历史：`git log --all`（63 commits，2 位贡献者）

---

## 2. 两位贡献者的分工

| 贡献者 | 提交数 | 时间 | 角色 |
|---|---|---|---|
| **dllm** | 16 | 2026-06-16 ~ 06-19 | **开山作者**：搭起项目底座（初始 commit、多会话、token 追踪、模块化 core/ + providers/、DeepSeek 工具块解析、React 循环本地执行工具、规则引擎雏形） |
| **chentianxiong123** | 47 | 2026-06-21 ~ 11-08 | **主开发者**：v1 分层架构 + React Agent 中间层 + v2 MCP 改造 + 本次归档 |

> ⚠️ 两人共用同一邮箱 `2036680567@qq.com`，仅 author 名字不同。

---

## 3. v1 完整架构（中间层对接 React Agent 的每一环节）

```
客户端 (Claude Code / Generic OpenAI)
   │  POST /v1/chat/completions
   ▼
┌─────────────────────────── 中间层（proxy/）───────────────────────────┐
│ ① agents/          下游客户端适配    识别谁在调、是否 housekeeping     │
│ ② gateway.py       请求过滤          拦截 CC housekeeping、提干净prompt│
│ ③ rules.py+json    规则引擎          拦截/剥离 CC 注入标签            │
│ ④ request_parser   请求解析          React 续接判定 (role=tool vs user)│
│ ⑤ prompts/         提示词管理        Markdown sections 可开关/注入    │
│ ⑥ backends+providers 上游抽象        DeepSeek/Qwen 网页端统一封装     │
│ ⑦ pipeline/chat.py 主流程编排        会话、续接、token、事件流        │
│ ⑧ handler.py       响应组装          Provider Event → OpenAI 响应     │
│ ⑨ tool_format.py   工具格式转换      模型输出"工具 X"块→tool_calls    │
│ ⑩ tool_buffer.py   并行工具缓冲      Qwen 多工具 → CC 并行结果→合并   │
│ ⑪ session.py       会话管理          多账号会话、续接点、usage        │
│ ⑫ approval.py      工具审批          权限门                           │
└────────────────────────────────────────────────────────────────────────┘
   │  HTTPS (curl_cffi 模拟 Chrome 指纹)
   ▼
   DeepSeek / Qwen 网页端 (SSE)
```

**每一环节的职责与实现（这是核心，逐条记录）：**

### ① 下游客户端适配层 `agents/`
- `claude_code.py`：识别 Claude Code（user-agent 含 `claude-cli`/`claude-code`，或 `x-claude-code-session-id` 头），并判定其 **housekeeping** 请求
- `generic.py`：兜底，任何 OpenAI 兼容客户端，不做特殊处理
- `base.py`：适配器基类，定义 `extract_upstream_turn` / `clean_prompt_for_rules` / `detect` / `is_housekeeping`
- `registry.py`：按 header/body 自动选择适配器（默认 claude_code → generic）

### ② 请求过滤 `gateway.py`
- **Claude Code 的 housekeeping 请求**（标题生成、建议模式等）直接丢弃，不发给上游
- `extract_clean_user_prompt`：只保留最后一条 `role=user`，取其 content 中最后一个 `type=text` 块，剔除所有 harness/CC 注入标签 → 干净 prompt

### ③ 规则引擎 `rules.py` + `rules.json`
- 规则结构：`id/name/match_type(substring|regex)/scope(request|response)/pattern/action(block|strip|intercept)/enabled`
- 针对 Claude Code 注入的拦截（r001–r009）：
  - `r001 block` 起一个标题（CC 的标题生成请求）
  - `r002 strip` `<system-reminder>...</system-reminder>`（CC 注入的 system-reminder 标签）
  - `r003 block` `[SUGGESTION MODE:`（CC 后台建议模式）
  - `r004 intercept` `Your task is to create a detailed summary of the conversation so far`（**/compact 压缩请求** → 触发上游会话重置）
  - `r005–r009 strip` LOCAL_COMMAND_CAVEAT / COMMAND_NAME / COMMAND_MESSAGE / COMMAND_ARGS / LOCAL_COMMAND_STDOUT（CC 本地命令注入标签）
- 可在线增删改（routes/rules.py + admin 页）

### ④ 请求解析 `request_parser.py`（React 续接判定）
- `build_ds_input(body) → ChatRequest`：**只看末尾消息**，判断这是"React 续接"还是"新的人话"
  - 最后一条 `role=tool` → **react 续接** → 发这条 tool 的结果给上游
  - 最后一条 `role=user` → 新的人话 → 发这条 user 内容
- 这是"对接 React Agent 循环"的关键：Claude Code 在工具调用后会以 `role=tool` 回传结果，必须把它当成上游对话的**续接点**，而不是新对话

### ⑤ 提示词管理 `prompts/`
- `manager.py`：统一管理 sections（Markdown + frontmatter）、tools（JSON）、compact（压缩指令）、summary
- `sections/*.md`：系统提示词各环节，**带 frontmatter（id/title/enabled/order）可开关、可排序、可拼接**（01-role / 02-workspace / 03-tools / 04-format / 06-example / 08-rules）
- `03-tools.md` 含 `{auto_tools}` 占位符 → 运行时注入实际工具定义
- 压缩指令 + 摘要单独文件（配合 r004 处理 `/compact`）
- `sections_backup_20260626_135928/`：重构前的 sections 备份（留痕）

### ⑥ 上游抽象 `backends/` + `providers/`
- `providers/base.py`：`UpstreamProtocol`（上游协议接口）+ `ContinuationState`（**续接点管理，共享**）+ `EventBridge`（同步 generator → AsyncIterator[Event]）+ `ConfigResolver`
- `backends/base.py`：Backend 基类（chat_turn / is_authenticated / active_model / 会话生命周期）
- `backends/deepseek_web/`：`deepseek_api.py`(457行, HTTP 客户端)、`login.py`、`protocol.py`、`provider.py`、**`pow_native.py` + `pow_solver.js`（PoW 鉴权求解）**
- `backends/qwen_web/`：`qwen_api.py`(471行)、`provider.py`、`protocol.py`
- 多上游统一到一套抽象 → 换上游只改 backend，不动中间层

### ⑦ 主流程 `pipeline/chat.py`
- 编排：解析请求 → 选 agent → housekeeping/规则拦截 → 取会话 → 调 backend → 组装事件流 → 返回 SSE/JSON
- 每请求生成 request_id、会话 key、token 计量

### ⑧ 响应组装 `handler.py`
- 把 Provider 的 Event 流组装成 OpenAI Chat Completions 响应（流式/非流式）
- `make_skip_response`：housekeeping / 规则命中时返回"跳过"响应（避免 CC 重试）

### ⑨ 工具格式转换 `tool_format.py`（React Agent 工具对接核心）
- 模型输出是自然语言工具块（`工具 X` / `工具结束` + `KEY=value` 行）→ 解析成 OpenAI `tool_calls`
- 多行 content 解析：**支持引号内换行 + KV 分组顺序**（8dda7a8 重写）
- `_unescape` 处理字面 `\n \t` 转义（否则 Write 工具换行丢失，205f312/050be3b）
- `tool_sieve` / `tool_dsml` 相关：流式筛分 + DSML 解析

### ⑩ 并行工具缓冲 `tool_buffer.py`（React Agent 并行对接）
- Qwen 一次输出**多个**工具块 → Claude Code **并行**发回多个 `tool` 结果
- 需要提前建缓冲（响应发送前）设定期望数量 → 陆续收齐 → **合并后**再回给上游
- 核心时序修复多次（8f8fc67 / a4ff397 / b124a38 / fd6727b）：不能只取最后一个结果，要**全部结果都进缓冲**

### ⑪ 会话管理 `session.py`
- 持久化 `sessions.json`：`active_session_id` + 多会话状态（label / last_message_id / message_count / created_at / last_used_at）
- 兼容旧结构自动迁移；续接点重启后不丢失（fb46d40 修复）
- token 计量：`new_input_tokens` / `cached_tokens` / `output_tokens`，全部**自己估算**不依赖上游（91bec54/df3d019/df67c28/d6916b0）

### ⑫ 工具审批 `approval.py`
- 工具调用权限门（admin 可配置是否审批、哪些工具需要审批）

---

## 4. 技术要点与踩坑记录（"非常费劲"的地方）

1. **React Agent 续接语义**：`role=tool` 回传 ≠ 新对话，必须走上游续接点（`ContinuationState`），否则上下文全乱。
2. **Claude Code 注入标签**：CC 会注入 `system-reminder`、`[SUGGESTION MODE:`、`/compact` 摘要、`LOCAL_COMMAND_*` 等，必须在发上游前拦截/剥离（rules.json r001–r009）。漏一个就会污染上下文。
3. **工具块解析脆弱性**：模型输出是自然语言块而非 JSON，解析要处理引号内换行、转义、KV 顺序、多行——`tool_format.py` 反复重写（789b7eb/8dda7a8/63b2078）。
4. **并行工具结果合并**：多工具并行时 CC 会分开回传，必须缓冲到全部到齐再合并，否则丢结果或错序（tool_buffer.py 多次时序修复）。
5. **PoW 鉴权**：DeepSeek 网页端需要 PoW 求解（pow_native.py + pow_solver.js WASM），上游改协议就失效。
6. **会话/续接点持久化**：重启后续接点会丢，需持久化并在启动恢复（fb46d40）。
7. **token 计量**：上游的 usage 不可靠，全部自己估算（中文 1.65 字符/token，英文 3.5 字符/token，Qwen 官方比率）。
8. **上游错误静默**：必须显式返回错误（502/SSE 错误事件），否则 Claude Code 以为空内容会重试（03f87c7/081a4af/cc23f17）。
9. **可移植性差的根源**：中间层深度耦合 Claude Code 专属协议（UA 识别、注入标签、react 循环、tool 块格式、compact 拦截），换客户端（如 Cursor/OpenCode）就要重做适配层。这是 v1 最大的代价。

---

## 5. v2（MCP 改造，2026-08-23）

- 新增 `mcp_server.py`（fastmcp>=3.0）+ `mcp_pipeline.py`，把 DeepSeek 网页对话包装成 MCP 工具：
  - `ask_deepseek(query, model, thinking, search)` / `deepseek_models()` / `deepseek_status()`
- Streamable HTTP + SSE 传输（后移除 SSE，只留 Streamable HTTP），协议 v2025-06-18
- 挂在 `/{api_key}/mcp`（带鉴权 + allowed_hosts/origins 传输安全）
- admin 增加 MCP 管理页
- 结论：**v2 证明了这条路可做成 MCP，但仍是"单一 DeepSeek 网页端"的封装**，模型名硬编码（deepseek-v4-flash/v4-pro），无动态发现，且延续了 v1 的封号风险——这是 v2 过时、主线转向 Web 搜索 + 外援老师 MCP 的原因。

---

## 6. 关键文件（便于查找）

```
proxy/
  main.py               入口 + 路由 + MCP 挂载
  gateway.py            请求过滤（housekeeping + 干净 prompt）
  handler.py            响应组装（Event → OpenAI 响应）
  request_parser.py     React 续接判定
  tool_format.py        工具块 → tool_calls 解析
  tool_buffer.py        并行工具结果缓冲
  rules.py + rules.json 规则引擎（CC 注入拦截）
  session.py            多会话/续接点/usage
  approval.py           工具审批
  agents/               下游客户端适配（claude_code / generic）
  backends/             上游抽象（deepseek_web / qwen_web）
  providers/            上游协议接口 + 续接点 + 事件桥
  pipeline/chat.py      主流程编排
  prompts/              提示词管理（sections/tools/compact）
```

---

## 7. 恢复与参考

- **查看 v1 完整代码**：`git checkout archive/legacy-2026-08-mcp`
- **只看某个文件**：`git show archive/legacy-2026-08-mcp:proxy/pipeline/chat.py`
- **全部提交历史**：`git log --all --oneline`
- **当前主线**：见 `README.md`（Web 搜索 MCP + 外援老师 MCP）

> **最后提醒**：这份文档保存的是 **v1/v2 的心血与教训**。中间层对 React Agent 的对接经验（续接语义、注入拦截、工具块解析、并行合并）在未来的 Web 搜索 / 外援老师 MCP 里依然有借鉴价值——尤其是"如何把一个外部能力干净地接进 agent 循环"这件事。
