# MewCode Agent Loop Checklist

> 每一项都通过运行命令或观察系统行为来验证；不以逐行阅读实现代码作为通过依据。

## 实现完整性

- [ ] Agent 公共包可以导入运行模式、停止原因、六类事件、Runner 和 Scheduler（验证：运行 `python -c "from mewcode.agent import AgentMode, StopReason, AgentTextDelta, AgentToolCall, AgentToolResult, AgentTokenUsage, AgentProgress, AgentStopped, AgentRunner, ToolScheduler"`，期望命令以 0 退出）。
- [ ] Provider 公共包可以导入异步协议、`TokenUsage`、`ProviderUsage` 和 `ModelResponse`（验证：运行 `python -c "from mewcode.providers import LLMProvider, TokenUsage, ProviderUsage, ModelResponse"`，期望命令以 0 退出）。
- [ ] 工具公共包可以导入 `ToolSafety` 和 `ToolExecution`，六个内置工具均有固定安全分类（验证：运行 `python -m pytest tests/test_tools_base.py -q -k "tool_safety or builtin_registry"`，期望只读工具为 3 个、副作用工具为 3 个）。
- [ ] Conversation 同时提供普通任务、规划、执行计划和活动取消入口（验证：运行 `python -m pytest tests/test_conversation.py tests/test_plan_mode.py -q -k "ask or plan or execute or cancel"`，期望接口行为测试通过）。

## Agent Loop 与停止条件

- [ ] **AC1：** 多轮工具任务可以自动循环到最终回答，无需用户追加消息（验证：运行 `python -m pytest tests/test_agent_runner.py tests/test_tool_conversation.py -q -k react_loop`，期望至少两轮工具调用后以 `COMPLETED` 停止）。
- [ ] **AC2：** 后续模型调用能看到此前完整调用和结果，并能根据失败结果修正动作（验证：运行 `python -m pytest tests/test_agent_runner.py -q -k "react_loop or tool_failure"`，期望 fake Provider 收到按轮累积的消息且修正场景完成）。
- [ ] **AC3：** 纯文本响应实时输出并保存为最终回答（验证：运行 `python -m pytest tests/test_stream_collector.py tests/test_agent_runner.py -q -k "text or completed_without_tools"`，期望分片立即出现、完整文本一致且停止原因为 `COMPLETED`）。
- [ ] **AC4：** 文本和工具参数分片被双路收集，流结束后恢复完整响应（验证：运行 `python -m pytest tests/test_stream_collector.py -q -k "text or tool_call"`，期望实时文本事件与最终完整文本、工具调用列表同时正确）。
- [ ] **AC5：** 单次响应的多个工具调用都恰好执行一次并在下一模型调用前全部回写（验证：运行 `python -m pytest tests/test_agent_runner.py tests/test_tool_scheduler.py -q -k "multiple or react_loop"`，期望调用次数、结果数量和后续消息完整）。
- [ ] **AC6：** 相邻只读工具能够重叠执行且并发不超过 4（验证：运行 `python -m pytest tests/test_tool_scheduler.py -q -k concurrency`，期望观察到并发重叠且最大活动计数不大于 4）。
- [ ] **AC7：** 写入、编辑和命令工具均作为独占屏障执行（验证：运行 `python -m pytest tests/test_tool_scheduler.py -q -k barrier`，期望副作用工具运行期间其他工具活动数为零，批次顺序与请求顺序一致）。
- [ ] **AC8：** 并发结果事件按完成时间出现，但回写顺序保持原始调用顺序（验证：运行 `python -m pytest tests/test_tool_scheduler.py -q -k ordering`，期望事件顺序与完成门一致、`ToolExecution` 顺序与请求 index 一致）。
- [ ] **AC9：** 每个工具调用和结果都能通过 run、iteration 与 call ID 建立关联（验证：运行 `python -m pytest tests/test_agent_runner.py -q -k event_order`，期望所有结果事件都能唯一关联调用，且调用事件不重复）。
- [ ] **AC10：** 坏参数、普通失败和工具异常不会终止循环（验证：运行 `python -m pytest tests/test_agent_runner.py tests/test_tools_base.py -q -k "tool_failure or wraps_unexpected"`，期望失败被结构化回写且下一迭代继续）。
- [ ] **AC11：** 第 20 次模型响应仍请求工具时停止且不执行该批工具（验证：运行 `python -m pytest tests/test_agent_runner.py -q -k iteration_limit`，期望模型调用数为 20、最后工具调用数为零、停止原因为 `ITERATION_LIMIT`）。
- [ ] **AC12：** 未知工具在限制内可被模型自行纠正（验证：运行 `python -m pytest tests/test_agent_runner.py -q -k "unknown_tool_limit and recovers"`，期望未知失败回写后改用已知工具并正常完成）。
- [ ] **AC13：** 连续三轮只请求未知工具时停止（验证：运行 `python -m pytest tests/test_agent_runner.py -q -k "unknown_tool_limit and stops"`，期望恰好三轮未知结果、无工具实际执行且停止原因为 `UNKNOWN_TOOL_LIMIT`）。
- [ ] **AC14：** 运行期间 `Ctrl+C` 在正常情况下 2 秒内回到 REPL，且下一消息可继续处理（验证：运行 `python -m pytest tests/test_repl.py -q -k "ctrl_c or continues_after_cancel"`，期望取消耗时断言通过且第二条消息得到响应）。
- [ ] **AC15：** 取消不回滚已完成副作用，也不启动后续工具（验证：运行 `python -m pytest tests/test_agent_runner.py tests/test_tool_scheduler.py -q -k "cancel and side_effect"`，期望已完成结果保留、后续 fake 工具调用数为零）。
- [ ] **AC16：** 流错误保留已展示文本和此前完整迭代，但不提交当前半截响应（验证：运行 `python -m pytest tests/test_agent_runner.py -q -k stream_error`，期望文本事件存在、`new_messages` 无当前响应且包含此前配对段）。
- [ ] **AC17：** 流错误不自动重试，并产生脱敏停止事件（验证：运行 `python -m pytest tests/test_agent_runner.py tests/test_providers.py -q -k "stream_error or redacted"`，期望 Provider 调用次数不增加、停止原因为 `STREAM_ERROR` 且错误中无 API Key）。
- [ ] **AC18：** 每轮与累计 Token 用量正确，缺失值明确为不可用（验证：运行 `python -m pytest tests/test_stream_collector.py tests/test_agent_runner.py -q -k usage`，期望当前、累计和 `None` 传播断言全部通过）。
- [ ] **AC19：** 完整任务包含开始、迭代、模型完成、工具批次和停止进度（验证：运行 `python -m pytest tests/test_agent_runner.py -q -k progress`，期望进度阶段按因果顺序齐全）。

## Plan Mode 与会话行为

- [ ] **AC20：** `/plan <任务>` 只暴露并允许三个只读工具（验证：运行 `python -m pytest tests/test_plan_mode.py -q -k "plan and readonly"`，期望 Provider 工具定义只有 `read_file`、`find_files`、`search_code`，副作用请求不执行）。
- [ ] **AC21：** 成功规划会显示并保存计划，新规划替换旧计划（验证：运行 `python -m pytest tests/test_plan_mode.py tests/test_repl.py -q -k "plan and replace"`，期望终端包含计划文本且 pending plan 等于最新内容）。
- [ ] **AC22：** `/do` 使用全部工具执行计划，完成后清除计划（验证：运行 `python -m pytest tests/test_plan_mode.py -q -k "execute and completed"`，期望六个工具定义可用、运行完成且再次执行提示无计划）。
- [ ] **AC23：** `/do` 失败或取消后仍可重试同一计划（验证：运行 `python -m pytest tests/test_plan_mode.py -q -k "execute and (failure or cancel)"`，期望 pending plan 保留且第二次执行能启动）。
- [ ] **AC24：** 空 `/plan` 和无计划 `/do` 不调用模型（验证：运行 `python -m pytest tests/test_plan_mode.py tests/test_repl.py -q -k "empty or missing"`，期望显示用法提示且 fake Provider 调用数为零）。
- [ ] **AC25：** 普通消息直接使用完整工具集合，纯聊天多轮行为不退化（验证：运行 `python -m pytest tests/test_conversation.py tests/test_tool_conversation.py -q -k "context or no_tool or direct"`，期望普通任务收到六个工具且多轮文本历史正确）。

## Provider、终端与故障隔离

- [ ] **AC26：** Anthropic 与 OpenAI 对等脚本生成等价统一事件（验证：运行 `python -m pytest tests/test_providers.py tests/test_tool_providers.py -q -k parity`，期望文本、工具调用、Token 和停止语义逐项一致）。
- [ ] **AC27：** 终端不显示完整参数、原始供应商事件或大结果，超限结果仍被标记（验证：运行 `python -m pytest tests/test_repl.py tests/test_file_tools.py tests/test_search_tools.py tests/test_command_tool.py -q -k "tool_status or output or truncates"`，期望输出无参数 JSON，所有超限场景含截断标记）。
- [ ] **AC28：** Provider、工具或事件渲染错误后 REPL 继续工作且没有遗留任务（验证：运行 `python -m pytest tests/test_repl.py tests/test_agent_runner.py tests/test_tool_scheduler.py -q -k "internal_error or render_error or cancel"`，期望下一输入仍被处理且测试结束无 pending-task 警告）。
- [ ] **AC29：** API Key 与隐藏推理不会进入错误、事件或历史（验证：运行 `python -m pytest tests/test_providers.py tests/test_tool_providers.py tests/test_repl.py -q -k "redacted or hidden or reasoning"`，期望哨兵密钥和隐藏内容在所有可观察载荷中均不存在）。
- [ ] **AC30：** 测试在无真实密钥、无网络和无危险命令条件下完成（验证：在新 PowerShell 进程运行 `Remove-Item Env:OPENAI_API_KEY,Env:ANTHROPIC_API_KEY -ErrorAction SilentlyContinue; python -m pytest -q`，期望全部测试通过且没有外部网络或危险命令日志）。
- [ ] **AC31：** Python 3.11+ 下新旧测试全部通过（验证：运行 `python -c "import sys; assert sys.version_info >= (3, 11); print(sys.version)"` 后运行 `python -m pytest -q`，期望版本断言和完整测试均成功）。

## 架构与集成检查

- [ ] Agent 模块不依赖 REPL 或 CLI（验证：运行 `rg -n "mewcode\.(repl|cli)|from \.\.?repl|from \.\.?cli" src/mewcode/agent`，期望无匹配）。
- [ ] Provider 与 Agent 之间只交换归一化事件和消息转换结果（验证：运行 `python -m pytest tests/test_stream_collector.py tests/test_providers.py tests/test_tool_providers.py -q`，期望边界测试全部通过）。
- [ ] Plan Mode 的只读限制同时作用于工具定义和注册中心执行（验证：运行 `python -m pytest tests/test_tools_base.py tests/test_plan_mode.py -q -k "select or readonly"`，期望副作用工具既不导出也无法从视图执行）。
- [ ] 每个完整工具响应在历史中都有同批全部结果，没有悬空调用（验证：运行 `python -m pytest tests/test_agent_runner.py -q -k atomic_history`，期望所有完成、失败和取消场景的调用/结果数量与 ID 配对）。
- [ ] 配置文件格式和六个工具的名称、参数 Schema 保持兼容（验证：运行 `python -m pytest tests/test_config.py tests/test_tools_base.py -q`，期望现有配置和工具定义回归测试通过）。

## 编译与质量检查

- [ ] 源码和测试无语法或导入错误（验证：运行 `python -m compileall -q src tests`，期望命令以 0 退出且无输出）。
- [ ] 所有单元与集成测试通过（验证：运行 `python -m pytest -q`，期望零失败）。
- [ ] 代码改动无空白错误（验证：运行 `git diff --check`，期望命令以 0 退出且无输出）。
- [ ] 本章没有引入新运行时依赖或配置字段（验证：运行 `git diff -- pyproject.toml examples/config.yaml`，期望无差异）。
- [ ] 用户文档不再宣称每轮最多一次工具，并包含 Agent Loop、`/plan`、`/do`、`Ctrl+C` 和 20 次上限（验证：运行 `rg -n "Agent Loop|/plan|/do|Ctrl\+C|20" README.md` 并运行 `rg -n "最多执行一次工具|一次工具调用上限" README.md`，期望前者覆盖全部主题、后者无匹配）。

> 项目当前没有独立 lint 配置；本阶段以 `compileall`、完整 pytest 和 `git diff --check` 作为静态质量门槛。

## 端到端场景

- [ ] 直接任务：模型读取文件、修改文件、运行验证命令并给出最终总结，全程无需用户追加提示（验证：运行 `python -m pytest tests/test_tool_conversation.py -q -k end_to_end_direct`，期望工具按 ReAct 多轮执行、文件结果正确且停止原因为 `COMPLETED`）。
- [ ] 两阶段任务：`/plan <任务>` 只读取并生成计划，`/do` 再写入和运行命令，成功后计划被清除（验证：运行 `python -m pytest tests/test_plan_mode.py tests/test_repl.py -q -k end_to_end`，期望规划阶段无副作用、执行阶段完成且第二次 `/do` 不调用模型）。
- [ ] 取消场景：长任务执行期间触发 `Ctrl+C`，2 秒内回到提示符并成功处理下一条聊天消息（验证：运行 `python -m pytest tests/test_repl.py -q -k end_to_end_cancel`，期望无后续工具启动、无后台任务警告且会话继续）。
- [ ] 安全网场景：脚本模型持续请求工具，分别在第 20 次迭代和连续第 3 次未知工具时停止（验证：运行 `python -m pytest tests/test_agent_runner.py -q -k "iteration_limit or unknown_tool_limit"`，期望两个停止原因、调用次数和未执行工具断言全部正确）。
