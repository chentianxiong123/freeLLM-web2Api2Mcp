---
id: compact_summary
title: Compact 摘要
---

# 对话详细总结

## 1. 用户的核心需求和目标
-   **核心需求**：为几个朋友组建纯 P2P、免费、无公网 IP 的隔离网络，用于暴露本机端口互通服务（如网盘、API）。
-   **体验要求**：必须像“开房间”一样简单（生成房间号 → 朋友输入即入），明确拒绝 Tailscale 的企业级账号绑定、邮件邀请、ACL 审批重流程。当前任务**：确认 ZeroTier 是否符合需求，并尝试通过工具自动下载 ZeroTier Windows 安装包到桌面 `C:/Users/A1/Desktop/`。
-   **附带任务**：将选型讨论和折腾过程整理成文档保存到桌面；验证工具调用环境是否恢复正常。

## 2. 涉及的技术概念、框架、工具
-   **组网工具对比**：Tailscale（三层 IP 隧道、企业零信任、OAuth 注册）、ZeroTier（二层虚拟以太网、Network ID 开房模式、邮箱注册）、n2n/Yggdrasil（全开源但无 GUI）。ZeroTier 特性**：二层 MAC 层隧道、支持 ARP/广播/mDNS、端口零限制暴露、官方 Planet 闭源但客户端开源、房间内默认全通无 ACL。Windows 环境**：PowerShell、Invoke-WebRequest、curl、TLS1.2 强制设置、Windows 防火墙专用网络配置 **安全加固**：应用层认证（FileBrowser 密码、API Token）、最小端口暴露、防火墙入站规则。

## 3. 检查或修改过的文件
-   **`C://P2P组网选型与折腾记录.md`**：完整记录了需求、三方案对比表、ZeroTier 部署三步流程、安全加固 PowerShell 命令、Tailscale 不适配原因、后续优化方向。
1/Desktop/get_zt_link.ps1`**：为绕过 Bash→PowerShell 引号转义问题而写入的脚本（注：之前写入版本存在语法错误，需重写），预期内容如下：
    ```powershell
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $r = Invoke-WebRequest -Uri 'https://www.zerotier.com/download/' -UseBasicParsing
    $msiLinks = $r.Links | Where-Object { $_.href -match '\.msi$' } | Select-Object -ExpandProperty href
    if ($msiLinks) {
        Write-Host "FOUND_MSI_LINK: $msiLinks"
    } else {Host "NO_MSI_FOUND"
        $r.Links | Select-Object -First 20 -Expand }
    ```/A1/Desktop/t5.txt`、`t6.txt`、`test3.txt`**：多次写入 "hello" 用于验证 Write 工具格式是否正常。

## 4. 遇到的错误及解决方案
| 错误现象 | 根因 | 解决尝试 | 最终状态 |
| :--- | :--- | :连续 exit code 127，连 `echo hello` 都失败 | 底层 shell 进程挂掉或权限回收 | 等待环境自愈后重试成功 | ✅ 环境恢复 |
| `Invoke-WebRequest` 返回 404 | ZeroTier MSI 直链 URL 已变更 | 改为从官网下载页动态提取真实链接 | ⏳ 进行中 |
| PowerShell `-Command` 中 `$var =` 被吞掉变量名 | Bash 传递给 PowerShell 时 `$` 被外层 shell 解释 | 改用 `-EncodedCommand` Base64 编码 | ❌ 编码格式不匹配仍报 127 |
| `-File` 参数报路径不存在 | 反斜杠路径在传递中被吃掉 | 改用正斜杠 `C:/.ps1` |路径修正后报解析错误 |
| PS1 脚本报 `TerminatorExpectedAtEndOfString` | Write 工具写入时首行被意外加了前导双引号 | 重新用 Write 覆盖写入纯净内容 | ⏳ 待重新执行验证 |

## 5. 当前工作进度和待办事项已完成**：环境恢复验证、选型文档写入桌面、多次 Write 工具格式验证、PS1 脚本写入（需确认内容纯净）。
-   **进行中**：通过 PS1 脚本提取 ZeroTier 真实 MSI 下载链接并下载安装包到桌面 **待办**1.  重新写入并执行 `get_z` 确认脚本解析正常并获取真实 MSI URL。
    2.  用正确 URL 下载 ZeroTier_One.msi 到桌面3.  指导用户安装后验证服务启动及加入网络。
    4.  若直连率低，提供自建 Moon 节点指南。

## 6. 用户的偏好和约束语言风格**：中文口语化，称呼“兄弟”，喜欢直给结论、厌恶绕弯子。
-   **技术偏好**：极度排斥企业级重流程（OAuth/邀请制/ACL），追求“游戏开房”式轻量体验；对开源程度有关注但可接受“客户端开源+官方免费服务器”折中方案。
-   **工具约束**：Windows + PowerShell 环境；路径必须用正斜杠；Write content 中换行用 `\n`；命令中双引号需 `\"` 转义。
-   **交互偏好**：不要过度解释，一次一条指令，收到结果再决定下一步；出错时直接承认并切换方案，不要反复重试相同失败路径。
