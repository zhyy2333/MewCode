# MewCode Plan Mode Finalization Fix Tasks

## 实施原则

- 按任务顺序实施；每个任务通过自身验证后再进入下一项。
- 修改前检查工作树，保留现有 `repl.py`、`tests/test_repl.py` 和其他用户未提交内容。
- 只使用 Fake Provider 和本地工具测试，不调用真实 API、不读取真实密钥。
- 当前轮被截断、取消或流失败时，不提交该轮不完整响应或隐藏续传片段。
- 不自动执行 `git add`、`git commit`、`git push`、回滚或清理用户文件。

## T1：建立三态 thinking 配置模型

**目标：** 让配置层稳定输出 `auto / enabled / disabled`，并保持旧配置兼容。

**涉及文件：**

- `src/mewcode/providers/base.py`
- `src/mewcode/providers/__init__.py`
- `src/mewcode/config.py`
- `tests/test_config.py`

**实施内容：**

1. 定义并导出 `ThinkingMode`。
2. 将 `ProviderProfile.thinking` 改为规范化的 `ThinkingMode`。
3. 实现 `_parse_thinking_mode()`：
   - 缺省 -> `AUTO`；
   - `true` -> `ENABLED`；
   - `false` -> `DISABLED`；
   - 三态字符串按值解析；
   - 其他类型和值抛出 `ConfigError`。
4. 更新配置测试，覆盖三态、布尔兼容、缺省值和非法输入。

**完成条件：** Provider 构造前不存在未经规范化的 thinking 配置。

**验证：**

```powershell
python -m pytest tests/test_config.py
```

## T2：扩展 Provider 响应与调用契约

**目标：** 让每个完整模型响应携带规范化结束原因和不可公开的内部续传片段。

**依赖：** T1。

**涉及文件：**

- `src/mewcode/providers/base.py`
- `src/mewcode/providers/__init__.py`
- `tests/fakes.py`
- `tests/test_stream_collector.py`

**实施内容：**

1. 定义并导出 `ProviderFinishReason`、`ProviderFinished`、`ProviderInternalPart`。
2. 将新事件加入 `ProviderEvent`。
3. 为 `ModelResponse` 增加 `finish_reason` 与 `internal_parts`。
4. 为 `LLMProvider.stream_reply()` 增加关键字参数 `max_output_tokens`。
5. 更新 `ScriptedAsyncProvider`：记录每次输出上限，并让测试脚本明确或自动生成合法结束事件。
6. 更新 StreamCollector 测试脚本，为后续严格结束事件校验准备基线。

**完成条件：** Fake Provider 能表达自然结束、工具结束、输出截断和隐藏内部片段。

**验证：**

```powershell
python -m pytest tests/test_stream_collector.py tests/test_agent_runner.py -q
```

## T3：实现 StreamCollector 的结束原因与隐藏片段收集

**目标：** 保持公共流实时输出，同时形成带完整内部状态的 `ModelResponse`。

**依赖：** T2。

**涉及文件：**

- `src/mewcode/agent/streaming.py`
- `tests/test_stream_collector.py`

**实施内容：**

1. 收集文本、工具调用、用量、唯一结束原因和内部片段。
2. `ProviderInternalPart` 只写入 `ModelResponse`，不 yield 任何 `AgentEvent`。
3. 检查缺失、重复或冲突的结束事件，失败时不允许读取 `response`。
4. 保持正文、工具和用量事件的现有实时顺序。
5. 增加测试证明隐藏内容不会出现在公共事件中。

**完成条件：** 完整流必定产生带结束原因的 `ModelResponse`，失败流不产生可提交响应。

**验证：**

```powershell
python -m pytest tests/test_stream_collector.py
```

## T4：修复 Anthropic 与 DeepSeek 兼容请求

**目标：** 明确表达三态 thinking，解析结束原因，并支持思考工具循环的内部续传。

**依赖：** T1-T3。

**涉及文件：**

- `src/mewcode/providers/anthropic_provider.py`
- `tests/test_providers.py`
- `tests/test_tool_providers.py`

**实施内容：**

1. 使用调用参数设置 `max_tokens`。
2. 按三态构造 thinking 参数：
   - `AUTO`：省略；
   - `ENABLED`：adaptive，明确不支持时回退 manual；
   - `DISABLED`：发送 `{"type": "disabled"}`。
3. 从 Anthropic 流的 `stop_reason` 映射自然结束、工具结束和输出上限。
4. 收集 thinking、signature 和 redacted thinking 内容块，块完整结束后产出内部片段。
5. 在 `assistant_messages()` 中按原顺序回写内部片段和工具调用。
6. 未知终止状态和不支持的显式 thinking 状态返回脱敏 `ProviderError`。
7. 补充 DeepSeek Anthropic 兼容场景的离线请求断言。

**完成条件：** `thinking: false` 兼容配置会明确关闭思考；启用思考的工具回合能续传内部内容且不公开显示。

**验证：**

```powershell
python -m pytest tests/test_providers.py tests/test_tool_providers.py -k anthropic
```

## T5：补齐 OpenAI Provider 的等价语义

**目标：** OpenAI Responses API 与 Anthropic 对上层提供一致的结束、预算和隐藏续传语义。

**依赖：** T1-T3。

**涉及文件：**

- `src/mewcode/providers/openai_provider.py`
- `tests/test_providers.py`
- `tests/test_tool_providers.py`

**实施内容：**

1. 使用调用参数设置 `max_output_tokens`。
2. 按三态构造 reasoning 参数：
   - `AUTO`：省略；
   - `ENABLED`：`effort=medium`；
   - `DISABLED`：`effort=none`。
3. 对不支持显式状态的模型保留并脱敏包装 API 错误，不静默降级。
4. 将 completed 映射为自然结束或工具结束。
5. 将 `max_output_tokens` 导致的 incomplete 映射为输出上限；其他 incomplete、failed 和 error 转为 `ProviderError`。
6. 收集完成的 reasoning output item，并在后续 input 中原样回传。
7. 增加隐藏 reasoning item 不进入公共事件的测试。

**完成条件：** 两种 Provider 在 Agent 层呈现等价的自然结束、工具结束、输出截断和流错误。

**验证：**

```powershell
python -m pytest tests/test_providers.py tests/test_tool_providers.py -k openai
```

## T6：修复 Direct 与 Execute 的完成判断

**目标：** 防止无工具但空白或截断的响应被误判为完成。

**依赖：** T2-T5。

**涉及文件：**

- `src/mewcode/agent/events.py`
- `src/mewcode/agent/runner.py`
- `src/mewcode/agent/__init__.py`
- `tests/test_agent_runner.py`
- `tests/test_tool_conversation.py`

**实施内容：**

1. 增加 `StopReason.OUTPUT_LIMIT` 和 `StopReason.EMPTY_RESPONSE`。
2. 每轮调用显式传入普通预算 4096。
3. 自然结束且正文非空才完成并提交当前 assistant 消息。
4. 自然空白以 `EMPTY_RESPONSE` 停止，不提交当前响应。
5. 输出截断以 `OUTPUT_LIMIT` 停止，不提交当前响应。
6. 工具结束才进入工具调度；结束原因与实际工具调用冲突时以内部错误停止。
7. 保持迭代上限、取消、流错误、未知工具限制和成对历史的原有语义。

**完成条件：** Direct/Execute 不再把空响应或 Token 截断显示为 `completed`。

**验证：**

```powershell
python -m pytest tests/test_agent_runner.py tests/test_tool_conversation.py
```

## T7：实现 Plan 两阶段状态机

**目标：** 让 `/plan` 在有限调查后必定进入一次独立的最终计划输出。

**依赖：** T6。

**涉及文件：**

- `src/mewcode/agent/runner.py`
- `src/mewcode/conversation.py`
- `tests/test_plan_mode.py`

**实施内容：**

1. 为 `AgentRunConfig` 增加内部 Plan 调查轮数和最终预算，并校验正整数。
2. Plan 调查最多执行 6 次 Provider 调用，每次只使用传入的只读工具和 4096 上限。
3. 调查自然结束时提交完整调查响应到工作上下文，并进入最终阶段。
4. 第 6 轮工具调用执行和回写完成后进入最终阶段，不发起第 7 轮调查。
5. 在工作上下文中追加明确的最终计划输出指令。
6. 最终阶段恰好调用一次 Provider，传入 `tools=None` 和 8192 上限。
7. 最终自然非空正文完成；空白、截断、错误、取消或违规工具调用均失败。
8. 保证两阶段共用 run id、累计用量、事件序列和取消入口。
9. 补充提前结束、6 轮封顶、最终调用参数和异常路径测试。

**完成条件：** 无论调查提前结束还是达到上限，成功路径都有且只有一次无工具最终输出调用。

**验证：**

```powershell
python -m pytest tests/test_plan_mode.py tests/test_agent_runner.py
```

## T8：收紧计划保存边界并更新示例输出

**目标：** 只保存完整最终计划，并让新增停止原因对用户可观察。

**依赖：** T7。

**涉及文件：**

- `src/mewcode/conversation.py`
- `src/mewcode/repl.py`（仅在必要时最小修改）
- `examples/config.yaml`
- `tests/test_plan_mode.py`
- `tests/test_repl.py`

**实施内容：**

1. 保存前同时检查 `completed` 和非空最终正文。
2. 新 Plan 失败时保留已有 `PendingPlan`，首次失败时保持为空。
3. 验证 `output_limit`、`empty_response`、stream error 和 cancelled 的 REPL 停止输出。
4. 保留现有 REPL 缩进和空行层级，不重构 `_EventRenderer`。
5. 将示例配置改为三态字符串，并注明旧布尔值兼容。

**完成条件：** 用户能够区分完成、截断和空响应，且失败不会覆盖可重试的旧计划。

**验证：**

```powershell
python -m pytest tests/test_plan_mode.py tests/test_repl.py tests/test_config.py
```

## T9：执行跨 Provider 与端到端回归

**目标：** 验证本次修复满足全部验收标准且不破坏现有 Agent Loop。

**依赖：** T1-T8。

**涉及文件：** 全部本次修改和测试文件。

**实施内容：**

1. 运行 Provider、Collector、Runner、Plan 和 REPL 聚焦测试。
2. 运行完整测试套件。
3. 检查端到端 `/plan -> /do`：调查只读、最终无工具、执行阶段全工具、成功后清除计划。
4. 检查测试未访问真实网络、未读取真实密钥、未遗留异步任务。
5. 检查 `git diff`，确认未覆盖用户已有 REPL 输出层级改动，也未包含缓存文件或无关修改。
6. 对照 spec 的 AC1-AC10 记录 checklist 结果。

**完成条件：** 所有自动化检查通过，工作树中只有预期源码、测试、示例和文档改动。

**验证：**

```powershell
python -m pytest
```

