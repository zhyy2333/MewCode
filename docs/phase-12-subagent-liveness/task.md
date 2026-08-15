# 子 Agent 活性保护 Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 修改 | `src/mewcode/subagents/builtin/explore.md` | 让冻结只读角色采用无需确认的权限模式 |
| 修改 | `src/mewcode/agent/events.py` | 定义连续工具拒绝的停止原因 |
| 修改 | `src/mewcode/agent/runner.py` | 增加可选拒绝上限、批次判定和停止逻辑 |
| 修改 | `src/mewcode/subagents/models.py` | 定义 300 秒子任务期限常量 |
| 修改 | `src/mewcode/subagents/__init__.py` | 导出期限常量 |
| 修改 | `src/mewcode/subagents/runtime.py` | 为子 Runner 启用拒绝上限并映射错误 |
| 修改 | `src/mewcode/subagents/tasks.py` | 监督 Driver 执行期限和竞态收敛 |
| 修改 | `tests/test_agent_runner.py` | 验证拒绝熔断及根默认兼容 |
| 修改 | `tests/test_subagent_runtime.py` | 验证子运行时启用配置和 outcome |
| 修改 | `tests/test_subagent_tasks.py` | 验证总期限、取消、清理与竞态 |
| 修改 | `tests/test_subagent_catalog.py` | 验证内置 explore 权限与工具边界 |
| 修改 | `tests/test_subagent_integration.py` | 验证实际探索任务和完整活性保护链 |
| 修改 | `docs/phase-14-subagent-liveness/checklist.md` | 记录逐项验收证据 |

## T1：建立拒绝批次分类测试

**文件：** `tests/test_agent_runner.py`  
**依赖：** 无

**步骤：**
1. 增加脚本化 Provider/工具结果用例，分别产生全权限拒绝、全 Hook 拒绝、策略拒绝、成功与拒绝混合、未知工具和普通执行失败。
2. 先断言现状会继续请求，以稳定复现成本问题；测试名称表达期望终态而不依赖私有实现。
3. 覆盖阈值边界 2/3、成功批次重置和根默认关闭三条路径。

**验证：** 运行 `python -m pytest tests/test_agent_runner.py -q -k "denial_limit"`；实现前期望新增用例失败且能证明第 4 次模型请求发生，实现后期望全部通过。

## T2：实现通用连续拒绝熔断

**文件：** `src/mewcode/agent/events.py`、`src/mewcode/agent/runner.py`、`tests/test_agent_runner.py`  
**依赖：** T1

**步骤：**
1. 为运行配置增加默认关闭的正整数拒绝上限校验，并增加 `tool_denial_limit` 停止原因。
2. 在 Scheduler 原始 executions 上判定非空全拒绝批次；只接受既有 `permission_denied` 或 `hook_denied` 标记。
3. 在 assistant/tool messages 成对提交后更新计数；命中上限则在下一次 Provider 调用前停止并返回有界错误。
4. 保持取消优先，未知工具计数独立，成功或非拒绝失败批次归零。

**验证：** 运行 `python -m pytest tests/test_agent_runner.py tests/test_tool_scheduler.py -q`；期望新熔断与全部既有 Agent/Scheduler 用例通过。

## T3：让内置 explore 在冻结只读范围内可用

**文件：** `src/mewcode/subagents/builtin/explore.md`、`tests/test_subagent_catalog.py`  
**依赖：** 无

**步骤：**
1. 将包内 explore 的权限模式改为 `allow`，不改角色工具、模型、轮次或正文。
2. 更新生产解析器资源测试，断言三个只读工具顺序及 allow 模式。
3. 断言角色目录/策略仍排除写工具和全局禁止工具。

**验证：** 运行 `python -m pytest tests/test_subagent_parser.py tests/test_subagent_catalog.py tests/test_subagent_policy.py -q`；期望资源解析和安全交集通过。

## T4：为子运行时启用拒绝上限

**文件：** `src/mewcode/subagents/runtime.py`、`tests/test_subagent_runtime.py`  
**依赖：** T2

**步骤：**
1. 子运行时创建 Runner 时固定配置拒绝上限 3；定义式与 Fork 共享行为。
2. 将新停止原因映射为 `failed` outcome，并提供明确、去敏的错误；保留累计 usage。
3. 用实际 SubagentRuntime 驱动三轮拒绝，断言只发生三次 Provider 请求且 Driver 正常关闭。

**验证：** 运行 `python -m pytest tests/test_subagent_runtime.py -q -k "denial or preserves or close"`；期望定义式/Fork 前缀与新失败映射全部通过。

## T5：建立可控总期限测试夹具

**文件：** `tests/test_subagent_tasks.py`  
**依赖：** 无

**步骤：**
1. 用可控 sleep/Event 构造 Driver 创建阻塞、Provider/事件阻塞、工具阻塞和快速完成场景。
2. 记录 Driver cancel/close 次数、Provider 启动次数、事件、通知、usage 和最终 snapshot。
3. 覆盖注册后已消耗部分期限、10 秒 detach 后继续原期限以及无需真实等待的 300 秒边界。

**验证：** 运行 `python -m pytest tests/test_subagent_tasks.py -q -k "execution_timeout"`；实现前期望超时用例稳定失败且无真实等待，实现后期望通过。

## T6：实现注册时刻总期限监督

**文件：** `src/mewcode/subagents/models.py`、`src/mewcode/subagents/__init__.py`、`src/mewcode/subagents/tasks.py`、`tests/test_subagent_tasks.py`  
**依赖：** T5

**步骤：**
1. 定义并导出 300 秒常量，为 TaskManager 增加可注入正数期限参数。
2. 把 Driver 创建和事件消费放入单一执行 Task；用注册单调时刻计算剩余时间并与可控期限 Task 竞速。
3. 期限获胜时调用 Driver cancel、取消并收敛执行 Task，再生成 `failed` 超时 outcome；不设置用户取消标记。
4. 执行获胜时取消期限 Task；所有分支在 finally 中关闭 Driver 并只提交一次终态。
5. 合并关闭阶段得到的 usage/Worktree 信息，但禁止其覆盖超时失败；保留当前 Worktree 生命周期行为。

**验证：** 运行 `python -m pytest tests/test_subagent_tasks.py tests/test_subagent_worktree.py -q`；期望期限、取消、保留、关闭及 Worktree outcome 全部通过。

## T7：验证完成、取消和期限竞态

**文件：** `tests/test_subagent_tasks.py`  
**依赖：** T6

**步骤：**
1. 同时释放完成与期限，断言已完成执行优先且仅一个 completed 终态。
2. 同时触发用户取消与期限，断言先获得终态闸门的路径唯一；用户先取消保持 cancelled，期限先到保持 failed。
3. 注入 Driver cancel/close 异常，断言任务仍收敛、错误有界、管理器和其他任务可继续使用。

**验证：** 运行 `python -m pytest tests/test_subagent_tasks.py -q -k "timeout_race or execution_timeout"`；期望无重复通知、事件或 pending asyncio task。

## T8：端到端验证 explore 开箱执行

**文件：** `tests/test_subagent_integration.py`  
**依赖：** T3、T4、T6

**步骤：**
1. 构造没有源码通配权限规则的工作区，通过生产角色目录、Coordinator、Runtime 和 TaskManager 启动内置 explore。
2. 让子模型依次执行 find_files、read_file、search_code 后自然完成，断言没有 ASK/非交互拒绝。
3. 同场景尝试写工具、越界路径和嵌套 agent，断言安全边界仍拒绝且拒绝熔断可终止重试。

**验证：** 运行 `python -m pytest tests/test_subagent_integration.py -q -k "explore_liveness"`；期望只读成功、安全边界和请求次数断言通过。

## T9：端到端验证后台总期限

**文件：** `tests/test_subagent_integration.py`  
**依赖：** T6、T7

**步骤：**
1. 启动定义式前台任务，在虚拟 10 秒原地 detach 后继续推进到注册后虚拟 300 秒。
2. 断言没有重启 Provider/消息/权限/usage，任务最终 failed，终端摘要与一次性通知各一条。
3. 对 Fork 后台重复期限路径，断言父缓存前缀不变，超时后本地查询仍显示累计 usage。

**验证：** 运行 `python -m pytest tests/test_subagent_integration.py -q -k "execution_timeout or detach_deadline"`；期望前后台、Fork 与通知链路全部通过。

## T10：运行定向回归并处理当前工作区兼容

**文件：** 全部受影响测试；当前 Worktree 阶段文件  
**依赖：** T1–T9

**步骤：**
1. 运行 Agent、权限、Hook、子运行时、任务、通知、Conversation、REPL 和 Worktree 定向测试。
2. 检查本阶段 diff，只修改计划列出的局部；不覆盖当前未提交的 Phase 13 文件内容。
3. 修复失败时保持已批准 3/300 常量和安全边界，不扩展角色格式或配置。

**验证：** 运行 `python -m pytest tests/test_agent_runner.py tests/test_tool_scheduler.py tests/test_subagent_permissions.py tests/test_subagent_policy.py tests/test_subagent_runtime.py tests/test_subagent_tasks.py tests/test_subagent_catalog.py tests/test_subagent_integration.py tests/test_subagent_worktree.py tests/test_conversation.py tests/test_repl.py -q`；期望全部通过。

## T11：执行全量回归与交付检查

**文件：** 本阶段修改文件、`docs/phase-14-subagent-liveness/checklist.md`  
**依赖：** T10

**步骤：**
1. 运行完整 pytest，记录通过、跳过、失败数和耗时。
2. 运行 `git diff --check`；核对 `git status --short`，明确区分本阶段修改与用户已有 Phase 13/缓存/Hook 改动。
3. 按 checklist 逐项记录拒绝次数、虚拟期限、终态、通知和 usage 证据。

**验证：** 运行 `python -m pytest -q` 和 `git diff --check`；期望完整测试通过且无空白错误。

## 执行顺序

```text
T1 -> T2 ─┐
          ├-> T4 ─────────┐
T3 ───────┘               │
T5 -> T6 -> T7 ───────────┼-> T8 -> T9 -> T10 -> T11
                          │
当前 Phase 13 兼容检查 ────┘
```
