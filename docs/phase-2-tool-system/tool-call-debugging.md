# 工具调用无响应问题复盘

## 问题现象

手动测试阶段发现：普通对话可以正常流式回复，但所有工具相关请求都没有可见结果。用户要求模型创建文件、读取文件、搜索代码或执行命令时，终端没有显示预期的工具状态，例如：

```text
tool: write_file ...
tool: write_file ok - Wrote hello.txt
```

这说明问题不在 REPL 基础输入输出，也不在纯文本 provider 调用链路，而集中在“模型发起工具调用 -> Provider 解析工具调用事件 -> Conversation 执行工具”这段链路。

## 影响范围

- 普通多轮对话不受影响。
- 本地六个工具本身不受影响；工具注册、文件读写、搜索和命令执行的单元测试通过。
- 受影响的是 Anthropic 与 OpenAI provider 对真实流式工具调用事件的解析。
- 因为工具调用事件没有正确转换成统一的 `ProviderToolCall`，Conversation 无法进入工具执行分支，终端也就不会显示工具状态。

## 根因一：Anthropic 流式事件消费方式错误

### 原因

Anthropic SDK 的 `messages.stream()` 返回的 `MessageStream` 本身就是事件迭代器。真实工具调用事件需要通过迭代 `stream` 读取，例如 `content_block_start`、`content_block_delta`、`content_block_stop`。

原实现只在存在 `stream.events` 时解析事件，否则退回到 `stream.text_stream`：

```python
with self._client.messages.stream(**request) as stream:
    if hasattr(stream, "events"):
        yield from _parse_anthropic_events(stream.events)
        return
    for text in stream.text_stream:
        yield ProviderTextDelta(text)
```

真实 SDK 的 stream 没有 `.events` 属性。普通文本回复可以从 `text_stream` 读到内容，所以普通对话正常；但当 Claude 选择工具调用时，响应主要是 `tool_use` 事件，不是文本 delta，`text_stream` 不会产出工具调用信息。

### 解决方案

统一直接解析 `stream` 本身：

```python
with self._client.messages.stream(**request) as stream:
    yield from _parse_anthropic_events(stream)
```

`_parse_anthropic_events()` 负责处理：

- `content_block_delta` + `text_delta` -> `ProviderTextDelta`
- `content_block_start` + `tool_use` -> 记录工具 id 和工具名
- `content_block_delta` + `input_json_delta` -> 拼接 JSON 参数碎片
- `content_block_stop` -> 生成统一 `ProviderToolCall`

## 根因二：OpenAI Responses API 事件关联键用错

### 原因

OpenAI Responses API 的工具调用流式事件里，参数增量事件使用 `item_id` 关联 output item；真正用于回灌工具结果的是 function call 的 `call_id`。

原实现主要按 `call_id` 聚合参数碎片：

```python
call_id = event.call_id or event.item_id
```

在真实事件中：

- `response.output_item.added` 里同时有 output item 的 `id` 和 function call 的 `call_id`
- `response.function_call_arguments.delta` 使用 `item_id`
- `response.function_call_arguments.done` 使用 `item_id`

如果解析器用错键，参数事件无法正确关联到最初记录的工具名，最终会生成名称为空或错误的工具调用请求。Conversation 即使收到请求，也会走到未知工具失败路径，无法完成预期工具执行。

### 解决方案

解析器内部使用 `item_id` 聚合流式参数碎片，同时保留 `call_id` 用于后续工具结果回灌：

```python
item_id = item.id or item.call_id
call_id = item.call_id or item_id
self._calls[item_id] = {"call_id": call_id, "name": name, "parts": []}
```

当 `response.function_call_arguments.done` 到达时：

- 用 `item_id` 找回工具名和参数碎片
- 用事件里的 `arguments` 或已拼接的碎片解析 JSON
- 生成 `ToolCallRequest(id=call_id, name=name, ...)`

同时支持 `response.output_item.done` 作为兜底事件，避免某些流只在 output item 完成事件里给出完整参数。

## 根因三：测试桩没有覆盖真实 SDK 事件形态

### 原因

最初测试覆盖了 fake provider 的工具事件，但 fake 事件形态比真实 SDK 更理想化：

- Anthropic fake stream 暴露了 `.events` 属性，真实 `MessageStream` 不这样工作。
- OpenAI fake 参数事件使用 `call_id`，真实 Responses API 参数事件使用 `item_id`。

因此自动测试通过，但手动联调失败。

### 解决方案

补充更贴近真实 SDK 的回归测试：

- Anthropic fake stream 实现 `__iter__()`，通过迭代 stream 本身产生 `content_block_*` 事件。
- OpenAI fake stream 使用 `item_id` 传递参数 delta 和 done 事件，同时保留 `call_id` 检查工具结果回灌 id。
- 增加 `response.output_item.done` 兜底解析测试。
- 增加去重逻辑，避免同时收到 `arguments.done` 和 `output_item.done` 时重复执行同一个工具调用。

## 代码变更

涉及文件：

- `src/mewcode/providers/anthropic_provider.py`
- `src/mewcode/providers/openai_provider.py`
- `src/mewcode/tools/base.py`
- `tests/test_providers.py`
- `tests/test_tool_providers.py`
- `tests/test_tools_base.py`

关键修复：

- Anthropic provider 从读取 `text_stream` 改为直接解析真实 stream 事件。
- OpenAI provider 用 `item_id` 聚合工具参数，用 `call_id` 作为工具结果回灌 id。
- OpenAI provider 支持 `response.output_item.done` 工具调用兜底解析。
- OpenAI 工具定义补充 `strict: False`，匹配当前 SDK 类型要求。
- Provider 测试补充真实事件形态，避免 fake 流再次偏离 SDK 行为。

## 验证结果

定向测试：

```powershell
python -m pytest tests/test_tool_providers.py tests/test_providers.py tests/test_tool_conversation.py
```

结果：

```text
25 passed
```

全量测试：

```powershell
python -m pytest
```

结果：

```text
99 passed
```

编译检查：

```powershell
python -m compileall src tests
```

结果：通过。

## 后续防范

- Provider 流式事件测试必须尽量模拟真实 SDK 字段名和迭代方式，不只测理想化事件。
- 每次接入新的 provider 或 SDK 版本升级时，都要手动验证一次真实工具调用。
- 对“普通文本流”和“工具调用流”分别保留回归测试，因为它们在 SDK 中通常走不同事件路径。
- 发现手动测试和单元测试结果冲突时，优先怀疑测试桩与真实协议不一致。
