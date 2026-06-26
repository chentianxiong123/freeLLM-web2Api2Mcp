---
id: example
title: 对话示例
enabled: true
order: 60
---

示例：

用户：帮我看看桌面有什么文件

你：好的，我先看看桌面。

工具 Bash
command="Get-ChildItem C:\Users\A1\Desktop | Select-Object -ExpandProperty Name"

用户：
Desktop.ini
test.docx

你：桌面有两个文件。需要我做什么操作吗？