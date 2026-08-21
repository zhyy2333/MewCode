# Phase 14C Team Lead 编排、受控 Git 集成与 Coordinator 双开关 Plan

## 架构概览

Phase 14C 采用“现有团队生命周期 + 可选交付协调层 + 受控 Git 驱动”的分层设计，不修改 Phase 14A/14B 的 `TeamState` 格式：

```text
配置 teams.coordinator.enabled ─┐
                               ├─ 能力解析器 ── 两者均开启？
环境 MEWCODE_ENABLE_TEAM_COORDINATOR ┘             │
                                                    ├─ 否：14A/14B 原路径，零 14C 写入
                                                    └─ 是
                                                       ↓
用户目标 → Team Lead → 交付协调服务 → 共享任务 / 审批 / 邮箱 / 调度器
                              │                  ↓
                              │             长期成员固定 Worktree
                              ↓                  ↓
                    严格状态仓库 / journal ← 成果检查
                              │
                              ↓
                    稳定拓扑集成计划
                              │
                              ↓
                    受控 Git 驱动 → 本地目标分支
```

- 既有 `TeamCoordinator` 继续负责团队挂载、Lead 租约、14A/14B 中断收敛、成员服务和控制 broker；避免改变已经验收的生命周期语义。
- 新增 `TeamDeliveryCoordinator`，仅在双开关均开启且团队已挂载时构造。它负责拆解事务、资格判定、派发决定、人工决策、成果审阅、集成计划、恢复和审计。
- 新增独立 `CoordinatorRepository`。Phase 14C 文件位于团队目录的专用子树，使用各自版本、修订、文件锁和原子替换；旧 `state.json` 不增加字段，缺少专用子树即表示从未启用。
- Git 只通过 `CoordinatorGitBackend` 的固定方法执行。Lead 不获得任意命令字符串；用户可见的“受限 shell”表现为结构化 `team_git` 工具，只接受检查、计划、集成、恢复等动作与已登记 ID。
- Coordinator 生效且当前会话确实挂载为 Team Lead 时，运行视图只保留基础只读工具和团队专用工具，移除所有通用副作用工具，再显式加入 coordinator 工具。未挂载会话、成员进程和普通子 Agent 使用原工具视图。
- v1 安全策略拒绝所有 Git 冲突自动解析、拒绝目标分支漂移、要求目标工作区和成员 Worktree 都干净。后续版本可新增明确的可验证策略，但不能在 v1 记录上静默采用。

## 核心数据结构

Phase 14C 使用独立 `COORDINATOR_SCHEMA_VERSION = 1` 和 `COORDINATOR_POLICY_VERSION = 1`。所有记录为冻结数据结构并在构造时校验；OID 必须是完整 40/64 位十六进制，分支必须是安全的 `refs/heads/...`，时间必须带 UTC 时区。

### `CoordinatorSettings`

```python
@dataclass(frozen=True)
class CoordinatorSettings:
    schema_version: int
    configuration_enabled: bool
    environment_enabled: bool
    enabled: bool
    safety_policy_version: int
    terminal_backends_verified: bool
    resolved_at: datetime
```

- `enabled` 必须严格等于两个开关的逻辑与。
- 配置只接受 YAML 布尔值 `teams.coordinator.enabled`；缺失为 `False`。
- 环境变量只把精确值 `1` 解释为开启；缺失、空值和 `0` 为关闭，其它值返回有界配置诊断并保持关闭。
- 不保存原始环境变量内容。只有 `enabled=True` 时才把设置快照写入团队目录；已存在快照的策略版本不匹配时拒绝启动协调服务。
- `terminal_backends_verified` 由可注入的构建能力提供者给出。本仓库的 Phase 14B 验收标志为真；测试可替换为假以覆盖仅进程内边界。

### 拆解任务与派发决定

```python
class DeliveryKind(StrEnum):
    GIT = "git"
    NO_GIT = "no_git"

@dataclass(frozen=True)
class CoordinatorTaskSpec:
    local_id: str
    task_id: str
    ordinal: int
    title: str
    description: str
    dependency_local_ids: tuple[str, ...]
    dependency_task_ids: tuple[str, ...]
    target_member_id: str | None
    required_role: str | None
    required_tool_names: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    delivery_kind: DeliveryKind

@dataclass(frozen=True)
class DispatchDecision:
    decision_id: str
    sequence: int
    task_id: str
    action: DispatchAction
    member_id: str | None
    reason_code: str
    observed_team_revision: int
    worktree_start_oid: str | None
    decided_at: datetime
```

- 每个任务必须指定一个目标成员或一个所需角色；二者同时给出时，目标成员仍须满足角色与工具能力。`required_tool_names` 必须是所选成员冻结角色允许工具的子集。
- `local_id` 是单次拆解内的稳定引用；服务在 prepare 阶段一次性分配所有共享 `task_id` 并持久化，再把本地依赖解析为共享依赖。
- `DeliveryKind.NO_GIT` 用于审阅、验证或明确不产生代码的任务，允许后续依赖记录“明确不影响 Git”。默认交付类型为 `GIT`。
- 固定上限：每个拆解批次最多 32 个任务；每个任务最多 16 条验收标准、64 个依赖和 32 个所需工具；目标、描述、标准和诊断分别使用现有团队文本上限或更小的专用上限。
- `DispatchAction` 覆盖 `PENDING`、`ASSIGN`、`REASSIGN`、`CANCEL`、`STOP`、`MANUAL` 和 `START_FAILED`。所有决定只保存枚举原因码与有界说明，不保存模型推理。

### `DecompositionRun`

```python
class DecompositionStatus(StrEnum):
    PREPARED = "prepared"
    ACTIVE = "active"
    READY_TO_INTEGRATE = "ready_to_integrate"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    MANUAL = "manual"

@dataclass(frozen=True)
class DecompositionRun:
    schema_version: int
    revision: int
    run_id: str
    team_id: str
    user_goal: str
    target_branch: str
    target_baseline_oid: str
    auto_integrate: bool
    tasks: tuple[CoordinatorTaskSpec, ...]
    decisions: tuple[DispatchDecision, ...]
    status: DecompositionStatus
    diagnostic: str | None
    created_at: datetime
    updated_at: datetime
```

- 用户目标最多 64 KiB，按需求持久化；不保存完整会话、prompt 或模型回复。
- 创建批次时解析当前已检出的本地分支与 HEAD；调用方可以给出同一分支的完整 ref，但服务不执行 checkout。
- `auto_integrate=True` 表示所有任务终态、成果审阅和 Git 候选条件满足后自动创建并推进集成批次。任何人工/失败任务会阻止自动集成。
- 拆解发布是 journal 化事务：先保存 `PREPARED` 及确定的任务 ID，再用一次 TeamState CAS 添加全部共享任务，最后确认 `ACTIVE`。不存在部分任务发布。

### 成果审阅记录

```python
class DeliveryReviewStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    MANUAL = "manual"

@dataclass(frozen=True)
class DeliveryReview:
    task_id: str
    member_id: str
    task_revision: int
    worktree_start_oid: str | None
    worktree_end_oid: str | None
    commit_oids: tuple[str, ...]
    status: DeliveryReviewStatus
    evidence_summary: str
    reviewed_at: datetime | None
```

- Coordinator 在任务为 `COMPLETED`、成员为可信非活动终态且无调度器/控制 broker 活动运行后，读取固定 Worktree 成果并形成待审阅快照。
- Git 任务必须工作区干净、起点为终点祖先、提交范围非空且分支 HEAD 等于记录的终点。NO_GIT 任务不生成提交范围。
- Team Lead 通过结构化审阅动作接受或拒绝，并提供有界证据摘要；定性验收标准不由基础设施伪装成机器可判定。任务修订、assignee 或 HEAD 改变会使旧审阅失效。

### `IntegrationBatch`

```python
class IntegrationBatchStatus(StrEnum):
    PREPARED = "prepared"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    MANUAL = "manual"

@dataclass(frozen=True)
class IntegrationBatch:
    schema_version: int
    revision: int
    batch_id: str
    team_id: str
    decomposition_run_id: str
    target_branch: str
    baseline_oid: str
    candidate_task_ids: tuple[str, ...]
    topological_task_ids: tuple[str, ...]
    step_ids: tuple[str, ...]
    next_step: int
    status: IntegrationBatchStatus
    diagnostic: str | None
    created_at: datetime
    updated_at: datetime
```

- 只有同一拆解批次中所有任务已成功、审阅已接受或明确为 NO_GIT，且依赖条件满足时才能建立批次。
- 拓扑排序使用 Kahn 算法；就绪节点按 `(ordinal, task_id)` 排序，保证稳定。循环依赖在拆解阶段已整体拒绝。
- v1 要求目标 ref 在批次创建时仍等于 `target_baseline_oid`，每一步要求等于上一确认步骤的结果 OID；任何外部漂移转人工，不自动 rebase、checkout 或猜测修复。

### `IntegrationStep`

```python
class IntegrationStepStatus(StrEnum):
    PREPARED = "prepared"
    MERGING = "merging"
    COMMIT_OBSERVED = "commit_observed"
    VERIFIED = "verified"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"
    MANUAL = "manual"

@dataclass(frozen=True)
class IntegrationStep:
    schema_version: int
    revision: int
    step_id: str
    batch_id: str
    ordinal: int
    task_id: str
    member_id: str
    worktree_root: Path
    member_branch: str
    start_oid: str
    end_oid: str
    commit_oids: tuple[str, ...]
    expected_target_oid: str
    pre_merge_oid: str | None
    integration_commit_oid: str | None
    rollback_oid: str | None
    status: IntegrationStepStatus
    diagnostic: str | None
    created_at: datetime
    updated_at: datetime
```

- 路径必须与当前团队成员记录以及受管理 Worktree record/marker 三方一致；owner 必须是 `TEAM_MEMBER`、`owner_id == member_id`、`persistent=True`、仓库 ID 与团队绑定一致。
- 提交范围为 `(start_oid, end_oid]` 的稳定拓扑顺序列表，并在步骤创建时冻结。步骤执行前再次验证 end OID、范围、Worktree 干净状态和成员无活动运行。
- NO_GIT 任务不创建 Git 步骤，但在批次依赖检查中以已审阅且“不影响 Git”处理。

### `CoordinatorJournal`

```python
class JournalBoundary(StrEnum):
    PREPARED = "prepared"
    TEAM_STATE_COMMITTED = "team_state_committed"
    GIT_PRECHECKED = "git_prechecked"
    MERGE_STARTED = "merge_started"
    MERGE_APPLIED = "merge_applied"
    COMMIT_CREATED = "commit_created"
    POSTCHECKED = "postchecked"
    ROLLBACK_STARTED = "rollback_started"
    ROLLBACK_VERIFIED = "rollback_verified"
    MANUAL_REQUIRED = "manual_required"
    COMPLETED = "completed"

@dataclass(frozen=True)
class CoordinatorJournalEntry:
    sequence: int
    boundary: JournalBoundary
    task_id: str | None
    pre_oid: str | None
    result_oid: str | None
    diagnostic_code: str | None
    recorded_at: datetime

@dataclass(frozen=True)
class CoordinatorJournal:
    schema_version: int
    revision: int
    journal_id: str
    team_id: str
    operation_kind: str
    operation_id: str
    entries: tuple[CoordinatorJournalEntry, ...]
```

- 每个拆解事务、任务协调动作和集成批次各有独立 journal；序号必须从 0 连续递增，边界状态转换必须合法。
- 每次 Git 副作用前先原子持久化边界；副作用后再保存可验证结果。journal 不保存 argv、stdout、stderr、diff、异常堆栈或完整命令。
- journal 使用完整 JSON 快照而不是易留下半行的追加 JSONL；文件替换前后均 fsync。读取截断文件时拒绝并保留现场。

## 核心接口

### 双开关与运行视图

```python
class CoordinatorSettingsResolver:
    def resolve(self, config_path: Path) -> CoordinatorSettings: ...

class CoordinatorToolPolicy:
    def compose_lead_view(
        self,
        base: ToolRegistry,
        lifecycle: ToolRegistry,
        team_tools: ToolRegistry,
        coordinator_tools: ToolRegistry,
    ) -> ToolRegistry: ...
```

- Resolver 接收可替换的环境映射、时钟和 Phase 14B 能力提供者。
- 开启视图先 `select_safety({READ_ONLY})`，再显式排除 `write_file`、`edit_file`、`run_command`、`agent`、`load_skill`，最后加入生命周期、成员/任务/邮箱以及 coordinator 工具。
- 服务层每个 coordinator 写动作都再次执行 `require_enabled()` 和当前 Lead lease fence 校验，防止旧工具引用或手工调用绕过可见性限制。

### 持久仓库与锁

```python
class CoordinatorRepository:
    def initialize(self, team: TeamName, settings: CoordinatorSettings) -> None: ...
    def create_decomposition(self, run: DecompositionRun) -> None: ...
    def update_decomposition(self, run: DecompositionRun, *, expected_revision: int) -> DecompositionRun: ...
    def load_decomposition(self, run_id: str) -> DecompositionRun: ...
    def list_decompositions(self, *, active_only: bool = False) -> tuple[DecompositionRun, ...]: ...
    def create_batch(self, batch: IntegrationBatch, steps: tuple[IntegrationStep, ...]) -> None: ...
    def update_batch(self, batch: IntegrationBatch, *, expected_revision: int) -> IntegrationBatch: ...
    def update_step(self, step: IntegrationStep, *, expected_revision: int) -> IntegrationStep: ...
    def append_journal(self, journal_id: str, entry: CoordinatorJournalEntry) -> CoordinatorJournal: ...
    def task_lock(self, task_id: str) -> ContextManager[None]: ...
    def branch_lock(self, repository_id: str, target_branch: str) -> ContextManager[None]: ...
```

- 团队文件全部在 `team_root/coordinator` 内；任务锁也在该子树。
- 为排除同一仓库中不同团队同时集成同一目标分支，branch lock 位于 `teams_root/.coordinator-locks/<repository-id>/<sha256(ref)>.lock`。它只保存锁文件，不保存业务状态；路径仍受用户 teams 根包含性和链接/重解析点检查。
- `create_batch` 在持有 branch lock 和批次锁时先写 journal，再创建 batch/step 文件；恢复时可从 journal 区分未发布与已发布。

### 编排服务

```python
class TeamDeliveryCoordinator:
    async def open(self) -> tuple[CoordinatorDiagnostic, ...]: ...
    async def close(self) -> None: ...
    async def decompose(self, request: DecompositionRequest) -> DecompositionRun: ...
    async def reconcile(self, run_id: str | None = None) -> CoordinatorSnapshot: ...
    async def decide(self, request: CoordinatorDecisionRequest) -> DecompositionRun: ...
    async def review(self, request: DeliveryReviewRequest) -> DeliveryReview: ...
    async def integrate(self, run_id: str) -> IntegrationBatch: ...
    async def recover(self) -> tuple[CoordinatorDiagnostic, ...]: ...
    def snapshot(self, run_id: str | None = None) -> CoordinatorSnapshot: ...
```

- `open()` 先恢复 journal，再启动一个使用可注入等待器的协调循环；关闭时停止循环并把正在内存中、尚未产生外部副作用的动作标为可恢复。
- `reconcile()` 严格按 `(run.created_at, run_id, task.ordinal, task_id)` 扫描；只做确定性状态观察、派发、候选冻结和已允许的自动集成，不调用模型，也不重放成员工具。
- `decide()` 支持重派、取消、停止和转人工。停止继续调用 Phase 14B 的 roster/scheduler 路径；审批继续使用现有 ApprovalService 和邮箱协议。

### 容量预留与派发

现有容量池增加只用于调度器内部的可移交预留，避免“检查时有容量、提交后却排队”的竞态：

```python
class TeamMemberScheduler:
    async def try_reserve(self, member_id: str) -> MemberCapacityReservation | None: ...
    async def release_reservation(self, reservation: MemberCapacityReservation) -> None: ...

    # 现有 request_wake 在找到匹配预留时将 lease 移交给唯一 driver；
    # 普通 14A/14B 调用仍沿用原有排队路径。
```

派发候选必须同时满足：

1. 所有共享依赖任务为 `COMPLETED`，相应 coordinator 任务没有失败或人工阻塞；
2. 成员 ID/名称、冻结角色和所需工具匹配；
3. 成员为 `IDLE`、没有当前任务、queue、active run、scheduler driver 或 Worktree 占用；
4. 终端成员在 `terminal_backends_verified=True` 时才合格；
5. 可取得即时容量预留。

选择顺序为：指定成员优先；否则过滤精确角色和能力，然后按历史活动指派数量、成员创建时间、成员 ID 排序。没有候选或容量时只追加 `PENDING` 决定，不修改共享任务或启动成员。

取得预留后，协调服务记录 prepare 边界，调用既有任务领域逻辑分配任务并产生 outbox，再由 scheduler 在持久消息唤醒时消费同一预留。异常时释放预留；若 TeamState 已提交，则 journal 记录“已分配、未启动”，恢复只重新评估唤醒，不重复分配。

审批成员允许首次运行生成 Phase 14A 计划请求，但副作用工具继续由 `ApprovalGuardedTool` 阻断；批准前不会进入实现执行，Coordinator 不生成批准决定。

### 受控 Git 后端

```python
class CoordinatorGitBackend:
    async def current_target(self, binding: RepositoryBinding) -> GitTargetSnapshot: ...
    async def inspect_member(self, binding: RepositoryBinding, member: TeamMemberRecord) -> MemberGitSnapshot: ...
    async def commit_range(self, root: Path, start_oid: str, end_oid: str) -> tuple[str, ...]: ...
    async def begin_merge(self, target: GitTargetSnapshot, step: IntegrationStep) -> None: ...
    async def create_merge_commit(self, target: GitTargetSnapshot, step: IntegrationStep) -> str: ...
    async def verify_merge(self, target: GitTargetSnapshot, step: IntegrationStep, oid: str) -> None: ...
    async def recover_step(self, target: GitTargetSnapshot, step: IntegrationStep, journal: CoordinatorJournal) -> RecoveryDecision: ...
    async def rollback(self, target: GitTargetSnapshot, step: IntegrationStep) -> None: ...
```

- 后端复用 `GitCommandRunner` 的无 shell 子进程、输出上限、超时、禁用终端提示和错误脱敏，只暴露固定 argv 组合。
- 目标必须是绑定仓库根当前检出的分支；不执行 checkout。preflight 要求 HEAD/ref 等于期望 OID、index/工作区无 tracked/untracked 变化、无进行中的 merge/rebase/cherry-pick/bisect。
- 成员检查复用 `WorktreeRecordStore.validate_filesystem_identity`，并验证固定分支、owner、base、仓库 common dir、完整提交范围和干净状态。
- 集成执行 `git merge --no-ff --no-commit <end_oid>`，不传入成员文本。无冲突后创建一个 merge commit，提交消息只含有界标题和 `MewCode-Team`、`MewCode-Batch`、`MewCode-Task` 标识 trailer。成员原提交和作者保持不变。
- v1 不自动解决冲突。出现冲突先 `git merge --abort`；若仍需恢复，只在 target 原先干净、当前 HEAD 是已知 pre OID 或可证明的本步骤 merge commit且没有未知修改时执行受控 `reset --hard <pre_oid>`。从不执行 `clean`，不修改成员 Worktree。
- 后置验证检查：当前 ref、merge commit 两个 parent、第二 parent 等于成员 `end_oid`、标识 trailer、所有冻结提交可达、工作区重新干净。任何不一致都回滚或转人工。

### 工具接口

```python
class TeamCoordinatorTool:
    name = "team_coordinator"
    # action: status | decompose | reconcile | decide | review

class TeamGitTool:
    name = "team_git"
    # action: status | inspect | plan | integrate | recover
```

- 两个工具都要求 root Team Lead 控制上下文、有效 attachment、双开关开启和当前 lease fence。
- `team_coordinator.decompose` 接受目标、目标分支、auto_integrate 和结构化任务数组；服务端拒绝未知字段、重复 local ID、未解析依赖、循环和越界。
- `team_git` 不接受命令字符串、路径或任意 argv。所有写动作按 run/batch/task ID 定位已持久记录；只读 `inspect` 返回有界 status、提交 ID、文件名和 diff 统计，不回传秘密或完整异常。
- PLAN 模式只允许 `status`/`inspect`；拆解、决定、审阅和 Git 写动作继续拒绝。

## 模块设计

### `teams.coordinator_settings`

**职责：** 解析配置与环境双开关、Phase 14B 能力标志和安全策略版本。

**对外接口：** `CoordinatorSettingsResolver`、`TerminalBackendReadiness`。

**依赖：** 配置文件读取、可替换环境映射与时钟；不依赖团队持久目录。

### `teams.coordinator_models`

**职责：** 定义拆解、派发、审阅、集成、步骤、journal、状态枚举、严格上限和状态转换验证。

**对外接口：** 本计划中的 Phase 14C 数据结构与验证辅助函数。

**依赖：** `teams.models` 的通用验证和有界诊断，不反向修改 `TeamState`。

### `teams.coordinator_repository`

**职责：** 计算受控路径、初始化启用快照、严格读取、CAS 更新、原子创建、journal 更新以及任务/批次/目标分支并发锁。

**对外接口：** `CoordinatorRepository`。

**依赖：** `teams.codec`、`teams.paths`、`locking.FileLock`、`repository.atomic_write`。

### `teams.orchestration`

**职责：** journal 化拆解发布、依赖与成员资格判定、容量预留、稳定派发、重新派发/取消/停止/人工决策、成果快照和 Lead 审阅。

**对外接口：** `TeamDeliveryCoordinator` 的拆解、协调、决定、审阅与快照部分。

**依赖：** 团队 repository/domain/services、scheduler、roster、mailbox、approvals、Worktree 观察器。

### `teams.coordinator_git`

**职责：** 固定 Git 命令边界、目标/成员快照、提交范围、merge commit、验证、精确回滚和恢复判定。

**对外接口：** `CoordinatorGitBackend` 及 Git snapshot/recovery value objects。

**依赖：** `worktrees.GitCommandRunner`、`WorktreeRecordStore`、repository binding、路径策略。

### `teams.integration`

**职责：** 候选过滤、稳定拓扑计划、branch/task lock、逐步骤 journal、Git 调用、失败短路、批次完成与崩溃恢复。

**对外接口：** `IntegrationService.plan()`、`run()`、`recover()`、`snapshot()`。

**依赖：** coordinator repository/models、orchestration review、coordinator Git backend。

### 既有模块调整

| 模块 | 调整 |
|---|---|
| `config.py` | 读取顶层 `teams.coordinator.enabled`，不改变 profile 解析与 API key 处理。 |
| `teams.paths`、`teams.codec` | Phase 14C 受控路径和各记录严格编解码；普通 `ensure_directories()` 不创建 coordinator 子树。 |
| `teams.coordinator` | 服务集合增加可选 delivery 服务；挂载/关闭顺序接入恢复与协调循环；运行视图按当前 attachment 和 settings 裁剪工具。 |
| `teams.scheduler`、`agent.capacity` | 增加 coordinator 使用的即时容量预留/移交，原 FIFO 接口行为不变。 |
| `teams.tasks` | 增加由 coordinator 调用的确定 ID 批量创建/分配事务入口，复用 domain 规则与 outbox，不改变公开 14A 工具语义。 |
| `teams.tools` | 注册结构化 `team_coordinator` 与 `team_git`；保持旧工具 schema 和动作兼容。 |
| `teams.__init__`、`cli.py` | 导出、解析 settings、延迟装配 coordinator 服务和动态工具视图。 |
| `examples/config.yaml` | 增加默认关闭的 coordinator 配置示例和环境变量说明。 |

## 模块交互

### 1. 双开关关闭

1. CLI 在构造团队服务前解析配置和环境，不访问团队 coordinator 路径。
2. 任一开关关闭时，不构造 `CoordinatorRepository`、交付协调服务、集成服务或协调后台循环。
3. `TeamRunViewComposer` 沿用现有合并逻辑，保留 `write_file`、`edit_file`、`run_command`、普通 Agent 和原团队工具。
4. 即使磁盘上存在以前启用留下的 14C 文件，本次关闭会话也不更新它们；专用工具不可见，旧引用调用时由 settings guard 拒绝。

### 2. 双开关开启与挂载

1. 普通、未挂载 root 会话仍使用完整基础工具。
2. 成功挂载团队并验证 repository binding 与 Lead lease 后，初始化或严格读取 `CoordinatorSettings`。
3. 先沿用 14A/14B 收敛 RUNNING 成员，再恢复 coordinator journal；恢复不调用成员工具或模型。
4. 恢复完成后才 flush 邮箱、恢复普通 queued 成员和启动协调循环。
5. 当前 Lead 的运行视图变为只读基础工具 + 团队工具 + `team_coordinator`/`team_git`，prompt 明确“只编排、审阅和集成，不直接实现”。

### 3. 拆解与发布

1. Lead 生成结构化任务草案并调用 `decompose`。
2. 服务先完整验证数量、文本、成员/角色选择器、能力、依赖和 DAG，再冻结目标分支与 baseline。
3. 服务生成 run/task/journal ID，写 `PREPARED` run 和 journal。
4. 一次 TeamState CAS 按 ordinal 添加所有共享任务；任务描述包含工作正文，验收标准与选择器保留在 coordinator 记录中。
5. CAS 成功后记录团队修订并把 run 改为 `ACTIVE`。崩溃恢复看到全部确定 ID 与字段一致则确认；全部缺失则安全重试；部分或不一致则转人工。

### 4. 自动派发、审批和人工决策

1. 协调循环按稳定顺序读取 active run 和 TeamState，只处理无活动 task lock 的 pending 任务。
2. 依赖、成员状态、角色/工具能力、Phase 14B 能力和容量任一不满足时追加原因决定并保持 pending。
3. 满足条件时先冻结成员 Worktree 起点并取得容量预留，再通过现有 assign/outbox/mailbox 路径投递并唤醒；scheduler 只消费一次预留。
4. 审批成员先运行到计划请求并安全暂停。只有用户/Lead 经现有结构化批准动作批准后，scheduler 才能恢复实现；Coordinator 无批准接口。
5. 成员失败、停止或审批拒绝会阻止后续依赖。Lead 可调用 decide 重派、取消、停止或转人工，每次都写 journal 和 `DispatchDecision`。

### 5. 成果冻结与审阅

1. 共享任务标为 `COMPLETED` 后，协调循环仍等待成员进入 IDLE/STOPPED 等与成功结果一致的可信终态，并确认无 active run、driver、容量预留和 Worktree 锁。
2. Git 任务验证受管理 Worktree 归属、干净状态、起点/终点祖先关系并冻结提交列表；NO_GIT 任务记录无 Git 影响。
3. `team_git.inspect` 允许 Lead 查看有界文件列表、diff stat 和 commit 摘要；基础文件写工具仍不可用。
4. Lead 对照每条验收标准写入 accepted/rejected 审阅决定。任何任务修订、assignee、成员身份或 HEAD 变化使决定失效并重新阻塞。

### 6. 自动计划与集成

1. 所有任务成功且审阅有效后，auto 模式建立 `IntegrationBatch`；手动模式等待 `team_git plan/integrate`。
2. 服务按稳定拓扑顺序产生 Git step，NO_GIT 依赖直接标记不影响；持有 repository+branch lock 后才进入 RUNNING。
3. 每步重新验证 target、成员成果和依赖，写 `GIT_PRECHECKED` 与 `MERGE_STARTED` 后执行固定 merge。
4. 无冲突时生成带标识 trailer 的本地 merge commit，再验证 parents、可达性、ref 和干净状态；确认 step 后更新下一步 expected target OID。
5. 任一步失败立即回滚/转人工、标记 batch 失败并停止；后续依赖 step 不执行。
6. 全部 step 验证完成后 batch 和 decomposition run 标记 COMPLETED。系统不调用 push、fetch、remote、PR 或 Worktree 删除操作。

### 7. 崩溃恢复矩阵

| journal/仓库观察 | 恢复决定 |
|---|---|
| 已 prepare，HEAD 为 pre OID，无 merge 状态 | 可安全重试当前步骤，不重放已确认步骤。 |
| merge 已开始，HEAD 为 pre OID，存在匹配 `MERGE_HEAD` | 执行 `merge --abort`，验证干净后把步骤标为 rolled_back/retryable。 |
| journal 未确认 commit，但 HEAD 是 parents/trailer 全匹配的本步骤 merge commit | 补记 `COMMIT_CREATED`/`POSTCHECKED`，不得再次 merge。 |
| 已确认 step，但 batch.next_step 未推进 | 从已验证 step 结果修复 batch 元数据，不执行 Git。 |
| HEAD 漂移、未知修改、MERGE_HEAD 不匹配、trailer/parents 不匹配 | 不 reset、不继续，步骤和 batch 转 MANUAL 并报告有界诊断。 |
| rollback 命令失败或回滚后状态不可验证 | 转 MANUAL，停止所有后续依赖。 |

## 文件组织

```text
src/mewcode/
├── config.py                              # coordinator 配置能力开关
├── agent/capacity.py                      # 可移交即时容量预留
└── teams/
    ├── coordinator_models.py              # 14C 版本化记录与状态机
    ├── coordinator_settings.py            # 双开关与 14B readiness
    ├── coordinator_repository.py          # 专用存储、CAS、journal 和锁
    ├── orchestration.py                   # 拆解、派发、决定、审阅、循环
    ├── coordinator_git.py                 # 固定 Git 边界与恢复判定
    ├── integration.py                     # 拓扑批次和逐步集成
    ├── coordinator.py                     # 生命周期与工具视图接入
    ├── codec.py                           # 新记录严格编解码入口
    ├── paths.py                           # coordinator 目录与 branch lock 路径
    ├── scheduler.py                       # 容量预留消费
    ├── tasks.py                           # 确定 ID 批量任务事务
    ├── tools.py                           # team_coordinator / team_git
    └── __init__.py                        # 公开导出

tests/
├── test_config.py                         # 双开关配置解析
├── test_agent_capacity.py                 # 容量预留与竞态回归
├── test_team_cli_integration.py           # CLI 装配、工具裁剪和零副作用
└── teams/
    ├── test_coordinator_models.py          # 状态机、上限和严格验证
    ├── test_coordinator_settings.py        # 双开关矩阵与 readiness
    ├── test_coordinator_repository.py      # 原子/CAS/截断/重复/路径/锁
    ├── test_orchestration.py               # 拆解、派发、审批、重派和审阅
    ├── test_coordinator_git.py             # 固定 argv、检查、回滚、脱敏
    ├── test_coordinator_integration.py     # 拓扑、冲突、崩溃和恢复
    └── test_coordinator_e2e.py             # Git fake 与三后端端到端

docs/phase-14c-team-coordinator/
├── spec.md
├── plan.md
├── task.md
└── checklist.md
```

## 技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 14A/14B 格式兼容 | 独立 14C 文件，不扩展 `TeamState` | 开关关闭时零 14C 写入，旧状态无需迁移，未来 coordinator 损坏不会让普通团队状态不可读。 |
| 双开关解析 | 配置布尔值 + 精确环境值 `1` | 防止默认或模糊 truthy 值意外启用高权限模式。 |
| 工具收窄 | 只读基础工具白名单后显式加入团队工具 | 由构造保证权限，而不是依赖 prompt 自律；普通会话仍沿用原注册表。 |
| 受限 shell | 结构化 `team_git`，不接受字符串命令 | 能完成检查/合并/回滚/验证，同时从接口上排除 push、remote 和路径逃逸。 |
| 拆解原子性 | prepare journal + 确定 ID + 单次 TeamState CAS | 可区分未发布、已发布未确认和篡改，不产生部分共享任务。 |
| 调度确定性 | 简单 DAG + 稳定排序，不做复杂优化 | 满足有限任务与依赖需求，容易审计和恢复。 |
| 容量竞态 | scheduler 即时预留并在 wake 时移交 | 容量不足时任务真正保持 pending，避免检查与启动之间超额或排队。 |
| 审批语义 | 允许规划运行，副作用继续由 14A guard 阻断 | 成员必须先产生计划请求；Coordinator 不绕过或自批审批。 |
| 成果验收 | Git 机器检查 + Lead 结构化审阅 | 验收标准可能是语义性的，基础设施只证明可证明的仓库事实。 |
| Git 集成形式 | `merge --no-ff --no-commit` + 标识 trailer | 保留成员原提交/作者，merge parents 和 trailer 使崩溃后可识别副作用。 |
| 冲突策略 v1 | 全部拒绝并回滚 | 当前没有足够上下文定义无歧义通用自动解冲突；严格策略满足安全默认。 |
| 漂移策略 v1 | 全部拒绝并转人工 | 避免把外部目标分支变化静默吸收到已审阅批次。 |
| 回滚 | 只在 preclean 且当前状态可证明时 abort/reset；从不 clean | 恢复 coordinator 自己的变化，同时不删除未知或成员成果。 |
| 恢复 | 以 Git 可验证事实补 journal，不以缺失确认重复命令 | 关闭“commit 成功、确认写盘前崩溃”造成重复合并的窗口。 |
| 远端边界 | Git backend 无 remote/fetch/push/PR 方法 | 从可调用能力上排除远端副作用，而非只做字符串黑名单。 |

## 安全与失败处理

- 所有 coordinator 动作同时校验 settings、attachment、team ID、Lead actor、lease fence、记录 revision 与相应文件锁。
- 任何模型提供的任务、成员名、标题、标准、分支或理由先严格验证；文本永不进入 shell，分支不用于文件名。
- Git stderr 仅保留现有脱敏摘要；工具输出进一步限制文件数量、提交数量和文本长度，不返回完整异常或命令。
- coordinator 文件读取遇到未知/重复字段、未来版本、截断、大小越界、链接/重解析点或非法状态时停止该服务并保留原文件；不覆盖现场。
- 挂载恢复先处理不确定 Git 状态，再允许新批次。一个 MANUAL 集成批次会阻止同目标分支的新批次，直到用户在仓库外处理并显式调用 recover。
- 关闭过程不删除 coordinator 文件、成员 Worktree、分支或提交；只释放内存预留/锁并保存可恢复边界。

## 验证策略

- **模型与编解码：** 每个版本化记录的 round-trip、未知/重复/缺失字段、未来版本、截断、越界文本、非法 OID/ref/path 和状态转换。
- **双开关与权限：** 四种开关组合、非法环境值、未挂载/挂载会话、普通成员/普通子 Agent，比较工具名称及磁盘树。
- **拆解与派发：** 稳定 ID/依赖、整体拒绝、角色/工具选择、容量预留、繁忙/失败/停止成员、审批规划暂停和并发 reconcile。
- **成果与拓扑：** Worktree owner/record/marker/branch 三方验证、dirty/空范围/HEAD 改变、审阅失效、稳定 Kahn 顺序和 NO_GIT 依赖。
- **Git 故障：** 固定 argv fake 覆盖 preflight、merge 冲突、commit 失败、postcheck 失败、abort/reset 失败、输出越界和秘密脱敏；断言无 push/remote/clean/Worktree 删除调用。
- **崩溃恢复：** 在每个 journal 边界注入进程中断，覆盖未执行、merge 未提交、commit 未确认、step 已确认 batch 未推进、未知漂移和回滚失败。
- **端到端：** 使用临时本地仓库与 scripted Git runner 完成多成员依赖链；分别覆盖 in_process、Windows Terminal fake、tmux fake。readiness=false 时终端路径明确拒绝。
- **回归：** `python -m compileall -q src/mewcode`、团队专项、agent capacity/CLI 受影响测试、完整 `python -m pytest`、`git diff --check` 和安装/CLI 冒烟。
