# Phase 14B 隔离成员后端 Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 新建 | `src/mewcode/teams/backends.py` | 后端请求、平台优先级、能力探测和诊断。 |
| 新建 | `src/mewcode/teams/panes.py` | 终端适配器协议及 Windows Terminal/tmux 实现。 |
| 新建 | `src/mewcode/teams/control.py` | 本地 Lead 控制 broker 与严格控制协议。 |
| 新建 | `src/mewcode/teams/member_worker.py` | 隐藏成员工作模式、运行描述与结果记录。 |
| 新建 | `src/mewcode/teams/pane_host.py` | 隐藏窗格宿主、重连与子进程管理。 |
| 修改 | `src/mewcode/teams/models.py` | 后端、窗格绑定、健康视图和唤醒回执模型。 |
| 修改 | `src/mewcode/teams/codec.py` | 新状态及控制/结果记录的严格编解码。 |
| 修改 | `src/mewcode/teams/paths.py` | 窗格控制和单次运行文件的安全路径。 |
| 修改 | `src/mewcode/teams/runtime.py` | 可由进程内和成员工作模式复用的执行组装。 |
| 修改 | `src/mewcode/teams/scheduler.py` | 运行时后端路由、启动回执、取消和结果收敛。 |
| 修改 | `src/mewcode/teams/mailbox.py` | 邮件持久投递与成员唤醒的结果分离。 |
| 修改 | `src/mewcode/teams/roster.py` | `auto` 解析、窗格 provisioning、成员视图与移除回收。 |
| 修改 | `src/mewcode/teams/coordinator.py` | broker 生命周期和挂载恢复。 |
| 修改 | `src/mewcode/teams/tools.py` | 默认后端和成员列表编码。 |
| 修改 | `src/mewcode/teams/__init__.py` | 新公开组件导出。 |
| 修改 | `src/mewcode/cli.py` | 依赖装配、隐藏成员宿主及工作模式入口。 |
| 新建 | `tests/teams/test_backends.py` | 后端优先级、显式错误和环境探测。 |
| 新建 | `tests/teams/test_panes.py` | 固定 argv、终端适配器和窗格 provisioning。 |
| 新建 | `tests/teams/test_control.py` | broker、宿主登记、控制代际和断线。 |
| 新建 | `tests/teams/test_member_worker.py` | 工作模式、结果文件与 14A 运行时复用。 |
| 新建 | `tests/teams/test_pane_host.py` | 宿主单运行、取消、重连和保留窗格语义。 |
| 修改 | `tests/teams/test_models.py`、`test_paths_codec.py`、`helpers.py` | 新模型、格式兼容和测试工厂。 |
| 修改 | `tests/teams/test_roster.py`、`test_scheduler.py`、`test_runtime.py`、`test_mailbox_protocols.py`、`test_integration.py`、`test_tools.py` | 14A 服务的隔离后端集成与回归。 |
| 修改 | `tests/test_team_cli_integration.py` | CLI 装配和隐藏运行模式回归。 |

## T1: 扩展团队后端和运行视图领域模型

**文件：** `src/mewcode/teams/models.py`、`tests/teams/test_models.py`、`tests/teams/helpers.py`

**依赖：** 无

**步骤：**

1. 将持久成员后端扩展为 `in_process`、`windows_terminal` 与 `tmux`，新增仅用于请求的 `auto` 后端选择模型。
2. 添加版本化窗格绑定、窗格健康状态、成员运行视图和结构化唤醒回执，并复用既有标识、时间和有界诊断验证。
3. 在 `TeamMemberRecord` 中添加可选窗格绑定，保持现有 14A 构造方式与进程内成员语义兼容。
4. 更新测试工厂和枚举/不变量测试，覆盖合法与非法绑定、诊断截断和旧字段缺失。

**验证：** 运行 `python -m pytest tests/teams/test_models.py`，期望所有模型、枚举和兼容断言通过。

## T2: 完成严格持久格式和受控路径

**文件：** `src/mewcode/teams/codec.py`、`src/mewcode/teams/paths.py`、`tests/teams/test_paths_codec.py`

**依赖：** T1

**步骤：**

1. 为窗格绑定、控制描述和单次成员运行结果增加独立版本化编码/解码，保持 JSON 未知字段、重复字段、截断和未来版本的拒绝策略。
2. 为成员控制描述、窗格绑定与运行结果建立成员目录内的安全路径，并继续应用名称、包含性和链接/重解析点检查。
3. 验证缺失的可选绑定能读取 14A 状态，而新格式损坏、替换或指向团队外路径时保留现场并拒绝写入。

**验证：** 运行 `python -m pytest tests/teams/test_paths_codec.py`，期望旧状态 round-trip、新记录 round-trip 与全部畸形输入用例通过。

## T3: 实现后端解析与能力探测

**文件：** `src/mewcode/teams/backends.py`、`tests/teams/test_backends.py`

**依赖：** T1

**步骤：**

1. 定义可替换的平台、环境与可执行文件探测接口，以及统一的能力/诊断结果。
2. 实现 `auto`：Windows 依次尝试 Windows Terminal 与进程内；macOS/Linux 依次尝试 tmux 与进程内。
3. 实现显式后端的严格探测：非匹配平台、缺少当前终端宿主、不可执行或权限不足均返回稳定错误，绝不继续尝试其它后端。
4. 使用 fake 平台与环境测试所有优先级和明确失败路径，不依赖本机终端安装状态。

**验证：** 运行 `python -m pytest tests/teams/test_backends.py`，期望自动优先级、显式无降级和诊断断言全部通过。

## T4: 实现终端窗格适配器

**文件：** `src/mewcode/teams/panes.py`、`tests/teams/test_panes.py`

**依赖：** T2、T3

**步骤：**

1. 定义 `TerminalPaneAdapter`、固定 `PaneHostLaunch` 和可替换 argv 进程执行器；禁止 shell 字符串拼接。
2. 实现 Windows Terminal 适配器：仅在可识别的当前 Windows Terminal 宿主中，以固定 `wt --window ... split-pane` argv 启动宿主。
3. 实现 tmux 适配器：仅在当前 tmux 会话中以固定 argv 创建窗格并保存返回的安全 pane 句柄。
4. 实现预检、未发布窗格回收和命令成功但宿主未登记时的失败表示。

**验证：** 运行 `python -m pytest tests/teams/test_panes.py`，期望各适配器的 argv、宿主条件、句柄验证和回滚断言通过。

## T5: 定义本地控制协议与严格消息编解码

**文件：** `src/mewcode/teams/control.py`、`tests/teams/test_control.py`

**依赖：** T1、T2

**步骤：**

1. 定义登记、心跳、运行、取消、进度、结果和关闭的固定消息 union，并验证团队、成员、宿主、控制代际、运行 ID 与成员代际。
2. 为控制描述定义受限本地端点与不出现在 argv 的认证材料；严格限制大小、未知字段与诊断文本。
3. 编写消息回放、重复、字段遗漏、越界 ID 与过期代际测试。

**验证：** 运行 `python -m pytest tests/teams/test_control.py -k "protocol or message"`，期望畸形和陈旧控制消息均被拒绝。

## T6: 实现 Lead 本地控制 broker

**文件：** `src/mewcode/teams/control.py`、`tests/teams/test_control.py`

**依赖：** T5

**步骤：**

1. 实现 broker 的打开、关闭、候选宿主授权、宿主登记、单成员连接归属与健康视图。
2. 将控制代际与 Team Lead 生命周期绑定，使新 Lead 拒绝旧宿主连接和旧运行结果。
3. 实现可替换的连接、时钟和有限重连策略；控制面断线需通知运行时取消在途工作，但不进行忙轮询。
4. 覆盖重复宿主、失联后重连、过期结果、Lead 重启和关闭顺序。

**验证：** 运行 `python -m pytest tests/teams/test_control.py`，期望 broker 生命周期、单连接归属和断线收敛测试通过。

## T7: 抽取可复用成员执行组装

**文件：** `src/mewcode/teams/runtime.py`、`tests/teams/test_runtime.py`

**依赖：** T1、T2

**步骤：**

1. 从当前 `TeamMemberRuntimeFactory` 中抽取共享的成员身份验证、固定 Worktree 进入、会话打开、恢复 prompt 和 AgentRun 组装路径。
2. 保持现有进程内 `TeamMemberRuntime` 的容量、清理和结果映射行为不变。
3. 为独立成员工作模式暴露不拥有 Lead 容量租约的执行入口，同时保留会话锁、Worktree suspend 和安全边界。
4. 扩展现有 runtime 测试，证明进程内路径仍按 14A 运行，独立入口复用同一恢复上下文。

**验证：** 运行 `python -m pytest tests/teams/test_runtime.py`，期望原有测试和新增共享执行测试均通过。

## T8: 实现隐藏成员工作模式与结果记录

**文件：** `src/mewcode/teams/member_worker.py`、`tests/teams/test_member_worker.py`

**依赖：** T2、T5、T7

**步骤：**

1. 读取严格的运行描述，验证当前团队、成员、运行 ID、运行代际和 RUNNING 状态后才执行成员运行。
2. 调用共享执行组装完成一个完整 MewCode 成员运行，继续使用冻结角色、审批、固定 Worktree、会话和邮箱入站源。
3. 将最终结果通过原子、版本化结果文件交给宿主；错误和取消必须映射为既有安全结果而不直接改写团队状态。
4. 拒绝普通 REPL 输入、伪造描述、过期运行和未授权路径，且测试中不使用真实模型调用。

**验证：** 运行 `python -m pytest tests/teams/test_member_worker.py`，期望会话恢复、结果原子性、取消、身份校验和无 REPL 用例通过。

## T9: 实现保留窗格的隐藏宿主模式

**文件：** `src/mewcode/teams/pane_host.py`、`tests/teams/test_pane_host.py`

**依赖：** T5、T6、T8

**步骤：**

1. 实现宿主登记、单个工作进程启动、进度/结果转发和安全终端摘要输出。
2. 工作进程自然结束后保持宿主与窗格可用；新的运行请求复用同一宿主，禁止重叠运行。
3. 控制面断线或取消时停止在途工作；使用注入的等待/子进程接口实现有界重连且不忙轮询。
4. 覆盖重复运行、工作进程异常、宿主重连、控制断线和窗格保留场景。

**验证：** 运行 `python -m pytest tests/teams/test_pane_host.py`，期望一个宿主连续执行两轮、每轮至多一个工作进程且断线收敛测试通过。

## T10: 实现终端成员运行时与容量归属

**文件：** `src/mewcode/teams/runtime.py`、`src/mewcode/teams/control.py`、`tests/teams/test_runtime.py`、`tests/teams/test_control.py`

**依赖：** T6、T8、T9

**步骤：**

1. 实现 `TerminalMemberRuntime`，使其通过 broker 请求窗格宿主启动工作进程、转发进度并等待已验证结果。
2. 将 Lead 获取的 `AgentCapacityLease` 保持到终态结果或取消后的清理完成；空闲宿主不获取容量。
3. 将窗格缺失后的替代创建、工作进程异常、宿主断线、显式停止和陈旧结果映射到既有成员结果类型。
4. 使用 fake broker、适配器和容量池证明容量不会重复获取或泄漏。

**验证：** 运行 `python -m pytest tests/teams/test_runtime.py tests/teams/test_control.py`，期望终端运行生命周期、取消与容量回收断言通过。

## T11: 扩展调度器进行后端路由和启动回执

**文件：** `src/mewcode/teams/scheduler.py`、`tests/teams/test_scheduler.py`

**依赖：** T10

**步骤：**

1. 将运行时工厂改为按成员的已解析后端创建进程内或终端运行时，且继续由现有调度器提交状态和最终通知。
2. 在唤醒路径公开 `running`、`queued`、`failed`、`not_applicable` 回执；容量满时保持持久 FIFO 而不等待后端。
3. 后端不可用、窗格创建/登记失败或过期运行结果时，将已投递成员收敛到 FAILED，并保留稳定诊断。
4. 维持同一成员的队列合并、恢复、停止、关闭与中断恢复行为，并添加后端混合竞争测试。

**验证：** 运行 `python -m pytest tests/teams/test_scheduler.py`，期望 FIFO、单运行、失败回执、停止竞争和恢复断言通过。

## T12: 分离邮箱持久投递与唤醒结果

**文件：** `src/mewcode/teams/mailbox.py`、`tests/teams/test_mailbox_protocols.py`

**依赖：** T11

**步骤：**

1. 将 outbox 的消息追加和已投递标记与唤醒尝试分开，确保唤醒异常不会让已完成的邮箱投递被重复写入。
2. 将结构化唤醒回执并入点对点和广播结果，使调用方可区分已投递、排队和已投递但未启动。
3. 保持现有收件人锁、协议方向、广播部分成功和幂等消息 ID 语义。
4. 增加终端唤醒失败后的邮件保留、广播混合结果及重复 flush 测试。

**验证：** 运行 `python -m pytest tests/teams/test_mailbox_protocols.py`，期望邮件不丢不重且唤醒诊断可观察。

## T13: 为花名册接入 auto、窗格 provisioning 和运行视图

**文件：** `src/mewcode/teams/roster.py`、`tests/teams/test_roster.py`

**依赖：** T3、T4、T6、T11

**步骤：**

1. 将新增成员的默认请求设为 `auto`，对显式后端执行严格预检并持久化实际后端。
2. 对终端成员将候选宿主与 Worktree、会话、邮箱纳入 provisioning journal，只有登记成功后发布花名册和名称注册。
3. 在失败路径回收未发布的窗格宿主，且不留下可投递成员；对无法回收的资源保留 journal 诊断供恢复。
4. 成员列表返回运行视图；停止、恢复、刷新和移除沿用 14A 门禁，并在移除时回收终端宿主。

**验证：** 运行 `python -m pytest tests/teams/test_roster.py`，期望 auto/显式选择、全成全败、窗格缺失恢复、列表健康和安全移除断言通过。

## T14: 将 broker 纳入协调器生命周期

**文件：** `src/mewcode/teams/coordinator.py`、`tests/teams/test_integration.py`

**依赖：** T6、T11、T13

**步骤：**

1. 在挂载并取得 Lead 租约后启动 broker，在服务创建与队列恢复前提供当前控制代际。
2. 在关闭、租约丢失、卸载和异常路径中先停止调度与在途工作，再关闭 broker、刷新 outbox 和释放 Lead 租约。
3. 挂载后将遗留 RUNNING 成员按 14A 规则收敛为 INTERRUPTED；空闲宿主仅重新登记，不会自动启动成员。
4. 覆盖关闭顺序、控制面重启、旧宿主拒绝和其它成员不受影响。

**验证：** 运行 `python -m pytest tests/teams/test_integration.py`，期望创建、附加、关闭、重启与恢复顺序全部通过。

## T15: 更新团队工具的默认与可观察输出

**文件：** `src/mewcode/teams/tools.py`、`tests/teams/test_tools.py`

**依赖：** T12、T13

**步骤：**

1. 保持固定工具 schema，但使成员新增动作的 `backend` 可选并默认 `auto`。
2. 编码成员列表运行视图、实际后端、窗格健康及有界诊断，不泄露控制描述、密钥、会话内容或工具参数。
3. 编码邮件与任务的唤醒回执，使已投递但未启动能被 Lead 明确观察。
4. 保持 PLAN 门禁、成员工具隔离和既有动作参数拒绝规则。

**验证：** 运行 `python -m pytest tests/teams/test_tools.py`，期望 schema 稳定、默认选择、诊断脱敏与权限门禁测试通过。

## T16: 装配 CLI 与隐藏运行模式

**文件：** `src/mewcode/cli.py`、`src/mewcode/teams/__init__.py`、`tests/test_team_cli_integration.py`

**依赖：** T7、T9、T10、T14、T15

**步骤：**

1. 将成员运行时装配提取为进程内 Lead 与独立成员工作模式均可复用的构造路径。
2. 注册隐藏宿主和成员工作命令行模式；它们与普通 REPL 会话模式互斥，且不会创建主会话、Lead 租约或人工交互入口。
3. 为当前 Lead 装配后端 resolver、终端适配器、broker、运行时路由、花名册和邮箱服务。
4. 更新公开导出；验证普通 CLI、进程内团队和隐藏模式互不改变对方的启动行为。

**验证：** 运行 `python -m pytest tests/test_team_cli_integration.py`，期望现有 CLI 冒烟和新增隐藏模式/依赖装配测试通过。

## T17: 完成隔离后端端到端与崩溃/并发测试

**文件：** `tests/teams/test_backends.py`、`tests/teams/test_panes.py`、`tests/teams/test_control.py`、`tests/teams/test_member_worker.py`、`tests/teams/test_pane_host.py`、现有团队测试

**依赖：** T12、T13、T14、T15、T16

**步骤：**

1. 使用 Windows Terminal 与 tmux fake 分别运行“创建 → 邮件/任务 → 独立成员运行 → IDLE → 同窗格恢复”的完整流程。
2. 验证窗格消失后替代创建、工作进程异常、控制面断线、Lead 重启、陈旧结果和后端不可用的安全终态。
3. 并发触发邮件、广播、任务指派、显式恢复、停止和容量释放，验证每位成员最多一个运行且邮箱不丢不重。
4. 对 14A 持久状态、进程内成员、审批、普通子 Agent容量与未使用团队回归进行并排验证。

**验证：** 运行 `python -m pytest tests/teams tests/test_agent_capacity.py tests/test_team_cli_integration.py`，期望专项与受影响集成测试全部通过且无 skip/xfail 增量。

## T18: 执行全量验证并记录证据

**文件：** `docs/phase-14b-isolated-member-backends/checklist.md`（获批后创建并在验收阶段填写）

**依赖：** T17

**步骤：**

1. 运行编译、专项、受影响回归和完整测试套件。
2. 记录每项命令、退出码、通过数量、耗时和任何平台限制；只对实际验证通过的 checklist 项打勾。
3. 审查 git diff，确认没有删除测试、降低断言或以无理由 skip/xfail 替代修复。

**验证：** 运行 `python -m compileall -q src/mewcode`、`python -m pytest tests/teams tests/test_agent_capacity.py tests/test_team_cli_integration.py`、`python -m pytest`，期望全部命令退出码为 0。

## 执行顺序

```text
T1 → T2 → T4 ─┐
 │    └→ T5 → T6 ─┐
 └→ T3 ───────────┼→ T13 ─┐
T2 → T7 → T8 → T9 → T10 → T11 → T12 ─┼→ T15 ─┐
                                     T14 ────────┼→ T16 → T17 → T18
                                                  └───────────────┘
```

T3、T5 与 T7 可在其依赖完成后并行；T13、T14 在各自依赖完成后可并行。其余任务按上图顺序执行，以保持持久格式、控制协议、运行时和产品装配之间的可验证边界。
