# 子 Agent 系统 Tasks

## 文件清单

### 新建功能文件

| 操作 | 文件 | 职责 |
|---|---|---|
| 新建 | `src/mewcode/subagents/__init__.py` | 汇总子 Agent 功能层的稳定公共导出。 |
| 新建 | `src/mewcode/subagents/models.py` | 定义角色、任务、通知、诊断、限制常量和异常。 |
| 新建 | `src/mewcode/subagents/paths.py` | 发现项目、用户、内置和注入插件的角色候选。 |
| 新建 | `src/mewcode/subagents/parser.py` | 严格解析 YAML frontmatter 与 Markdown 正文。 |
| 新建 | `src/mewcode/subagents/catalog.py` | 编译层级覆盖、无效回退且不可变的角色目录。 |
| 新建 | `src/mewcode/subagents/policy.py` | 计算定义式/Fork 式冻结执行策略。 |
| 新建 | `src/mewcode/subagents/permissions.py` | 构造隔离且非交互的子任务权限控制器。 |
| 新建 | `src/mewcode/subagents/scoped_tools.py` | 创建 schema 等价工具代理及任务级文件读取观察。 |
| 新建 | `src/mewcode/subagents/notifications.py` | 管理有界、去重、一次性的完成通知。 |
| 新建 | `src/mewcode/subagents/tasks.py` | 实现任务状态机、前后台转换、取消、事件和保留。 |
| 新建 | `src/mewcode/subagents/runtime.py` | 为每个任务组装并清理隔离 Agent 运行时。 |
| 新建 | `src/mewcode/subagents/coordinator.py` | 把委派调用编译成冻结的任务启动说明。 |
| 新建 | `src/mewcode/subagents/control.py` | 提供 schema 固定的 `agent` 控制工具与委派操作。 |
| 新建 | `src/mewcode/subagents/builtin/explore.md` | 提供内置只读代码探索角色。 |
| 新建 | `src/mewcode/providers/request_boundary.py` | 提供 ContextVar 请求边界及透明 Provider 包装。 |
| 新建 | `examples/agents/code-reviewer.md` | 给出七字段角色定义示例。 |

### 修改功能文件

| 操作 | 文件 | 职责 |
|---|---|---|
| 修改 | `src/mewcode/agent/control.py` | 增加 `AgentControlContext` 并扩展控制工具协议。 |
| 修改 | `src/mewcode/agent/events.py` | 增加安全、有界的子任务进度事件。 |
| 修改 | `src/mewcode/agent/runner.py` | 支持实际请求快照、Fork seed、真实 loop limit 和策略上下文。 |
| 修改 | `src/mewcode/agent/scheduler.py` | 插入执行策略并向控制工具传递本轮上下文。 |
| 修改 | `src/mewcode/agent/__init__.py` | 导出新增通用 Agent 类型。 |
| 修改 | `src/mewcode/providers/__init__.py` | 导出请求边界协议、绑定器和包装器。 |
| 修改 | `src/mewcode/hooks/runtime.py` | 增加按 task ID 分区的 Hook prompt 队列。 |
| 修改 | `src/mewcode/hooks/events.py` | 增加安全的任务及父运行关联字段。 |
| 修改 | `src/mewcode/hooks/provider.py` | 固定 Hook 与 RequestBoundary 的转换顺序契约。 |
| 修改 | `src/mewcode/prompting/models.py` | 为动态角色正文增加 `agent_role`。 |
| 修改 | `src/mewcode/prompting/sections.py` | 注册动态 `Agent Role` 区段。 |
| 修改 | `src/mewcode/prompting/builder.py` | 合并并渲染角色区段而不改变稳定前缀。 |
| 修改 | `src/mewcode/permissions/models.py` | 增加策略拒绝和非交互拒绝来源。 |
| 修改 | `src/mewcode/context/archive.py` | 允许任务归档跳过进程级 stale cleanup。 |
| 修改 | `src/mewcode/context/manager.py` | 增加 Fork 首轮只检查容量、不压缩的路径。 |
| 修改 | `src/mewcode/skills/control.py` | 适配控制工具上下文参数并保持原行为。 |
| 修改 | `src/mewcode/skills/runtime.py` | 根 Skill 视图保留 `agent`，isolated 视图不泄漏。 |
| 修改 | `src/mewcode/commands/contracts.py` | 扩展任务查询、取消和转后台协议。 |
| 修改 | `src/mewcode/commands/builtin.py` | 注册并格式化 `/tasks` 与 `/task`。 |
| 修改 | `src/mewcode/conversation.py` | 接入任务门面、根通知以及 reset/close 顺序。 |
| 修改 | `src/mewcode/terminal.py` | 增加 `Ctrl+B` 读取和 prompt-safe 异步通知。 |
| 修改 | `src/mewcode/repl.py` | 并行消费主 Agent、运行控制键和任务终态事件。 |
| 修改 | `src/mewcode/cli.py` | 完成角色、Provider、任务、工具和生命周期装配。 |
| 修改 | `README.md` | 记录角色格式、委派方式、任务命令、安全边界和非目标。 |

### 新建测试文件

| 操作 | 文件 | 职责 |
|---|---|---|
| 新建 | `tests/test_subagent_paths.py` | 验证来源发现、排序、符号链接和候选限制。 |
| 新建 | `tests/test_subagent_parser.py` | 验证严格字段、UTF-8、大小、正文和边界值。 |
| 新建 | `tests/test_subagent_catalog.py` | 验证四层覆盖、回退、冲突、Profile/工具及总量。 |
| 新建 | `tests/test_subagent_policy.py` | 验证收窄交集、硬拒绝和 Fork schema 不变。 |
| 新建 | `tests/test_subagent_permissions.py` | 验证持久规则快照、空 session 和 ASK 自动拒绝。 |
| 新建 | `tests/test_subagent_scoped_tools.py` | 验证透明代理、读取观察和跨任务隔离。 |
| 新建 | `tests/test_subagent_notifications.py` | 验证去重、顺序、预算、截断和不可信边界。 |
| 新建 | `tests/test_subagent_tasks.py` | 验证并发、竞态、转换、取消、保留及关闭。 |
| 新建 | `tests/test_subagent_runtime.py` | 验证定义式/Fork 运行时隔离与清理。 |
| 新建 | `tests/test_subagent_control.py` | 验证固定 schema、参数组合和前后台工具结果。 |
| 新建 | `tests/test_subagent_integration.py` | 验证 CLI 装配及三条端到端场景。 |
| 新建 | `tests/test_request_boundary.py` | 验证 ContextVar 隔离、透明转发和包装顺序。 |

### 扩展现有测试文件

| 操作 | 文件 | 新增验证职责 |
|---|---|---|
| 修改 | `tests/test_agent_runner.py` | 实际请求上下文、Fork seed、缺失快照和 loop limit。 |
| 修改 | `tests/test_tool_scheduler.py` | hard preflight → policy → Hook → permission 顺序。 |
| 修改 | `tests/test_hook_runtime.py` | 全局兼容、task 分区、总预算和清理。 |
| 修改 | `tests/test_hook_provider.py` | Hook 注入先于 RequestBoundary。 |
| 修改 | `tests/test_prompt_builder.py` | 动态 Agent Role 与稳定前缀。 |
| 修改 | `tests/test_context_manager.py` | preserve-prefix 容量成功/失败且不调用 compactor。 |
| 修改 | `tests/test_skill_runtime.py` | 根视图保留与 isolated 视图隔离。 |
| 修改 | `tests/test_builtin_commands.py` | 新命令解析、usage、格式化和错误。 |
| 修改 | `tests/test_conversation.py` | 任务门面、通知及 reset/close 顺序。 |
| 修改 | `tests/test_repl.py` | `Ctrl+B`、权限输入互斥、摘要和监视器关闭。 |
| 修改 | `tests/test_terminal.py` | 运行控制 reader、取消和 prompt-safe notify。 |

`pyproject.toml` 不修改：现有 Python 3.11、PyYAML、prompt-toolkit、asyncio 和 pytest 已覆盖实现与验证需要，Hatch 的 `src/mewcode` 包目标会沿用现有方式包含包内 Markdown。

## 任务分组与依赖骨架

| 批次 | 范围 | 依赖 | 完成出口 |
|---|---|---|---|
| B1 | 通用 Agent 控制上下文、请求边界和 Provider 顺序 | 无 | 通用层回归通过，且不导入 `subagents`。 |
| B2 | Prompt、Hook、权限、Context、Skill 通用扩展 | B1 | 所有新增扩展在无子任务时保持兼容。 |
| B3 | 角色模型、路径、解析和目录 | B2 | 四层目录可冻结，错误与资源上限可验证。 |
| B4 | 执行策略、非交互权限和任务工具代理 | B2、B3 | 能冻结定义式/Fork 能力且隔离任务观察。 |
| B5 | 通知队列和任务状态机 | B3 | 前后台、终态、竞态、容量、保留和清理可独立测试。 |
| B6 | 隔离运行时、协调器和固定 Agent 工具 | B1–B5 | 两类委派均可通过测试替身跑到确定结果。 |
| B7 | 本地命令、Conversation、终端和 REPL | B5、B6 | 用户可查、可取消、可手动转后台并收到摘要。 |
| B8 | CLI 装配、内置/示例角色和文档 | B3–B7 | 实际入口拥有冻结角色目录和稳定 Agent 工具。 |
| B9 | 集成、缓存前缀、端到端和全量回归 | B1–B8 | 三条 E2E 与完整 `pytest` 通过。 |

批次内部仍按后续 T 编号顺序执行；只允许在依赖批次完成并验证后进入下一批。B3 与 B1 后半段可独立准备测试夹具，但合入顺序以上表为准，避免通用层反向依赖功能层。

## B1：通用 Agent 控制上下文与请求边界

### T1：建立请求边界作用域

**文件：** `src/mewcode/providers/request_boundary.py`、`tests/test_request_boundary.py`  
**依赖：** 无

**步骤：**
1. 定义 `ProviderRequestBoundary.prepare(ModelRequest) -> ModelRequest`、当前边界 ContextVar 和成对 bind/reset 的上下文管理器。
2. 为未绑定、嵌套绑定和异常退出恢复编写测试，确保作用域不泄漏。
3. 增加两个 asyncio 任务并发绑定不同边界的测试，证明 ContextVar 隔离。

**验证：** 运行 `python -m pytest tests/test_request_boundary.py -q`，期望作用域、嵌套恢复和并发隔离用例全部通过。

### T2：实现透明 RequestBoundaryProvider

**文件：** `src/mewcode/providers/request_boundary.py`、`tests/test_request_boundary.py`  
**依赖：** T1

**步骤：**
1. 实现 `RequestBoundaryProvider`：每次 `stream_reply` 只调用一次当前边界的 `prepare`，并把返回请求交给内层 Provider。
2. 未绑定边界时把原 `ModelRequest` 对象直接传给内层 Provider，不做复制。
3. 原样转发事件，并把 `assistant_messages`、`tool_result_messages` 委派给内层 Provider。

**验证：** 运行 `python -m pytest tests/test_request_boundary.py -q`，期望请求转换次数、对象透传、流事件和消息转换委派用例全部通过。

### T3：固定 Hook 与请求边界的包装顺序

**文件：** `src/mewcode/providers/__init__.py`、`src/mewcode/hooks/provider.py`、`tests/test_request_boundary.py`、`tests/test_hook_provider.py`  
**依赖：** T2

**步骤：**
1. 从 `mewcode.providers` 导出请求边界协议、绑定器和包装器。
2. 用测试 Provider 组成 `HookedProvider(RequestBoundaryProvider(inner))`，记录每层看到的请求。
3. 断言 `message.before` 产生的 Hook Context 已出现在边界收到的请求中，且空 Hook 快速路径仍经过边界。

**验证：** 运行 `python -m pytest tests/test_request_boundary.py tests/test_hook_provider.py -q`，期望边界总在 Hook 注入之后、真实 Provider 之前运行。

### T4：定义通用控制上下文与执行策略协议

**文件：** `src/mewcode/agent/control.py`、`src/mewcode/permissions/models.py`、`src/mewcode/agent/__init__.py`、`tests/test_tool_scheduler.py`  
**依赖：** 无

**步骤：**
1. 按 Plan 定义不可变 `AgentControlContext`，包含 run、iteration、mode、Profile、权限模式、真实 loop limit、安全集合和父 `ModelRequest`。
2. 定义 `ToolPolicyDecision`、`ToolExecutionPolicy` 以及默认全允许实现；这些通用类型不得导入 `mewcode.subagents`。
3. 把 `AgentControlTool.control_operation` 签名改为接收 arguments 与 context，并增加 `PermissionSource.SUBAGENT_POLICY`。
4. 更新公共导出并用静态测试替身验证协议字段和默认策略。

**验证：** 运行 `python -m pytest tests/test_tool_scheduler.py -q`，期望新协议可由测试替身实现，现有调度用例仍通过。

### T5：把执行策略插入工具调度顺序

**文件：** `src/mewcode/agent/scheduler.py`、`tests/test_tool_scheduler.py`  
**依赖：** T4

**步骤：**
1. 让 `ToolScheduler`/`ToolSchedule` 接收默认全允许的 `ToolExecutionPolicy`，保持普通调用方兼容。
2. 在参数验证和硬安全 preflight 之后、`tool.before` Hook 之前执行策略。
3. 策略拒绝时产生稳定的 `SUBAGENT_POLICY` 决策和失败 `ToolResult`，跳过 before Hook、权限与真实工具，但仍恰好调用一次 `tool.after(denied)`。
4. 增加顺序探针，覆盖参数错误、硬拒绝、策略拒绝、Hook 拒绝和正常允许五条路径。

**验证：** 运行 `python -m pytest tests/test_tool_scheduler.py -q`，期望调度顺序严格为 validation → hard preflight → policy → Hook → permission → execute。

### T6：向控制工具传递本轮上下文

**文件：** `src/mewcode/agent/scheduler.py`、`src/mewcode/skills/control.py`、`tests/test_tool_scheduler.py`、`tests/test_skill_runtime.py`  
**依赖：** T4、T5

**步骤：**
1. 让 `ToolScheduler.schedule` 与 `ToolSchedule` 保存该响应批次唯一的 `AgentControlContext`。
2. 调用控制工具时传入同一上下文对象；普通工具路径不读取该对象。
3. 更新 `LoadSkillTool.control_operation` 签名并明确忽略 context，保持 Skill 参数和运行结果不变。
4. 测试多控制调用共享本轮上下文、下一轮使用新上下文，并验证取消仍转发到活动控制操作。

**验证：** 运行 `python -m pytest tests/test_tool_scheduler.py tests/test_skill_runtime.py -q`，期望控制上下文身份、取消链和既有 Skill 控制行为全部通过。

### T7：捕获每次实际 Provider 请求

**文件：** `src/mewcode/providers/request_boundary.py`、`src/mewcode/agent/runner.py`、`tests/test_request_boundary.py`、`tests/test_agent_runner.py`  
**依赖：** T3、T6

**步骤：**
1. 增加一次写入的 `RequestSnapshotSlot` 和只捕获、不转换的 `CaptureOnlyRequestBoundary`。
2. `AgentRun` 每次真实 Provider 调用前创建新槽并在调用期间绑定边界；Provider 返回后只把该槽用于当前响应的工具批次。
3. 没有经过 `RequestBoundaryProvider`、槽为空或重复写入时返回安全的控制上下文错误，不从历史拼装近似请求。
4. 测试 Hook 注入、Context 处理后的最终请求被捕获，并证明上一 iteration 的槽不能被下一 iteration 复用。

**验证：** 运行 `python -m pytest tests/test_request_boundary.py tests/test_agent_runner.py -q`，期望捕获值等于真实内层 Provider 请求，空槽和陈旧槽用例确定失败。

### T8：生成完整 AgentControlContext

**文件：** `src/mewcode/agent/runner.py`、`tests/test_agent_runner.py`、`tests/test_tool_scheduler.py`  
**依赖：** T7

**步骤：**
1. 为 `AgentRunner` 增加有兼容默认值的 Profile 名、权限模式 supplier 和允许 `ToolSafety` 集合输入。
2. 在每轮响应调度前，用当前 run ID、iteration、mode、实际 Profile、权限模式、真实 loop limit、安全集合和捕获请求构造 `AgentControlContext`。
3. PLAN 模式上下文报告本次实际 `plan_max_investigation_iterations + 1` loop limit，DIRECT/EXECUTE 报告 `max_iterations`；上下文在创建后不可变。
4. 验证普通无控制工具运行不增加 Provider 请求，也不改变现有 history commit 行为。

**验证：** 运行 `python -m pytest tests/test_agent_runner.py tests/test_tool_scheduler.py -q`，期望各模式上下文字段正确且现有 Agent 循环测试无回归。

### T9：支持 ForkRequestSeed 首轮请求

**文件：** `src/mewcode/agent/control.py`、`src/mewcode/agent/runner.py`、`src/mewcode/agent/__init__.py`、`tests/test_agent_runner.py`  
**依赖：** T8

**步骤：**
1. 按 Plan 定义不可变 `ForkRequestSeed`，保存父 Profile、实际请求、父 run/iteration、权限模式、独立轮次上限及安全集合。
2. 为 `AgentRunner.start` 增加可选 seed；默认路径完全沿用 PromptBuilder，seed 路径复用父 prompt、消息、工具顺序和 max output，并只在末尾追加新任务用户消息。
3. seed 子运行强制使用自己的空 history commit sink 和独立轮次计数，不纳入产生委派调用的助手工具消息。
4. 测试首次请求前缀、第二轮正常追加子运行消息，以及 Profile 不一致/空任务的安全失败。

**验证：** 运行 `python -m pytest tests/test_agent_runner.py -q`，期望 seed 首次请求除末尾任务外与父请求值一致，普通 Runner 用例保持通过。

### T10：增加有界子任务进度事件

**文件：** `src/mewcode/agent/events.py`、`src/mewcode/agent/__init__.py`、`tests/test_agent_runner.py`  
**依赖：** T8

**步骤：**
1. 定义 `AgentSubagentProgress`，只允许 task ID、位置、状态和有界进度文本。
2. 把类型加入 `AgentEvent` 联合及公共导出，不携带子运行消息、工具参数或 Provider part。
3. 增加构造与事件联合回归，限制测试中的进度文本长度。

**验证：** 运行 `python -m pytest tests/test_agent_runner.py -q`，期望新事件可被事件流识别且不改变现有事件序列。

## B2：Prompt、Hook、权限、Context 与 Skill 通用扩展

### T11：扩展 PromptAdditions 的 Agent Role 字段

**文件：** `src/mewcode/prompting/models.py`、`tests/test_prompt_builder.py`  
**依赖：** T9

**步骤：**
1. 为 `PromptAdditions` 增加可选 `agent_role`，默认值保持无角色调用方输出不变。
2. 更新 `merged`，支持显式合并角色正文并保持现有 custom instructions、memory 和 Skill 字段语义。
3. 增加空值、单次合并和 run view 多轮合并测试。

**验证：** 运行 `python -m pytest tests/test_prompt_builder.py -q`，期望 `agent_role` 合并正确，既有 PromptAdditions 用例全部通过。

### T12：渲染动态 Agent Role 区段

**文件：** `src/mewcode/prompting/sections.py`、`src/mewcode/prompting/builder.py`、`tests/test_prompt_builder.py`  
**依赖：** T11

**步骤：**
1. 注册动态 `## Agent Role` 区段，位置固定在 Custom Instructions 之后、Skill 目录之前。
2. 仅在 `agent_role` 非空时渲染；角色正文不进入稳定基础规则前缀。
3. 比较有/无角色的 PromptPackage，断言稳定区字节不变且角色在每轮动态区持续存在。

**验证：** 运行 `python -m pytest tests/test_prompt_builder.py -q`，期望区段顺序、缺省兼容和稳定前缀比较全部通过。

### T13：给 Hook 作用域增加安全任务关联

**文件：** `src/mewcode/hooks/events.py`、`src/mewcode/hooks/runtime.py`、`tests/test_hook_runtime.py`  
**依赖：** T3

**步骤：**
1. 让 Hook scope 支持可选 `subagent_task_id`、`parent_run_id` 和 task component。
2. 事件序列化只加入有界 ID 字段，不加入任务正文、历史、工具结果或凭据。
3. 测试嵌套 scope 的覆盖/恢复、两个 asyncio 任务隔离和现有非子任务事件结构兼容。

**验证：** 运行 `python -m pytest tests/test_hook_runtime.py -q`，期望任务关联准确、无额外敏感字段且旧事件用例通过。

### T14：按任务分区 Hook 临时 Prompt

**文件：** `src/mewcode/hooks/runtime.py`、`src/mewcode/hooks/provider.py`、`tests/test_hook_runtime.py`、`tests/test_hook_provider.py`  
**依赖：** T13

**步骤：**
1. 保留现有全局 prompt 队列，并增加按 `subagent_task_id` 键控的队列。
2. task scope 的 Hook prompt 只进入本任务分区；子任务 Provider 只消费自己的分区，根/维护请求不消费它。
3. 非子任务 dispatch 和 Provider 继续使用原全局队列语义。
4. 并发生成三组 prompt，验证消费顺序、任务隔离和全局兼容。

**验证：** 运行 `python -m pytest tests/test_hook_runtime.py tests/test_hook_provider.py -q`，期望全局及各任务只消费自己的 prompt 且同任务内顺序稳定。

### T15：限制并清理 Hook 任务队列

**文件：** `src/mewcode/hooks/runtime.py`、`tests/test_hook_runtime.py`  
**依赖：** T14

**步骤：**
1. 让现有 Hook prompt 总预算同时统计全局队列与所有 task 分区。
2. 增加清理单个 task 分区和关闭时清空所有分区的接口，保持锁内修改。
3. 支持 Fork 首轮 `preserve_fork_prefix`：command/HTTP 动作照常执行，新 prompt 留在本任务队列供第二次请求消费。
4. 测试总预算拒绝、任务结束清理、关闭清理和首轮延迟消费。

**验证：** 运行 `python -m pytest tests/test_hook_runtime.py -q`，期望预算不能被分区绕过，清理后无残留，Fork 首轮 prompt 只在后续请求出现。

### T16：增加非交互权限拒绝来源

**文件：** `src/mewcode/permissions/models.py`、`tests/test_tool_scheduler.py`  
**依赖：** T4

**步骤：**
1. 增加 `PermissionSource.SUBAGENT_NON_INTERACTIVE`，与 `SUBAGENT_POLICY` 一并保持稳定字符串值。
2. 确认通用 PermissionController 不自动产生这两个来源，只由后续子任务包装器显式使用。
3. 增加枚举序列化和现有权限决策回归测试。

**验证：** 运行 `python -m pytest tests/test_tool_scheduler.py -q`，期望新增来源可稳定序列化且现有权限来源不变。

### T17：允许任务 ContextArchive 跳过全局清理

**文件：** `src/mewcode/context/archive.py`、`tests/test_context_manager.py`  
**依赖：** 无

**步骤：**
1. 为 `ContextArchive.start` 增加缺省执行 stale cleanup 的兼容选项。
2. 关闭该选项时只创建/管理本实例目录，不扫描或删除其他 session 目录。
3. 测试主归档仍清理遗留目录，两个任务归档并发启动互不删除，close 只清理自身。

**验证：** 运行 `python -m pytest tests/test_context_manager.py -q`，期望主归档旧行为和任务归档隔离用例全部通过。

### T18：增加 preserve-prefix 容量检查模式

**文件：** `src/mewcode/context/manager.py`、`tests/test_context_manager.py`  
**依赖：** T9、T17

**步骤：**
1. 为 `ContextManager.prepare` 增加显式 preserve-prefix 模式，只使用现有估算器判断请求是否安全容纳。
2. 容量足够时原样返回 request；不足时返回 `ContextFailureKind.CAPACITY`，两条路径都不得调用 HistoryCompactor 或改变消息。
3. 自动模式保持现有压缩行为和 status/usage 语义。
4. 用 spy compactor 验证通过、失败和默认自动三条路径。

**验证：** 运行 `python -m pytest tests/test_context_manager.py -q`，期望 preserve-prefix 从不压缩，容量失败明确，原自动压缩测试无回归。

### T19：完成 LoadSkillTool 上下文兼容回归

**文件：** `src/mewcode/skills/control.py`、`tests/test_skill_runtime.py`、`tests/test_tool_scheduler.py`  
**依赖：** T6

**步骤：**
1. 为既有 Load Skill 成功、参数错误、取消和 Coordinator 失败用例提供测试 `AgentControlContext`。
2. 断言改变后的协议没有让 Skill 读取或修改父请求快照。
3. 断言普通 Skill 控制操作产生的 ToolResult 与事件顺序保持不变。

**验证：** 运行 `python -m pytest tests/test_skill_runtime.py tests/test_tool_scheduler.py -q`，期望 Load Skill 全部既有行为在新签名下通过。

### T20：区分根与 isolated Skill 的 Agent 工具视图

**文件：** `src/mewcode/skills/runtime.py`、`tests/test_skill_runtime.py`  
**依赖：** T19

**步骤：**
1. 让根 `run_view` 在普通状态和共享 Skill 激活状态都保留名为 `agent` 的全局控制工具。
2. isolated Skill 视图不自动带入 `agent`，也不能通过 Skill 包白名单恢复它。
3. 保持 `load_skill`、全局工具、包工具和安全裁剪的现有合并/冲突规则。
4. 覆盖无 agent 的旧式测试注册表，确保缺少该工具时不会凭空创建。

**验证：** 运行 `python -m pytest tests/test_skill_runtime.py -q`，期望根视图稳定保留现有 agent 实例，isolated 视图始终没有它，其他 Skill 测试通过。

### T21：执行 B1–B2 定向回归门

**文件：** B1–B2 涉及的全部实现和测试文件  
**依赖：** T1–T20

**步骤：**
1. 运行请求边界、AgentRunner、ToolScheduler、Prompt、Hook、Permission、Context 和 Skill 的定向测试集合。
2. 检查 `src/mewcode/agent`、`providers`、`hooks`、`permissions`、`context`、`prompting`、`skills` 未导入 `mewcode.subagents`。
3. 若测试失败，只修复 B1–B2 已定义的通用契约，不提前创建 B3 及之后的功能模块。

**验证：** 运行 `python -m pytest tests/test_request_boundary.py tests/test_agent_runner.py tests/test_tool_scheduler.py tests/test_prompt_builder.py tests/test_hook_runtime.py tests/test_hook_provider.py tests/test_context_manager.py tests/test_skill_runtime.py -q`，期望全部通过；再运行 `rg -n "mewcode\.subagents" src/mewcode/agent src/mewcode/providers src/mewcode/hooks src/mewcode/permissions src/mewcode/context src/mewcode/prompting src/mewcode/skills`，期望无匹配结果。

## B3：角色模型、发现、解析与目录

### T22：定义角色模型与资源限制

**文件：** `src/mewcode/subagents/models.py`、`tests/test_subagent_catalog.py`  
**依赖：** T21

**步骤：**
1. 定义 `AgentDefinitionLayer`、`AgentDefinitionSource`、`AgentDefinition`、`AgentDefinitionDiagnostic`、`AgentDefinitionCatalog` 及角色目录异常。
2. 集中定义名称规则、64 KiB 文件、256 候选、1 MiB 正文总量、64 KiB 任务、20,000 字符结果、8 活动任务、16/64 KiB 通知、128 保留及 5/10 秒产品常量。
3. 让目录通过 `MappingProxyType` 按角色名稳定排序，并完整保存正文字符串而非惰性文件引用。
4. 测试枚举优先级、不可变映射、稳定顺序和产品默认值单一来源。

**验证：** 运行 `python -m pytest tests/test_subagent_catalog.py -q`，期望角色模型不可变、层级为 PROJECT > USER > BUILTIN > PLUGIN 且限制常量符合 Spec。

### T23：建立四类角色根目录与确定性发现

**文件：** `src/mewcode/subagents/paths.py`、`tests/test_subagent_paths.py`  
**依赖：** T22

**步骤：**
1. 定义 `AgentDefinitionRoots.defaults(workspace_root, plugin_roots=())`，默认项目、用户和包内 built-in 路径符合 Plan。
2. 按项目、用户、内置、插件层产生来源；多个插件根同属一个最低优先级层，不引入隐式覆盖顺序。
3. 每个根只发现直属 `<name>.md`，忽略子目录、其他后缀和不存在的根，并按大小写稳定排序。
4. 测试每个来源的 layer、root、path、entry name 和 origin 诊断标签。

**验证：** 运行 `python -m pytest tests/test_subagent_paths.py -q`，期望四类来源、直属文件筛选和跨平台稳定排序用例全部通过。

### T24：落实角色发现安全边界

**文件：** `src/mewcode/subagents/paths.py`、`tests/test_subagent_paths.py`  
**依赖：** T23

**步骤：**
1. 拒绝符号链接候选并把安全原因保存在来源诊断中，不跟随链接读取目标。
2. 非目录根和枚举 I/O 错误转成有界 `AgentDefinitionError`；不返回随机部分目录。
3. 对项目、用户、内置以及每个插件根分别执行最多 256 候选的检查，超限整体拒绝该来源。
4. 测试 256/257 边界、损坏根、链接文件和多个插件根独立计数。

**验证：** 运行 `python -m pytest tests/test_subagent_paths.py -q`，期望所有路径错误确定收敛、链接不被读取且任何来源都不能超过 256 个候选。

### T25：解析角色文件外壳

**文件：** `src/mewcode/subagents/parser.py`、`tests/test_subagent_parser.py`  
**依赖：** T22、T24

**步骤：**
1. 以二进制读取单个文件并在解析前执行 64 KiB 上限，避免先把超限内容完整读入。
2. 严格识别开头和结尾 YAML delimiter、UTF-8、YAML object 及非空 Markdown 正文；允许文件开头出现一个 UTF-8 BOM。
3. 捕获 Unicode、YAML、I/O 和发现诊断错误，统一转成有界 `AgentDefinitionError`。
4. 测试 LF/CRLF、可选单 BOM、空正文、缺分隔符、非 mapping YAML 和 64 KiB 边界。

**验证：** 运行 `python -m pytest tests/test_subagent_parser.py -q`，期望合法外壳可解析，所有损坏或超限文件只产生安全定义错误。

### T26：严格校验七个 frontmatter 字段

**文件：** `src/mewcode/subagents/parser.py`、`tests/test_subagent_parser.py`  
**依赖：** T25

**步骤：**
1. 只接受 `name`、`description`、`tools`、`disallowed_tools`、`model`、`max_turns`、`permission_mode` 七个必填字段。
2. 校验 kebab-case 文件名一致性、单行非空说明、两个无重复非空工具名列表、非空 model 字符串、1..100 非 bool 整数及三种权限模式。
3. 保留 `model=inherit` 或 Profile 名的语法值；Profile 是否存在延迟到目录阶段校验。
4. 为每个未知、缺失、错误类型、重复项和边界枚举编写独立参数化用例。

**验证：** 运行 `python -m pytest tests/test_subagent_parser.py -q`，期望七字段合法定义生成 `AgentDefinition`，所有歧义输入均被拒绝。

### T27：实现跨层有效定义回退

**文件：** `src/mewcode/subagents/catalog.py`、`tests/test_subagent_catalog.py`  
**依赖：** T22、T26

**步骤：**
1. 按角色名聚合候选，并按 PROJECT、USER、BUILTIN、PLUGIN 从高到低尝试解析和语义校验。
2. 高层候选无效时记录有界诊断并继续寻找下一层有效定义；所有层无效时不暴露该角色。
3. 选中定义后仍保留其他无效候选诊断，但不在运行时重新读取文件。
4. 覆盖四层逐级移除、高层损坏回退、全损坏和不同角色互不影响。

**验证：** 运行 `python -m pytest tests/test_subagent_catalog.py -q`，期望项目到插件的覆盖顺序正确，高层错误不会屏蔽低层有效角色。

### T28：拒绝同层有效重名冲突

**文件：** `src/mewcode/subagents/catalog.py`、`tests/test_subagent_catalog.py`  
**依赖：** T27

**步骤：**
1. 在完成候选解析和语义校验后检查同一 layer 的有效同名定义数量。
2. 同层两个及以上有效定义抛出 `AgentCatalogError`，错误列出有界来源，不依赖扫描顺序选择。
3. 同层一个有效、一个无效时选择有效项并保留无效诊断；低层冲突即使被高层有效角色遮盖也按目录冲突处理。
4. 覆盖多个插件根重名、大小写路径顺序及有效/无效混合。

**验证：** 运行 `python -m pytest tests/test_subagent_catalog.py -q`，期望所有有效重名冲突确定失败，单个有效候选仍可选择。

### T29：校验 Profile、工具和目录总量

**文件：** `src/mewcode/subagents/catalog.py`、`tests/test_subagent_catalog.py`  
**依赖：** T28

**步骤：**
1. 接收 `ProfileCatalog` 名称快照、基础工具名及全局禁止名；`inherit` 直接有效，其他 model 必须匹配现有 Profile。
2. 白名单中的未知、未注册或全局禁止工具使候选无效；黑名单名称也必须是当前已知工具且只能收窄能力。
3. Profile/工具语义错误参与 T27 的高层回退，不在首次委派时才暴露。
4. 选中角色正文合计超过 1 MiB 时拒绝目录装配；恰好上限可用，目录和正文随后冻结。

**验证：** 运行 `python -m pytest tests/test_subagent_catalog.py -q`，期望 Profile/工具错误可回退、全局禁止不可进入白名单且正文总量边界正确。

### T30：执行 B3 角色目录回归门

**文件：** `src/mewcode/subagents/models.py`、`src/mewcode/subagents/paths.py`、`src/mewcode/subagents/parser.py`、`src/mewcode/subagents/catalog.py`、`tests/test_subagent_paths.py`、`tests/test_subagent_parser.py`、`tests/test_subagent_catalog.py`  
**依赖：** T22–T29

**步骤：**
1. 运行路径、解析和目录全部定向测试。
2. 使用临时目录构造 plugin → builtin → user → project 四层同名角色，确认最终快照正文来自项目层且文件后续改动不影响快照。
3. 检查角色模块不导入 AgentRunner、TaskManager、Conversation、REPL 或 CLI。

**验证：** 运行 `python -m pytest tests/test_subagent_paths.py tests/test_subagent_parser.py tests/test_subagent_catalog.py -q`，期望全部通过；再运行 `rg -n "agent\.runner|subagents\.tasks|conversation|repl|cli" src/mewcode/subagents/models.py src/mewcode/subagents/paths.py src/mewcode/subagents/parser.py src/mewcode/subagents/catalog.py`，期望无匹配结果。

## B4：冻结执行策略、权限与任务工具代理

### T31：计算定义式工具交集

**文件：** `src/mewcode/subagents/policy.py`、`tests/test_subagent_policy.py`  
**依赖：** T30

**步骤：**
1. 根据父模式允许名称、角色白名单、冻结后台名单、角色黑名单和全局禁止名单计算 `defined_executable`。
2. 使用只收窄的集合运算，黑名单与白名单冲突时黑名单优先，空白名单产生空工具集。
3. 从基础 `ToolRegistry` 按原注册顺序生成定义式模型视图，并以同一名称集合创建第二道 `FrozenSubagentToolPolicy`。
4. 参数化验证各集合顺序变化不扩大结果，READ_ONLY/PLAN 安全上限不可被角色 `allow` 恢复。

**验证：** 运行 `python -m pytest tests/test_subagent_policy.py -q`，期望定义式 schema 与可执行集合完全一致且只会收窄。

### T32：冻结 Fork 执行策略

**文件：** `src/mewcode/subagents/policy.py`、`tests/test_subagent_policy.py`  
**依赖：** T31

**步骤：**
1. 以父请求实际工具名、冻结后台名单、父模式安全集合和全局禁止名单计算 `fork_executable`。
2. 保留每个展示但不可执行工具的稳定、有界拒绝原因，尤其覆盖 `agent`、`load_skill`、后台越界及模式越界。
3. 使用 T5 的 Scheduler 验证策略拒绝不会触发 before Hook、权限控制器、真实工具或嵌套任务创建。
4. 父请求工具为空时生成可工作的空策略，不扩大到基础注册表其他工具。

**验证：** 运行 `python -m pytest tests/test_subagent_policy.py tests/test_tool_scheduler.py -q`，期望 Fork 展示能力和执行能力分离，所有越界调用确定失败且无副作用。

### T33：创建 schema 等价的任务工具代理

**文件：** `src/mewcode/subagents/scoped_tools.py`、`tests/test_subagent_scoped_tools.py`  
**依赖：** T30

**步骤：**
1. 实现 `TaskScopedTool`，逐项复用底层工具的 name、description、parameters_schema、safety 和 permission_spec。
2. 构建代理 `ToolRegistry` 时保持父注册顺序，不排序、不重命名、不添加提示字段，也不深拷贝后改写 schema。
3. `execute` 原样传入参数并原样返回底层 `ToolResult`；取消继续传播到正在执行的底层 coroutine。
4. 测试元数据值/对象等价、注册顺序、成功/失败结果和取消行为。

**验证：** 运行 `python -m pytest tests/test_subagent_scoped_tools.py -q`，期望代理公开 schema 与底层工具等价且执行语义透明。

### T34：隔离文件读取观察

**文件：** `src/mewcode/subagents/scoped_tools.py`、`tests/test_subagent_scoped_tools.py`  
**依赖：** T33

**步骤：**
1. 定义 `FileReadObservationCache` 和 `FileReadObservation`，成功 `read_file` 后按规范相对路径记录返回内容摘要及字节数。
2. 当前任务的 `write_file`/`edit_file` 成功后只清除自己的同路径观察；失败结果不修改缓存。
3. 代理每次仍调用真实底层工具，不用观察缓存替代文件读取。
4. 用两个独立缓存读取同一文件、其中一个写入后再读，验证新内容可见且另一任务缓存对象未被直接修改。

**验证：** 运行 `python -m pytest tests/test_subagent_scoped_tools.py -q`，期望观察按任务隔离、写入只清本缓存且共享文件变化可重新读取。

### T35：复制持久权限规则并清空 session

**文件：** `src/mewcode/subagents/permissions.py`、`tests/test_subagent_permissions.py`  
**依赖：** T16、T30

**步骤：**
1. 从任务创建时的 `PermissionRuleSets` 构造新快照，复制 project-local、project、user 元组并强制 `session=()`。
2. 为每任务创建独立 `PermissionRuleStore`/`PermissionController`，使用角色或 Fork 冻结的 `PermissionMode` 和不写持久配置的 writer。
3. 父 RuleStore 后续增加 session 或持久规则时，不改变既有任务快照；子控制器变化也不回写父状态。
4. 测试三层允许/拒绝、父 session 允许不继承以及两个任务决策状态互不共享。

**验证：** 运行 `python -m pytest tests/test_subagent_permissions.py -q`，期望只继承创建时三层持久规则，session 和后续变更完全隔离。

### T36：把权限 ASK 自动改写为 DENY

**文件：** `src/mewcode/subagents/permissions.py`、`tests/test_subagent_permissions.py`  
**依赖：** T35

**步骤：**
1. 实现 `SubagentPermissionController`：`preflight` 保留硬拒绝，`evaluate_preflight` 保留 ALLOW/DENY 并把 ASK 同步改写为 DENY。
2. 自动拒绝使用 `SUBAGENT_NON_INTERACTIVE`、稳定原因、原 target 和原 match，不声称用户做过选择。
3. `apply_choice` 明确不可调用，子任务路径不产生 `PermissionChallenge`，也不调用任何规则写方法。
4. 分别在 strict/default/allow 和显式拒绝规则下验证结果，并通过 Scheduler 确认模型收到普通失败工具结果后仍可继续下一轮。

**验证：** 运行 `python -m pytest tests/test_subagent_permissions.py tests/test_tool_scheduler.py -q`，期望所有 ASK 自动拒绝、显式拒绝与硬安全不可绕过且没有交互挑战。

### T37：执行 B4 能力隔离回归门

**文件：** `src/mewcode/subagents/policy.py`、`src/mewcode/subagents/permissions.py`、`src/mewcode/subagents/scoped_tools.py`、`tests/test_subagent_policy.py`、`tests/test_subagent_permissions.py`、`tests/test_subagent_scoped_tools.py`  
**依赖：** T31–T36

**步骤：**
1. 运行策略、权限、任务工具代理和通用 Scheduler 定向测试。
2. 构造同时包含允许、黑名单、全局禁止、后台越界和模式越界工具的注册表，逐项证明没有路径可以扩大能力。
3. 确认功能层只依赖通用 Tool/Permission/Agent 协议，不导入 Conversation、REPL 或 CLI。

**验证：** 运行 `python -m pytest tests/test_subagent_policy.py tests/test_subagent_permissions.py tests/test_subagent_scoped_tools.py tests/test_tool_scheduler.py -q`，期望全部通过；再运行 `rg -n "conversation|repl|cli" src/mewcode/subagents/policy.py src/mewcode/subagents/permissions.py src/mewcode/subagents/scoped_tools.py`，期望无匹配结果。

## B5：通知队列与任务状态机

### T38：定义并安全渲染完成通知

**文件：** `src/mewcode/subagents/models.py`、`src/mewcode/subagents/notifications.py`、`tests/test_subagent_notifications.py`  
**依赖：** T22

**步骤：**
1. 定义 `SubagentNotification`、`NotificationBatch` 及通知状态所需不可变模型。
2. 把单个结果截断到 20,000 字符并明确附加截断标记；错误、角色、ID 和 usage 使用安全有界格式。
3. 渲染动态 `## Completed Subagent Tasks`，用 `<untrusted-subagent-results>` 边界声明结果不是高优先级指令。
4. 测试成功、失败、取消、未知 usage、伪系统指令内容和截断边界。

**验证：** 运行 `python -m pytest tests/test_subagent_notifications.py -q`，期望通知内容有界、状态完整且恶意文本始终位于不可信边界内。

### T39：实现通知去重、顺序与批次预算

**文件：** `src/mewcode/subagents/notifications.py`、`tests/test_subagent_notifications.py`  
**依赖：** T38

**步骤：**
1. 实现 `enqueue_once`，按完成顺序入队并以 task ID 去重。
2. 实现 `consume_batch(max_items=16, max_bytes=65536)`，按 UTF-8 编码后的完整渲染预算选择整条通知。
3. 超过条数或字节预算的通知保持原顺序等待后续批次，不拆分、不静默丢弃。
4. 测试空队列、20 条通知、跨批次顺序、精确字节边界和重复入队。

**验证：** 运行 `python -m pytest tests/test_subagent_notifications.py -q`，期望每批最多 16 条/64 KiB，剩余通知可在后续批次完整取得。

### T40：提交一次性通知投递结果

**文件：** `src/mewcode/subagents/notifications.py`、`tests/test_subagent_notifications.py`  
**依赖：** T39

**步骤：**
1. 让批次消费原子移除选中条目并记录 delivered task ID，确保同一通知不会再次返回。
2. 增加 delivered 回调/订阅点供 TaskManager 更新 `notification_pending` 与保留队列，但队列不反向导入任务模块。
3. `clear` 同时清空待投递和去重状态，适配 `/reset`；正常批次消费后同一 ID 仍不得重复入队。
4. 测试回调恰好一次、回调失败安全收敛、clear 后无旧通知以及 Provider 失败场景不自动重放已消费批次。

**验证：** 运行 `python -m pytest tests/test_subagent_notifications.py -q`，期望通知最多交付一次、回调隔离且 reset 清理彻底。

### T41：定义任务快照、启动说明与取消结果

**文件：** `src/mewcode/subagents/models.py`、`src/mewcode/subagents/tasks.py`、`tests/test_subagent_tasks.py`  
**依赖：** T22

**步骤：**
1. 定义 `SubagentKind`、五种 `SubagentTaskStatus`、`SubagentPlacement`、`SubagentParent`、`SubagentProgress`、`SubagentTaskSnapshot`、`SubagentLaunch` 和 `TaskCancelResult`。
2. 快照包含 Plan 规定的 ID、类型、角色、Profile、父关联、位置、时间、进度、有界结果/错误、截断、usage 和通知状态。
3. 内部 managed record 保存驱动 task、取消/解除事件和清理引用，不从公开 API 暴露。
4. 测试公开模型不可变、状态枚举稳定及 active/terminal 判定。

**验证：** 运行 `python -m pytest tests/test_subagent_tasks.py -q`，期望任务模型字段完整、不可变且状态分类符合 Spec。

### T42：原子注册任务并限制活动容量

**文件：** `src/mewcode/subagents/tasks.py`、`tests/test_subagent_tasks.py`  
**依赖：** T41

**步骤：**
1. 实现 `SubagentTaskManager.start` 的锁内容量检查、UUID4/可注入 ID 生成、REGISTERED 快照登记和单一驱动 task 创建。
2. 产品默认活动上限使用 T22 的 8；测试可注入较小值，终态任务不占活动名额。
3. 同一锁内防止 reset/close 期间创建任务，并拒绝重复或非唯一 ID。
4. 用并发 barrier 同时提交超额任务，证明成功数从不超过容量且失败发生在驱动/Provider 调用前。

**验证：** 运行 `python -m pytest tests/test_subagent_tasks.py -q`，期望并发注册原子、ID 不可简单递增且活动数始终不超上限。

### T43：驱动任务到单一明确终态

**文件：** `src/mewcode/subagents/tasks.py`、`tests/test_subagent_tasks.py`  
**依赖：** T42

**步骤：**
1. 通过窄的可注入运行时驱动协议，让 `_drive` 在锁外创建/运行子 Agent 并在锁内提交 REGISTERED → RUNNING → 终态。
2. 把自然完成映射为 COMPLETED，把 Agent 非成功 outcome/Provider/Context/内部错误映射为 FAILED，把取消映射为 CANCELLED。
3. 消费原始子事件只更新有界 `SubagentProgress`，最终结果和错误在入快照前截断；`finally` 恰好执行一次运行时清理。
4. 测试运行时创建失败、自然结束、各种非成功 outcome、异常和取消清理。

**验证：** 运行 `python -m pytest tests/test_subagent_tasks.py -q`，期望每条驱动路径进入正确终态、结果安全有界且清理只执行一次。

### T44：以首个终态收敛完成/取消/转后台竞态

**文件：** `src/mewcode/subagents/tasks.py`、`tests/test_subagent_tasks.py`  
**依赖：** T39、T43

**步骤：**
1. 所有完成、失败、取消和解除回调通过同一个锁内终态提交函数，已终态记录不可再次改写或重复计量。
2. 前台终态不入通知；先转为后台的任务在终态时恰好 `enqueue_once` 并设置 `notification_pending=True`。
3. 用可控 event 同时触发完成、取消和 detach，验证管理锁中首个合法状态变化获胜。
4. 禁止 done callback 直接修改公开快照，锁内不等待 Provider、工具、Hook、清理或终端。

**验证：** 运行 `python -m pytest tests/test_subagent_tasks.py tests/test_subagent_notifications.py -q`，期望竞态只产生一个终态和至多一个后台通知。

### T45：实现前台订阅、自动与手动转后台

**文件：** `src/mewcode/subagents/tasks.py`、`tests/test_subagent_tasks.py`  
**依赖：** T44

**步骤：**
1. 实现 `SubagentTaskHandle.foreground_events`，转发有界进度并在终态或解除事件中先发生者到达时结束。
2. 使用可注入单调时钟/等待器，从成功注册后计算 10 秒自动解除；测试不真实等待 10 秒。
3. 实现 `detach_foreground` 和 `detach_current_foreground`，只原子修改 placement，不取消、不重启驱动，也不重置 usage、权限或上下文引用。
4. 同一时刻只允许当前控制操作绑定一个 foreground task；无当前任务、已后台和已终态均返回确定无副作用结果。

**验证：** 运行 `python -m pytest tests/test_subagent_tasks.py -q`，期望快速完成直接返回，超时/手动解除原地转后台且驱动调用次数始终为一。

### T46：实现单任务确定取消

**文件：** `src/mewcode/subagents/tasks.py`、`tests/test_subagent_tasks.py`  
**依赖：** T44、T45

**步骤：**
1. `cancel(task_id)` 在锁内区分未知、已终态、已请求取消和可取消活动任务，并在锁外请求 AgentRun/驱动取消。
2. 最多等待注入的 5 秒清理预算；超时后取消并 gather 驱动 task，再由单一终态提交函数收敛。
3. 重复取消和取消终态任务不改写结果、usage、结束时间或通知。
4. 测试取消运行中、REGISTERED、刚完成、未知、重复以及完成/取消同时竞争。

**验证：** 运行 `python -m pytest tests/test_subagent_tasks.py -q`，期望只有活动任务被请求取消一次，所有其他结果确定且无副作用。

### T47：提供不可变查询与终态事件流

**文件：** `src/mewcode/subagents/tasks.py`、`tests/test_subagent_tasks.py`  
**依赖：** T43

**步骤：**
1. 实现 `list()` 与 `get()`，仅返回不可变快照；列表稳定区分活动和终态且不包含内部消息、参数或异常对象。
2. 实现 `terminal_events()`，每个任务首次进入终态后发布一个只含 ID、状态和安全摘要的事件。
3. 慢消费者不阻塞管理锁或任务运行；manager close 后事件流有明确结束信号。
4. 测试活动进度查询非阻塞、未知 ID、快照不可变、事件恰好一次及关闭收敛。

**验证：** 运行 `python -m pytest tests/test_subagent_tasks.py -q`，期望查询不泄漏内部状态且每个任务只发布一次终态事件。

### T48：实现有界 reset 与 close

**文件：** `src/mewcode/subagents/tasks.py`、`tests/test_subagent_tasks.py`  
**依赖：** T40、T46、T47

**步骤：**
1. `reset` 先设置 resetting、拒绝新 start，并发取消活动任务，使用注入等待器最多等待 5 秒后强制收敛。
2. reset 期间抑制新通知，最后原子清空任务记录、通知队列和注册的 task Hook 清理回调，再恢复可创建状态。
3. `close` 执行相同有界取消，关闭终态事件流并永久拒绝新任务；reset/close 和重复 close 保持幂等。
4. 测试无响应驱动、清理异常、reset 后新建任务、close 后拒绝及全程不真实 sleep。

**验证：** 运行 `python -m pytest tests/test_subagent_tasks.py tests/test_subagent_notifications.py -q`，期望 reset/close 在虚拟 5 秒预算内收敛、无旧任务或通知残留。

### T49：投递后保留最近 128 条终态记录

**文件：** `src/mewcode/subagents/tasks.py`、`src/mewcode/subagents/notifications.py`、`tests/test_subagent_tasks.py`、`tests/test_subagent_notifications.py`  
**依赖：** T40、T44、T47

**步骤：**
1. 连接通知 delivered 回调，原子清除对应快照的 `notification_pending` 并登记可淘汰顺序。
2. 超过 128 条时只淘汰最早的已投递终态；活动、前台终态和尚未投递通知的后台终态不可淘汰。
3. 未知/重复 delivered 回调安全忽略，不重新生成通知或改写终态。
4. 使用下调保留上限的测试创建混合状态记录，验证淘汰顺序和查询结果。

**验证：** 运行 `python -m pytest tests/test_subagent_tasks.py tests/test_subagent_notifications.py -q`，期望只保留最近已投递终态且任何活动或待通知任务都不会被淘汰。

### T50：执行 B5 通知与任务状态机回归门

**文件：** `src/mewcode/subagents/models.py`、`src/mewcode/subagents/notifications.py`、`src/mewcode/subagents/tasks.py`、`tests/test_subagent_notifications.py`、`tests/test_subagent_tasks.py`  
**依赖：** T38–T49

**步骤：**
1. 运行通知与任务状态机全部定向测试，确保使用 fake clock、event 和 driver，没有真实网络或 10 秒等待。
2. 重放 explicit background、10 秒 detach、manual detach、完成/取消竞争、20 条通知、128 条保留和 reset/close 场景。
3. 检查 TaskManager 状态锁内没有 await Provider/driver/Hook/终端/清理，并确认 tasks/notifications 不导入 Conversation、REPL 或 CLI。

**验证：** 运行 `python -m pytest tests/test_subagent_notifications.py tests/test_subagent_tasks.py -q`，期望全部通过且测试耗时不依赖产品超时；再运行 `rg -n "conversation|repl|cli" src/mewcode/subagents/notifications.py src/mewcode/subagents/tasks.py`，期望无匹配结果。

## B6：隔离运行时、协调器与统一 Agent 工具

### T51：实现根 Agent 完成通知请求边界

**文件：** `src/mewcode/subagents/notifications.py`、`src/mewcode/providers/request_boundary.py`、`tests/test_subagent_notifications.py`、`tests/test_request_boundary.py`  
**依赖：** T40、T50

**步骤：**
1. 实现 `RootAgentRequestBoundary`：先消费一个通知批次并只追加到 `PromptPackage.dynamic_system`，再把最终请求写入当前 `RequestSnapshotSlot`。
2. 没有通知时保持原 PromptPackage/ModelRequest 对象；稳定系统提示、消息、工具和 max output 均不改变。
3. 子任务与维护请求使用 `CaptureOnlyRequestBoundary` 或无边界，不能取得通知队列消费能力。
4. 测试通知追加位置、捕获顺序、空队列零复制、批次投递一次及压缩/记忆/子任务不消费。

**验证：** 运行 `python -m pytest tests/test_subagent_notifications.py tests/test_request_boundary.py -q`，期望通知只进入根真实请求动态区且捕获快照包含本次已注入通知。

### T52：建立 SubagentRuntimeFactory 依赖与生命周期接口

**文件：** `src/mewcode/subagents/runtime.py`、`tests/test_subagent_runtime.py`  
**依赖：** T18、T34、T36、T43

**步骤：**
1. 定义 `SubagentRuntimeFactory` 的共享依赖：ProfileCatalog/provider supplier、PromptBuilder、Workspace、HookRuntime、基础 additions supplier、基础工具注册表和 Context 配置工厂。
2. 定义供 TaskManager 驱动的窄运行时对象，暴露单次事件流、cancel 和幂等 close，不让 tasks 模块反向了解 AgentRunner 组装细节。
3. 每次 `create(launch)` 分配独立取消状态、文件观察缓存、ContextArchive/ContextManager、PermissionController 和 ToolScheduler 引用。
4. 用测试替身证明两个 create 调用不共享可变运行对象，而 Provider/Profile/Hook/Workspace 引用按设计共享。

**验证：** 运行 `python -m pytest tests/test_subagent_runtime.py -q`，期望每任务状态对象唯一、共享基础设施身份一致且 close 幂等。

### T53：构造定义式空白上下文

**文件：** `src/mewcode/subagents/runtime.py`、`tests/test_subagent_runtime.py`、`tests/test_prompt_builder.py`  
**依赖：** T12、T30、T52

**步骤：**
1. 定义式运行从 `history=()` 启动，并把本次 task 作为唯一的新用户消息。
2. 从基础 additions supplier 只复制项目/用户人工指令和长期记忆，填写 `agent_role`，显式清空 available/active Skill 和父临时 Hook 内容。
3. 使用当前环境与稳定基础规则重新构建 Prompt，不继承父消息、父 PLAN 提醒或父 PromptPackage。
4. 测试父历史、父 Skill、父 Hook prompt 均不出现，而角色正文在定义式每轮请求中持续存在。

**验证：** 运行 `python -m pytest tests/test_subagent_runtime.py tests/test_prompt_builder.py -q`，期望定义式首轮只有独立 task 消息和允许的动态基础上下文。

### T54：组装定义式工具、权限和 DIRECT Runner

**文件：** `src/mewcode/subagents/runtime.py`、`tests/test_subagent_runtime.py`  
**依赖：** T31、T34、T36、T53

**步骤：**
1. 使用启动说明中冻结的定义式工具 registry、`FrozenSubagentToolPolicy` 和角色权限模式创建任务 ToolScheduler。
2. 创建任务级 ContextArchive 时用 task ID 派生受工作区根约束的目录并跳过 stale cleanup；为其创建独立 ContextManager。
3. 创建 `AgentRunner`/AgentRun，模式固定 DIRECT、`max_iterations=role.max_turns`、history sink 为 `None`，Profile 和安全集合来自冻结说明。
4. 测试空工具角色、只读角色、角色 allow 仍受 policy/hard safety 限制，以及子运行不提交主 history。

**验证：** 运行 `python -m pytest tests/test_subagent_runtime.py tests/test_subagent_policy.py tests/test_subagent_permissions.py -q`，期望定义式 Runner 只看见冻结工具并使用独立权限、Context 与轮次上限。

### T55：驱动定义式运行并保证清理

**文件：** `src/mewcode/subagents/runtime.py`、`tests/test_subagent_runtime.py`  
**依赖：** T15、T54

**步骤：**
1. 在整个子运行期间绑定 `component=subagent`、task ID、parent run ID 的 Hook scope。
2. 把原始 AgentEvent 流交给 TaskManager 驱动层消费，运行时自身只提供 outcome、cancel 和资源清理。
3. 无论自然完成、轮次/输出/上下文失败、异常还是取消，均清理 task Hook prompt 分区、ContextManager 和仅本任务归档目录。
4. 测试 close 顺序、一次性清理、清理异常有界收敛，以及一个任务失败不关闭共享 Provider/Hook/Workspace。

**验证：** 运行 `python -m pytest tests/test_subagent_runtime.py tests/test_hook_runtime.py -q`，期望所有定义式终止路径清理任务资源且共享基础设施仍可被其他任务使用。

### T56：组装 Fork schema 等价工具视图与请求种子

**文件：** `src/mewcode/subagents/runtime.py`、`tests/test_subagent_runtime.py`、`tests/test_subagent_scoped_tools.py`  
**依赖：** T9、T18、T32、T34、T52

**步骤：**
1. 按父 `ModelRequest.tools` 原顺序创建任务代理 registry，保持 name、description、parameters schema、safety 和 permission spec 值不变。
2. 使用 `ForkRequestSeed` 的父 prompt、messages、tools、max output 和 Profile，末尾只追加本次 task 用户消息。
3. Runner 固定 DIRECT，但使用父本次真实 loop limit 作为独立 `max_iterations`，不继承已消耗 iteration。
4. ToolScheduler 使用 Fork 冻结 policy；schema 中保留的 `agent`/`load_skill` 只能得到策略失败，不能实例化控制操作。

**验证：** 运行 `python -m pytest tests/test_subagent_runtime.py tests/test_subagent_scoped_tools.py tests/test_subagent_policy.py -q`，期望 Fork schema/顺序与父请求等价而执行能力严格受限。

### T57：保护 Fork 首次缓存前缀

**文件：** `src/mewcode/subagents/runtime.py`、`tests/test_subagent_runtime.py`、`tests/test_context_manager.py`、`tests/test_hook_runtime.py`  
**依赖：** T15、T18、T51、T56

**步骤：**
1. Fork 首轮调用 ContextManager preserve-prefix 模式；容量足够时不压缩，容量不足时在 Provider 前以 CONTEXT_CAPACITY 失败。
2. 首轮绑定 `preserve_fork_prefix=True` 的任务 Hook scope：command/HTTP 动作执行，新 prompt 留到本任务第二轮。
3. 首轮使用 capture-only 请求边界，不消费根通知；第二轮起恢复任务 Hook prompt 消费和自动 Context 压缩。
4. 比较父请求与 Fork 首轮在新增 task 之前的 prompt/messages/tools 值，并验证 compactor/通知队列均未被调用。

**验证：** 运行 `python -m pytest tests/test_subagent_runtime.py tests/test_context_manager.py tests/test_hook_runtime.py -q`，期望 Fork 首轮前缀不被压缩、Hook 或通知改变，容量失败零 Provider 调用。

### T58：保持任务 usage 独立且进程账本只计一次

**文件：** `src/mewcode/subagents/runtime.py`、`tests/test_subagent_runtime.py`  
**依赖：** T54、T56

**步骤：**
1. 任务 outcome 直接采用独立 AgentRun 的 `TokenUsage`，不由 runtime 或 TaskManager 再写共享 UsageLedger。
2. 所有 Profile 的 Provider 继续来自 ProfileCatalog 缓存并由唯一 UsageTrackingProvider 计入进程账本。
3. 保留 Provider 未报告的 usage 字段为 `None`，不估算缓存读取/写入。
4. 并发运行两个返回不同 usage 的任务，验证任务快照各自累计，进程账本请求数与 Provider 调用数相同而非翻倍。

**验证：** 运行 `python -m pytest tests/test_subagent_runtime.py tests/test_usage_tracking.py -q`，期望任务 usage 独立、缺失字段未知且全局账本恰好记录一次。

### T59：校验统一委派参数

**文件：** `src/mewcode/subagents/coordinator.py`、`tests/test_subagent_control.py`  
**依赖：** T30、T37、T50

**步骤：**
1. `SubagentCoordinator.prepare` 严格接受 `type/task/role/background` 组合，并对 task trim 后非空与 UTF-8 最大 64 KiB 做检查。
2. defined 必须给 role，background 缺省 false；fork 禁止 role 和 background；未知字段仍由固定工具 schema 拒绝。
3. 未知角色、缺失父请求快照和非法类型在 TaskManager.start 前转成稳定安全错误。
4. 参数化覆盖空任务、空白角色、未知类型/角色、bool 类型错误和所有非法组合，并断言任务数/Provider 调用数为零。

**验证：** 运行 `python -m pytest tests/test_subagent_control.py -q`，期望所有非法调用在任务注册前失败且错误语义稳定。

### T60：冻结定义式 SubagentLaunch

**文件：** `src/mewcode/subagents/coordinator.py`、`tests/test_subagent_control.py`  
**依赖：** T31、T35、T59

**步骤：**
1. 解析目录快照中的角色；`model=inherit` 使用 `AgentControlContext.profile_name`，指定名称使用已校验 Profile。
2. 冻结角色正文、定义式工具 registry/policy、三层持久规则、角色权限模式、父安全上限、后台名单、父关联和基础 additions 快照。
3. 默认 placement=FOREGROUND，`background=true` 使用 BACKGROUND；两种位置从启动前共享同一能力上限。
4. 在 prepare 后修改父权限模式、角色文件、注册表和基础 additions，验证 `SubagentLaunch` 不变。

**验证：** 运行 `python -m pytest tests/test_subagent_control.py -q`，期望定义式启动说明完整冻结且 model/placement/能力选择正确。

### T61：冻结 Fork SubagentLaunch

**文件：** `src/mewcode/subagents/coordinator.py`、`tests/test_subagent_control.py`  
**依赖：** T32、T35、T56、T59

**步骤：**
1. 从 `AgentControlContext.parent_request` 构造 `ForkRequestSeed`，冻结父 Profile、run/iteration、权限模式、安全集合和真实 loop limit。
2. 生成 schema 等价代理视图与独立 Fork policy，持久规则复制后清空 session。
3. Fork placement 强制 BACKGROUND，prepare 不允许调用方覆盖，也不复制产生 agent 调用的助手工具消息。
4. 修改父注册表、权限或后续 iteration 槽后，验证既有 Fork launch 的 schema、policy 和 seed 不变。

**验证：** 运行 `python -m pytest tests/test_subagent_control.py tests/test_subagent_policy.py -q`，期望 Fork 启动说明保留父请求前缀并冻结独立执行能力。

### T62：实现固定 schema 的唯一 AgentTool

**文件：** `src/mewcode/subagents/control.py`、`src/mewcode/subagents/__init__.py`、`tests/test_subagent_control.py`  
**依赖：** T59–T61

**步骤：**
1. 把 Plan 中 `agent` JSON schema 定义为模块级不可变常量，只包含 type、task、role、background，required 为 type/task 且禁止额外字段。
2. `AgentTool` 标记 READ_ONLY 控制工具，description 不枚举角色、任务或动态状态。
3. `control_operation(arguments, context)` 只创建 `SubagentDelegationOperation`，不直接查询或取消任务。
4. 在空目录、单/多角色和已有任务状态下逐字比较工具 name、description、schema 与注册顺序。

**验证：** 运行 `python -m pytest tests/test_subagent_control.py -q`，期望所有运行状态下只得到同一个字节稳定 AgentTool schema。

### T63：让显式后台与 Fork 立即返回

**文件：** `src/mewcode/subagents/control.py`、`tests/test_subagent_control.py`  
**依赖：** T42、T60–T62

**步骤：**
1. `SubagentDelegationOperation.events` 先调用 Coordinator prepare，再调用 TaskManager.start。
2. defined explicit background 和 fork 在成功注册后立即生成 `ToolResult(ok=True)`，包含 UUID task ID、kind、BACKGROUND 和初始状态。
3. 返回前不得等待运行时 create、首次 Provider 响应或进度事件；容量/注册错误转 `ToolResult(ok=False)`。
4. 用阻塞 fake driver 验证 ToolResult 已返回、驱动仍未释放且 TaskManager 中恰好一个任务。

**验证：** 运行 `python -m pytest tests/test_subagent_control.py tests/test_subagent_tasks.py -q`，期望两类后台委派零首响应等待并返回可查询 task ID。

### T64：完成定义式前台操作与取消语义

**文件：** `src/mewcode/subagents/control.py`、`tests/test_subagent_control.py`  
**依赖：** T45、T46、T60、T62

**步骤：**
1. 默认 defined 订阅 `foreground_events`，只向父事件流转发 `AgentSubagentProgress`，不转发子文本、工具参数或内部消息。
2. 10 秒内终态时返回有界结果、状态、截断标记和 task usage；FAILED/CANCELLED 使用 `ok=False` 安全错误。
3. 自动/手动 detach 时返回 `ok=True` 的 task ID 和当前状态，不产生前台最终结果。
4. 父 ToolSchedule 取消操作时只取消仍绑定的前台任务；已 detach 的后台任务不受随后父取消影响。

**验证：** 运行 `python -m pytest tests/test_subagent_control.py tests/test_subagent_tasks.py -q`，期望快速前台结果、两种 detach 和取消竞态都只产生一个确定 ToolResult。

### T65：执行 B6 子 Agent 运行链回归门

**文件：** `src/mewcode/subagents/runtime.py`、`src/mewcode/subagents/coordinator.py`、`src/mewcode/subagents/control.py`、`src/mewcode/subagents/__init__.py`、`tests/test_subagent_runtime.py`、`tests/test_subagent_control.py`  
**依赖：** T51–T64

**步骤：**
1. 运行 runtime、control、policy、permission、tasks、notifications、AgentRunner 和 RequestBoundary 的定向测试。
2. 用 fake Provider 跑一条定义式前台自然完成、一条定义式 detach 后完成和一条 Fork 首轮请求，检查 history、usage、Hook scope 和清理。
3. 检查 `mewcode.agent`/providers/hooks 等通用层没有反向导入 `subagents`，子功能层没有导入 Conversation、REPL 或 CLI。

**验证：** 运行 `python -m pytest tests/test_subagent_runtime.py tests/test_subagent_control.py tests/test_subagent_policy.py tests/test_subagent_permissions.py tests/test_subagent_tasks.py tests/test_subagent_notifications.py tests/test_agent_runner.py tests/test_request_boundary.py -q`，期望全部通过；再运行 `rg -n "mewcode\.subagents" src/mewcode/agent src/mewcode/providers src/mewcode/hooks`，期望无匹配结果。

## B7：Conversation、本地命令、终端与 REPL

### T66：扩展本地命令运行时任务协议

**文件：** `src/mewcode/commands/contracts.py`、`tests/test_builtin_commands.py`  
**依赖：** T65

**步骤：**
1. 为 `CommandRuntime` 增加 list/get/cancel 子任务接口，返回 B5 的不可变快照/取消结果。
2. 协议不暴露 TaskManager 内部 record、消息、工具参数或等待终态方法。
3. 更新命令测试 fake runtime，并保证缺少任务时不会产生模型请求或 Conversation history 写入。

**验证：** 运行 `python -m pytest tests/test_builtin_commands.py -q`，期望 fake runtime 满足新协议且现有命令行为保持通过。

### T67：实现 `/tasks` 安全摘要

**文件：** `src/mewcode/commands/builtin.py`、`tests/test_builtin_commands.py`  
**依赖：** T66

**步骤：**
1. 注册本地 `/tasks`，严格拒绝参数，并在静态命令目录中参与现有冲突检测。
2. 按活动与终态分组格式化 ID、kind、角色、placement、status、时间和有界进度摘要。
3. 空任务表显示简短确定文本；列表不显示完整结果、错误栈、工具参数或凭据。
4. 覆盖空表、混合状态、Fork 无角色、截断进度及非法参数。

**验证：** 运行 `python -m pytest tests/test_builtin_commands.py -q`，期望 `/tasks` 全程本地、分组清楚且输出仅含安全摘要。

### T68：实现 `/task <id>` 非阻塞详情

**文件：** `src/mewcode/commands/builtin.py`、`tests/test_builtin_commands.py`  
**依赖：** T66

**步骤：**
1. 注册 `/task` 并严格解析一个 task ID；不接受多余 token。
2. 活动任务立即显示状态和有界进度；终态显示结果或错误、截断标记及 input/output/total/cache usage 的 n/a 语义。
3. 未知 ID 返回稳定本地错误，不等待任务、不调用模型。
4. 覆盖五种状态、未知 usage、20,000 字符截断和未知 ID。

**验证：** 运行 `python -m pytest tests/test_builtin_commands.py -q`，期望 `/task <id>` 对活动任务非阻塞、终态信息完整且错误确定。

### T69：实现 `/task cancel <id>`

**文件：** `src/mewcode/commands/builtin.py`、`tests/test_builtin_commands.py`  
**依赖：** T66、T68

**步骤：**
1. 仅接受 `cancel <id>` 两个 token，并调用 CommandRuntime 的异步 cancel 接口。
2. 分别格式化 cancelled、already-terminal、already-requested 和 unknown，不把幂等结果当内部异常。
3. `/task` 的其他子命令、缺 ID 和额外参数返回明确 usage。
4. 验证 handler 不写主 history、不查询 Provider，也不取消其他任务。

**验证：** 运行 `python -m pytest tests/test_builtin_commands.py -q`，期望 `/task cancel` 只作用于指定活动任务且所有重复/非法输入无副作用。

### T70：向 Conversation 注入任务管理门面

**文件：** `src/mewcode/conversation.py`、`tests/test_conversation.py`  
**依赖：** T50、T66

**步骤：**
1. 为 Conversation 注入可选 TaskManager，提供 list/get/cancel 方法给 CommandRuntime 调用方。
2. 提供 `background_foreground_subagent()` 及 `subagent_terminal_events()`，只转发任务管理器的安全结果/事件流。
3. 未装配 TaskManager 时返回空列表、unknown/unavailable 等兼容结果，不启动后台 task。
4. 测试所有门面调用、异常到 `ConversationError` 的安全映射和现有普通 send 状态不变。

**验证：** 运行 `python -m pytest tests/test_conversation.py -q`，期望任务门面准确转发且无任务装配时普通 Conversation 完全兼容。

### T71：让根 Conversation 只在真实请求消费通知

**文件：** `src/mewcode/conversation.py`、`tests/test_conversation.py`、`tests/test_request_boundary.py`  
**依赖：** T51、T70

**步骤：**
1. 根 `send`/plan/execute/shared Skill 的 AgentRun 使用可消费通知的 `RootAgentRequestBoundary`。
2. Context compact、memory update、session maintenance、isolated Skill 和子 Agent 不绑定根消费边界。
3. 根 Agent 仍运行时完成的通知进入后续 iteration；空闲完成的通知进入下一用户任务首轮。
4. 测试上述两个时序以及 maintenance 先运行不消费，通知不进入 `Conversation.messages()` 或 SessionBinding commit。

**验证：** 运行 `python -m pytest tests/test_conversation.py tests/test_request_boundary.py -q`，期望每条通知只由下一次根真实请求消费且主历史始终不含通知。

### T72：按任务优先顺序实现 Conversation reset

**文件：** `src/mewcode/conversation.py`、`tests/test_conversation.py`  
**依赖：** T48、T70

**步骤：**
1. 保持主 run/context operation 活动时拒绝 reset；空闲时先 await TaskManager.reset。
2. 任务和通知清理成功后才等待 Memory、重置 Session、消息/plan、Skill 和主 Context。
3. TaskManager reset 失败转安全 `ConversationError`，不继续提交半重置会话。
4. 用调用日志验证顺序、幂等和 reset 后根请求收不到旧通知。

**验证：** 运行 `python -m pytest tests/test_conversation.py -q`，期望 reset 顺序固定、失败不半提交且旧任务结果完全清除。

### T73：按基础设施依赖顺序实现 Conversation close

**文件：** `src/mewcode/conversation.py`、`tests/test_conversation.py`  
**依赖：** T48、T70

**步骤：**
1. close 先取消主 Agent/compact，再关闭 TaskManager，使子任务停止使用共享基础设施。
2. 随后等待 Memory、发 session.end Hook、关闭 Session/Skill/主 Context，最后关闭共享 Hook；保留已有诊断聚合。
3. TaskManager close 关闭终态事件流，重复 Conversation.close 不重复关闭任何组件。
4. 用严格 fake 记录顺序，并验证某层抛错时普通异常安全收敛且后续资源仍尝试关闭。

**验证：** 运行 `python -m pytest tests/test_conversation.py -q`，期望生命周期顺序满足依赖、重复 close 幂等且无后台任务访问已关闭资源。

### T74：给终端增加 Ctrl+B 运行控制 reader

**文件：** `src/mewcode/terminal.py`、`tests/test_terminal.py`  
**依赖：** T10、T65

**步骤：**
1. 定义 `RunControl.BACKGROUND`，把异步 `read_run_control()` 加入 `TerminalSession`。
2. PromptToolkitTerminal 仅在无 PromptSession 消费输入时从现有 Input 等待 Ctrl+B；普通字符不触发控制，Ctrl+C 保留 KeyboardInterrupt/cancel 语义。
3. reader 被取消时释放输入等待且不关闭共享 Input；测试终端可注入确定按键，Legacy 路径返回可取消的未完成等待。
4. 覆盖 Ctrl+B、普通字符、Ctrl+C、取消和重新监听，不创建第二个 PromptSession。

**验证：** 运行 `python -m pytest tests/test_terminal.py -q`，期望只识别 Ctrl+B，取消可收敛且 Ctrl+C 行为不变。

### T75：实现 prompt-safe 异步终端通知

**文件：** `src/mewcode/terminal.py`、`tests/test_terminal.py`  
**依赖：** T74

**步骤：**
1. 为 TerminalSession 增加 `async notify(text)`；PromptToolkit 活动时使用安全的 run-in-terminal 输出并恢复 prompt。
2. 无活动 application、重定向输出和 LegacyTerminal 时直接写入并 flush。
3. 对通知文本执行单行和长度约束，不从 TaskManager done callback 直接访问 stdout。
4. 测试 prompt 活动/空闲、并发两条摘要、重定向输出和 notify 异常安全处理。

**验证：** 运行 `python -m pytest tests/test_terminal.py -q`，期望异步摘要不破坏当前提示符且所有输出路径及时 flush。

### T76：启动并收敛 REPL 任务终态监视器

**文件：** `src/mewcode/repl.py`、`tests/test_repl.py`  
**依赖：** T47、T70、T73、T75

**步骤：**
1. Conversation.start 后创建一个监视协程消费 `subagent_terminal_events()`。
2. 每个事件通过 `TerminalSession.notify` 输出 `subagent[short-id]: completed|failed|cancelled` 单行摘要，不显示完整结果。
3. Conversation.close 关闭事件流后再 await 监视器；无 TaskManager 的兼容路径不创建常驻任务。
4. 测试运行中通知、终端失败不杀死主循环、正常退出不漏最后事件和关闭后无悬空 task。

**验证：** 运行 `python -m pytest tests/test_repl.py -q`，期望任务终态即时显示、主输入继续工作且监视器在关闭时完全收敛。

### T77：竞速消费 Agent 事件与 Ctrl+B

**文件：** `src/mewcode/repl.py`、`tests/test_repl.py`  
**依赖：** T64、T70、T74

**步骤：**
1. `_consume` 同时维护一个 `anext(AgentEvent)` task 和一个 `read_run_control()` task，任一完成后继续另一侧。
2. Ctrl+B 调用 `Conversation.background_foreground_subagent()`，显示成功 task ID 或“无可转换任务”提示；不直接修改历史。
3. Agent source 完成/失败/取消时取消并 await 控制 reader；控制 reader 普通结束时可重新监听。
4. 渲染 `AgentSubagentProgress` 时只显示 `subagent[short-id]`、状态和有界进度，不显示子文本/参数。

**验证：** 运行 `python -m pytest tests/test_repl.py -q`，期望 Ctrl+B 原地转后台、Agent 事件不中断且源结束后没有输入 reader 残留。

### T78：保证权限提示与运行控制输入互斥

**文件：** `src/mewcode/repl.py`、`tests/test_repl.py`  
**依赖：** T74、T77

**步骤：**
1. 收到 `AgentPermissionRequest` 时先取消并 await 当前 run-control reader，再调用 `prompt_permission`。
2. 权限选择完成或 EOF 自动拒绝后，若 Agent source 仍活动再创建新的 run-control reader。
3. 任一时刻只允许主 prompt、权限 PromptSession 或 run-control reader 中一个消费 Terminal Input。
4. 覆盖权限期间 Ctrl+B 字节不被误消费、权限后 Ctrl+B 可用、Ctrl+C 仍取消当前主 Agent 而不取消已后台任务。

**验证：** 运行 `python -m pytest tests/test_repl.py tests/test_terminal.py -q`，期望所有输入消费者严格互斥且 Ctrl+B/C 两种语义稳定。

### T79：执行 B7 本地交互回归门

**文件：** `src/mewcode/commands/contracts.py`、`src/mewcode/commands/builtin.py`、`src/mewcode/conversation.py`、`src/mewcode/terminal.py`、`src/mewcode/repl.py`、`tests/test_builtin_commands.py`、`tests/test_conversation.py`、`tests/test_terminal.py`、`tests/test_repl.py`  
**依赖：** T66–T78

**步骤：**
1. 运行命令、Conversation、Terminal、REPL、任务和通知定向测试。
2. 模拟前台快速完成、Ctrl+B detach、后台终态摘要、`/tasks`、`/task`、cancel、下一根请求通知和 `/reset` 全链路。
3. 确认任务命令没有 Provider 调用或 history commit，输入同一时刻一个消费者，关闭后无 pending asyncio task。

**验证：** 运行 `python -m pytest tests/test_builtin_commands.py tests/test_conversation.py tests/test_terminal.py tests/test_repl.py tests/test_subagent_tasks.py tests/test_subagent_notifications.py -q`，期望全部通过且现有普通命令、权限提示与 Ctrl+C 回归无失败。

## B8：CLI 装配、内置角色与文档

### T80：添加内置 explore 角色

**文件：** `src/mewcode/subagents/builtin/explore.md`、`tests/test_subagent_catalog.py`  
**依赖：** T30

**步骤：**
1. 创建 `explore.md`，七字段完整，name=`explore`、model=`inherit`、permission mode=`default`，只白名单 `read_file`、`find_files`、`search_code`。
2. 正文明确它负责只读代码库调查、引用证据、报告不确定性，不修改文件或继续委派。
3. 通过默认 built-in 根发现并解析该文件，验证正文随目录快照完整载入。
4. 验证 wheel 使用的 `src/mewcode` 包目录能通过 `AgentDefinitionRoots.defaults` 定位资源，不增加动态生成步骤。

**验证：** 运行 `python -m pytest tests/test_subagent_catalog.py -q`，期望默认目录包含合法 `explore` 且其可执行工具仅为三个只读工具。

### T81：添加可复制的 code-reviewer 示例

**文件：** `examples/agents/code-reviewer.md`、`tests/test_subagent_parser.py`  
**依赖：** T26

**步骤：**
1. 创建完整七字段的 `code-reviewer` 示例，使用只读检索工具、`model: inherit` 和有界轮次。
2. 正文要求按严重度报告发现、给出文件证据、避免无证据结论和任何写入。
3. 直接用生产 parser 解析示例，防止文档样例与实现格式漂移。

**验证：** 运行 `python -m pytest tests/test_subagent_parser.py -q`，期望示例文件可被生产解析器加载且字段符合只读角色预期。

### T82：先注册任务命令并保留 Agent 工具名

**文件：** `src/mewcode/cli.py`、`tests/test_subagent_integration.py`、`tests/test_repl.py`  
**依赖：** T67–T69

**步骤：**
1. CLI 首先创建包含 `/tasks`、`/task` 的静态命令目录，再进行 Profile、Provider、MCP、Skill 或角色装配。
2. MCP 启动 reserved names 增加 `agent`，同时继续保留 built-in、`load_skill` 和 Skill 包工具名称。
3. Skill 命令与 `/tasks`、`/task` 冲突时沿用 `CommandRegistrationError` 在 Provider/后台任务启动前失败。
4. 用启动探针验证注册顺序、MCP reserved 集合和冲突零外部副作用。

**验证：** 运行 `python -m pytest tests/test_subagent_integration.py tests/test_repl.py -q`，期望静态冲突最早失败且 MCP 永远不能注册名为 `agent` 的工具。

### T83：为每个 Profile 缓存完整 Provider 包装栈

**文件：** `src/mewcode/cli.py`、`tests/test_subagent_integration.py`、`tests/test_hook_provider.py`、`tests/test_request_boundary.py`  
**依赖：** T3、T51

**步骤：**
1. 为每个 Profile 缓存 `HookedProvider(RequestBoundaryProvider(UsageTrackingProvider))`，有无 Hook 规则都保持同一层次。
2. 根运行、定义式、Fork、Context compact 和 Memory 复用相同 Profile 的底层客户端及 UsageLedger，但只在绑定的 ContextVar 下执行对应请求边界。
3. 多 Profile 按名称分别缓存，未知 Profile 在创建任务前由目录/协调器拒绝。
4. 测试包装身份、Hook → boundary → usage → real provider 顺序、空 Hook 快速路径和跨 Profile 隔离。

**验证：** 运行 `python -m pytest tests/test_subagent_integration.py tests/test_hook_provider.py tests/test_request_boundary.py tests/test_usage_tracking.py -q`，期望每个 Profile 只有一个完整包装栈且 usage 不重复记录。

### T84：在启动期构建冻结角色目录

**文件：** `src/mewcode/cli.py`、`tests/test_subagent_integration.py`、`tests/test_subagent_catalog.py`  
**依赖：** T30、T80、T83

**步骤：**
1. 基础/MCP 工具和全部 Profile 可用后、任何任务或终端监视器创建前，发现并构建 `AgentDefinitionCatalog`。
2. 已知角色工具和后台能力名单均冻结自 `base_registry.names`；全局禁止冻结为 `agent`、`load_skill` 和未来显式模型代理控制工具。
3. 启动装配 helper 接受内部注入的 plugin agent roots，缺省为空；不新增 CLI flag、插件扫描或热重载。
4. 单候选错误进入启动诊断；同层有效冲突、总量错误等 catalog fatal error 中止启动。

**验证：** 运行 `python -m pytest tests/test_subagent_integration.py tests/test_subagent_catalog.py -q`，期望目录在任务系统前冻结、插件根只可注入且 fatal 目录错误零后台副作用。

### T85：装配权限快照、运行时工厂与任务管理器

**文件：** `src/mewcode/cli.py`、`tests/test_subagent_integration.py`  
**依赖：** T52、T58、T84

**步骤：**
1. 主持久权限 RuleStore 创建后提供只读 snapshot supplier，子任务每次从当前持久三层复制并清空 session。
2. 用共享 Profile provider supplier、PromptBuilder、Workspace、HookRuntime、base registry、Context 配置和基础 additions supplier创建 `SubagentRuntimeFactory`。
3. 依次创建 NotificationQueue、TaskManager、SubagentCoordinator 和唯一 AgentTool；产品上限/超时全部取 T22 单一常量。
4. 用构造替身记录依赖身份和创建顺序，保证任务组件不会早于角色目录或权限规则。

**验证：** 运行 `python -m pytest tests/test_subagent_integration.py -q`，期望子 Agent 组件完整装配、共享/隔离依赖正确且默认值没有第二来源。

### T86：合并根工具注册表并保持 Skill 边界

**文件：** `src/mewcode/cli.py`、`src/mewcode/skills/runtime.py`、`tests/test_subagent_integration.py`、`tests/test_skill_runtime.py`  
**依赖：** T20、T62、T85

**步骤：**
1. 最终根 registry 按稳定顺序合并 `base + load_skill + agent`，角色数量和任务状态不参与构造。
2. 最终 Skill catalog 的全局工具名称包含 `agent`，但角色目录仍只允许 base 工具。
3. `SkillRuntime.set_global_tools` 接收根 registry；共享 Skill 根视图保留 agent，isolated Skill 视图不获得它。
4. 测试无角色/多角色/Skill 激活/任务运行中工具列表与 AgentTool schema 完全一致。

**验证：** 运行 `python -m pytest tests/test_subagent_integration.py tests/test_skill_runtime.py tests/test_subagent_control.py -q`，期望根工具列表稳定且任何 isolated 模型运行都不能取得 AgentTool。

### T87：连接根 Runner、Conversation 与 REPL

**文件：** `src/mewcode/cli.py`、`src/mewcode/conversation.py`、`tests/test_subagent_integration.py`、`tests/test_conversation.py`  
**依赖：** T65、T71、T73、T79、T86

**步骤：**
1. 根 AgentRunner 注入 Profile 名、实时主权限模式 supplier、根请求边界工厂和通用 Hook/Context；Conversation 每次 start 传入该模式实际 `allowed_safety`。
2. isolated Skill Runner 保持 capture-only/无通知且工具视图无 agent；SubagentRuntimeFactory 使用任务 scope。
3. Conversation 注入 TaskManager 和 NotificationQueue 相关边界，REPL 注入同一 Conversation/终端/命令目录。
4. 正常关闭由 Conversation 幂等清理主/子运行后，CLI finally 只关闭未交给 Conversation 或构造中途失败的资源。

**验证：** 运行 `python -m pytest tests/test_subagent_integration.py tests/test_conversation.py tests/test_repl.py -q`，期望三类 Runner 请求边界正确、模式安全集合准确且关闭不重复。

### T88：收敛启动错误、诊断与部分装配清理

**文件：** `src/mewcode/cli.py`、`tests/test_subagent_integration.py`、`tests/test_repl.py`  
**依赖：** T84–T87

**步骤：**
1. 启动消息追加有界角色诊断，禁止正文、凭据、完整异常栈或原始 Provider 响应进入输出。
2. 捕获 `AgentDefinitionError`/`AgentCatalogError` 为稳定 CLI 错误；普通子任务失败不能逃逸到 CLI 主循环。
3. 对角色目录后、MCP 后、TaskManager 后和 Conversation 后分别注入启动失败，验证已创建资源按逆依赖安全关闭。
4. 正常退出、KeyboardInterrupt 和重复 finally 不持久化任务表/通知，也不重复结束 shared Hook/Provider。

**验证：** 运行 `python -m pytest tests/test_subagent_integration.py tests/test_repl.py -q`，期望所有部分启动失败安全清理、错误去敏且退出码保持既有语义。

### T89：记录用户可见用法与边界

**文件：** `README.md`、`src/mewcode/subagents/builtin/explore.md`、`examples/agents/code-reviewer.md`  
**依赖：** T80、T81、T88

**步骤：**
1. 记录七字段角色格式、项目/用户/内置/插件注入优先级、Profile 语义、无热重载和无内置模型别名。
2. 记录固定 AgentTool 的 defined/fork 调用、前台 10 秒、显式/Fork 后台、`Ctrl+B`、`/tasks` 和 `/task`。
3. 解释 ASK 自动拒绝、多层工具收窄、Fork schema 与执行权限分离、共享文件系统和不可信一次性通知。
4. 明确 Worktree、团队编排、跨会话持久化、嵌套 Agent、交互审批和缓存命中保证均不在本阶段。

**验证：** 运行 `rg -n "tools:|disallowed_tools:|model:|max_turns:|permission_mode:|/tasks|/task|Ctrl\+B|Fork|Worktree" README.md examples/agents/code-reviewer.md src/mewcode/subagents/builtin/explore.md`，期望所有关键格式、操作和边界均有明确说明。

### T90：执行 B8 实际入口装配回归门

**文件：** `src/mewcode/cli.py`、`src/mewcode/subagents/builtin/explore.md`、`examples/agents/code-reviewer.md`、`README.md`、`tests/test_subagent_integration.py`  
**依赖：** T80–T89

**步骤：**
1. 运行 CLI 装配、角色目录、Skill、Conversation 和 REPL 定向测试。
2. 用 fake application 启动到主 prompt，检查 `/tasks`、`/task`、根 registry、explore 角色、Provider 栈和关闭顺序。
3. 从临时安装布局解析包内 explore，并验证没有角色/任务时不创建额外模型请求、日志或会话写入。

**验证：** 运行 `python -m pytest tests/test_subagent_integration.py tests/test_subagent_catalog.py tests/test_skill_runtime.py tests/test_conversation.py tests/test_repl.py -q`，期望实际 CLI 入口完整装配且无任务快速路径保持兼容。

## B9：缓存前缀、端到端与全量回归

### T91：建立确定性子 Agent 集成测试夹具

**文件：** `tests/test_subagent_integration.py`  
**依赖：** T90

**步骤：**
1. 建立可脚本化 Provider、ProfileCatalog、Hook executor、权限规则、工具、单调时钟、任务等待器、Terminal 和 SessionBinding 夹具。
2. 夹具能阻塞/释放模型或工具、精确返回 usage、记录请求/Hook/历史/会话写入及驱动取消次数。
3. 每个用例结束断言无 pending asyncio task、未消费通知或遗留任务 ContextArchive。

**验证：** 运行 `python -m pytest tests/test_subagent_integration.py -q`，期望集成夹具自检通过且测试不访问网络、不真实等待 10 秒。

### T92：验证固定入口与角色启动边界

**文件：** `tests/test_subagent_integration.py`  
**依赖：** T91

**步骤：**
1. 在无角色、单角色、多角色和已有任务四种状态比较根工具列表及 AgentTool schema。
2. 通过实际 Scheduler 提交所有非法参数组合、未知角色、64 KiB 任务边界及容量已满，验证零 Provider/任务副作用。
3. 启动后修改角色文件与父 session 权限，验证已冻结目录和任务启动说明不变。

**验证：** 运行 `python -m pytest tests/test_subagent_integration.py -q -k "stable_entry or launch_boundary"`，期望固定入口逐字一致且所有启动错误发生在模型请求前。

### T93：端到端验证定义式前台快速完成

**文件：** `tests/test_subagent_integration.py`  
**依赖：** T91

**步骤：**
1. 让根模型调用 `agent(type=defined, role=explore)`，子模型使用一次只读工具后在虚拟 10 秒内自然结束。
2. 验证子首轮空历史、角色动态区、三层工具交集、独立权限/Context/usage 和自然终态。
3. 根 AgentTool 只收到有界最终结果和 usage 后继续回答；主 history/Session JSONL 不包含子中间消息、工具结果或通知。

**验证：** 运行 `python -m pytest tests/test_subagent_integration.py -q -k "defined_foreground"`，期望完整前台委派只向主上下文返回一次最终 ToolResult。

### T94：端到端验证转后台、命令与一次性通知

**文件：** `tests/test_subagent_integration.py`  
**依赖：** T91

**步骤：**
1. 分别用虚拟 10 秒和 Ctrl+B 把定义式任务原地转后台，证明 Provider 调用、消息、权限和 usage 未重启。
2. 验证终态单行摘要、`/tasks`、`/task <id>`、另一个活动任务的 cancel 及 20 条通知分批。
3. 根仍运行和已空闲两种时序下，通知只进入下一真实根请求一次，不进入 history/Session。
4. 执行 `/reset`，验证活动任务、记录、Hook 分区和待通知全部清空。

**验证：** 运行 `python -m pytest tests/test_subagent_integration.py -q -k "background or notification or reset"`，期望后台生命周期、命令和一次性通知全链路通过。

### T95：验证 Provider 无关的 Fork 请求前缀

**文件：** `tests/test_subagent_runtime.py`、`tests/test_subagent_integration.py`  
**依赖：** T57、T91

**步骤：**
1. 构造包含长历史、Hook Context、动态通知和稳定工具顺序的父实际 `ModelRequest`，从其 AgentControlContext 发起 Fork。
2. 比较 Fork 首轮的 Profile、stable/dynamic prompt、父 messages、tools 和 max output；新增 task 之前全部值和顺序一致。
3. 验证 Fork 立即返回后台 ID、独立轮次/Context/权限/usage，schema 中 agent 调用被策略拒绝且不创建嵌套任务。
4. 容量不足时在 Provider 前明确失败，不压缩或退化为非前缀请求。

**验证：** 运行 `python -m pytest tests/test_subagent_runtime.py tests/test_subagent_integration.py -q -k "fork_prefix or fork_capacity or fork_nesting"`，期望 Provider 无关模型请求前缀完整保留且执行能力不扩大。

### T96：逐字节比较 Anthropic 父/Fork 适配请求

**文件：** `tests/test_subagent_integration.py`  
**依赖：** T95

**步骤：**
1. 用 fake Anthropic SDK 捕获父请求和 Fork 首次请求的实际 keyword payload。
2. 对 system cache block、父 messages 前缀、tools 数组及其顺序做确定 JSON UTF-8 字节比较；只允许 messages 尾部增加 task。
3. 验证父 stable system 的 ephemeral cache control 保持，Provider 报告 cache usage 时原样计量；未报告不伪造。
4. 不断言供应商实际缓存命中，也不因 cache read 为零重试。

**验证：** 运行 `python -m pytest tests/test_subagent_integration.py -q -k "anthropic_fork_bytes"`，期望新增 task 之前的 Anthropic 请求片段逐字节一致。

### T97：逐字节比较 OpenAI 父/Fork 适配请求

**文件：** `tests/test_subagent_integration.py`  
**依赖：** T95

**步骤：**
1. 用 fake OpenAI SDK 捕获父请求和 Fork 首次请求的 Responses API keyword payload。
2. 对 stable/dynamic system input、父 input 前缀、tools 数组及其顺序做确定 JSON UTF-8 字节比较；只允许末尾增加 task input。
3. 验证 explicit prompt cache options 与由 stable system/tools 生成的 cache key 不变，usage 完全采用 Provider 事件。
4. 不把实际 cache hit 作为正确性条件，也不增加重试请求。

**验证：** 运行 `python -m pytest tests/test_subagent_integration.py -q -k "openai_fork_bytes"`，期望新增 task 之前的 OpenAI 请求片段及 cache key 逐字节一致。

### T98：集成验证并发、安全和进程内边界

**文件：** `tests/test_subagent_integration.py`  
**依赖：** T91

**步骤：**
1. 并发保持 8 个任务并超额委派，验证活动数不超限；同时制造完成/取消、detach/完成和 delivered/retention 竞态。
2. 并发触发根、两个子任务及维护 Hook，验证 scope、prompt 队列、权限决策和文件观察不串线。
3. 注入含伪系统指令、异常、长结果和敏感参数的任务失败，验证有界去敏与不可信通知边界。
4. 关闭并重新建立 application，验证任务表/通知为空、Session JSONL 无子内部消息且共享工作区已提交文件仍存在。

**验证：** 运行 `python -m pytest tests/test_subagent_integration.py -q -k "concurrency or isolation or process_boundary"`，期望并发上限、单终态、安全输出和纯进程内状态全部成立。

### T99：运行全部受影响模块的定向回归

**文件：** 本文档列出的全部测试文件  
**依赖：** T92–T98

**步骤：**
1. 运行所有 `test_subagent_*`、request boundary 及 Plan 指定的既有回归文件。
2. 检查普通对话、PLAN、权限、Hook、Context、Memory、MCP、Skill、命令、Terminal 和 Provider 适配均无回归。
3. 修复失败时只按已批准 Spec/Plan/Tasks 调整，不新增持久化、Worktree、团队编排或嵌套 Agent 范围。

**验证：** 运行 `python -m pytest tests/test_subagent_paths.py tests/test_subagent_parser.py tests/test_subagent_catalog.py tests/test_subagent_policy.py tests/test_subagent_permissions.py tests/test_subagent_scoped_tools.py tests/test_subagent_notifications.py tests/test_subagent_tasks.py tests/test_subagent_runtime.py tests/test_subagent_control.py tests/test_subagent_integration.py tests/test_request_boundary.py tests/test_agent_runner.py tests/test_tool_scheduler.py tests/test_hook_runtime.py tests/test_hook_provider.py tests/test_prompt_builder.py tests/test_context_manager.py tests/test_skill_runtime.py tests/test_builtin_commands.py tests/test_conversation.py tests/test_repl.py tests/test_terminal.py -q`，期望全部通过。

### T100：执行全量测试与交付前一致性检查

**文件：** 本阶段创建或修改的全部文件  
**依赖：** T99

**步骤：**
1. 运行完整 pytest，确认所有既有与新增测试通过。
2. 运行 `git diff --check`，检查无空白错误；确认没有意外修改用户已有 `__pycache__` 或其他无关文件。
3. 重新解析内置/示例角色，并核对 AgentTool schema、产品限制常量、README 命令和实际实现一致。
4. 记录测试数量、耗时和任何环境性跳过，作为进入 checklist 验收的证据。

**验证：** 运行 `python -m pytest -q`，期望完整测试套件通过；再运行 `git diff --check`，期望无输出且退出码为 0。

## 执行顺序

批次内按 T 编号执行。B4 与 B5 在 B3 通过后没有相互依赖，可并行实现；进入 B6 前两者必须都通过。其余批次严格串行：

```text
B1  T1–T10
  -> B2  T11–T21
  -> B3  T22–T30
       ├-> B4  T31–T37 ─┐
       └-> B5  T38–T50 ─┴-> B6  T51–T65
                              -> B7  T66–T79
                              -> B8  T80–T90
                              -> B9  T91–T100
```

每个普通任务完成后立即运行该任务的验证命令；每个批次末尾先通过对应回归门，再进入后继批次。若验证失败，修复并重跑当前任务，不带着已知失败继续推进。

## Plan 组件覆盖

| Plan 组件 | 实现任务 | 主要验证任务 |
|---|---|---|
| 通用请求边界、父请求捕获 | T1–T3、T7–T9 | T21、T51、T95–T97 |
| Agent 控制上下文、策略调度、事件 | T4–T10 | T21、T32、T64 |
| Prompt 动态角色区 | T11–T12 | T53、T93 |
| Hook task scope 与 prompt 分区 | T13–T15 | T55、T57、T98 |
| Context/Skill 通用兼容扩展 | T17–T20 | T54、T57、T86 |
| 角色模型、发现、解析、目录 | T22–T30 | T80–T81、T84、T92 |
| 定义式/Fork 工具策略 | T31–T34 | T54、T56、T95 |
| 非交互权限隔离 | T35–T36 | T54、T56、T93、T98 |
| 通知队列与根请求注入 | T38–T40、T51 | T71、T94、T98 |
| 任务状态机、前后台、取消、保留 | T41–T50 | T63–T64、T94、T98 |
| 隔离运行时 | T52–T58 | T65、T93–T95 |
| Coordinator 与固定 AgentTool | T59–T64 | T65、T92–T95 |
| 本地任务命令 | T66–T69 | T79、T94 |
| Conversation 生命周期 | T70–T73 | T79、T94、T98 |
| Terminal/REPL 控制与通知 | T74–T79 | T94 |
| CLI、Provider 栈、Skill 视图与资源 | T80–T90 | T92–T98 |
| Anthropic/OpenAI 缓存前缀 | T95–T97 | T99–T100 |
| 兼容性、端到端与全量回归 | T91–T100 | T100 |
