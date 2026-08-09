# MewCode Plan Mode Finalization Fix Checklist

## 配置与请求语义

- [x] AC1：`thinking: auto/enabled/disabled` 均可加载并映射为对应 `ThinkingMode`。（验证：`python -m pytest tests/test_config.py -k thinking`）
- [x] AC1：旧值 `thinking: true/false` 分别兼容为 `enabled/disabled`，字段缺失为 `auto`。（验证：`python -m pytest tests/test_config.py -k thinking`）
- [x] AC1：非法 thinking 类型和值返回包含合法选项的 `ConfigError`。（验证：`python -m pytest tests/test_config.py -k thinking`）
- [x] AC2：Anthropic/DeepSeek 兼容请求在 `disabled` 时包含 `thinking={"type": "disabled"}`，而不是省略字段。（验证：`python -m pytest tests/test_providers.py -k "anthropic and thinking"`）
- [x] 显式 `enabled/disabled` 不受支持时返回脱敏 Provider 错误，不静默切换为 `auto`。（验证：`python -m pytest tests/test_providers.py -k thinking`）

## Provider 结束原因

- [x] AC3：Anthropic `end_turn/stop_sequence`、`tool_use`、`max_tokens` 分别映射为自然结束、工具结束和输出上限。（验证：`python -m pytest tests/test_providers.py -k anthropic`）
- [x] AC9：OpenAI completed、max-output incomplete 和 failed/error 分别映射为自然或工具结束、输出上限和 Provider 错误。（验证：`python -m pytest tests/test_providers.py -k openai`）
- [x] AC9：Provider 的每个成功流都产生唯一结束事件，缺失或重复结束事件不能形成可提交响应。（验证：`python -m pytest tests/test_stream_collector.py`）
- [x] 两个 Provider 都使用每次调用传入的输出 Token 上限，不在 Provider 内固定覆盖。（验证：`python -m pytest tests/test_providers.py -k max`）

## 隐藏续传与公共事件边界

- [x] AC4：Anthropic thinking、signature 和 redacted thinking 块能完整进入后续工具回合 assistant 消息。（验证：`python -m pytest tests/test_tool_providers.py -k anthropic`）
- [x] AC4：OpenAI reasoning output item 能进入后续 Responses API input。（验证：`python -m pytest tests/test_tool_providers.py -k openai`）
- [x] AC4：`ProviderInternalPart` 不产生 `AgentTextDelta`、工具、进度或其他公共事件。（验证：`python -m pytest tests/test_stream_collector.py -k internal`）
- [x] 隐藏片段字段默认 `repr` 不暴露内容，错误信息和 REPL 输出中不存在测试用隐藏文本。（验证：`python -m pytest tests/test_stream_collector.py tests/test_repl.py -k "internal or hidden or reasoning or thinking"`）
- [x] 流错误、取消和输出截断不会提交当前轮的不完整隐藏片段。（验证：`python -m pytest tests/test_agent_runner.py -k "stream_error or cancel or output_limit"`）

## Agent 完成与停止语义

- [x] AC3：无工具但达到输出上限的响应以 `StopReason.OUTPUT_LIMIT` 停止，不标记 completed。（验证：`python -m pytest tests/test_agent_runner.py -k output_limit`）
- [x] AC3：输出上限响应的当前轮正文和 assistant 消息不提交到历史。（验证：`python -m pytest tests/test_agent_runner.py -k output_limit`）
- [x] 自然结束但正文为空或仅空白时以 `StopReason.EMPTY_RESPONSE` 停止。（验证：`python -m pytest tests/test_agent_runner.py -k empty_response`）
- [x] 正常非空文本仍会实时输出、提交历史并以 completed 结束。（验证：`python -m pytest tests/test_agent_runner.py -k text_only`）
- [x] 迭代上限、连续未知工具、流错误、内部错误和取消的既有行为保持通过。（验证：`python -m pytest tests/test_agent_runner.py`）
- [x] 多工具并发/串行调度和取消后的工具结果成对历史保持通过。（验证：`python -m pytest tests/test_tool_scheduler.py tests/test_agent_runner.py`）

## Plan 两阶段流程

- [x] AC8：Plan 调查阶段只暴露 `read_file`、`find_files`、`search_code`。（验证：`python -m pytest tests/test_plan_mode.py -k readonly`）
- [x] AC6：调查第 1 轮自然结束时仍会追加一次无工具最终调用。（验证：`python -m pytest tests/test_plan_mode.py -k early`）
- [x] AC5：连续产生工具调用时最多执行 6 轮调查，然后停止调查。（验证：`python -m pytest tests/test_plan_mode.py -k investigation_limit`）
- [x] AC5：第 6 轮的只读工具调用及结果会执行和回写。（验证：`python -m pytest tests/test_plan_mode.py -k sixth`）
- [x] AC5：调查结束后恰好执行一次最终模型调用，不会重复 finalization。（验证：`python -m pytest tests/test_plan_mode.py -k finalization`）
- [x] AC7-AC8：最终调用传入 `tools=None` 和 `max_output_tokens=8192`。（验证：`python -m pytest tests/test_plan_mode.py -k finalization`）
- [x] 最终阶段若违规返回工具调用，不执行该工具并以错误停止。（验证：`python -m pytest tests/test_plan_mode.py -k unexpected_tool`）
- [x] 两阶段使用同一 run id，Token 用量累计包含调查和最终调用。（验证：`python -m pytest tests/test_plan_mode.py -k cumulative`）
- [x] 调查阶段输出上限、流错误、取消或未知工具达到限制时立即停止，不进入最终调用。（验证：`python -m pytest tests/test_plan_mode.py -k "output_limit or error or cancel or unknown"`）

## 待执行计划保存边界

- [x] AC6：最终调用自然结束且正文非空时保存任务和完整计划正文。（验证：`python -m pytest tests/test_plan_mode.py -k saves`）
- [x] AC7：最终输出为空时不创建新计划，也不覆盖已有计划。（验证：`python -m pytest tests/test_plan_mode.py -k empty`）
- [x] AC7：最终输出截断时不创建新计划，也不覆盖已有计划。（验证：`python -m pytest tests/test_plan_mode.py -k output_limit`）
- [x] AC7：最终流错误和取消时保留已有待执行计划。（验证：`python -m pytest tests/test_plan_mode.py -k "failure or cancel"`）
- [x] `/do` 只使用成功保存的最终计划，执行成功后清除，失败后保留重试。（验证：`python -m pytest tests/test_plan_mode.py -k execute`）

## REPL、兼容性与端到端

- [x] `output_limit` 和 `empty_response` 在 REPL 中显示为明确 stopped 原因，而不是 completed。（验证：`python -m pytest tests/test_repl.py -k stopped`）
- [x] 当前 REPL 文本、工具、Token 和迭代层级测试保持通过，未覆盖用户已有修改。（验证：`python -m pytest tests/test_repl.py`）
- [x] AC10：端到端 `/plan -> /do` 完成只读调查、最终无工具输出、全工具执行、验证并清除计划。（验证：`python -m pytest tests/test_plan_mode.py -k end_to_end`）
- [x] 普通聊天、工具会话、文件工具、搜索工具和命令工具测试无回归。（验证：`python -m pytest tests/test_conversation.py tests/test_tool_conversation.py tests/test_file_tools.py tests/test_search_tools.py tests/test_command_tool.py`）
- [x] AC10：完整测试套件通过。（验证：`python -m pytest`）
- [x] AC10：测试使用 Fake Provider 和临时目录，不需要网络或真实 API Key。（验证：检查测试实现并运行完整测试）
- [x] 完整测试结束后没有未关闭流或遗留异步任务警告。（验证：`python -m pytest -W error`，若第三方库存在既有非本功能警告则记录并单独判定）

## 工作树与交付检查

- [x] `git diff` 中保留修改前已有的 REPL 输出层级工作，没有回滚用户内容。
- [ ] 未修改或提交 `__pycache__`、密钥、用户配置及其他无关文件。
  - 说明：仓库在实施前已有被追踪且已修改的 `__pycache__`；测试运行又更新了这些生成文件。为遵守“不回滚用户未提交改动”，本次未擅自恢复或删除它们，也未暂存或提交它们。
- [x] `docs/phase-3-plan-finalization/` 包含已审批的 `spec.md`、`plan.md`、`task.md`、`checklist.md`。
- [x] 对照 AC1-AC10 全部通过后才宣布修复完成。
- [x] 未执行自动 Git 暂存、提交或推送。
