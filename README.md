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
    context_window: 128000
```

`context_window` 可省略；旧配置无需迁移，MewCode 会统一采用保守的 128000 Token 默认值。需要为兼容模型设置更小窗口时，可以在 Profile 中显式填写不小于 21193 的整数。启动时会完整校验所有 Profile（包括非活动项）及其 API Key 环境变量；独立 Skill 可以按名称复用其中一个 Profile。

### MCP Server

MewCode 支持 MCP `2025-11-25` 的工具发现与调用。用户级 Server 写在 `~/.mewcode/config.yaml`，项目级 Server 写在当前工作区的 `.mewcode/config.yaml`；两个文件使用 `mcp_servers` map。不同名 Server 合并，同名 Server 由项目条目整项替换，不做字段深合并。

本地 Server 使用 stdio，命令和参数作为 argv 直接启动，不经过 shell：

```yaml
mcp_servers:
  local-tools:
    transport: stdio
    command: python
    args: ["tools/local_mcp.py"]
    env:
      SERVICE_TOKEN: "${LOCAL_MCP_TOKEN}"
```

远程 Server 使用 Streamable HTTP：

```yaml
mcp_servers:
  team-api:
    transport: http
    url: https://mcp.example.com/mcp
    headers:
      Authorization: "Bearer ${TEAM_MCP_TOKEN}"
```

`${VAR}` 只在 stdio 的 `env` 值和 HTTP 的 `headers` 值中展开。协议 header 由 MewCode 控制；HTTP 默认校验证书且不跟随重定向。项目配置能够启动本地程序并发送认证 header，因此只应在受信任的项目中启用 MCP Server。

发现到的工具以 `<server>__<tool>` 为公开名；非法或超长名称会确定性规范化并追加短哈希。所有 MCP 工具固定按 `SIDE_EFFECT` 处理，权限目标为 `<public_name>(invoke)`：仅本次只放行当前调用，本会话或永久规则放行该公开工具后续使用任意参数的调用。Server 暂时离线时，其已有 namespace 权限规则可以休眠，不会影响其他工具启动。

每个 Server 在一次 MewCode 进程中复用同一会话。单个 Server 的配置、启动或运行失败不会影响其它 MCP Server 和内置工具；运行期失败后调用快速返回，不自动重连、重启或重新初始化。退出时 MewCode 会关闭 stdio 子进程和 HTTP Session。

本阶段只接入 MCP 工具，不支持资源、提示词、采样、动态工具更新、健康检查、自动重连、长期 SSE GET、OAuth、Registry 安装或二进制结果落盘，也不支持 MCP `2026-07-28` 及其它协议版本。

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

默认启动会自动恢复当前项目 30 天内最近一次可用会话。也可以强制新建或指定恢复：

```powershell
mewcode --new
mewcode --resume 20260811-120000-abcd
```

`--new` 与 `--resume` 互斥。指定会话不存在、已过期、正被另一进程占用或无法恢复时，程序会明确报错，不会静默改用其他会话。

也可以使用：

```powershell
python -m mewcode
```

进入 REPL 后，以 `/` 开头的输入由本地命令系统处理，不会先交给 Agent。公开命令如下：

| 命令 | 作用 |
|---|---|
| `/help [command]` | 列出公开命令，或查看单个命令的描述、用法、参数提示和别名 |
| `/compact` | 显式尝试压缩较早的对话历史 |
| `/clear` | 仅清除当前终端显示，不修改会话、记忆或模式 |
| `/plan` | 进入持续的 PLAN 模式，后续普通消息强制只读 |
| `/do` | 退出 PLAN 模式，恢复 DEFAULT 执行模式 |
| `/session` | 显示当前会话 ID、标题、恢复状态、消息数和忙闲状态的安全摘要 |
| `/memory` | 显示项目/用户记忆条数、索引容量和后台更新状态，不显示记忆正文 |
| `/permission [strict\|default\|allow]` | 查询或切换当前权限模式；兼容别名为 `/permissions` |
| `/status` | 显示模式、会话、权限、Token、上下文和记忆的核心摘要 |
| `/tasks` | 本地列出当前进程内的活动与终态子 Agent 任务摘要 |
| `/task <id>` | 非阻塞查看一个子任务的状态、结果和用量 |
| `/task cancel <id>` | 取消指定的活动子任务；重复或终态取消保持幂等 |
| `/worktrees` | 只读列出由 MewCode 管理的 Worktree、状态、路径和临时分支 |
| `/worktree delete <name> [--force]` | 删除指定的非活动 Worktree；默认保护未提交修改和未推送提交 |
| `/reset` | 原子清空当前会话消息、待执行计划和 Skill 激活状态，并恢复 `[DEFAULT]` |

所有有效 Skill 也会自动注册为 `/<skill-name> [input]`，因此内置的 `/commit`、`/review` 和 `/test` 会与系统命令一起出现在帮助和补全中。

`/exit` 及其兼容别名 `/quit` 仍可退出，但作为隐藏兼容命令不出现在帮助和补全中。命令名称大小写不敏感；未知命令会提示使用 `/help`，不会发送给 AI。

输入命令前缀后可按 Tab 补全：单个匹配直接补齐，多个匹配显示候选菜单，光标进入参数区域后不再提供命令名候选。底部状态栏始终显示共享模式标记 `[DEFAULT]` 或 `[PLAN]`。

`/status` 的 Token 数据覆盖当前进程内当前会话的全部模型调用，包括普通对话、PLAN、Skill、上下文压缩和自动记忆更新；Provider 未报告的累计字段显示为 `n/a`，不会用估算值代替。

## 子 Agent 系统

主 Agent 通过始终稳定的 `agent` 工具委派独立任务。工具只有 `type`、`task`、`role`、`background` 四个参数：`defined` 必须指定已加载角色，默认在前台等待；`fork` 不接受角色或 `background` 参数并始终进入后台。定义式任务超过 10 秒会原地转为后台，也可在运行时按 `Ctrl+B` 手动转后台；这不会取消、重启或重计任务。`Ctrl+C` 仍取消当前主运行以及仍与其绑定的前台子任务，已经解除到后台的任务继续执行。

角色是带严格 YAML frontmatter 的 Markdown 文件。项目级 `<workspace>/.mewcode/agents/` 覆盖用户级 `~/.mewcode/agents/`，再覆盖包内置角色，最后覆盖启动时显式注入的插件根；高层无效定义会产生诊断并回退到低层有效定义，同层有效重名会拒绝启动。目录只在启动时读取，没有热重载。`isolation` 可选，缺省为 `shared`：

```markdown
---
name: code-reviewer
description: Review code changes without modifying them.
tools:
  - read_file
  - find_files
  - search_code
disallowed_tools: []
model: inherit
max_turns: 20
permission_mode: default
isolation: worktree
---
You are an independent code reviewer...
```

`model: inherit` 使用委派父请求的 Profile；其他值必须是配置中已有的 Profile 名。`haiku`、`sonnet`、`opus` 没有内置别名，只有用户实际创建同名 Profile 时才有效。完整示例见 `examples/agents/code-reviewer.md` 和 `examples/agents/worktree-coder.md`；内置 `explore` 角色只开放 `read_file`、`find_files`、`search_code`。

定义式子 Agent 从空历史和固定角色正文启动，只复制人工指令与长期记忆，不继承父对话、活动 Skill 或临时 Hook prompt。Fork 首轮复用产生委派调用的实际父请求 prompt、消息前缀、工具顺序和输出上限，并只在尾部追加新任务，以便 Provider 有机会复用缓存；缓存实际命中不作保证。两类任务的消息、权限 session、文件读取观察、上下文归档和 Token 统计彼此隔离；`shared` 角色仍使用主工作区，`worktree` 角色使用独立 Git Worktree。

工具能力采用多层交集：父模式安全上限、角色白名单、角色黑名单、启动时冻结的后台能力名单和全局禁止名单共同收窄。`agent`、`load_skill` 不能在子 Agent 中执行，禁止嵌套委派。Fork 为保持缓存前缀可继续展示父工具 schema，但越界工具会在 Hook 和权限检查之前被冻结策略拒绝。子 Agent 不进行交互审批；任何原本为 `ASK` 的权限决定都会以非交互来源自动改写为拒绝，再把普通工具失败交回子模型继续处理。

后台任务结束时终端只显示单行摘要。完整的有界结果可用 `/task <id>` 查看，并会在根 Agent 的下一次真实模型请求中以 `<untrusted-subagent-results>` 边界一次性注入；它不写入主历史。任务表和通知纯属进程内状态，退出后不恢复；`/reset` 会先取消并清空所有任务和待投递通知。

`worktree` 角色会在 `<workspace>/.mewcode/worktrees/task/<摘要>/` 创建独立目录和 `mewcode/worktree/task/<摘要>` 临时分支。所有文件、命令、Skill 进程、项目 Hook、stdio MCP、Prompt 环境和上下文归档都显式绑定该绝对目录，MewCode 不调用进程级 `chdir`。主 Agent 启动时冻结的用户级配置继续复用，项目指令、项目记忆、Hook 和 MCP 则从该 Worktree 重新加载。

任务退出时，干净且没有未发布提交的临时目录会自动删除；存在 tracked 修改、未忽略的 untracked 文件、未被任一远端跟踪引用包含的新提交，或保护检查不确定时会保留，并在 `/task`、通知和 `/worktrees` 中显示。`--force` 只允许人工本地命令逐次指定，不能由 Agent 工具、配置或后台清理启用。后台清理只处理超过 24 小时的非活动候选，每轮最多 256 个，并复用相同的归属验证和非强制保护。

可提交的初始化规则位于 `.mewcode/worktrees.yaml`，示例见 `examples/worktrees.yaml`。默认只尝试复制明确列出的本地 MewCode 配置/记忆；自定义 `copy` 和 `link` 规则也只接受主工作区内“未跟踪且已忽略”的内容。`link` 失败不会回退为大规模复制，`git_hooks` 通过子进程专属的 `core.hooksPath` 环境覆盖生效，不修改共享 Git 配置。

Worktree 是并发文件隔离，不是操作系统安全沙箱；能够执行任意命令的代码仍可能访问绝对路径。普通 `agent` 临时 Worktree 流程不提供自动合并、跨 Worktree 代码同步、多 Agent 团队编排、跨会话后台任务持久化、嵌套 Agent、子 Agent 人工审批或缓存命中保证，合并仍由上层显式执行 `git merge`。持久团队在双开关启用后可以使用 Phase 14C 的独立受控集成流程，见下文。

## Skill 系统

Skill 把可复用 AI 工作流保存为 YAML frontmatter 加 Markdown SOP。系统按项目级 `<workspace>/.mewcode/skills/`、用户级 `~/.mewcode/skills/`、内置资源的顺序发现，同名定义按“项目＞用户＞内置”选择。每层同时识别 `<name>.md` 和 `<name>/SKILL.md`；目录包只以 `SKILL.md` 为入口。高层定义无效时回退低层有效版本，单个解析错误只警告；同层有效重名、系统命令冲突、缺失白名单工具或无效 Profile 会拒绝启动。

名称必须是小写 kebab-case。定义字段严格且不接受未知字段：

```markdown
---
name: explain-change
description: Explain the current change for a reviewer.
tools:
  - read_file
  - search_code
mode: shared
---
Explain the change with this focus: {{input}}
```

`name`、`description`、`tools`、`mode` 必填，`mode` 只能是 `shared` 或 `isolated`。共享模式禁止 `history` 和 `model`；独立模式必须提供非负整数 `history`，并可用 `model` 填写现有 Profile 名称。正文只替换字面量 `{{input}}`；没有占位符时，调用参数仍作为任务内容提供。

启动时模型只看到 Skill 名称和一句说明。Agent 需要使用时调用始终可见的系统工具 `load_skill`：

- `shared` 在当前会话激活，完整 SOP 按激活顺序常驻 `Active Skills`，同名再次调用只替换最新参数渲染结果而不移动顺序。
- `isolated` 每次新建临时 Direct 对话，从主历史复制最近 `history` 个完整轮次，不拆开工具链；它继承环境、人工指令、长期记忆和共享 SOP，只追加本次独立 SOP。最终回复直接回流，内部消息和工具调用不写入主历史。

直接调用共享斜杠命令会把原始命令保存为该轮用户消息，随后保存正常 Agent 回复与工具链。直接调用独立命令只保存原始斜杠消息和独立最终回复；主 Agent 自主调用独立 Skill 时，主历史保存 `load_skill` 调用、最终回复工具结果和主 Agent 后续回复。

没有共享 Skill 激活时，主对话仍能看到当前模式允许的全部注册工具。一旦有共享 Skill 激活，工具集收窄为各共享白名单并集，再与 DEFAULT/PLAN/READ_ONLY 的安全上限取交集；`load_skill` 始终保留。独立运行使用“共享白名单并集＋当前独立白名单”后再取安全交集，不改变主对话工具集。所有实际工具仍经过现有权限系统。

### 目录包专属工具

目录型 Skill 可在 `tools/*.json` 中为每个工具放一个严格声明，实现文件通常位于 `scripts/`：

```json
{
  "name": "check",
  "description": "Check the selected files.",
  "parameters": {
    "type": "object",
    "properties": {"path": {"type": "string"}},
    "required": ["path"]
  },
  "command": ["python", "scripts/check.py"],
  "safety": "read_only",
  "timeout_seconds": 60
}
```

局部名称统一公开为 `<skill-name>__<tool-name>`，frontmatter 的 `tools` 也填写完整公开名；Skill 只能引用全局工具和自己的包工具，不能依赖其他 Skill 的包工具。`safety` 必须为 `read_only` 或 `side_effect`，并以完整公开名进入工具级权限判断。

`command` 是 argv 字符串数组，解释器由作者显式填写，MewCode 不经过 shell。包内路径安全解析到激活时的临时只读版本副本；子进程 cwd 是工作区，环境提供 `MEWCODE_SKILL_DIR` 和 `MEWCODE_WORKSPACE_ROOT`，并移除所有 Profile API Key 环境变量。

调用参数以一个 JSON 对象写入 stdin。stdout 必须且只能是一个 JSON 对象，包含布尔 `ok` 和字符串 `content`，可选字符串 `error` 与对象 `metadata`。非零退出、超时、非法 JSON、字段错误或超量 I/O 会成为结构化工具失败；stderr 只保留有界内部诊断。超时默认 60 秒，可配置 1–600 秒，超时和取消都会终止子进程。

### 热更新、恢复与内置样板

每次处理新的非空输入或斜杠命令前，MewCode 比较 Skill 文件元数据；无变化不重读，有变化才重建完整候选。成功更新会按名称把激活项绑定到当前最高有效版本并用最后原始参数重渲染；定义全部消失时自动失活。候选出现全局错误时整批拒绝，旧目录、命令、SOP、工具和物化包继续工作，不使用后台监听线程。

会话只持久化激活名称、顺序和最后原始参数，恢复时用当前文件重新解析，不保存旧 SOP 或工具实例。`/reset` 使用同一会话 ID 原子清空消息、旧计划和所有激活 Skill，并恢复 DEFAULT；人工指令、长期记忆和权限模式不变，重启不会恢复 reset 前历史。`/clear` 仍只清终端显示。

内置样板如下：

- `commit`：共享模式，检查 Git 改动、运行相称验证、只暂存相关安全文件并创建一次提交；无改动、验证失败或范围不明时不提交。
- `review`：独立模式、history 0、只读最小工具集，只审查当前工作区；它替代了旧的硬编码 `/review`。
- `test`：共享模式，识别项目测试方式并运行与参数或未提交改动匹配的测试，只运行和报告，不修改产品代码。

本阶段不包含 Skill 市场、远程安装、版本管理、依赖解析、签名、后台 watcher、通用 OS 沙箱、参数级权限目标或 `{{input}}` 之外的模板语法。

## 项目指令、会话与长期记忆

启动时会按以下优先级加载人工维护的 Markdown 指令：

1. `<workspace>/.mewcode/instructions.md`（最高）
2. `<workspace>/MEWCODE.md`
3. `~/.mewcode/instructions.md`（最低）

指令文件可用独占一行的 `@include 相对路径` 拆分规则，路径相对当前文件解析，最多嵌套 5 层。项目级入口只能引用当前项目内的文件，用户级入口只能引用 `~/.mewcode/` 内的文件；循环、重复、越界和不可读引用会被安全跳过并显示简洁警告。

会话保存在 `<workspace>/.mewcode/sessions/<session-id>.jsonl`。JSONL 采用追加写，不维护额外 meta 文件；恢复时跳过完整坏行、移除未配对的工具调用尾部，并在中断超过 24 小时时插入包含上次活动时间和本次恢复时间的 system 提醒。超过 30 天且未被其他进程占用的会话会定期清理。

自动笔记分为用户偏好、纠正反馈、项目知识和参考资料。项目笔记位于 `<workspace>/.mewcode/memory/`，用户笔记位于 `~/.mewcode/memory/`；每条笔记是带 frontmatter 的 Markdown，并由各自的 `index.md` 索引。每份索引和合并注入内容均限制为 200 行、25KB，合并时优先保留项目记忆。自动记忆只作为参考知识，不能覆盖上述人工指令。

模型自然给出最终回复后，终端会立即展示结果，再在后台用同一 Provider 更新笔记。下一条请求和正常退出会等待上一轮更新完成；更新失败时保留两份旧索引、只警告一次且不自动重试。写入会过滤常见凭据并通过双作用域事务避免项目索引与用户索引出现一新一旧。

本阶段不使用向量数据库、RAG 检索或团队记忆同步。

## Agent Loop

普通消息会启动 ReAct Agent Loop。MewCode 会持续让模型思考、调用工具、读取结果并调整下一步，直到模型给出不再包含工具调用的最终回复，无需逐步追加提示。

每次运行最多调用模型 20 次；如果第 20 次响应仍要求工具，MewCode 会停止且不会执行最后一批工具。运行还会在用户按下 `Ctrl+C`、连续三轮只请求未知工具、Provider 流出错或内部错误时停止。`Ctrl+C` 只取消当前一轮，清理完成后可以继续在同一 REPL 中输入任务。

模型一次返回多个工具调用时，相邻的只读工具会并发执行，最大并发数为 4；写文件、编辑文件和运行命令按原始顺序独占执行。终端会实时显示文本、简短工具状态、迭代进度和 Token 用量，不显示完整工具参数或大段工具结果。

## 结构化系统提示与缓存

每次模型请求都使用同一套结构化系统提示。稳定前缀依次包含 Identity、System Constraints、Task Mode、Action Execution、Tool Use、Tone and Style 和 Text Output；Environment、自动发现的项目/用户指令、Skill 目录、已激活共享 Skill 内容、长期记忆以及当次 `<system-reminder>` 位于稳定边界之后。

Plan 和 Execute 模式按一次 Agent Run 内的真实模型调用次数注入提醒：第 1, 5, 9, 13, 17 次使用完整指令，其余调用使用精简提醒。Direct Mode 不增加模式提醒。提醒使用系统语义，不会作为用户消息写入对话历史。

工具定义和稳定系统提示会按 Provider 协议组成确定性的缓存前缀。缓存是否实际写入或命中仍取决于模型支持、前缀长度和服务端状态，MewCode 不保证每次命中。Token 行会显示：

```text
tokens: in=... out=... total=... cache-read=... cache-write=... cumulative=... cumulative-cache-read=... cumulative-cache-write=...
```

MCP 工具来自启动时静态快照，不会改变结构化提示的运行时边界。Skill 只有在用户调用斜杠命令或 Agent 调用 `load_skill` 后才激活；未激活 SOP 和专属工具 schema 不进入模型请求。

## 上下文管理

每次模型请求前，MewCode 会先限制工具结果体积，再检查累计历史容量。单个工具结果估算超过 8K Token 时会保存完整结果；同一轮工具结果合计超过 12K 时，会从最大的结果开始继续保存，直到活动内容回到预算内。上下文中的占位内容保留文件路径以及合计最多约 1K Token 的首尾预览。

当整体请求接近窗口上限时，MewCode 会用当前活动 Profile 和 Provider 生成一份无工具、最大输出 8192 Token 的结构化滚动摘要。近期约 10K Token 且至少 5 条消息保持原文，工具调用组不会被拆开；较早的完整记录写入工作区的 `.mewcode/context/<session-id>/`。摘要与近期原文之间的边界提示要求模型在需要代码、文件或工具细节时重新读取原文件或存盘记录，不得根据摘要猜测。

自动触发边界为 `context_window - 本次最大输出 Token - 13000`。`/compact` 即使未达到自动阈值也会显式尝试一次，摘要请求使用 `context_window - 8192 - 3000` 的容量边界；没有可压缩的早期消息时不会调用模型。连续三次摘要失败后，本会话停止自动摘要：安全请求仍可继续，存在溢出风险的请求会在调用主模型前报错。此时可再次执行 `/compact`；成功后失败计数清零并恢复自动摘要。

Token 数采用近似估算：以上一次 API 返回的输入 usage 为锚，只按后续字符增量修正；ASCII 约按 4 字符/Token、非 ASCII 约按 1 字符/Token 估算，并用安全余量吸收误差，不依赖精确 tokenizer。存盘文件只在当前会话期间保留，正常退出时删除；下次启动会清理崩溃遗留目录，同时保留仍由其他进程锁定的活动会话。

## Plan Mode

`/plan` 是持续状态切换命令，本身不接收任务、不调用模型，也不写入对话历史。切换后，底栏立即显示 `[PLAN]`，后续普通消息使用计划提示并且只开放只读工具；即使用户要求修改文件或运行有副作用的操作，也不会获得写工具。

```text
mew> /plan
[PLAN]
mew> 分析配置加载器应如何增加环境变量校验
agent: iteration 1
tool: search_code ...
...

mew> /do
[DEFAULT]
mew> 按刚才的分析实现并验证
```

`/do` 只把持续模式切回 DEFAULT，不会自动执行或改写旧版本会话中保存的计划。内置 `/review` 是独立只读 Skill；在 PLAN 中调用时仍受只读安全上限约束，完成或失败后不会改变持续模式。

当前阶段不包含通用网络沙箱、自动化质量评估或 Hook 之外的审计系统。

## Hook 自动化

Hook 在 Agent 生命周期的固定边界执行声明式自动化。配置按以下顺序追加加载，文件缺失等同空配置；任一文件存在格式错误时，整个 Hook 目录在启动阶段被拒绝，不会先执行部分规则：

- 用户全局：`~/.mewcode/hooks.yaml`
- 项目共享：`<workspace>/.mewcode/hooks.yaml`
- 项目本地：`<workspace>/.mewcode/hooks.local.yaml`

每条规则由必填 `event`、可选 `if` 和必填 `action` 组成。固定事件为 `session.start/end`、`turn.start/end`、`message.before/after`、`tool.before/after`、`system.compact.before/after` 和 `system.error`。message 边界对应每一次真实 Provider 请求，包括主回复、独立 Skill、上下文摘要和记忆更新；已开始的生命周期在失败、拒绝或取消时仍会得到配对 after/end。

```yaml
hooks:
  - event: tool.before
    if:
      all:
        - field: tool.name
          match: exact
          value: run_command
        - field: tool.arguments.command
          match: regex
          value: "^git\\s+push(?:\\s|$)"
          negate: false
    action:
      type: command
      command: python .mewcode/check_push.py
      timeout_seconds: 10
      once: false
      background: false
```

条件必须选择非空 `all` 或 `any`，不能混用或嵌套。子句支持类型严格的 `exact`、与权限规则相同转义语义的完整 `glob`、带运行时超时的完整 `regex`，以及最后应用的 `negate`。`tool.arguments.*` 可定位嵌套工具参数；对象、数组和 null 不会被隐式转成字符串。

动作有四类：

- `command`：以工作区为 cwd 执行 shell 命令，统一事件 JSON 从 stdin 输入；默认超时 60 秒，最大 600 秒。
- `prompt`：把内容加入下一次真实模型请求的动态 `## Hook Context`，消费后不重放，也不写入历史。
- `http`：把同一事件 JSON 作为请求体发往 HTTP(S) 地址；默认 POST/30 秒，最大 120 秒，不跟随重定向。
- `agent`：当前版本只校验并记录 placeholder skipped，不会真正启动子 Agent。

command 和 HTTP 支持 `once`、`background` 与各自的 `timeout_seconds`。`once` 在当前进程首次匹配、动作尝试前原子消费，即使动作失败也不重试；重启后可以再次触发，不写持久标记。后台动作按声明顺序启动，退出时有界等待后取消/终止；`tool.before` 以及 prompt/agent 不允许后台运行。同步动作按声明顺序执行，普通 Hook 失败只写诊断并继续 Agent 主流程。

`tool.before` 的同步 command stdout 或 HTTP 2xx body 可以返回严格 JSON：`{"decision":"allow"}` 或 `{"decision":"deny","reason":"..."}`。空响应表示继续；非零退出、非 2xx、超时、非法 JSON、未知决定或缺少 reason 都按 Hook 失败放行。首个合法 deny 会停止剩余 before 规则，不执行工具，并把原因作为失败 ToolResult 反馈模型。安全顺序始终是“危险命令/路径硬门禁 → Hook → 权限规则与人工确认”；Hook allow 不能越过任何权限限制，硬门禁拒绝的参数不会发送给外部 Hook。

command stdin 与 HTTP body 使用相同的有界、带 `schema_version` 的 JSON 信封。大参数会被递归截断并在 `truncated_fields` 标记；信封不包含完整历史、PromptPackage、隐藏模型内容、API Key 或认证头。command 环境还会移除所有 Profile Key 变量。项目共享配置中的 command/HTTP 首次使用前需要针对当前规范工作区单独确认信任；拒绝后仅禁用这两类外部动作，prompt 仍可用，其他工作区不会继承决定。

动作结果写入 `~/.mewcode/logs/hooks.jsonl`，约 1 MiB 时轮转并保留 `.1`–`.3`。日志仅记录事件、规则来源/索引、动作类型、后台状态、耗时、结果和有界脱敏摘要，不保存信封、headers、响应正文、原始堆栈或凭据。主要上限还包括每文件 256 条、合并 512 条、每规则 32 个条件、单 prompt 32 KiB、单次 prompt 消费 64 KiB、外部信封 1 MiB、command 双路输出各 64 KiB、HTTP 响应 64 KiB、后台任务 32 个。

完整示例见 `examples/hooks.yaml`。本阶段不提供显式 priority、热重载、失败重试、跨重启 once、真实子 Agent、通用 OS 沙箱或跨平台 shell 语法转换。

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

## Agent Teams

### 持久团队

根 Agent 始终可通过固定的 `team` 工具创建、列出、挂载、重新关联或卸载本机团队。挂载后它会升格为 Team Lead，并在下一次模型请求获得 `team_member`、`team_task` 和 `team_message`：前者维护长期成员，任务工具管理带修订号和依赖的共享清单，消息工具提供点对点邮箱、广播、已读回执及计划审批。普通子 Agent 和团队成员都看不到团队生命周期或成员管理入口；成员只能使用冻结角色允许的工作区工具以及共享任务、邮箱入口。

每个成员具有长期身份和固定 Git Worktree。自然结束只把成员置为 `IDLE`，不会替它把任务标为完成；消息、任务指派或显式恢复会通过持久 FIFO 队列再次运行同一成员。成员的完整安全边界历史、上下文归档身份和已投递消息 ID 会保存在 `~/.mewcode/teams/<team-name>/members/`，邮箱在同一团队目录的 `mailboxes/` 下使用独立锁和追加式日志，因此应用重启后无需重新 add 或 spawn。

需要审批的成员可以先读取代码并提交计划；申请会让当前运行安全暂停。Lead 批准只解除该成员当前任务、当前修订和审批代际的副作用门禁，不会扩大冻结角色、全局权限或 Worktree 范围。任务重新指派、依赖变化或重置会使旧批准失效。

Phase 14A 采用本机保密模型：团队状态和消息仅写入用户目录，运行中的成员共享进程级八名额容量池，成员 Worktree 不参与普通临时目录清理。它不提供操作系统级沙箱或跨机器团队。

### 隔离成员后端

成员可以使用 `auto`、`in_process`、`windows_terminal` 或 `tmux` 后端。`auto` 在 Windows Terminal 宿主中优先选择相邻 Windows Terminal 窗格，在 macOS/Linux 的 tmux 宿主中优先选择相邻 tmux 窗格，否则使用进程内后端；显式选择的终端后端不可用时会明确失败，不会静默降级。实际后端一旦解析便随成员身份持久化。

终端成员仍使用同一长期身份、固定 Worktree、冻结角色、任务、邮箱、审批和会话。自然停止后窗格保留并进入 `IDLE`，后续消息、任务或恢复请求会复用该窗格；窗格丢失时可重建关联。唤醒失败会保留已投递数据并将成员收敛为带诊断的 `FAILED`，进程异常退出或 Lead 重启也不会重放未确认的成员工具调用。

### Team Lead Coordinator

Coordinator 默认关闭，只有用户配置和环境变量两个开关同时开启才生效：

```yaml
teams:
  coordinator:
    enabled: true
```

```powershell
$env:MEWCODE_ENABLE_TEAM_COORDINATOR = "1"
mewcode
```

任一开关关闭时，Coordinator 专用工具不可用，Lead 原有写入权限不变，也不会创建 coordinator 状态或后台任务。两个开关均开启并挂载团队后，限制只作用于该 Team Lead：通用写文件、编辑、命令执行、普通子 Agent 和 Skill 加载工具会被移除；Lead 保留只读及团队生命周期、成员、任务、邮箱、审批、停止和恢复工具，并通过结构化的 `team_coordinator` 与 `team_git` 完成编排和 Git 集成。普通成员、普通子 Agent 和未启用团队的会话不受影响。

Lead 可以把目标拆成带依赖、角色/成员选择器和验收标准的共享任务，按依赖、成员状态、审批和共享容量做可审计派发；前置条件不足的任务保持 pending，不会强行启动或绕过计划审批。协调运行、派发决定、集成批次、步骤和恢复 journal 持久化在 `~/.mewcode/teams/<team-name>/coordinator/`。

受控集成只处理成功完成且通过成员终态、Worktree 归属、基线、工作区和提交范围检查的任务，并按稳定的依赖拓扑顺序合并到绑定的本地目标分支。冲突、Git 异常或提交后验证失败会回滚到合并前的可验证状态、停止后续依赖并转为人工处理；恢复逻辑不会重复已确认的合并步骤。该流程不会 `fetch`、`push`、修改远端、创建 PR，也不会删除成员 Worktree、分支或未合并成果。
