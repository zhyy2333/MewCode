# 斜杠命令注册与分发系统 Plan

## 架构概览

系统分为六个协作层次：

### 1. 命令核心

新增独立的命令包，承载命令元数据、不可变注册表、输入解析和异步分发。该层不导入 REPL、`prompt_toolkit`、Conversation 或具体业务服务。

注册表在构造时一次性规范化名称与别名，并检查全部大小写无关冲突；成功构造后不再允许运行时修改。帮助和补全均直接读取这份注册表。

### 2. 内置命令

十个公开命令和隐藏退出命令集中在一个内置命令工厂中登记。每个处理函数只依赖命令上下文中的抽象能力，不直接写标准输出、不操作具体终端对象，也不自行创建 Agent。

固定的代码审查提示词作为版本内常量保存；处理函数不读取工作区内容来拼接提示词。

### 3. 命令控制边界

命令上下文由两个协议组成：

- 界面控制协议：显示普通消息与错误、清屏、发送用户消息、读取或切换持续模式、读取 Token、刷新状态栏、请求退出。
- 运行状态协议：执行手动压缩，读取会话、记忆和上下文摘要，读取或修改现有权限模式。

REPL 提供这两个协议的适配实现。命令层因此只认识稳定操作和只读快照，不认识 `prompt_toolkit`、文件流或具体渲染器。

### 4. 对话路由

Conversation 增加统一的消息执行入口，并显式接收一次请求的执行策略：

- `DEFAULT`：直接对话提示，完整工具集，继续受权限系统控制。
- `PLAN`：计划提示，只读工具集。
- `READ_ONLY`：直接对话提示，只读工具集，专供 `/review` 等单次命令使用。

REPL 的持续 `[DEFAULT]`、`[PLAN]` 状态只决定普通输入采用前两种策略；`/review` 临时使用 `READ_ONLY`，不改变持续状态。

旧会话中的待执行计划记录继续能够被解析以保持存储兼容，但新的 REPL 不再创建或执行这类状态，也不会因 `/do` 自动调用旧计划。

### 5. 终端适配

新增基于 `prompt_toolkit` 的终端输入适配器，使用异步提示会话、注册表驱动的补全器、自定义 Tab 行为和底部状态栏：

- 单候选时直接应用补全。
- 多候选时启动选择菜单。
- 状态栏内容由当前持续模式动态生成。
- 清屏和输出后由适配器恢复提示区状态。

REPL 主循环改为单一异步生命周期，使 Agent 消费、权限询问、命令处理和后台记忆更新共享同一事件循环。测试使用无终端依赖的脚本化适配器。

### 6. 运行状态聚合

在现有组件上增加轻量只读快照：

- Provider 外层增加用量跟踪装饰器，统一统计所有模型流，包括 Agent、压缩和记忆更新。
- Conversation 暴露会话 ID、动态标题、消息数量和忙闲状态。
- MemoryManager 暴露两种作用域的条目数量、注入索引容量和最近更新状态。
- ContextManager 暴露自动压缩是否可用及连续失败数。
- PermissionController 继续提供现有模式读写能力。

CLI 在创建真实 Provider 后立即包裹用量跟踪器，并把同一个包装实例传给 Agent、上下文压缩和记忆更新，确保不会漏记或重复计算。

## 核心数据结构与接口

### 命令核心模型

```python
class CommandType(StrEnum):
    LOCAL = "local"
    UI = "ui"
    PROMPT = "prompt"


class InputKind(StrEnum):
    EMPTY = "empty"
    MESSAGE = "message"
    COMMAND = "command"


class InteractionMode(StrEnum):
    DEFAULT = "default"
    PLAN = "plan"


@dataclass(frozen=True)
class ParsedInput:
    kind: InputKind
    text: str = ""
    identifier: str = ""
    arguments: str = ""


CommandHandler = Callable[
    ["CommandContext", str],
    Awaitable[None],
]


@dataclass(frozen=True)
class CommandDefinition:
    name: str
    description: str
    usage: str
    command_type: CommandType
    handler: CommandHandler
    aliases: tuple[str, ...] = ()
    argument_hint: str | None = None
    hidden: bool = False
```

命令名称和别名在模型中均不带 `/`。展示、解析和补全时再添加斜杠。`CommandDefinition` 为不可变对象，处理函数之外的全部帮助和补全信息都来自这里。

### 解析结果与错误

```python
class CommandRegistrationError(RuntimeError):
    pass


class CommandUsageError(RuntimeError):
    pass


class CommandExecutionError(RuntimeError):
    pass


def parse_input(raw: str) -> ParsedInput:
    ...
```

`parse_input` 先去除整条输入首尾空白：

- 结果为空时返回 `EMPTY`。
- 不以 `/` 开头时返回 `MESSAGE`，`text` 保存清理后的普通消息。
- 以 `/` 开头时只按第一个 ASCII 空格切分，`identifier` 保存不带 `/` 的原始标识，`arguments` 只去除首尾空白。

解析器不负责查表或判断参数是否合法。

### 不可变注册表

```python
class CommandRegistry:
    def __init__(
        self,
        definitions: Iterable[CommandDefinition],
    ) -> None:
        ...

    def resolve(self, identifier: str) -> CommandDefinition | None:
        ...

    def public_definitions(self) -> tuple[CommandDefinition, ...]:
        ...

    def completion_candidates(self, prefix: str) -> tuple[str, ...]:
        ...
```

构造函数完成以下工作：

1. 校验名称和别名非空、不含 `/` 或空白。
2. 对全部标识执行 `casefold()`。
3. 检查规范名称和别名的完整冲突矩阵。
4. 建立只读索引。
5. 按规范名称排序公开命令，按显示文本排序补全候选。

`resolve` 同时解析规范名称和别名；`public_definitions` 与 `completion_candidates` 永远过滤隐藏命令及其别名。

### 命令上下文

```python
@dataclass(frozen=True)
class CommandContext:
    registry: CommandRegistry
    ui: CommandUI
    runtime: CommandRuntime
```

命令处理函数只能通过这三个入口协作。

### 界面控制协议

```python
class CommandUI(Protocol):
    def show_message(self, message: str) -> None:
        ...

    def show_error(self, message: str) -> None:
        ...

    def clear_display(self) -> None:
        ...

    async def send_user_message(
        self,
        message: str,
        *,
        read_only: bool = False,
    ) -> None:
        ...

    def interaction_mode(self) -> InteractionMode:
        ...

    def set_interaction_mode(self, mode: InteractionMode) -> None:
        ...

    def token_usage(self) -> UsageSnapshot:
        ...

    def refresh_status(self) -> None:
        ...

    def request_exit(self) -> None:
        ...
```

普通输入不通过命令处理函数发送；REPL 根据 `interaction_mode()` 选择 Conversation 的 `DEFAULT` 或 `PLAN` 策略。`/review` 调用 `send_user_message(..., read_only=True)`，适配器把它映射为一次 `READ_ONLY` 请求。

### 运行状态协议

```python
class CommandRuntime(Protocol):
    async def compact_context(self) -> None:
        ...

    def session_status(self) -> ConversationStatus:
        ...

    def memory_status(self) -> MemoryRuntimeStatus:
        ...

    def context_status(self) -> ContextRuntimeStatus:
        ...

    def permission_mode(self) -> PermissionMode:
        ...

    def set_permission_mode(self, mode: PermissionMode) -> None:
        ...
```

`compact_context` 由 REPL 适配器消费现有压缩事件并沿用统一事件渲染。其余方法只返回内存中的快照，不等待后台记忆任务，也不扫描历史正文。

### 分发器

```python
class CommandDispatcher:
    def __init__(
        self,
        registry: CommandRegistry,
        ui: CommandUI,
        runtime: CommandRuntime,
    ) -> None:
        ...

    async def dispatch(self, invocation: ParsedInput) -> None:
        ...
```

`dispatch` 只接受 `COMMAND` 类型输入。它负责解析别名、处理未知命令、调用登记的异步处理函数，并把用法错误和可预期执行错误转换为用户消息。未预期异常只输出经过清理的通用错误，交互循环继续运行。

### 对话执行策略

```python
class ConversationMode(StrEnum):
    DEFAULT = "default"
    PLAN = "plan"
    READ_ONLY = "read_only"


@dataclass(frozen=True)
class ConversationStatus:
    session_id: str
    title: str
    resumed: bool
    message_count: int
    busy: bool


class Conversation:
    async def send(
        self,
        user_text: str,
        mode: ConversationMode = ConversationMode.DEFAULT,
    ) -> AsyncIterator[AgentEvent]:
        ...

    def status(self) -> ConversationStatus:
        ...
```

策略映射如下：

| ConversationMode | Agent 提示模式 | 工具集合 |
|---|---|---|
| `DEFAULT` | `DIRECT` | 全部工具 |
| `PLAN` | `PLAN` | 只读工具 |
| `READ_ONLY` | `DIRECT` | 只读工具 |

现有手动 `compact()` 保留。旧的 `plan()`、`execute_plan()` 和运行期 `PendingPlan` 路由由 `send()` 取代；会话编解码器仍识别旧 `StoredPlan` 记录，但 Conversation 不再使用它。

### Token 用量跟踪

```python
@dataclass(frozen=True)
class UsageSnapshot:
    usage: TokenUsage
    request_count: int
    unreported_request_count: int


class UsageLedger:
    def record(self, usage: TokenUsage | None) -> None:
        ...

    def snapshot(self) -> UsageSnapshot:
        ...


class UsageTrackingProvider:
    def __init__(
        self,
        provider: LLMProvider,
        ledger: UsageLedger,
    ) -> None:
        ...

    def stream_reply(
        self,
        request: ModelRequest,
    ) -> AsyncIterator[ProviderEvent]:
        ...

    def assistant_messages(...):
        ...

    def tool_result_messages(...):
        ...
```

每次模型流结束、失败或取消时只登记一次：

- 收到用量事件时登记该次调用最后一份完整用量。
- 完全未收到用量事件时登记一次“未报告”调用。
- 任一累计字段遇到未知值后保持 `None`，`/status` 将其显示为 `n/a`，不用估算值填补。
- 消息转换方法原样委托给真实 Provider，不改变 Provider 行为。

### 记忆状态

```python
class MemoryUpdateState(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DISABLED = "disabled"


@dataclass(frozen=True)
class MemoryRuntimeStatus:
    project_notes: int
    user_notes: int
    index_lines: int
    index_bytes: int
    max_index_lines: int
    max_index_bytes: int
    update_state: MemoryUpdateState
```

`MemoryManager` 在构造、调度、成功、失败和禁用路径更新状态；快照只读取已加载目录和索引视图，不触发磁盘扫描，也不等待 `_pending`。

### 上下文状态

```python
@dataclass(frozen=True)
class ContextRuntimeStatus:
    automatic_compaction_enabled: bool
    consecutive_failures: int
```

`ContextManager.status()` 从现有熔断器生成快照，不启动压缩。手动压缩的即时结果继续通过现有状态事件显示。

### 终端输入协议

```python
class TerminalSession(Protocol):
    async def prompt(self) -> str:
        ...

    async def prompt_permission(self, message: str) -> str:
        ...

    def write(self, text: str) -> None:
        ...

    def write_error(self, text: str) -> None:
        ...

    def clear(self) -> None:
        ...

    def invalidate(self) -> None:
        ...
```

生产实现使用 `prompt_toolkit`；测试实现使用预置输入序列和内存文本流。底部状态栏回调读取 `InteractionMode`，不把模式复制到第二份状态。

## 模块设计

### `mewcode.commands.core`

**职责：**

- 定义命令类型、输入类型、命令元数据和命令错误。
- 实现 `parse_input` 和 `CommandRegistry`。
- 保证注册、查找、帮助排序和补全候选确定性。

**依赖：**

- 仅依赖 Python 标准库。
- 不依赖 Conversation、终端或业务组件。

### `mewcode.commands.contracts`

**职责：**

- 定义 `CommandContext`、`CommandUI` 和 `CommandRuntime` 协议。
- 汇总命令处理所需的只读状态类型。

**依赖：**

- 只依赖各领域公开的状态快照和权限枚举。
- 不依赖 `prompt_toolkit` 或具体 REPL。

### `mewcode.commands.builtin`

**职责：**

- 保存固定 `/review` 提示词。
- 实现十个公开命令和隐藏退出命令的处理函数。
- 提供 `create_builtin_command_registry()`。
- 提供帮助、会话、记忆和状态摘要的纯格式化函数。
- 使用统一的无参数校验辅助函数。

**依赖：**

- 命令核心与协议。
- 公开状态模型和 `PermissionMode`。
- 不直接依赖具体终端或 Provider。

### `mewcode.terminal`

**职责：**

- 定义 `TerminalSession`。
- 实现 `PromptToolkitTerminal`。
- 实现注册表驱动的 `CommandCompleter` 和 Tab 键绑定。
- 提供底部模式栏、普通输入、权限输入、清屏、输出和失效重绘。
- 关闭输入历史，避免本阶段引入历史搜索功能。

**依赖：**

- `prompt_toolkit>=3.0,<4`。
- 命令注册表与共享交互状态。
- 不依赖 Conversation。

### `mewcode.repl`

**职责：**

- 持有唯一的可变 `InteractionState`，初始模式为 `DEFAULT`。
- 运行单一异步输入循环。
- 对 `ParsedInput` 做三路分流：空输入、命令、普通消息。
- 实现 `CommandUI` 和 `CommandRuntime` 两个协议。
- 将普通输入模式映射到 Conversation 策略。
- 消费 Agent 与压缩事件，处理异步权限询问。
- 负责正常退出、EOF、取消和最终资源收尾。
- 保留现有 `_EventRenderer` 的流式输出层级。

**依赖：**

- Commands、Terminal、Conversation、PermissionController 及状态快照。
- 是具体终端与应用服务的唯一组合层。

### `mewcode.conversation`

**职责变化：**

- 以 `send(user_text, mode)` 取代 REPL 使用的 `ask`、`plan`、`execute_plan` 三套入口。
- 根据 `ConversationMode` 同时选择 Agent 提示模式和工具集合。
- 暴露不含正文的 `ConversationStatus`。
- 保留上下文预检、历史提交、记忆调度、取消和关闭语义。
- 忽略恢复状态中的旧 `StoredPlan`，但不重写或删除旧会话记录。

### `mewcode.providers.usage`

**职责：**

- 实现 `UsageLedger` 和 `UsageTrackingProvider`。
- 在 Provider 边界统一统计完成、失败和取消的模型流。
- 原样委托消息转换方法，避免改变 Agent/Provider 协议。

### `mewcode.continuity.memory_manager`

**职责变化：**

- 跟踪最近更新状态。
- 从已加载目录与索引视图生成 `MemoryRuntimeStatus`。
- 查询状态时不等待后台任务、不重新扫描磁盘。

### `mewcode.context.manager`

**职责变化：**

- 增加只读 `status()`，从现有熔断器生成 `ContextRuntimeStatus`。
- 不改变自动和手动压缩算法。

### `mewcode.cli`

**职责变化：**

- 创建 `UsageLedger`，用 `UsageTrackingProvider` 包裹真实 Provider。
- 将同一个跟踪 Provider 传给 Agent、ContextManager 和 MemoryUpdater。
- 创建共享交互状态、内置注册表、终端适配器和 REPL。
- 将命令注册错误转换为启动期非零退出。
- 保留现有 MCP、权限、会话、记忆和关闭顺序。

## 内置命令定义

| 名称 | 别名 | 类型 | 参数提示 | 隐藏 | 用法 |
|---|---|---|---|---|---|
| `help` | 无 | 本地 | `[command]` | 否 | `/help [command]` |
| `compact` | 无 | 本地 | 无 | 否 | `/compact` |
| `clear` | 无 | 界面 | 无 | 否 | `/clear` |
| `plan` | 无 | 界面 | 无 | 否 | `/plan` |
| `do` | 无 | 界面 | 无 | 否 | `/do` |
| `session` | 无 | 本地 | 无 | 否 | `/session` |
| `memory` | 无 | 本地 | 无 | 否 | `/memory` |
| `permission` | `permissions` | 本地 | `[strict\|default\|allow]` | 否 | `/permission [strict\|default\|allow]` |
| `status` | 无 | 本地 | 无 | 否 | `/status` |
| `review` | 无 | 提示词 | 无 | 否 | `/review` |
| `exit` | `quit` | 本地 | 无 | 是 | `/exit` |

处理行为：

- `help`：无参数时格式化 `public_definitions()`；有参数时允许输入 `status` 或 `/status`，只解析公开命令。
- `compact`：调用 `runtime.compact_context()`，由 REPL 流式渲染现有压缩事件。
- `clear`：调用 `ui.clear_display()`，随后 `ui.refresh_status()`。
- `plan`：把共享状态设为 `PLAN` 并刷新状态栏。
- `do`：把共享状态设为 `DEFAULT` 并刷新状态栏。
- `session`：格式化 `runtime.session_status()`。
- `memory`：格式化 `runtime.memory_status()`。
- `permission`：无参数读取当前模式；合法单参数通过现有控制器切换；模式参数使用大小写无关匹配。
- `status`：读取模式、Token、会话、权限、上下文和记忆快照，打印核心摘要后刷新状态栏。
- `review`：调用 `ui.send_user_message(REVIEW_PROMPT, read_only=True)`。
- `exit`：只设置退出请求；实际关闭统一由 REPL 主循环的 `finally` 完成。

## 固定审查提示词

```text
Review the current workspace's uncommitted Git changes. Inspect the working
tree and report only actionable findings, ordered by severity, with file and
line references where possible. Focus on defects, behavioral regressions,
security risks, and missing tests. Do not modify files. If there are no
findings, say so explicitly.
```

该文本作为一个固定常量发送，不预先执行 Git、不插入 diff，也不根据当前持续模式改变。

## 稳定输出格式

`/session`：

```text
session: id=<id> state=<new|resumed> messages=<count> operation=<idle|busy>
title: <sanitized title>
```

`/memory`：

```text
memory: project=<count> user=<count> update=<state>
index: lines=<used>/<limit> bytes=<used>/<limit>
```

`/status`：

```text
mode: [DEFAULT|PLAN]
session: <id>
permission: <strict|default|allow>
tokens: in=<n|n/a> out=<n|n/a> total=<n|n/a> cache-read=<n|n/a> cache-write=<n|n/a> requests=<n> unreported=<n>
context: automatic-compaction=<enabled|disabled> consecutive-failures=<n>
memory: project=<n> user=<n> update=<state>
```

帮助列表按规范名称排序；错误统一使用 `Error:` 前缀。标题继续复用现有清理和截断规则，状态输出不包含正文。

## 模块交互

### 启动流程

```text
CLI
  -> 创建真实 Provider
  -> 创建 UsageLedger
  -> 用 UsageTrackingProvider 包裹真实 Provider
  -> 将同一跟踪 Provider 注入 Agent、上下文压缩、记忆更新
  -> 初始化工具、MCP、权限、会话、记忆和 Conversation
  -> 构造全部内置 CommandDefinition
  -> 构造 CommandRegistry 并完成冲突检查
       -> 失败：输出安全错误，返回非零，不创建输入提示
  -> 创建 InteractionState(DEFAULT)
  -> 创建 PromptToolkitTerminal(registry, state)
  -> 创建 CommandDispatcher 与 Repl
  -> 进入单一异步 REPL 生命周期
```

注册表先于交互终端启动，但晚于基本配置加载。注册失败不会遗留会话输入循环或后台任务。

### 输入分流

```text
TerminalSession.prompt()
  -> parse_input(raw)
     -> EMPTY   -> 直接显示下一次提示
     -> COMMAND -> CommandDispatcher.dispatch()
     -> MESSAGE -> Repl 按 InteractionState 选择 ConversationMode
```

普通输入映射：

```text
InteractionMode.DEFAULT -> ConversationMode.DEFAULT
InteractionMode.PLAN    -> ConversationMode.PLAN
```

命令输入无论是否命中都不会进入普通消息路径。

### 命令分发

```text
ParsedInput(COMMAND)
  -> registry.resolve(identifier)
     -> 未命中：ui.show_error("Unknown command ... Use /help.")
     -> 命中：
          await definition.handler(context, arguments)
             -> CommandUsageError
                  -> 显示 definition.usage
             -> CommandExecutionError
                  -> 显示经过约束的安全消息
             -> 未预期异常
                  -> 显示通用失败消息，不输出异常正文或堆栈
```

分发器不按 `CommandType` 推断行为；类型是登记、帮助和测试元数据，真实行为只由处理函数通过协议能力执行。测试会校验每条内置命令的登记类型与调用路径一致。

### 普通消息与计划模式

```text
Repl
  -> Conversation.send(text, DEFAULT|PLAN)
  -> 等待上一轮记忆更新并输出必要诊断
  -> 选择工具集和 AgentMode
  -> AgentRunner
  -> UsageTrackingProvider
  -> 流式事件回到 Repl
  -> EventRenderer 即时输出
  -> 自然完成后调度 MemoryManager 更新
  -> 返回输入提示，后台更新继续在同一事件循环运行
```

`PLAN` 使用现有 Agent 计划提示和计划终结阶段，但最终文本只作为普通助手消息写入历史，不再建立单独待执行计划。`/do` 仅影响下一条输入的路由。

### `/review`

```text
/review
  -> 固定处理函数
  -> ui.send_user_message(REVIEW_PROMPT, read_only=True)
  -> Conversation.send(REVIEW_PROMPT, READ_ONLY)
  -> DIRECT 提示 + 只读工具集
  -> 正常事件渲染与历史提交
  -> 完成或失败
  -> InteractionState 保持原值
```

只读约束来自工具集合筛选，不依赖提示词中的 “Do not modify files”。

### `/compact`

```text
/compact
  -> runtime.compact_context()
  -> Conversation.compact()
  -> 等待既有记忆更新
  -> ContextManager 手动压缩
  -> UsageTrackingProvider 统计摘要模型调用
  -> Repl 使用现有 AgentContextStatus 渲染
  -> 成功时原子提交压缩后历史
```

该路径不创建 AgentRun；压缩失败沿用现有“历史不变”语义。

### 本地状态命令

`/session`、`/memory`、`/permission` 和 `/status` 只读取当前内存对象：

```text
handler
  -> runtime/ui snapshot
  -> pure formatter
  -> ui.show_message
```

它们不调用 Conversation 的预检，因此不会等待正在运行或尚未收尾的记忆更新。`/memory` 可以即时显示 `running`；`/status` 的 Token 只包含快照时已经结束并登记的模型流。

### Token 统计

```text
所有 ModelRequest
  -> UsageTrackingProvider.stream_reply()
       -> 转发所有 ProviderEvent
       -> 保留最后一个 ProviderUsage
       -> 流结束/失败/取消时向 UsageLedger 登记一次
  -> 原消费者继续按原逻辑处理
```

计数规则：

- Agent 自身的 `AgentTokenUsage` 仍表示单次 AgentRun 内累计值，只用于现有流式输出。
- 全局 `UsageLedger` 只从 Provider 边界计数。
- ContextStatus 中携带的 usage 不再次计数。
- MemoryUpdater 即使忽略 `ProviderUsage` 事件，外层跟踪器仍会计数。
- 自动压缩和手动压缩使用同一包装 Provider，因此自然纳入。
- 一个模型流无 usage、抛错或在 usage 前取消时，`unreported_request_count` 增加，并使对应累计字段显示 `n/a`。
- 查询快照不修改账本。

### 记忆状态

```text
初始化成功       -> IDLE
存储不可安全写入 -> DISABLED
schedule()       -> RUNNING
更新完整成功     -> SUCCEEDED
更新任一步失败   -> FAILED
下一次 schedule  -> RUNNING
```

成功但没有产生 mutation 仍记为 `SUCCEEDED`。条目数来自当前已加载 catalog，容量来自当前 `MemoryPromptView` 和实际 `MemoryConfig`。

### 权限询问

Agent 事件流遇到权限请求时，REPL 使用 `await terminal.prompt_permission(...)`。输入仍沿用现有 `deny/once/session/permanent` 映射：

- 非法输入继续询问。
- EOF 解析为拒绝。
- 权限提示不启用斜杠命令补全。
- 权限决议仍由现有 Challenge 和 PermissionController 执行。

### 补全流程

补全只在光标位于首个空格之前且当前文本以 `/` 开头时启用：

```text
当前命令前缀
  -> registry.completion_candidates(casefolded prefix)
     -> 0 个：无动作
     -> 1 个：直接替换为完整候选
              有参数提示时追加一个空格
     -> 多个：启动 prompt_toolkit 选择菜单
```

候选包括公开规范名称和公开别名，显示时带 `/`；候选顺序固定。光标进入参数区域后不再提供命令名候选。

## 异步生命周期

`Repl.run()` 保持同步 CLI 签名，但内部只创建一个 `asyncio.Runner`，并一次运行完整 `_run_loop()`。不再为每条消息分别启动和停止事件循环。

```text
Runner 创建
  -> await 启动消息输出
  -> while not exit_requested:
       await terminal.prompt()
       await 路由或分发
  -> finally:
       await conversation.close()
       输出安全关闭警告
  -> Runner 关闭
```

这样后台记忆任务可在用户停留于输入提示时继续执行，同时本地命令无需等待它。

退出行为：

- `/exit`、`/quit`：设置 `exit_requested`，结束循环后统一关闭。
- EOF：与隐藏退出命令走相同的正常关闭路径。
- 输入阶段 `KeyboardInterrupt`：保持现有进程中断语义，完成关闭后返回 130。
- Agent 或压缩阶段取消：调用现有取消能力，显示取消结果并返回输入循环。
- 关闭阶段失败：输出不含敏感正文的警告，继续释放其余资源。

## 状态栏一致性

`PromptToolkitTerminal` 的底栏回调直接读取共享 `InteractionState.mode`。模式切换、清屏和 `/status` 会调用 `invalidate()`；普通或流式输出结束后，下一次 `prompt()` 自动重新绘制底栏。

状态栏不缓存独立模式字符串，因此不存在命令状态与显示状态分叉。

## 错误路径

| 错误 | 处理 |
|---|---|
| 注册名称或别名冲突 | 抛出 `CommandRegistrationError`，CLI 输出冲突标识并返回 1 |
| 未知命令 | 显示未知命令及 `/help` 引导，不调用处理函数 |
| 参数不合法 | 显示登记的 `Usage:`，不执行副作用 |
| 可预期本地状态错误 | `CommandExecutionError` 携带安全消息，循环继续 |
| 未预期命令异常 | 记录为通用命令失败，不向终端暴露异常正文或堆栈 |
| `/review` 对话失败 | 沿用 Conversation 安全错误，持续模式不变 |
| `/compact` 失败 | 显示现有压缩失败状态，历史不变 |
| Token 未报告 | 累计相关字段标记 `n/a`，不猜测 |
| 终端 EOF | 正常关闭并返回 0 |
| 关闭警告 | 写入错误流，继续其他收尾 |

## 文件组织

```text
MewCode/
├── pyproject.toml                         # 增加 prompt-toolkit 运行依赖
├── README.md                              # 更新斜杠命令、模式和补全说明
├── src/mewcode/
│   ├── cli.py                             # 组装用量跟踪、注册表、终端和 REPL
│   ├── conversation.py                    # 统一 send 路由与会话状态快照
│   ├── repl.py                            # 单事件循环、命令分流、协议适配
│   ├── terminal.py                        # prompt_toolkit 终端适配与补全
│   ├── commands/
│   │   ├── __init__.py                    # 导出命令公共接口
│   │   ├── core.py                        # 模型、错误、解析器、不可变注册表
│   │   ├── contracts.py                   # UI/Runtime 协议与交互状态
│   │   ├── dispatcher.py                  # 异步命令分发与错误收敛
│   │   └── builtin.py                     # 内置定义、处理函数、固定提示、格式化
│   ├── providers/
│   │   ├── __init__.py                    # 导出用量跟踪接口
│   │   └── usage.py                       # UsageLedger 与 Provider 装饰器
│   ├── context/
│   │   ├── __init__.py                    # 导出上下文状态快照
│   │   ├── models.py                      # ContextRuntimeStatus
│   │   └── manager.py                     # status() 查询
│   └── continuity/
│       ├── __init__.py                    # 导出记忆运行状态
│       ├── memory_models.py               # MemoryUpdateState/RuntimeStatus
│       ├── memory_store.py                # 只读暴露实际 MemoryConfig
│       └── memory_manager.py              # 状态机与 status() 查询
└── tests/
    ├── test_command_core.py                # 解析、注册、冲突、排序、补全候选
    ├── test_command_dispatcher.py          # 未知、用法、错误隔离、异步处理
    ├── test_builtin_commands.py            # 十个公开命令与隐藏退出命令
    ├── test_terminal.py                    # Tab、菜单、底栏、清屏和 EOF
    ├── test_usage_tracking.py              # 全模型流累计及缺失 usage
    ├── test_repl.py                        # 异步主循环、分流、权限、退出、渲染
    ├── test_conversation.py                # 三种 ConversationMode 与旧计划兼容
    ├── test_context_manager.py             # 上下文状态快照
    ├── test_memory_manager.py              # 记忆状态转换与安全摘要
    └── test_continuity_integration.py      # 会话恢复、记忆、命令端到端
```

不修改会话 JSONL 格式。`StoredPlan` 及其编解码继续保留，避免旧文件因未知记录而损坏。

## 关键技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 注册生命周期 | 一次性批量构造不可变注册表 | 能在首次输入前检查全部名称与别名，也符合本阶段不做动态注册的边界 |
| 标识规范化 | 使用 Unicode `casefold()` | 比简单 `lower()` 更稳定地表达大小写不敏感 |
| 参数解析 | 只按第一个 ASCII 空格切分 | 严格对应已批准 Spec，不引入 shell 引号或结构化参数语义 |
| 处理函数模型 | 所有处理函数统一为异步签名 | `/compact`、`/review` 需要等待；本地命令可立即返回，分发器无需双轨逻辑 |
| 命令类型 | 作为元数据和测试约束，不作为隐式执行器 | 避免类型标签替代清晰处理行为，同时保留后续 Skill 扩展信息 |
| 依赖反转 | 命令处理函数只接收 `CommandUI` 与 `CommandRuntime` | 命令不绑定 REPL、输出流或终端库，测试可以使用轻量 fake |
| 终端能力 | `prompt_toolkit` 3.x | 跨平台提供异步输入、补全菜单、按键绑定、清屏和底栏 |
| 输入历史 | 显式使用无历史实现 | 避免超出“不增加命令历史搜索”的范围 |
| Tab 行为 | 自定义 Tab 绑定而非依赖默认绑定 | 明确保证单候选直接补全、多候选打开菜单 |
| 状态所有权 | 单个共享 `InteractionState` | REPL 路由和底栏读取同一模式值，避免显示与行为分叉 |
| REPL 生命周期 | 一个 `asyncio.Runner` 运行完整会话 | 后台记忆可在等待用户输入时继续，权限提示和命令也能统一 await |
| 对话 API | 单一 `send(text, ConversationMode)` | 工具边界和提示模式在同一处组合，避免 REPL 再次硬编码三套调用 |
| `/review` 只读 | `DIRECT` 提示模式 + 只读工具集 | 审查不应触发计划终结提示，同时强制阻止写操作 |
| 旧计划记录 | 继续解析但运行期忽略 | 不迁移、不重写旧会话，同时彻底取消 `/do` 自动执行语义 |
| Token 聚合位置 | Provider 装饰器 | Agent、自动/手动压缩和记忆更新全部经过该边界，可一次覆盖 |
| Token 去重 | 每个模型流结束时只登记一次 | 避免同时从 Provider、AgentEvent 和 ContextStatus 重复累计 |
| 缺失 Token | 对应累计字段永久变为未知并显示 `n/a` | 无法可靠恢复缺失值，不能用估算冒充实际账单数据 |
| 状态查询 | 只读取内存快照 | `/session`、`/memory`、`/status` 不等待后台任务、不扫描正文、不访问网络 |
| 命令错误 | 已知错误显示安全消息，未知异常显示通用消息 | 保持交互可用并避免把正文、路径或秘密从异常中带到终端 |
| 帮助与补全 | 始终由注册表派生 | 新增登记后自动可发现，不产生第二份易漂移清单 |
| 隐藏命令 | 可解析但从公开查询中过滤 | 保留 `/exit`、`/quit` 兼容，同时满足十个公开命令的产品边界 |

## 需求覆盖

| 需求范围 | 主要归属 |
|---|---|
| F1-F4 | 命令核心、内置注册表、CLI 启动失败 |
| F5-F10 | 输入解析器、分发器、REPL 三路分流 |
| F11-F15 | CommandUI/CommandRuntime、REPL 适配 |
| F16-F20 | InteractionState、ConversationMode、底部状态栏 |
| F21-F24 | 注册表派生帮助、CommandCompleter、Tab 绑定 |
| F25-F36 | 内置命令处理、运行状态快照、用量跟踪、正常关闭 |
| N1-N3 | 不可变注册、确定性排序、明确命令执行路径 |
| N4-N5 | prompt_toolkit 终端适配和单一状态所有权 |
| N6-N7、N12 | 分发错误边界、安全格式化和现有文本清理 |
| N8 | 保留领域组件与持久化格式，只替换明确的 Plan/Do 路由 |
| N9 | 协议 fake、可控 Provider、脚本化终端 |
| N10-N11 | 注册表派生能力和协议隔离 |
| N13-N14 | 工具集合强制只读和固定提示常量 |

## 技术验证策略

- 命令核心使用纯单元测试覆盖完整冲突矩阵、大小写、空输入、参数保真、隐藏过滤和确定性排序。
- 内置命令使用 fake UI/Runtime 记录调用，不启动真实终端、网络或模型。
- 终端测试使用 `prompt_toolkit` 的管道输入与无界面输出，发送真实 Tab 键序列验证单补全和多候选菜单。
- 用量跟踪使用可控异步 Provider，覆盖成功、多 usage、无 usage、异常和取消。
- Conversation 使用现有 fake Provider 与工具注册表验证三种策略实际收到的工具集合。
- REPL 使用脚本化 TerminalSession 验证命令分流、模式持久、权限提示、EOF 和关闭顺序。
- CLI/连续性集成测试使用临时目录和 fake Provider，执行已批准的端到端命令序列。
- 最终运行完整 `pytest`，并执行 `git diff --check`；项目当前没有独立 lint 配置，不虚构 lint 命令。
