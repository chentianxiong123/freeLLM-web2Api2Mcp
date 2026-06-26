---
id: escape
title: PowerShell 转义规则
enabled: true
order: 50
---

PowerShell 转义规则：
- 命令中的双引号必须转义为 \"
- Write 工具的 content 参数：\n = 换行，\\n = 字面量反斜杠+n
- 路径用 Windows 格式：C:\\Users\\name\\file.txt
- gcc 等编译器用 Unix 路径：/c/Users/name/file.c