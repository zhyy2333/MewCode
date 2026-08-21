# Phase 14A 持久团队核心 Tasks

> 本文只拆解已批准的 `spec.md` 和 `plan.md`。每个任务目标粒度为 2–5 分钟；每项完成后立即运行对应验证，再进入依赖它的任务。四份文档全部批准前不得执行这些实现任务。

## 文件清单

### 新建实现文件

| 操作 | 文件 | 职责 |
|---|---|---|
| 新建 | `src/mewcode/agent/capacity.py` | 普通子 Agent 与团队成员共享的进程级容量池 |
| 新建 | `src/mewcode/teams/__init__.py` | 团队领域公共导出 |
| 新建 | `src/mewcode/teams/models.py` | 团队、成员、任务、审批、消息、队列、租约和运行结果模型 |
| 新建 | `src/mewcode/teams/paths.py` | 名称策略及用户团队目录布局 |
| 新建 | `src/mewcode/teams/codec.py` | 团队持久数据的严格编解码 |
| 新建 | `src/mewcode/teams/repository.py` | 状态快照、CAS、原子写及操作日志 |
| 新建 | `src/mewcode/teams/domain.py` | 无 I/O 状态机及领域转换 |
| 新建 | `src/mewcode/teams/leases.py` | Lead 心跳租约、过期检测和 fencing |
| 新建 | `src/mewcode/teams/repository_binding.py` | Git 仓库证明、验证和重新关联 |
| 新建 | `src/mewcode/teams/tasks.py` | 共享任务服务 |
| 新建 | `src/mewcode/teams/protocols.py` | 七种固定消息协议及方向约束 |
| 新建 | `src/mewcode/teams/mailbox.py` | 邮箱日志、锁、广播、回执及 outbox |
| 新建 | `src/mewcode/teams/approvals.py` | 计划审批、失效及副作用 permit |
| 新建 | `src/mewcode/teams/roster.py` | 成员创建、角色冻结、生命周期和安全移除 |
| 新建 | `src/mewcode/teams/sessions.py` | 长期成员会话和投递检查点 |
| 新建 | `src/mewcode/teams/inbound.py` | Lead/成员邮箱的安全边界注入 |
| 新建 | `src/mewcode/teams/policy.py` | 成员工具裁剪和审批包装 |
| 新建 | `src/mewcode/teams/runtime.py` | 单次长期成员 Agent 运行 |
| 新建 | `src/mewcode/teams/scheduler.py` | 持久 FIFO、唤醒合并及运行驱动 |
| 新建 | `src/mewcode/teams/tools.py` | 四个固定团队工具 |
| 新建 | `src/mewcode/teams/coordinator.py` | 当前团队、Lead 升格、心跳及关闭编排 |

### 修改实现文件

| 操作 | 文件 | 改动位置 |
|---|---|---|
| 修改 | `src/mewcode/locking.py` | 增加带令牌元数据、旧锁判断和有界重试的锁包装 |
| 修改 | `src/mewcode/agent/__init__.py` | 导出容量及入站边界公共类型 |
| 修改 | `src/mewcode/agent/runner.py` | 轮询入站消息、原子提交投递 ID、支持安全暂停 |
| 修改 | `src/mewcode/providers/base.py` | 增加 `MessageKind.TEAM_INBOUND` |
| 修改 | `src/mewcode/continuity/session_models.py` | 记录已提交的入站消息 ID |
| 修改 | `src/mewcode/continuity/session_codec.py` | 编解码 `inbound_history` 记录 |
| 修改 | `src/mewcode/continuity/session_repository.py` | 原子提交入站消息与 ID，恢复检查点 |
| 修改 | `src/mewcode/tools/base.py` | 为工具结果增加通用安全暂停元数据 |
| 修改 | `src/mewcode/tools/__init__.py` | 导出新增工具基础类型 |
| 修改 | `src/mewcode/worktrees/__init__.py` | 导出 Worktree 拥有者及新生命周期入口 |
| 修改 | `src/mewcode/worktrees/models.py` | 增加 `WorktreePurpose`、`WorktreeOwner` 及持久拥有者字段 |
| 修改 | `src/mewcode/worktrees/paths.py` | 增加团队成员 Worktree 名称生成 |
| 修改 | `src/mewcode/worktrees/records.py` | 新旧 Worktree 记录兼容编解码 |
| 修改 | `src/mewcode/worktrees/lifecycle.py` | 增加 `create_or_recover()`、`enter()` 和 `suspend()` |
| 修改 | `src/mewcode/worktrees/janitor.py` | 跳过有效长期成员 Worktree |
| 修改 | `src/mewcode/subagents/tasks.py` | 接入共享容量池并保持满载立即失败 |
| 修改 | `src/mewcode/subagents/workspace_runtime.py` | 抽取可供长期成员复用的工作区装配 |
| 修改 | `src/mewcode/conversation.py` | 动态组合 Skill/Team 运行视图及 Lead 入站源 |
| 修改 | `src/mewcode/cli.py` | 装配容量池和团队服务，注册工具并按序关闭 |
| 修改 | `README.md` | 记录 Phase 14A 使用方式、持久目录和范围边界 |

### 新建测试文件

| 操作 | 文件 | 覆盖范围 |
|---|---|---|
| 新建 | `tests/teams/__init__.py` | 团队测试包 |
| 新建 | `tests/teams/helpers.py` | 可替换时钟、ID、锁、Git、运行时和状态工厂 |
| 新建 | `tests/teams/test_models.py` | 模型、限制及状态枚举 |
| 新建 | `tests/teams/test_paths_codec.py` | 名称、路径和严格编解码 |
| 新建 | `tests/teams/test_repository.py` | 状态原子提交、CAS、损坏隔离和 journal |
| 新建 | `tests/teams/test_leases.py` | Lead 独占、续期、过期及 fencing |
| 新建 | `tests/teams/test_repository_binding.py` | Git 证明、跨仓库拒绝及重新关联 |
| 新建 | `tests/teams/test_domain_tasks.py` | 成员状态机、任务、依赖、队列及 outbox |
| 新建 | `tests/teams/test_mailbox_protocols.py` | 协议、邮箱、广播、锁、去重及回执 |
| 新建 | `tests/teams/test_approvals.py` | 计划审批、失效和副作用竞态 |
| 新建 | `tests/teams/test_sessions_inbound.py` | 长期会话、消息注入和崩溃窗口 |
| 新建 | `tests/teams/test_roster.py` | 成员创建、刷新、停止、恢复和移除 |
| 新建 | `tests/teams/test_scheduler.py` | FIFO、唤醒合并、容量及停止竞态 |
| 新建 | `tests/teams/test_runtime.py` | 成员运行资源、结果映射和故障隔离 |
| 新建 | `tests/teams/test_tools.py` | 固定 schema、可见性及动作级授权 |
| 新建 | `tests/teams/test_integration.py` | 团队任务、邮箱、审批和成员恢复集成 |
| 新建 | `tests/test_agent_capacity.py` | 普通子 Agent 与团队成员共享容量 |
| 新建 | `tests/test_team_cli_integration.py` | CLI 装配、跨应用恢复及关闭顺序 |

### 修改现有测试文件

| 操作 | 文件 | 回归范围 |
|---|---|---|
| 修改 | `tests/test_locking.py` | 旧锁、有界重试和活动锁保护 |
| 修改 | `tests/test_agent_runner.py` | 入站边界和安全暂停 |
| 修改 | `tests/test_providers.py` | `TEAM_INBOUND` Provider 编码兼容 |
| 修改 | `tests/test_session_codec.py` | `inbound_history` 编解码 |
| 修改 | `tests/test_session_repository.py` | 原子入站提交和恢复去重 |
| 修改 | `tests/worktrees/test_paths.py` | 团队成员名称及路径安全 |
| 修改 | `tests/worktrees/test_records.py` | Worktree 新旧记录兼容 |
| 修改 | `tests/worktrees/test_lifecycle.py` | 长期成员恢复、进入和 suspend |
| 修改 | `tests/worktrees/test_janitor.py` | 长期目录清理豁免 |
| 修改 | `tests/worktrees/test_integration.py` | 普通 Worktree 行为兼容 |
| 修改 | `tests/test_subagent_tasks.py` | 共享容量下的立即失败与释放 |
| 修改 | `tests/test_subagent_worktree.py` | 抽取工作区装配后的行为兼容 |
| 修改 | `tests/test_conversation.py` | 动态 Team 视图与普通模式兼容 |
| 修改 | `tests/test_plan_mode.py` | PLAN 模式下团队混合工具动作门禁 |

## 基础模型、路径与持久化

## T01：建立团队测试骨架

**文件：** `tests/teams/__init__.py`、`tests/teams/helpers.py`、`tests/teams/test_models.py`  
**依赖：** 无

**步骤：**
1. 建立 `tests.teams` 包及最小合法团队状态工厂。
2. 提供固定 UTC 时钟和确定性 ID 生成器，测试不得真实等待或访问网络。
3. 添加一个帮助器导入冒烟测试。

**验证：** 运行 `python -m pytest tests/teams/test_models.py -q`，期望帮助器冒烟测试通过。

## T02：定义团队枚举

**文件：** `src/mewcode/teams/models.py`、`tests/teams/test_models.py`  
**依赖：** T01

**步骤：**
1. 定义 `TeamMemberStatus`、`TeamMemberBackend`、`TeamTaskStatus`、`PlanApprovalStatus`、`PlanDecision`、`TeamProtocol` 和 `MemberWakeReason`。
2. 固定 Phase 14A 仅有 `IN_PROCESS` 后端和七种协议值。
3. 测试未知枚举值被拒绝。

**验证：** 运行 `python -m pytest tests/teams/test_models.py -q -k enum`，期望枚举值与 `plan.md` 完全一致。

## T03：定义名称、参与者和诊断模型

**文件：** `src/mewcode/teams/models.py`、`tests/teams/test_models.py`  
**依赖：** T02

**步骤：**
1. 增加 `TeamName`、`TeamActor`、`TeamSummary` 和 `TeamDiagnostic`。
2. 使用稳定 ID 作为内部身份，名称只保留展示值和规范键。
3. 对诊断文本及公开标识设置有界输出。

**验证：** 运行 `python -m pytest tests/teams/test_models.py -q -k 'name or actor or diagnostic'`，期望值对象不可变且有界。

## T04：定义团队清单、冻结角色和成员模型

**文件：** `src/mewcode/teams/models.py`、`tests/teams/test_models.py`  
**依赖：** T03

**步骤：**
1. 实现 `RepositoryBinding`、`TeamManifest`、`FrozenRoleSnapshot` 和 `TeamMemberRecord`。
2. 保存解析后的 Profile、工具名、权限模式、规则及版本指纹，不保存 `inherit`。
3. 校验时间有时区、路径为绝对路径、运行代际非负。

**验证：** 运行 `python -m pytest tests/teams/test_models.py -q -k 'manifest or role or member'`，期望合法记录可构造、非法记录被拒绝。

## T05：定义任务和审批模型

**文件：** `src/mewcode/teams/models.py`、`tests/teams/test_models.py`  
**依赖：** T04

**步骤：**
1. 实现 `TeamTask`、`TeamTaskView` 和 `PlanApprovalRecord`。
2. 加入任务修订、`approval_epoch`、计划版本和完整时间字段。
3. 校验标题、说明、依赖数和结果大小限制。

**验证：** 运行 `python -m pytest tests/teams/test_models.py -q -k 'task or approval'`，期望边界值通过、超限值失败。

## T06：定义邮箱、队列、状态和租约模型

**文件：** `src/mewcode/teams/models.py`、`tests/teams/test_models.py`  
**依赖：** T05

**步骤：**
1. 实现 `MailboxRegistration`、`TeamMessage`、邮箱记录、`MemberQueueEntry` 和 `TeamOutboxEntry`。
2. 实现 `TeamState`、`TeamLeadLeaseRecord`、`TeamLeadLease`、`TeamAttachment`、成员会话和入站批次模型。
3. 固定 `schema_version`、UTC 时间和不可变集合表示。

**验证：** 运行 `python -m pytest tests/teams/test_models.py -q -k 'message or queue or state or lease or session'`，期望模型字段及默认未读语义正确。

## T07：集中实现领域限制校验

**文件：** `src/mewcode/teams/models.py`、`tests/teams/test_models.py`  
**依赖：** T06

**步骤：**
1. 集中定义团队、成员、任务、消息和花名册数量上限。
2. 拒绝 NaN、无时区时间、空摘要、多行摘要和超限正文。
3. 保证所有错误只暴露安全字段和有界文本。

**验证：** 运行 `python -m pytest tests/teams/test_models.py -q -k limits`，期望 N2–N4 与 N34 的边界测试通过。

## T08：实现安全名称策略

**文件：** `src/mewcode/teams/paths.py`、`tests/teams/test_paths_codec.py`  
**依赖：** T03

**步骤：**
1. 实现 `TeamNamePolicy` 的 Unicode 规范化、大小写折叠和最大长度校验。
2. 目录段仅接受安全 ASCII 子集，拒绝 Windows 保留名称、路径分隔符和点路径。
3. 测试大小写别名和规范化别名产生同一规范键。

**验证：** 运行 `python -m pytest tests/teams/test_paths_codec.py -q -k name`，期望合法名称稳定、危险名称在落盘前失败。

## T09：实现团队路径布局

**文件：** `src/mewcode/teams/paths.py`、`tests/teams/test_paths_codec.py`  
**依赖：** T08

**步骤：**
1. 实现 `TeamPaths.for_user()` 及状态、租约、锁、邮箱、会话和事务目录属性。
2. 为成员邮箱和会话提供只接受已验证名称/ID 的路径方法。
3. 在解析后检查路径仍位于团队根内，并拒绝链接或重解析点逃逸。

**验证：** 运行 `python -m pytest tests/teams/test_paths_codec.py -q -k path`，期望跨目录、链接和大小写替换均被拒绝。

## T10：增加有界重试锁

**文件：** `src/mewcode/locking.py`、`tests/test_locking.py`  
**依赖：** T01

**步骤：**
1. 在现有 advisory lock 上增加令牌、创建时间和持有者元数据。
2. 实现可注入时钟/等待器的 5 秒有界重试和 30 秒旧锁判断。
3. 仅在 OS 锁实际未被持有时回收旧锁文件。

**验证：** 运行 `python -m pytest tests/test_locking.py -q`，期望活动锁不被回收、旧文件可接管、超时明确失败。

## T11：实现严格标量和模型编解码原语

**文件：** `src/mewcode/teams/codec.py`、`tests/teams/test_paths_codec.py`  
**依赖：** T07

**步骤：**
1. 实现字符串、整数、布尔值、UTC 时间、路径、枚举和严格对象字段解码器。
2. 拒绝重复键、未知键、错误类型、NaN 和未知 `schema_version`。
3. 为模型编码提供确定字段顺序。

**验证：** 运行 `python -m pytest tests/teams/test_paths_codec.py -q -k strict`，期望非法 JSON 形态全部拒绝且不改写源文件。

## T12：实现团队状态和租约编解码

**文件：** `src/mewcode/teams/codec.py`、`tests/teams/test_paths_codec.py`  
**依赖：** T11

**步骤：**
1. 实现清单、角色、成员、任务、审批、队列、outbox 和完整 `TeamState` 的往返编码。
2. 实现 Lead 租约及仓库证明记录的往返编码。
3. 解码后调用跨字段一致性校验入口。

**验证：** 运行 `python -m pytest tests/teams/test_paths_codec.py -q -k 'state or lease or binding'`，期望合法快照逐字段往返一致。

## T13：实现追加记录编解码

**文件：** `src/mewcode/teams/codec.py`、`tests/teams/test_paths_codec.py`  
**依赖：** T12

**步骤：**
1. 实现邮箱消息、已读回执、成员会话扩展和 provisioning/relink journal 的 JSONL 编解码。
2. 只容忍文件尾部未完成记录，中间损坏必须停止并保留现场。
3. 为每类记录校验固定版本和严格字段集合。

**验证：** 运行 `python -m pytest tests/teams/test_paths_codec.py -q -k 'jsonl or journal or truncated'`，期望尾部截断可诊断恢复、中间损坏被拒绝。

## T14：实现团队仓库的创建、枚举和加载

**文件：** `src/mewcode/teams/repository.py`、`tests/teams/test_repository.py`  
**依赖：** T09、T12

**步骤：**
1. 实现 `TeamRepository.list()`、`create()` 和 `load()`。
2. 用临时文件、flush/fsync 和原子替换提交状态快照。
3. 强制用户范围 128 个团队上限及名称唯一性。

**验证：** 运行 `python -m pytest tests/teams/test_repository.py -q -k 'create or list or load'`，期望重启式重建仓库对象后仍得到同一状态。

## T15：实现团队状态 CAS 与 fence 校验

**文件：** `src/mewcode/teams/repository.py`、`tests/teams/test_repository.py`  
**依赖：** T10、T14

**步骤：**
1. 实现 `compare_and_swap()`，在状态锁内重新加载当前修订和 Lead fence。
2. 完整校验候选状态后只写入 `revision + 1`。
3. 返回修订冲突及当前版本，拒绝旧代际写入。

**验证：** 运行 `python -m pytest tests/teams/test_repository.py -q -k 'cas or fence or revision'`，期望并发写只有合法候选成功。

## T16：实现纯转换重试和操作日志存储

**文件：** `src/mewcode/teams/repository.py`、`tests/teams/test_repository.py`  
**依赖：** T13、T15

**步骤：**
1. 实现 `TeamMutationRunner` 对团队级 CAS 冲突的纯转换重放。
2. 保持调用方传入的任务 `expected_revision` 为严格前置条件。
3. 实现 provisioning/relink journal 的创建、阶段推进、恢复枚举和完成删除。

**验证：** 运行 `python -m pytest tests/teams/test_repository.py -q -k 'mutation or journal'`，期望内部冲突可重试、过期任务修订仍失败。

## T17：实现 Lead 租约获取与排他性

**文件：** `src/mewcode/teams/leases.py`、`tests/teams/test_leases.py`  
**依赖：** T10、T12、T14

**步骤：**
1. 实现 `TeamLeaseService.acquire()` 的短锁临界区。
2. 有效租约存在时拒绝第二个 Lead，不得抢占。
3. 新租约生成稳定 `lease_id` 并递增 `generation`。

**验证：** 运行 `python -m pytest tests/teams/test_leases.py -q -k acquire`，期望并发获取只有一个成功者。

## T18：实现租约续期、过期接管和 fencing

**文件：** `src/mewcode/teams/leases.py`、`tests/teams/test_leases.py`  
**依赖：** T17

**步骤：**
1. 实现 `renew()`、`validate()` 和幂等 `release()`。
2. 使用 10 秒续期间隔、60 秒过期阈值及接管前二次确认。
3. 验证旧 Lead 在新代际产生后不能续期或提交状态。

**验证：** 运行 `python -m pytest tests/teams/test_leases.py -q -k 'renew or expire or fence'`，期望替代时钟无需真实等待即可覆盖所有边界。

## T19：实现仓库证明创建与验证

**文件：** `src/mewcode/teams/repository_binding.py`、`tests/teams/test_repository_binding.py`  
**依赖：** T12、T14

**步骤：**
1. 实现 `TeamRepositoryBindingService.create_binding()`，在 Git common dir 和团队目录保存同一随机证明。
2. 实现 `verify()`，同时核验规范仓库身份、证明、主工作区和 Git 指针。
3. 明确拒绝非 Git 目录、其他仓库及被替换的 Git 元数据。

**验证：** 运行 `python -m pytest tests/teams/test_repository_binding.py -q -k 'create or verify'`，期望合法仓库通过、伪造或跨仓库绑定失败。

## T20：实现显式仓库重新关联

**文件：** `src/mewcode/teams/repository_binding.py`、`src/mewcode/teams/repository.py`、`tests/teams/test_repository_binding.py`  
**依赖：** T16、T19

**步骤：**
1. 实现 `relink()`，验证持久证明后检查成员 Worktree、临时分支和 Git 指针。
2. 用 relink journal 分阶段更新路径记录，完成前保持团队不可挂载。
3. 覆盖崩溃后幂等继续和证明不匹配时保留现场。

**验证：** 运行 `python -m pytest tests/teams/test_repository_binding.py -q -k relink`，期望移动后的同一仓库可恢复，其他仓库不能接管。

## Worktree 与纯领域规则

## T21：扩展 Worktree 拥有者模型

**文件：** `src/mewcode/worktrees/models.py`、`src/mewcode/worktrees/records.py`、`tests/worktrees/test_records.py`  
**依赖：** T04

**步骤：**
1. 增加 `WorktreePurpose` 和 `WorktreeOwner`，并把拥有者信息写入 `WorktreeRecord`。
2. 将旧 `task_id` 记录兼容映射为 `SUBAGENT_TASK`，团队成员使用稳定 `member_id`。
3. 对未知用途、拥有者替换和不兼容版本明确失败。

**验证：** 运行 `python -m pytest tests/worktrees/test_records.py -q`，期望旧记录仍可读取，新记录完整往返拥有者字段。

## T22：增加团队成员 Worktree 名称

**文件：** `src/mewcode/worktrees/paths.py`、`tests/worktrees/test_paths.py`  
**依赖：** T08、T21

**步骤：**
1. 实现 `WorktreeNameFactory.for_team_member(team_id, member_id)`。
2. 生成稳定、跨平台且与普通子 Agent 不冲突的名称。
3. 继续应用现有根目录、链接和路径长度检查。

**验证：** 运行 `python -m pytest tests/worktrees/test_paths.py -q -k team`，期望相同成员名称稳定、不同拥有者不碰撞、危险路径被拒绝。

## T23：增加长期 Worktree 恢复、进入和 suspend

**文件：** `src/mewcode/worktrees/lifecycle.py`、`src/mewcode/worktrees/__init__.py`、`tests/worktrees/test_lifecycle.py`  
**依赖：** T21、T22

**步骤：**
1. 实现 `create_or_recover()`，验证记录、marker、Git 指针及稳定拥有者。
2. 实现 `enter()`，同一成员目录同时只允许一个活动租约。
3. 实现 `suspend()`，释放占用但保持目录、分支和 READY 记录。

**验证：** 运行 `python -m pytest tests/worktrees/test_lifecycle.py -q -k 'recover or enter or suspend'`，期望跨生命周期恢复同一目录且并发进入被拒绝。

## T24：保护长期成员 Worktree 不被 Janitor 清理

**文件：** `src/mewcode/worktrees/janitor.py`、`tests/worktrees/test_janitor.py`  
**依赖：** T23

**步骤：**
1. 让 Janitor 根据 `purpose`、`persistent` 和有效花名册证明识别长期成员目录。
2. 对有效成员跳过 TTL 清理，对失去证明的目录只报告诊断而不强删。
3. 保持普通子 Agent Worktree 的既有过期策略。

**验证：** 运行 `python -m pytest tests/worktrees/test_janitor.py -q`，期望团队成员目录被保护、普通过期目录仍按旧规则处理。

## T25：抽取通用 Worktree 工作区装配

**文件：** `src/mewcode/subagents/workspace_runtime.py`、`tests/test_subagent_worktree.py`  
**依赖：** T23

**步骤：**
1. 将工作区文件工具、Hook、MCP、Context 和指令加载的公共装配从子 Agent 专属参数中抽出。
2. 保留普通子 Agent 适配器及原有隔离提示。
3. 暴露团队运行时可传入固定 Worktree、角色和额外工具的构造入口。

**验证：** 运行 `python -m pytest tests/test_subagent_worktree.py -q`，期望现有子 Agent 工作区装配测试保持通过。

## T26：验证普通 Worktree 全量兼容

**文件：** `tests/worktrees/test_integration.py`、`tests/worktrees/test_records.py`、`tests/worktrees/test_lifecycle.py`  
**依赖：** T21–T25

**步骤：**
1. 增加旧格式记录、普通任务 create/enter/exit 和清理路径回归用例。
2. 验证普通任务仍执行原有成果保护与退出策略。
3. 验证新 `suspend()` 不会被普通任务路径意外调用。

**验证：** 运行 `python -m pytest tests/worktrees tests/test_subagent_worktree.py -q`，期望全部 Worktree 回归通过。

## T27：实现团队聚合一致性校验

**文件：** `src/mewcode/teams/domain.py`、`tests/teams/test_domain_tasks.py`  
**依赖：** T06

**步骤：**
1. 实现 `validate_team_state()`，检查清单、注册表、成员、任务、审批、队列和 outbox 的交叉引用。
2. 检查一个成员最多一个当前任务、一个成员最多一个未完成队列项。
3. 拒绝未知参与者、重复规范名称和已移除成员引用。

**验证：** 运行 `python -m pytest tests/teams/test_domain_tasks.py -q -k consistency`，期望所有半状态候选在提交前被拒绝。

## T28：实现成员状态机

**文件：** `src/mewcode/teams/domain.py`、`tests/teams/test_domain_tasks.py`  
**依赖：** T27

**步骤：**
1. 定义创建、排队、运行、等待审批、空闲、停止、中断和失败之间的合法转换。
2. 校验 `active_run_id`、`current_task_id` 和 `run_generation` 与状态匹配。
3. 返回新不可变状态，不原地修改输入。

**验证：** 运行 `python -m pytest tests/teams/test_domain_tasks.py -q -k member_state`，期望合法转换通过、非法跳转保持原状态。

## T29：实现名称注册表转换

**文件：** `src/mewcode/teams/domain.py`、`tests/teams/test_domain_tasks.py`  
**依赖：** T27

**步骤：**
1. 实现 Lead 和成员注册、解析及注销纯转换。
2. 保证规范名称唯一并与邮箱一一对应。
3. 拒绝未知、已移除和跨团队参与者。

**验证：** 运行 `python -m pytest tests/teams/test_domain_tasks.py -q -k registry`，期望名称查找稳定且注销后不可投递。

## T30：实现任务创建、读取和成员权限规则

**文件：** `src/mewcode/teams/domain.py`、`tests/teams/test_domain_tasks.py`  
**依赖：** T27

**步骤：**
1. 实现任务创建及 `TeamTaskView` 阻塞状态计算。
2. 实现 Lead、普通成员、任务负责人的动作权限矩阵。
3. 保证成员只能修改允许的未开始任务或本人任务进度。

**验证：** 运行 `python -m pytest tests/teams/test_domain_tasks.py -q -k 'create_task or authorization'`，期望合法动作成功、越权动作失败。

## T31：实现任务依赖图校验

**文件：** `src/mewcode/teams/domain.py`、`tests/teams/test_domain_tasks.py`  
**依赖：** T30

**步骤：**
1. 拒绝未知依赖、自依赖和重复依赖。
2. 在写入前检测任意长度依赖环。
3. 计算失败/取消/未完成依赖造成的阻塞及下游重新可运行状态。

**验证：** 运行 `python -m pytest tests/teams/test_domain_tasks.py -q -k dependency`，期望合法链、环和终态阻塞场景通过。

## T32：实现任务原子领取、指派和重新指派

**文件：** `src/mewcode/teams/domain.py`、`tests/teams/test_domain_tasks.py`  
**依赖：** T28、T31

**步骤：**
1. 实现成员领取未指派且依赖满足的任务。
2. 实现 Lead 指派及重新指派，并同步成员 `current_task_id`。
3. 重新指派时递增 `approval_epoch` 并生成确定 outbox 事件。

**验证：** 运行 `python -m pytest tests/teams/test_domain_tasks.py -q -k 'claim or assign'`，期望并发候选中只有一个修订可提交且始终单负责人。

## T33：实现任务状态转换和删除约束

**文件：** `src/mewcode/teams/domain.py`、`tests/teams/test_domain_tasks.py`  
**依赖：** T31、T32

**步骤：**
1. 实现 PENDING、IN_PROGRESS、COMPLETED、FAILED 和 CANCELLED 的合法转换。
2. 终态时保存结果、清除当前任务并生成 Lead 状态通知。
3. 拒绝删除进行中或仍被依赖的任务。

**验证：** 运行 `python -m pytest tests/teams/test_domain_tasks.py -q -k 'transition or delete'`，期望状态、时间、下游可运行性和删除约束一致。

## T34：实现审批领域转换

**文件：** `src/mewcode/teams/domain.py`、`tests/teams/test_approvals.py`  
**依赖：** T28、T32

**步骤：**
1. 创建按成员、任务、`approval_epoch` 和 `plan_version` 绑定的申请。
2. 实现批准、带反馈驳回、新版本失效及任务变更失效。
3. 未知、损坏或不匹配状态统一按未批准处理。

**验证：** 运行 `python -m pytest tests/teams/test_approvals.py -q -k domain`，期望旧任务、旧计划或旧 epoch 的批准无效。

## T35：实现队列合并和 outbox 纯转换

**文件：** `src/mewcode/teams/domain.py`、`tests/teams/test_domain_tasks.py`  
**依赖：** T28、T29

**步骤：**
1. 实现持久 FIFO 序号分配、同成员队列项合并和安全出队。
2. 合并后保留每个唯一消息 ID，不重复启动成员。
3. 实现 outbox 新增、投递成功和错误记录转换。

**验证：** 运行 `python -m pytest tests/teams/test_domain_tasks.py -q -k 'queue or outbox'`，期望 FIFO、去重及部分失败状态可重放。

## 任务、协议、邮箱与审批服务

## T36：实现任务创建和查询服务

**文件：** `src/mewcode/teams/tasks.py`、`tests/teams/test_domain_tasks.py`  
**依赖：** T15、T30、T31

**步骤：**
1. 实现 `TeamTaskService.create()`、`get()` 和 `list()`。
2. 绑定当前 `TeamActor` 并通过 `TeamMutationRunner` 提交纯领域转换。
3. 支持按状态和负责人过滤，返回计算后的 `TeamTaskView`。

**验证：** 运行 `python -m pytest tests/teams/test_domain_tasks.py -q -k task_service_read`，期望 Lead 和成员只看到本团队一致快照。

## T37：实现任务更新和删除服务

**文件：** `src/mewcode/teams/tasks.py`、`tests/teams/test_domain_tasks.py`  
**依赖：** T33、T36

**步骤：**
1. 实现带 `expected_revision` 的 `update()` 和 `delete()`。
2. 将过期修订冲突返回为含当前任务版本的稳定错误。
3. 任务依赖变化时在同一事务使批准失效。

**验证：** 运行 `python -m pytest tests/teams/test_domain_tasks.py -q -k 'service_update or service_delete or stale_revision'`，期望过期写不覆盖新状态。

## T38：实现任务指派和领取服务

**文件：** `src/mewcode/teams/tasks.py`、`tests/teams/test_domain_tasks.py`  
**依赖：** T32、T36

**步骤：**
1. 实现 `assign()` 和 `claim()` 的动作授权及修订检查。
2. 在同一团队状态事务中提交任务、成员关联、审批失效和 outbox。
3. 并发领取冲突时返回当前任务负责人及修订。

**验证：** 运行 `python -m pytest tests/teams/test_domain_tasks.py -q -k task_service_assignment`，期望单负责人和原子 outbox 断言通过。

## T39：实现任务终态通知服务

**文件：** `src/mewcode/teams/tasks.py`、`tests/teams/test_domain_tasks.py`  
**依赖：** T33、T36

**步骤：**
1. 实现 `transition()` 及有界结果保存。
2. 完成、失败或取消时生成给 Lead 的 `task_status` outbox。
3. 保证成员自然结束路径不能调用任务完成转换。

**验证：** 运行 `python -m pytest tests/teams/test_domain_tasks.py -q -k task_service_transition`，期望显式转换才改变任务终态。

## T40：实现七种协议载荷解析

**文件：** `src/mewcode/teams/protocols.py`、`tests/teams/test_mailbox_protocols.py`  
**依赖：** T06、T11

**步骤：**
1. 为 `text`、`task_assignment`、`task_status`、`plan_request`、`plan_decision`、`member_idle` 和 `stop_request` 实现严格解析器。
2. 拒绝未知字段、缺失字段、错误类型和超限载荷。
3. 将解析结果表示为固定协议 union，不保留任意字典。

**验证：** 运行 `python -m pytest tests/teams/test_mailbox_protocols.py -q -k payload`，期望七种合法载荷通过、所有畸形载荷失败。

## T41：实现协议方向与状态准备

**文件：** `src/mewcode/teams/protocols.py`、`tests/teams/test_mailbox_protocols.py`  
**依赖：** T29、T34、T40

**步骤：**
1. 实现 `TeamProtocolRouter.prepare()` 的发送方、目标和引用对象校验。
2. 固定计划申请、审批决定、空闲通知和停止请求的合法方向。
3. 为需要领域变化的协议生成与消息同事务提交的 `ProtocolTransition`。

**验证：** 运行 `python -m pytest tests/teams/test_mailbox_protocols.py -q -k direction`，期望伪造 Lead、成员或系统方向全部失败且不产生 outbox。

## T42：实现邮箱追加存储和重放

**文件：** `src/mewcode/teams/mailbox.py`、`tests/teams/test_mailbox_protocols.py`  
**依赖：** T10、T13

**步骤：**
1. 实现 `TeamMailboxStore` 在收件人级锁内追加完整 JSONL 记录。
2. 使用 `message_id` 建立去重索引，重试已存在消息时返回原结果。
3. 重放消息和回执，按提交顺序计算最终未读视图。

**验证：** 运行 `python -m pytest tests/teams/test_mailbox_protocols.py -q -k mailbox_store`，期望并发消息完整、重复 ID 只出现一次、重启后已读状态一致。

## T43：实现点对点发送、分页和已读

**文件：** `src/mewcode/teams/mailbox.py`、`tests/teams/test_mailbox_protocols.py`  
**依赖：** T29、T41、T42

**步骤：**
1. 实现 `TeamMailboxService.send()`，由系统补时间戳并固定初始未读。
2. 实现确定顺序的 `list()` 分页和追加回执式 `mark_read()`。
3. 未知目标、输入超限或锁超时不得留下部分消息。

**验证：** 运行 `python -m pytest tests/teams/test_mailbox_protocols.py -q -k 'send or page or mark_read'`，期望点对点投递及跨重启读取一致。

## T44：实现广播与部分失败重试

**文件：** `src/mewcode/teams/mailbox.py`、`tests/teams/test_mailbox_protocols.py`  
**依赖：** T43

**步骤：**
1. 实现 `broadcast()`，排除发送者并为每个目标生成独立确定消息 ID。
2. 使用共享 `correlation_id` 汇总逐收件人成功和失败结果。
3. 重试只补失败目标，不复制已经成功的消息。

**验证：** 运行 `python -m pytest tests/teams/test_mailbox_protocols.py -q -k broadcast`，期望部分失败报告准确且重试后每个成功目标恰有一条消息。

## T45：实现事务 outbox 投递

**文件：** `src/mewcode/teams/mailbox.py`、`tests/teams/test_mailbox_protocols.py`  
**依赖：** T16、T35、T43

**步骤：**
1. 实现 `flush_outbox()` 读取未投递条目并逐目标幂等追加。
2. 邮箱成功后用 CAS 标记投递；CAS 冲突时依据消息 ID 安全重试。
3. 保留失败条目及有界错误，不回滚已提交的任务或审批状态。

**验证：** 运行 `python -m pytest tests/teams/test_mailbox_protocols.py -q -k outbox`，期望所有崩溃窗口最终收敛且不重复消息。

## T46：增加持久化后唤醒回调

**文件：** `src/mewcode/teams/mailbox.py`、`tests/teams/test_mailbox_protocols.py`  
**依赖：** T45

**步骤：**
1. 定义 `MemberWakeSink`，邮箱层只在完整投递后通知它。
2. 点对点和广播分别传递目标成员与成功消息 ID。
3. 已停止、已移除或 Lead 收件人不产生自动成员恢复请求。

**验证：** 运行 `python -m pytest tests/teams/test_mailbox_protocols.py -q -k wake_sink`，期望只有已持久化且可唤醒的成员收到回调。

## T47：实现审批申请与决定服务

**文件：** `src/mewcode/teams/approvals.py`、`tests/teams/test_approvals.py`  
**依赖：** T15、T34、T41

**步骤：**
1. 实现 `TeamApprovalService.request()`，验证当前任务并递增计划版本。
2. 实现 `decide()`，仅允许 Lead 对精确申请批准或带反馈驳回。
3. 同事务更新成员审批状态并生成协议 outbox。

**验证：** 运行 `python -m pytest tests/teams/test_approvals.py -q -k 'request or decide'`，期望方向、版本和反馈规则正确。

## T48：实现审批失效和副作用 permit

**文件：** `src/mewcode/teams/approvals.py`、`tests/teams/test_approvals.py`  
**依赖：** T34、T47

**步骤：**
1. 实现成员级异步审批锁及 `side_effect_permit()`。
2. permit 内重新检查成员、任务、epoch、计划版本和冻结角色状态。
3. `invalidate_for_task()` 等待已开始工具退出后提交失效，后续工具必须拒绝。

**验证：** 运行 `python -m pytest tests/teams/test_approvals.py -q -k 'permit or invalidation or race'`，期望工具先行与失效先行两种竞态均收敛。

## 会话、安全边界与容量

## T49：增加团队入站消息类型

**文件：** `src/mewcode/providers/base.py`、`tests/test_providers.py`  
**依赖：** T01

**步骤：**
1. 增加 `MessageKind.TEAM_INBOUND`。
2. 保持供应商侧以普通不可信用户上下文编码，不获得系统优先级。
3. 验证现有 USER、ASSISTANT 和 TOOL 类型行为不变。

**验证：** 运行 `python -m pytest tests/test_providers.py -q -k team_inbound`，期望两种 Provider 的请求编码均保持不可信角色。

## T50：扩展主会话入站检查点模型和编解码

**文件：** `src/mewcode/continuity/session_models.py`、`src/mewcode/continuity/session_codec.py`、`tests/test_session_codec.py`  
**依赖：** T49

**步骤：**
1. 在会话状态加入已提交入站 ID 集合。
2. 增加 `inbound_history` 记录，同时编码完整消息和对应 ID。
3. 重放时保持旧会话兼容并拒绝畸形 ID/消息组合。

**验证：** 运行 `python -m pytest tests/test_session_codec.py -q -k inbound`，期望新记录往返、旧日志重放和截断处理均正确。

## T51：实现主会话原子入站提交

**文件：** `src/mewcode/continuity/session_repository.py`、`tests/test_session_repository.py`  
**依赖：** T50

**步骤：**
1. 让 `SessionBinding` 实现 `delivered_inbound_ids` 和 `commit_inbound()`。
2. 单次追加同时持久化消息与邮箱消息 ID，不允许只写其中一半。
3. 打开会话时恢复已提交 ID，并对重复提交做幂等处理。

**验证：** 运行 `python -m pytest tests/test_session_repository.py -q -k inbound`，期望重启后检查点一致且重复提交不重复历史。

## T52：定义通用 Agent 入站边界接口

**文件：** `src/mewcode/agent/runner.py`、`src/mewcode/agent/__init__.py`、`tests/test_agent_runner.py`  
**依赖：** T51

**步骤：**
1. 定义 `InboundHistoryCommitSink` 和 `AgentInboundSource` 协议。
2. 将可选 `inbound_source` 传入 `AgentRunner.start()` 和 `AgentRun`。
3. 未提供入站源时保持当前 Agent Loop 行为完全不变。

**验证：** 运行 `python -m pytest tests/test_agent_runner.py -q -k inbound_source`，期望空入站源和未配置路径均不改变模型请求。

## T53：在安全模型边界注入消息

**文件：** `src/mewcode/agent/runner.py`、`tests/test_agent_runner.py`  
**依赖：** T52

**步骤：**
1. 每轮 Provider 请求前调用 `poll(committed_ids)`。
2. 先调用 `commit_inbound()`，成功后再调用 `acknowledge()`。
3. 当前模型流或工具调度期间不轮询、不取消正在进行的操作。

**验证：** 运行 `python -m pytest tests/test_agent_runner.py -q -k inbound_boundary`，期望调用顺序为 poll → commit → acknowledge → provider，且运行中消息延后到下一轮。

## T54：实现工具请求的安全暂停

**文件：** `src/mewcode/tools/base.py`、`src/mewcode/tools/__init__.py`、`src/mewcode/agent/runner.py`、`tests/test_agent_runner.py`  
**依赖：** T52

**步骤：**
1. 为 `ToolResult` 增加通用、可选且默认关闭的安全暂停元数据。
2. Agent Loop 在完整工具结果提交后以明确暂停原因结束本次运行。
3. 普通工具及未设置元数据的结果继续进入原有下一轮。

**验证：** 运行 `python -m pytest tests/test_agent_runner.py -q -k safe_pause`，期望工具结果先持久化再暂停，且不被映射为失败或取消。

## T55：实现长期成员会话创建和打开

**文件：** `src/mewcode/teams/sessions.py`、`tests/teams/test_sessions_inbound.py`  
**依赖：** T09、T13、T49

**步骤：**
1. 实现 `MemberSessionStore.create()` 和 `open()`。
2. 将成员 ID、稳定 session ID、上下文归档 ID 和固定文件路径绑定。
3. 只在实际恢复成员时加载完整消息，不在团队挂载时批量读取。

**验证：** 运行 `python -m pytest tests/teams/test_sessions_inbound.py -q -k 'create_session or lazy_open'`，期望团队挂载式索引读取不加载大型历史。

## T56：实现成员会话边界提交和恢复

**文件：** `src/mewcode/teams/sessions.py`、`tests/teams/test_sessions_inbound.py`  
**依赖：** T55

**步骤：**
1. 实现 `MemberSessionBinding.commit()`、`commit_inbound()` 和幂等 `close()`。
2. 只承认完整模型响应和完整工具结果边界，修剪尾部未完整工具组。
3. 保留压缩状态、关键结果和投递 ID，不应用主会话 30 天过期删除。

**验证：** 运行 `python -m pytest tests/teams/test_sessions_inbound.py -q -k 'boundary or replay or retention'`，期望四种中断位置只恢复最后完整边界。

## T57：实现有界不可信消息渲染

**文件：** `src/mewcode/teams/inbound.py`、`tests/teams/test_sessions_inbound.py`  
**依赖：** T43、T49

**步骤：**
1. 实现 `render_inbound_batch()`，保留安全字段、协议载荷和消息 ID。
2. 将正文标为不可信同级成员内容并限制批次总长度。
3. 不复制完整内部记录、凭据、工具参数或异常堆栈。

**验证：** 运行 `python -m pytest tests/teams/test_sessions_inbound.py -q -k render`，期望恶意正文不能改变消息角色且超长内容被安全截断。

## T58：实现 Lead/成员入站源和崩溃去重

**文件：** `src/mewcode/teams/inbound.py`、`tests/teams/test_sessions_inbound.py`  
**依赖：** T51、T56、T57

**步骤：**
1. 实现 `LeadInboundSource` 和 `MemberInboundSource` 的 poll/acknowledge。
2. 已存在于会话 `delivered_inbound_ids` 的邮件只补回执，不再次渲染。
3. 覆盖提交前、提交后回执前、回执后三个崩溃窗口。

**验证：** 运行 `python -m pytest tests/teams/test_sessions_inbound.py -q -k 'inbound_source or crash_window'`，期望消息不丢失且同一成员上下文至多注入一次。

## T59：实现容量池非等待获取

**文件：** `src/mewcode/agent/capacity.py`、`src/mewcode/agent/__init__.py`、`tests/test_agent_capacity.py`  
**依赖：** T01

**步骤：**
1. 实现默认 8 名额的 `AgentCapacityPool`。
2. 实现 `try_acquire(owner_kind, owner_id)`，满载时立即返回无租约。
3. 拒绝同一活动拥有者重复占用名额。

**验证：** 运行 `python -m pytest tests/test_agent_capacity.py -q -k try_acquire`，期望第 9 个非等待请求立即失败且活动数不超过 8。

## T60：实现容量等待、公平释放和关闭

**文件：** `src/mewcode/agent/capacity.py`、`tests/test_agent_capacity.py`  
**依赖：** T59

**步骤：**
1. 实现等待式 `acquire()` 的 FIFO 唤醒。
2. 实现 `AgentCapacityLease.close()` 幂等释放及取消等待者清理。
3. `AgentCapacityPool.close()` 拒绝新请求并唤醒所有等待者退出。

**验证：** 运行 `python -m pytest tests/test_agent_capacity.py -q -k 'fifo or release or close'`，期望释放不泄漏、取消者不阻塞后续等待者。

## T61：让普通子 Agent 使用共享容量

**文件：** `src/mewcode/subagents/tasks.py`、`tests/test_subagent_tasks.py`  
**依赖：** T59、T60

**步骤：**
1. 向 `SubagentTaskManager` 注入共享 `AgentCapacityPool`。
2. 启动前使用 `try_acquire()`，满载时保持现有立即失败错误。
3. 在成功、失败、取消和启动异常路径都幂等释放租约。

**验证：** 运行 `python -m pytest tests/test_subagent_tasks.py -q -k capacity`，期望普通子 Agent 不进入团队等待队列且所有终态释放名额。

## T62：验证普通子 Agent 容量兼容

**文件：** `tests/test_agent_capacity.py`、`tests/test_subagent_tasks.py`  
**依赖：** T61

**步骤：**
1. 增加普通子 Agent 与模拟团队拥有者合计 8 名额的测试。
2. 验证已有前台任务限制、状态表和通知行为不变。
3. 验证某个失败拥有者不会阻止其他等待者获得释放名额。

**验证：** 运行 `python -m pytest tests/test_agent_capacity.py tests/test_subagent_tasks.py -q`，期望共享上限及旧任务语义同时通过。

## 成员权限、花名册、运行时与调度

## T63：实现冻结角色快照构造

**文件：** `src/mewcode/teams/policy.py`、`tests/teams/test_roster.py`  
**依赖：** T04

**步骤：**
1. 从当前有效角色目录解析提示、实际 Profile、工具范围、权限模式和规则。
2. 计算可验证 `source_fingerprint` 并创建不可变 `FrozenRoleSnapshot`。
3. 未知、损坏或含 `inherit` 未解析值的角色在发布成员前失败。

**验证：** 运行 `python -m pytest tests/teams/test_roster.py -q -k frozen_role`，期望角色文件后续变化不改变既有快照。

## T64：实现成员工具范围裁剪

**文件：** `src/mewcode/teams/policy.py`、`tests/teams/test_tools.py`  
**依赖：** T63

**步骤：**
1. 实现 `build_member_tool_scope()` 和 `TeamMemberToolPolicy`。
2. 先应用冻结角色、全局禁用、工作区及权限规则，再加入 `team_task` 与 `team_message`。
3. 硬排除普通 Agent、Skill、`team` 和 `team_member`，任何配置都不能恢复。

**验证：** 运行 `python -m pytest tests/teams/test_tools.py -q -k member_scope`，期望成员只能看到被收窄后的普通工具、任务和邮箱工具。

## T65：实现审批保护工具包装

**文件：** `src/mewcode/teams/policy.py`、`tests/teams/test_approvals.py`  
**依赖：** T48、T64

**步骤：**
1. 实现 `ApprovalGuardedTool`，只包装角色原本允许的副作用工具。
2. 未批准时保留只读、任务读取、邮箱读取和计划申请，拒绝其他副作用。
3. 执行前在 permit 内重新检查审批，批准不得扩大冻结角色或绕过权限。

**验证：** 运行 `python -m pytest tests/teams/test_approvals.py -q -k guarded_tool`，期望无审批、过期审批和越权角色都不能产生副作用。

## T66：实现成员新增的成功路径

**文件：** `src/mewcode/teams/roster.py`、`tests/teams/test_roster.py`  
**依赖：** T16、T20、T23、T55、T63

**步骤：**
1. 实现 `TeamRosterService.add_member()` 和 `TeamMemberProvisioner`。
2. 依次写 journal、创建固定 Worktree、会话和邮箱，最后原子发布花名册与注册表。
3. 强制 Lead fence、名称唯一、32 人上限及仅 `IN_PROCESS` 后端。

**验证：** 运行 `python -m pytest tests/teams/test_roster.py -q -k add_member_success`，期望新成员为 IDLE 且所有持久资源和冻结角色可观察。

## T67：实现成员新增故障回滚

**文件：** `src/mewcode/teams/roster.py`、`tests/teams/test_roster.py`  
**依赖：** T66

**步骤：**
1. 对角色、Worktree、会话、邮箱和发布步骤分别注入失败。
2. 按 journal 幂等回滚未发布资源，发布后崩溃只补收尾。
3. 无法安全删除的 Worktree 保留诊断现场但不注册成员。

**验证：** 运行 `python -m pytest tests/teams/test_roster.py -q -k provisioning_failure`，期望任何故障后都不存在可挂载的半个成员。

## T68：实现显式角色刷新

**文件：** `src/mewcode/teams/roster.py`、`tests/teams/test_roster.py`  
**依赖：** T63、T66

**步骤：**
1. 实现 `refresh_role()`，仅允许 IDLE 或 STOPPED 成员。
2. 完整构建并验证新快照后原子替换，保留旧版本及变更时间。
3. 运行中、排队中或损坏的新角色不得改变当前快照。

**验证：** 运行 `python -m pytest tests/teams/test_roster.py -q -k refresh_role`，期望刷新生成新 fingerprint，失败刷新保留原快照。

## T69：实现成员显式恢复和停止

**文件：** `src/mewcode/teams/roster.py`、`tests/teams/test_roster.py`  
**依赖：** T28、T35、T46、T66

**步骤：**
1. 实现带非空原因的 `resume()`，仅接受 IDLE、INTERRUPTED、FAILED 或 STOPPED。
2. 实现 `stop()`，排队成员移除队列，活动成员发送停止请求并交给调度器取消。
3. STOPPED 成员收到普通消息不自动恢复，只有显式 resume 才重新排队。

**验证：** 运行 `python -m pytest tests/teams/test_roster.py -q -k 'resume or stop'`，期望停止保留身份、会话、邮箱和 Worktree。

## T70：实现成员安全移除

**文件：** `src/mewcode/teams/roster.py`、`tests/teams/test_roster.py`  
**依赖：** T24、T67、T69

**步骤：**
1. 仅允许非活动且不负责非终态任务的成员进入移除流程。
2. 在成员恢复锁内先原子注销花名册、注册表和队列项，再用 journal 清理资源。
3. Worktree 有未提交或未合并成果时不改写 Git，返回保留路径与原因。

**验证：** 运行 `python -m pytest tests/teams/test_roster.py -q -k remove`，期望活动/有任务成员被拒绝，干净成员清理，含成果目录保留。

## T71：实现成员运行时工厂的工作区恢复

**文件：** `src/mewcode/teams/runtime.py`、`tests/teams/test_runtime.py`  
**依赖：** T25、T55、T60、T64

**步骤：**
1. 实现 `TeamMemberRuntimeFactory.create()`，验证 attachment、成员状态、容量租约和 Worktree 拥有者。
2. 进入固定 Worktree 并按需打开成员会话。
3. 恢复提示中明确成员身份、中断原因、当前任务和审批状态。

**验证：** 运行 `python -m pytest tests/teams/test_runtime.py -q -k factory`，期望恢复使用同一身份、会话和 Worktree，不创建新成员。

## T72：装配成员 Agent 运行资源

**文件：** `src/mewcode/teams/runtime.py`、`tests/teams/test_runtime.py`  
**依赖：** T53、T58、T65、T71

**步骤：**
1. 绑定成员入站源、持久 history sink、冻结模型和工具范围。
2. 装配工作区工具、项目/用户 Hook、独立 stdio MCP、Context 归档和读取观察缓存。
3. 任一资源启动失败时按逆序关闭已启动资源并保留安全诊断。

**验证：** 运行 `python -m pytest tests/teams/test_runtime.py -q -k resources`，期望成功路径资源齐全、每个故障注入点均无泄漏。

## T73：实现成员运行结果映射和收尾

**文件：** `src/mewcode/teams/runtime.py`、`tests/teams/test_runtime.py`  
**依赖：** T39、T54、T72

**步骤：**
1. 将自然结束、计划暂停、显式取消、中断和失败映射为不同 `TeamMemberOutcome`。
2. 先提交最后完整历史，再关闭运行资源并 suspend Worktree。
3. 自然结束返回 IDLE，绝不自动把当前任务设为 COMPLETED。

**验证：** 运行 `python -m pytest tests/teams/test_runtime.py -q -k outcome`，期望每种停止原因映射正确且任务状态保持显式控制。

## T74：实现调度器队列恢复和唤醒合并

**文件：** `src/mewcode/teams/scheduler.py`、`tests/teams/test_scheduler.py`  
**依赖：** T35、T46、T60、T73

**步骤：**
1. 实现 `restore()`，只恢复原本未启动的持久队列，不自动重放 INTERRUPTED 成员。
2. 实现 `request_wake()`，同成员消息、审批和显式恢复合并为一个队列项。
3. 已停止、已移除或已有活动运行的成员不产生重复启动。

**验证：** 运行 `python -m pytest tests/teams/test_scheduler.py -q -k 'restore or coalesce'`，期望重启后 FIFO 和消息 ID 集合保持一致。

## T75：实现容量获取和单运行启动

**文件：** `src/mewcode/teams/scheduler.py`、`tests/teams/test_scheduler.py`  
**依赖：** T18、T28、T60、T74

**步骤：**
1. 按持久 FIFO 等待 `AgentCapacityPool.acquire()`。
2. 获得容量后在成员恢复锁内提交 RUNNING、`active_run_id` 和递增 `run_generation`。
3. 旧协程的晚到结果必须因运行代际或 Lead fence 失效而拒绝。

**验证：** 运行 `python -m pytest tests/teams/test_scheduler.py -q -k 'capacity or single_run or generation'`，期望并发唤醒只启动一次且全局活动数不超过 8。

## T76：实现调度结果提交、停止和关闭

**文件：** `src/mewcode/teams/scheduler.py`、`tests/teams/test_scheduler.py`  
**依赖：** T45、T73、T75

**步骤：**
1. 驱动 `TeamMemberRuntime.events()` 并将 outcome 原子提交为 IDLE、AWAITING_APPROVAL、STOPPED、INTERRUPTED 或 FAILED。
2. IDLE/FAILED 时生成有界 Lead 通知，任何结果都保持任务状态由成员显式更新。
3. 实现 `stop()` 和 `close()`；关闭最多等待 5 秒，随后取消、记录中断并释放容量。

**验证：** 运行 `python -m pytest tests/teams/test_scheduler.py -q -k 'outcome or stop or close'`，期望状态、通知、Worktree suspend 和容量释放顺序正确。

## 固定工具、协调器与应用装配

## T77：定义四个固定团队工具 schema

**文件：** `src/mewcode/teams/tools.py`、`tests/teams/test_tools.py`  
**依赖：** T02

**步骤：**
1. 定义 `team`、`team_member`、`team_task` 和 `team_message` 四个固定工具名及 JSON schema。
2. 动作、名称和 ID 使用普通字符串参数，不生成动态枚举。
3. 对未知字段、未知动作和不完整参数返回稳定错误。

**验证：** 运行 `python -m pytest tests/teams/test_tools.py -q -k schema`，期望不同花名册和任务状态下 schema 字节级不变。

## T78：实现 `team` 生命周期工具

**文件：** `src/mewcode/teams/tools.py`、`tests/teams/test_tools.py`  
**依赖：** T77

**步骤：**
1. 将 create、list、attach、relink 和 detach 动作转发到 `TeamCoordinator`。
2. 仅普通根 Agent 可见并执行该工具，普通子 Agent和团队成员硬拒绝。
3. PLAN 模式只允许 list 等读动作，写生命周期动作不得执行。

**验证：** 运行 `python -m pytest tests/teams/test_tools.py tests/test_plan_mode.py -q -k team_lifecycle`，期望动作级授权和固定入口行为正确。

## T79：实现 `team_member` 工具

**文件：** `src/mewcode/teams/tools.py`、`tests/teams/test_tools.py`  
**依赖：** T68–T70、T77

**步骤：**
1. 实现 list、add、refresh_role、resume、stop 和 remove 动作。
2. 每个动作从控制上下文取得活动 Lead 身份及当前租约 fence。
3. 非 Lead、租约失效和当前无 attachment 时拒绝，不泄漏其他团队信息。

**验证：** 运行 `python -m pytest tests/teams/test_tools.py -q -k team_member`，期望所有成员动作正确路由且越权调用失败。

## T80：实现 `team_task` 工具

**文件：** `src/mewcode/teams/tools.py`、`tests/teams/test_tools.py`  
**依赖：** T36–T39、T77

**步骤：**
1. 映射 create、get、list、update、assign、claim、transition 和 delete 动作。
2. 绑定 Lead 或当前成员 `TeamActor`，传递 `expected_revision`。
3. 将阻塞、冲突和当前版本以稳定有界结构返回。

**验证：** 运行 `python -m pytest tests/teams/test_tools.py -q -k team_task`，期望 Lead 与成员权限矩阵及修订冲突结果正确。

## T81：实现 `team_message` 工具

**文件：** `src/mewcode/teams/tools.py`、`tests/teams/test_tools.py`  
**依赖：** T43–T48、T54、T77

**步骤：**
1. 映射 send、broadcast、list、mark_read、plan_request 和 plan_decision 动作。
2. 所有协议先经 `TeamProtocolRouter` 严格验证，再提交状态及消息。
3. 计划申请成功时返回安全暂停元数据；部分广播失败返回逐目标结果。

**验证：** 运行 `python -m pytest tests/teams/test_tools.py -q -k team_message`，期望协议、审批暂停、广播和已读动作结果可预测。

## T82：实现协调器创建、挂载与重新关联

**文件：** `src/mewcode/teams/coordinator.py`、`tests/teams/test_integration.py`  
**依赖：** T18、T20、T67、T74

**步骤：**
1. 实现 `TeamCoordinator.create()`、`list()`、`attach()` 和 `relink()`。
2. 强制一个根会话只挂载一个团队，并按仓库验证 → 租约 → journal 恢复 → 中断收敛顺序挂载。
3. 恢复花名册、任务、审批、outbox 和队列，但不加载所有成员完整历史。

**验证：** 运行 `python -m pytest tests/teams/test_integration.py -q -k 'create_attach or relink'`，期望挂载顺序、仓库约束及惰性历史加载正确。

## T83：实现心跳、outbox 和租约丢失收敛

**文件：** `src/mewcode/teams/coordinator.py`、`tests/teams/test_integration.py`  
**依赖：** T18、T45、T76、T82

**步骤：**
1. 挂载后启动 10 秒心跳、outbox 刷新和成员调度任务。
2. 租约丢失时停止出队、撤销写工具、取消活动成员并拒绝旧 fence 提交。
3. 背景任务错误只产生有界诊断，不破坏其他团队或普通会话。

**验证：** 运行 `python -m pytest tests/teams/test_integration.py -q -k 'heartbeat or lease_loss or outbox_loop'`，期望替代时钟下无需等待即可完成收敛。

## T84：实现安全卸载和应用关闭

**文件：** `src/mewcode/teams/coordinator.py`、`tests/teams/test_integration.py`  
**依赖：** T76、T83

**步骤：**
1. 实现 `detach()`，RUNNING、QUEUED 或活动恢复存在时返回具体阻止成员。
2. 实现 `close()`：停止新调用和心跳、停止出队、等待安全边界、标记中断、flush outbox、最后释放租约。
3. 所有关闭步骤幂等，并把超时限制为 5 秒。

**验证：** 运行 `python -m pytest tests/teams/test_integration.py -q -k 'detach or close_order'`，期望卸载门禁及关闭调用顺序精确。

## T85：实现根 Agent 动态运行视图

**文件：** `src/mewcode/teams/coordinator.py`、`tests/teams/test_tools.py`  
**依赖：** T78–T84

**步骤：**
1. 实现 `TeamRunViewComposer` 和 `root_run_view()`。
2. 普通根 Agent 始终只有 `team`；有效 attachment 从下一模型请求加入 Lead Prompt、`team_member`、`team_task` 和 `team_message`。
3. detach 或租约丢失后从下一请求移除 Lead 能力。

**验证：** 运行 `python -m pytest tests/teams/test_tools.py -q -k root_run_view`，期望升格和降格均无需重启 Agent 且工具 schema 稳定。

## T86：把 Team 视图和入站源接入 Conversation

**文件：** `src/mewcode/conversation.py`、`tests/test_conversation.py`  
**依赖：** T53、T58、T85

**步骤：**
1. 每次模型请求组合基础、Skill 和 Team `AgentRunView`，保持现有 PLAN 安全裁剪顺序。
2. 始终向根 Agent 绑定由 coordinator 提供的 Lead 入站源；未挂载时为空操作。
3. 保持普通会话、Skill 激活和普通子 Agent 通知注入行为不变。

**验证：** 运行 `python -m pytest tests/test_conversation.py -q -k 'team or run_view or inbound'`，期望动态团队能力与既有 Skill/PLAN 行为可组合。

## T87：装配 CLI 团队依赖和关闭顺序

**文件：** `src/mewcode/cli.py`、`tests/test_team_cli_integration.py`  
**依赖：** T61、T82–T86

**步骤：**
1. 创建单个共享 `AgentCapacityPool` 并注入普通子 Agent和团队调度器。
2. 装配团队路径、仓库、租约、Git 绑定、邮箱、审批、运行时、调度器和协调器。
3. 注册固定 `team` 入口，并在退出时先关闭团队协调器再关闭其余运行时和容量池。

**验证：** 运行 `python -m pytest tests/test_team_cli_integration.py -q -k wiring`，期望依赖实例共享正确且关闭顺序符合 plan。

## T88：整理公共导出和控制上下文门禁

**文件：** `src/mewcode/teams/__init__.py`、`src/mewcode/tools/__init__.py`、`src/mewcode/agent/__init__.py`、`tests/teams/test_tools.py`、`tests/test_plan_mode.py`  
**依赖：** T54、T64、T77–T87

**步骤：**
1. 仅导出装配层需要的稳定公共类型，避免领域内部实现泄漏。
2. 为混合读写团队工具使用现有控制上下文做 action 级安全检查。
3. 验证普通 Agent、普通子 Agent、Lead 和团队成员四种身份的硬边界。

**验证：** 运行 `python -m pytest tests/teams/test_tools.py tests/test_plan_mode.py -q`，期望工具可见性和 PLAN 动作门禁全部通过。

## 集成、恢复、兼容与文档

## T89：验证完整工具可见性矩阵

**文件：** `tests/teams/test_integration.py`、`tests/teams/test_tools.py`  
**依赖：** T88

**步骤：**
1. 覆盖普通根 Agent、活动 Lead、已卸载根 Agent、普通子 Agent和团队成员。
2. 断言只有根 Agent 有固定 `team` 入口，只有 Lead 有成员管理，Lead/成员共享任务和邮箱。
3. 断言成员不能派生普通子 Agent、创建团队或新增成员。

**验证：** 运行 `python -m pytest tests/teams/test_tools.py tests/teams/test_integration.py -q -k visibility`，期望 AC1 对应矩阵逐项通过。

## T90：验证任务、邮箱和唤醒集成链

**文件：** `tests/teams/test_integration.py`  
**依赖：** T38、T44–T46、T75、T80、T81

**步骤：**
1. 创建依赖任务并指派给空闲成员。
2. 验证状态事务先提交、outbox 后投递、邮箱后唤醒、容量后运行。
3. 覆盖广播、容量满、同成员多消息合并及任务显式完成通知。

**验证：** 运行 `python -m pytest tests/teams/test_integration.py -q -k task_mailbox_wake`，期望消息不丢、单成员单运行、任务不因自然空闲自动完成。

## T91：验证审批端到端集成链

**文件：** `tests/teams/test_integration.py`  
**依赖：** T47、T48、T54、T65、T73、T81

**步骤：**
1. 让需审批成员读取代码、尝试副作用、提交计划并安全暂停。
2. 分别验证驳回后新版本和批准后合法副作用路径。
3. 在重新指派、重置和依赖变化后确认旧批准失效。

**验证：** 运行 `python -m pytest tests/teams/test_integration.py -q -k approval_flow`，期望审批只解除计划门禁且不扩大原权限。

## T92：验证跨应用恢复同一成员

**文件：** `tests/test_team_cli_integration.py`、`tests/teams/test_integration.py`  
**依赖：** T56、T58、T73、T76、T84、T87

**步骤：**
1. 运行成员多轮对话和工具结果，持久化后完全销毁应用对象。
2. 新建应用对象并重新挂载团队，给原空闲成员发送消息。
3. 断言恢复同一成员 ID、完整历史、固定 Worktree、任务和有效审批。

**验证：** 运行 `python -m pytest tests/test_team_cli_integration.py tests/teams/test_integration.py -q -k restart_resume`，期望无需重新 add/spawn 即继续原上下文。

## T93：验证并发、锁和崩溃收敛

**文件：** `tests/teams/test_repository.py`、`tests/teams/test_leases.py`、`tests/teams/test_mailbox_protocols.py`、`tests/teams/test_scheduler.py`  
**依赖：** T18、T45、T58、T75、T76

**步骤：**
1. 并发执行双 Lead 挂载、任务领取、邮箱写入、消息唤醒、显式恢复和停止。
2. 在状态替换、邮箱追加、历史提交、回执和运行收尾边界注入崩溃。
3. 断言恢复后无双 Lead、无双运行、无重复上下文、无半条消息或半个成员。

**验证：** 运行 `python -m pytest tests/teams/test_repository.py tests/teams/test_leases.py tests/teams/test_mailbox_protocols.py tests/teams/test_scheduler.py -q -k 'concurrent or crash or race'`，期望所有竞态用替代实现快速收敛。

## T94：验证路径、安全和故障隔离

**文件：** `tests/teams/test_paths_codec.py`、`tests/teams/test_repository_binding.py`、`tests/teams/test_runtime.py`、`tests/teams/test_integration.py`  
**依赖：** T20、T57、T72、T83

**步骤：**
1. 覆盖路径别名、符号链接、大小写变体、Git 元数据替换和跨团队引用。
2. 在任务说明、邮箱正文和协议载荷加入伪造系统指令，验证权限不变。
3. 损坏单团队或单成员持久文件，验证其他团队、其他成员和普通会话仍工作。

**验证：** 运行 `python -m pytest tests/teams -q -k 'security or isolation or corruption'`，期望危险输入被拒绝且故障范围局部化。

## T95：运行普通功能兼容回归

**文件：** `tests/test_agent_runner.py`、`tests/test_conversation.py`、`tests/test_plan_mode.py`、`tests/test_subagent_tasks.py`、`tests/test_subagent_worktree.py`、`tests/worktrees/test_integration.py`  
**依赖：** T26、T62、T86–T88

**步骤：**
1. 验证未创建或未挂载团队时不启动后台任务、不写团队目录。
2. 验证普通对话、PLAN、Skill、Hook、MCP、普通子 Agent和 Worktree 子 Agent 行为不变。
3. 验证新增可选参数全部有兼容默认值。

**验证：** 运行 `python -m pytest tests/test_agent_runner.py tests/test_conversation.py tests/test_plan_mode.py tests/test_subagent_tasks.py tests/test_subagent_worktree.py tests/worktrees/test_integration.py -q`，期望所有既有及新增兼容断言通过。

## T96：补充 Phase 14A 用户文档

**文件：** `README.md`  
**依赖：** T87–T95

**步骤：**
1. 说明四个工具、Lead 升格、成员状态、任务依赖、邮箱、审批和恢复流程。
2. 说明 `~/.mewcode/teams/<team-name>/`、固定 Git Worktree、本地保密模型和安全限制。
3. 明确 Phase 14B/14C 才包含终端后端、自动编排、Git 合并和 coordinator 模式。

**验证：** 运行 `rg -n "Phase 14A|team_member|team_task|team_message|Worktree|审批|Phase 14B|Phase 14C" README.md`，期望每个主题至少出现一次且范围表述与 spec 一致。

## T97：执行完整静态与测试验证

**文件：** `src/mewcode/**`、`tests/**`、`README.md`  
**依赖：** T89–T96

**步骤：**
1. 编译全部 Python 源码，捕获导入、类型名和语法错误。
2. 运行完整测试套件，不只运行团队测试。
3. 检查实现中没有 Phase 14B/14C 后端、自动 Git 合并或 coordinator 开关的越界代码。

**验证：** 依次运行 `python -m compileall -q src/mewcode`、`python -m pytest -q` 和 `rg -n "tmux|terminal pane|coordinator_mode|auto.?merge" src/mewcode/teams src/mewcode/agent/capacity.py`；期望编译及测试退出码为 0，范围搜索没有未解释的 Phase 14B/14C 实现。

## 执行顺序

每个任务的“依赖”字段是唯一权威依赖关系；所有依赖都指向较小编号，因此不存在循环。严格按 `T01 → T02 → … → T97` 执行始终合法。为缩短开发周期，在依赖满足后可采用下列并行轨道：

```text
基础持久化：T01 -> T02..T20
Worktree：        T04 -> T21..T26
领域/服务：       T06 -> T27..T48
会话入站：        T49 -> T50..T58
统一容量：        T59 -> T60..T62
                         \____________
角色与成员：                    T63..T70
运行与调度：                         T71..T76
工具与装配：                              T77..T88
集成与回归：                                   T89..T97
```

允许并行的典型组合：

- T17–T18、T21–T24、T27–T35、T49–T58、T59–T62 在各自前置完成后可由不同开发者并行。
- T36–T39、T40–T46、T47–T48 分属任务、邮箱和审批服务，可在纯领域层完成后并行。
- T89–T94 是不同集成场景，可在 T88 完成且各自列出的依赖满足后并行。
- T95–T97 必须最后串行执行，作为兼容回归、文档和全量验证收口。

## 组件覆盖

| `plan.md` 组件 | 实现任务 |
|---|---|
| `teams.models` | T02–T07 |
| `teams.paths` | T08–T09 |
| `teams.codec` | T11–T13 |
| `teams.repository` | T14–T16 |
| `teams.leases` | T17–T18 |
| `teams.repository_binding` | T19–T20 |
| Worktree 生命周期扩展 | T21–T26 |
| `teams.domain` | T27–T35 |
| `teams.tasks` | T36–T39 |
| `teams.protocols` | T40–T41 |
| `teams.mailbox` | T42–T46 |
| `teams.approvals` | T47–T48 |
| Agent 入站边界与 `teams.sessions/inbound` | T49–T58 |
| `agent.capacity` 与普通子 Agent 兼容 | T59–T62 |
| `teams.policy` | T63–T65 |
| `teams.roster` | T66–T70 |
| `teams.runtime` | T71–T73 |
| `teams.scheduler` | T74–T76 |
| `teams.tools` | T77–T81 |
| `teams.coordinator` | T82–T85 |
| `conversation` 与 `cli` 装配 | T86–T88 |
| 集成、安全、兼容及文档 | T89–T97 |

## 需求覆盖

| 需求范围 | 主要任务 |
|---|---|
| F1–F7 团队生命周期 | T14–T20、T77–T78、T82–T87 |
| F8–F18 花名册与隔离 | T21–T26、T59–T76、T79、T88–T89 |
| F19–F28 共享任务 | T27–T39、T80、T90 |
| F29–F40 邮箱与唤醒 | T29、T35、T40–T46、T57–T58、T74–T76、T81、T90 |
| F41–F46 计划审批 | T34、T41、T47–T48、T54、T63–T65、T81、T91 |
| F47–F54 会话与恢复 | T49–T58、T71–T76、T84–T89、T92–T95 |
| N1–N6 容量与性能 | T07、T55、T59–T62、T74–T77、T87 |
| N7–N15 持久一致性 | T09–T18、T27、T35、T42–T48、T56、T76、T83–T84、T93 |
| N16–N20 恢复可靠性 | T49–T58、T71–T76、T92–T94 |
| N21–N28 安全权限 | T08–T09、T19–T26、T40–T41、T57、T63–T70、T88、T94 |
| N29–N34 兼容与测试 | T01、T26、T49、T62、T87–T97 |
