# Phase 14B 隔离成员后端 Plan

## 架构概览

Phase 14B 采用“Lead 控制面 + 窗格宿主 + 成员工作进程”三层架构：

```text
邮箱 / 任务
   ↓
现有 Lead 调度器（状态、容量、租约的唯一所有者）
   ↓
后端路由
   ├─ 进程内：沿用 14A 运行时
   └─ 终端：窗格适配器 → 窗格宿主 → 独立成员 MewCode 工作进程
```

- Lead 调度器仍是成员状态转换、队列合并、容量名额和最终结果提交的唯一所有者。终端成员运行期间，容量租约由 Lead 持有；空闲窗格宿主不占用名额。
- 每个终端窗格运行一个轻量宿主。宿主保持窗格存活、与当前 Lead 建立本地受控连接，并在收到运行请求时启动一次完整的成员工作进程；工作进程自然结束后，宿主保留并等待下一次请求。
- 工作进程复用 14A 的 Worktree、会话、成员工具、审批和入站邮箱能力，只额外向宿主报告进度与最终结果。它不成为 Lead，也不获得人工 REPL。
- Lead 重启或异常退出时，宿主连接失效会终止在途工作进程；新 Lead 挂载后建立新的本地控制端点，原宿主重新登记。无可用宿主时，下次唤醒创建替代窗格。
- 后端路由把 `auto` 仅解析一次并持久化实际后端；显式后端不经路由降级。既有 `in_process` 成员仍使用原运行时。
- Windows Terminal 适配器使用 `wt` 的既有窗口与 `split-pane` 能力；tmux 适配器使用当前会话中的可寻址窗格。两者都只启动固定的 MewCode 宿主命令，不通过 shell 拼接用户内容。

## 核心数据结构

### 后端选择

持久化枚举 `TeamMemberBackend` 扩展为：

```text
in_process | windows_terminal | tmux
```

请求值使用独立的 `MemberBackendRequest`：

```text
auto | in_process | windows_terminal | tmux
```

`auto` 只作为创建时输入，永不写入成员记录。`MemberBackendResolver` 接收请求、平台、进程环境和可替换探测器，返回已解析的 `TeamMemberBackend` 或稳定的后端不可用诊断：

```python
class MemberBackendResolver:
    def resolve(self, requested: MemberBackendRequest) -> TeamMemberBackend: ...
```

Windows 的自动顺序为 `windows_terminal → in_process`；macOS 与 Linux 为 `tmux → in_process`。显式请求仅验证指定后端。

### 窗格绑定和成员视图

`TeamMemberRecord` 增加可选的、严格版本化的终端绑定字段：

```python
@dataclass(frozen=True)
class TerminalPaneBinding:
    schema_version: int
    backend: TeamMemberBackend
    host_id: str
    backend_handle: str | None
    created_at: datetime
    last_connected_at: datetime | None
    last_error: str | None
```

- `backend_handle` 只保存受校验的适配器句柄，例如 tmux pane ID；Windows Terminal 以 `host_id` 登记为准，不用标题或焦点猜测窗格身份。
- `last_error` 一律经过既有有界诊断清理。
- 14A 成员缺失绑定字段时使用 dataclass 默认值并保持 `in_process`；新记录由旧版本读取时会因未知字段明确拒绝，旧版本不能覆盖新格式。

只读 `TeamMemberRuntimeView` 合并持久成员、终端绑定和本地控制面当前健康状态：

```python
class PaneHealth(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    CONNECTED = "connected"
    MISSING = "missing"
    UNAVAILABLE = "unavailable"

@dataclass(frozen=True)
class TeamMemberRuntimeView:
    member: TeamMemberRecord
    pane_health: PaneHealth
    diagnostic: str | None
```

成员列表使用该视图；成员身份、状态机与动态工具 schema 不变。

### 终端适配器

```python
class TerminalPaneAdapter(Protocol):
    backend: TeamMemberBackend

    def probe(self) -> BackendCapability: ...
    async def create_host(self, launch: PaneHostLaunch) -> PendingPane: ...
    async def terminate_unpublished(self, pane: PendingPane) -> None: ...
```

`WindowsTerminalPaneAdapter` 和 `TmuxPaneAdapter` 分别实现该协议。它们只构造固定可执行文件及 argv；成员名称、任务正文、邮件正文、路径或密钥不进入 shell 片段。适配器命令成功后仍须等待宿主登记，登记才是窗格可用的证据。

### 本地控制面与跨进程运行时

活动 Lead 创建 `MemberControlBroker`。它开放同机本地端点，维护当前控制代际并验证宿主身份：

```python
class MemberControlBroker:
    async def open(self, attachment: TeamAttachment) -> None: ...
    async def authorize_pending(self, launch: PaneHostLaunch) -> None: ...
    async def ensure_host(self, member: TeamMemberRecord) -> PaneHostConnection: ...
    async def close(self) -> None: ...
```

控制消息带有团队 ID、成员 ID、宿主 ID、Lead 控制代际、运行 ID 和成员运行代际。任何字段不匹配的登记、心跳、进度或结果均被拒绝。

`TerminalMemberRuntime` 与现有调度器使用相同的事件、取消、结果和关闭契约：

```python
class TerminalMemberRuntime:
    async def events(self) -> AsyncIterator[TeamMemberProgress]: ...
    @property
    def outcome(self) -> TeamMemberOutcome: ...
    async def cancel(self, *, explicit_stop: bool = False) -> None: ...
    async def close(self) -> None: ...
```

它在 Lead 侧持有既有 `AgentCapacityLease`，直到工作进程产生可验证的终态结果后才释放。

### 宿主和成员工作模式

- 隐藏宿主模式保持窗格存活，读取受限本地控制描述，登记到 `MemberControlBroker`，启动或终止固定的成员工作进程，并转发安全摘要。
- 隐藏成员工作模式从当前团队状态验证运行身份，然后复用 `TeamMemberRuntimeFactory` 的 Worktree、会话、Prompt、成员工具、审批、权限和入站邮箱组装逻辑。
- 工作进程完成后写入版本化、原子替换的单次结果记录，并由宿主转发给 Lead；它不直接修改团队成员状态。
- 运行描述、控制描述和结果记录均位于团队成员目录中，使用经校验的路径和本地受限控制凭据，凭据不出现在命令行、窗格标题、邮箱或用户可见诊断中。

## 模块设计

### `teams.backends`

**职责：** 定义后端请求、能力结果、平台优先级与诊断。

**对外接口：** `MemberBackendResolver`、`BackendCapability`、`MemberBackendRequest`。

**依赖：** `teams.models`，可替换的平台/环境/命令探测接口。

### `teams.panes`

**职责：** 定义终端适配器协议并实现 Windows Terminal 与 tmux 的创建、预检和未发布资源清理。

**对外接口：** `TerminalPaneAdapter`、`WindowsTerminalPaneAdapter`、`TmuxPaneAdapter`、`PaneHostLaunch`。

**依赖：** `teams.backends`、可替换的进程执行器与环境探测。

### `teams.control`

**职责：** 提供活动 Lead 的本地控制 broker、宿主登记、控制代际校验、运行/取消请求和结果/心跳传输。

**对外接口：** `MemberControlBroker`、`PaneHostConnection`、严格的控制消息 union。

**依赖：** `teams.models`、`teams.paths`、可替换的本地端点和时钟。

### `teams.pane_host`

**职责：** 在终端窗格中执行隐藏宿主模式、重建与 Lead 的连接、管理单个工作进程并转发其安全结果。

**对外接口：** `run_pane_host()`。

**依赖：** `teams.control`、`teams.member_worker`、可替换的子进程与等待接口。

### `teams.member_worker`

**职责：** 在独立 MewCode 进程中执行一个已验证的成员运行，并原子落盘其结果。

**对外接口：** `run_member_worker()`、`MemberRunDescriptorStore`。

**依赖：** 14A 的运行时、会话、Worktree、审批、工具和入站模块。

### 14A 模块调整

| 模块 | 调整 |
|---|---|
| `teams.models`、`codec`、`paths` | 后端枚举、窗格绑定/视图/唤醒回执、严格版本化记录和受控路径。 |
| `teams.roster` | 解析默认 `auto`，执行终端预检与 journal 化窗格宿主 provisioning，并在列表返回运行视图。 |
| `teams.runtime` | 抽取可在成员工作模式复用的执行组装，使进程内和独立进程共享 Worktree/会话/工具语义。 |
| `teams.scheduler` | 依据实际后端选择进程内或终端运行时，合并启动回执、取消、容量和陈旧结果。 |
| `teams.mailbox` | 将持久投递与唤醒结果分离，保留 outbox 去重，并公开结构化唤醒回执。 |
| `teams.coordinator` | 生命周期内打开/关闭 broker；附加时处理宿主重新登记与 14A 中断收敛。 |
| `teams.tools` | `backend` 从新增成员动作的必填字段变为可选，默认 `auto`；成员列表编码运行视图。 |
| `teams.__init__`、`cli` | 导出新组件，装配适配器/broker，注册隐藏宿主和成员工作模式。 |

## 模块交互

### 1. 创建成员

1. 成员工具允许省略 `backend`，花名册服务将其解释为 `auto`。
2. 花名册服务解析冻结角色并调用后端 resolver；显式后端失败立即返回诊断，自动后端只按已定义顺序继续尝试。
3. 对终端后端，服务先向 broker 授权候选宿主，再以 provisioning journal 创建 Worktree、会话、邮箱和窗格宿主。
4. 适配器启动宿主，broker 验证宿主登记及实际后端；任一步失败都清理未发布资源并请求宿主退出。
5. 只有全部资源已验证后，服务通过既有 CAS 一次提交发布成员、窗格绑定和名称注册。

### 2. 邮件、任务与可靠唤醒

1. 邮箱 outbox 先按 14A 规则持久化并去重消息，再单独触发成员唤醒；唤醒失败不回滚或重复已投递消息。
2. 唤醒返回 `running`、`queued`、`failed` 或 `not_applicable` 的结构化回执及有界诊断。
3. 容量不足时保留原有持久 FIFO；后端不可用时调度器将对应成员收敛为 FAILED。
4. 邮件与任务调用结果明确区分“已投递”和“已启动”，满足已持久化但终端无法唤醒时的可观察错误语义。

### 3. 运行、空闲与重复事件

1. 调度器先获取容量、提交 RUNNING 与运行代际，再创建进程内或终端运行时。
2. 终端运行时确保宿主可用，必要时重建消失窗格；随后把运行请求交给宿主。
3. 宿主启动一次成员工作进程，工作进程以 14A 语义写入会话、轮询邮箱并完成 Agent 运行。
4. 宿主只转发控制代际、运行 ID 和成员代际均匹配的进度和结果。调度器最终提交 IDLE、AWAITING_APPROVAL、STOPPED、INTERRUPTED 或 FAILED，并释放容量。
5. 宿主留在原窗格等待下一次请求。重复邮件、任务指派、恢复、容量释放、重连和陈旧结果均通过现有队列、运行代际和控制代际合并或拒绝。

### 4. 故障、重启、停止和移除

1. 空闲窗格断开时仅记录 `MISSING`；下一次唤醒通过适配器创建替代窗格。
2. 运行中窗格断开、成员工作进程异常或控制失败会形成 FAILED 结果；系统不自动重放步骤。
3. Lead 正常关闭向宿主取消在途运行；Lead 崩溃导致控制面断开时，宿主终止在途工作。新 Lead 挂载保留 14A 的 RUNNING → INTERRUPTED 收敛，不自动恢复。
4. 停止调用终端运行时取消；移除在注销成员后回收窗格宿主并复用既有 Worktree 成果保护和 journal 清理语义。

## 文件组织

| 操作 | 文件 | 职责 |
|---|---|---|
| 新建 | `src/mewcode/teams/backends.py` | 后端请求解析、能力探测、稳定诊断和实际后端选择。 |
| 新建 | `src/mewcode/teams/panes.py` | 窗格适配器协议、Windows Terminal/tmux 实现、宿主创建和验证。 |
| 新建 | `src/mewcode/teams/control.py` | Lead 本地控制 broker、宿主登记、认证、运行/取消/结果协议。 |
| 新建 | `src/mewcode/teams/member_worker.py` | 受管理成员工作模式与严格运行结果报告。 |
| 新建 | `src/mewcode/teams/pane_host.py` | 保留窗格的宿主模式、连接重建与子工作进程管理。 |
| 修改 | `src/mewcode/teams/models.py` | 后端枚举、窗格绑定、回执和运行视图。 |
| 修改 | `src/mewcode/teams/codec.py` | 新模型及控制/结果持久记录的严格编解码。 |
| 修改 | `src/mewcode/teams/paths.py` | 窗格绑定、控制描述与运行结果的受控路径。 |
| 修改 | `src/mewcode/teams/roster.py` | 后端解析、宿主 provisioning、列表运行视图与移除清理。 |
| 修改 | `src/mewcode/teams/runtime.py` | 抽取可复用成员执行组装。 |
| 修改 | `src/mewcode/teams/scheduler.py` | 运行时路由、唤醒回执、取消和陈旧结果收敛。 |
| 修改 | `src/mewcode/teams/mailbox.py` | 持久投递与唤醒结果分离。 |
| 修改 | `src/mewcode/teams/coordinator.py` | broker 生命周期和重启恢复。 |
| 修改 | `src/mewcode/teams/tools.py` | 默认 `auto` 与成员列表视图编码。 |
| 修改 | `src/mewcode/teams/__init__.py`、`src/mewcode/cli.py` | 导出新组件、依赖装配和隐藏宿主/成员工作入口。 |
| 新建/修改 | `tests/teams/test_backends.py`、`test_panes.py`、`test_control.py`、`test_member_worker.py` 及现有团队测试 | 单元、集成、故障、并发、重启和端到端覆盖。 |

## 技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 后端持久化 | 只保存实际后端 | `auto` 是创建策略而不是长期身份，避免重启后静默漂移。 |
| 格式兼容 | 可选版本化窗格绑定 | 14A 进程内成员无需迁移；旧程序遇到新字段明确拒绝写入。 |
| 窗格身份 | 宿主登记身份为准 | 终端标题、焦点和布局均不是可靠的成员身份。 |
| 跨进程控制 | 本机受控连接 + 代际/运行 ID | 可在重启、重连和陈旧事件间阻止双运行。 |
| 容量 | Lead 调度器持有既有租约 | 独立成员工作进程不会绕开与普通子 Agent共享的 14A 容量边界。 |
| 状态提交 | 仅 Lead 调度器写团队状态 | 复用 CAS、fence、通知和状态机，避免跨进程双事实来源。 |
| 邮箱语义 | 投递和启动分开报告 | 已投递后端不可用时不丢信，也不将其伪报为已运行。 |
| 终端安全 | 固定 argv，拒绝 shell 拼接 | 防止成员名、任务或消息成为命令注入途径。 |
| 崩溃处理 | 控制面失联终止工作，重启标中断 | 保持 14A 的保守不重放保证。 |

## 风险与处理

- Windows Terminal 不提供足以作为成员身份的稳定窗格标识时，以宿主成功登记证明绑定；登记超时或断开即诊断失败，绝不猜测成功。
- 宿主可能跨 Lead 重启继续存活，控制代际和宿主身份拒绝旧连接、旧结果和重复唤醒。
- 窗格创建是外部资源，复用 provisioning journal 保证失败资源可清理且未发布成员不可投递。
- 时钟、时限、连接重试、终端命令、子进程和环境均可替换；测试不依赖真实睡眠保证顺序。
- 不采用常驻模型成员等待邮件的方案，以避免长期占用容量；不采用每次邮件新建无状态窗格的方案，以保留窗格复用和重启关联。

## 验证策略

- 单元：后端解析、宿主环境探测、严格持久编解码、控制消息验证、代际与重复事件拒绝。
- 集成：邮箱/outbox 到唤醒回执、容量 FIFO、停止/移除、角色与审批、旧成员兼容。
- 崩溃恢复：窗格创建、工作中、结果写入和 Lead 断线的每个边界。
- 并发：重复邮件、并行恢复、窗格重连、过期结果、容量释放与停止竞争。
- 端到端：Windows Terminal fake、tmux fake、进程内回归，以及真实可选终端环境的受控冒烟。
- 最终：专项测试、受影响回归、完整 `pytest`，并在 checklist 中逐项附实际证据后勾选。

## 外部接口依据

- Windows Terminal：[`wt` command-line arguments](https://learn.microsoft.com/en-us/windows/terminal/command-line-arguments) 支持使用 `--window` 对既有终端窗口执行命令，且 `split-pane` 可启动指定命令。
- tmux：[Advanced Use](https://github.com/tmux/tmux/wiki/Advanced-Use) 说明了可寻址 pane 与控制命令的使用方式。
