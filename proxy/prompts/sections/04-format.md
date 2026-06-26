---
id: format
title: 工具调用格式
enabled: true
order: 40
---

工具调用格式：
- 每个工具调用以 "工具 名称" 开头，独占一行，前面不能有空格
- 参数 key="value"，一行一个
- 多个工具依次列出，每个工具独立成块
- 工具块不要混入其他文字，先完成推理再调用工具
- 路径使用正斜杠（C:/Users/test.txt），不要用反斜杠

示例（单工具）：
工具 Write
file_path="C:/Users/test.txt"
content="hello"

示例（多工具）：
工具 Bash
command="Get-ChildItem -Name"
工具 Read
file_path="C:/Users/test.txt"
offset="1"
limit="10"