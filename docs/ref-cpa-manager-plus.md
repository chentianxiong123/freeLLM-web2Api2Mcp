# 参考项目沉淀：CPA-Manager-Plus（CPAMP）

> 2026-11-08 | 参考项目 `seakee/CPA-Manager-Plus`（★4k，Go）克隆自 `ref-project/CPA-Manager-Plus`
> 定位：**CPA / CLIProxyAPI 管理面板 + AI 网关可观测性**（请求/用量/成本/配额/失败/账户健康）。
> 说明：CPAMP **不转发 LLM 流量**（选路由 CLIProxyAPI/CPA 本体做），它是管理/监控面板。

## 1. 概述

- 自托管 CPA / CLIProxyAPI 管理面板 + AI 网关**可观测性**仪表盘
- 操作：providers / credentials / OAuth / plugins / 配置；本地持久化：请求历史 / 成本分析 / 账户自动化
- 结构：`apps/manager-server/`（`internal/worker` 调度 / `internal/model` 数据模型 / `internal/usage` 用量 / `internal/service/proxy` 代理 / `internal/http` HTTP / `internal/repository` sqlite 存储）

## 2. 核心方法（沉淀，非重点）

### 2.1 账户健康 → 自动禁用（`AccountActionCandidateWorker`）
- `HandleUsageEvents(ctx, cfg, events)`：接收用量事件
- `handleCandidate(ctx, candidate)`：处理账户动作候选
- `maybeAutoDisable(ctx, item, candidate)`：异常账户**自动禁用**（降风控）
  - 判定 `AutoDisableEligible` → 取 baseURL/managementKey → 身份验证 → `authFileMutations.Acquire`（**同 auth file 串行**）→ `ResolveVerifiedStatusMutationTarget` → 禁用

### 2.2 429 限流冷却（`QuotaCooldown`）
- `QuotaCooldownOwnerUsage429 = "cpamp_usage_429"`：被限流自动冷却
- 状态 `active → recovered/skipped`；`WindowKind` 窗口类型

### 2.3 并发协调（`authFileMutations.Acquire`）
- 同一 auth file 的修改**串行**（mutation coordinator）——避免并发改同一账户配置

### 2.4 配额/用量监控
- `account_quota_snapshot` / `account_quota_window` / `model_price_rules`：配额快照/窗口/模型定价
- `dead_letter_event`：失败事件（死信）

## 3. 路由策略（网关重点）

### 3.1 HTTP 路由注册（`http/router`）
```
/usage-service/updates          → updates.Handle（可观测性推送）
/usage-service/info|config      → system/managerConfig
/usage-service/quota-cooldowns  → quotaCooldown
/health /status /setup
/                                → rootHandler（统一分发）
```

### 3.2 rootHandler 分发（`controller/proxy`）
```
/ (proxy)
  ├─ Management       ← isManagementPath（管理路径）
  ├─ ModelList        ← isModelListPath（模型列表路径）
  ├─ V8APIKeysConfig  ← V8 API keys 配置路径
  └─ CPAResource      ← CPA 插件/资源路径
```

### 3.3 路径分类判定（`service/proxy`）
```
isManagementPath / isModelListPath / isCPAPluginResourcePath /
isCPAV8APIKeysConfigPath / isStrictManagementPath / isCanonicalRequestPath
```

> **要点**：CPAMP 路由 = **管理路径分类**（管理 vs 模型列表 vs 插件资源 vs API keys 配置）。
> **请求→provider 选路（负载均衡/轮换/健康检查）在 CLIProxyAPI（CPA）本体**，不在 CPAMP。

## 4. 结论

- CPAMP 的方法（账户健康/429冷却/并发协调/配额）→ **可借鉴到 tutor 的供应商健康管理**（平台异常自动停用/冷却）
- **路由策略**：CPAMP 只做**管理路径分类**；真正的**网关选路**需看 **CLIProxyAPI（CPA）本体**
