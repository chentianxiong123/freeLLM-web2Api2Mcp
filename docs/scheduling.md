# 调度策略（会话亲和 + 串行排队 + 缓存路由 + 轮询）

> 2026-11-08 | v3 外援老师核心 | 用户确认的调度策略。
> 核心目标：**风控最小**（严格串行不并发）+ **会话亲和**（同消费者同会话）+ **省额度**（缓存）。

## 1. 目标与原则

| 原则 | 说明 |
|---|---|
| **严格拒绝并发** | LLM 调用**一次只一个**，绝不并发发请求 |
| **串行排队** | 所有请求进**全局一个 FIFO 队列**，一个接一个处理 |
| **轮询伪并发** | 客户端**提交后轮询结果**；服务端串行处理——多个消费者可同时"挂着轮询"，体验并发，实际串行 |
| **会话亲和** | **同一消费者（consumer）→ 同一会话**，短时间请求匹配进同一个 session，不每次新开 |
| **缓存路由** | 请求先查缓存，命中直接返回（不调 LLM、不耗额度） |
| **供应商启停** | 每个平台（供应商）可**启停**，只操作启用的 |
| **轮换（可选）** | 多供应商轮换调用降风控（默认关，需要才开） |

## 2. 架构

```
请求 (consumer, platform, prompt)
  │
  ▼
①【缓存路由】 key = consumer + platform + hash(prompt)
  │  命中 → 返回缓存（不排队、不调LLM、不耗额度）
  ▼  未命中
②【会话亲和】 consumer → conversation_id 映射
  │  有 → resume(cid) 续聊（同一消费者同一会话，上下文连贯）
  │  无 → 新会话（记录 conversation_id 回映射）
  ▼
③【串行队列】 全局一个 FIFO 队列，严格一次一个（绝不并发）
  │  客户端提交后【轮询】结果；服务端串行处理
  ▼
④ 调 LLM（resume续聊 / 新会话提问）→ 平台侧会话 URL 续接
  │
  ▼
⑤ 写缓存 + 更新 consumer→conversation_id → 返回
```

## 3. 调度细节

### 3.1 缓存路由
- **key**：`consumer + platform + hash(prompt)`（精确匹配，同消费者同平台同提问 → 复用）
- **TTL**：短时间（默认几分钟），过期失效
- **命中**：直接返回缓存（不排队、不调 LLM、不耗额度）
- **未命中**：进串行队列 → 调 LLM → **写缓存**

### 3.2 会话亲和（续接）
- **映射**：`consumer_id → {platform, conversation_id, last_used_at}`
- **key**：`consumer + platform`（同消费者每平台各一 session，互不串）
- **续接**：命中 → `resume(conversation_id)`（goto 平台会话 URL 续聊）；未命中 → 新会话
- **TTL 回收**：session 空闲超时（如 30min）→ 回收，下次新开
- **续接体系**：浏览器驱动用 **URL 会话 id**（`conversation_id_pattern`/`conversation_url_fmt`），
  不是 v1 API 逆向的 `last_message_id`——续接概念同，实现走 URL 会话 id

### 3.3 串行队列 + 轮询
- **串行**：全局一个 FIFO 队列，worker 一次处理一个（严格拒绝并发）
- **轮询**：请求提交后返回"任务 id"，客户端轮询 `/task/{id}` 拿结果（伪并发）
- **控频**：处理间隔受 `min_interval~max_interval`（随机延迟，风控）

### 3.4 供应商管理
- **启停**：`enabled: {platform: bool}`（启用的才参与 ask/auto/巡检）
- **轮换（可选）**：`rotate=true` 时 auto/聚合轮换供应商（分散风控），默认关

### 3.5 容错
- 单平台失败 → 试下一个（auto 模式）
- 缓存/会话失效 → 自动重建（检测失效后重新匹配）

## 4. 状态（内存/持久化）

| 状态 | 结构 | 说明 |
|---|---|---|
| `sessions` | `{consumer_platform: {conversation_id, last_used_at}}` | 会话亲和映射（TTL 回收） |
| `cache` | `{key: {answer, ts}}` | 结果缓存（TTL） |
| `queue` | FIFO 列表 | 串行排队任务 |
| `enabled` | `{platform: bool}` | 供应商启停 |
| `tasks` | `{task_id: {status, result}}` | 轮询结果存储 |

## 5. 为什么这样（风控/体验权衡）

- **严格串行**：平台风控最怕并发/高频异常行为 → 一次一个最稳
- **轮询伪并发**：多个消费者不互相阻塞（都能"挂着"），但 LLM 仍一次一个
- **会话亲和**：同消费者上下文连贯（多轮对话），且不频繁新开会话（省资源/降风控）
- **缓存**：重复提问不重复调 LLM（省额度），命中即回

## 6. 待实现清单（按此调度策略）

- [ ] 缓存路由（key=consumer+platform+hash(prompt)，TTL）
- [ ] 会话亲和（consumer→conversation_id 映射 + TTL 回收）
- [ ] 串行队列（全局 FIFO，严格一次一个）
- [ ] 轮询任务（task_id → /task/{id} 轮询结果）
- [ ] 供应商启停（enabled per platform）
- [ ] 轮换（rotate，可选开关）
