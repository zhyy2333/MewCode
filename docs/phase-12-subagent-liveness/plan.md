# 子 Agent 活性保护 Plan

## 架构概览

修复分成三个相互补强但边界独立的部分：内置角色选择适合其冻结只读能力的权限模式；通用 Agent 循环提供默认关闭、仅由子运行时启用的连续拒绝熔断；任务管理器以注册时刻为基准，用可注入睡眠任务监督完整 Driver 创建与事件消费。现有工具过滤、非交互权限转换、10 秒前台转后台和 Worktree Driver 生命周期保持原有所有权关系。

## 核心数据结构与接口

### AgentRunConfig

新增可选的连续拒绝批次上限。默认值为关闭，从而不改变根 Agent；子 Agent 运行时固定传入 `3`。配置只接受正整数或关闭值。

### StopReason

新增通用的 `tool_denial_limit` 停止原因，用于区分轮次耗尽、未知工具耗尽和连续工具拒绝。Runner 的最终错误只描述安全的计数与原因，不包含完整工具参数。

### 拒绝批次判定

一个非空工具批次仅在每个结果都带有权限拒绝或 Hook 拒绝标记时计为“全拒绝”。权限标记覆盖硬安全、冻结子 Agent 策略、普通权限和非交互 ASK 转拒绝；Hook 使用既有独立标记。任一成功执行，或含有未知、参数错误、执行失败等其他结果，都会把连续拒绝计数归零。未知工具计数继续独立计算。

### SUBAGENT_EXECUTION_TIMEOUT_SECONDS

在子 Agent 产品限制常量中固定为 `300.0` 秒。`SubagentTaskManager` 接受默认使用该常量的正数构造参数，测试可注入极短期限及现有可控 `sleep`、单调时钟。

### Driver 执行监督

任务管理器为每个任务建立两个内部 Task：

- 单一执行 Task：创建 Driver、登记 Driver、转发预先到达的取消、从头到尾消费事件并返回 Driver outcome；同一异步生成器不会被多个 Task 交替推进。
- 期限 Task：按“固定总期限减去注册后已耗时”调用可注入 sleep。

管理器等待二者首次完成。执行先完成则取消期限 Task并沿用原结果；期限先完成则调用 Driver cancel、取消并收敛执行 Task，生成 `failed` 超时 outcome。关闭 Driver 后只合并截至超时可取得的 usage 与 Worktree 清理信息，不允许关闭阶段把超时状态覆盖成 `cancelled` 或 `completed`。

## 模块设计

### 内置探索角色

**职责：** 将包内 `explore` 的权限模式改为 `allow`。

**安全边界：** 角色仍只声明 `read_file`、`find_files`、`search_code`；Coordinator 继续与父工具视图、父安全等级、后台白名单和全局禁止名单取交集。路径硬检查和工具自身工作区解析不受权限模式影响。

### 通用 Agent Runner

**职责：** 在每个已执行工具批次后更新连续拒绝计数，并在配置上限命中时提交当前成对的 assistant/tool messages 后停止。

**兼容性：** 默认配置关闭此行为；根 Agent、PLAN、普通 Skill 和现有未知工具熔断不变。子运行时显式启用上限 3。

### 子 Agent Runtime

**职责：** 创建 Runner 时传入拒绝上限。将新的停止原因映射为现有 `failed` 子任务 outcome，并保留 Runner 给出的安全错误及 usage。

### 子 Agent TaskManager

**职责：** 从注册时刻监督 300 秒期限；在定义式/Fork、前台/后台和 Shared/Worktree Driver 上采用同一路径。超时不设置用户取消标记，确保终态保持 `failed`；显式用户取消仍保持 `cancelled`。

**竞态：** `_commit_terminal` 继续作为单终态闸门。自然完成与期限同时就绪时优先采用已经完成的执行结果；一旦期限路径获胜，后到的完成或取消不能覆盖超时 outcome。

### 通知与命令

不新增接口。现有终端事件、通知队列、`/tasks` 与 `/task` 读取统一 snapshot；超时和拒绝上限通过已有有界错误字段自然展示。

## 模块交互

```text
内置 explore(permission=allow)
  -> Coordinator 冻结只读工具/安全范围
  -> Runtime 创建 Runner(denial_limit=3)
  -> TaskManager 注册任务并记录 monotonic 起点
       ├─ execution Task -> Driver -> Runner -> Scheduler 结果标记
       │                              -> 连续全拒绝 3 次后停止
       └─ deadline Task  -> 可注入 sleep(300 - 已耗时)
                              -> cancel Driver/execution
                              -> failed timeout outcome
  -> 单终态提交 -> snapshot / terminal event / notification / local commands
```

## 文件组织

```text
src/mewcode/agent/events.py                 新增拒绝上限停止原因
src/mewcode/agent/runner.py                 配置、计数与熔断
src/mewcode/subagents/models.py             300 秒产品常量
src/mewcode/subagents/runtime.py            子运行时启用拒绝上限
src/mewcode/subagents/tasks.py              Driver/期限竞速与超时收敛
src/mewcode/subagents/builtin/explore.md     只读角色权限模式
src/mewcode/subagents/__init__.py            导出产品常量
tests/test_agent_runner.py                   通用关闭、全拒绝与重置
tests/test_subagent_runtime.py               子运行时启用及失败映射
tests/test_subagent_tasks.py                 期限、取消和终态竞态
tests/test_subagent_catalog.py               内置角色权限断言
tests/test_subagent_integration.py           开箱探索与端到端活性保护
docs/phase-14-subagent-liveness/             规格、计划、任务和验收记录
```

## 技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 内置探索权限 | 角色级 `allow` | 冻结工具全部只读，解决开箱不可用且不放宽其他角色或全局权限 |
| 熔断位置 | 通用 Runner 可选配置 | 能在下一次 Provider 请求前停止，同时保持通用层不反向依赖子系统 |
| 拒绝阈值 | 连续 3 个全拒绝批次 | 与未知工具保护一致，允许模型一次纠错但限制成本 |
| 总期限 | 固定 300 秒、从注册计时 | 对前后台一致，避免转后台重置；不修改角色格式 |
| 时间实现 | 可注入 sleep 的并发期限 Task | 单元测试无需真实等待，也覆盖 Driver 创建卡住的情况 |
| 超时终态 | `failed` 而非 `cancelled` | 区分系统活性保护与用户主动取消 |
| Worktree 兼容 | 保留超时失败，仅合并清理元数据 | 避免当前未提交 Worktree 生命周期改动覆盖超时语义 |
