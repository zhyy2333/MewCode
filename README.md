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

可用启动参数切换权限模式：

```powershell
mewcode --permission-mode strict
mewcode --permission-mode default
mewcode --permission-mode allow
```

也可以使用：

```powershell
python -m mewcode
```

进入 REPL 后，输入 `/exit` 或 `/quit` 退出。使用 `/permissions` 查询当前权限模式，或用 `/permissions strict|default|allow` 在会话中切换。对话历史只保存在当前进程内，程序退出后不会保存。

## Agent Loop

普通消息会启动 ReAct Agent Loop。MewCode 会持续让模型思考、调用工具、读取结果并调整下一步，直到模型给出不再包含工具调用的最终回复，无需逐步追加提示。

每次运行最多调用模型 20 次；如果第 20 次响应仍要求工具，MewCode 会停止且不会执行最后一批工具。运行还会在用户按下 `Ctrl+C`、连续三轮只请求未知工具、Provider 流出错或内部错误时停止。`Ctrl+C` 只取消当前一轮，清理完成后可以继续在同一 REPL 中输入任务。

模型一次返回多个工具调用时，相邻的只读工具会并发执行，最大并发数为 4；写文件、编辑文件和运行命令按原始顺序独占执行。终端会实时显示文本、简短工具状态、迭代进度和 Token 用量，不显示完整工具参数或大段工具结果。

## 结构化系统提示与缓存

每次模型请求都使用同一套结构化系统提示。稳定前缀依次包含 Identity、System Constraints、Task Mode、Action Execution、Tool Use、Tone and Style 和 Text Output；Environment、调用方提供的自定义指令、已激活 Skill 内容、长期记忆以及当次 `<system-reminder>` 位于稳定边界之后。调用方未提供可选内容时，不会自动发现项目指令、激活 Skill 或创建记忆。

Plan 和 Execute 模式按一次 Agent Run 内的真实模型调用次数注入提醒：第 1, 5, 9, 13, 17 次使用完整指令，其余调用使用精简提醒。Direct Mode 不增加模式提醒。提醒使用系统语义，不会作为用户消息写入对话历史。

工具定义和稳定系统提示会按 Provider 协议组成确定性的缓存前缀。缓存是否实际写入或命中仍取决于模型支持、前缀长度和服务端状态，MewCode 不保证每次命中。Token 行会显示：

```text
tokens: in=... out=... total=... cache-read=... cache-write=... cumulative=... cumulative-cache-read=... cumulative-cache-write=...
```

本阶段只接受调用方直接提供的自定义指令、Skill 和长期记忆内容，不加载项目指令文件、不自动激活 Skill、不生成或持久化记忆，也不接入真实 MCP Server。

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

当前阶段不包含网络请求限制、资源配额、审计日志、上下文压缩和自动化质量评估。

## 权限系统

每个有效工具调用在执行前都会经过危险命令黑名单、内置文件工具路径沙箱、分层规则、权限模式与人工确认。黑名单和路径沙箱是不可绕过的安全上限；即使使用 `allow` 模式或显式 allow 规则，危险命令和越界文件路径仍会被拒绝。权限拒绝会作为工具失败返回模型，Agent Loop 可以改用更安全的策略继续工作。

三档模式的含义如下：

- `strict`：deny 直接拒绝；本会话已确认的精确 allow 自动执行；持久 allow 与未匹配调用仍需首次确认。
- `default`：采用明确的 allow/deny，未匹配调用需要确认。
- `allow`：deny 仍然生效，其余调用自动执行。

规则按会话、项目本地、项目共享、用户全局的顺序解析。持久化文件位置为：

- 用户全局：`~/.mewcode/permissions.yaml`
- 项目共享：`<workspace>/.mewcode/permissions.yaml`
- 项目本地：`<workspace>/.mewcode/permissions.local.yaml`

三个 YAML 文件格式相同：

```yaml
rules:
  - rule: "run_command(git *)"
    result: allow
  - rule: "write_file(src/generated/**)"
    result: deny
```

规则使用实际工具名和主要参数，支持精确与 glob 匹配。同层中精确规则优先于 glob，固定文本更多者优先，具体度并列时 deny 获胜。命令 glob 的 `*` 可匹配空格；路径 glob 的 `*` 不跨 `/`，`**` 可递归跨目录。用 `\\`、`\*`、`\?`、`\[`、`\]` 表示字面量反斜杠或 glob 字符。

需要确认时可选择拒绝、仅本次、本会话或永久。永久放行只把当前调用的精确 allow 写入项目本地 `permissions.local.yaml`；该文件默认不提交，项目共享 `permissions.yaml` 可以提交。

路径沙箱仅约束 MewCode 内置的读取、写入、编辑、查找和搜索工具。`run_command` 子进程从工作区启动，但本阶段没有操作系统级文件隔离；它仍受危险命令黑名单、权限规则、模式与人工确认保护。

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
