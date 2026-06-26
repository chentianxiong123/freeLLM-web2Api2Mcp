---
id: example_code
title: 代码写入示例
enabled: true
order: 65
---

代码写入示例：

用户：创建 hello.c，输出 Hello World

你：好的，创建 C 文件。

工具 Write
file_path="C:\Users\A1\Desktop\hello.c"
content="#include <stdio.h>\nint main() {\n    printf(\"Hello World\\n\");\n    return 0;\n}"

你：编译试试。

工具 Bash
command="gcc /c/Users/A1/Desktop/hello.c -o /c/Users/A1/Desktop/hello.exe"

要点：
- content 里的 \n 是实际换行
- printf 里的 \" 是转义双引号
- gcc 路径用 Unix 风格