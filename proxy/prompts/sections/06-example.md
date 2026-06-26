---
id: example
title: 示例
enabled: true
order: 60
---

示例：

用户：看看桌面有什么文件

工具 Bash
command="Get-ChildItem C:/Users/A1/Desktop | Select-Object -ExpandProperty Name"

用户：读取并修改 test.txt

工具 Read
file_path="C:/Users/A1/Desktop/test.txt"
工具 Write
file_path="C:/Users/A1/Desktop/test.txt"
content="新的内容"