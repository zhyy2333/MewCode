# Phase 14C Team Lead 编排、受控 Git 集成与 Coordinator 双开关 Checklist

> 每项必须通过运行代码、检查持久状态或观察 fake 时间线验证。只有取得实际证据后才能勾选；不得用删除测试、放宽断言或无理由 skip/xfail 代替修复。

## 基线

- [x] **B01 — 实施前基线已记录。** 在开始源码改动前运行完整测试、编译和 diff 检查并保存通过数、耗时和退出码。（验证：运行 `python -m pytest`、`python -m compileall -q src/mewcode`、`git diff --check`，期望退出码均为 0。）

## 双开关与权限（AC1、AC2）

- [ ] **C01 / AC1 — 配置关、环境关时完全关闭。** coordinator 工具不可见，Lead 原写入工具仍可用，团队目录没有 14C 文件或专用后台循环。（验证：运行双开关矩阵测试并比较工具名、服务构造计数、磁盘树和活动 task。）
- [ ] **C02 / AC1 — 配置开、环境关时完全关闭。** 单独配置能力开关不会收窄权限或创建 coordinator 状态。（验证：设置配置为 true、删除环境变量，挂载团队并检查工具与文件树。）
- [ ] **C03 / AC1 — 配置关、环境开时完全关闭。** 单独环境变量不会启用 coordinator，也不会生成 settings/journal。（验证：配置为 false、环境为 `1`，挂载团队并检查工具与文件树。）
- [ ] **C04 / AC1 — 非法环境值安全关闭。** 除 `1` 外的非法非关闭值产生有界诊断并保持关闭，不把原始值持久化。（验证：参数化非法值并搜索状态、日志和工具输出中的哨兵。）
- [ ] **C05 / AC2 — 双开关均开启后 Lead 工具被收窄。** 已挂载 Lead 看不到/不能调用写文件、编辑文件、通用命令、普通 Agent 和技能加载工具，但保留基础只读、成员、任务、邮箱、审批、停止/恢复与 coordinator 工具。（验证：比较 enabled Lead 的精确工具集合并直接尝试旧工具引用。）
- [ ] **C06 / AC2 — 受限 Git 接口可用且无任意命令入口。** Lead 可检查、计划、集成和恢复，但 schema 不接受 command、argv 或任意路径。（验证：运行工具 schema/调用测试，输入 shell 元字符、push 和越界路径，期望服务端拒绝且 Git runner 无调用。）
- [ ] **C07 / AC2 — 权限裁剪只作用于已挂载 Lead。** 未挂载 root、普通成员、普通子 Agent、隐藏成员工作模式和未启用团队保持原工具视图。（验证：为每种身份构造运行视图并比较工具名称与安全属性。）
- [ ] **C08 / AC1/AC2 — 旧工具引用不能绕过 gate。** 工具在开启/关闭或 detach 后被缓存时，服务层仍校验 settings、attachment、actor 和 lease fence。（验证：保存旧工具对象后切换状态并调用，期望明确拒绝且无持久/Git 副作用。）

## 自动拆解、派发与审批（AC3、AC4）

- [ ] **C09 / AC3 — 拆解任务字段完整。** 每个任务都有标题、描述、依赖、目标成员或角色、验收标准和交付类型；本地 ID 正确解析为共享 task ID。（验证：提交有效多层 DAG，读取拆解记录与共享任务并逐字段比对。）
- [ ] **C10 / AC3 — 拆解上限严格。** 最多 32 个任务、每任务最多 16 条验收标准、64 个依赖和 32 个所需工具；越界批次整体拒绝。（验证：分别测试边界值和边界值加一，检查共享任务数与 coordinator 文件。）
- [ ] **C11 / AC3 — 无效拆解全成全败。** 重复 ID、缺失依赖、循环、非法 selector、未知成员、角色/工具不匹配或越界文本不会发布部分共享任务。（验证：逐类注入错误并比较 TeamState revision、任务 ID 集和磁盘文件哈希。）
- [ ] **C12 / AC3 — 拆解结果稳定且可审计。** 相同有效输入、团队 snapshot 和目标分支产生相同 ordinal、依赖顺序和解释，记录能关联用户目标、团队、任务和状态修订。（验证：使用固定 ID/时钟重复运行于等价 fixture 并比较规范化记录。）
- [ ] **C13 / AC3 — 拆解事务可恢复。** prepare 前、TeamState CAS 后和 finalize 前崩溃分别收敛为安全重试、补确认或人工处理，不产生部分/重复任务。（验证：在三个边界注入故障，重建服务后比较任务集合和 journal。）
- [ ] **C14 / AC3 — 人工协调决定完整落盘。** 重派、取消、停止和转人工都保存 task、member、TeamState revision、原因码、时间和结果；并发第二决定被拒绝或顺序化。（验证：执行四类动作及 barrier 竞争，读取 decision/journal 时间线。）
- [ ] **C15 / AC3 — 审批协议不可绕过。** 审批成员只先运行规划并安全暂停；批准前实现副作用为零，Coordinator 不能生成批准决定，批准/拒绝/失效继续使用 Phase 14A 协议。（验证：运行审批端到端，记录计划请求、结构化决定、工具副作用和成员状态。）
- [ ] **C16 / AC4 — 依赖未成功时保持 pending。** pending、failed、cancelled、manual 或未审阅的依赖都阻止下游派发，并记录稳定原因。（验证：参数化依赖状态，执行 reconcile，期望 assignee/run 数不变。）
- [ ] **C17 / AC4 — 成员状态阻止不安全派发。** PROVISIONING、QUEUED、RUNNING、AWAITING_APPROVAL、STOPPED、INTERRUPTED、FAILED、已有任务或 Worktree 占用的成员不会被强制启动。（验证：参数化成员状态与占用 fake，检查任务仍 pending。）
- [ ] **C18 / AC4 — 角色和能力选择准确。** 指定成员必须匹配角色/工具要求；按角色选择时过滤能力不足者并用历史负载、创建时间和 member ID 稳定排序。（验证：使用等价成员排列多次协调并比较选择结果。）
- [ ] **C19 / AC4 — 容量不足不提交派发。** 无即时容量时任务保持未分配 pending，不写 wake queue、不启动 driver、不超过共享容量。（验证：容量为 1 时占满名额再 reconcile，比较 TeamState、queue 和 active owner。）
- [ ] **C20 / AC4 — 容量预留无竞态和泄漏。** 预留与 mailbox wake 只移交一次；assign/wake 失败、停止、关闭和异常 driver 都释放预留。（验证：用 barrier/故障 fake 交错操作并统计 lease acquire/transfer/release。）
- [ ] **C21 / AC4 — reconcile 幂等且单动作。** 相同 snapshot 的重复/并发 reconcile 不重复 decision、assignment、outbox、成员启动或工具调用；同一任务同时只有一个活动动作。（验证：并发运行两个 reconcile 并比较副作用计数与 task lock 时间线。）

## 成果审阅与合并候选（AC5）

- [ ] **C22 / AC5 — 可信终态是候选前提。** 任务 completed 但成员仍有 active run、driver、容量预留、控制运行或 Worktree 锁时不会冻结候选。（验证：逐项保留活动证据并执行成果观察，期望 review/candidate 不生成。）
- [ ] **C23 / AC5 — Worktree 归属严格验证。** 团队 binding、member ID、固定 root/branch、record、marker、repository common dir、TEAM_MEMBER owner 和 persistent 标志全部一致才可继续。（验证：逐字段篡改 fixture，期望每类都被拒绝且原文件不被覆盖。）
- [ ] **C24 / AC5 — 提交范围严格。** start 必须是 end 祖先，成员 HEAD 必须等于 end，工作区必须干净且 Git 交付提交范围非空；提交列表冻结后不可漂移。（验证：覆盖非祖先、空范围、dirty、HEAD 改变和超限范围。）
- [ ] **C25 / AC5 — NO_GIT 依赖明确处理。** 只有已成功并 accepted 且声明无 Git 交付的任务可被视为不影响后续集成，不创建伪 Git step。（验证：构造混合 DAG 并比较 topological task IDs 与 step IDs。）
- [ ] **C26 / AC5 — Lead 审阅是候选门禁。** Git 机器检查通过但 review 为 pending/rejected/manual 时不能成为候选；accepted 必须有有界证据摘要。（验证：按四种 review 状态计划批次并检查候选集合。）
- [ ] **C27 / AC5 — 审阅在事实变化后失效。** task revision、assignee、member 身份、HEAD、start/end 或提交列表变化使 accepted review 失效。（验证：逐字段变化后重新观察，期望候选被移除。）
- [ ] **C28 / AC5 — 集成顺序稳定且依赖正确。** 多层 DAG 严格拓扑排序，同层按 ordinal/task ID；依赖未合并或未明确 NO_GIT 时下游不执行。（验证：多次打乱输入映射，比较 batch/step 顺序和 Git 调用时间线。）
- [ ] **C29 / AC5 — batch 和 step 并发互斥。** 同一 repository/target branch 同时只有一个团队 batch，同一 task 只有一个 merge attempt；不同 branch 可并行。（验证：两个 repository service 实例用 barrier 竞争 branch/task lock。）
- [ ] **C30 / AC5 — 目标分支与基线正确。** 只在绑定仓库当前检出的本地分支上集成，不自动 checkout；detached HEAD、错误 ref、dirty target 或 v1 基线漂移都转人工。（验证：参数化 target snapshot 并检查无 merge 调用。）

## Git 原子性与恢复（AC6）

- [ ] **C31 / AC6 — 每个 Git 副作用前后都有 journal 边界。** precheck、merge start、commit、postcheck、rollback 和完成按合法连续序号持久化。（验证：执行一步成功 merge，读取 journal 并与 scripted Git 调用顺序逐项对齐。）
- [ ] **C32 / AC6 — 冲突被回滚并短路。** v1 不自动解析冲突；匹配 merge state 被 abort，目标恢复到 pre OID/干净状态，后续依赖 step 不执行。（验证：注入 merge conflict，检查 HEAD/status、batch 状态和后续调用数。）
- [ ] **C33 / AC6 — Git/commit/postcheck 失败原子收敛。** 每个失败点恢复到操作前可验证状态；无法证明或回滚失败时转 MANUAL，不报告完成。（验证：逐故障点注入错误并比较 pre/post OID、status、step/batch 终态。）
- [ ] **C34 / AC6 — merge 未提交崩溃可恢复。** journal 为 merge started 且存在匹配 MERGE_HEAD 时，新进程 abort、验证并决定安全重试，不留下部分 index/worktree。（验证：在 merge applied 后中断并重建服务。）
- [ ] **C35 / AC6 — commit 已成功但 journal 未确认不会重复。** 恢复通过 merge parents、第二 parent 和 team/batch/task trailer 识别 commit，补写确认而不再次调用 merge/commit。（验证：commit 后、journal 前中断，重启并统计 merge commit 与 runner 调用数均为 1。）
- [ ] **C36 / AC6 — 已验证 step 与 batch 元数据可修复。** step 完成但 next_step/run 状态未推进时只修复记录，不重放 Git。（验证：在 step finalize 和 batch update 之间中断，重启后比较目标 HEAD 与命令计数。）
- [ ] **C37 / AC6 — 未知仓库状态保守转人工。** HEAD 漂移、未知 dirty、MERGE_HEAD 不匹配、parents/trailer 不匹配时不 reset、不继续，且阻止同分支新 batch。（验证：逐类篡改仓库状态并检查 manual 诊断与零破坏调用。）
- [ ] **C38 / AC6 — 已确认步骤永不重放。** 服务多次重启、recover 与 reconcile 后，已完成 step 的 merge/commit 调用计数保持不变。（验证：完成多步骤批次后连续重建三次并比较历史。）
- [ ] **C39 / AC6 — 成员工具调用不在恢复时重放。** Lead/成员中断仍按 14A/14B 收敛，coordinator recovery 只读持久事实，不重新执行成员模型或工具。（验证：副作用哨兵在成员中断、Lead 重启和 batch 恢复后仍只出现一次。）

## 本地 Git 与成果保护（AC7）

- [ ] **C40 / AC7 — 无远端命令。** 成功、冲突、失败和恢复路径均不调用 push、fetch、pull、remote、PR 或远端 ref 写入。（验证：审查 scripted runner argv 与 fake remote refs，期望禁用命令零出现且 refs 不变。）
- [ ] **C41 / AC7 — 不删除成员成果。** 任何路径都不调用 Worktree remove、branch delete、`git clean`，成员目录、分支与未合并提交在失败后仍存在。（验证：运行负向端到端并比较目录、ref 和 object 可达性。）
- [ ] **C42 / AC7 — Git 访问被路径边界限制。** 只允许绑定 repository root 和登记成员 Worktree；任意调用方 path、跨 repo、symlink/reparse 或路径漂移被拒绝。（验证：输入越界/链接路径并记录 runner cwd，期望无越界调用。）
- [ ] **C43 / AC7 — 固定 argv 不受文本注入。** 目标、标题、描述、验收标准、member 名和错误文本不能改变 Git 子命令或参数边界。（验证：输入 shell 元字符与命令哨兵，比较完整 fake argv。）

## 持久格式、隐私与并发架构

- [ ] **I01 — 旧团队状态无需迁移。** 只含 Phase 14A/14B 文件的团队可挂载并完整运行；缺少 coordinator 子树解释为从未启用。（验证：加载旧 fixture，运行成员/任务/邮箱流程并比较 state schema/version。）
- [ ] **I02 — 关闭模式不碰已有 14C 文件。** 先启用创建状态，再关闭双开关挂载；文件哈希、mtime 和 journal revision 保持不变。（验证：前后快照 coordinator 子树。）
- [ ] **I03 — 所有 14C 记录严格拒绝未知格式。** settings、decomposition、batch、step、journal 拒绝未知/重复/缺失字段、未来版本、截断 JSON、非法 UTF-8 和非有限数字。（验证：参数化 corruption 测试并确认原文件未覆盖。）
- [ ] **I04 — 文本、集合和提交范围有界。** 用户目标、任务、标准、工具列表、决定、审阅、诊断、候选、step 和 journal 达到边界可读，超过边界明确拒绝。（验证：对每个上限运行 N/N+1 测试。）
- [ ] **I05 — 路径与链接检查覆盖所有新文件。** coordinator 子树、task lock 和跨团队 branch lock 均受 teams root 包含性、safe ID、link/reparse 检查。（验证：构造 `..`、绝对注入、Windows 保留名、symlink/reparse fixture。）
- [ ] **I06 — 原子写和 CAS 不丢更新。** 并发 decomposition/batch/step/journal 更新只有一个 revision 成功，失败方不覆盖胜者或留下临时截断文件。（验证：barrier 并发写和故障注入后扫描目录。）
- [ ] **I07 — journal 序号连续且状态合法。** 并行追加没有重复/跳号，非法终态后追加或错误边界被拒绝。（验证：多 writer fake 与状态机测试。）
- [ ] **I08 — 同分支跨团队锁有效。** 同一 repository/branch 的两个团队互斥，不同 branch 不互相阻塞；进程异常后文件锁可重新取得。（验证：两个 repository 实例并发和模拟进程释放。）
- [ ] **I09 — 敏感内容不持久化。** API key、完整 argv、完整会话、prompt、模型原文、Git stdout/stderr、异常堆栈和控制凭据不出现在任何 14C 文件。（验证：把不同秘密哨兵注入每个输入/错误源并递归搜索 coordinator 子树。）
- [ ] **I10 — 用户诊断有界且脱敏。** 工具结果只报告稳定阶段/错误码和必要摘要，不泄露秘密、完整命令或原始异常。（验证：捕获工具 content/error/metadata 并执行哨兵零命中与长度断言。）
- [ ] **I11 — 生命周期顺序安全。** attach 先执行 14A/14B 中断收敛，再恢复 coordinator，随后 flush 邮箱/恢复 queue/启动循环；关闭或 lease lost 先停止新协调动作。（验证：记录 fake 服务调用时间线。）
- [ ] **I12 — 时间与等待可替换。** 协调循环、锁重试、Git timeout、容量和恢复使用 fake 时钟/等待器，专项测试无真实长 sleep 或网络。（验证：审查依赖注入并统计专项测试墙钟时间/网络调用。）
- [ ] **I13 — 关闭不删除或自动清理。** detach、close、lease lost 和失败恢复不会删除 coordinator 记录、成员 Worktree、分支或提交。（验证：前后文件/ref 快照。）
- [ ] **I14 — v1 策略不静默升级。** 已保存 policy version 与当前不匹配时明确拒绝协调，旧记录不被新策略覆盖。（验证：篡改/注入未来 policy version 并比较文件哈希。）

## Phase 14A/14B 与普通能力回归（AC8、AC9）

- [ ] **C44 / AC8 — 进程内成员回归通过。** 创建、任务、邮箱、审批、停止、恢复、会话和固定 Worktree 行为与 14A/14B 相同。（验证：运行现有 teams/runtime/scheduler/approval/mailbox/session 测试与 coordinator in-process E2E。）
- [ ] **C45 / AC8 — Windows Terminal 成员回归通过。** 宿主创建、投递唤醒、IDLE 复用、窗格消失替代、停止和重连保持 14B 语义。（验证：运行现有 Windows Terminal fake 测试和 14C E2E。）
- [ ] **C46 / AC8 — tmux 成员回归通过。** pane 绑定、复用、断线、恢复、停止和结果提交保持 14B 语义。（验证：运行现有 tmux fake 测试和 14C E2E。）
- [ ] **C47 / AC8 — 普通子 Agent与非团队能力不变。** 普通子 Agent、Worktree 子 Agent、PLAN、Skill、Hook、MCP、上下文、会话和未启用团队回归通过。（验证：运行现有完整测试并比较 coordinator disabled 工具/文件状态。）
- [ ] **C48 / AC9 — Phase 14B 已验收时终端成员可参与 14C。** Windows Terminal 与 tmux fake 均完成拆解、派发、审批、成果冻结、审阅和集成。（验证：运行两个终端 backend 的 14C E2E 并保存时间线。）
- [ ] **C49 / AC9 — readiness 未证明时明确拒绝终端。** Windows Terminal/tmux 不被派发且结果不成为候选，不降级；同团队 in_process 路径仍可完成。（验证：注入 readiness=false 的三后端对照测试。）

## 编译与自动化测试（AC10）

- [x] **B02 — 源码编译通过。** （验证：运行 `python -m compileall -q src/mewcode`，期望退出码 0。）
- [x] **B03 — coordinator 模型、settings、路径和 repository 单元测试通过。** （验证：运行 `python -m pytest tests/teams/test_coordinator_models.py tests/teams/test_coordinator_settings.py tests/teams/test_coordinator_repository.py tests/teams/test_paths_codec.py -k coordinator`，期望全部通过。）
- [x] **B04 — 编排、Git 和集成专项通过。** （验证：运行 `python -m pytest tests/teams/test_orchestration.py tests/teams/test_coordinator_git.py tests/teams/test_coordinator_integration.py`，期望全部通过。）
- [x] **B05 — coordinator 端到端、并发和崩溃恢复通过。** （验证：运行 `python -m pytest tests/teams/test_coordinator_e2e.py`，期望全部通过且没有无理由 skip/xfail。）
- [x] **B06 — 团队与受影响回归通过。** （验证：运行 `python -m pytest tests/teams tests/test_agent_capacity.py tests/test_team_cli_integration.py`，期望全部通过。）
- [x] **B07 — 完整测试套件通过。** （验证：运行 `python -m pytest`，期望退出码 0，并记录测试数和耗时。）
- [x] **B08 — 变更质量检查通过。** （验证：运行 `git diff --check`，搜索 Phase 14C 范围的 `skip|xfail|TODO|TBD`，期望无无理由命中。）
- [x] **B09 — 安装与 CLI 冒烟通过。** （验证：临时 venv 中执行 `pip install --no-deps -e .`、`mewcode --help`、隐藏模式帮助和 `python -c "import mewcode.teams"`，期望退出码 0且普通帮助不显示隐藏参数。）

## 端到端场景

- [ ] **E01 — 双开关关闭的普通团队。** 创建/挂载团队，Lead 直接编辑文件并使用原团队工具；进程退出后不存在 14C 子树。（验证：四种非全开组合的 CLI fixture 和磁盘快照。）
- [ ] **E02 — 双开关开启的进程内交付。** 两名成员完成依赖任务，其中一名经过计划审批；Lead 审阅后自动按拓扑合并到本地目标分支。（验证：记录任务、审批、容量、review、batch、journal 和 merge parents。）
- [ ] **E03 — Windows Terminal 完整交付。** 终端成员通过持久邮箱唤醒、计划/执行、IDLE 后成果冻结并合并；同一成员不重复运行。（验证：记录 host/run generation、Worktree OID、batch step 和最终 HEAD。）
- [ ] **E04 — tmux 完整交付。** tmux 成员经历 pane 断线/替代后保持身份与 Worktree，最终成果只合并一次。（验证：比较断线前后 member/host/worktree/task 和 merge commit。）
- [ ] **E05 — 容量与依赖压力。** 容量为 1，多成员 DAG、普通子 Agent和 stop/reassign 并发；任务按条件推进且总运行数不超 1。（验证：保存容量/queue/task/action 完整时间线。）
- [ ] **E06 — Git 冲突。** 上游成功合并、下游发生冲突；下游回滚，后续依赖不执行，目标分支保留上游确认成果且成员 Worktree 完整。（验证：比较 pre/upstream/conflict 后 HEAD、status、refs 和调用数。）
- [ ] **E07 — commit 后崩溃。** merge commit 已创建但 journal 未确认时终止进程；重启识别并确认同一 commit，不产生第二个 merge commit。（验证：比较 commit graph、trailers、journal 和 runner 计数。）
- [ ] **E08 — 未知漂移转人工。** 批次中途由外部改变目标 HEAD 或工作区；恢复不 reset 外部成果、不继续 batch并阻止新同分支批次。（验证：比较外部 commit/文件前后和 manual 诊断。）
- [ ] **E09 — 远端与未合并成果保护。** 有 fake remote 和额外成员提交时运行成功/失败集成；remote refs、成员 branch、Worktree 和额外提交不变。（验证：前后 Git ref/object/目录快照与 argv 审计。）
- [ ] **E10 — readiness=false 三后端对照。** 同一拆解中进程内任务可运行，Windows Terminal/tmux 任务保持 pending/明确拒绝，其已有结果不成为候选。（验证：记录三成员 decision/review/candidate 集合。）

## 完成标准

- [ ] AC1–AC10 均至少由一个已勾选的 C 项直接覆盖，并具有命令输出或可复现观察证据。（验证：检查 C01–C49 与 AC 映射。）
- [ ] I01–I14 全部通过，证明兼容性、持久性、并发、安全和隐私边界。（验证：检查每项关联的测试或快照证据。）
- [ ] B01–B09 全部通过并保存测试数、耗时和退出码。（验证：检查验证记录。）
- [ ] E01–E10 全部通过；真实终端不可用时仍必须使用 Phase 14B fake 覆盖，平台限制单独记录而不隐藏。（验证：检查每个场景的时间线与最终状态。）
- [ ] 所有失败项已修复并重新验证，没有通过删除测试、降低断言或无理由 skip/xfail 制造“通过”。（验证：审查最终 diff、pytest 收集结果和 skip/xfail 搜索。）

## 验证记录

> 开发阶段在此追加日期、命令、通过数、耗时、退出码和关键端到端时间线；没有证据的条目保持未勾选。

- 2026-08-21 实施前基线：`python -m compileall -q src/mewcode` 退出码 0；`python -m pytest` — 1105 passed in 31.80s；`git diff --check` 退出码 0。工作树中 Phase 14A 文档目录迁移为实施前已有改动，本阶段不覆盖。
- 2026-08-21 Phase 14C 专项：模型/settings/存储/路径 31 passed in 1.50s；编排/Git/集成 9 passed in 5.45s；Git fake E2E（进程内、Windows Terminal、tmux、readiness=false、冲突和崩溃恢复）10 passed in 4.97s。
- 2026-08-21 受影响回归：`tests/teams tests/test_agent_capacity.py tests/test_team_cli_integration.py` — 125 passed in 9.40s；完整套件 — 1141 passed in 36.26s（后续新增验收用例后最终结果见最终验证记录）。
- 2026-08-21 安装/CLI：临时 venv 中 `pip install --no-deps -e .`、`mewcode --help` 和 `import mewcode.teams` 均退出 0；普通帮助未显示隐藏 team 参数。`git diff --check` 退出 0，Phase 14C 范围无 `skip|xfail|TODO|TBD` 命中。
- 2026-08-21 最终验证：`python -m compileall -q src/mewcode` 退出码 0；更新后的完整套件 `python -m pytest -q` — 1159 passed in 45.49s；恢复生成的已跟踪 bytecode 后 `git diff --check` 退出码 0。
