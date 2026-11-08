# 参考项目沉淀：CLIProxyAPI 本体路由策略

> 2026-11-08 | 本体 `router-for-me/CLIProxyAPI`（★57k，Go）克隆自 `ref-project/CLIProxyAPI`（2294 文件/49M）
> 定位：**CLIProxyAPI（CPA）本体**——把 AI 订阅（Claude Code/Codex/Grok 等）包装成 OpenAI 兼容 API 的**代理网关**。
> 重点：**路由策略**（选上游 auth）——4 种内置选择器 + 冷却 + 资格 + 权重。

## 1. 概述

- 把 AI 订阅（Antigravity/ChatGPT Codex/Claude Code/Grok...）包装成 OpenAI 兼容 API
- 核心选路：`internal/pluginhost/scheduler.go` `Host.PickAuth`（可插拔调度器）
- 选路实现：`sdk/cliproxy/auth/selector.go`（选择器）+ `conductor_selection.go`（可用筛选）+ `conductor_cooldown.go`（冷却）

## 2. 各种路由策略（核心）

### 2.1 `RoundRobinSelector`（轮询）
- `getSelectorAvailableAuths` 过滤（冷却/禁用/不可用）→ `preferCodexWebsocketAuths` 偏好 → `successorIndex`（按 ID 轮转，`lastPicked[key]` 记上次取后继）
- 轮询选路：按 auth ID 轮转

### 2.2 `WeightedRoundRobinSelector`（平滑加权轮询）
- `positiveWeightAuths`（权重>0 才参与）→ `authWeightVector`（权重向量）→ `pickSmoothWeightedAuth`（平滑加权 round-robin）
- 加权轮询：权重向量 + 平滑算法

### 2.3 `FillFirstSelector`（先填满）
- 返回 `available[0]`（第一个可用，顺序塞满）
- 先填满：一直用第一个，满了才下一个

### 2.4 `SessionAffinitySelector`（会话亲和）
- `extractExplicitSessionIDs`（显式 session id）→ `pickLCP`（LCP 匹配）→ `extractSessionIDs`（headers/body/metadata）→ **按 session id 绑定同一 auth**
- 会话亲和：同会话→同一上游（**对应 tutor 要的"同一消费者→同一会话"**）

## 3. 选路前置（冷却/资格/权重）

### 3.1 冷却（`conductor_cooldown.go`）
- `SetQuotaCooldownDisabled`（全局开关）/ `SetTransientErrorCooldownSeconds`（**408/500/502/503/504 瞬时错误冷却**）
- auth 出错 → 冷却该 auth（跳过）

### 3.2 资格（`isAuthBlockedForModel`）
- `Disabled/StatusDisabled` → 排除；冷却中 → 排除；模型不支持 → 排除

### 3.3 权重（`credentialweight`）
- `Normalize(weight)`：非正 → 0（**权重 0 排除出加权路由**）；上限 1,000,000
- `ParseString/ParseValue`：默认 1

## 4. 选路流程

```
可用 auth（冷却/禁用/资格过滤，availableAuthsForSelector）
  → 选择器 Pick（RoundRobin / WeightedRoundRobin / FillFirst / SessionAffinity）
  → 返回选中 auth → 转发请求
```

## 5. 结论（对 tutor 的借鉴）

| CLIProxyAPI 路由策略 | tutor 可借鉴 |
|---|---|
| **SessionAffinity**（会话亲和） | **同消费者→同一会话**（用户明确要的）——已有先例 |
| **WeightedRoundRobin** | 多供应商**加权轮换**（降风控） |
| **FillFirst** | 优先填满一个平台（先用一个，失败换） |
| **冷却（408/500/502/503/504）** | 平台错误 → 冷却该平台（自动降风控） |
| **资格过滤** | 供应商启停（disabled 排除） |

> **核心洞察**：CLIProxyAPI 的会话亲和（SessionAffinity）+ 加权轮换（WeightedRoundRobin）+ 冷却 = **tutor 调度策略的完整蓝图**（会话亲和已实现，轮换/冷却可移植）。
