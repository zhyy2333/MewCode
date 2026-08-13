# 子 Agent 系统 Checklist

> 每一项都通过运行测试、启动应用或观察外部状态验证；不以逐行阅读实现代码作为通过依据。AC 编号对应已批准 `spec.md`。

## 委派入口与角色目录

- [ ] C1 `[AC1]` 固定委派入口不随角色或任务状态变化：分别在无角色、单角色、多角色和已有后台任务时捕获根工具列表，始终只有一个 `agent`，其名称、说明、参数 schema 和工具顺序逐字一致。（验证：运行 `python -m pytest tests/test_subagent_control.py tests/test_subagent_integration.py -q -k "stable_schema or stable_entry"`，期望全部通过。）

- [ ] C2 `[AC2]` 所有非法委派在任务注册和 Provider 调用前失败：覆盖空任务、未知 type、defined 缺失/未知 role、fork 携带 role 及非法 background 组合，任务表保持不变。（验证：运行 `python -m pytest tests/test_subagent_control.py tests/test_subagent_integration.py -q -k "invalid_arguments or launch_boundary"`，期望每例返回稳定参数错误且 fake Provider 零调用。）

- [ ] C3 `[AC3]` 同名有效角色按 project → user → builtin → plugin 选择；逐层移除高优先级文件后，下一层正文依次生效。（验证：运行 `python -m pytest tests/test_subagent_catalog.py -q -k "priority or highest_valid"`，期望四层选择顺序准确。）

- [ ] C4 `[AC4]` 高层无效角色产生安全诊断并回退，任一层出现两个有效同名角色则整个目录装配失败，不依赖扫描顺序。（验证：运行 `python -m pytest tests/test_subagent_catalog.py -q -k "fallback or conflict or duplicate"`，期望回退与 fatal conflict 两类结果明确。）

- [ ] C5 `[AC5]` 严格角色格式拒绝未知/缺失字段、错误类型、非法名称、重复工具、空正文、未知 Profile、max turns 0/101 和未知权限模式，同时接受 max turns 1/100。（验证：运行 `python -m pytest tests/test_subagent_parser.py tests/test_subagent_catalog.py -q`，期望全部格式和边界用例通过。）

- [ ] C6 `[AC6]` 只有启动装配显式注入的 plugin root 会被扫描；未注入时不存在插件目录发现副作用，其他三层照常工作。（验证：运行 `python -m pytest tests/test_subagent_paths.py tests/test_subagent_integration.py -q -k "plugin"`，期望注入前后目录差异只来自给定 root。）

- [ ] C7 `[AC7]` 角色目录为启动快照：运行中修改、新增或删除文件不改变已有目录及后续委派，重启后才采用新内容。（验证：运行 `python -m pytest tests/test_subagent_catalog.py tests/test_subagent_integration.py -q -k "snapshot or no_hot_reload"`，期望同一进程保持旧正文，新进程加载新正文。）

- [ ] C8 `[AC8]` 工具字段按规则收窄：未知/未注册/全局禁止白名单使角色无效；黑白名单冲突时工具被移除；空白名单角色可在无工具 schema 下自然完成。（验证：运行 `python -m pytest tests/test_subagent_catalog.py tests/test_subagent_policy.py tests/test_subagent_runtime.py -q -k "tool or empty"`，期望目录和运行结果符合三种情形。）

- [ ] C9 `[AC9]` `model: inherit` 使用调用主 Agent 的完整 Profile，指定现有 Profile 时完整切换协议、模型、地址和上下文窗口；无同名 Profile 的供应商模型 ID 被拒绝。（验证：运行 `python -m pytest tests/test_subagent_catalog.py tests/test_subagent_control.py tests/test_subagent_runtime.py -q -k "profile or model"`，期望捕获请求使用正确 Profile。）

- [ ] C10 `[AC10]` 定义式首轮只包含基础规则、环境、人工指令、长期记忆、角色正文和独立任务，不含父历史标记、父 Hook 临时提示、父 PLAN 状态或已激活 Skill。（验证：运行 `python -m pytest tests/test_subagent_runtime.py tests/test_prompt_builder.py -q -k "blank_history or agent_role or parent_context"`，期望捕获请求只出现允许来源。）

- [ ] C11 `[AC11]` 多轮定义式请求持续携带相同角色正文，任务只作为独立用户消息出现，完整子消息和工具链不进入主 history 或 Session JSONL。（验证：运行 `python -m pytest tests/test_subagent_runtime.py tests/test_subagent_integration.py -q -k "role_persists or no_history_pollution"`，期望每轮角色存在且存储中无子内部记录。）

- [ ] C12 `[AC12]` 定义式 schema 严格等于父模式、角色白名单、后台名单的交集再移除黑名单/全局禁止项；Fork 保留父 schema，但交集外调用全部策略拒绝，改变输入集合顺序不会扩大执行能力。（验证：运行 `python -m pytest tests/test_subagent_policy.py tests/test_subagent_integration.py -q -k "intersection or order or fork_policy"`，期望 schema/执行集合与数学结果一致。）

- [ ] C13 `[AC13]` 同一读写角色在 DEFAULT 只能获得过滤后允许能力，在 PLAN 只获得只读能力；角色 `permission_mode: allow` 不能恢复写入或命令能力。（验证：运行 `python -m pytest tests/test_subagent_policy.py tests/test_subagent_integration.py -q -k "mode_ceiling or plan_read_only"`，期望所有副作用调用在 PLAN 被裁剪或拒绝。）

- [ ] C14 `[AC14]` 定义式 schema 不含 `agent`、`load_skill` 或其他模型代理入口；Fork 中这些父工具仍可见但调用只得到策略失败，两条路径都无法创建第二层任务。（验证：运行 `python -m pytest tests/test_subagent_policy.py tests/test_subagent_runtime.py tests/test_subagent_integration.py -q -k "nesting or globally_forbidden"`，期望 TaskManager 活动数不因拒绝调用增加。）

- [ ] C15 `[AC15]` Fork 首次请求与触发委派的父实际请求使用相同 Profile；stable/dynamic system、父消息和工具 schema/顺序在新增任务前逐字节一致，未配对的委派助手工具消息未进入 Fork。（验证：运行 `python -m pytest tests/test_subagent_runtime.py tests/test_subagent_integration.py -q -k "fork_prefix or fork_bytes"`，期望所有前缀比较通过。）

## 运行时隔离、权限与终态

- [ ] C16 `[AC16]` 从工具受限父运行发起 Fork 后，首轮逐项保留父实际 schema 与顺序；全局禁止、后台名单外和父模式越界调用分别得到确定策略拒绝，交集内工具仍可正常执行。（验证：运行 `python -m pytest tests/test_subagent_policy.py tests/test_subagent_runtime.py tests/test_subagent_integration.py -q -k "fork_policy or restricted_parent"`，期望展示 schema 不变且执行结果按冻结策略分流。）

- [ ] C17 `[AC17]` Provider 报告缓存读写量时 Fork 任务及进程账本如实记录；Provider 报告未命中或缺失缓存字段时任务仍正常完成、不重试且显示未知而非估算。（验证：运行 `python -m pytest tests/test_subagent_runtime.py tests/test_subagent_integration.py tests/test_usage_tracking.py -q -k "cache or usage"`，期望请求次数不因缓存未命中增加。）

- [ ] C18 `[AC18]` 两个并发子 Agent 的消息、ContextArchive/压缩状态、文件观察、session 权限、决策、轮次、取消和任务 usage 互不串线；取消其中一个不改变另一个的状态或结果。（验证：运行 `python -m pytest tests/test_subagent_runtime.py tests/test_subagent_tasks.py tests/test_subagent_scoped_tools.py tests/test_subagent_permissions.py tests/test_subagent_integration.py -q -k "isolation or concurrent"`，期望每个 task ID 的可变状态只被本任务观察。）

- [ ] C19 `[AC19]` 一个任务写入共享工作区并完成后，另一个任务重新读取能看到新内容；两个任务仍维护各自读取观察，系统不表现为文件快照、事务或自动冲突合并。（验证：运行 `python -m pytest tests/test_subagent_scoped_tools.py tests/test_subagent_integration.py -q -k "shared_workspace or file_observation"`，期望真实文件变化可见且观察缓存对象不同。）

- [ ] C20 `[AC20]` 子 Agent 只复制任务创建时的 project-local/project/user 持久规则，不继承父 session allow；ASK 自动变为 `SUBAGENT_NON_INTERACTIVE` 拒绝并反馈模型继续，显式拒绝和硬安全始终优先。（验证：运行 `python -m pytest tests/test_subagent_permissions.py tests/test_tool_scheduler.py tests/test_subagent_integration.py -q -k "non_interactive or persistent_rules or ask"`，期望无 PermissionChallenge、无规则写入且模型可继续下一轮。）

- [ ] C21 `[AC21]` 并发根 Agent、两个子任务和维护请求的 Hook 事件携带正确 task/parent 关联；每个临时 Hook prompt 只由来源运行消费，同任务内事件和工具结果顺序确定。（验证：运行 `python -m pytest tests/test_hook_runtime.py tests/test_hook_provider.py tests/test_subagent_runtime.py tests/test_subagent_integration.py -q -k "scope or partition or hook_isolation"`，期望各分区消费记录完全分离。）

- [ ] C22 `[AC22]` 两个任务分别显示 Provider 返回的完整/缺失 usage；input/output/cache 字段不串线，进程 UsageLedger 对同一调用只累计一次，缺失字段输出 `n/a`/未知。（验证：运行 `python -m pytest tests/test_subagent_runtime.py tests/test_subagent_tasks.py tests/test_builtin_commands.py tests/test_usage_tracking.py -q -k "usage"`，期望任务合计与底层 Provider 事件一致且账本无双计。）

- [ ] C23 `[AC23]` 自然结束、defined 轮次上限、Fork 独立轮次上限、输出上限、Provider 错误、Context 容量/压缩错误、取消和内部异常都映射为明确终态；上限轮次仍要求的最后一批工具不执行。（验证：运行 `python -m pytest tests/test_agent_runner.py tests/test_subagent_runtime.py tests/test_subagent_tasks.py tests/test_subagent_integration.py -q -k "terminal or limit or error or cancelled"`，期望每例恰好一个终态且末批工具调用次数为零。）

## 前后台转换与任务命令

- [ ] C24 `[AC24]` 定义式默认前台任务在虚拟 10 秒内完成时，`agent` 直接返回有界最终结果、成功状态和任务 usage；主 history 仅出现正常委派调用/结果，不含子中间消息。（验证：运行 `python -m pytest tests/test_subagent_control.py tests/test_subagent_integration.py -q -k "defined_foreground or quick_completion"`，期望无 task notification 且 history 污染检查通过。）

- [ ] C25 `[AC25]` 使用可控单调时钟推进到 10 秒后，前台任务原地变为 BACKGROUND 并返回 task ID；底层驱动、Provider 请求、消息、权限状态和 usage 不取消、不重启、不归零或双计。（验证：运行 `python -m pytest tests/test_subagent_tasks.py tests/test_subagent_control.py tests/test_subagent_integration.py -q -k "timeout_detach or auto_background"`，期望驱动创建次数和首请求次数均为一。）

- [ ] C26 `[AC26]` defined `background=true` 与 fork 都在等待首次模型响应前返回唯一不可预测 task ID；Fork 始终标记 BACKGROUND，任何前台覆盖参数都被拒绝。（验证：运行 `python -m pytest tests/test_subagent_control.py tests/test_subagent_tasks.py tests/test_subagent_integration.py -q -k "immediate_background or fork_background"`，期望阻塞 fake Provider 尚未释放时 ToolResult 已返回。）

- [ ] C27 `[AC27]` defined 前台运行时按 `Ctrl+B` 会立即原地转后台并显示 task ID；无前台任务时只显示简短提示；`Ctrl+C` 仍取消当前前台运行，且不取消已解除的后台任务。（验证：运行 `python -m pytest tests/test_terminal.py tests/test_repl.py tests/test_subagent_tasks.py tests/test_subagent_integration.py -q -k "ctrl_b or ctrl_c or manual_detach"`，期望输入消费者无残留且两种按键语义分离。）

- [ ] C28 `[AC28]` REGISTERED、RUNNING、COMPLETED、FAILED、CANCELLED 任务快照记录 kind、role、父运行、placement、时间、状态、有界结果/错误和 usage；UUID 在进程内唯一且不是简单递增序列。（验证：运行 `python -m pytest tests/test_subagent_tasks.py tests/test_subagent_integration.py -q -k "snapshot or status or uuid"`，期望五种状态字段完整且 ID 唯一。）

- [ ] C29 `[AC29]` 同时保持 8 个活动任务时，并发超额委派全部在 Provider 前明确失败，观测到的活动数从不超过 8；任一任务终态后可再注册一个。（验证：运行 `python -m pytest tests/test_subagent_tasks.py tests/test_subagent_integration.py -q -k "capacity or eight or atomic"`，期望成功注册数恰好等于上限且失败任务零驱动调用。）

- [ ] C30 `[AC30]` `/tasks` 将活动/终态清楚分组且仅显示安全摘要；`/task <id>` 对活动任务立即返回有界进度，对终态显示结果/错误和 usage，对未知 ID 返回确定错误。（验证：运行 `python -m pytest tests/test_builtin_commands.py tests/test_conversation.py tests/test_subagent_integration.py -q -k "tasks_command or task_detail"`，期望所有命令本地完成、无 Provider 请求或 history 写入。）

- [ ] C31 `[AC31]` `/task cancel <id>` 只对活动任务请求一次取消；终态、未知和重复取消无副作用；完成/取消同时竞争时仅首个终态获胜，结果、通知和 usage 不重复。（验证：运行 `python -m pytest tests/test_builtin_commands.py tests/test_subagent_tasks.py tests/test_subagent_notifications.py tests/test_subagent_integration.py -q -k "cancel or terminal_race"`，期望每个 task 一个终态且最多一个通知。）

- [ ] C32 `[AC32]` 超过 128 个已投递终态后只保留最近 128 条；活动任务和未投递通知的终态始终可查，淘汰不会删除或跳过待通知结果。（验证：运行 `python -m pytest tests/test_subagent_tasks.py tests/test_subagent_notifications.py -q -k "retention or 128 or eviction"`，期望淘汰顺序只覆盖最早已投递终态。）

## 通知、生命周期、安全与兼容性

- [ ] C33 `[AC33]` 后台任务 completed、failed、cancelled 时各向终端即时输出一条含短 task ID 与终态的单行摘要；对应有界结果/错误/usage 各自只入通知队列一次。（验证：运行 `python -m pytest tests/test_subagent_notifications.py tests/test_subagent_tasks.py tests/test_terminal.py tests/test_repl.py -q -k "terminal_event or notify or summary"`，期望每个终态恰好一条摘要和一个队列项。）

- [ ] C34 `[AC34]` 后台任务在根 Agent 仍运行时完成，其通知进入下一 iteration；根 Agent 空闲时完成，其通知进入下一用户任务首轮。（验证：运行 `python -m pytest tests/test_request_boundary.py tests/test_conversation.py tests/test_subagent_integration.py -q -k "notification_timing or next_iteration or next_user"`，期望捕获请求中的通知出现位置准确。）

- [ ] C35 `[AC35]` 待通知期间先运行子 Agent、Context compact、自动 Memory 更新和其他维护请求，队列保持未消费；只有根真实任务请求能取得批次。（验证：运行 `python -m pytest tests/test_request_boundary.py tests/test_conversation.py tests/test_subagent_integration.py -q -k "maintenance or notification_consumer"`，期望维护请求内容无通知且随后根请求仍能收到。）

- [ ] C36 `[AC36]` 同时完成 20 个任务且结果总量超过 64 KiB 时，首个根请求按完成顺序最多收到 16 条且编码总量不超 64 KiB；剩余条目在后续请求继续投递，每条最多一次。（验证：运行 `python -m pytest tests/test_subagent_notifications.py tests/test_subagent_integration.py -q -k "batch or budget or twenty"`，期望跨批次 ID 序列无重复、无丢失、顺序不变。）

- [ ] C37 `[AC37]` 通知投递前后主 `Conversation.messages()` 和 Session JSONL 均无通知内容；应用重启后任务表/通知队列为空，旧结果不显示、不注入。（验证：运行 `python -m pytest tests/test_conversation.py tests/test_subagent_integration.py -q -k "no_persistence or process_boundary or jsonl"`，期望磁盘会话仅包含主对话记录。）

- [ ] C38 `[AC38]` 有活动任务和待通知时执行 `/reset` 会取消任务并清空任务表、Hook 分区及通知；重置后根请求收不到旧结果。正常退出在虚拟 5 秒预算内收敛，失响应任务被强制结束并安全诊断。（验证：运行 `python -m pytest tests/test_subagent_tasks.py tests/test_conversation.py tests/test_subagent_integration.py -q -k "reset or close_timeout or shutdown"`，期望无遗留 task、通知或 ContextArchive。）

- [ ] C39 `[AC39]` 角色文件 64 KiB、每来源 256 候选、正文总计 1 MiB、task 64 KiB 和单结果 20,000 字符边界按规定接受；超限时拒绝或明确截断，诊断不含 API Key、认证头、完整工具参数、模型内部内容或原始 Provider 响应。（验证：运行 `python -m pytest tests/test_subagent_paths.py tests/test_subagent_parser.py tests/test_subagent_catalog.py tests/test_subagent_control.py tests/test_subagent_notifications.py tests/test_subagent_integration.py -q -k "limit or oversized or truncate or redact"`，期望所有边界及去敏断言通过。）

- [ ] C40 `[AC40]` 包含伪系统指令的子结果只出现在 `<untrusted-subagent-results>` 边界内，不能改变 stable system、人工指令、权限模式或实际工具上限。（验证：运行 `python -m pytest tests/test_subagent_notifications.py tests/test_request_boundary.py tests/test_subagent_integration.py -q -k "untrusted or injection"`，期望提示结构和执行策略均保持原值。）

- [ ] C41 `[AC41]` 分别注入单任务 Provider、Hook、工具和通知处理失败，只让来源任务安全失败或通知延后；主 REPL、主 history、Session 文件、其他任务和 UsageLedger 继续可用。（验证：运行 `python -m pytest tests/test_subagent_runtime.py tests/test_subagent_tasks.py tests/test_subagent_notifications.py tests/test_subagent_integration.py tests/test_repl.py -q -k "failure_isolation or provider_failure or hook_failure or tool_failure"`，期望后续独立任务和主消息仍成功。）

- [ ] C42 `[AC42]` 在无用户角色、无任务、无通知时，普通对话、PLAN、权限、Hook、Context、Memory、MCP 和 Skill 公共行为保持兼容；除固定 AgentTool 和本地命令外无额外模型请求、常驻任务、日志或会话写入。（验证：运行 `python -m pytest tests/test_agent_runner.py tests/test_plan_mode.py tests/test_permission_integration.py tests/test_hook_integration.py tests/test_context_integration.py tests/test_continuity_integration.py tests/test_mcp_integration.py tests/test_skill_integration.py tests/test_conversation.py tests/test_repl.py -q`，期望全部通过且 no-task 探针记录零额外副作用。）

## 端到端场景

- [ ] C43 `[AC43]` 只读审查角色端到端：根 Agent 发起 defined 委派，子任务从空白历史按限定只读工具执行并在 10 秒内完成，根只收到最终 ToolResult 后继续回答。（验证：运行 `python -m pytest tests/test_subagent_integration.py -q -k "defined_foreground"`，期望角色、工具、权限、history 和 usage 全链路断言通过。）

- [ ] C44 `[AC44]` 长任务端到端：defined 任务自动或按 `Ctrl+B` 原地转后台，根先完成当前回复；子任务终态后即时摘要，下一根请求只收到一次通知，用户可查询状态/usage 并取消另一活动任务。（验证：运行 `python -m pytest tests/test_subagent_integration.py -q -k "background or notification or reset"`，期望前后台、命令、取消和通知链路全部通过。）

- [ ] C45 `[AC45]` Fork 端到端：从长历史和稳定工具集发起 Fork，调用立即返回后台 ID；Fork 首轮保留父缓存前缀且运行状态独立，禁止嵌套委派，完成后只通过一次性通知返回根 Agent。（验证：运行 `python -m pytest tests/test_subagent_runtime.py tests/test_subagent_integration.py -q -k "fork_prefix or fork_bytes or fork_nesting"`，期望缓存条件、隔离、安全与通知断言全部通过。）

## 实现完整性与架构集成

- [ ] C46 子 Agent 公开模块、内置角色和示例角色都可导入/发现/解析，`agent`、`/tasks`、`/task` 可从实际 CLI 入口调用。（验证：运行 `python -m pytest tests/test_subagent_catalog.py tests/test_subagent_control.py tests/test_subagent_integration.py tests/test_builtin_commands.py -q`，期望所有真实入口与资源测试通过。）

- [ ] C47 通用层依赖方向保持单向：Agent、Provider、Hook、Permission、Context、Prompt 和 Skill 通用模块不反向导入 `mewcode.subagents`。（验证：运行 `rg -n "mewcode\.subagents" src/mewcode/agent src/mewcode/providers src/mewcode/hooks src/mewcode/permissions src/mewcode/context src/mewcode/prompting src/mewcode/skills`，期望无匹配结果、退出码为 1。）

- [ ] C48 子系统核心层不依赖应用交互层：角色、策略、权限、工具代理、通知和任务状态机不导入 Conversation、REPL 或 CLI。（验证：运行 `rg -n "mewcode\.(conversation|repl|cli)|from \.{1,2}(conversation|repl|cli)" src/mewcode/subagents/models.py src/mewcode/subagents/paths.py src/mewcode/subagents/parser.py src/mewcode/subagents/catalog.py src/mewcode/subagents/policy.py src/mewcode/subagents/permissions.py src/mewcode/subagents/scoped_tools.py src/mewcode/subagents/notifications.py src/mewcode/subagents/tasks.py`，期望无匹配结果、退出码为 1。）

- [ ] C49 Provider 包装顺序固定为 Hook → RequestBoundary → UsageTracking → 真实 Provider，根、子任务和维护调用通过作用域选择消费/捕获行为，且同一 Profile 只缓存一套包装栈。（验证：运行 `python -m pytest tests/test_hook_provider.py tests/test_request_boundary.py tests/test_usage_tracking.py tests/test_subagent_integration.py -q -k "order or boundary or provider_stack"`，期望转换顺序和调用计数全部通过。）

- [ ] C50 所有公开子任务接口都有真实调用方：TaskManager 被 Coordinator/Conversation 使用，通知被根请求边界使用，终态事件被 REPL 监视器使用，Terminal 控制被 `_consume` 使用。（验证：运行 `python -m pytest tests/test_subagent_control.py tests/test_conversation.py tests/test_repl.py tests/test_subagent_integration.py -q`，期望集成调用链全部通过且无仅测试使用的公开路径。）

- [ ] C51 生命周期依赖顺序可观察：主运行先取消，子任务随后收敛，Memory/Session/Skill/Context 后关，Hook 最后关闭；重复 close 幂等且无 pending asyncio task。（验证：运行 `python -m pytest tests/test_conversation.py tests/test_repl.py tests/test_subagent_integration.py -q -k "close or shutdown or lifecycle"`，期望调用日志顺序正确且事件循环无遗留任务。）

## 构建、测试与交付一致性

- [ ] C52 所有新建子系统单元测试通过。（验证：运行 `python -m pytest tests/test_subagent_paths.py tests/test_subagent_parser.py tests/test_subagent_catalog.py tests/test_subagent_policy.py tests/test_subagent_permissions.py tests/test_subagent_scoped_tools.py tests/test_subagent_notifications.py tests/test_subagent_tasks.py tests/test_subagent_runtime.py tests/test_subagent_control.py tests/test_request_boundary.py -q`，期望全部通过。）

- [ ] C53 所有受影响既有模块的定向回归通过。（验证：运行 `python -m pytest tests/test_agent_runner.py tests/test_tool_scheduler.py tests/test_hook_runtime.py tests/test_hook_provider.py tests/test_prompt_builder.py tests/test_context_manager.py tests/test_skill_runtime.py tests/test_builtin_commands.py tests/test_conversation.py tests/test_repl.py tests/test_terminal.py -q`，期望全部通过。）

- [ ] C54 Anthropic 与 OpenAI 的父/Fork 实际适配请求在新增 task 前逐字节一致，同时 cache usage 只采用 Provider 报告值。（验证：运行 `python -m pytest tests/test_subagent_integration.py -q -k "anthropic_fork_bytes or openai_fork_bytes"`，期望两种协议的前缀和 cache key/cache block 比较通过。）

- [ ] C55 完整测试套件无失败。（验证：运行 `python -m pytest -q`，期望全部测试通过；记录通过、跳过数量和总耗时作为验收证据。）

- [ ] C56 交付 diff 不含空白错误或用户无关改动。（验证：运行 `git diff --check`，期望无输出且退出码为 0；再运行 `git status --short`，期望只出现本阶段文件及用户原有且未被改动的无关状态。）

- [ ] C57 README、内置 explore 和 code-reviewer 示例与实际格式/操作一致，明确七字段、优先级、Profile、defined/fork、`Ctrl+B`、任务命令、安全边界和非目标。（验证：运行 `rg -n "tools:|disallowed_tools:|model:|max_turns:|permission_mode:|/tasks|/task|Ctrl\+B|Fork|Worktree" README.md examples/agents/code-reviewer.md src/mewcode/subagents/builtin/explore.md`，期望所有主题均有匹配；运行 `python -m pytest tests/test_subagent_parser.py tests/test_subagent_catalog.py -q`，期望两个 Markdown 资源可由生产逻辑加载。）

- [ ] C58 范围保持在本阶段边界：没有 Worktree/容器隔离、团队编排、嵌套 Agent、后台持久化/恢复、角色热重载、插件扫描安装、交互式子权限、模型任务查询工具或 Hook Agent 动作实现。（验证：运行 `git diff --name-only`，期望对照 `docs/phase-12-subagent-system/spec.md` 的“不做的事情”后无范围外模块或配置；运行 `python -m pytest tests/test_subagent_integration.py -q -k "no_hot_reload or no_persistence or fork_nesting"`，期望边界测试通过。）

- [ ] C59 Python 测试收集阶段无语法、导入或插件错误；项目未配置独立 lint 工具，因此不臆造新的 lint 依赖，代码风格最低门禁由测试收集与 `git diff --check` 承担。（验证：运行 `python -m pytest --collect-only -q`，期望完整测试集合成功收集且退出码为 0；运行 `rg -n "ruff|flake8|pylint|mypy" pyproject.toml`，期望无匹配结果、退出码为 1。）

- [ ] C60 `[N3]` 角色正文、任务状态和完成通知只进入 dynamic system，任何状态变化都不改变稳定系统提示前缀。（验证：运行 `python -m pytest tests/test_prompt_builder.py tests/test_request_boundary.py tests/test_subagent_notifications.py -q -k "stable or dynamic or agent_role"`，期望 stable system 字节比较不变且动态内容位置正确。）

- [ ] C61 `[N14]` 任务创建时冻结 Profile、持久权限规则、工具视图、角色定义和后台能力名单；运行中修改父模式、规则、注册表或角色文件不改变既有任务。（验证：运行 `python -m pytest tests/test_subagent_control.py tests/test_subagent_runtime.py tests/test_subagent_integration.py -q -k "frozen or snapshot"`，期望修改前后同一任务的请求和策略完全一致。）

- [ ] C62 `[N23]` 时间、并发、Provider、Hook、权限、工具和终端输入边界均可被测试替身控制；自动转后台与竞态测试不访问网络且不真实等待 10 秒。（验证：运行 `python -m pytest tests/test_subagent_tasks.py tests/test_subagent_integration.py tests/test_terminal.py -q -k "timeout or race or control"`，期望测试使用可控 event/clock 完成且无网络依赖。）

## 验收记录要求

执行本清单时，对每个条目记录：实际命令、退出码、关键观察结果，以及测试通过/跳过/失败数量。任何失败项必须先修复并重新执行对应验证；只有 C1–C62 全部通过后，才能宣告本阶段验收完成。
