# 斜杠命令注册与分发系统 Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 修改 | `pyproject.toml` | 增加 `prompt-toolkit` 运行依赖 |
| 修改 | `README.md` | 记录命令、模式、补全和兼容语义 |
| 新建 | `src/mewcode/commands/__init__.py` | 导出命令系统公共接口 |
| 新建 | `src/mewcode/commands/core.py` | 命令模型、输入解析、错误和不可变注册表 |
| 新建 | `src/mewcode/commands/contracts.py` | 命令 UI、运行状态协议和共享交互状态 |
| 新建 | `src/mewcode/commands/dispatcher.py` | 命令解析命中后的异步分发和错误收敛 |
| 新建 | `src/mewcode/commands/builtin.py` | 内置命令、固定审查提示词和输出格式化 |
| 新建 | `src/mewcode/terminal.py` | `prompt_toolkit` 终端、补全、Tab 和底栏 |
| 修改 | `src/mewcode/repl.py` | 单异步生命周期、输入分流、命令协议适配 |
| 修改 | `src/mewcode/cli.py` | Provider 跟踪包装和命令终端装配 |
| 修改 | `src/mewcode/conversation.py` | 三种消息策略和安全会话状态快照 |
| 新建 | `src/mewcode/providers/usage.py` | 会话 Token 账本和 Provider 装饰器 |
| 修改 | `src/mewcode/providers/__init__.py` | 导出用量跟踪类型 |
| 修改 | `src/mewcode/context/models.py` | 定义上下文运行状态快照 |
| 修改 | `src/mewcode/context/manager.py` | 提供无副作用状态查询 |
| 修改 | `src/mewcode/context/__init__.py` | 导出上下文状态快照 |
| 修改 | `src/mewcode/continuity/memory_models.py` | 定义记忆更新状态和安全摘要 |
| 修改 | `src/mewcode/continuity/memory_store.py` | 只读暴露实际记忆配置 |
| 修改 | `src/mewcode/continuity/memory_manager.py` | 跟踪更新状态并提供内存快照 |
| 修改 | `src/mewcode/continuity/__init__.py` | 导出记忆运行状态类型 |
| 新建 | `tests/test_command_core.py` | 解析、冲突、查找、排序和候选测试 |
| 新建 | `tests/test_command_dispatcher.py` | 分发、未知命令、用法和错误隔离测试 |
| 新建 | `tests/test_builtin_commands.py` | 内置元数据、处理路径和格式测试 |
| 新建 | `tests/test_terminal.py` | 真实补全键序列、底栏、清屏和 EOF 测试 |
| 新建 | `tests/test_usage_tracking.py` | Token 聚合、委托、异常和取消测试 |
| 修改 | `tests/test_conversation.py` | 三种 ConversationMode 和旧计划兼容测试 |
| 修改 | `tests/test_context_manager.py` | 上下文状态快照测试 |
| 修改 | `tests/test_memory_manager.py` | 记忆状态转换和摘要测试 |
| 修改 | `tests/test_repl.py` | 脚本终端、异步分流、权限与生命周期测试 |
| 修改 | `tests/test_continuity_integration.py` | 命令、恢复、记忆、Token 端到端测试 |

## T1：登记终端运行依赖

**文件：** `pyproject.toml`  
**依赖：** 无

**步骤：**

1. 在项目运行依赖中加入 `prompt-toolkit>=3.0,<4`。
2. 保持现有 Provider、HTTP 和 YAML 依赖不变。

**验证：** 运行 `python -c "import tomllib, pathlib; d=tomllib.loads(pathlib.Path('pyproject.toml').read_text()); assert any(x.startswith('prompt-toolkit') for x in d['project']['dependencies'])"`，期望命令成功退出。

## T2：建立命令模型和输入解析器

**文件：** `src/mewcode/commands/core.py`、`tests/test_command_core.py`  
**依赖：** 无

**步骤：**

1. 定义命令类型、输入类型、交互模式、解析结果、命令定义和三类命令异常。
2. 实现首尾清理、空输入、普通消息和按第一个 ASCII 空格拆分的斜杠命令解析。
3. 覆盖参数内部大小写与空白保真、只有斜杠和 Tab 不作为参数分隔符的边界测试。

**验证：** 运行 `python -m pytest tests/test_command_core.py -k parse -q`，期望解析测试全部通过。

## T3：实现注册校验和冲突失败

**文件：** `src/mewcode/commands/core.py`、`tests/test_command_core.py`  
**依赖：** T2

**步骤：**

1. 实现批量构造的只读标识索引。
2. 拒绝空名称、斜杠和任意空白字符。
3. 使用 `casefold()` 检查名称-名称、名称-别名、别名-别名冲突。
4. 让冲突异常只包含安全的冲突标识。

**验证：** 运行 `python -m pytest tests/test_command_core.py -k 'invalid or conflict' -q`，期望完整冲突矩阵通过。

## T4：实现注册表公开查询和补全候选

**文件：** `src/mewcode/commands/core.py`、`tests/test_command_core.py`  
**依赖：** T3

**步骤：**

1. 实现大小写无关的规范名称与别名查找。
2. 实现按规范名称稳定排序的公开定义查询。
3. 实现带斜杠、大小写无关、稳定排序的公开名称与别名补全候选。
4. 保证隐藏命令及其别名仍可解析但永不公开。

**验证：** 运行 `python -m pytest tests/test_command_core.py -q`，期望命令核心测试全部通过。

## T5：实现会话级 Token 账本

**文件：** `src/mewcode/providers/usage.py`、`tests/test_usage_tracking.py`  
**依赖：** 无

**步骤：**

1. 定义 `UsageSnapshot` 和 `UsageLedger`。
2. 累计请求数、未报告请求数和 `TokenUsage` 各字段。
3. 保证任一字段遇到未知值后在后续快照中继续为 `None`。

**验证：** 运行 `python -m pytest tests/test_usage_tracking.py -k ledger -q`，期望已知、部分未知和完全未知累计测试通过。

## T6：实现 Provider 正常流跟踪与委托

**文件：** `src/mewcode/providers/usage.py`、`tests/test_usage_tracking.py`  
**依赖：** T5

**步骤：**

1. 实现 `UsageTrackingProvider.stream_reply()`，原样转发所有事件并保存最后一个 usage。
2. 在模型流正常结束时只登记一次调用。
3. 原样委托助手消息和工具结果消息转换方法。

**验证：** 运行 `python -m pytest tests/test_usage_tracking.py -k 'forward or delegate or success' -q`，期望事件序列不变且账本只增加一次。

## T7：覆盖 Provider 无用量、异常和取消

**文件：** `src/mewcode/providers/usage.py`、`tests/test_usage_tracking.py`、`src/mewcode/providers/__init__.py`  
**依赖：** T6

**步骤：**

1. 在无 usage、Provider 异常和取消路径的流关闭处登记未报告调用。
2. 保证已收到 usage 后再失败或取消时不会重复登记。
3. 从 Provider 包导出跟踪类型。

**验证：** 运行 `python -m pytest tests/test_usage_tracking.py -q`，期望成功、失败、无用量和取消测试全部通过。

## T8：增加上下文运行状态快照

**文件：** `src/mewcode/context/models.py`、`src/mewcode/context/manager.py`、`src/mewcode/context/__init__.py`、`tests/test_context_manager.py`  
**依赖：** 无

**步骤：**

1. 定义 `ContextRuntimeStatus`。
2. 从现有熔断器状态实现无副作用 `status()`。
3. 覆盖初始、连续失败和恢复后的快照。

**验证：** 运行 `python -m pytest tests/test_context_manager.py -k status -q`，期望状态查询不触发 Provider 或压缩且数值正确。

## T9：定义记忆运行状态并暴露配置

**文件：** `src/mewcode/continuity/memory_models.py`、`src/mewcode/continuity/memory_store.py`、`src/mewcode/continuity/__init__.py`、`tests/test_memory_manager.py`  
**依赖：** 无

**步骤：**

1. 定义五态 `MemoryUpdateState` 和 `MemoryRuntimeStatus`。
2. 为 MemoryStore 增加只读配置属性，返回构造时的实际配置。
3. 导出新增类型并验证默认和自定义容量配置。

**验证：** 运行 `python -m pytest tests/test_memory_manager.py -k 'config or runtime_model' -q`，期望配置和模型测试通过。

## T10：实现记忆初始状态与安全快照

**文件：** `src/mewcode/continuity/memory_manager.py`、`tests/test_memory_manager.py`  
**依赖：** T9

**步骤：**

1. 在可写存储上初始化为 `IDLE`，不可写时初始化为 `DISABLED`。
2. 用已加载 catalog 统计项目级与用户级条目。
3. 用当前 PromptView 与 MemoryConfig 返回索引使用量和限制。
4. 保证 `status()` 不等待 pending、不读取笔记正文、不重新加载索引。

**验证：** 运行 `python -m pytest tests/test_memory_manager.py -k 'status or disabled' -q`，期望安全摘要与无等待测试通过。

## T11：实现记忆更新状态转换

**文件：** `src/mewcode/continuity/memory_manager.py`、`tests/test_memory_manager.py`  
**依赖：** T10

**步骤：**

1. 在 `schedule()` 时切换为 `RUNNING`。
2. 成功更新或成功无操作后切换为 `SUCCEEDED`。
3. 任一步失败时切换为 `FAILED`，同时保留现有诊断与旧索引。
4. 为 NullMemoryManager 返回零容量、禁用状态快照。

**验证：** 运行 `python -m pytest tests/test_memory_manager.py -q`，期望现有记忆测试和新增状态机测试全部通过。

## T12：增加 Conversation 策略与会话快照模型

**文件：** `src/mewcode/conversation.py`、`tests/test_conversation.py`  
**依赖：** 无

**步骤：**

1. 定义 `ConversationMode` 和 `ConversationStatus`。
2. 让 Conversation 保存新建或恢复标记。
3. 用现有安全标题函数、消息数量和活动操作生成动态状态快照。
4. 验证状态输出不包含消息正文或工具结果。

**验证：** 运行 `python -m pytest tests/test_conversation.py -k status -q`，期望新建、恢复、标题和忙闲测试通过。

## T13：统一默认和单次只读消息入口

**文件：** `src/mewcode/conversation.py`、`tests/test_conversation.py`  
**依赖：** T12

**步骤：**

1. 实现 `send(user_text, DEFAULT)` 对应直接提示和完整工具集。
2. 实现 `send(user_text, READ_ONLY)` 对应直接提示和只读工具集。
3. 复用现有预检、历史提交、取消和记忆调度逻辑。

**验证：** 运行 `python -m pytest tests/test_conversation.py -k 'default_mode or read_only_mode' -q`，期望 Provider 请求模式和工具集合符合映射。

## T14：接入持续计划模式并停止旧执行路由

**文件：** `src/mewcode/conversation.py`、`tests/test_conversation.py`  
**依赖：** T13

**步骤：**

1. 实现 `send(user_text, PLAN)` 对应现有计划提示和只读工具集。
2. 移除 REPL 所需的运行期 PendingPlan 创建和自动执行入口。
3. 保持 SessionState 中旧 StoredPlan 可被构造但被 Conversation 忽略，且不重写会话文件。
4. 更新旧 Plan/Execute 测试为三种 ConversationMode 测试。

**验证：** 运行 `python -m pytest tests/test_conversation.py tests/test_plan_mode.py tests/test_session_integration.py -q`，期望新路由与旧会话解码兼容测试通过。

## T15：定义命令控制协议和共享交互状态

**文件：** `src/mewcode/commands/contracts.py`、`tests/test_command_dispatcher.py`  
**依赖：** T4、T7、T8、T11、T14

**步骤：**

1. 定义 `InteractionState`，默认模式为 `DEFAULT`，退出标记为假。
2. 定义 `CommandUI`、`CommandRuntime` 和不可变 `CommandContext`。
3. 用结构化 fake 验证协议所需能力不包含具体终端对象。

**验证：** 运行 `python -m pytest tests/test_command_dispatcher.py -k contracts -q`，期望 fake 可满足协议且初始状态正确。

## T16：实现命令分发基础路径

**文件：** `src/mewcode/commands/dispatcher.py`、`tests/test_command_dispatcher.py`  
**依赖：** T15

**步骤：**

1. 让分发器只接受命令类型 ParsedInput。
2. 通过注册表解析规范名称和别名并 await 处理函数。
3. 未命中时输出未知命令与 `/help` 引导。
4. 验证未知命令和别名不会调用 AI 发送能力。

**验证：** 运行 `python -m pytest tests/test_command_dispatcher.py -k 'dispatch or unknown or alias' -q`，期望基础分发测试通过。

## T17：收敛命令用法和执行错误

**文件：** `src/mewcode/commands/dispatcher.py`、`tests/test_command_dispatcher.py`  
**依赖：** T16

**步骤：**

1. 将 `CommandUsageError` 转换为登记的 `Usage:` 输出。
2. 显示 `CommandExecutionError` 的安全消息。
3. 把未预期异常转换为不含异常正文和堆栈的通用失败消息。
4. 验证失败后下一条命令仍可执行。

**验证：** 运行 `python -m pytest tests/test_command_dispatcher.py -q`，期望错误隔离与隐私测试全部通过。

## T18：建立命令包公共导出

**文件：** `src/mewcode/commands/__init__.py`  
**依赖：** T17

**步骤：**

1. 导出核心模型、注册表、解析器、协议、状态、分发器和命令错误。
2. 避免从公共入口导入 `prompt_toolkit` 或触发终端构造。

**验证：** 运行 `python -c "import mewcode.commands as c; assert c.CommandRegistry and c.CommandDispatcher and c.InteractionState"`，期望无终端初始化副作用地成功导入。

## T19：登记全部内置命令元数据

**文件：** `src/mewcode/commands/builtin.py`、`tests/test_builtin_commands.py`  
**依赖：** T18

**步骤：**

1. 建立 fake UI/Runtime 测试夹具。
2. 创建十个公开定义和一个隐藏 exit 定义。
3. 只登记 `permissions` 与 `quit` 两个别名，并标注正确类型、用法和参数提示。

**验证：** 运行 `python -m pytest tests/test_builtin_commands.py -k metadata -q`，期望公开数量、隐藏命令、别名和类型精确匹配 Plan 表格。

## T20：实现注册表驱动帮助

**文件：** `src/mewcode/commands/builtin.py`、`tests/test_builtin_commands.py`  
**依赖：** T19

**步骤：**

1. 实现稳定排序的公开命令列表格式化。
2. 实现单命令详情，支持带或不带 `/` 的公开名称和别名。
3. 隐藏命令详情按未知命令处理。
4. 输出描述、用法、参数提示和别名，不维护第二份清单。

**验证：** 运行 `python -m pytest tests/test_builtin_commands.py -k help -q`，期望帮助列表和详情测试通过。

## T21：实现清屏与模式切换命令

**文件：** `src/mewcode/commands/builtin.py`、`tests/test_builtin_commands.py`  
**依赖：** T19

**步骤：**

1. `/clear` 只调用清屏和状态刷新。
2. `/plan` 设置 `PLAN` 并刷新状态。
3. `/do` 设置 `DEFAULT` 并刷新状态。
4. 拒绝全部额外参数，验证不发送用户消息、不修改领域状态。

**验证：** 运行 `python -m pytest tests/test_builtin_commands.py -k 'clear or plan or do' -q`，期望界面调用轨迹精确匹配。

## T22：实现会话与记忆摘要命令

**文件：** `src/mewcode/commands/builtin.py`、`tests/test_builtin_commands.py`  
**依赖：** T19

**步骤：**

1. 实现稳定的会话 ID、状态、消息数、忙闲和安全标题格式。
2. 实现两级记忆条数、更新状态和索引容量格式。
3. 拒绝参数并测试正文、工具结果和记忆内容不会出现在输出。

**验证：** 运行 `python -m pytest tests/test_builtin_commands.py -k 'session or memory' -q`，期望摘要与隐私测试通过。

## T23：实现权限与核心状态命令

**文件：** `src/mewcode/commands/builtin.py`、`tests/test_builtin_commands.py`  
**依赖：** T19

**步骤：**

1. `/permission` 无参数时查询，单个合法参数时大小写无关切换现有三档模式。
2. 让 `/permissions` 通过同一处理函数执行。
3. 格式化 `/status` 的模式、会话、权限、Token、上下文和记忆行。
4. 将未知 Token 显示为 `n/a`，输出后刷新状态栏。

**验证：** 运行 `python -m pytest tests/test_builtin_commands.py -k 'permission or status' -q`，期望三档权限、别名、Token 缺失和核心摘要测试通过。

## T24：实现压缩与固定审查命令

**文件：** `src/mewcode/commands/builtin.py`、`tests/test_builtin_commands.py`  
**依赖：** T19

**步骤：**

1. 保存批准的固定 `REVIEW_PROMPT` 常量。
2. `/compact` 只 await Runtime 的手动压缩能力。
3. `/review` 只调用 `send_user_message(REVIEW_PROMPT, read_only=True)`。
4. 拒绝参数并验证当前持续模式不会变化。

**验证：** 运行 `python -m pytest tests/test_builtin_commands.py -k 'compact or review' -q`，期望调用次数、固定文本和单次只读标记正确。

## T25：实现隐藏退出并审计所有参数规则

**文件：** `src/mewcode/commands/builtin.py`、`tests/test_builtin_commands.py`、`src/mewcode/commands/__init__.py`  
**依赖：** T20、T21、T22、T23、T24

**步骤：**

1. `/exit` 和 `/quit` 只设置共享退出请求。
2. 确认两者可解析但不出现在帮助和候选中。
3. 对所有无参数命令做参数拒绝参数化测试。
4. 导出内置注册表工厂和固定提示词。

**验证：** 运行 `python -m pytest tests/test_builtin_commands.py -q`，期望全部内置命令测试通过。

## T26：实现终端协议和注册表补全器

**文件：** `src/mewcode/terminal.py`、`tests/test_terminal.py`  
**依赖：** T1、T4、T15

**步骤：**

1. 定义 `TerminalSession` 协议。
2. 实现从 Document 光标位置提取命令前缀的 `CommandCompleter`。
3. 只在斜杠开头且光标仍在首个空格前提供候选。
4. 用注册表候选验证大小写、别名、隐藏过滤和参数区禁用。

**验证：** 运行 `python -m pytest tests/test_terminal.py -k completer -q`，期望补全器单元测试通过。

## T27：实现 prompt_toolkit 终端与底栏

**文件：** `src/mewcode/terminal.py`、`tests/test_terminal.py`  
**依赖：** T26

**步骤：**

1. 使用异步 PromptSession、DummyHistory、补全器和共享状态构造生产终端。
2. 实现普通写入、错误写入、清屏和界面失效。
3. 让底栏回调直接显示共享状态的 `[DEFAULT]` 或 `[PLAN]`。
4. 使用管道输入和无界面输出验证模式切换后重绘。

**验证：** 运行 `python -m pytest tests/test_terminal.py -k 'toolbar or output or clear' -q`，期望终端输出和单一状态来源测试通过。

## T28：实现精确 Tab 键行为

**文件：** `src/mewcode/terminal.py`、`tests/test_terminal.py`  
**依赖：** T27

**步骤：**

1. 增加自定义 Tab 绑定。
2. 单候选时直接应用完整文本；带参数提示的候选追加空格。
3. 多候选时启动可选择菜单而不擅自选中某项。
4. 用真实 Tab 键序列验证 `/comp`、`/p`、大小写前缀和隐藏命令。

**验证：** 运行 `python -m pytest tests/test_terminal.py -k tab -q`，期望单补全和多候选菜单测试通过。

## T29：实现权限输入和终端 EOF

**文件：** `src/mewcode/terminal.py`、`tests/test_terminal.py`  
**依赖：** T27

**步骤：**

1. 实现不启用命令补全的异步权限提示。
2. 保证普通输入和权限输入的 EOF 均作为 EOFError 交给 REPL。
3. 验证权限输入不会污染正常命令缓冲区或历史。

**验证：** 运行 `python -m pytest tests/test_terminal.py -q`，期望全部终端测试通过。

## T30：建立 REPL 单事件循环骨架

**文件：** `src/mewcode/repl.py`、`tests/test_repl.py`  
**依赖：** T14、T17、T28、T29

**步骤：**

1. 用脚本化 TerminalSession 替换测试中的同步 input_func。
2. 让 `run()` 只创建一个 Runner 并执行完整异步循环。
3. 在 REPL 构造时用自身 UI/Runtime 适配创建 CommandDispatcher。
4. 保留启动消息和事件渲染器，不在此任务接入全部命令行为。

**验证：** 运行 `python -m pytest tests/test_repl.py -k 'startup or empty or direct' -q`，期望单循环启动和基础输入测试通过。

## T31：接入三路输入分流与持续模式

**文件：** `src/mewcode/repl.py`、`tests/test_repl.py`  
**依赖：** T30

**步骤：**

1. 对 Terminal 输入统一调用 `parse_input()`。
2. 空输入直接继续，命令交给 Dispatcher，普通消息进入 Conversation。
3. 将 DEFAULT/PLAN 交互状态映射到对应 ConversationMode。
4. 验证未知命令、大小写命令和参数不会误发给 AI。

**验证：** 运行 `python -m pytest tests/test_repl.py -k 'route or command or mode' -q`，期望三路分流和模式路由测试通过。

## T32：实现 REPL 的 CommandUI 适配

**文件：** `src/mewcode/repl.py`、`tests/test_repl.py`  
**依赖：** T25、T31

**步骤：**

1. 实现消息、错误、清屏、模式读取切换、Token 查询、状态刷新和退出请求。
2. 将 `read_only=True` 用户消息映射到 `ConversationMode.READ_ONLY` 并消费事件。
3. 让模式切换与清屏不改变会话历史和领域状态。

**验证：** 运行 `python -m pytest tests/test_repl.py -k 'ui_adapter or review or clear' -q`，期望 UI 协议行为测试通过。

## T33：实现 REPL 的 CommandRuntime 适配

**文件：** `src/mewcode/repl.py`、`tests/test_repl.py`  
**依赖：** T8、T11、T32

**步骤：**

1. 代理 Conversation、MemoryManager、ContextManager 和 PermissionController 快照。
2. 实现权限模式查询与切换。
3. 实现手动压缩并沿用现有事件渲染。
4. 验证状态命令不调用预检、不等待 pending 记忆任务。

**验证：** 运行 `python -m pytest tests/test_repl.py -k 'runtime_adapter or compact or local_status' -q`，期望本地状态与压缩适配测试通过。

## T34：异步化权限请求并保持事件渲染

**文件：** `src/mewcode/repl.py`、`tests/test_repl.py`  
**依赖：** T33

**步骤：**

1. 让事件消费在遇到权限请求时 await Terminal 权限输入。
2. 保留 deny/once/session/permanent 解析和非法输入重试。
3. EOF 时拒绝 Challenge，Agent 流继续安全收尾。
4. 运行现有输出层级测试，确保流式文本和辅助事件格式不变。

**验证：** 运行 `python -m pytest tests/test_repl.py -k 'permission or event or streaming or indent' -q`，期望权限与渲染测试通过。

## T35：完成 REPL 退出、取消与关闭路径

**文件：** `src/mewcode/repl.py`、`tests/test_repl.py`  
**依赖：** T34

**步骤：**

1. 让 `/exit`、`/quit` 和普通 EOF 走统一正常关闭路径。
2. 输入阶段 KeyboardInterrupt 在关闭后返回 130。
3. Agent/压缩阶段取消调用现有取消能力并返回输入循环。
4. 关闭警告写入错误流，单项失败不跳过其余收尾。

**验证：** 运行 `python -m pytest tests/test_repl.py -q`，期望全部 REPL 测试通过。

## T36：在 CLI 统一包裹并注入跟踪 Provider

**文件：** `src/mewcode/cli.py`、`tests/test_repl.py`  
**依赖：** T7、T8、T11、T14、T35

**步骤：**

1. 创建真实 Provider 后立即创建 Ledger 和跟踪包装器。
2. 将同一包装对象传给 ContextManager、MemoryUpdater 和 AgentRunner。
3. 把 Ledger、MemoryManager、ContextManager 和恢复标记交给 REPL/Conversation 状态路径。
4. 用 spy 验证三类模型消费者引用同一包装实例。

**验证：** 运行 `python -m pytest tests/test_repl.py -k 'cli and usage' -q`，期望 Provider 装配与恢复状态测试通过。

## T37：在 CLI 装配注册表和真实终端

**文件：** `src/mewcode/cli.py`、`src/mewcode/repl.py`、`tests/test_repl.py`  
**依赖：** T25、T29、T36

**步骤：**

1. 创建内置注册表、默认 InteractionState 和 PromptToolkitTerminal。
2. 将注册表、状态和终端传给 REPL，并更新启动帮助文案。
3. 捕获 `CommandRegistrationError`，输出冲突标识并在显示提示前返回 1。
4. 保持 MCP、权限、会话、记忆和归档关闭顺序。

**验证：** 运行 `python -m pytest tests/test_repl.py -k 'cli or registration or startup' -q`，期望正常装配、注册失败和资源关闭测试通过。

## T38：覆盖公开命令端到端序列

**文件：** `tests/test_continuity_integration.py`  
**依赖：** T37

**步骤：**

1. 用脚本终端执行帮助、补全候选、Plan/Do、清屏、权限、会话、记忆、状态和退出序列。
2. 验证十个公开命令可发现，隐藏命令只可直接执行。
3. 验证本地命令不形成会话消息且恢复后的历史完整。

**验证：** 运行 `python -m pytest tests/test_continuity_integration.py -k command_sequence -q`，期望完整公开命令序列通过。

## T39：覆盖 Plan 与 Review 的强制只读集成

**文件：** `tests/test_continuity_integration.py`、`tests/test_conversation.py`  
**依赖：** T38

**步骤：**

1. 在 PLAN 中提交写操作请求，断言实际工具集只有只读能力。
2. 在 DEFAULT 和 PLAN 下分别执行 `/review`，断言都使用固定提示、DIRECT 模式和只读工具。
3. 验证审查成功或失败后持续模式和工作区均不变。

**验证：** 运行 `python -m pytest tests/test_conversation.py tests/test_continuity_integration.py -k 'plan_read_only or review_read_only' -q`，期望只读边界测试通过。

## T40：覆盖全模型 Token 与本地零调用集成

**文件：** `tests/test_continuity_integration.py`、`tests/test_usage_tracking.py`  
**依赖：** T39

**步骤：**

1. 用可控 Provider 分别产生普通、PLAN、review、压缩和记忆更新 usage。
2. 验证 `/status` 累计值无重复且请求数正确。
3. 注入一次缺失 usage，验证对应字段为 `n/a`。
4. 对八个非模型命令记录调用轨迹，验证不调用 Provider、不进入 Agent、不等待记忆任务。

**验证：** 运行 `python -m pytest tests/test_usage_tracking.py tests/test_continuity_integration.py -k 'all_model_usage or local_commands' -q`，期望用量和零调用测试通过。

## T41：更新用户文档

**文件：** `README.md`  
**依赖：** T40

**步骤：**

1. 用表格记录十个公开命令、`/permissions` 别名和隐藏退出兼容行为。
2. 说明 `/plan`、`/do` 是持续模式切换，Plan 强制只读。
3. 说明 `/review` 单次只读、`/clear` 仅清屏、Tab 补全和底栏标记。
4. 删除旧 `/plan <task>` 与 `/do` 自动执行说明。

**验证：** 运行 `rg -n '/help|/compact|/clear|/plan|/do|/session|/memory|/permission|/status|/review|\[DEFAULT\]|\[PLAN\]' README.md`，期望所有公开命令和两个模式均有说明，且不存在旧用法。

## T42：执行完整回归并清理差异

**文件：** 本阶段全部实现和测试文件  
**依赖：** T41

**步骤：**

1. 运行完整测试套件，修复所有本阶段引入的回归。
2. 检查测试没有依赖真实网络、真实用户目录或交互终端。
3. 检查没有修改会话 JSONL 格式，没有引入计划外别名、动态提示或命令权限。
4. 检查格式和工作树差异，只处理本阶段文件。

**验证：** 运行 `python -m pytest -q`，期望全部测试通过；再运行 `git diff --check`，期望无空白错误。

## 执行顺序

```text
T1 ───────────────────────────────────────────────┐
T2 -> T3 -> T4 ───────────────────────────────┐   │
T5 -> T6 -> T7 ────────────────────────────┐  │   │
T8 ─────────────────────────────────────┐   │  │   │
T9 -> T10 -> T11 ────────────────────┐  │   │  │   │
T12 -> T13 -> T14 ────────────────┐  │  │   │  │   │
                                  v  v  v   v  v   │
                                 T15 -> T16 -> T17 -> T18
                                                    │
                         T19 -> T20 ────────────────┤
                           ├──> T21 ────────────────┤
                           ├──> T22 ────────────────┤
                           ├──> T23 ────────────────┤
                           └──> T24 ────────────────┘
                                      -> T25

T1 + T4 + T15 -> T26 -> T27 -> T28
                            └──────> T29

T14 + T17 + T28 + T29 -> T30 -> T31 -> T32 -> T33 -> T34 -> T35
T7 + T8 + T11 + T14 + T35 -> T36
T25 + T29 + T36 -> T37 -> T38 -> T39 -> T40 -> T41 -> T42
```

T2-T14 中互不依赖的命令核心、Token、上下文、记忆和 Conversation 分支可以并行；T20-T24 的内置命令处理也可在 T19 后并行。其余任务按依赖顺序执行。
