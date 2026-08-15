# 子 Agent Worktree 隔离 Checklist

> 每一项都通过运行代码、自动化测试或观察外部行为验证。除特别说明外，测试使用临时仓库和本地裸远端，不访问网络、不依赖用户全局 Git 配置，也不读取实现细节来判定通过。

## 实现完整性

- [x] 角色可以选择共享或 Worktree 隔离，未声明时保持共享行为。（验证：运行 `python -m pytest tests/test_subagent_parser.py tests/test_subagent_catalog.py -k isolation -q`，期望所有声明与默认值测试通过。）
- [x] Worktree 生命周期具备创建、只读恢复、进入、退出、列表和删除六个可调用行为。（验证：运行 `python -m pytest tests/worktrees/test_lifecycle.py -q`，期望六类行为及其错误结果均被覆盖并通过。）
- [x] 初始化支持明确复制、目录链接、Git Hook 环境和必需/可选失败语义。（验证：运行 `python -m pytest tests/worktrees/test_config.py tests/worktrees/test_links.py tests/worktrees/test_initializer.py -q`，期望配置与三类初始化测试全部通过。）
- [x] 隔离任务的工具、权限、Prompt、Context、Hook、MCP、Skill 和项目记忆都能绑定同一 Worktree。（验证：运行 `python -m pytest tests/test_subagent_worktree.py -k bundle -q`，期望每个组件报告相同的任务绝对根路径。）
- [x] 后台清理具备启动扫描、逐小时扫描、24 小时过期、候选限额和三层过滤。（验证：运行 `python -m pytest tests/worktrees/test_janitor.py -q`，期望调度、边界和保守清理测试全部通过。）
- [x] `/worktrees` 与 `/worktree delete <名称> [--force]` 仅作为本地命令可用。（验证：运行 `python -m pytest tests/test_builtin_commands.py -k worktree -q`，期望本地命令可调用且模型工具 schema 无新增 Worktree 工具。）
- [x] 用户文档说明配置、角色字段、生命周期、保护、命令和非沙箱边界。（验证：加载 `README.md` 与两个 examples，并运行对应解析器测试，期望示例有效且文档字段与程序行为一致。）

## 隔离声明、名称与分配

- [x] [AC1] 加载未声明隔离、`shared`、`worktree` 和未知值角色，前三者按定义生效、未知值被拒绝。（验证：运行 `python -m pytest tests/test_subagent_parser.py -k isolation -q`，期望四类输入得到对应结果。）
- [x] [AC2] 分别发起共享定义式、Worktree 定义式和 Fork 式任务，只有 Worktree 定义式创建目录，委派工具 schema 与 Fork 首次请求缓存前缀不变。（验证：运行 `python -m pytest tests/test_subagent_coordinator.py tests/test_subagent_runtime.py -k 'isolation or fork' -q`，期望三条路径行为保持区分。）
- [x] [AC3] 两个并发 Worktree 任务获得不同任务身份、目录和临时分支，主目录未提交修改不进入任一隔离目录。（验证：运行 `python -m pytest tests/test_subagent_worktree.py -k two_isolated_agents -q`，期望三个工作目录状态互不相同且互不覆盖。）
- [x] [AC4] 托管目录位于仓库内但不会出现在可提交状态中。（验证：运行 `python -m pytest tests/worktrees/test_integration.py -k managed_root_is_ignored -q`，期望主工作树状态不报告托管区域。）
- [x] [AC5] 合法单段、嵌套和长度边界名称被接受；大写、空段、`.`、`..`、绝对路径、反斜杠、盘符、UNC、控制字符及超限名称全部拒绝。（验证：运行 `python -m pytest tests/worktrees/test_paths.py -k name -q`，期望完整名称矩阵通过。）
- [x] [AC6] 路径别名、大小写碰撞、区域外链接父级和并发同名请求在危险副作用前被拒绝或安全串行，最终最多一个合法目标。（验证：运行 `python -m pytest tests/worktrees/test_paths.py tests/worktrees/test_lifecycle.py -k 'collision or ancestor or concurrent_same_name' -q`，期望目录/Git 状态无越界变化。）

## 生命周期与变更保护

- [x] [AC7] 从已提交基线按分支、Worktree、必需初始化、就绪状态顺序创建；任一阶段故障只回滚本次资源。（验证：运行 `python -m pytest tests/worktrees/test_lifecycle.py tests/worktrees/test_integration.py -k 'create_order or create_fault' -q`，期望成功顺序与逐阶段故障结果准确。）
- [x] [AC8] 完整既有环境快速恢复时 Git 调用和文件写入均为零；任一身份或就绪信息损坏都被拒绝且不修复。（验证：运行 `python -m pytest tests/worktrees/test_records.py tests/worktrees/test_lifecycle.py -k recovery -q`，期望只读取固定元数据并通过伪造矩阵。）
- [x] [AC9] 进入前后及两个任务并发期间进程 cwd 不变，进入结果包含规范绝对路径、临时分支和隔离身份。（验证：运行 `python -m pytest tests/worktrees/test_lifecycle.py -k enter -q`，期望 cwd 快照始终一致且进入结果完整。）
- [x] [AC10] 任务成功、失败和取消都释放活动占用并执行相同保护检查。（验证：运行 `python -m pytest tests/test_subagent_worktree.py -k terminal -q`，期望三种终态均产生保护结果且没有遗留活动租约。）
- [x] [AC11] 无变更或只有已发布新提交的任务退出后，精确 Worktree 和临时分支被删除，过程中没有 fetch 或网络访问。（验证：运行 `python -m pytest tests/worktrees/test_integration.py -k clean_exit -q`，期望目标资源消失、其他引用保留且网络替身零调用。）
- [x] [AC12] tracked 修改、未忽略 untracked、未发布提交、无远端新提交及远端状态失败都会保留 Worktree，并报告路径、分支和准确原因。（验证：运行 `python -m pytest tests/worktrees/test_integration.py -k protection -q`，期望保护矩阵全部保守。）
- [x] [AC13] 普通删除拒绝受保护目标；逐次显式强制可覆盖真实目标的变更保护，但伪造目标、自动退出和后台清理不能强制。（验证：运行 `python -m pytest tests/worktrees/test_lifecycle.py tests/worktrees/test_janitor.py -k force -q`，期望强制权限仅存在于单次显式调用。）
- [x] [AC14] 重复退出、重复删除和删除已不存在的已知资源返回确定结果，不影响名称相近目录或分支。（验证：运行 `python -m pytest tests/worktrees/test_lifecycle.py -k idempotent -q`，期望重复调用无额外破坏性副作用。）
- [x] [AC15] 创建、进入、退出、显式删除和后台清理竞争同一目标时状态始终唯一，不同 Worktree 可以独立推进。（验证：运行 `python -m pytest tests/worktrees/test_lifecycle.py tests/worktrees/test_integration.py -k 'concurrent or race' -q`，期望无死锁、双重删除或全局锁阻塞。）

## 环境初始化

- [x] [AC16] 安全默认配置处理既定本地配置，未声明 `git_hooks` 时保留 Git 默认 Hook 行为；显式复制、链接和忽略内容规则生效，未声明忽略文件不会自动复制。（验证：运行 `python -m pytest tests/worktrees/test_initializer.py -k defaults -q`，期望目标内容只来自默认或明确规则且 Hook 行为符合配置。）
- [x] [AC17] 必需规则缺失/失败使创建失败并回滚，可选规则缺失/失败保留可用环境且产生有界诊断。（验证：运行 `python -m pytest tests/worktrees/test_initializer.py -k 'required or optional' -q`，期望两类失败语义严格区分。）
- [x] [AC18] 区域外源/目标、链接逃逸、类型不匹配、目标冲突及规则/文件/大小总量超限都不会覆盖或越界。（验证：运行 `python -m pytest tests/worktrees/test_config.py tests/worktrees/test_initializer.py -k 'boundary or limit or conflict or escape' -q`，期望按必需性失败且无危险写入。）
- [x] [AC19] 声明的本地配置和被忽略运行内容按原相对结构出现在 Worktree，主工作目录内容不变。（验证：运行 `python -m pytest tests/worktrees/test_integration.py -k copied_runtime_content -q`，期望源内容和元数据保持不变。）
- [x] [AC20] 类 Unix 与 Windows 场景都创建平台目录链接而非完整副本；链接能力不可用时按规则失败且不回退复制。（验证：运行 `python -m pytest tests/worktrees/test_links.py tests/worktrees/test_initializer.py -k link -q`，期望平台矩阵与失败语义通过。）
- [x] [AC21] Worktree 中项目 Git Hook 生效，但主目录、另一 Worktree、仓库共享设置和用户设置均不被改写。（验证：运行 `python -m pytest tests/worktrees/test_integration.py -k git_hooks -q`，期望 Hook 仅在目标任务环境中生效。）
- [x] [AC22] 任一初始化阶段中断都不会产生可恢复就绪环境；完整环境快速恢复不会修复、覆盖或重建既有初始化产物。（验证：运行 `python -m pytest tests/worktrees/test_initializer.py tests/worktrees/test_lifecycle.py -k 'interrupted or recover_existing_artifacts' -q`，期望不完整环境拒绝、完整环境只读恢复。）

## 子 Agent 运行时与缓存

- [x] [AC23] Worktree 创建成功时只在就绪后调用 Provider；创建失败时零模型请求并进入明确失败终态。（验证：运行 `python -m pytest tests/test_subagent_worktree.py -k startup -q`，期望 Provider 调用顺序和次数准确。）
- [x] [AC24] 文件工具、命令、Hook、Skill、MCP 等工作区操作都显式收到同一 Worktree 绝对路径；并发任务收到各自路径且进程 cwd 不变。（验证：运行 `python -m pytest tests/test_subagent_worktree.py -k explicit_workspace -q`，期望所有捕获的 cwd/root 与任务绑定一致。）
- [x] [AC25] 隔离子 Agent 的系统上下文明确给出 Worktree 绝对路径、临时分支和边界，不把主目录描述为当前工作区。（验证：运行 `python -m pytest tests/test_prompt_builder.py tests/test_subagent_worktree.py -k worktree_prompt -q`，期望上下文内容准确且有界。）
- [x] [AC26] 主目录与两个 Worktree 的同相对路径不同内容，在指令、系统提示来源、项目记忆和普通文件读取时使用不同绝对路径缓存；相同用户源可复用。（验证：运行 `python -m pytest tests/test_subagent_scoped_tools.py tests/test_instruction_loader.py tests/test_memory_manager.py -k cache_isolation -q`，期望无跨目录误命中。）
- [x] [AC27] Worktree 项目指令、配置和项目记忆覆盖主目录版本，用户指令与用户长期记忆仍和主 Agent 一致。（验证：运行 `python -m pytest tests/test_subagent_worktree.py -k project_context -q`，期望项目作用域重载、用户作用域冻结。）
- [x] [AC28] 自动清理和多种保留结果都进入任务查询/最终结果；保留摘要包含路径、分支、原因，并能区分 ready、active、retained、deleting、deleted。（验证：运行 `python -m pytest tests/test_subagent_tasks.py tests/test_subagent_notifications.py -k worktree -q`，期望状态与终态摘要完整且脱敏。）

## 后台清理与安全

- [x] [AC29] 可控时钟下启动立即扫描、此后每小时扫描；单轮至多 256 个候选，多余候选延期且主 Agent 请求不被扫描阻塞。（验证：运行 `python -m pytest tests/worktrees/test_janitor.py -k 'schedule or limit' -q`，期望无需真实等待即可通过所有时间/批次断言。）
- [x] [AC30] 活动、结束未满 24 小时、恰好 24 小时及超过 24 小时的环境中，只有无占用且达到期限者成为删除候选。（验证：运行 `python -m pytest tests/worktrees/test_janitor.py -k expiry -q`，期望时间边界准确。）
- [x] [AC31] 归属安全、任务占用/过期、工作区/提交保护三层必须全部通过才删除候选。（验证：运行 `python -m pytest tests/worktrees/test_janitor.py -k three_layers -q`，期望组合矩阵中只有全真条件删除。）
- [x] [AC32] 标记、Git 状态、远端跟踪、占用或时间信息失败/矛盾时保留目录并记录有界诊断。（验证：运行 `python -m pytest tests/worktrees/test_janitor.py -k conservative -q`，期望所有不确定状态均保留。）
- [x] [AC33] 链接/联接候选、错误分支、被其他 Worktree 使用的分支和需要强制的目录均不会被后台清理跟随或删除。（验证：运行 `python -m pytest tests/worktrees/test_janitor.py tests/worktrees/test_integration.py -k forged -q`，期望外部及受保护资源保持不变。）
- [x] [AC34] 首候选检查超时或删除失败时被保留，后续候选继续检查，主 Agent 和其他子 Agent 不受影响。（验证：运行 `python -m pytest tests/worktrees/test_janitor.py -k timeout -q`，期望扫描报告包含失败且后续成功候选仍被处理。）

## 可靠性、兼容性与安全输出

- [x] [AC35] 所有 Git 与辅助进程均以结构化参数、显式 cwd、受控环境和有效超时启动，生命周期没有隐式网络命令。（验证：运行 `python -m pytest tests/worktrees/test_git.py tests/test_processes.py -k 'runner or environment or no_network' -q`，期望进程记录不含 shell 拼接或 fetch/pull/push。）
- [x] [AC36] 初始化规则/复制上限和后台候选上限在边界处停止或延期，不产生失控遍历或部分就绪环境。（验证：运行 `python -m pytest tests/worktrees/test_config.py tests/worktrees/test_initializer.py tests/worktrees/test_janitor.py -k limit -q`，期望所有资源上限精确生效。）
- [x] [AC37] 路径、标记、配置、Git、Hook 和命令错误中注入的模拟密钥与超长内容不会出现在记录或用户诊断中。（验证：运行 `python -m pytest tests/worktrees tests/test_hook_runtime.py tests/test_command_tool.py -k 'redact or bounded or secret' -q`，期望只显示有界摘要。）
- [x] [AC38] 创建/删除各阶段进程中断后重试，不完整环境不被使用、不产生第二套资源、不删除既有现场，并可由扫描保守识别。（验证：运行 `python -m pytest tests/worktrees/test_lifecycle.py tests/worktrees/test_integration.py -k 'interrupted or retry' -q`，期望重试状态确定且所有权边界保持。）
- [x] [AC39] 并发和竞态测试使用可控时钟、临时仓库、本地裸远端及故障替身，不依赖网络、用户配置或真实等待。（验证：运行 `python -m pytest tests/worktrees -k 'concurrent or race or fixture' -q`，期望测试环境记录所有外部边界均为本地替身。）
- [x] [AC40] 非 Git、Git 不可用及不支持 Worktree 时共享任务保持可用、隔离任务独立失败；Agent、权限、Hook、Skill、Context、Memory、MCP、通知和用量既有回归保持通过。（验证：运行 `python -m pytest tests/test_cli.py tests/test_subagent_runtime.py tests/test_permission_integration.py tests/test_hook_integration.py tests/test_skill_integration.py tests/test_context_integration.py tests/test_continuity_integration.py tests/test_mcp_integration.py tests/test_subagent_notifications.py tests/test_usage_tracking.py -q`，期望全部通过。）

## 端到端场景

- [x] [AC41] 主 Agent 保留未提交修改时并发启动两个隔离子 Agent，二者修改同一相对路径为不同结果，三个目录、工具和缓存互不覆盖。（验证：运行 `python -m pytest tests/test_subagent_worktree.py tests/worktrees/test_integration.py -k two_isolated_agents -q`，期望三份内容及 Git 状态各自独立。）
- [x] [AC42] 一个无变更任务自动清理；另一个有未提交修改的任务被保留，用户定位后提交并推送到本地远端，再执行普通删除时仅目标资源被清理。（验证：运行 `python -m pytest tests/worktrees/test_integration.py -k retained_then_published -q`，期望保护原因先出现、推送后解除且相邻资源不变。）
- [x] [AC43] 异常中断留下完整过期 Worktree 和伪造目录，重启扫描只在真实目标闲置、干净且提交远端可达时清理，伪造目录始终保留并产生安全诊断。（验证：运行 `python -m pytest tests/worktrees/test_integration.py -k restart_janitor -q`，期望真实/伪造候选得到不同且保守的结果。）

## 本地 Worktree 管理

- [x] [AC44] 对可清理、受保护、活动和伪造环境执行 `/worktrees`，只列出归属可信环境，状态/保护原因准确、输出有界且模型工具列表不变。（验证：运行 `python -m pytest tests/test_builtin_commands.py tests/test_conversation.py -k worktrees -q`，期望列表和 schema 断言通过。）
- [x] [AC45] 对干净、修改、未发布、未知、非法和伪造目标执行本地删除；默认只删除干净目标，单次 `--force` 只覆盖真实托管目标的变更保护，不能覆盖归属或活动保护。（验证：运行 `python -m pytest tests/test_builtin_commands.py tests/worktrees/test_integration.py -k worktree_delete -q`，期望完整删除矩阵通过。）

## 架构与集成约束

- [x] 生命周期、工具、Hook、Skill、MCP 和 Janitor 的执行均不会改变进程级 cwd。（验证：运行 `python -m pytest tests/worktrees tests/test_command_tool.py tests/test_hook_actions.py tests/test_skill_process_tool.py tests/test_mcp_transports.py -k cwd -q`，期望每个测试前后 cwd 相同。）
- [x] 快速恢复只解析固定数量的管理元数据，不调用 Git、不写文件、不递归扫描工作树。（验证：运行 `python -m pytest tests/worktrees/test_records.py tests/worktrees/test_lifecycle.py -k recovery_complexity -q`，期望 Git/写入/遍历替身调用数为零或固定上限。）
- [x] 用户级 Hook/MCP/指令/记忆和权限在任务创建时冻结，项目级内容从 Worktree 重载。（验证：运行 `python -m pytest tests/test_subagent_worktree.py -k scope_snapshot -q`，期望委派后的主目录变化不改变用户快照，Worktree 项目变化按任务加载。）
- [x] 任务私有 Hook、MCP、Prompt 和 Context 关闭不会关闭根运行时或其他任务资源。（验证：运行 `python -m pytest tests/test_subagent_worktree.py -k bundle_close -q`，期望关闭顺序有界、重复关闭幂等、其他运行时仍可用。）
- [x] Worktree 任务只能使用冻结名称中可安全重建或明确工作区无关的工具。（验证：运行 `python -m pytest tests/test_subagent_worktree.py -k tool_selection -q`，期望缺失/不可重建工具在模型调用前失败。）
- [x] Git Hook 路径只通过任务环境生效，快速恢复可从已验证相对路径重建同样环境。（验证：运行 `python -m pytest tests/worktrees/test_initializer.py tests/worktrees/test_lifecycle.py -k hooks -q`，期望新建与恢复环境一致且共享 Git 配置未改变。）
- [x] 分支删除使用完整引用和当前预期 OID，引用在检查后移动时不会误删。（验证：运行 `python -m pytest tests/worktrees/test_git.py tests/worktrees/test_lifecycle.py -k conditional_delete -q`，期望竞态目标被拒绝并保留现场。）
- [x] 自动退出和后台清理都只能调用非强制删除路径。（验证：运行 `python -m pytest tests/worktrees/test_lifecycle.py tests/worktrees/test_janitor.py -k never_force -q`，期望所有自动调用记录的 `force` 均为 false。）
- [x] 管理记录不包含凭据、环境变量值、文件/Hook 内容或原始命令输出。（验证：运行 `python -m pytest tests/worktrees/test_records.py -k sensitive -q`，期望持久化 JSON 只含白名单字段。）
- [x] `mewcode.worktrees` 可独立导入且不会依赖子 Agent、命令 UI 或执行仓库发现。（验证：运行 `python -m pytest tests/worktrees/test_config.py -k public_api -q`，期望导入图和副作用断言通过。）
- [x] 现有共享定义式和 Fork 子 Agent 不创建 Worktree，也不承担 Git 前置条件。（验证：运行 `python -m pytest tests/test_subagent_coordinator.py tests/test_subagent_runtime.py -k 'shared or fork' -q`，期望既有路径完全通过。）

## 编译、测试与交付检查

- [x] Python 源码可以完整编译。（验证：运行 `python -m compileall -q src`，期望退出码为 0。）
- [x] Worktree 核心和隔离运行时测试全部通过。（验证：运行 `python -m pytest tests/worktrees tests/test_subagent_worktree.py -q`，期望全部通过且无后台任务泄漏警告。）
- [x] 所有既有与新增测试通过。（验证：运行 `python -m pytest -q`，期望退出码为 0、无失败或错误。）
- [x] 变更没有空白错误或冲突标记。（验证：运行 `git diff --check` 和 `rg -n '^(<<<<<<<|=======|>>>>>>>)' src tests README.md examples`，期望两条检查都不报告问题。）
- [x] Git 状态中不包含托管 Worktree 运行目录或意外生成文件。（验证：运行 `git status --short --ignored`，期望 `.mewcode/worktrees/` 仅作为 ignored 内容出现，提交候选只包含本阶段预期源码、测试、文档和示例。）
- [x] 本阶段没有实现自动 merge/rebase/cherry-pick、同步、安装依赖、提交、推送、fetch 或面向模型的 Worktree 管理工具。（验证：运行 `python -m pytest tests/test_subagent_control.py tests/test_builtin_commands.py tests/worktrees/test_git.py -k 'schema or worktree or no_network' -q`，期望只出现 spec 授权的本地命令和生命周期行为。）
