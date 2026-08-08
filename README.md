# MewCode

MewCode 是一个最小可用的命令行 AI 助手。它支持终端多轮对话，并能在当前工作区内执行一组受限工具。

## 安装

```powershell
python -m pip install -e .[dev]
```

## 配置

创建用户配置目录，并复制示例配置：

```powershell
New-Item -ItemType Directory -Force "$HOME\.mewcode"
Copy-Item .\examples\config.yaml "$HOME\.mewcode\config.yaml"
```

运行 MewCode 前，请先通过环境变量设置 API key。配置文件只保存 `env:OPENAI_API_KEY` 这类引用，不保存真实密钥。
```
$env:OPENAI_API_KEY = "你的 OpenAI API Key"
如果测 Anthropic：
$env:ANTHROPIC_API_KEY = "你的 Anthropic API Key"
```

编辑 `~/.mewcode/config.yaml`，把 `active` 设置为要使用的 profile：

```yaml
active: openai-main
profiles:
  - name: openai-main
    protocol: openai
    model: gpt-5.6
    base_url: https://api.openai.com/v1
    api_key: env:OPENAI_API_KEY
    thinking: false
```

## 运行

```powershell
mewcode
```

也可以使用：

```powershell
python -m mewcode
```

进入 REPL 后，输入 `/exit` 或 `/quit` 退出。对话历史只保存在当前进程内，程序退出后不会保存。

## Agent Loop

普通消息会启动 ReAct Agent Loop。MewCode 会持续让模型思考、调用工具、读取结果并调整下一步，直到模型给出不再包含工具调用的最终回复，无需逐步追加提示。

每次运行最多调用模型 20 次；如果第 20 次响应仍要求工具，MewCode 会停止且不会执行最后一批工具。运行还会在用户按下 `Ctrl+C`、连续三轮只请求未知工具、Provider 流出错或内部错误时停止。`Ctrl+C` 只取消当前一轮，清理完成后可以继续在同一 REPL 中输入任务。

模型一次返回多个工具调用时，相邻的只读工具会并发执行，最大并发数为 4；写文件、编辑文件和运行命令按原始顺序独占执行。终端会实时显示文本、简短工具状态、迭代进度和 Token 用量，不显示完整工具参数或大段工具结果。

## Plan Mode

需要先审阅计划再执行时，使用两阶段命令：

```text
mew> /plan 为配置加载器增加环境变量校验并补测试
agent: iteration 1
tool: search_code ...
tool: search_code ok - src/mewcode/config.py:...
1. 检查现有配置加载路径……
2. 增加校验并补充回归测试……
agent: completed

mew> /do
agent: iteration 1
tool: edit_file ...
tool: edit_file ok - Edited src/mewcode/config.py
...
已完成实现和验证。
agent: completed
```

`/plan <任务>` 只向模型开放 `read_file`、`find_files` 和 `search_code`，并保存最近一次成功生成的计划。`/do` 恢复全部工具执行该计划；成功后清除计划，失败或取消时保留计划以便重试。

当前阶段不包含权限系统、上下文压缩和交互式工具确认。

## 工具系统

MewCode 会把以下内置工具暴露给模型：

- `read_file(path)`：读取当前工作区内的 UTF-8 文本文件。
- `write_file(path, content)`：在当前工作区内写入 UTF-8 文本。
- `edit_file(path, old_text, new_text)`：只在原文恰好匹配一次时替换文本。
- `run_command(command, timeout_seconds?)`：在工作区根目录执行命令。
- `find_files(pattern)`：用 glob 模式查找文件。
- `search_code(query, path?)`：搜索 UTF-8 文本文件内容。

工具只能访问启动 `mewcode` 时所在的当前工作区。父目录跳转、越界绝对路径和符号链接越界都会被拒绝。

命令工具默认超时 30 秒，最大超时 120 秒，并会拦截明显危险的破坏性命令。
