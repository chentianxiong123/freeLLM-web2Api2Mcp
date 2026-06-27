---
id: format
title: 工具调用格式
enabled: true
order: 40
---

工具调用格式：
- 每个工具调用以 "工具 名称" 开头，独占一行
- 参数 key=value，一行一个，无引号
- 路径用正斜杠（C:/Users/test.txt）
- content 中换行用 \n，不用真实换行符
- 多工具依次列出，每个工具独立成块

示例：
工具 Bash
command=echo hello world

示例（写文件）：
工具 Write
file_path=C:/Users/test.txt
content=第一行\n第二行\n第三行