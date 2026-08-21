# Phase 14C Team Lead 编排、受控 Git 集成与 Coordinator 双开关 Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 新建 | `src/mewcode/teams/coordinator_models.py` | 14C 版本化模型、枚举、上限和状态转换。 |
| 新建 | `src/mewcode/teams/coordinator_settings.py` | 配置/环境双开关与 Phase 14B readiness 解析。 |
| 新建 | `src/mewcode/teams/coordinator_repository.py` | coordinator 文件、CAS、journal 与并发锁。 |
| 新建 | `src/mewcode/teams/orchestration.py` | 拆解、派发、人工决定、成果冻结、审阅与协调循环。 |
| 新建 | `src/mewcode/teams/coordinator_git.py` | 受控 Git 检查、merge、验证、回滚和恢复判定。 |
| 新建 | `src/mewcode/teams/integration.py` | 候选、稳定拓扑、批次执行与崩溃恢复。 |
| 修改 | `src/mewcode/config.py` | 读取 coordinator 配置能力开关。 |
| 修改 | `src/mewcode/agent/capacity.py` | 支持 coordinator 的即时容量预留/移交语义。 |
| 修改 | `src/mewcode/teams/paths.py` | 受控 coordinator 目录、文件与 repository/branch lock 路径。 |
| 修改 | `src/mewcode/teams/codec.py` | Phase 14C 记录严格编解码入口。 |
| 修改 | `src/mewcode/teams/tasks.py` | 确定 ID 的原子批量任务发布入口。 |
| 修改 | `src/mewcode/teams/scheduler.py` | 容量预留、wake 消费和关闭释放。 |
| 修改 | `src/mewcode/teams/coordinator.py` | delivery 生命周期、恢复顺序和 Lead 工具视图裁剪。 |
| 修改 | `src/mewcode/teams/tools.py` | `team_coordinator` 与 `team_git` 结构化工具。 |
| 修改 | `src/mewcode/teams/__init__.py` | 导出 Phase 14C 公开组件。 |
| 修改 | `src/mewcode/cli.py` | 双开关解析、服务延迟装配和工具注册。 |
| 修改 | `examples/config.yaml` | 默认关闭的配置示例。 |
| 新建 | `tests/teams/coordinator_helpers.py` | 共享设置、状态、Git 与故障注入 fake。 |
| 新建 | `tests/teams/test_coordinator_models.py` | 模型、不变量、上限和状态转换测试。 |
| 新建 | `tests/teams/test_coordinator_settings.py` | 双开关/readiness 测试。 |
| 新建 | `tests/teams/test_coordinator_repository.py` | 严格存储、CAS、路径与锁测试。 |
| 新建 | `tests/teams/test_orchestration.py` | 拆解、派发、审批、决定和审阅测试。 |
| 新建 | `tests/teams/test_coordinator_git.py` | 固定 Git 边界、验证、回滚和脱敏测试。 |
| 新建 | `tests/teams/test_coordinator_integration.py` | 拓扑、批次、冲突和恢复测试。 |
| 新建 | `tests/teams/test_coordinator_e2e.py` | Git fake 与三种成员后端端到端测试。 |
| 修改 | `tests/test_config.py` | 顶层 teams 配置兼容和错误测试。 |
| 修改 | `tests/test_agent_capacity.py` | 容量预留并发与释放测试。 |
| 修改 | `tests/teams/test_scheduler.py` | 预留消费、去重和普通 FIFO 回归。 |
| 修改 | `tests/teams/test_domain_tasks.py` | 原子批量任务行为测试。 |
| 修改 | `tests/teams/test_paths_codec.py` | coordinator 路径和编解码回归。 |
| 修改 | `tests/teams/test_tools.py` | 新工具 schema、模式与 guard 测试。 |
| 修改 | `tests/teams/test_integration.py` | 挂载/恢复/关闭生命周期测试。 |
| 修改 | `tests/test_team_cli_integration.py` | CLI 工具可见性、零副作用和普通会话回归。 |
| 修改 | `docs/phase-14c-team-coordinator/checklist.md` | 实施后的实际验收证据。 |

## T01：记录实施前基线

**文件：** `docs/phase-14c-team-coordinator/checklist.md`（批准后生成，开发阶段只记录结果）

**依赖：** 四份文档全部批准

**步骤：**
1. 确认工作树中的用户既有改动并记录，不覆盖 Phase 14A 文档迁移。
2. 运行完整测试、编译和 `git diff --check`，保存通过数、耗时与退出码。

**验证：** 运行 `python -m pytest`、`python -m compileall -q src/mewcode` 和 `git diff --check`，期望全部退出码为 0，并把证据写入 checklist 基线。

## T02：建立 coordinator 测试 fake

**文件：** `tests/teams/coordinator_helpers.py`

**依赖：** T01

**步骤：**
1. 提供固定时钟、确定 ID、启用/关闭 settings 和 Phase 14B readiness 构造器。
2. 提供可记录调用的 scripted Git runner、故障边界和最小团队/成员状态构造器。

**验证：** 运行 `python -m pytest --collect-only tests/teams/coordinator_helpers.py`，期望导入无错误且不收集伪测试。

## T03：定义 coordinator 常量和基础枚举

**文件：** `src/mewcode/teams/coordinator_models.py`

**依赖：** T01

**步骤：**
1. 定义 schema/policy 版本、任务/文本/提交/journal 上限。
2. 定义拆解、派发、交付审阅、批次、步骤和 journal 枚举。

**验证：** 运行 `python -m compileall -q src/mewcode/teams/coordinator_models.py`，期望退出码 0。

## T04：实现 CoordinatorSettings 模型不变量

**文件：** `src/mewcode/teams/coordinator_models.py`, `tests/teams/test_coordinator_models.py`

**依赖：** T03

**步骤：**
1. 实现版本、布尔关系、策略版本、UTC 时间校验。
2. 添加 enabled 与双开关不一致、未来版本和无时区时间测试。

**验证：** 运行 `python -m pytest tests/teams/test_coordinator_models.py -k settings`，期望全部通过。

## T05：实现拆解任务与派发决定模型

**文件：** `src/mewcode/teams/coordinator_models.py`, `tests/teams/test_coordinator_models.py`

**依赖：** T03

**步骤：**
1. 实现 `CoordinatorTaskSpec`、`DispatchDecision`、selector、依赖和文本上限。
2. 拒绝重复工具/依赖、空标准、非法 target/role 组合和非法 OID。

**验证：** 运行 `python -m pytest tests/teams/test_coordinator_models.py -k 'task_spec or dispatch'`，期望全部通过。

## T06：实现 DecompositionRun 状态机

**文件：** `src/mewcode/teams/coordinator_models.py`, `tests/teams/test_coordinator_models.py`

**依赖：** T04, T05

**步骤：**
1. 实现 run 字段、任务数量、local/shared ID 唯一性、依赖解析和稳定 ordinal 校验。
2. 实现合法状态转换与 revision 单调规则。

**验证：** 运行 `python -m pytest tests/teams/test_coordinator_models.py -k decomposition`，期望合法 DAG 通过、循环/越界/非法转换被拒绝。

## T07：实现 DeliveryReview 模型

**文件：** `src/mewcode/teams/coordinator_models.py`, `tests/teams/test_coordinator_models.py`

**依赖：** T05

**步骤：**
1. 实现 Git/NO_GIT 两类审阅字段一致性和提交列表上限。
2. 拒绝 accepted 但缺少 evidence、Git range 或 review time 的记录。

**验证：** 运行 `python -m pytest tests/teams/test_coordinator_models.py -k review`，期望全部通过。

## T08：实现 IntegrationBatch 与 IntegrationStep 模型

**文件：** `src/mewcode/teams/coordinator_models.py`, `tests/teams/test_coordinator_models.py`

**依赖：** T03, T07

**步骤：**
1. 实现 batch/step 字段、完整 ref/OID、next_step、step 顺序和路径校验。
2. 实现合法步骤/批次状态转换与终态不变量。

**验证：** 运行 `python -m pytest tests/teams/test_coordinator_models.py -k integration`，期望全部通过。

## T09：实现 CoordinatorJournal 模型与边界状态机

**文件：** `src/mewcode/teams/coordinator_models.py`, `tests/teams/test_coordinator_models.py`

**依赖：** T03, T08

**步骤：**
1. 实现 journal/entry、连续序号、操作身份和上限。
2. 拒绝跳号、重复边界、非法回滚/完成顺序和终态后追加。

**验证：** 运行 `python -m pytest tests/teams/test_coordinator_models.py -k journal`，期望全部通过。

## T10：解析顶层 coordinator 配置

**文件：** `src/mewcode/config.py`, `tests/test_config.py`

**依赖：** T04

**步骤：**
1. 增加不解析 API key 的顶层 capability 读取入口。
2. 缺失 `teams`/`coordinator` 默认关闭，错误类型和非布尔 enabled 明确拒绝。
3. 保持现有 profile catalog 行为不变。

**验证：** 运行 `python -m pytest tests/test_config.py -k 'coordinator or profile'`，期望新矩阵与旧 profile 测试全部通过。

## T11：实现双开关 settings resolver

**文件：** `src/mewcode/teams/coordinator_settings.py`, `tests/teams/test_coordinator_settings.py`

**依赖：** T04, T10

**步骤：**
1. 注入环境映射、时钟和 terminal readiness provider。
2. 实现四种开关组合、精确 `1`、关闭值和非法值有界诊断。

**验证：** 运行 `python -m pytest tests/teams/test_coordinator_settings.py -k resolver`，期望全部通过。

## T12：固化 Phase 14B readiness 边界

**文件：** `src/mewcode/teams/coordinator_settings.py`, `tests/teams/test_coordinator_settings.py`

**依赖：** T11

**步骤：**
1. 提供默认已验收 readiness 标志。
2. 支持测试注入 false，且不从 checklist 文本或终端探测猜测验收状态。

**验证：** 运行 `python -m pytest tests/teams/test_coordinator_settings.py -k terminal`，期望 true/false 两条路径稳定。

## T13：补充默认关闭配置示例

**文件：** `examples/config.yaml`

**依赖：** T10

**步骤：**
1. 添加 `teams.coordinator.enabled: false` 示例。
2. 注明还需 `MEWCODE_ENABLE_TEAM_COORDINATOR=1`，且默认无权限变化。

**验证：** 使用配置读取入口加载 `examples/config.yaml`（在测试环境提供示例 API key），期望 coordinator capability 为关闭且 profile 可解析。

## T14：定义 CoordinatorPaths

**文件：** `src/mewcode/teams/paths.py`, `tests/teams/test_paths_codec.py`

**依赖：** T03

**步骤：**
1. 计算 settings、decompositions、integrations、steps、journals 和 task locks 路径。
2. 单独提供 `ensure_coordinator_directories()`；普通 `ensure_directories()` 不创建它们。

**验证：** 运行 `python -m pytest tests/teams/test_paths_codec.py -k coordinator_paths`，期望路径包含且关闭路径未被创建。

## T15：实现 repository/branch lock 路径

**文件：** `src/mewcode/teams/paths.py`, `tests/teams/test_paths_codec.py`

**依赖：** T14

**步骤：**
1. 用 repository ID 与 branch ref 摘要生成跨团队 branch lock。
2. 检查 user teams root 包含性、unsafe ID、symlink/reparse 和 Windows 保留名。

**验证：** 运行 `python -m pytest tests/teams/test_paths_codec.py -k coordinator_lock`，期望逃逸和链接路径被拒绝。

## T16：增加 14C 严格编解码入口

**文件：** `src/mewcode/teams/codec.py`, `tests/teams/test_paths_codec.py`

**依赖：** T04-T09

**步骤：**
1. 为 settings、decomposition、batch、step、journal 增加显式 encode/decode。
2. 复用 duplicate JSON field 检测，并保持 record 类型不混读。

**验证：** 运行 `python -m pytest tests/teams/test_paths_codec.py -k coordinator_codec`，期望所有记录 round-trip 且错类型被拒绝。

## T17：覆盖未来版本、截断和越界编解码

**文件：** `tests/teams/test_paths_codec.py`

**依赖：** T16

**步骤：**
1. 参数化未知/重复/缺失字段、未来版本、截断 JSON、非法 UTF-8 和越界文本。
2. 断言读取失败不会修改原始文件。

**验证：** 运行 `python -m pytest tests/teams/test_paths_codec.py -k coordinator_corruption`，期望全部通过。

## T18：实现 CoordinatorRepository 初始化

**文件：** `src/mewcode/teams/coordinator_repository.py`, `tests/teams/test_coordinator_repository.py`

**依赖：** T11, T14-T16

**步骤：**
1. 仅 enabled settings 可创建目录和 settings 文件。
2. 已存在相同快照幂等；策略/readiness/team 不匹配明确拒绝且不覆盖。

**验证：** 运行 `python -m pytest tests/teams/test_coordinator_repository.py -k initialize`，期望关闭零文件、开启一次创建、重复幂等。

## T19：实现 DecompositionRun 原子 CRUD/CAS

**文件：** `src/mewcode/teams/coordinator_repository.py`, `tests/teams/test_coordinator_repository.py`

**依赖：** T18

**步骤：**
1. 实现 create/load/list/update 与 expected revision。
2. 排序稳定，重复 create 和 revision 冲突不覆盖文件。

**验证：** 运行 `python -m pytest tests/teams/test_coordinator_repository.py -k decomposition`，期望 CRUD、排序与 CAS 测试通过。

## T20：实现 batch/step 原子 CRUD

**文件：** `src/mewcode/teams/coordinator_repository.py`, `tests/teams/test_coordinator_repository.py`

**依赖：** T18

**步骤：**
1. 实现 batch 与所有 step 的 prepare/create/load/list/update。
2. 防止 batch 引用缺失/重复 step，拒绝部分发布为可运行批次。

**验证：** 运行 `python -m pytest tests/teams/test_coordinator_repository.py -k 'batch or step'`，期望全部通过。

## T21：实现 journal 原子追加

**文件：** `src/mewcode/teams/coordinator_repository.py`, `tests/teams/test_coordinator_repository.py`

**依赖：** T18, T09

**步骤：**
1. 在 journal lock 内读取、验证、追加、递增 revision 并原子替换。
2. 并行追加只能有一个合法顺序，失败不会留下截断快照。

**验证：** 运行 `python -m pytest tests/teams/test_coordinator_repository.py -k journal`，期望并发序列无重复/跳号。

## T22：实现任务动作锁与跨团队 branch lock

**文件：** `src/mewcode/teams/coordinator_repository.py`, `tests/teams/test_coordinator_repository.py`

**依赖：** T15, T18

**步骤：**
1. 提供 task/action/batch lock context manager。
2. 验证两个 repository 实例对同一 repo/ref 互斥，对不同 ref 可并行。

**验证：** 运行 `python -m pytest tests/teams/test_coordinator_repository.py -k lock`，期望互斥、释放和异常退出测试通过且无真实等待。

## T23：增加确定 ID 的批量任务领域操作

**文件：** `src/mewcode/teams/tasks.py`, `tests/teams/test_domain_tasks.py`

**依赖：** T06

**步骤：**
1. 使用既有 `domain.create_task` 在单个 transform 中按 ordinal 添加全部确定 ID 任务。
2. 任何一项失败时 CAS 不提交，重复确定 ID 可由恢复层识别而不再创建。

**验证：** 运行 `python -m pytest tests/teams/test_domain_tasks.py -k batch_create`，期望全成全败和依赖映射测试通过。

## T24：暴露 coordinator 批量发布服务入口

**文件：** `src/mewcode/teams/tasks.py`, `tests/teams/test_domain_tasks.py`

**依赖：** T23

**步骤：**
1. 增加仅内部使用的 `create_batch`，要求 Lead actor 和有效 fence。
2. 返回提交后的 team revision 与 task views，不改变公开 `create` 行为。

**验证：** 运行 `python -m pytest tests/teams/test_domain_tasks.py -k coordinator_batch`，期望 fence/actor/旧接口测试通过。

## T25：为容量池补充可移交预留语义

**文件：** `src/mewcode/agent/capacity.py`, `tests/test_agent_capacity.py`

**依赖：** T01

**步骤：**
1. 定义 reservation 所有权、一次移交和释放状态。
2. 保持现有 lease/FIFO/close 行为，拒绝重复 owner 和双重移交。

**验证：** 运行 `python -m pytest tests/test_agent_capacity.py -k reservation`，期望预留、移交、取消和 close 测试通过。

## T26：在 scheduler 中实现 try_reserve/release

**文件：** `src/mewcode/teams/scheduler.py`, `tests/teams/test_scheduler.py`

**依赖：** T25

**步骤：**
1. 为 IDLE 且无 driver 的成员取得即时预留并按 member ID 去重。
2. 容量不足返回 `None`，不写 queue 或成员状态。

**验证：** 运行 `python -m pytest tests/teams/test_scheduler.py -k reserve`，期望容量不足零状态变化、重复预留被合并。

## T27：让 wake driver 消费匹配预留

**文件：** `src/mewcode/teams/scheduler.py`, `tests/teams/test_scheduler.py`

**依赖：** T26

**步骤：**
1. `request_wake`/`_drive` 优先一次性移交 coordinator 预留。
2. 普通邮箱/恢复 wake 没有预留时继续走既有容量 acquire。

**验证：** 运行 `python -m pytest tests/teams/test_scheduler.py -k reservation_wake`，期望预留只消费一次且旧 FIFO 测试仍通过。

## T28：释放失败、停止和关闭时的预留

**文件：** `src/mewcode/teams/scheduler.py`, `tests/teams/test_scheduler.py`

**依赖：** T27

**步骤：**
1. 覆盖 assignment 未提交、wake 失败、显式停止、scheduler close 和异常 driver。
2. 确保没有容量泄漏或晚到 driver。

**验证：** 运行 `python -m pytest tests/teams/test_scheduler.py -k 'reservation and (failure or close or stop)'`，期望全部通过。

## T29：定义受控 Git snapshot 与恢复值对象

**文件：** `src/mewcode/teams/coordinator_git.py`, `tests/teams/test_coordinator_git.py`

**依赖：** T08, T02

**步骤：**
1. 定义 target/member snapshot、work status、recovery decision 与严格摘要上限。
2. 拒绝非法 OID/ref/path 和不一致 merge 状态。

**验证：** 运行 `python -m pytest tests/teams/test_coordinator_git.py -k models`，期望全部通过。

## T30：实现固定 Git 调用与输出脱敏封装

**文件：** `src/mewcode/teams/coordinator_git.py`, `tests/teams/test_coordinator_git.py`

**依赖：** T29

**步骤：**
1. 只允许模块内部枚举的固定 argv，复用 `GitCommandRunner` 超时/输出上限。
2. 错误只公开操作代码和脱敏摘要，不持久化 argv/stdout/stderr。

**验证：** 运行 `python -m pytest tests/teams/test_coordinator_git.py -k 'fixed_argv or redaction'`，期望命令记录无 shell、push、remote、秘密。

## T31：实现目标分支 preflight

**文件：** `src/mewcode/teams/coordinator_git.py`, `tests/teams/test_coordinator_git.py`

**依赖：** T30

**步骤：**
1. 验证 repository binding、当前 symbolic ref、HEAD、干净状态和无进行中 Git 操作。
2. 拒绝 checkout 其它分支、detached HEAD、dirty/untracked 和 baseline 漂移。

**验证：** 运行 `python -m pytest tests/teams/test_coordinator_git.py -k target_preflight`，期望每个拒绝原因稳定。

## T32：实现成员 Worktree 身份检查

**文件：** `src/mewcode/teams/coordinator_git.py`, `tests/teams/test_coordinator_git.py`

**依赖：** T30

**步骤：**
1. 复用 Worktree record/marker/filesystem identity 验证 owner、purpose、persistent、repo、root 和 branch。
2. 拒绝链接/重解析、路径漂移、跨成员和跨团队 Worktree。

**验证：** 运行 `python -m pytest tests/teams/test_coordinator_git.py -k worktree_identity`，期望全部通过。

## T33：实现提交范围与 inspect 摘要

**文件：** `src/mewcode/teams/coordinator_git.py`, `tests/teams/test_coordinator_git.py`

**依赖：** T31, T32

**步骤：**
1. 验证 start 是 end 祖先，冻结稳定 commit list，并要求成员 HEAD 为 end。
2. 返回有界 commit 摘要、文件名和 diff stat；拒绝空/超限范围和 dirty 成果。

**验证：** 运行 `python -m pytest tests/teams/test_coordinator_git.py -k 'commit_range or inspect'`，期望排序、上限和脏状态测试通过。

## T34：实现 begin_merge

**文件：** `src/mewcode/teams/coordinator_git.py`, `tests/teams/test_coordinator_git.py`

**依赖：** T31, T33

**步骤：**
1. 再次 preflight expected target OID 后执行固定 `merge --no-ff --no-commit end_oid`。
2. 成员标题/描述不进入 argv；冲突返回结构化失败而不尝试解析。

**验证：** 运行 `python -m pytest tests/teams/test_coordinator_git.py -k begin_merge`，期望成功 argv 固定、冲突无自动 resolution。

## T35：实现 merge commit 创建与后置验证

**文件：** `src/mewcode/teams/coordinator_git.py`, `tests/teams/test_coordinator_git.py`

**依赖：** T34

**步骤：**
1. 创建只含有界标题和 team/batch/task trailer 的 merge commit。
2. 验证两个 parent、第二 parent、提交可达性、ref、HEAD 和干净状态。

**验证：** 运行 `python -m pytest tests/teams/test_coordinator_git.py -k 'create_merge_commit or verify_merge'`，期望合法 merge 通过、伪 trailer/parents 被拒绝。

## T36：实现精确回滚

**文件：** `src/mewcode/teams/coordinator_git.py`, `tests/teams/test_coordinator_git.py`

**依赖：** T35

**步骤：**
1. 匹配 merge state 时优先 abort；只有可证明为本步骤结果时允许 reset 到 pre OID。
2. 禁止 clean、Worktree 删除、分支删除和远端命令；未知 dirty 状态转人工。

**验证：** 运行 `python -m pytest tests/teams/test_coordinator_git.py -k rollback`，期望恢复前后 OID/状态正确且 forbidden 调用为零。

## T37：实现 Git 崩溃恢复判定

**文件：** `src/mewcode/teams/coordinator_git.py`, `tests/teams/test_coordinator_git.py`

**依赖：** T35, T36, T09

**步骤：**
1. 覆盖未执行、merge 未提交、commit 未确认、已验证和未知漂移矩阵。
2. 仅通过 parents/trailer/OID/merge state 可证明事实返回 retry/confirm/rollback/manual。

**验证：** 运行 `python -m pytest tests/teams/test_coordinator_git.py -k recovery`，期望恢复矩阵全部通过且确认路径不再次 merge。

## T38：实现稳定拓扑排序

**文件：** `src/mewcode/teams/integration.py`, `tests/teams/test_coordinator_integration.py`

**依赖：** T06

**步骤：**
1. 实现 Kahn 排序并用 `(ordinal, task_id)` 排序就绪节点。
2. 覆盖多层、同层、NO_GIT、未知依赖和循环。

**验证：** 运行 `python -m pytest tests/teams/test_coordinator_integration.py -k topology`，期望每次顺序一致。

## T39：实现集成候选资格过滤

**文件：** `src/mewcode/teams/integration.py`, `tests/teams/test_coordinator_integration.py`

**依赖：** T07, T33, T38

**步骤：**
1. 要求共享任务成功、审阅有效、成员可信终态、无运行、范围/归属有效。
2. NO_GIT 只在 accepted 且明确无 Git 影响时满足依赖。

**验证：** 运行 `python -m pytest tests/teams/test_coordinator_integration.py -k candidate`，期望每个不合格原因阻止候选。

## T40：实现 IntegrationBatch/Step 计划持久化

**文件：** `src/mewcode/teams/integration.py`, `tests/teams/test_coordinator_integration.py`

**依赖：** T20-T22, T38, T39

**步骤：**
1. 持有 branch lock，冻结 baseline、候选、拓扑、step 和 expected target OID。
2. 同分支已有非终态 batch 或同任务已有尝试时拒绝。

**验证：** 运行 `python -m pytest tests/teams/test_coordinator_integration.py -k plan_batch`，期望稳定记录和并发排除通过。

## T41：实现单个集成步骤执行

**文件：** `src/mewcode/teams/integration.py`, `tests/teams/test_coordinator_integration.py`

**依赖：** T21, T34-T36, T40

**步骤：**
1. 按 precheck、merge started、commit created、postchecked、completed 顺序写 journal。
2. 每次写 Git 前后保存可验证 OID，不在内存中越过未持久边界。

**验证：** 运行 `python -m pytest tests/teams/test_coordinator_integration.py -k run_step`，期望 journal 边界和 Git 调用顺序精确。

## T42：实现批次顺序、失败短路和回滚

**文件：** `src/mewcode/teams/integration.py`, `tests/teams/test_coordinator_integration.py`

**依赖：** T41

**步骤：**
1. 逐步推进 next_step 并把上一 merge OID 作为下一 expected target。
2. 冲突、Git/commit/postcheck 失败时回滚、标记失败/人工并停止后续依赖。

**验证：** 运行 `python -m pytest tests/teams/test_coordinator_integration.py -k 'batch_run or short_circuit'`，期望后续步骤调用数为零。

## T43：实现 IntegrationService 崩溃恢复

**文件：** `src/mewcode/teams/integration.py`, `tests/teams/test_coordinator_integration.py`

**依赖：** T37, T42

**步骤：**
1. 扫描非终态 batch/journal，调用 Git 恢复判定并修复 step/batch 元数据。
2. confirm 路径不执行 merge；rollback 后只在验证安全时重试；未知状态转人工。

**验证：** 运行 `python -m pytest tests/teams/test_coordinator_integration.py -k recovery`，期望每个崩溃边界无重复副作用。

## T44：实现拆解请求严格验证

**文件：** `src/mewcode/teams/orchestration.py`, `tests/teams/test_orchestration.py`

**依赖：** T06, T31

**步骤：**
1. 将工具草案解析为完整 `CoordinatorTaskSpec`，一次性验证上限、selector、依赖和 DAG。
2. 冻结当前目标分支/baseline，拒绝 checkout 或基线不确定状态。

**验证：** 运行 `python -m pytest tests/teams/test_orchestration.py -k validate_decomposition`，期望无效批次零文件、零共享任务。

## T45：实现 journal 化拆解发布

**文件：** `src/mewcode/teams/orchestration.py`, `tests/teams/test_orchestration.py`

**依赖：** T19, T21, T24, T44

**步骤：**
1. 按 PREPARED → TeamState 单次 CAS → ACTIVE 写入 run/journal。
2. 在 prepare、CAS 后和 finalize 前注入故障。

**验证：** 运行 `python -m pytest tests/teams/test_orchestration.py -k publish_decomposition`，期望正常全量发布、故障无部分任务。

## T46：恢复未完成拆解事务

**文件：** `src/mewcode/teams/orchestration.py`, `tests/teams/test_orchestration.py`

**依赖：** T45

**步骤：**
1. 全部确定 task ID 缺失时安全重试；全部精确存在时补 finalize。
2. 部分/字段不一致时转人工，不覆盖 TeamState。

**验证：** 运行 `python -m pytest tests/teams/test_orchestration.py -k recover_decomposition`，期望三类恢复结果正确且无重复创建。

## T47：实现成员资格过滤与稳定排名

**文件：** `src/mewcode/teams/orchestration.py`, `tests/teams/test_orchestration.py`

**依赖：** T12, T05

**步骤：**
1. 检查依赖、角色、冻结工具、状态/current task/queue/run/driver 和 readiness。
2. 按目标成员或历史分配数、创建时间、ID 产生稳定顺序。

**验证：** 运行 `python -m pytest tests/teams/test_orchestration.py -k eligibility`，期望角色/能力/状态/readiness 矩阵与稳定排序通过。

## T48：实现容量不足的 pending 决定

**文件：** `src/mewcode/teams/orchestration.py`, `tests/teams/test_orchestration.py`

**依赖：** T21, T26, T47

**步骤：**
1. 在 task lock 内尝试即时预留；无容量只追加有界 PENDING 决定。
2. 重复 reconcile 合并相同观察，不制造无界重复决定。

**验证：** 运行 `python -m pytest tests/teams/test_orchestration.py -k capacity_pending`，期望任务未分配、成员未启动、容量未超限。

## T49：实现派发事务与预留移交

**文件：** `src/mewcode/teams/orchestration.py`, `tests/teams/test_orchestration.py`

**依赖：** T21, T27, T45, T47

**步骤：**
1. 记录 Worktree start OID，取得预留，持久化决定，调用 assign/outbox 并 flush 唤醒。
2. 处理已分配未启动、wake failed 和并发 reconcile，不重复 assign/run。

**验证：** 运行 `python -m pytest tests/teams/test_orchestration.py -k dispatch`，期望 task revision、outbox、driver 和容量各只变化一次。

## T50：保留审批计划/批准协议

**文件：** `src/mewcode/teams/orchestration.py`, `tests/teams/test_orchestration.py`

**依赖：** T49

**步骤：**
1. 审批成员首次 wake 只允许规划并到 AWAITING_APPROVAL。
2. Coordinator 不生成 plan_decision；拒绝/失效阻止实施与依赖派发，批准后复用既有 resume。

**验证：** 运行 `python -m pytest tests/teams/test_orchestration.py -k approval`，期望批准前副作用计数为零且请求/决定协议不变。

## T51：实现重派、取消、停止和转人工

**文件：** `src/mewcode/teams/orchestration.py`, `tests/teams/test_orchestration.py`

**依赖：** T49

**步骤：**
1. 在 task lock 和 journal 下执行四类 Lead 决定，调用既有 task/roster/scheduler 语义。
2. 保存 actor、revision、reason code 和结果，阻止并发第二动作。

**验证：** 运行 `python -m pytest tests/teams/test_orchestration.py -k decisions`，期望每类决定可审计且不会重复 stop/start。

## T52：冻结可信成果快照

**文件：** `src/mewcode/teams/orchestration.py`, `tests/teams/test_orchestration.py`

**依赖：** T33, T49

**步骤：**
1. 只在任务 completed、成员可信非活动终态且 scheduler/broker/Worktree 无运行时读取 end OID。
2. Git 任务冻结非空范围；NO_GIT 生成明确无 Git 影响的 pending review。

**验证：** 运行 `python -m pytest tests/teams/test_orchestration.py -k delivery_snapshot`，期望运行中/dirty/空范围/错误 owner 全被阻止。

## T53：实现结构化成果审阅与失效

**文件：** `src/mewcode/teams/orchestration.py`, `tests/teams/test_orchestration.py`

**依赖：** T52

**步骤：**
1. Lead 可 accepted/rejected/manual 并提供有界 evidence。
2. task revision、assignee、member、HEAD 或 commit range 变化自动使旧 accepted review 失效。

**验证：** 运行 `python -m pytest tests/teams/test_orchestration.py -k review`，期望审阅状态和所有失效条件通过。

## T54：实现确定性 reconcile

**文件：** `src/mewcode/teams/orchestration.py`, `tests/teams/test_orchestration.py`

**依赖：** T46-T53

**步骤：**
1. 按 run/task 稳定顺序推进 pending、派发、审批等待、成果冻结和阻塞终态。
2. 同一 snapshot 重复 reconcile 幂等，不调用模型或成员工具重放。

**验证：** 运行 `python -m pytest tests/teams/test_orchestration.py -k reconcile`，期望两次执行后的持久状态与副作用计数相同。

## T55：接入自动计划与集成

**文件：** `src/mewcode/teams/orchestration.py`, `src/mewcode/teams/integration.py`, `tests/teams/test_orchestration.py`

**依赖：** T42, T53, T54

**步骤：**
1. 所有任务成功/accepted 后把 run 标为 READY_TO_INTEGRATE。
2. auto 模式创建并运行唯一 batch；manual/failed/rejected 不自动启动。

**验证：** 运行 `python -m pytest tests/teams/test_orchestration.py -k auto_integrate`，期望唯一 batch、正确完成/阻塞状态。

## T56：实现协调循环生命周期

**文件：** `src/mewcode/teams/orchestration.py`, `tests/teams/test_orchestration.py`

**依赖：** T43, T54, T55

**步骤：**
1. `open` 先 recover 再启动使用注入等待器的单循环；`close` 取消并释放预留。
2. 无 busy polling、无真实长等待，关闭不删除成果或状态文件。

**验证：** 运行 `python -m pytest tests/teams/test_orchestration.py -k lifecycle`，期望 fake wait 时间线、关闭和恢复顺序正确。

## T57：定义 coordinator 工具 schema

**文件：** `src/mewcode/teams/tools.py`, `tests/teams/test_tools.py`

**依赖：** T44, T53, T55

**步骤：**
1. 定义 `team_coordinator` 和 `team_git` 的结构化 action/字段 schema。
2. 服务端严格拒绝未知字段、任意 command/argv/path 和无关 action 字段。

**验证：** 运行 `python -m pytest tests/teams/test_tools.py -k coordinator_schema`，期望有效输入通过、注入/未知字段被拒绝。

## T58：实现 TeamCoordinatorTool

**文件：** `src/mewcode/teams/tools.py`, `tests/teams/test_tools.py`

**依赖：** T56, T57

**步骤：**
1. 实现 status/decompose/reconcile/decide/review dispatch。
2. 要求 root Lead、enabled settings、attachment/fence；PLAN 只允许 status。

**验证：** 运行 `python -m pytest tests/teams/test_tools.py -k team_coordinator_tool`，期望 context/mode/guard/动作测试通过。

## T59：实现 TeamGitTool

**文件：** `src/mewcode/teams/tools.py`, `tests/teams/test_tools.py`

**依赖：** T43, T55, T57

**步骤：**
1. 实现 status/inspect/plan/integrate/recover，写动作只接受持久 ID。
2. PLAN 只允许 status/inspect；输出限制 diff/commit/诊断长度。

**验证：** 运行 `python -m pytest tests/teams/test_tools.py -k team_git_tool`，期望无任意 shell 接口且边界测试通过。

## T60：接入 settings 与 delivery 服务集合

**文件：** `src/mewcode/teams/coordinator.py`, `tests/teams/test_integration.py`

**依赖：** T11, T56

**步骤：**
1. `TeamCoordinatorServices` 增加可选 delivery，不影响旧构造器。
2. enabled attachment 按收敛→delivery recover/open→mailbox flush→scheduler restore 顺序启动。

**验证：** 运行 `python -m pytest tests/teams/test_integration.py -k coordinator_delivery_lifecycle`，期望顺序和异常清理通过。

## T61：实现关闭与租约丢失收敛

**文件：** `src/mewcode/teams/coordinator.py`, `tests/teams/test_integration.py`

**依赖：** T60

**步骤：**
1. 正常关闭和 lease lost 时先停止 delivery 新动作，再停止 scheduler/broker。
2. 保存可恢复边界，重复 close 幂等，不自动运行 Git 或成员工具。

**验证：** 运行 `python -m pytest tests/teams/test_integration.py -k 'delivery and (close or lease)'`，期望状态收敛和调用次数正确。

## T62：实现 Lead 工具视图双态裁剪

**文件：** `src/mewcode/teams/coordinator.py`, `tests/teams/test_integration.py`

**依赖：** T58, T59, T60

**步骤：**
1. 未启用/未挂载沿用现有工具合并。
2. enabled Lead 只保留基础 READ_ONLY，显式排除 file write/edit、run_command、agent、load_skill，再加入团队/coordinator 工具。

**验证：** 运行 `python -m pytest tests/teams/test_integration.py -k tool_view`，期望四种开关组合和挂载状态名称集合精确。

## T63：更新 enabled Lead prompt

**文件：** `src/mewcode/teams/coordinator.py`, `tests/teams/test_integration.py`

**依赖：** T62

**步骤：**
1. enabled prompt 明确只编排、审阅、停止/恢复和 Git 集成，不直接实现。
2. disabled prompt 保持 Phase 14A/14B 文本和行为。

**验证：** 运行 `python -m pytest tests/teams/test_integration.py -k lead_prompt`，期望 enabled/disabled additions 分离。

## T64：导出 Phase 14C 组件

**文件：** `src/mewcode/teams/__init__.py`

**依赖：** T58-T63

**步骤：**
1. 导出 settings、repository、delivery、integration、Git backend 和新工具。
2. 不引入循环导入或隐藏模式启动副作用。

**验证：** 运行 `python -c "import mewcode.teams"`，期望退出码 0。

## T65：在 CLI 解析双开关但保持关闭零副作用

**文件：** `src/mewcode/cli.py`, `tests/test_team_cli_integration.py`

**依赖：** T11, T64

**步骤：**
1. 主模式解析 settings；隐藏 pane/worker 模式不初始化 coordinator。
2. 任一开关关闭时不构造 repository/delivery/integration，不创建目录或后台 task。

**验证：** 运行 `python -m pytest tests/test_team_cli_integration.py -k coordinator_disabled`，期望四种关闭组合磁盘树与旧工具一致。

## T66：装配 enabled coordinator 服务

**文件：** `src/mewcode/cli.py`, `tests/test_team_cli_integration.py`

**依赖：** T60, T64, T65

**步骤：**
1. attachment 时延迟构造 CoordinatorRepository、Git backend、IntegrationService 和 TeamDeliveryCoordinator。
2. 注入现有 tasks/mailbox/approvals/roster/scheduler/worktree/binding/lease 能力。

**验证：** 运行 `python -m pytest tests/test_team_cli_integration.py -k coordinator_enabled_services`，期望只在 enabled attachment 构造一次且正确关闭。

## T67：注册 coordinator 工具并隔离普通会话

**文件：** `src/mewcode/cli.py`, `tests/test_team_cli_integration.py`

**依赖：** T62, T66

**步骤：**
1. enabled Lead 动态视图加入两个工具，global/普通 root 仍保持旧 registry。
2. 成员、普通子 Agent、技能 runtime 与未启用团队不继承 Lead 裁剪。

**验证：** 运行 `python -m pytest tests/test_team_cli_integration.py -k coordinator_tool_scope`，期望各运行身份工具集合符合 AC1/AC2/AC8。

## T68：补全工具输出编码与诊断脱敏

**文件：** `src/mewcode/teams/tools.py`, `tests/teams/test_tools.py`

**依赖：** T58, T59

**步骤：**
1. 为新 dataclass/enum/path/时间提供有界 JSON 编码。
2. 用 secret、完整 argv、原始异常和会话哨兵验证零泄漏。

**验证：** 运行 `python -m pytest tests/teams/test_tools.py -k coordinator_redaction`，期望所有哨兵在结果/metadata/错误中零命中。

## T69：实现进程内多任务 Git fake 端到端

**文件：** `tests/teams/test_coordinator_e2e.py`

**依赖：** T55, T66-T68

**步骤：**
1. 建立两个成员、依赖 DAG、审批/非审批任务、固定 Worktree 提交与自动审阅输入。
2. 执行拆解→派发→完成→审阅→拓扑 merge，并记录 journal/merge parents。

**验证：** 运行 `python -m pytest tests/teams/test_coordinator_e2e.py -k in_process`，期望唯一运行、稳定顺序和本地目标分支结果正确。

## T70：实现 Windows Terminal fake 端到端

**文件：** `tests/teams/test_coordinator_e2e.py`

**依赖：** T69

**步骤：**
1. 复用 Phase 14B fake host，完成终端成员派发、计划批准、结果和 Git 候选。
2. 确认 idle pane 不阻止可信终态，活动 run 会阻止候选。

**验证：** 运行 `python -m pytest tests/teams/test_coordinator_e2e.py -k windows_terminal`，期望端到端通过且无静默降级。

## T71：实现 tmux fake 端到端

**文件：** `tests/teams/test_coordinator_e2e.py`

**依赖：** T69

**步骤：**
1. 复用 tmux fake host，完成派发、断线恢复、结果、审阅和集成。
2. 验证宿主替代不改变 member/worktree/task 身份。

**验证：** 运行 `python -m pytest tests/teams/test_coordinator_e2e.py -k tmux`，期望端到端通过且结果只集成一次。

## T72：覆盖 Phase 14B readiness=false 边界

**文件：** `tests/teams/test_coordinator_e2e.py`

**依赖：** T70, T71

**步骤：**
1. 注入 readiness false，分别使用 Windows Terminal/tmux 成员尝试派发和候选。
2. 同一团队的 in_process 成员继续可用。

**验证：** 运行 `python -m pytest tests/teams/test_coordinator_e2e.py -k readiness_false`，期望终端明确拒绝、进程内成功、无降级。

## T73：覆盖并发 reconcile/stop/reassign/integrate

**文件：** `tests/teams/test_coordinator_e2e.py`

**依赖：** T69-T72

**步骤：**
1. 用 barrier 交错两个 reconcile、stop/reassign 和同分支 integrate。
2. 统计 task action、成员 run、容量、batch 和 Git merge 调用。

**验证：** 运行 `python -m pytest tests/teams/test_coordinator_e2e.py -k concurrency`，期望每任务一个活动动作/尝试、每分支一个 batch、容量不超限。

## T74：覆盖每个 Git journal 边界的崩溃端到端

**文件：** `tests/teams/test_coordinator_e2e.py`

**依赖：** T43, T69

**步骤：**
1. 在 precheck、merge、commit、postcheck、step/batch finalize 边界分别中断并重建服务。
2. 断言 retry/abort/confirm/manual 符合恢复矩阵。

**验证：** 运行 `python -m pytest tests/teams/test_coordinator_e2e.py -k crash_recovery`，期望 merge commit 数不重复、未知状态不继续。

## T75：覆盖远端与成果保护负向端到端

**文件：** `tests/teams/test_coordinator_e2e.py`, `tests/teams/test_coordinator_git.py`

**依赖：** T69

**步骤：**
1. 注册 fake remote 与未合并成员提交，运行成功、冲突和失败批次。
2. 断言无 push/fetch/remote/clean/worktree remove/branch delete，成员提交和目录仍存在。

**验证：** 运行 `python -m pytest tests/teams/test_coordinator_e2e.py tests/teams/test_coordinator_git.py -k 'remote or protect'`，期望所有保护断言通过。

## T76：运行 coordinator 专项测试

**文件：** 所有 Phase 14C 源码与测试

**依赖：** T02-T75

**步骤：**
1. 运行所有 coordinator 专项文件。
2. 修复失败，不删除断言、不增加无理由 skip/xfail。

**验证：** 运行 `python -m pytest tests/teams/test_coordinator_*.py tests/teams/test_orchestration.py`，期望全部通过。

## T77：运行团队与容量/CLI 受影响回归

**文件：** `tests/teams`, `tests/test_agent_capacity.py`, `tests/test_team_cli_integration.py`

**依赖：** T76

**步骤：**
1. 运行全部团队、容量和 CLI 集成测试。
2. 修复 Phase 14A/14B、普通子 Agent、审批、邮箱和会话恢复回归。

**验证：** 运行 `python -m pytest tests/teams tests/test_agent_capacity.py tests/test_team_cli_integration.py`，期望全部通过。

## T78：运行编译、完整测试与 diff 检查

**文件：** 整个仓库

**依赖：** T77

**步骤：**
1. 运行 compileall、完整 pytest 和 diff whitespace 检查。
2. 保存测试数、耗时和退出码。

**验证：** 运行 `python -m compileall -q src/mewcode`、`python -m pytest`、`git diff --check`，期望全部退出码 0。

## T79：执行安装与 CLI 冒烟

**文件：** 构建与 CLI 入口

**依赖：** T78

**步骤：**
1. 在临时 venv 中执行无依赖可编辑安装和 `mewcode --help`。
2. 冒烟普通启动装配、隐藏模式帮助和 `import mewcode.teams`；不连接真实模型。

**验证：** 所有安装、帮助和导入命令退出码为 0，普通帮助不泄露隐藏入口。

## T80：完成 checklist 验收与证据回填

**文件：** `docs/phase-14c-team-coordinator/checklist.md`

**依赖：** T78, T79

**步骤：**
1. 按 checklist 逐项执行 AC1–AC10、集成、并发、崩溃和端到端验证。
2. 只勾选有实际命令输出或可复现观察证据的项目，记录任何平台限制。

**验证：** 检查 checklist 每条 AC 都有关联证据，所有失败项已修复重跑，且最终 `git diff --check` 退出码 0。

## 执行顺序

```text
T01 → T02
  ├─ T03 → T04–T09 ─┬─ T16–T22 ───────────────┐
  │                  ├─ T23–T24 ───────────────┤
  │                  └─ T29–T37 → T38–T43 ─────┤
  ├─ T10 → T11–T13 ────────────────────────────┤
  ├─ T14 → T15 → T18–T22 ──────────────────────┤
  └─ T25 → T26–T28 ────────────────────────────┤
                                                 ↓
                          T44–T56 → T57–T64 → T65–T68
                                                 ↓
                                      T69–T75 → T76 → T77
                                                 ↓
                                      T78 → T79 → T80
```

T04–T09、T10–T13、T14–T22、T25–T28 和 T29–T37 在依赖满足后可按文件冲突情况交错执行；同一文件上的任务保持编号顺序。实现阶段按逻辑组提交，不包含用户既有的 Phase 14A 文档迁移改动。
