# 子 Agent 系统 Plan

## 架构概览

本阶段新增独立的 `mewcode.subagents` 子系统，不改写现有 Skill 语义。现有 `mewcode.agent` 继续负责单个 ReAct 循环；子 Agent 子系统负责角色目录、委派参数校验、父请求快照、任务生命周期、隔离运行时、后台通知和本地管理命令。主装配层把这些组件接到现有 Provider、Hook、权限、上下文、Conversation、REPL 与工具注册表。

### 角色目录

启动时从项目、用户、内置及调用方注入的插件目录发现单文件 Markdown 角色。角色加载器完成严格 frontmatter 解析、Profile 与工具名称校验、同层冲突检查、跨层有效版本回退和总量限制，最终生成不可变目录快照。目录内容只被 Agent 工具按字符串角色名查询，不进入工具参数枚举，因此角色数量不会改变主 Agent 的工具 schema。

### 请求边界与 Fork 快照

在 Hook 已完成 `message.before` 并追加其临时提示后、真正 Provider 请求开始前，统一请求边界执行两项工作：只为根主 Agent 消费并追加子任务完成通知；捕获本次实际 `ModelRequest` 作为当前迭代的父请求快照。`AgentRun` 把该快照、当前 Profile、模式、轮次上限、父 run ID 和实际工具视图封装为控制工具调用上下文，再交给 Agent 工具。

Fork 子 Agent 的首次请求以这个快照为种子，在原系统提示、消息和工具 schema 之后只追加新的用户任务。Fork 为任务创建字节等价、顺序一致的工具 schema 视图，同时使用独立执行策略硬拒绝 Agent、模型代理控制入口、后台名单外能力及父模式越界能力；因此模型请求保留缓存前缀，但展示的工具不等于可执行权限。

### 委派协调器与统一 Agent 工具

主工具注册表只增加一个固定 schema 的 Agent 控制工具。工具把定义式/Fork 式参数与当前控制上下文交给委派协调器。协调器解析角色或 Fork 快照，冻结 Profile、角色、工具视图、执行策略、持久权限规则和父关联，构造任务启动说明并原子注册任务。参数错误、未知角色、缺失快照或容量超限都在创建模型请求前转成普通工具失败。

### 隔离运行时工厂

每个任务由运行时工厂创建独立的 Agent 配置、ToolScheduler、PermissionController、ContextManager、ContextArchive、文件读取缓存、Hook 任务作用域和取消状态。定义式运行以空消息历史、基础动态上下文与角色正文启动；Fork 运行以父请求种子启动。Provider/Profile 目录、PromptBuilder、HookRuntime、Workspace、底层工具/MCP 会话和进程级 UsageLedger 继续共享。

任务工具视图为每个任务创建轻量代理对象，保持名称、说明、schema、顺序和安全分类不变，同时记录该任务自己的文件读取观察。定义式在进入模型请求前直接裁剪 schema；Fork 保留父 schema，但 Task ToolScheduler 在 Hook 和权限之前应用冻结执行策略。任务权限控制器使用去掉父会话规则的持久规则快照，并把所有 `ASK` 同步转换为带原因的 `DENY`，不产生终端挑战。

### 任务管理器

进程内任务管理器是唯一的任务状态所有者。它在锁内执行 8 个活动任务的容量检查与 UUID 注册，在独立 `asyncio.Task` 中跑完子 Agent，并以“首个终态获胜”收敛完成、失败与取消竞争。它保存有界结果、错误、进度、时间和任务级 usage，维护当前可手动转后台的唯一前台任务，并在通知完成后按规则淘汰旧终态记录。

定义式默认以前台订阅方式等待：10 秒内结束则 Agent 工具取得最终结果；超时、显式后台或 `Ctrl+B` 只解除前台订阅并返回任务 ID，底层任务不重启。Fork 注册后立即解除订阅。`Ctrl+C` 通过现有 AgentRun → ToolSchedule → 控制操作取消链取消仍在前台的任务；已解除订阅的后台任务只能通过任务命令、`/reset` 或关闭流程取消。

### 通知与本地交互

任务进入终态时先把一次有界完成记录放入通知队列，再发布终端生命周期事件。REPL 用独立监视协程消费终端事件，并通过 prompt-toolkit 安全通知接口输出单行摘要。根主 Agent 的请求边界按完成顺序、条数和字节预算消费通知；子 Agent、压缩、记忆及其他 Provider 请求没有该消费能力。

静态命令目录新增 `/tasks` 与 `/task`，通过 Conversation 暴露的只读任务查询和异步取消接口访问管理器。REPL 在消费 Agent 事件期间并行监听运行控制键；收到 `Ctrl+B` 时只调用任务管理器的前台转后台操作，遇到权限挑战前暂时停止控制键读取，避免与交互式权限输入竞争。

### 生命周期装配

CLI 先装配基础/MCP 工具、Profile、权限和 Hook，再构建角色目录、后台能力名单、通知队列、任务管理器及固定 Agent 工具，最后把完整工具注册表交给 Skill 与 Conversation。Conversation 在 `/reset` 时先清理任务和通知再清理会话，在关闭时先取消主运行和子任务，再关闭 Memory、Session、Skill、Context 与共享 Hook/Provider 资源，防止后台任务使用已关闭基础设施。

```text
主 Agent Provider 请求
  -> Hook 注入
  -> 根通知注入 + 实际请求快照
  -> Provider 响应调用 Agent 工具
  -> 委派协调器
       -> 定义式：角色目录 + 空历史
       -> Fork 式：父请求种子 + 同 schema 执行策略
  -> 任务管理器
       -> 隔离 Agent 运行时 -> 共享 Provider / Hook / Workspace
       -> 前台完成：最终 ToolResult
       -> 转入后台：task ID -> 完成通知队列 -> 根主 Agent 下一请求
```

## 核心数据结构与接口

### 角色定义模型

`mewcode.subagents.models` 集中声明限制常量、枚举和不可变快照：

```python
class AgentDefinitionLayer(IntEnum):
    PLUGIN = 0
    BUILTIN = 1
    USER = 2
    PROJECT = 3

@dataclass(frozen=True)
class AgentDefinitionSource:
    layer: AgentDefinitionLayer
    root: Path
    path: Path
    entry_name: str
    origin: str

@dataclass(frozen=True)
class AgentDefinition:
    name: str
    description: str
    tools: tuple[str, ...]
    disallowed_tools: tuple[str, ...]
    model: str                    # "inherit" 或 Profile 名称
    max_turns: int                # 1..100
    permission_mode: PermissionMode
    system_prompt: str
    source: AgentDefinitionSource

@dataclass(frozen=True)
class AgentDefinitionCatalog:
    definitions: Mapping[str, AgentDefinition]
    diagnostics: tuple[AgentDefinitionDiagnostic, ...]
```

角色文件只识别以下七个 frontmatter 字段，全部必填：

```yaml
---
name: code-reviewer
description: Review a change without modifying it.
tools:
  - read_file
  - search_code
disallowed_tools: []
model: inherit
max_turns: 20
permission_mode: default
---
You are an independent code reviewer...
```

默认根目录为 `<workspace>/.mewcode/agents/`、`~/.mewcode/agents/` 和包内 `subagents/builtin/`。插件根目录以 `Sequence[Path]` 传给发现函数；同一插件层没有隐式先后级，重复有效名称按冲突处理。只发现根目录直属的 `<name>.md`，不接受目录包或符号链接。角色正文启动时完整读入目录快照，不保存文件惰性引用。

### 统一 Agent 工具与控制上下文

公开工具名为 `agent`，标记为始终可见的只读控制工具；它不因角色目录改变 schema：

```json
{
  "type": "object",
  "properties": {
    "type": {"type": "string", "enum": ["defined", "fork"]},
    "task": {"type": "string"},
    "role": {"type": "string"},
    "background": {"type": "boolean"}
  },
  "required": ["type", "task"],
  "additionalProperties": false
}
```

定义式要求 `role`，`background` 缺省为 `false`；Fork 式禁止同时提供 `role` 或 `background`。字符串大小、空白和组合约束由控制操作在任务注册前完成，工具 schema 不使用条件分支或动态角色枚举。

现有控制工具协议扩展为显式接收本次工具调用上下文；`LoadSkillTool` 接收但忽略新增参数，保持原行为：

```python
@dataclass(frozen=True)
class AgentControlContext:
    run_id: str
    iteration: int
    mode: AgentMode
    profile_name: str
    permission_mode: PermissionMode
    max_iterations: int
    allowed_safety: frozenset[ToolSafety]
    parent_request: ModelRequest

class AgentControlTool(Protocol):
    def control_operation(
        self,
        arguments: dict[str, object],
        context: AgentControlContext,
    ) -> AgentControlOperation: ...
```

`parent_request` 是当前迭代真正发送给 Provider 的最终请求，不包含产生本次 `agent` 调用的助手响应。若请求边界未能捕获最终请求，Agent 调用返回安全失败，不能用提交历史拼凑一个近似 Fork。

### 请求种子与执行策略

```python
@dataclass(frozen=True)
class ForkRequestSeed:
    profile_name: str
    request: ModelRequest
    parent_run_id: str
    parent_iteration: int
    permission_mode: PermissionMode
    max_iterations: int
    allowed_safety: frozenset[ToolSafety]

@dataclass(frozen=True)
class ToolPolicyDecision:
    allowed: bool
    reason: str = ""

class ToolExecutionPolicy(Protocol):
    def evaluate(
        self,
        call: ValidatedToolCall,
        preflight: PermissionPreflight | None,
    ) -> ToolPolicyDecision: ...
```

`FrozenSubagentToolPolicy` 保存不可变 `executable_names` 和按名称生成的拒绝原因。主 Agent 使用全允许策略；定义式使用与已裁剪 schema 相同的允许集合做第二道防线；Fork 的 `ModelRequest.tools` 保持父 schema 字节等价，但其 Task ToolScheduler 使用策略限制实际执行集合。调度顺序固定为“参数校验 → 现有危险命令/路径 preflight → 子 Agent 执行策略 → Hook before → 权限模式 → 工具”，策略拒绝新增 `PermissionSource.SUBAGENT_POLICY`，不会把参数发送给外部 Hook。

角色工具集合计算为：

```text
defined_executable =
    parent_mode_tool_names
    ∩ role.tools
    ∩ background_capable_names
    - role.disallowed_tools
    - globally_forbidden_names

fork_executable =
    parent_request_tool_names
    ∩ background_capable_names
    ∩ names_allowed_by_parent_mode
    - globally_forbidden_names
```

CLI 首期把基础内置工具和 MCP 工具的启动快照作为 `background_capable_names`；`agent`、`load_skill` 以及未来明确标记为模型代理入口的控制工具属于 `globally_forbidden_names`。Skill 包专属工具不自动进入后台名单。

### 非交互权限与任务级工具状态

`SubagentPermissionController` 包装现有 `PermissionController`：构造时复制 `PermissionRuleStore.snapshot()` 的 project-local、project 和 user 元组，把 session 元组置空，并使用空操作持久化 writer。定义式权限模式来自角色；Fork 权限模式来自 `AgentControlContext`。`preflight` 保留现有硬拒绝，`evaluate_preflight` 把底层 `ASK` 改写为 `DENY / PermissionSource.SUBAGENT_NON_INTERACTIVE`，`apply_choice` 不会被调用。

```python
@dataclass
class FileReadObservationCache:
    observations: dict[str, FileReadObservation]

@dataclass(frozen=True)
class FileReadObservation:
    path: str
    content_digest: str
    bytes_read: int
```

`TaskScopedTool` 保持被代理工具的公开元数据不变。成功 `read_file` 后从结果记录规范相对路径、内容摘要和字节数；当前任务的 `write_file`/`edit_file` 成功后只清除自己的同路径观察。代理始终重新访问底层文件系统，不用缓存内容替代真实读取，因此其他任务已提交的文件变化仍可见。每个任务持有独立缓存实例；MCP 会话和无状态工具实例仍可共享。

### 任务模型与管理接口

```python
class SubagentKind(StrEnum):
    DEFINED = "defined"
    FORK = "fork"

class SubagentTaskStatus(StrEnum):
    REGISTERED = "registered"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class SubagentPlacement(StrEnum):
    FOREGROUND = "foreground"
    BACKGROUND = "background"

@dataclass(frozen=True)
class SubagentParent:
    run_id: str
    iteration: int

@dataclass(frozen=True)
class SubagentProgress:
    iteration: int
    phase: str
    message: str

@dataclass(frozen=True)
class SubagentTaskSnapshot:
    task_id: str
    kind: SubagentKind
    status: SubagentTaskStatus
    placement: SubagentPlacement
    role: str | None
    profile_name: str
    parent: SubagentParent
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    progress: SubagentProgress | None
    result: str
    error: str | None
    truncated: bool
    usage: TokenUsage
    notification_pending: bool
```

时间快照使用 UTC wall clock 供显示，10 秒转换与竞争判定使用单调时钟。内部 `_ManagedSubagentTask` 额外保存 `asyncio.Task`、取消锁、前台解除事件、事件订阅队列和独立运行时清理回调，不对命令层暴露。

```python
class SubagentTaskManager:
    async def start(self, launch: SubagentLaunch) -> SubagentTaskHandle: ...
    async def detach_foreground(self, task_id: str, reason: str) -> bool: ...
    async def detach_current_foreground(self, reason: str) -> str | None: ...
    async def cancel(self, task_id: str) -> TaskCancelResult: ...
    def list(self) -> tuple[SubagentTaskSnapshot, ...]: ...
    def get(self, task_id: str) -> SubagentTaskSnapshot | None: ...
    async def terminal_events(self) -> AsyncIterator[SubagentTerminalEvent]: ...
    async def reset(self) -> tuple[SubagentDiagnostic, ...]: ...
    async def close(self) -> tuple[SubagentDiagnostic, ...]: ...
```

`start()` 在同一锁内检查活动数、生成 UUID、注册记录和创建驱动任务。`SubagentTaskHandle.foreground_events(timeout=10)` 是 Agent 控制操作的唯一前台订阅；它转发有界任务进度，并在终态、显式解除、手动解除或超时解除中的首个条件发生时结束。控制操作取消只取消仍处于前台的底层任务；一旦已解除，控制操作已返回且不再拥有任务。

### 通知与 Provider 请求边界

```python
@dataclass(frozen=True)
class SubagentNotification:
    task_id: str
    status: SubagentTaskStatus
    role: str | None
    result: str
    error: str | None
    truncated: bool
    usage: TokenUsage
    completed_at: datetime

@dataclass(frozen=True)
class NotificationBatch:
    notifications: tuple[SubagentNotification, ...]
    rendered_system_section: str
    encoded_bytes: int

class SubagentNotificationQueue:
    def enqueue_once(self, notification: SubagentNotification) -> bool: ...
    def consume_batch(self, max_items: int = 16, max_bytes: int = 65536) -> NotificationBatch: ...
    def clear(self) -> None: ...
```

队列按完成顺序保存并用 task ID 去重。渲染内容放在 `## Completed Subagent Tasks` 动态系统区，以明确的 `<untrusted-subagent-results>` 边界包裹；每项包含 ID、终态、角色、usage 和有界结果/错误。批次消费成功后通知标记 delivered，并触发任务管理器执行 128 条终态保留策略。

Provider 栈增加位于 `HookedProvider` 内侧的 `RequestBoundaryProvider`。它读取 ContextVar 中当前 `ProviderRequestBoundary`：

```python
class ProviderRequestBoundary(Protocol):
    def prepare(self, request: ModelRequest) -> ModelRequest: ...

class RootAgentRequestBoundary:
    # 先追加通知，再保存最终实际请求到 RequestSnapshotSlot

class CaptureOnlyRequestBoundary:
    # 不消费通知，只保存实际请求；主要用于一致测试和未来控制工具
```

`AgentRun` 在每次真实 Provider 调用期间绑定边界，并把捕获槽生成的 `AgentControlContext` 传给 ToolScheduler。HookedProvider 先完成 Hook prompt 追加，再调用内层 RequestBoundaryProvider，所以 Fork 捕获的是最终请求。没有绑定边界的上下文压缩、记忆和其他维护请求原样通过，也不能消费通知。

### Prompt 与终端控制接口

`PromptAdditions` 新增 `agent_role`，`PromptBuilder` 在 Custom Instructions 之后、Skill 目录之前渲染动态 `## Agent Role`；定义式只填写此字段，不填写 available/active Skill。Fork 直接复用父 `PromptPackage`，不重新构建系统提示。

`AgentEvent` 新增只含任务 ID、位置、状态和有界进度的 `AgentSubagentProgress`，前台订阅不向主事件流转发子 Agent 原始文本、工具参数或内部消息。

```python
class RunControl(StrEnum):
    BACKGROUND = "background"

class TerminalSession(Protocol):
    async def read_run_control(self) -> RunControl: ...
    async def notify(self, text: str) -> None: ...
```

`PromptToolkitTerminal.read_run_control()` 在没有 PromptSession 读取 stdin 时通过现有 `Input` 等待 `Ctrl+B`；REPL 遇到主权限挑战时先取消该等待，再启动权限 PromptSession。`notify()` 在提示符活动时使用 prompt-toolkit 的安全终端回调输出，否则直接写 stdout。Legacy 与测试终端可返回永不完成的控制 Future 或注入确定按键。

## 模块设计

### 角色发现与目录

**位置：** `mewcode.subagents.models`、`paths`、`parser`、`catalog`

**职责：**

- `models` 定义角色层级、来源、角色、诊断、目录快照、错误和全部产品限制常量。
- `paths` 只扫描直属 `.md` 文件，拒绝符号链接，按规范路径和确定顺序产生来源；每个根目录超过 256 个候选时产生目录错误，不读取部分随机集合。
- `parser` 以二进制读取并限制单文件 64 KiB，验证 UTF-8、严格 YAML、文件名与角色名一致、七个必填字段、正文非空、列表去重和 1..100 轮次。
- `catalog` 按名称和层级聚合候选；同层多个有效候选是全局冲突，高层无效则记录诊断并回退。它用 `ProfileCatalog`、基础工具名和全局禁止名验证模型与工具，最后检查选中正文合计不超过 1 MiB。

**对外接口：** `AgentDefinitionRoots.defaults()`、`discover_agent_sources()`、`parse_agent_definition()`、`build_agent_catalog()`。

**依赖：** pathlib、PyYAML、`ProfileCatalog`、`PermissionMode`；不依赖 AgentRunner、TaskManager、Conversation 或 REPL。

### 通用 Agent 控制扩展

**位置：** `mewcode.agent.control`、`runner`、`scheduler`、`events`

**职责：**

- `control` 增加 `AgentControlContext`，并把控制工具协议改为接收上下文。
- `runner` 为每次 Provider 请求创建捕获槽，支持正常 PromptBuilder 路径和 Fork `seed_request` 路径；Provider 返回工具调用后，把实际请求快照封装进控制上下文。
- `runner` 保存构造时的 Profile 名称、PermissionMode supplier、允许的 ToolSafety 和本次真实 loop limit。Fork 子运行采用 DIRECT 循环语义，但首轮及后续请求继续使用父 `PromptPackage`，不会重新生成父模式提醒。
- `scheduler` 接受默认全允许的 `ToolExecutionPolicy`，在硬 preflight 后、Hook 前执行；控制操作取得本次上下文。策略拒绝复用现有权限决定/工具失败通道，不进入普通工具执行。
- `events` 增加 `AgentSubagentProgress`，供前台委派显示任务级状态，不复用子运行的 run ID 事件作为主运行事件。

**兼容处理：** `AgentRunner` 与 `ToolScheduler` 新参数均有保持现状的默认值；`LoadSkillTool` 更新签名但忽略上下文。现有非 Agent 控制工具、普通工具批处理和取消顺序不变。

**依赖方向：** `mewcode.agent` 只依赖通用 Provider、Tool、Permission 和 Hook 类型，不导入 `mewcode.subagents`。

### Provider 请求边界

**位置：** `mewcode.providers.request_boundary`、`mewcode.hooks.provider`

**职责：**

- `request_boundary` 提供 `ProviderRequestBoundary`、ContextVar 绑定器和透明 `RequestBoundaryProvider`；透明包装器完整转发消息转换方法。
- CLI 对每个 Profile 始终缓存 `HookedProvider(RequestBoundaryProvider(UsageTrackingProvider))`。Hook 目录为空时 dispatch 走现有快速路径，但请求仍可被根 Agent 边界捕获。
- `HookedProvider` 保持现有事件与提示注入职责；其内层 BoundaryProvider 因调用顺序自然看到追加 Hook Context 后的最终请求。
- `RootAgentRequestBoundary` 由根 `AgentRun` 绑定，先调用通知注入器，再写入仅本迭代有效的快照槽；没有通知时返回原对象，减少无意义复制。
- Fork/定义式子运行绑定不消费通知的捕获边界；维护 Provider 调用不绑定边界，透明通过。

**依赖方向：** Provider 与 Hook 模块不知道任务目录或管理器；根边界通过小型 `RequestEnricher`/`RequestObserver` 协议接受回调。

### Hook 任务作用域

**位置：** `mewcode.hooks.runtime`、`events`

**职责：**

- Hook scope 新增可选 `subagent_task_id` 与 `parent_run_id`，序列化事件只增加这些安全标识，不增加历史或任务正文。
- 保留现有非子 Agent 全局 prompt 队列语义，使 session、turn、memory 和 compact 的“下一真实 Provider 请求”行为兼容。
- 子 Agent scope 下匹配出的 prompt 放入按 task ID 分区的队列；子 Agent Provider 只消费自己分区，不能消费全局或其他任务队列。
- 所有分区合计继续受现有 prompt 字节预算约束；任务结束时显式丢弃该 task ID 未消费提示，HookRuntime 关闭时清空全部分区。

**依赖：** HookRuntime 只识别 task ID 字符串，不依赖任务状态类型。

### 工具能力与文件观察

**位置：** `mewcode.subagents.policy`、`scoped_tools`

**职责：**

- `policy` 根据定义式角色或 Fork 种子构造冻结的可执行名称集合和稳定拒绝原因，实现通用 `ToolExecutionPolicy`。
- 定义式先调用 `ToolRegistry.select_names()` 生成模型 schema，再用同一集合创建策略；Fork 按父顺序逐项包装工具，保持公开字段和值相同，只由策略限制执行。
- `scoped_tools` 为工具创建透明任务代理并持有 `FileReadObservationCache`。代理不修改参数、结果正文、权限目标或 Hook 事件，只在成功结果后更新本任务观察。
- 全局禁止名单首期包含 `agent` 与 `load_skill`；后台能力名单从 `base_registry.names` 冻结，因此包括已启动 MCP 工具，不包括 Skill 包工具和随后加入的控制工具。

**依赖：** 通用 `ToolRegistry`/`Tool` 协议、工具结果 metadata；不依赖 REPL 或角色文件系统。

### 非交互权限

**位置：** `mewcode.subagents.permissions`

**职责：**

- 从主 `PermissionRuleSets` 构建 `session=()` 的不可变任务快照，保留 project-local/project/user 层。
- 用角色模式或 Fork 的父模式构建独立 PermissionController，维护任务自己的决策过程。
- 把 `ASK` 转为 `SUBAGENT_NON_INTERACTIVE` 来源的 DENY；拒绝原因不声称用户做过选择。
- 不调用 `PermissionConfigWriter`，也不允许子任务改变主 RuleStore。

**对外接口：** `create_subagent_permission_controller(workspace, persistent_snapshot, mode)`。

### 隔离运行时

**位置：** `mewcode.subagents.runtime`

**职责：**

- `SubagentRuntimeFactory` 接收 ProfileCatalog、共享 Provider supplier、PromptBuilder、Workspace、HookRuntime、基础 additions supplier、基础工具注册表和上下文配置工厂。
- 每次 `create(launch)` 新建任务级 ContextArchive 并以 task ID 派生独立目录；子归档启动时跳过全局 stale cleanup，避免并发任务互相扫描/删除，关闭时只删除自己的目录。
- 为任务创建 ContextManager、权限控制器、策略 ToolScheduler、文件观察工具视图和带任务 loop limit 的 AgentRunner；history commit sink 始终为 `None`。
- 定义式把人工指令、长期记忆和 `agent_role` 放入 PromptAdditions，明确清空 Skill 字段，并从空历史启动。
- Fork 把父 ModelRequest 的 PromptPackage/messages/max output 作为种子，追加任务用户消息；schema 工具用字节等价的任务代理注册表替换，执行策略另行冻结。
- 在整个运行期间绑定 `subagent_task_id`、`parent_run_id`、`component=subagent` Hook scope；消费子 Agent 原始事件来更新进度和 outcome，任务结束始终关闭 ContextManager/Archive 并清理 Hook prompt 分区。

**运行模式：** 两条路径都使用 AgentMode.DIRECT 的“自然结束即完成”循环控制。父 PLAN/READ_ONLY 只通过冻结安全上限影响工具，不让子运行进入现有 PLAN 的调查/最终化两阶段。

### 委派协调器与控制操作

**位置：** `mewcode.subagents.coordinator`、`control`

**职责：**

- `SubagentCoordinator.prepare()` 校验工具 JSON 之外的条件约束，解析角色，选择 Profile，计算定义式/Fork 工具和权限，生成 `SubagentLaunch`。
- `model=inherit` 使用 `AgentControlContext.profile_name`；指定 Profile 由目录加载阶段保证存在。
- 定义式从 Conversation 提供的基础 additions supplier 取人工指令与长期记忆，但只复制不可变内容；Fork 完全使用父请求种子。
- `AgentTool` 提供固定 schema 和控制操作；`SubagentDelegationOperation` 调用 TaskManager.start，按显式后台/Fork立即返回，或订阅前台事件直到完成/解除。
- 前台成功返回 `ok=True` 的有界最终 ToolResult；前台失败/取消返回 `ok=False`；后台返回 `ok=True`、task ID、位置和状态 metadata。操作被父 ToolSchedule 取消时，只取消仍绑定的前台任务。

**依赖：** 角色目录、运行时工厂、TaskManager 和通用 AgentControlContext；不导入 Conversation 或终端。

### 任务、通知与保留

**位置：** `mewcode.subagents.tasks`、`notifications`

**职责：**

- `tasks` 在一把 `asyncio.Lock` 下完成注册、前后台转换、首终态提交、通知资格判定和活动计数；耗时 Agent Run 在锁外执行。
- `_drive()` 是子 Agent 事件流唯一消费者，把原始事件压缩为 `SubagentProgress`，把 AgentRunOutcome 转成任务终态，并在 `finally` 调用运行时清理。
- 终态提交与 detach 使用同一锁：终态先获锁且仍为前台时不通知、由控制操作取结果；detach 先获锁则位置变为后台，后续终态恰好入队一次。
- `notifications` 负责结果/错误截断、去重、完成顺序、16 条/64 KiB 批次渲染与 delivered 回调。任务管理器只在 delivered 后把记录纳入 128 条可淘汰集合。
- `/reset` 设置 resetting 标记、阻止新任务、取消并有界等待、抑制清理期间新通知，最后原子清空记录和队列；`close` 同样收敛任务但无需恢复可用状态。
- 关闭 5 秒后仍未结束的驱动任务会被取消并 gather；诊断只报告 task ID 与安全状态，不暴露异常栈。

**并发不变量：** 活动数不超过 8；每个 ID 一个驱动任务；每个任务一个终态；后台终态最多一个通知；同一时刻最多一个 `FOREGROUND` 任务绑定当前 Agent 工具操作。

### Conversation 与命令

**位置：** `mewcode.conversation`、`mewcode.commands.contracts`、`builtin`

**职责：**

- Conversation 注入 TaskManager，提供 `list_subagent_tasks()`、`get_subagent_task()`、`cancel_subagent_task()`、`background_foreground_subagent()`，并把根通知 enricher 交给根 AgentRunner。
- `reset()` 在检查主 Conversation 空闲后先调用 TaskManager.reset，再重置 Session、Skill 与主 Context；任务清理失败转安全 ConversationError，不提交半重置会话。
- `close()` 在 Memory/Session/Skill/Context/Hook 之前关闭 TaskManager；多次关闭保持幂等。
- CommandRuntime 增加对应任务接口；`/tasks` 不接受参数，`/task <id>` 与 `/task cancel <id>` 使用严格 token 数解析。
- 命令格式化只读取 `SubagentTaskSnapshot`，统一 `n/a` usage、时间、截断和状态文本；所有任务命令保持本地，不写历史、不调用模型。

### REPL 与终端

**位置：** `mewcode.repl`、`terminal`

**职责：**

- REPL 启动后创建任务终态监视协程；Conversation.close 关闭任务事件流后，REPL 再收敛监视器，保证正常运行期间的终态摘要不会漏掉。
- `_consume()` 用一个 `anext(AgentEvent)` task 和一个 `read_run_control()` task 做竞速；Ctrl+B 调用 Conversation 转后台并渲染结果，Agent 事件继续消费。源完成或异常时取消按键等待。
- 收到 `AgentPermissionRequest` 时先取消运行键等待，再进入现有权限提示；处理后重新监听，避免同一 Input 被两个 PromptSession/reader 同时消费。
- `AgentSubagentProgress` 使用 `subagent[<short-id>]` 前缀渲染，不显示子 Agent 文本、参数或大结果。
- PromptToolkitTerminal 的 `notify()` 使用安全的 run-in-terminal 输出保持当前提示符；LegacyTerminal 直接写入。控制键 reader 只识别 Ctrl+B，其他普通字符在 Agent 运行期丢弃，Ctrl+C 继续走现有 KeyboardInterrupt 取消链。

### CLI 装配与兼容边界

**位置：** `mewcode.cli`、`skills.runtime`、包导出

**职责：**

- 静态命令目录先注册 `/tasks`、`/task`，使 Skill 命令冲突仍按现有规则启动失败。
- MCP 名称保留集合增加 `agent`；角色目录在基础/MCP 工具快照和 Profile 全部可用后构建。
- 创建持久权限 RuleStore 后冻结子 Agent 用的持久规则 supplier；随后创建通知、运行时工厂、TaskManager、Coordinator 与 AgentTool。
- 最终根工具注册表为 `base + load_skill + agent`。SkillRuntime 在根运行视图中始终保留 `agent`，但 isolated Skill 视图不自动获得它；因此主 Agent 即使激活共享 Skill 仍可委派，模型驱动 Skill 不形成额外父层。
- 根 AgentRunner 注入 Profile 名、PermissionMode supplier、通知 enricher 和控制上下文；isolated Skill runner 保持无通知、无 Agent 工具路径。
- 启动消息追加角色目录诊断；异常处理新增 AgentDefinitionCatalogError/DefinitionError；finally 依靠 Conversation 的幂等关闭，不重复创建或持久化任务状态。

**依赖顺序：** `providers/hooks/agent/tools` 通用层 ← `subagents` 功能层 ← `conversation/commands/repl/cli` 应用装配层。禁止通用层反向导入任务管理器，避免循环依赖。

## 模块交互

### 启动与冻结快照

```text
CLI
  -> 创建静态命令目录（含 /tasks、/task）
  -> 加载 Profile + Hook，并为每个 Profile 缓存：
       HookedProvider(RequestBoundaryProvider(UsageTrackingProvider))
  -> 预解析 Skill 包工具名
  -> 创建内置工具并启动 MCP
       reserved names 含 load_skill、agent、Skill 包工具名
  -> base_registry = builtin + MCP
  -> 构建最终 Skill 目录（已知全局工具含 agent）
  -> 发现并构建 AgentDefinitionCatalog
       known role tools = base_registry.names
       background capable = frozen(base_registry.names)
       global forbidden = {agent, load_skill, model-agent controls}
  -> 加载权限规则并创建主 PermissionController / ToolScheduler
  -> 创建主 ContextArchive / ContextManager / PromptBuilder
  -> 创建 NotificationQueue / SubagentRuntimeFactory / TaskManager
  -> 创建 Coordinator / AgentTool
  -> root_registry = base_registry + load_skill + agent
  -> 注入 SkillRuntime / root AgentRunner / Conversation / REPL
```

角色目录在任务系统之前完成，任一全局目录冲突、总量错误或 Profile 错误都让 CLI 在创建后台任务、终端监视器和会话运行之前失败。单候选解析错误只进入启动诊断。Provider 包装器按 Profile 缓存，根运行、子运行、压缩和记忆复用同一底层客户端与 UsageLedger。

### 根请求、快照与 Agent 工具调用

```text
Conversation.send
  -> root AgentRun iteration N
  -> ContextManager.prepare(candidate request)
  -> bind RootAgentRequestBoundary(snapshot_slot, notifications)
  -> HookedProvider.stream_reply
       -> message.before Hooks
       -> consume global Hook prompts -> append Hook Context
       -> inner RequestBoundaryProvider
            -> consume root task notifications -> append dynamic section
            -> snapshot_slot.capture(actual_request)
            -> UsageTrackingProvider -> real API
  -> response contains agent(...) tool call
  -> ToolScheduler.schedule(..., AgentControlContext(snapshot_slot.value))
       -> hard safety preflight
       -> main allow policy
       -> tool.before Hook
       -> AgentTool.control_operation(arguments, context)
```

每个 iteration 使用新快照槽；旧快照不能被后续工具批次误用。一次模型响应中的所有 Agent 控制调用共享产生该响应的同一父请求快照，但各自生成独立 task ID。若真实 Provider 没有经过边界、槽为空或快照 Profile 不一致，所有 Fork 调用安全失败；定义式仍要求有效控制上下文，但不读取父消息。

### 定义式前台快速完成

```text
AgentTool
  -> Coordinator 校验 type/task/role/background
  -> 解析角色 + Profile + parent mode safety
  -> 计算裁剪 schema 与 FrozenSubagentToolPolicy
  -> TaskManager.start(placement=foreground)
       [lock] capacity -> UUID -> REGISTERED -> create _drive task
  -> DelegationOperation.foreground_events(timeout=10s)

_drive task
  -> SubagentRuntimeFactory.create
       -> task ContextArchive.start(skip stale cleanup)
       -> task PermissionController / Scheduler / FileReadCache / ContextManager
       -> AgentRunner(max_iterations=role.max_turns)
  -> bind Hook task scope
  -> run blank history + task user message + Agent Role
  -> consume raw child events; publish only bounded progress
  -> natural response without tools
  -> [lock] RUNNING -> COMPLETED while placement still foreground
       -> do not enqueue notification
  -> close task runtime

foreground operation
  -> observes terminal snapshot before timeout/detach
  -> ToolResult(ok=True, bounded final result + usage)
  -> parent ToolScheduler commits only this ToolResult
  -> root AgentRun continues next iteration
```

前台失败、轮次/输出/上下文上限或 Ctrl+C 走同一路径，但 ToolResult 为失败并带安全错误。TaskManager 仍保留终态记录供 `/tasks` 查看；因为终态提交时仍为前台，不再额外通知根 Agent。

### 显式、自动与手动转后台

显式 `background=true` 的定义式和所有 Fork 在注册时直接使用 BACKGROUND placement；控制操作拿到 handle 后立即返回 task ID，不等待 `_drive` 创建 Provider 请求。

默认定义式的解除由同一个前台订阅处理：

```text
race:
  A. task terminal event
  B. injected monotonic timer reaches 10s
  C. TaskManager.detach_current_foreground("manual") from Ctrl+B
  D. parent operation cancellation from Ctrl+C
```

- A 先获得管理锁：任务保持前台，返回最终结果，不通知。
- B/C 先获得管理锁：placement 原子改为 BACKGROUND，订阅结束并向父返回 task ID；`_drive`、上下文、权限和 usage 不变。
- D 在仍前台时取消 `_drive` 并等待终态；若 B/C 已经解除，控制操作已经完成，之后的 Ctrl+C 只取消父 Agent，不影响后台任务。
- B/C 与 A 同时发生时以管理锁中的先提交状态为准，不能同时产生前台结果和后台通知。

REPL 的按键 reader 只在消费 Agent 事件时存在。Ctrl+B 返回的 task ID 通过 `AgentSubagentProgress`/简短控制消息显示；实际 Agent ToolResult 仍由控制操作正常回到模型，终端按键不会直接修改主历史。

### Fork 首次请求与缓存前缀

```text
Coordinator
  -> ForkRequestSeed = copy(parent actual ModelRequest metadata)
  -> task tool proxies preserve parent order/name/description/schema/safety
  -> fork execution policy freezes executable subset
  -> TaskManager.start(background) -> immediate task ID

Fork AgentRun first iteration
  -> prompt = seed.request.prompt                  # same object/value
  -> messages = seed.request.messages + user(task)
  -> tools = byte-equivalent task proxy registry  # same serialized schema/order
  -> max_output_tokens = seed.request.max_output_tokens
  -> context capacity preflight in preserve-prefix mode
       -> fits: send without history compaction
       -> does not fit: stop with CONTEXT_CAPACITY before Provider
  -> bind subagent Hook scope with preserve_fork_prefix=True
  -> message.before Hooks run
       -> command/http still execute
       -> prompt actions remain in this task partition for next iteration
  -> RequestBoundaryProvider passes exact seeded request to shared Provider
```

首次 Fork 请求禁止自动历史压缩，因为压缩会改变父消息前缀；无法安全容纳新增任务时明确失败。首次请求期间新匹配的 Hook prompt 延迟到该任务下一次 Provider 请求，避免把系统区插入父消息前缀之前；父请求快照中已经存在的 Hook Context 保持原样。第二次及后续请求恢复任务级 Hook prompt 消费和正常自动压缩。

Provider 序列化测试分别对 Anthropic/OpenAI 适配层比较父请求与 Fork 请求在新增用户任务之前的工具、系统和消息字节。缓存 read/write usage 完全采用 Provider 事件，不由运行时推断。

### 子 Agent 工具、Hook 与权限顺序

```text
child ToolScheduler for each call
  -> registry.validate_call
       unknown/invalid -> tool.after(failure), no before
  -> PermissionController.preflight
       dangerous command/path sandbox hard deny
       -> policy not consulted, no tool.before, tool.after(denied)
  -> FrozenSubagentToolPolicy.evaluate
       deny -> SUBAGENT_POLICY decision
               no tool.before, tool.after(denied), deterministic ToolResult
  -> HookRuntime.dispatch(tool.before) in task scope
       deny -> Hook failure ToolResult -> tool.after
       prompt -> queued only for this task
  -> SubagentPermissionController.evaluate_preflight
       ASK -> SUBAGENT_NON_INTERACTIVE DENY -> tool.after
       DENY -> tool.after
       ALLOW -> execute TaskScopedTool
  -> update FileReadObservationCache when applicable
  -> HookRuntime.dispatch(tool.after)
  -> tool result returns only to child history
```

Fork schema 中的 `agent`/`load_skill` 会在策略层拒绝，因而不会实例化控制操作或占用 TaskManager 容量。策略拒绝和非交互拒绝都作为普通失败工具结果反馈子模型，模型可以在剩余轮次使用允许工具或自然结束。

### 后台终态与通知投递

```text
_drive reaches terminal outcome
  -> truncate result/error to 20,000 chars
  -> [manager lock]
       first terminal wins
       placement == background
       -> NotificationQueue.enqueue_once(task_id)
       -> snapshot.notification_pending = True
  -> publish SubagentTerminalEvent(task_id, status)

REPL monitor
  -> TerminalSession.notify("subagent[short-id]: completed|failed|cancelled")

next root real Provider request
  -> RootAgentRequestBoundary.prepare
  -> NotificationQueue.consume_batch(max 16, max 64 KiB)
  -> append ## Completed Subagent Tasks / untrusted boundary
  -> mark task records delivered
  -> apply retention of oldest delivered terminal records beyond 128
  -> capture request snapshot after notification injection
```

通知消费和快照捕获在同一根请求边界内完成，所以父 Agent 在该请求产生 Fork 时，Fork 会继承父实际看到的已完成任务结果。Provider 尝试开始后即视为通知已投递；请求失败不自动重放，避免同一结果重复注入。队列预算不足时只消费完整条目，不拆分单条，剩余条目保持原顺序。

### 任务命令与单任务取消

```text
/tasks
  -> Conversation.list_subagent_tasks
  -> immutable snapshots -> formatter -> terminal

/task <id>
  -> Conversation.get_subagent_task
  -> active: current bounded progress
  -> terminal: result/error + usage + truncated marker

/task cancel <id>
  -> Conversation.cancel_subagent_task
  -> TaskManager.cancel
       [lock] validate known/nonterminal
       request AgentRun.cancel outside lock
       bounded await cleanup
       terminal commit races under lock
  -> deterministic cancelled/already-terminal/unknown response
```

单任务取消使用与关闭相同的 5 秒收敛上限；超时后取消驱动 task 并 gather，最终状态仍由首终态规则决定。命令执行期间没有模型调用，也不等待其他无关任务。

### `/reset` 与正常关闭

`/reset` 只在主 Conversation 空闲时执行：

```text
Conversation.reset
  -> TaskManager.reset
       set resetting; reject new start
       cancel all active AgentRuns concurrently
       wait <= 5s; force-cancel pending drivers
       suppress terminal notification enqueue during reset
       clear task records + NotificationQueue + Hook task prompt partitions
       clear resetting
  -> await pending Memory update
  -> SessionBinding.reset_state
  -> clear main messages/plan/Skill state/main Context runtime
```

正常关闭顺序为：取消主 Agent/compact → TaskManager.close（取消子运行并关闭事件流）→ 等待 Memory → `session.end` Hook → Session/Skill/main Context → shared HookRuntime。REPL 任务监视器读到任务事件流结束后退出。CLI `finally` 中的资源 close 保持幂等，仅处理 Conversation 构造前失败的部分装配资源。

## 文件组织

```text
MewCode/
├── src/mewcode/
│   ├── subagents/
│   │   ├── __init__.py                 # 功能层公开模型、目录、管理器和 AgentTool 导出
│   │   ├── models.py                   # 角色/任务/通知模型、枚举、限制与异常
│   │   ├── paths.py                    # 四层单文件来源发现与路径安全
│   │   ├── parser.py                   # 严格 YAML frontmatter + Markdown 正文解析
│   │   ├── catalog.py                  # 层级覆盖、无效回退、Profile/工具校验
│   │   ├── policy.py                   # 定义式/Fork 冻结执行策略
│   │   ├── permissions.py              # 无会话授权、ASK 自动拒绝控制器
│   │   ├── scoped_tools.py             # schema 等价工具代理与任务文件读取观察
│   │   ├── notifications.py            # 有界一次性通知队列与系统区渲染
│   │   ├── tasks.py                    # 任务状态机、前后台、取消、保留和事件流
│   │   ├── runtime.py                  # 每任务 Agent/Context/Permission/Hook 运行时工厂
│   │   ├── coordinator.py              # 委派参数、角色/Fork 启动说明构造
│   │   ├── control.py                  # 固定 agent 工具与 AgentControlOperation
│   │   └── builtin/
│   │       └── explore.md               # 内置只读代码库探索角色
│   ├── providers/
│   │   ├── request_boundary.py         # ContextVar 请求边界与透明 Provider 包装
│   │   └── __init__.py                 # 导出请求边界协议
│   ├── agent/
│   │   ├── control.py                  # AgentControlContext + 控制工具新签名
│   │   ├── events.py                   # AgentSubagentProgress
│   │   ├── runner.py                   # 请求槽、seed_request、Profile/loop 上下文
│   │   ├── scheduler.py                # ToolExecutionPolicy 顺序与控制上下文传递
│   │   └── __init__.py                 # 新公共类型导出
│   ├── hooks/
│   │   ├── runtime.py                  # task ID 分区 prompt 队列
│   │   ├── events.py                   # 安全 task/parent 标识字段
│   │   └── provider.py                 # 保持 Hook 在 RequestBoundary 外层
│   ├── prompting/
│   │   ├── models.py                   # PromptAdditions.agent_role
│   │   ├── sections.py                 # 动态 Agent Role section
│   │   ├── builder.py                  # agent_role 渲染与合并
│   │   └── __init__.py                 # 新字段相关导出不变式
│   ├── permissions/
│   │   └── models.py                   # SUBAGENT_POLICY / SUBAGENT_NON_INTERACTIVE 来源
│   ├── context/
│   │   ├── archive.py                  # 子归档可跳过 stale cleanup
│   │   └── manager.py                  # Fork 首轮 preserve-prefix 容量模式
│   ├── skills/
│   │   ├── control.py                  # 接收并忽略 AgentControlContext
│   │   └── runtime.py                  # 根 Skill 视图保留 agent，isolated 不保留
│   ├── commands/
│   │   ├── contracts.py                # 任务查询/取消 Runtime 协议
│   │   └── builtin.py                  # /tasks、/task handlers 与格式化
│   ├── conversation.py                 # TaskManager、通知、reset/close 与命令门面
│   ├── terminal.py                     # Ctrl+B reader 与 prompt-safe notify
│   ├── repl.py                         # 控制键竞速、任务事件监视与渲染
│   └── cli.py                          # 全部组件的启动/失败/关闭装配
├── tests/
│   ├── test_subagent_paths.py          # 根目录、排序、符号链接、候选限制
│   ├── test_subagent_parser.py         # 七字段、UTF-8、大小、正文和边界值
│   ├── test_subagent_catalog.py        # 四层覆盖、回退、冲突、Profile/工具/总量
│   ├── test_subagent_policy.py         # 交集、硬拒绝、Fork schema 不变
│   ├── test_subagent_permissions.py    # 持久规则快照、会话隔离、ASK 拒绝
│   ├── test_subagent_scoped_tools.py   # schema 等价、读取观察与跨任务隔离
│   ├── test_subagent_notifications.py  # 去重、顺序、16/64KiB、信任边界
│   ├── test_subagent_tasks.py          # 8 并发、竞态、转换、取消、保留、关闭
│   ├── test_subagent_runtime.py        # 定义式/Fork 运行时隔离与清理
│   ├── test_subagent_control.py        # 固定 schema、参数组合、前后台 ToolResult
│   ├── test_subagent_integration.py    # CLI 级装配和三条端到端场景
│   └── test_request_boundary.py        # ContextVar 隔离、透明转发和转换顺序
├── examples/
│   └── agents/
│       └── code-reviewer.md            # 用户可复制的角色定义示例
├── docs/phase-12-subagent-system/
│   ├── spec.md
│   ├── plan.md
│   ├── task.md
│   └── checklist.md
└── README.md                            # 角色格式、Agent 工具、任务命令与边界
```

### 新建文件

| 文件 | 职责 |
|---|---|
| `src/mewcode/subagents/__init__.py` | 提供功能层稳定导出，避免应用层依赖内部文件布局。 |
| `src/mewcode/subagents/models.py` | 集中所有限制和不可变数据模型，保证默认值单一来源。 |
| `src/mewcode/subagents/paths.py` | 实现项目/用户/内置/插件角色来源发现。 |
| `src/mewcode/subagents/parser.py` | 解析严格 Markdown 角色定义。 |
| `src/mewcode/subagents/catalog.py` | 编译不可变角色目录并生成诊断。 |
| `src/mewcode/subagents/policy.py` | 实现定义式裁剪与 Fork schema/执行能力分离。 |
| `src/mewcode/subagents/permissions.py` | 构造每任务非交互权限控制器。 |
| `src/mewcode/subagents/scoped_tools.py` | 创建任务工具代理和独立文件读取观察。 |
| `src/mewcode/subagents/notifications.py` | 实现一次性通知、预算和不可信系统区。 |
| `src/mewcode/subagents/tasks.py` | 实现任务管理器及并发状态机。 |
| `src/mewcode/subagents/runtime.py` | 组装并清理单个隔离子 Agent 运行时。 |
| `src/mewcode/subagents/coordinator.py` | 把工具调用上下文编译成冻结启动说明。 |
| `src/mewcode/subagents/control.py` | 暴露唯一 `agent` 控制工具。 |
| `src/mewcode/subagents/builtin/explore.md` | 提供默认只读探索角色，使用 `read_file/find_files/search_code`。 |
| `src/mewcode/providers/request_boundary.py` | 在不耦合任务模块的前提下支持最终请求转换/观察。 |
| `examples/agents/code-reviewer.md` | 展示全部七个 frontmatter 字段和只读角色正文。 |
| 11 个 `tests/test_subagent_*.py` | 分层覆盖新子系统并集中三条 E2E。 |
| `tests/test_request_boundary.py` | 验证通用 Provider 边界不依赖任务模块且并发隔离。 |

### 修改文件

| 文件 | 修改内容 |
|---|---|
| `src/mewcode/agent/control.py` | 增加控制上下文并更新协议。 |
| `src/mewcode/agent/events.py` | 增加安全的子任务进度事件。 |
| `src/mewcode/agent/runner.py` | 支持实际请求捕获、Fork seed、loop limit 和策略上下文。 |
| `src/mewcode/agent/scheduler.py` | 插入冻结执行策略并向控制工具传上下文。 |
| `src/mewcode/agent/__init__.py` | 导出新增通用类型。 |
| `src/mewcode/providers/__init__.py` | 导出请求边界类型。 |
| `src/mewcode/hooks/runtime.py` | 保留全局队列并增加 task prompt 分区和清理。 |
| `src/mewcode/hooks/events.py` | 允许有界 task ID/parent run ID 事件字段。 |
| `src/mewcode/hooks/provider.py` | 固定 HookedProvider 与内层 RequestBoundaryProvider 的调用契约。 |
| `src/mewcode/prompting/models.py` | 增加和合并 `agent_role`。 |
| `src/mewcode/prompting/sections.py` | 注册动态 Agent Role 区段。 |
| `src/mewcode/prompting/builder.py` | 渲染角色区段且不改变稳定前缀。 |
| `src/mewcode/permissions/models.py` | 增加两个明确拒绝来源。 |
| `src/mewcode/context/archive.py` | 为任务归档提供不执行全局清理的启动选项。 |
| `src/mewcode/context/manager.py` | 增加只检查容量、不压缩首个 Fork 请求的模式。 |
| `src/mewcode/skills/control.py` | 适配通用控制工具新签名。 |
| `src/mewcode/skills/runtime.py` | 只在根运行视图中保留 `agent`。 |
| `src/mewcode/commands/contracts.py` | 扩展任务管理协议。 |
| `src/mewcode/commands/builtin.py` | 注册和格式化 `/tasks`、`/task`。 |
| `src/mewcode/conversation.py` | 注入 TaskManager、根通知、任务门面和清理顺序。 |
| `src/mewcode/terminal.py` | 实现运行控制键和异步安全通知。 |
| `src/mewcode/repl.py` | 并行消费 Agent/控制键/任务终态事件。 |
| `src/mewcode/cli.py` | 增加 Provider 边界、角色、任务、AgentTool 和错误装配。 |
| `README.md` | 记录定义格式、来源优先级、权限、缓存、命令、限制和非目标。 |

### 扩展现有测试

| 文件 | 新增回归点 |
|---|---|
| `tests/test_agent_runner.py` | 控制上下文取实际请求、seed 首轮、空快照失败、loop limit。 |
| `tests/test_tool_scheduler.py` | hard safety → policy → Hook → permission 顺序及控制上下文。 |
| `tests/test_hook_runtime.py` | 全局 prompt 兼容、task 分区、总预算、清理。 |
| `tests/test_hook_provider.py` | Hook 注入发生在 RequestBoundary 之前。 |
| `tests/test_prompt_builder.py` | Agent Role 为动态区且稳定前缀不变。 |
| `tests/test_context_manager.py` | preserve-prefix 容量通过/失败且不调用 compactor。 |
| `tests/test_skill_runtime.py` | 根视图保留 agent、isolated 视图不泄漏。 |
| `tests/test_builtin_commands.py` | 新命令解析、usage、格式化和错误。 |
| `tests/test_conversation.py` | task 门面、reset/close 顺序和幂等。 |
| `tests/test_repl.py` | Ctrl+B、权限输入互斥、后台摘要和监视器关闭。 |
| `tests/test_terminal.py` | prompt-toolkit Ctrl+B reader、取消和 prompt-safe notify。 |

`pyproject.toml` 不增加第三方依赖；现有 PyYAML、prompt-toolkit 和 asyncio 能覆盖全部实现。包内 Markdown 沿用现有 built-in Skill 的打包方式进入 wheel/sdist。

## 技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 与 Skill 的关系 | 新建独立 `subagents` 功能层，复用通用 Agent Loop | 保持 phase-10 已验收语义，避免把后台状态强塞进 Skill 激活模型。 |
| 委派工具 | 单个固定 `agent` 控制工具，类型参数分流 | 角色和任务变化不会改变 schema；主缓存前缀稳定。 |
| 角色模型字段 | `inherit` 或现有 Profile 名 | 直接复用多 Provider、凭据、上下文窗口和 usage 装配，不引入 Claude 专属别名。 |
| 角色正文存储 | 启动时完整读入不可变目录 | 文件总量已受 1 MiB 限制；避免运行中 TOCTOU 与热更新语义。 |
| 插件来源 | 调用方注入目录，不发现插件 | 满足最低优先级来源契约而不实现插件系统。 |
| 父请求捕获 | Hook 注入后的 Provider 内边界 | Fork 得到父实际看到的 Prompt/消息/schema，而不是 Runner 近似候选。 |
| Fork 首轮构造 | 父请求种子 + 新用户消息 | 旧请求完整成为前缀，产生 Agent 调用的助手消息不会形成未配对工具链。 |
| Fork 工具安全 | schema 保持，执行策略硬拒绝 | 同时满足完整工具缓存前缀和不可嵌套/后台限制。 |
| 首轮容量不足 | 失败，不压缩 | 压缩会破坏明确承诺的父消息前缀；容量失败已有标准终态。 |
| 首轮新 Hook prompt | 延迟到 Fork 后续请求 | command/HTTP 仍执行，同时避免系统提示插入父消息前缀之前。 |
| 执行策略位置 | 硬 preflight 后、Hook 前 | 危险命令/路径继续最先拒绝；后台越界参数不泄漏给外部 Hook。 |
| 权限 ASK | 任务控制器同步改写为 DENY | 子 Agent 跑到底且不占用 REPL 权限输入。 |
| 权限继承 | 复制持久三层，清空 session | 保留用户/项目政策，不泄漏父临时批准。 |
| 运行状态 | 每任务独立 Runner/Scheduler/Context/Archive/Permission/cache | 隔离消息、轮次、权限、压缩和读观察；组件生命周期清晰。 |
| Provider/Hook/Workspace | 并发安全基础设施共享 | 复用连接、usage、自动化与真实文件系统，符合非 Worktree 边界。 |
| Hook prompt 隔离 | 非子任务保留全局队列，子任务按 ID 分区 | 新任务不串线，同时不破坏既有 memory/compact 的下一请求语义。 |
| 文件读取缓存 | 记录观察，不缓存返回内容 | 可追踪任务隔离，又不会向并发任务返回其他任务写入前的旧内容。 |
| 后台工具名单 | 冻结 `base_registry.names` | 内置/MCP 都能后台执行；控制工具与 Skill 包工具不会自动扩大能力。 |
| 前后台转换 | 同一驱动 task 上解除前台订阅 | 无重启、无消息迁移、无 usage 重算，竞态只需一个管理锁。 |
| 任务并发 | 单管理器、8 个活动 task、锁内原子注册 | 防止并发超额，状态归属唯一；Agent Run 耗时工作保持锁外。 |
| 完成通知 | 进程内一次性动态系统区 | 主 Agent 能收到完整有界结果，不污染或持久化主历史。 |
| 通知失败重放 | Provider 尝试开始即 delivered，不自动重放 | 保证最多注入一次，避免模型重复处理同一完成结果。 |
| 任务查询 | 本地 `/tasks`、`/task` | 用户可观察/取消，不增加模型轮询工具。 |
| 手动转后台 | 运行期 `Ctrl+B` reader | 不复用 Ctrl+C，不要求 REPL 在 Agent 运行时开放完整命令输入。 |
| 根 Skill 视图 | 根运行始终保留 `agent`，isolated Skill 不保留 | 满足主 Agent 稳定委派入口，同时避免另一种模型子运行再做父级委派。 |
| 任务 ID 与保留 | UUID4；通知后最多保留 128 条终态 | 不可简单猜测且进程内内存有界。 |
| 内置角色 | 只提供 `explore` | 给出可直接使用的安全定义式角色，不扩大到角色市场或团队配置。 |

## 实施约束

- `mewcode.agent`、`providers`、`hooks`、`permissions`、`tools` 等通用层不得导入 `mewcode.subagents`；功能层通过 Protocol、ContextVar 和通用 dataclass 接入。
- `agent` 工具 schema 必须定义为模块级不可变常量，不读取角色目录或任务管理器；Anthropic/OpenAI 工具序列化快照测试必须逐字节比较。
- Fork 的 task tool proxy 必须逐项保持父 ToolRegistry 顺序及 `name/description/parameters_schema/safety/permission_spec` 值，不得排序、深拷贝后改写或增加提示性字段。
- AgentRun 只能把本 iteration 的捕获槽传给同一响应工具批次；开始下一 iteration 前必须创建新槽并丢弃旧引用。
- 请求边界使用 ContextVar token 成对 bind/reset。后台 `asyncio.create_task` 继承父 context 后，子运行必须立即覆盖 task scope，任务完成后不得留下可消费回调。
- Hook prompt 总预算计算必须覆盖全局与所有 task 分区；队列修改继续在 HookRuntime 的现有调度锁内完成。
- TaskManager 不得在持有状态锁时等待 Provider、AgentRun、工具、Hook、终端或取消清理；锁内只做状态检查、不可变快照替换、队列登记和引用交换。
- 完成、取消、detach、reset 和 close 的所有回调都必须通过同一个终态提交函数；禁止从 done callback 直接改写公开记录。
- 任务通知和终端事件必须在终态提交后生成，内容只来源于已截断快照；不得携带 ChatMessage、ToolExecution、异常对象或 Provider 内部 part。
- `/reset` 和 close 的 5 秒预算使用可注入单调时钟/等待器；测试禁止真实 sleep 10 秒或依赖调度碰运气。
- 子 ContextArchive 的目录 ID 由 task ID 派生但仍经过现有工作区根约束；子启动不执行 stale cleanup，主 ContextArchive 启动继续负责进程级遗留清理。
- 定义式 PromptAdditions 必须重新构造并显式清空 Skill 字段；不得复用父 `run_view_provider` 或父临时 Hook prompt。
- Fork 首次 preserve-prefix 检查只允许 TokenEstimator/容量判断，不得调用 HistoryCompactor；失败不得悄然降级为非缓存请求。
- 策略拒绝必须在 `tool.before` 之前，仍触发一次有界 `tool.after(denied)`；硬安全拒绝继续优先于策略，Hook allow 不能覆盖任何拒绝。
- SubagentPermissionController 不暴露 `PermissionChallenge`，不调用 RuleStore 写方法；所有 ASK 拒绝必须保留原 match 供诊断但使用新的来源和原因。
- 任务级 usage 使用 AgentRunOutcome；进程 usage 继续只由共享 UsageTrackingProvider 记录，TaskManager 不再向 UsageLedger 写入。
- PromptToolkit 输入在任一时刻只允许一个消费者。权限 PromptSession 启动前必须取消并 await 运行控制 reader，主 prompt 启动前任务控制 reader必须已结束。
- 终端通知使用 prompt-toolkit 安全输出，不从 TaskManager done callback 直接写 stdout；LegacyTerminal 兼容路径保持同步最小实现。
- 新错误在子系统边界转成 AgentDefinitionError、AgentCatalogError、ToolResult、TaskCancelResult、ConversationError 或安全诊断；普通异常不能逃逸 REPL 主循环。
- 现有用户会话、权限文件、记忆、上下文档案、Skill 激活状态以及工作区内无关改动不属于迁移或清理范围。

## Spec 覆盖映射

| Spec | 设计归属 |
|---|---|
| F1–F4 | 固定 `AgentTool` schema、`SubagentCoordinator` 条件校验、本地任务命令分离。 |
| F5–F6 | `AgentControlContext.allowed_safety`、定义式 schema 裁剪、Fork policy、根/isolated Skill 视图。 |
| F7–F11 | `subagents.paths/parser/models` 严格单文件格式、Profile、轮次、角色动态区。 |
| F12–F16 | 四层 `catalog`、注入插件根、无效回退、同层冲突、工具校验和启动快照。 |
| F17 | 定义式空历史、基础 additions supplier、`agent_role`、显式清空 Skill/Hook 临时状态。 |
| F18–F19 | Hook 后 RequestBoundary、ForkRequestSeed、字节等价 schema、冻结执行 policy。 |
| F20–F22 | Task runtime 独立 Runner/Scheduler/Permission/Context/Archive/cache，无 history sink。 |
| F23–F24 | 角色/父 loop limit、DIRECT 跑到底、AgentRun 标准终态与最后工具批次保护。 |
| F25 | 持久规则快照、空 session、SubagentPermissionController ASK 自动拒绝。 |
| F26 | Hook task scope、分区 prompt、task/parent 安全事件字段与清理。 |
| F27 | AgentRunOutcome task usage + 共享 UsageTrackingProvider 进程账本。 |
| F28–F33 | DelegationOperation、TaskHandle 前台订阅、10 秒 timer、Ctrl+B、冻结后台名单。 |
| F34 | `SubagentTaskSnapshot` 与 TaskManager 单一状态所有权。 |
| F35–F37 | CommandRuntime 任务门面、`/tasks`、`/task` 和有界 cancel。 |
| F38–F40 | Terminal event、NotificationQueue、根请求注入、批次预算、delivered/retention。 |
| F41 | Conversation reset/close 顺序、TaskManager 有界清理、纯进程内状态。 |
| F42 | TaskManager 锁内 8 活动容量检查。 |
| N1–N3 | 模块级固定 schema、RequestBoundary/Fork seed、动态 Agent Role/通知区。 |
| N4–N6 | 8 任务原子注册、单调计时、锁外运行、Provider/Hook 单任务失败收敛。 |
| N7–N12 | models 限制、parser/catalog、结果截断、通知批次、128 保留、5 秒关闭和安全诊断。 |
| N13–N18 | policy 硬上限、启动冻结、共享 Workspace、UUID、untrusted 边界、Hook scope 顺序。 |
| N19–N20 | 单终态提交函数、通知去重、取消/完成/detach 竞态锁。 |
| N21 | 通用层默认参数、非任务快速路径、Skill/Hook/Context 回归与无额外请求。 |
| N22 | TaskManager/NotificationQueue 纯内存，Conversation/Session 不持久化。 |
| N23 | 注入时钟、Provider、Hook、权限、工具、终端与不依赖真实等待的测试。 |
| N24 | 分层异常类型、最外层收敛、安全稳定输出。 |

## 验证策略

1. 先运行角色目录、policy、权限、通知和任务状态机的纯单元测试，所有时间与并发边界使用 fake clock/event。
2. 再运行 Provider boundary、AgentRunner、ToolScheduler、Hook、Context、Prompt、Skill、Command、Terminal、Conversation 的定向回归。
3. 使用 fake Anthropic/OpenAI Provider 序列化父请求与 Fork 首次请求，逐字节验证新增用户任务之前的缓存前缀。
4. 运行三条端到端场景：10 秒内定义式完成、定义式转后台后异步通知、Fork 立即后台并命中可缓存前缀。
5. 运行完整 `pytest`，确认普通对话、PLAN、Skill、MCP、权限、Hook、上下文、记忆与命令系统无回归。
