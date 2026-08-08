# MewCode Agent Loop Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 新建 | `src/mewcode/agent/__init__.py` | Agent 公共出口 |
| 新建 | `src/mewcode/agent/events.py` | 模式、停止原因和统一事件 |
| 新建 | `src/mewcode/agent/streaming.py` | 双路流式收集器 |
| 新建 | `src/mewcode/agent/scheduler.py` | 工具安全分批与并发调度 |
| 新建 | `src/mewcode/agent/runner.py` | ReAct 循环、停止策略和运行结果 |
| 修改 | `src/mewcode/providers/base.py` | 异步 Provider 协议、Token 和完整响应 |
| 修改 | `src/mewcode/providers/__init__.py` | 导出新增 Provider 公共类型 |
| 修改 | `src/mewcode/providers/anthropic_provider.py` | Anthropic 异步流、多工具和用量适配 |
| 修改 | `src/mewcode/providers/openai_provider.py` | OpenAI 异步流、多工具和用量适配 |
| 修改 | `src/mewcode/tools/base.py` | 工具安全分类、异步执行和注册中心视图 |
| 修改 | `src/mewcode/tools/__init__.py` | 导出新增工具公共类型 |
| 修改 | `src/mewcode/tools/builtin.py` | 保持六工具注册并验证安全分类 |
| 修改 | `src/mewcode/tools/file_tools.py` | 异步文件工具与固定安全分类 |
| 修改 | `src/mewcode/tools/search_tools.py` | 异步可取消搜索工具 |
| 修改 | `src/mewcode/tools/command_tool.py` | 可取消异步子进程 |
| 修改 | `src/mewcode/conversation.py` | 会话历史、AgentRun 代理和 Plan Mode |
| 修改 | `src/mewcode/repl.py` | Agent 事件展示、命令解析和单轮取消 |
| 修改 | `src/mewcode/cli.py` | 新依赖组装和异步运行器生命周期 |
| 新建 | `tests/fakes.py` | 可控异步 Provider、工具和事件收集 helper |
| 新建 | `tests/test_stream_collector.py` | 流收集与实时事件测试 |
| 新建 | `tests/test_tool_scheduler.py` | 并发、屏障、排序和取消测试 |
| 新建 | `tests/test_agent_runner.py` | ReAct 循环与停止条件测试 |
| 新建 | `tests/test_plan_mode.py` | `/plan`、`/do` 和计划生命周期测试 |
| 修改 | `tests/test_providers.py` | 异步 SDK、Token、错误和 fallback 测试 |
| 修改 | `tests/test_tool_providers.py` | 多工具解析和批量消息转换测试 |
| 修改 | `tests/test_tools_base.py` | 安全分类、异步注册中心和视图测试 |
| 修改 | `tests/test_file_tools.py` | 异步文件工具回归测试 |
| 修改 | `tests/test_search_tools.py` | 异步搜索与协作取消测试 |
| 修改 | `tests/test_command_tool.py` | 异步命令、超时和取消测试 |
| 修改 | `tests/test_conversation.py` | 异步直接会话和历史提交测试 |
| 修改 | `tests/test_tool_conversation.py` | 多轮工具 Agent 集成回归测试 |
| 修改 | `tests/test_repl.py` | 事件格式、命令路由、取消和 CLI 测试 |
| 修改 | `README.md` | Agent Loop 与 Plan Mode 使用说明 |

## T1：定义 Provider 归一化响应类型

**文件：** `src/mewcode/providers/base.py`、`src/mewcode/providers/__init__.py`、`tests/test_providers.py`

**依赖：** 无

**步骤：**

1. 新增 `TokenUsage`、`ProviderUsage` 和 `ModelResponse`，实现未知值传播的 `TokenUsage.add()`。
2. 将 `ProviderEvent` 纳入用量事件，将 `LLMProvider` 签名改为异步事件流和批量消息转换。
3. 更新包出口并增加 Token 累计、未知字段和类型构造测试。

**验证：** 运行 `python -m pytest tests/test_providers.py -q -k token_usage`，期望 Token 累计与未知值测试全部通过。

## T2：定义工具安全与执行结果类型

**文件：** `src/mewcode/tools/base.py`、`src/mewcode/tools/__init__.py`、`tests/test_tools_base.py`

**依赖：** 无

**步骤：**

1. 新增 `ToolSafety` 和带原始顺序的 `ToolExecution`。
2. 为 `Tool` 协议增加 `safety`，并把执行签名改为异步。
3. 更新包出口和测试用 fake 工具，验证枚举与执行记录字段。

**验证：** 运行 `python -m pytest tests/test_tools_base.py -q -k "tool_safety or tool_execution"`，期望新增类型测试通过。

## T3：升级异步工具注册中心

**文件：** `src/mewcode/tools/base.py`、`tests/test_tools_base.py`

**依赖：** T2

**步骤：**

1. 将 `ToolRegistry.execute()` 改为等待异步工具，同时保留参数校验、未知工具和异常包装。
2. 实现 `select()`，返回共享工具实例且只包含指定安全分类的新注册中心。
3. 把注册中心执行测试改用 `asyncio.run()`，增加视图不可越权执行测试。

**验证：** 运行 `python -m pytest tests/test_tools_base.py -q -k registry`，期望注册、异步执行、筛选和错误包装测试通过。

## T4：标记六个内置工具的安全分类

**文件：** `src/mewcode/tools/file_tools.py`、`src/mewcode/tools/search_tools.py`、`src/mewcode/tools/command_tool.py`、`src/mewcode/tools/builtin.py`、`tests/test_tools_base.py`

**依赖：** T2

**步骤：**

1. 将读文件、找文件、搜代码标记为 `READ_ONLY`。
2. 将写文件、编辑文件、执行命令标记为 `SIDE_EFFECT`。
3. 验证完整注册中心有六个工具，只读视图恰好导出三个只读工具。

**验证：** 运行 `python -m pytest tests/test_tools_base.py -q -k builtin_registry`，期望工具数量、名称和安全分类测试通过。

## T5：建立 Agent 事件公共模型

**文件：** `src/mewcode/agent/events.py`、`src/mewcode/agent/__init__.py`

**依赖：** T1、T2

**步骤：**

1. 定义 `AgentMode`、`StopReason` 和六类事件 dataclass。
2. 定义 `AgentEvent` 联合类型并从 Agent 包统一导出。
3. 确保每类事件都包含设计要求的运行、迭代和载荷字段。

**验证：** 运行 `python -m py_compile src/mewcode/agent/events.py src/mewcode/agent/__init__.py`，期望编译成功且无导入错误。

## T6：建立异步测试替身

**文件：** `tests/fakes.py`

**依赖：** T1、T2、T5

**步骤：**

1. 实现可按轮返回 Provider 事件或异常的 `ScriptedAsyncProvider`。
2. 实现可用事件门控制开始、完成、失败和取消的异步 fake 工具。
3. 提供用 `asyncio.run()` 收集异步事件的 helper，所有替身记录调用历史。

**验证：** 运行 `python -m py_compile tests/fakes.py`，期望测试替身文件编译成功。

## T7：实现文本双路收集

**文件：** `src/mewcode/agent/streaming.py`、`tests/test_stream_collector.py`

**依赖：** T1、T5、T6

**步骤：**

1. 建立 `StreamCollector` 状态机和 `StreamStateError`。
2. 实时把 `ProviderTextDelta` 转换为 `AgentTextDelta`，同时累积完整文本。
3. 在正常流结束后生成无工具调用的 `ModelResponse`。

**验证：** 运行 `python -m pytest tests/test_stream_collector.py -q -k text`，期望实时分片与完整文本测试通过。

## T8：收集工具调用与 Token 用量

**文件：** `src/mewcode/agent/streaming.py`、`tests/test_stream_collector.py`

**依赖：** T7

**步骤：**

1. 按到达顺序收集多个完整工具调用，并各发出一次 `AgentToolCall`。
2. 处理 `ProviderUsage`，生成当前与累计 `AgentTokenUsage`。
3. 未收到用量事件时使用字段均为 `None` 的用量，而不是零。

**验证：** 运行 `python -m pytest tests/test_stream_collector.py -q -k "tool_call or usage"`，期望多调用、事件唯一性和用量测试通过。

## T9：封闭异常与非法状态

**文件：** `src/mewcode/agent/streaming.py`、`tests/test_stream_collector.py`

**依赖：** T8

**步骤：**

1. 流异常或取消时标记 Collector 未完成且不生成 `ModelResponse`。
2. 在流完成前读取 `response` 时抛出 `StreamStateError`。
3. 禁止同一 Collector 被消费两次，并验证已经发出的文本仍可被观察。

**验证：** 运行 `python -m pytest tests/test_stream_collector.py -q -k "error or state or cancel"`，期望异常与状态测试通过。

## T10：实现工具批次切分

**文件：** `src/mewcode/agent/scheduler.py`、`tests/test_tool_scheduler.py`

**依赖：** T2、T3、T5、T6

**步骤：**

1. 实现按原始顺序切分相邻只读批次和单个副作用屏障的内部逻辑。
2. 将未知工具切成不执行的串行屏障。
3. 为纯只读、纯副作用和混合顺序增加批次结构测试。

**验证：** 运行 `python -m pytest tests/test_tool_scheduler.py -q -k partition`，期望所有批次切分测试通过。

## T11：实现有界只读并发

**文件：** `src/mewcode/agent/scheduler.py`、`tests/test_tool_scheduler.py`

**依赖：** T10

**步骤：**

1. 使用异步任务和信号量并发执行只读批次。
2. 用受控 fake 工具记录最大同时运行数量。
3. 验证结果事件按完成时间产生，最大并发不超过 4。

**验证：** 运行 `python -m pytest tests/test_tool_scheduler.py -q -k concurrency`，期望并发重叠、上限和完成顺序测试通过。

## T12：实现副作用屏障与稳定回写顺序

**文件：** `src/mewcode/agent/scheduler.py`、`tests/test_tool_scheduler.py`

**依赖：** T11

**步骤：**

1. 串行执行副作用工具，并等待前一批完全结束。
2. 未知工具生成结构化失败结果，不调用任何 Tool。
3. 将所有 `ToolExecution` 按原始 index 排序，验证事件完成顺序不影响回写顺序。

**验证：** 运行 `python -m pytest tests/test_tool_scheduler.py -q -k "barrier or ordering or unknown"`，期望独占执行和稳定排序测试通过。

## T13：实现工具调度取消

**文件：** `src/mewcode/agent/scheduler.py`、`tests/test_tool_scheduler.py`

**依赖：** T12

**步骤：**

1. 为 `ToolSchedule` 增加单次消费保护、活动任务追踪和取消清理。
2. 保留已完成调用结果，为活动和未启动调用补结构化取消结果。
3. 验证取消后不进入后续批次、不遗留 asyncio 任务且结果仍按原始顺序完整。

**验证：** 运行 `python -m pytest tests/test_tool_scheduler.py -q -k cancel`，期望取消与清理测试通过。

## T14：实现 AgentRun 正常完成骨架

**文件：** `src/mewcode/agent/runner.py`、`src/mewcode/agent/__init__.py`、`tests/test_agent_runner.py`

**依赖：** T8、T12、T6

**步骤：**

1. 定义 `AgentRunConfig`、`AgentRunOutcome`、状态错误、`AgentRunner.start()` 和单次消费 `AgentRun`。
2. 实现 run/iteration 进度、一次无工具模型调用和唯一 `AgentStopped(COMPLETED)`。
3. 将完整用户消息和 assistant 文本写入 `new_messages`。

**验证：** 运行 `python -m pytest tests/test_agent_runner.py -q -k completed_without_tools`，期望完成原因、最终文本和消息测试通过。

## T15：实现多轮 ReAct 工具循环

**文件：** `src/mewcode/agent/runner.py`、`tests/test_agent_runner.py`

**依赖：** T14

**步骤：**

1. 在完整响应含工具调用时启动 ToolSchedule，并转发其结果与进度事件。
2. 通过 Provider 批量转换接口追加 assistant 调用和工具结果消息。
3. 使用更新后的工作历史继续调用模型，直到得到无工具最终响应。

**验证：** 运行 `python -m pytest tests/test_agent_runner.py -q -k react_loop`，期望两轮以上工具调用自动完成且后续调用看到全部结果。

## T16：保证工具失败与历史原子配对

**文件：** `src/mewcode/agent/runner.py`、`tests/test_agent_runner.py`

**依赖：** T15

**步骤：**

1. 普通工具失败仍将完整结果消息回写并继续下一迭代。
2. 仅在一个响应的全部工具调用都有结果后才把该段加入 `new_messages`。
3. 验证失败修正场景以及 assistant 调用和结果数量严格配对。

**验证：** 运行 `python -m pytest tests/test_agent_runner.py -q -k "tool_failure or atomic_history"`，期望失败恢复和协议配对测试通过。

## T17：实现迭代上限停止

**文件：** `src/mewcode/agent/runner.py`、`tests/test_agent_runner.py`

**依赖：** T15

**步骤：**

1. 每次模型调用前后维护从 1 开始的迭代计数。
2. 第 20 次完整响应仍请求工具时不创建 ToolSchedule，也不提交该响应。
3. 生成唯一 `AgentStopped(ITERATION_LIMIT)`，保留此前完整迭代和累计用量。

**验证：** 运行 `python -m pytest tests/test_agent_runner.py -q -k iteration_limit`，期望恰好 20 次模型调用且最后工具未执行。

## T18：实现连续未知工具停止

**文件：** `src/mewcode/agent/runner.py`、`tests/test_agent_runner.py`

**依赖：** T16

**步骤：**

1. 仅在一轮全部调用均未知时增加计数，出现任一已注册工具时归零。
2. 前两轮未知结果正常回写并继续。
3. 第三轮保存完整未知调用与失败结果后以 `UNKNOWN_TOOL_LIMIT` 停止。

**验证：** 运行 `python -m pytest tests/test_agent_runner.py -q -k unknown_tool_limit`，期望自我修正与连续三轮停止场景通过。

## T19：实现流错误和内部错误停止

**文件：** `src/mewcode/agent/runner.py`、`tests/test_agent_runner.py`

**依赖：** T15

**步骤：**

1. 捕获 `ProviderError`，丢弃当前 Collector 并生成 `STREAM_ERROR`。
2. 捕获非取消的意外异常，清理活动任务并生成 `ERROR`。
3. 验证部分文本事件可见、当前响应不提交、此前完整迭代保留且不自动重试。

**验证：** 运行 `python -m pytest tests/test_agent_runner.py -q -k "stream_error or internal_error"`，期望错误停止和历史边界测试通过。

## T20：实现 AgentRun 主动取消

**文件：** `src/mewcode/agent/runner.py`、`tests/test_agent_runner.py`

**依赖：** T13、T19

**步骤：**

1. 实现幂等 `cancel()`，传播到活动 Provider 流或 ToolSchedule。
2. 对完整工具响应补齐取消结果，对不完整模型流直接丢弃。
3. 清理后生成唯一 `AgentStopped(CANCELLED)`，不启动下一模型调用。

**验证：** 运行 `python -m pytest tests/test_agent_runner.py -q -k cancel`，期望模型阶段、工具阶段和重复取消测试通过。

## T21：补齐 Agent 进度、Token 和事件顺序

**文件：** `src/mewcode/agent/runner.py`、`tests/test_agent_runner.py`

**依赖：** T17、T18、T20

**步骤：**

1. 发出任务开始、迭代开始、模型完成、工具批次开始和完成进度。
2. 跨迭代累计 Token，并透传当前与累计用量。
3. 验证每个工具调用事件只来自 Collector、每次运行只有一个停止事件且因果标识一致。

**验证：** 运行 `python -m pytest tests/test_agent_runner.py -q -k "progress or usage or event_order"`，期望进度、用量和事件唯一性测试通过。

## T22：迁移 Anthropic 基础异步流

**文件：** `src/mewcode/providers/anthropic_provider.py`、`tests/test_providers.py`

**依赖：** T1

**步骤：**

1. 使用 `AsyncAnthropic` 和异步消息流上下文。
2. 将文本事件解析器改为异步迭代并保持请求参数不变。
3. 更新 SDK fake 和纯文本请求测试为 `asyncio.run()`。

**验证：** 运行 `python -m pytest tests/test_providers.py -q -k "anthropic and text"`，期望异步文本流和请求构造测试通过。

## T23：保留 Anthropic 错误、fallback 与取消

**文件：** `src/mewcode/providers/anthropic_provider.py`、`tests/test_providers.py`

**依赖：** T22

**步骤：**

1. 保留 API Key 脱敏和 `ProviderError` 包装。
2. 保留 adaptive thinking 不支持时仅回退一次 manual thinking 的行为。
3. 确保异步取消退出流上下文且不触发 fallback 或重试。

**验证：** 运行 `python -m pytest tests/test_providers.py -q -k "anthropic and (error or fallback or cancel)"`，期望错误、回退和取消测试通过。

## T24：解析 Anthropic 多工具调用

**文件：** `src/mewcode/providers/anthropic_provider.py`、`tests/test_tool_providers.py`

**依赖：** T22

**步骤：**

1. 按内容块 index 独立保存多个 tool-use 的 ID、名称和 JSON 参数碎片。
2. 每个内容块结束时生成一次完整 `ProviderToolCall`。
3. 保留坏 JSON 的原始参数，并验证文本与多个工具交错时不串包。

**验证：** 运行 `python -m pytest tests/test_tool_providers.py -q -k "anthropic and (multiple or bad_json)"`，期望多工具与坏参数测试通过。

## T25：归一化 Anthropic 用量并批量转换消息

**文件：** `src/mewcode/providers/anthropic_provider.py`、`tests/test_tool_providers.py`

**依赖：** T24

**步骤：**

1. 合并 message-start 和 message-delta 中的输入、输出 Token，正常结束时发出一次 `ProviderUsage`。
2. 将完整 `ModelResponse` 转换为包含文本和全部 tool-use 的 assistant 消息。
3. 将有序 `ToolExecution` 转换为一个包含全部 tool-result 的用户消息。

**验证：** 运行 `python -m pytest tests/test_tool_providers.py -q -k "anthropic and (usage or batch_message)"`，期望用量和批量消息格式测试通过。

## T26：迁移 OpenAI 基础异步流

**文件：** `src/mewcode/providers/openai_provider.py`、`tests/test_providers.py`

**依赖：** T1

**步骤：**

1. 使用 `AsyncOpenAI.responses.create(..., stream=True)`。
2. 异步解析输出文本并保持现有 Responses API 输入构造。
3. 更新 SDK fake 和纯文本测试为异步迭代。

**验证：** 运行 `python -m pytest tests/test_providers.py -q -k "openai and text"`，期望异步文本流和请求构造测试通过。

## T27：保留 OpenAI 错误脱敏与取消

**文件：** `src/mewcode/providers/openai_provider.py`、`tests/test_providers.py`

**依赖：** T26

**步骤：**

1. 将流内 error 事件和 SDK 异常统一包装成脱敏 `ProviderError`。
2. 取消时关闭异步响应流且不发起第二次请求。
3. 验证 API Key 不出现在异常文本中。

**验证：** 运行 `python -m pytest tests/test_providers.py -q -k "openai and (error or cancel or redacted)"`，期望错误、取消和脱敏测试通过。

## T28：解析 OpenAI 多工具调用

**文件：** `src/mewcode/providers/openai_provider.py`、`tests/test_tool_providers.py`

**依赖：** T26

**步骤：**

1. 按 item ID 独立收集多个 function-call 参数流，并保留 call ID。
2. 同时兼容 arguments-done 和 output-item-done，避免重复发出同一调用。
3. 验证多调用交错、仅 item-done 和坏 JSON 场景。

**验证：** 运行 `python -m pytest tests/test_tool_providers.py -q -k "openai and (multiple or item_done or bad_json)"`，期望多工具解析和去重测试通过。

## T29：归一化 OpenAI 用量并批量转换消息

**文件：** `src/mewcode/providers/openai_provider.py`、`tests/test_tool_providers.py`

**依赖：** T28

**步骤：**

1. 从 response-completed 中提取输入、输出和总 Token，缺失字段保持 `None`。
2. 将完整响应转换为 assistant 文本和有序 function-call 输入项。
3. 将有序执行结果转换为 function-call-output 输入项，保持调用 ID 和顺序。

**验证：** 运行 `python -m pytest tests/test_tool_providers.py -q -k "openai and (usage or batch_message)"`，期望用量与批量消息测试通过。

## T30：迁移异步读文件工具

**文件：** `src/mewcode/tools/file_tools.py`、`tests/test_file_tools.py`

**依赖：** T2、T4

**步骤：**

1. 将 `ReadFileTool.execute()` 改为异步入口并保持 UTF-8、路径边界和截断行为。
2. 对可能阻塞的读取使用可取消工作线程包装。
3. 将现有读取测试改用 `asyncio.run()`，保持原断言不变。

**验证：** 运行 `python -m pytest tests/test_file_tools.py -q -k read_file`，期望读取、越界和截断测试通过。

## T31：迁移异步写文件与编辑工具

**文件：** `src/mewcode/tools/file_tools.py`、`tests/test_file_tools.py`

**依赖：** T30

**步骤：**

1. 将写入和唯一替换操作改为异步接口，并将短写入视为不可分割临界段。
2. 保持父目录创建、越界拒绝、零匹配、多匹配和空原文行为。
3. 将相关测试改用 `asyncio.run()`。

**验证：** 运行 `python -m pytest tests/test_file_tools.py -q -k "write_file or edit_file"`，期望全部写入和编辑回归测试通过。

## T32：迁移异步找文件与搜代码工具

**文件：** `src/mewcode/tools/search_tools.py`、`tests/test_search_tools.py`

**依赖：** T2、T4

**步骤：**

1. 为找文件和搜代码提供异步执行入口。
2. 将目录扫描和内容搜索放入工作线程，同时保留隐藏目录跳过、路径限制和截断规则。
3. 将现有搜索测试改用 `asyncio.run()`。

**验证：** 运行 `python -m pytest tests/test_search_tools.py -q -k "find_files or search_code"`，期望原有查找、搜索、边界和截断行为通过。

## T33：实现只读扫描协作取消

**文件：** `src/mewcode/tools/search_tools.py`、`tests/test_search_tools.py`

**依赖：** T32

**步骤：**

1. 在线程扫描循环中定期检查协作停止标志。
2. 异步任务被取消时设置停止标志并等待工作线程退出。
3. 用受控大量文件场景验证取消后扫描计数不再增长且 2 秒内结束。

**验证：** 运行 `python -m pytest tests/test_search_tools.py -q -k cancel`，期望协作取消和无残留扫描测试通过。

## T34：实现异步命令基本执行

**文件：** `src/mewcode/tools/command_tool.py`、`tests/test_command_tool.py`

**依赖：** T2、T4

**步骤：**

1. 用 `asyncio.create_subprocess_shell()` 替代 `subprocess.run()`。
2. 保持工作区 cwd、stdout、stderr、退出码、危险命令和超时参数校验。
3. 将安全命令、非零退出和输出截断测试改为异步。

**验证：** 运行 `python -m pytest tests/test_command_tool.py -q -k "safe_command or nonzero or cwd or truncates or rejects"`，期望基本命令行为测试通过。

## T35：实现命令超时与取消清理

**文件：** `src/mewcode/tools/command_tool.py`、`tests/test_command_tool.py`

**依赖：** T34

**步骤：**

1. 超时时先终止子进程，短暂等待后仍未退出则强制结束。
2. 任务取消使用相同清理路径并重新传播取消。
3. 验证超时结果结构、取消耗时和子进程不再存活。

**验证：** 运行 `python -m pytest tests/test_command_tool.py -q -k "timeout or cancel"`，期望超时和取消清理测试通过。

## T36：完成工具层整体回归

**文件：** `src/mewcode/tools/__init__.py`、`src/mewcode/tools/builtin.py`、`tests/test_tools_base.py`、`tests/test_file_tools.py`、`tests/test_search_tools.py`、`tests/test_command_tool.py`

**依赖：** T3、T31、T33、T35

**步骤：**

1. 核对所有新增类型均从 tools 包导出，六个工具仍使用原名称和参数 Schema。
2. 修正异步迁移产生的工具注册和测试调用差异。
3. 运行整个工具测试集合，确认工作区边界和危险命令保护没有退化。

**验证：** 运行 `python -m pytest tests/test_tools_base.py tests/test_file_tools.py tests/test_search_tools.py tests/test_command_tool.py tests/test_workspace.py -q`，期望工具层全部测试通过。

## T37：接入 Conversation 普通任务

**文件：** `src/mewcode/conversation.py`、`tests/test_conversation.py`

**依赖：** T21、T36

**步骤：**

1. 用 `AgentRunner` 和完整工具注册中心替代旧的一次工具编排。
2. 实现异步 `ask()` 事件代理和运行结束后的 `new_messages` 一次提交。
3. 保持 `messages()` 返回副本，并验证纯聊天及多轮上下文。

**验证：** 运行 `python -m pytest tests/test_conversation.py -q -k "ask or history or context"`，期望普通异步会话和历史测试通过。

## T38：实现生成计划与只读边界

**文件：** `src/mewcode/conversation.py`、`tests/test_plan_mode.py`

**依赖：** T37

**步骤：**

1. 定义 `PendingPlan`、规划提示和 `plan(task)`。
2. 使用只读注册中心视图和 `PLAN` 模式启动 AgentRun。
3. 仅在完成时保存或替换计划；失败时保留原计划，并验证 Provider 只收到三个只读工具定义。

**验证：** 运行 `python -m pytest tests/test_plan_mode.py -q -k plan`，期望只读工具范围、计划保存和替换测试通过。

## T39：实现执行计划生命周期

**文件：** `src/mewcode/conversation.py`、`tests/test_plan_mode.py`

**依赖：** T38

**步骤：**

1. 实现执行提示和 `execute_plan()`，包含原始任务及完整计划文本。
2. 使用完整工具集合和 `EXECUTE` 模式。
3. 完成后清除计划；失败、流错误或取消后保留；无计划与空规划任务直接抛会话错误且不调用模型。

**验证：** 运行 `python -m pytest tests/test_plan_mode.py -q -k "execute or missing or empty"`，期望执行、清除、保留和输入校验测试通过。

## T40：实现活动运行保护与 Conversation 取消

**文件：** `src/mewcode/conversation.py`、`tests/test_conversation.py`、`tests/test_plan_mode.py`

**依赖：** T39

**步骤：**

1. 追踪当前 AgentRun，同一会话拒绝第二个并发运行。
2. 实现幂等 `cancel_active()` 并在事件消费结束后清空活动引用。
3. 验证取消结果仍提交安全消息，计划模式按停止原因正确保留状态。

**验证：** 运行 `python -m pytest tests/test_conversation.py tests/test_plan_mode.py -q -k "active or cancel"`，期望活动保护和取消生命周期测试通过。

## T41：实现 REPL Agent 事件格式化

**文件：** `src/mewcode/repl.py`、`tests/test_repl.py`

**依赖：** T5、T40

**步骤：**

1. 用统一 Agent 事件替代旧 Conversation 事件。
2. 文本增量立即输出；工具、进度、Token 和停止事件使用简短格式。
3. 确保终端不打印完整工具参数、完整结果或隐藏推理内容。

**验证：** 运行 `python -m pytest tests/test_repl.py -q -k "event or output or tool_status"`，期望事件展示和敏感内容隐藏测试通过。

## T42：实现 `/plan` 与 `/do` 命令路由

**文件：** `src/mewcode/repl.py`、`tests/test_repl.py`

**依赖：** T41

**步骤：**

1. 解析 `/plan <任务>` 并调用 `Conversation.plan()`。
2. 解析精确 `/do` 并调用 `execute_plan()`；普通文本调用 `ask()`。
3. 对空 `/plan`、无计划 `/do` 和会话忙错误输出明确提示且继续 REPL。

**验证：** 运行 `python -m pytest tests/test_repl.py -q -k "plan_command or do_command or routing"`，期望命令路由与错误提示测试通过。

## T43：实现 REPL 单轮 Ctrl+C 取消

**文件：** `src/mewcode/repl.py`、`tests/test_repl.py`

**依赖：** T42

**步骤：**

1. 使用长生命周期 `asyncio.Runner` 消费每轮异步事件。
2. 运行期间中断时取消当前 Conversation，完成清理后回到提示符。
3. 保留 EOF、退出命令和空闲中断退出行为，并验证取消后下一条消息仍可处理。

**验证：** 运行 `python -m pytest tests/test_repl.py -q -k "ctrl_c or continues_after_cancel or exit"`，期望单轮取消、继续输入和退出码测试通过。

## T44：更新 CLI 依赖组装

**文件：** `src/mewcode/cli.py`、`tests/test_repl.py`

**依赖：** T36、T40、T43、T23、T27

**步骤：**

1. 创建 Provider、完整注册中心、ToolScheduler、AgentRunner、Conversation 和 Repl。
2. 保留配置错误、Provider 启动错误和空闲 KeyboardInterrupt 的退出码。
3. 更新 CLI fake，断言各依赖被正确串接且配置格式不变。

**验证：** 运行 `python -m pytest tests/test_repl.py -q -k main`，期望 CLI 正常路径和错误路径测试通过。

## T45：验证双 Provider 统一事件语义

**文件：** `tests/test_providers.py`、`tests/test_tool_providers.py`

**依赖：** T25、T29

**步骤：**

1. 为两个 Provider 构造等价的文本、多工具和用量脚本。
2. 断言归一化事件序列包含等价文本、调用 ID、名称、参数和 Token。
3. 断言隐藏 thinking/reasoning 事件不会进入公共事件序列。

**验证：** 运行 `python -m pytest tests/test_providers.py tests/test_tool_providers.py -q -k parity`，期望 Provider 语义一致性测试通过。

## T46：迁移旧工具会话为多轮 Agent 集成测试

**文件：** `tests/test_tool_conversation.py`

**依赖：** T21、T37

**步骤：**

1. 将旧“最多一次工具”脚本改为至少两轮工具后完成的 Agent 场景。
2. 保留未知工具、失败结果回写和无工具纯聊天回归断言。
3. 断言每轮模型调用均获得工具定义，直到最终完成。

**验证：** 运行 `python -m pytest tests/test_tool_conversation.py -q`，期望迁移后的 Agent 集成测试全部通过。

## T47：增加 `/plan` 到 `/do` 端到端场景

**文件：** `tests/test_plan_mode.py`、`tests/test_repl.py`

**依赖：** T39、T43、T44

**步骤：**

1. 用 fake Provider 走完 `/plan <任务>`，读取工作区并生成计划。
2. 输入 `/do`，验证完整工具集合执行多轮并正常完成。
3. 断言计划被清除、终端事件顺序可读且第二次 `/do` 不调用模型。

**验证：** 运行 `python -m pytest tests/test_plan_mode.py tests/test_repl.py -q -k end_to_end`，期望两阶段端到端场景通过。

## T48：更新用户文档

**文件：** `README.md`

**依赖：** T44、T47

**步骤：**

1. 将“一轮最多一次工具”说明替换为 Agent Loop 行为和五类停止条件。
2. 说明多工具安全调度、`Ctrl+C` 单轮取消、进度与 Token 输出。
3. 增加 `/plan <任务>` 和 `/do` 的完整终端示例，并注明本章不包含的能力。

**验证：** 运行 `rg -n "Agent Loop|/plan|/do|Ctrl\+C|20" README.md`，期望每个主题至少出现一次且不存在旧的一次工具上限描述。

## T49：执行全量质量回归

**文件：** 全部本阶段修改文件

**依赖：** T36、T44、T45、T46、T47、T48

**步骤：**

1. 编译全部源码和测试，排除语法与导入错误。
2. 运行完整测试套件，修复所有新旧回归。
3. 运行 diff 格式检查，并确认测试无真实网络调用、无危险命令执行和无遗留异步任务警告。

**验证：** 依次运行 `python -m compileall -q src tests`、`python -m pytest -q` 和 `git diff --check`，期望命令全部以 0 退出，完整测试无失败、无警告性任务泄漏。

## 执行顺序

```text
T1 ─┬─> T5 ─> T6 ─> T7 ─> T8 ─> T9 ────────────────┐
    ├─> T22 -> T23 -> T24 -> T25 ────────────────┐  │
    └─> T26 -> T27 -> T28 -> T29 ─────────────┐  │  │
                                               │  │  │
T2 -> T3 ─┬─> T10 -> T11 -> T12 -> T13 ───────┼──┼──┤
          └─> T4 ─┬─> T30 -> T31 ─────────────┤  │  │
                  ├─> T32 -> T33 ─────────────┤  │  │
                  └─> T34 -> T35 ─────────────┤  │  │
                                              │  │  │
T3 + T31 + T33 + T35 -> T36 ──────────────────┤  │  │
T8 + T12 + T6 -> T14 -> T15 -> T16 ─┬─> T17  │  │  │
                                     ├─> T18  │  │  │
                                     └─> T19 -> T20 -> T21 ────────────┤
                                                                       │
T21 + T36 -> T37 -> T38 -> T39 -> T40 -> T41 -> T42 -> T43 ──────────┤
T23 + T27 + T36 + T40 + T43 -> T44 ──────────────────────────────────┤
T25 + T29 -> T45 ─────────────────────────────────────────────────────┤
T21 + T37 -> T46 ─────────────────────────────────────────────────────┤
T39 + T43 + T44 -> T47 -> T48 ────────────────────────────────────────┤
                                                                       v
                                                                      T49
```

可并行分支：

- T22–T25（Anthropic）与 T26–T29（OpenAI）可并行。
- T30–T31（文件）、T32–T33（搜索）与 T34–T35（命令）可并行。
- Provider 分支、工具分支和使用 fake 的 Agent 核心分支可在公共类型完成后并行，T44–T49 统一集成。
