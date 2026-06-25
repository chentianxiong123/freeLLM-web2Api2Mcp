---
id: escape
title: PowerShell 转义规则
enabled: true
order: 50
---

PowerShell 转义规则（非常重要）：

## 引号转义
- 命令中如果包含双引号，必须转义为反斜杠+双引号
- 例如：command="powershell -Command \"Get-ChildItem\""
- 不要嵌套双引号，否则解析会失败

## Write 工具 content 参数转义（极重要）
- content 里的 \n = 换行符
- content 里的 \\n = 字面量反斜杠+n（两个字符）
- 写代码时，代码中的 \n（如 C 语言）要写成 \\n
- 示例：写 C 代码 putchar('\n'); 要写成 content="putchar('\\n');"
- 示例：写多行文本 content="第1行\n第2行\n第3行"
- 单引号直接写，不需要转义

## 路径处理
- PowerShell 命令用 Windows 路径：C:\\Users\\name\\file.txt
- Write/Edit 工具的 file_path 参数用 Windows 路径：C:\\Users\\name\\file.txt
- gcc/编译器在 Bash 下要用 Unix 路径：gcc /c/Users/name/heart.c
