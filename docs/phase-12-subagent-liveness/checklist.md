# 子 Agent 活性保护 Checklist

> 每项都通过运行代码或观察公开任务行为验证；时间测试使用虚拟 sleep/clock，不真实等待 300 秒。

## 内置探索角色与安全边界

- [x] C1 `[AC1]` 生产角色目录加载的内置 `explore` 仍只包含 `read_file`、`find_files`、`search_code`，权限模式为 `allow`。（验证：运行 `python -m pytest tests/test_subagent_catalog.py -q -k "builtin"`，期望角色字段逐项匹配。）

- [x] C2 `[AC1]` 在项目和用户权限规则均不允许源码通配参数时，内置 explore 能实际执行 find/read/search 三种工具并自然完成，不产生 `SUBAGENT_NON_INTERACTIVE` 拒绝。（验证：运行 `python -m pytest tests/test_subagent_integration.py -q -k "explore_liveness"`，期望三种底层工具各执行一次。）

- [x] C3 `[AC1][N4]` explore 的 allow 模式不扩大冻结能力：写工具不出现在请求 schema，嵌套 agent 被策略拒绝，越界路径被硬检查或 Workspace 拒绝。（验证：运行 `python -m pytest tests/test_subagent_policy.py tests/test_subagent_integration.py -q -k "explore or forbidden or boundary"`，期望无越权执行。）

- [x] C4 `[N4]` 其他定义式角色的 `strict/default/allow` 语义、持久规则快照和空 session 规则保持不变，系统不改写 `.mewcode/permissions.local.yaml`。（验证：运行 `python -m pytest tests/test_subagent_permissions.py tests/test_subagent_control.py -q`，期望全部通过且测试工作区权限文件无额外写入。）

## 连续拒绝熔断

- [x] C5 `[AC2]` 子 Agent 连续 3 个非空工具批次全部为权限拒绝时，在第三批结果成对提交后以 `tool_denial_limit` 停止，Provider 总请求数严格为 3。（验证：运行 `python -m pytest tests/test_agent_runner.py tests/test_subagent_runtime.py -q -k "denial_limit"`。）

- [x] C6 `[AC2]` 冻结策略拒绝和 Hook 拒绝分别计入同一上限，错误只含安全原因与计数，不含完整参数、Provider 原始响应或内部模型内容。（验证：运行相同测试并检查 outcome error 与 ToolResult metadata。）

- [x] C7 `[AC2]` 阈值前两批拒绝仍返回模型纠错；命中第三批后不发生第四次 Provider 调用、Context compact 或工具执行。（验证：用调用计数探针运行 `python -m pytest tests/test_agent_runner.py -q -k "denial_limit"`。）

- [x] C8 `[AC2][AC5]` 根 Agent 默认不启用拒绝熔断；其用户权限交互和最大轮次行为与修复前一致。（验证：运行 `python -m pytest tests/test_agent_runner.py tests/test_permission_integration.py tests/test_conversation.py -q`。）

- [x] C9 `[AC3]` 一个批次只要含至少一个成功执行就把拒绝计数归零；含未知工具、参数错误或普通执行失败但不是“全部拒绝”的批次也不累计。（验证：运行 `python -m pytest tests/test_agent_runner.py -q -k "denial_limit and reset"`。）

- [x] C10 `[AC3][AC5]` 连续未知工具仍由既有 `unknown_tool_limit` 独立停止，不被重分类；用户取消优先产生 cancelled。（验证：运行 `python -m pytest tests/test_agent_runner.py -q -k "unknown or cancel or denial_limit"`。）

## 300 秒整体执行期限

- [x] C11 `[AC3]` `SUBAGENT_EXECUTION_TIMEOUT_SECONDS` 等于 `300.0`，TaskManager 默认使用它且拒绝零值、负值或非有限值。（验证：运行 `python -m pytest tests/test_subagent_tasks.py -q -k "execution_timeout and config"`。）

- [x] C12 `[AC3][N2]` Driver factory 阻塞、Provider/事件阻塞和工具阻塞均可用虚拟 sleep 触发期限，不访问网络且测试实际耗时远低于 300 秒。（验证：运行 `python -m pytest tests/test_subagent_tasks.py -q -k "execution_timeout"`。）

- [x] C13 `[AC3]` 期限获胜时活动 Driver cancel 与 close 各最多一次，执行 Task 被收敛，任务以 `failed` 结束且错误明确为 300 秒执行期限。（验证：检查同一测试的调用计数、snapshot 和无 pending task 断言。）

- [x] C14 `[AC3][N3]` 超时 snapshot、`/task` 详情、终端摘要和一次性根通知共享相同 failed 状态、错误和截至超时 usage，各只产生一次。（验证：运行 `python -m pytest tests/test_subagent_tasks.py tests/test_subagent_notifications.py tests/test_builtin_commands.py tests/test_subagent_integration.py -q -k "execution_timeout"`。）

- [x] C15 `[AC3]` 定义式、Fork、Shared 和 Worktree Driver 走同一期限路径；Worktree 清理信息可保留但不得把超时 failed 覆盖为 completed/cancelled。（验证：运行 `python -m pytest tests/test_subagent_tasks.py tests/test_subagent_worktree.py tests/test_subagent_integration.py -q -k "timeout or execution_timeout"`。）

## 前后台与竞态

- [x] C16 `[AC4]` 前台任务注册后虚拟 10 秒原地转后台，Provider、Driver、消息、权限和 usage 不重启，剩余期限为约 290 秒而非重新 300 秒。（验证：运行 `python -m pytest tests/test_subagent_tasks.py tests/test_subagent_integration.py -q -k "detach_deadline"`。）

- [x] C17 `[AC4]` 显式后台定义式和强制后台 Fork 均从注册时刻计算期限；进入后台不创建第二个 deadline Task。（验证：检查可控 sleep 调用次数和参数。）

- [x] C18 `[N3]` 自然完成与期限同时就绪时，已经完成的执行结果优先且仅产生一个 completed；后到的期限没有通知或状态副作用。（验证：运行 `python -m pytest tests/test_subagent_tasks.py -q -k "timeout_race and completed"`。）

- [x] C19 `[N3]` 用户取消与期限竞态只产生一个终态：用户取消先赢为 cancelled，期限先赢为 failed；Driver/通知/终端事件不重复。（验证：运行 `python -m pytest tests/test_subagent_tasks.py -q -k "timeout_race and cancel"`。）

- [x] C20 `[N3]` Driver cancel/close 抛错时任务仍收敛为有界失败，TaskManager 可继续注册后续任务，关闭时无遗留 asyncio Task。（验证：运行 `python -m pytest tests/test_subagent_tasks.py -q -k "timeout and failure"`。）

## 集成与兼容性

- [x] C21 `[AC5]` Fork 首次请求的 prompt/messages/tools/max output 及 Anthropic/OpenAI 缓存前缀不因活性保护变化。（验证：运行 `python -m pytest tests/test_subagent_runtime.py tests/test_subagent_integration.py -q -k "fork"`。）

- [x] C22 `[AC5]` 正常快速完成、前台 10 秒 detach、手动 Ctrl+B、`/tasks`、`/task cancel`、reset 和 close 生命周期保持通过。（验证：运行 `python -m pytest tests/test_subagent_control.py tests/test_subagent_tasks.py tests/test_conversation.py tests/test_repl.py -q`。）

- [x] C23 当前未提交的 Phase 13 Worktree 功能保持兼容，本阶段没有回退其模型、Driver、通知、命令或清理字段。（验证：运行 `python -m pytest tests/test_subagent_worktree.py tests/worktrees -q`，并人工核对本阶段 diff 为局部合并。）

- [x] C24 通用 Agent/Provider/Hook/Permission 层不反向导入 `mewcode.subagents`。（验证：运行 `rg -n "mewcode\.subagents" src/mewcode/agent src/mewcode/providers src/mewcode/hooks src/mewcode/permissions`，期望无匹配。）

## 测试与交付

- [x] C25 所有新增活性保护测试和受影响模块定向回归通过。（验证：运行 `python -m pytest tests/test_agent_runner.py tests/test_tool_scheduler.py tests/test_subagent_permissions.py tests/test_subagent_policy.py tests/test_subagent_runtime.py tests/test_subagent_tasks.py tests/test_subagent_catalog.py tests/test_subagent_integration.py tests/test_subagent_worktree.py tests/test_conversation.py tests/test_repl.py -q`。）

- [x] C26 完整 pytest 无失败，记录通过/跳过数量与耗时。（验证：运行 `python -m pytest -q`。）

- [x] C27 交付 diff 无空白错误且不包含对用户已有 Phase 13、Hook 配置、缓存文件或其他无关改动的覆盖。（验证：运行 `git diff --check` 与 `git status --short`，按基线逐项区分。）

- [x] C28 文档中的 3 次拒绝、300 秒期限、failed 超时和 explore allow 与实现常量及测试一致，不存在新增角色字段或自动权限写入。（验证：运行资源解析测试并搜索相关常量、README/角色文本。）

## 端到端场景

- [x] C29 `[AC1][AC2]` 无源码权限规则的真实 explore：find → read → search 成功完成；随后模拟嵌套/越权连续拒绝，在 3 次内明确失败且不继续请求。（验证：运行 `python -m pytest tests/test_subagent_integration.py -q -k "explore_liveness"`。）

- [x] C30 `[AC3][AC4]` 长任务：前台虚拟 10 秒转后台 → 沿用原执行 → 注册后虚拟 300 秒失败 → 单行摘要 → `/task` 显示 usage → 下一根请求仅注入一次通知。（验证：运行 `python -m pytest tests/test_subagent_integration.py -q -k "detach_deadline or execution_timeout"`。）

## 验收记录要求

执行时为 C1–C30 记录实际命令、退出码、通过/跳过/失败数及关键观察。任何失败必须修复并重跑；全部通过后才可宣告本阶段完成。

## 本次验收记录（2026-08-14）

- C1–C3、C29：`python -m pytest tests/test_subagent_catalog.py -q -k "builtin"` 为 `1 passed, 11 deselected`；`python -m pytest tests/test_subagent_integration.py -q -k "explore_liveness or execution_timeout"` 为 `2 passed, 5 deselected`。生产角色目录中的 explore 为 `allow` 且仅暴露三种只读工具；无源码权限规则时 find/read/search 实际完成，后台期限链路产生一次 failed 通知。
- C5–C10：`python -m pytest tests/test_agent_runner.py -q -k "denial_limit and reset"` 为 `2 passed, 40 deselected`；权限/Hook 全拒绝在第三批停止，普通失败与成功均重置计数，根默认配置保持关闭。
- C11–C20、C30：`python -m pytest tests/test_subagent_tasks.py -q -k "detach_deadline or (timeout and failure) or (timeout_race and completed) or (timeout_race and cancel)"` 为 `6 passed, 22 deselected`。虚拟时钟确认期限从注册时刻连续计算；完成/取消/期限竞态仅提交一个终态；cancel/close 失败后管理器仍可继续运行任务。
- C15、C23：`python -m pytest tests/test_subagent_worktree.py tests/worktrees -q` 为 `41 passed in 12.90s`。超时保持 failed，同时保留 usage 与 Worktree 清理摘要；Phase 13 回归通过。
- C4、C21–C22、C25：受影响模块定向回归命令为 `python -m pytest tests/test_agent_runner.py tests/test_tool_scheduler.py tests/test_subagent_permissions.py tests/test_subagent_policy.py tests/test_subagent_runtime.py tests/test_subagent_tasks.py tests/test_subagent_catalog.py tests/test_subagent_integration.py tests/test_subagent_worktree.py tests/test_conversation.py tests/test_repl.py -q`，结果 `186 passed in 2.47s`。
- C24、C27–C28：`rg -n "mewcode\.subagents" src/mewcode/agent src/mewcode/providers src/mewcode/hooks src/mewcode/permissions` 无匹配；`git diff --check` 与 `git diff --cached --check` 退出码均为 0，仅显示现有行尾转换警告。核对 diff 后，本阶段未覆盖已暂存的 Phase 13、Hook 配置或缓存改动。
- C26：`python -m pytest -q` 退出码 0，结果 `1004 passed in 26.21s`，无跳过、无失败。
