---
id: example
title: 示例
enabled: true
order: 60
---

示例：

用户：看看桌面有什么文件
工具 Bash
command=Get-ChildItem C:/Users/A1/Desktop | Select-Object -ExpandProperty Name

用户：读取并修改 test.txt
工具 Read
file_path=C:/Users/A1/Desktop/test.txt
工具 Write
file_path=C:/Users/A1/Desktop/test.txt
content=新的内容

用户：创建一个 C 程序
工具 Write
file_path=C:/Users/A1/Desktop/hello.c
content=#include <stdio.h>\nint main() {\n    printf("Hello World\\n");\n    return 0;\n}
工具 Bash
command=gcc C:/Users/A1/Desktop/hello.c -o C:/Users/A1/Desktop/hello.exe