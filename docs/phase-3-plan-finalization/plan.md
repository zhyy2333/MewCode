# MewCode Plan Mode Finalization Fix Plan

## 架构概览

本次修复沿用现有 `Config -> Provider -> StreamCollector -> AgentRun -> Conversation -> REPL` 分层，不新增独立服务或后台任务。改动集中在响应契约、Plan 两阶段状态机和保存边界三处。

### 配置层

`thinking` 从布尔值升级为三态配置：

- `auto`：请求中省略思考控制参数，使用 Provider 或模型默认行为。
- `enabled`：请求中明确开启思考。
- `disabled`：请求中明确关闭思考。

配置解析继续接受旧布尔值，`true` 映射为 `enabled`，`false` 映射为 `disabled`；字段缺失映射为 `auto`。解析完成后，Provider 只接收规范化后的 `ThinkingMode`，不再自行解释原始 YAML 值。

### Provider 层

Provider 流新增两类仅供内部消费的事件：响应结束原因和 Provider 私有续传片段。完整响应由以下五部分组成：

1. 可见文本；
2. 工具调用；
3. Token 用量；
4. 规范化结束原因；
5. 不可见的 Provider 私有续传数据。

生产 Provider 必须显式生成结束原因。自然结束、工具调用结束和输出额度耗尽分别归一化为统一枚举；请求失败继续抛出脱敏后的 `ProviderError`，由 Agent 映射为流错误。

`stream_reply()` 增加单次调用的 `max_output_tokens` 参数，使普通循环继续使用 4096，而 Plan 最终输出能够独立使用 8192。`tools=None` 表示请求中完全不提供工具定义。

### 流式收集层

`StreamCollector` 继续承担双路收集：可见文本和工具调用实时转成公共 Agent 事件，同时累计完整 `ModelResponse`。

结束原因和 Provider 私有续传片段只进入 `ModelResponse`，不会转换成 `AgentTextDelta`、进度消息或日志内容。流中断时，当前轮尚未形成完整响应，因此其正文、结束原因和私有片段均不提交到历史。

### Agent 运行层

Direct 和 Execute 模式继续走现有单阶段 Agent Loop，但完成判断从“没有工具调用”改为“结束原因为自然结束且正文非空”。新增两个停止原因：

- `output_limit`：模型达到输出上限；
- `empty_response`：模型自然结束但没有非空正文。

Plan 模式在同一个 `AgentRun` 内执行两阶段状态机：

1. 调查阶段最多 6 轮，每轮提供只读工具，单轮输出上限为 4096；
2. 调查自然结束或第 6 轮工具执行结束后，追加内部最终输出指令；
3. 最终阶段恰好调用模型一次，不提供任何工具，输出上限为 8192；
4. 只有最终阶段自然结束且正文非空时，整个运行才标记为 `completed`。

取消、流错误、连续未知工具和输出上限会立即终止，不再进入最终阶段。调查第 6 轮返回的合法工具调用仍会执行，随后再进入最终阶段，确保“最多 6 轮调查”包含第 6 轮调查结果。

### Conversation 与界面层

`Conversation.plan()` 仍先筛选三个只读工具，再启动 `AgentMode.PLAN`。只有 `completed` 且最终正文非空时才原子替换 `_pending_plan`；其他停止原因均保留原计划。

REPL 继续只消费公共 Agent 事件。现有通用停止原因渲染可直接显示 `output_limit` 和 `empty_response`，无需展示隐藏续传数据，也不改变当前尚未提交的输出层级实现。

## 核心数据结构与接口

### 思考模式

在 `providers/base.py` 中定义：

```python
class ThinkingMode(StrEnum):
    AUTO = "auto"
    ENABLED = "enabled"
    DISABLED = "disabled"
```

`RawProviderProfile.thinking` 表达可接受的原始兼容类型，`ProviderProfile.thinking` 固定为 `ThinkingMode`。`config.py` 负责完成布尔值、字符串和缺省值的规范化，并拒绝其他值。

### Provider 结束原因

```python
class ProviderFinishReason(StrEnum):
    NATURAL = "natural"
    TOOL_CALLS = "tool_calls"
    OUTPUT_LIMIT = "output_limit"


@dataclass(frozen=True)
class ProviderFinished:
    reason: ProviderFinishReason
```

`ProviderFinishReason` 只表示成功收到并解析完的模型响应。网络错误、SDK 错误、服务端失败和无法识别的终止状态统一抛出 `ProviderError`，避免把异常伪装成正常响应。

### Provider 私有续传片段

```python
@dataclass(frozen=True)
class ProviderInternalPart:
    data: Any = field(repr=False)
```

该对象保存 Provider 后续请求要求原样回传、但不能公开展示的结构化内容。它是 `ProviderEvent` 的成员，却不是 `AgentEvent` 的成员。字段关闭默认 `repr`，降低意外进入错误信息或调试输出的风险。

### 完整模型响应

```python
@dataclass(frozen=True)
class ModelResponse:
    text: str
    tool_calls: tuple[ToolCallRequest, ...]
    usage: TokenUsage
    finish_reason: ProviderFinishReason
    internal_parts: tuple[ProviderInternalPart, ...] = ()
```

`assistant_messages()` 由具体 Provider 使用 `internal_parts` 重建下一轮所需的 assistant 消息。公共会话正文仍只使用 `text`。

### Provider 调用接口

```python
def stream_reply(
    self,
    messages: list[ChatMessage],
    tools: list[dict[str, Any]] | None = None,
    *,
    max_output_tokens: int = DEFAULT_MAX_TOKENS,
) -> AsyncIterator[ProviderEvent]: ...
```

上限由 Agent 每次调用显式传入。Provider 不根据 Agent 模式自行猜测预算，也不负责 Plan 阶段切换。

### Agent 配置与停止原因

`AgentRunConfig` 增加内部运行参数：

```python
plan_max_investigation_iterations: int = 6
plan_final_max_tokens: int = 8192
```

这些参数用于测试和内部策略，不加入用户 YAML 配置。`StopReason` 增加 `OUTPUT_LIMIT` 与 `EMPTY_RESPONSE`；`AgentRunOutcome.completed` 仍只对 `COMPLETED` 返回真。

## 模块设计

### `src/mewcode/config.py`

- 新增 `_parse_thinking_mode()`，集中处理缺省、布尔兼容和三态字符串。
- 缺省值改为 `ThinkingMode.AUTO`。
- 错误信息列出合法值和兼容布尔值。
- 不改变 API Key 解析、协议选择和其他字段校验。

### `src/mewcode/providers/base.py`

- 定义 `ThinkingMode`、`ProviderFinishReason`、`ProviderFinished` 和 `ProviderInternalPart`。
- 扩展 `ProviderEvent`、`ModelResponse` 与 `LLMProvider.stream_reply()` 契约。
- 保持 `TokenUsage`、工具消息转换和 Provider 工厂职责不变。

### `src/mewcode/providers/anthropic_provider.py`

- `auto` 不发送 `thinking`。
- `enabled` 先发送 adaptive thinking；仅在明确不支持 adaptive 时回退一次 manual thinking。
- `disabled` 明确发送 `{"type": "disabled"}`，不再省略参数。
- 使用调用参数设置 `max_tokens`。
- 从 `message_delta.stop_reason` 解析自然结束、工具结束和 `max_tokens`。
- 收集 `thinking`、签名和 `redacted_thinking` 内容块，在块结束时产出 `ProviderInternalPart`。
- `assistant_messages()` 按 Provider 要求把内部片段放回工具调用所在 assistant 内容中，但不把它们转成普通文本。
- 未知终止原因和不受支持的显式思考状态转为脱敏 `ProviderError`。

### `src/mewcode/providers/openai_provider.py`

- `auto` 不发送 `reasoning` 参数。
- `enabled` 发送 `reasoning={"effort": "medium"}`。
- `disabled` 发送 `reasoning={"effort": "none"}`；模型不支持时保留 SDK 错误并脱敏包装，不静默回退。
- 使用调用参数设置 `max_output_tokens`。
- `response.completed` 按已收集工具调用归一化为自然结束或工具结束。
- `response.incomplete` 且原因为 `max_output_tokens` 时产出输出上限结束原因；其他 incomplete、failed 和 error 事件抛出 `ProviderError`。
- 收集已完成的 reasoning output item 作为 `ProviderInternalPart`，后续请求通过 Responses API input 原样回传。

### `src/mewcode/agent/streaming.py`

- 收集唯一的 `ProviderFinished`；缺失、重复或自相矛盾的结束事件视为状态错误。
- 收集 `ProviderInternalPart`，但不向调用者 yield。
- 完成后构造包含结束原因和内部片段的 `ModelResponse`。
- 保留可见文本、工具调用和 Token 用量的实时事件顺序。

### `src/mewcode/agent/events.py`

- 为 `StopReason` 增加 `OUTPUT_LIMIT` 和 `EMPTY_RESPONSE`。
- 不新增公开的 thinking/reasoning 事件类型。
- 现有 `AgentStopped` 继续携带最终停止原因和脱敏错误。

### `src/mewcode/agent/runner.py`

- 将单轮模型调用、响应提交、工具批次执行和停止处理拆成私有辅助逻辑，避免 Direct/Execute 与 Plan 复制完整循环。
- Direct/Execute 根据 `finish_reason` 决策，不再以工具列表是否为空作为唯一完成条件。
- 当前轮为 `OUTPUT_LIMIT` 时不调用 `assistant_messages()`，从而不提交截断正文或不完整内部片段。
- 自然结束但 `text.strip()` 为空时以 `EMPTY_RESPONSE` 停止。
- Plan 调查阶段限制为 6 轮；合法第 6 轮工具调用执行完成后进入最终阶段。
- 调查自然结束时把该轮完整响应加入工作上下文，再追加最终输出指令。
- 最终阶段调用 `tools=None` 和 `max_output_tokens=8192`，不调度任何工具。
- 最终阶段出现工具调用视为 Provider 协议错误并以 `ERROR` 停止；自然非空正文才提交并完成。
- 继续保持取消原子性、工具结果成对提交、连续未知工具限制和累计 Token 用量。

### `src/mewcode/conversation.py`

- 增加仅供 Plan 最终阶段使用的明确输出指令文本。
- 保持调查阶段原始任务提示和只读工具选择。
- 保存前同时检查 `outcome.completed` 与非空 `final_text`，并用最终正文原子替换待执行计划。
- 失败、取消、输出上限和空响应都不修改已有 `_pending_plan`。

### 包出口、示例和 REPL

- `providers/__init__.py` 导出新增 Provider 类型，供测试和 Agent 层使用。
- `agent/__init__.py` 继续导出新增枚举成员所在的既有类型，不增加隐藏数据出口到 REPL。
- `examples/config.yaml` 改用三态字符串展示推荐写法，并说明布尔值仍兼容。
- `repl.py` 原则上不改业务逻辑；其通用 stopped 渲染会自然显示新增停止原因。若测试暴露格式问题，只做与新增原因直接相关的最小调整。

### 测试模块

- `tests/fakes.py` 更新 Provider 协议，脚本可表达结束原因、内部片段和每次输出上限。
- `tests/test_config.py` 覆盖三态、布尔兼容、缺省和非法值。
- `tests/test_providers.py` 覆盖思考参数映射、结束原因、输出预算、错误脱敏。
- `tests/test_tool_providers.py` 覆盖 Anthropic/OpenAI 私有续传片段的收集和回写。
- `tests/test_stream_collector.py` 验证私有片段不产生公共事件，以及结束事件完整性。
- `tests/test_agent_runner.py` 覆盖输出上限、空响应、响应提交边界及现有停止条件回归。
- `tests/test_plan_mode.py` 覆盖提前结束、6 轮封顶、一次最终调用、8192 上限、无工具、失败保留旧计划和端到端 `/plan -> /do`。
- `tests/test_repl.py` 只补充新增停止原因的可观察输出，不改动已有输出层级断言。

## 模块交互

### 普通 Agent Loop

```text
Conversation.ask / execute_plan
  -> AgentRunner.start(mode=direct|execute)
  -> AgentRun 调用 provider.stream_reply(..., max_output_tokens=4096)
  -> StreamCollector
       -> 可见文本/工具/用量实时发送 AgentEvent
       -> 结束原因/私有片段仅写入 ModelResponse
  -> AgentRun 检查 finish_reason
       -> natural + 非空文本：提交并 completed
       -> natural + 空文本：empty_response
       -> output_limit：不提交当前响应，output_limit
       -> tool_calls：提交完整 assistant/tool 消息并继续循环
```

### Plan 两阶段流程

```text
/plan <task>
  -> Conversation 选择 READ_ONLY 工具
  -> 调查第 1..6 轮（4096 tokens，允许只读工具）
       -> tool_calls：执行并回写；未触发其他停止条件则继续
       -> natural：结束调查
       -> output_limit/error/cancel/unknown limit：立即停止
  -> 追加“仅输出最终完整计划”的内部用户指令
  -> 最终第 N+1 轮（8192 tokens，tools=None）
       -> natural + 非空正文：completed，保存 PendingPlan
       -> empty/output_limit/error/cancel：停止，PendingPlan 保持原状
```

最终轮与调查轮共用同一个 `run_id`、事件流、累计用量和取消入口，因此 Conversation 与 REPL 不需要协调两个独立运行对象。

### 隐藏续传数据

```text
Provider stream
  -> thinking/reasoning 结构化片段
  -> ProviderInternalPart(repr=False)
  -> StreamCollector.internal_parts
  -> ModelResponse.internal_parts
  -> provider.assistant_messages(response)
  -> 下一轮 Provider 请求

不会进入：AgentTextDelta / AgentProgress / REPL / 普通错误文本
```

仅当本轮响应完整结束并需要继续工具循环时，内部片段才随 assistant 消息提交。流错误、取消或输出上限不会提交当前轮片段。

### 停止原因映射

| Provider/运行状态 | Agent 停止原因 | 提交当前响应 | 保存新计划 |
|---|---|---:|---:|
| 自然结束且正文非空 | `completed` | 是 | 仅 Plan 最终轮是 |
| 自然结束但正文为空 | `empty_response` | 否 | 否 |
| 输出额度耗尽 | `output_limit` | 否 | 否 |
| Provider/流异常 | `stream_error` | 否 | 否 |
| 用户取消 | `cancelled` | 否；已完成工具批次保持成对历史 | 否 |
| 连续未知工具达到上限 | `unknown_tool_limit` | 已完成轮保持 | 否 |
| 普通模式迭代达到上限 | `iteration_limit` | 不执行最后一轮工具调用 | 否 |
| Plan 最终轮违规返回工具调用 | `error` | 否 | 否 |

## 需求归属

| 需求 | 主要实现位置 |
|---|---|
| F1-F2 / AC1-AC2 | `config.py`、Provider profile、Anthropic/OpenAI 请求构造 |
| F3-F4 / AC3、AC9 | Provider 结束事件、`StreamCollector`、`AgentRun` 停止映射 |
| F5 / AC4 | Provider 私有片段、assistant 消息重建、隐藏事件边界 |
| F6-F7 / AC5-AC6 | `AgentRun` Plan 两阶段状态机和单次调用预算 |
| F8 / AC7 | Runner 完成条件、Conversation 原子保存 |
| F9 / AC8 | Conversation 只读 Registry、最终轮 `tools=None` |
| N1-N2 | Provider 归一化契约和公共事件白名单 |
| N3 | 对 `repl.py` 的最小改动策略与已有测试保护 |
| N4-N5 / AC10 | Fake Provider、单元/集成/端到端回归测试 |

## 文件组织

```text
docs/phase-3-plan-finalization/
  spec.md
  plan.md
  task.md                 # task 阶段生成
  checklist.md            # checklist 阶段生成

src/mewcode/
  config.py
  conversation.py
  providers/
    __init__.py
    base.py
    anthropic_provider.py
    openai_provider.py
  agent/
    events.py
    streaming.py
    runner.py
  repl.py                  # 原则上仅验证，不主动重构

examples/
  config.yaml

tests/
  fakes.py
  test_config.py
  test_providers.py
  test_tool_providers.py
  test_stream_collector.py
  test_agent_runner.py
  test_plan_mode.py
  test_repl.py
```

## 技术决策

### 使用显式结束事件，而非用 Token 数量猜测

输出 Token 数恰好等于请求上限只是故障线索，不能稳定区分自然结束和截断。Provider 解析协议原生结束字段并输出统一原因，Agent 不依赖模型名称或用量启发式。

### Provider 私有片段保留结构，不转换成思维链文本

工具续传需要协议原始结构和签名。把它转成字符串既可能破坏签名，也会增加泄漏风险，因此使用 `repr=False` 的不透明结构，只允许 Provider 自己重建后续请求。

### Plan 最终输出仍属于同一个 AgentRun

单个运行对象能够复用取消、事件顺序、累计用量和历史提交边界；如果拆成两个 Conversation 运行，界面必须拼接两个 run，取消与旧计划保留也更容易出现竞态。

### 调查第 6 轮工具仍执行

“最多 6 轮调查”按模型调查调用计数。第 6 轮返回的只读工具结果属于该轮调查证据，应在进入最终输出前完成；这与普通模式迭代上限不执行最后工具调用的安全兜底语义分开处理。

### 显式思考状态不做静默降级

`auto` 才允许 Provider 默认行为。用户选择 `enabled` 或 `disabled` 后，请求必须携带对应参数；模型不支持时返回清晰错误。Anthropic 的 adaptive 到 manual 回退仍属于“保持 enabled 语义”的兼容实现，不改变用户选择。

### OpenAI 思考状态映射到 reasoning effort

OpenAI Responses API 的明确控制入口是 `reasoning.effort`。`enabled` 使用 `medium`，`disabled` 使用 `none`，`auto` 省略。部分旧模型不支持 `none`，此时由 API 返回错误并经 Provider 脱敏呈现，符合“不静默改变用户选择”的约束。

### 不为最终计划引入用户可配置预算

4096/8192 和 6 轮调查是本次修复确定的内部策略，先通过常量和 `AgentRunConfig` 提供可测试性，不扩展 YAML 表面积。后续若开放配置，应另行经过 spec 流程。

