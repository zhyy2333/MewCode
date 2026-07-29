# MewCode 工具系统 Plan

## 架构概览

本章在现有 Python 分层 CLI 架构上新增工具系统与一次工具调用编排。整体仍保持 `CLI -> REPL -> Conversation -> Provider` 的主链路，但 `Conversation` 不再只处理纯文本片段，而是处理 provider 产出的统一流式事件：文本片段、工具调用请求、工具调用上限提示。

新增 `tools` 子包，负责工具抽象、工具注册中心、工作区安全边界和六个内置工具。每个工具实现统一接口，声明 `name`、`description`、JSON Schema 风格参数定义，并返回统一 `ToolResult`。工具内部捕获可预期错误并返回失败结果，不向 REPL 抛出普通执行失败。

新增 `ToolRegistry` 集中登记六个内置工具，并提供三类能力：按名查找工具、导出 Anthropic 工具定义、导出 OpenAI 工具定义。Provider 层不直接知道具体工具实现，只接收工具定义列表并把模型请求转换为统一 `ToolCallRequest`。

Provider 接口从纯 `Iterator[str]` 扩展为事件流接口。Provider 每次请求接收当前消息历史和可用工具定义，并输出 `ProviderTextDelta` 或 `ProviderToolCall`。Anthropic provider 解析 `content_block_delta` 中的 tool input JSON 片段；OpenAI provider 解析 Responses API 的 function/tool call 参数 delta。两者都只向上层暴露完整工具调用请求，不泄露供应商原始事件。

`Conversation` 负责本章核心编排：每轮用户提问时调用 provider；如果只收到文本，则保持上一章纯聊天行为；如果收到一次工具调用，则执行注册中心中的对应工具，把结构化结果转成 provider 可发送的 tool result 消息，再调用 provider 一次生成最终文本回复。如果第二次 provider 调用仍请求工具，`Conversation` 不执行，向 REPL 产出一次工具上限提示事件并结束本轮。

`Repl` 在事件层面消费 `Conversation.ask()`：文本片段继续实时打印；工具调用开始/结束事件打印简短状态，如 `tool: read_file ...` 和 `tool: read_file ok` 或 `tool: read_file failed`；不会打印工具参数 JSON 碎片或完整大结果。

工作区边界由 `Workspace` 组件统一处理：所有工具收到路径后先规范化并解析到工作区根目录内。符号链接、绝对路径和 `..` 导致的越界都被拒绝。命令工具固定在工作区根目录执行，带默认超时、最大超时和危险命令拦截。

## 核心数据结构

### ToolParameterSchema

```python
ToolParameterSchema = dict[str, Any]
```

JSON Schema 风格参数定义。第一版只使用 `type: "object"`、`properties`、`required`、基础 `string`、`integer`、`boolean` 类型。

### ToolResult

```python
@dataclass(frozen=True)
class ToolResult:
    ok: bool
    tool_name: str
    content: str
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

工具执行统一结果。成功时 `ok=True`，主要输出放 `content`；失败时 `ok=False`，错误摘要放 `error`，可观察细节放 `metadata`。`metadata` 可包含 `truncated`、`exit_code`、`stdout`、`stderr`、`matches` 等字段。

### Tool

```python
class Tool(Protocol):
    name: str
    description: str
    parameters_schema: ToolParameterSchema

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        ...
```

所有工具的统一接口。工具自己校验必需参数和类型，失败时返回 `ToolResult(ok=False, ...)`。

### ToolRegistry

```python
class ToolRegistry:
    def __init__(self, tools: Iterable[Tool]) -> None: ...
    def get(self, name: str) -> Tool | None: ...
    def list(self) -> list[Tool]: ...
    def execute(self, request: ToolCallRequest) -> ToolResult: ...
    def to_anthropic_tools(self) -> list[dict[str, Any]]: ...
    def to_openai_tools(self) -> list[dict[str, Any]]: ...
```

集中管理工具。`execute()` 负责未知工具、坏参数和工具异常的结构化包装。API 转换方法只导出 name、description、schema，不包含执行函数。

### Workspace

```python
@dataclass(frozen=True)
class Workspace:
    root: Path

    def resolve_path(self, path: str) -> Path: ...
    def relative_path(self, path: Path) -> str: ...
```

工作区边界对象。`resolve_path()` 返回解析后的工作区内绝对路径；越界时抛 `WorkspaceError`，由工具包装成失败结果。

### ToolCallRequest

```python
@dataclass(frozen=True)
class ToolCallRequest:
    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str
```

provider 解析出的统一工具调用请求。`id` 用于 provider 回灌结果时关联供应商 tool call；`arguments` 是解析后的 JSON 对象，`raw_arguments` 用于坏 JSON 失败场景保留摘要。

### ProviderTextDelta

```python
@dataclass(frozen=True)
class ProviderTextDelta:
    text: str
```

### ProviderToolCall

```python
@dataclass(frozen=True)
class ProviderToolCall:
    request: ToolCallRequest
```

### ProviderEvent

```python
ProviderEvent = ProviderTextDelta | ProviderToolCall
```

provider 第一阶段和最终回复阶段都产出统一事件流。

### ConversationTextDelta

```python
@dataclass(frozen=True)
class ConversationTextDelta:
    text: str
```

### ConversationToolStatus

```python
@dataclass(frozen=True)
class ConversationToolStatus:
    tool_name: str
    status: Literal["started", "succeeded", "failed", "skipped"]
    summary: str
```

### ConversationEvent

```python
ConversationEvent = ConversationTextDelta | ConversationToolStatus
```

REPL 只消费会话事件，不直接接触 provider 事件或 tool result 原始结构。

### LLMProvider

```python
class LLMProvider(Protocol):
    def stream_reply(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> Iterator[ProviderEvent]:
        ...

    def tool_result_message(
        self,
        tool_call: ToolCallRequest,
        result: ToolResult,
    ) -> ChatMessage:
        ...
```

Provider 新接口。`stream_reply()` 接收可选工具定义；`tool_result_message()` 把统一工具结果转换成该 provider 后续请求需要的消息形态。现有纯文本 provider 行为通过只产出 `ProviderTextDelta` 保持兼容。

### Conversation

```python
class Conversation:
    def __init__(
        self,
        provider: LLMProvider,
        tools: ToolRegistry | None = None,
    ) -> None: ...

    def messages(self) -> list[ChatMessage]: ...

    def ask(self, user_text: str) -> Iterator[ConversationEvent]: ...
```

会话层编排一次工具调用。`tools is None` 时退化为纯对话。`ask()` 负责保存用户消息、助手文本、工具调用请求、工具结果消息和最终助手回复。

### 内置工具类

```python
class ReadFileTool: ...
class WriteFileTool: ...
class EditFileTool: ...
class RunCommandTool: ...
class FindFilesTool: ...
class SearchCodeTool: ...
```

每个工具构造时接收 `Workspace`，命令工具额外接收超时常量。

## 模块设计

### 工具基础模块

**文件：** `src/mewcode/tools/base.py`

**职责：**
- 定义 `Tool`、`ToolResult`、`ToolCallRequest`、`ToolRegistry`。
- 提供参数必填/类型校验 helper。
- 提供工具结果截断 helper。
- 提供 `to_anthropic_tools()` 与 `to_openai_tools()` 格式转换。

**对外接口：**
- `Tool`
- `ToolResult`
- `ToolCallRequest`
- `ToolRegistry`
- `truncate_text(text: str, limit: int) -> tuple[str, bool]`

**依赖：**
- 标准库 `dataclasses`、`typing`、`json`

### 工作区安全模块

**文件：** `src/mewcode/tools/workspace.py`

**职责：**
- 定义当前工作区根目录。
- 解析工具传入路径，拒绝越界路径。
- 提供相对路径格式化。
- 屏蔽符号链接越界。

**对外接口：**
- `Workspace(root: Path)`
- `Workspace.resolve_path(path: str) -> Path`
- `Workspace.relative_path(path: Path) -> str`
- `WorkspaceError`

**依赖：**
- 标准库 `pathlib`

### 文件工具模块

**文件：** `src/mewcode/tools/file_tools.py`

**职责：**
- 实现 `read_file`、`write_file`、`edit_file`。
- 只处理 UTF-8 文本。
- `read_file` 对大文件内容截断并标记。
- `write_file` 创建父目录，但只限工作区内。
- `edit_file` 使用原文唯一匹配替换；0 次或多次匹配都失败。

**对外接口：**
- `ReadFileTool`
- `WriteFileTool`
- `EditFileTool`

**依赖：**
- 工具基础模块
- 工作区安全模块

### 搜索工具模块

**文件：** `src/mewcode/tools/search_tools.py`

**职责：**
- 实现 `find_files` 和 `search_code`。
- `find_files` 使用工作区内 glob。
- `search_code` 遍历文本文件内容，返回匹配文件、行号和片段。
- 跳过常见缓存和隐藏目录：`.git`、`.pytest_cache`、`__pycache__`。
- 对结果数量和总输出大小做限制并标记截断。

**对外接口：**
- `FindFilesTool`
- `SearchCodeTool`

**依赖：**
- 工具基础模块
- 工作区安全模块

### 命令工具模块

**文件：** `src/mewcode/tools/command_tool.py`

**职责：**
- 实现 `run_command`。
- 命令固定在工作区根目录执行。
- 默认超时 30 秒，最大超时 120 秒。
- 捕获 stdout、stderr、exit_code。
- 超时返回结构化超时结果。
- 拦截危险命令模式。

**对外接口：**
- `RunCommandTool`
- `DEFAULT_COMMAND_TIMEOUT_SECONDS = 30`
- `MAX_COMMAND_TIMEOUT_SECONDS = 120`

**依赖：**
- 标准库 `subprocess`、`shlex`
- 工具基础模块
- 工作区安全模块

### 内置工具模块

**文件：** `src/mewcode/tools/builtin.py`

**职责：**
- 根据工作区创建六个内置工具。
- 创建默认 `ToolRegistry`。

**对外接口：**
- `create_builtin_registry(workspace: Workspace) -> ToolRegistry`

**依赖：**
- 六个工具实现模块

### Provider 基础模块

**文件：** `src/mewcode/providers/base.py`

**职责变化：**
- `ChatMessage.content` 从 `str` 放宽到 `Any`。
- 新增 `ProviderTextDelta`、`ProviderToolCall`、`ProviderEvent`。
- `LLMProvider.stream_reply()` 支持可选工具定义。
- `LLMProvider.tool_result_message()` 支持工具结果回灌。
- 保持 `create_provider()` lazy import。

**依赖：**
- 工具基础模块中的 `ToolCallRequest`、`ToolResult`

### Anthropic Provider 模块

**文件：** `src/mewcode/providers/anthropic_provider.py`

**职责变化：**
- 请求时接收 Anthropic 工具定义列表。
- 解析普通文本 delta 为 `ProviderTextDelta`。
- 解析 tool use content block 的名称与 input JSON delta，拼成 `ToolCallRequest`。
- 把 `ToolResult` 转成 Anthropic tool_result 消息。
- thinking 行为保持上一章逻辑。

**依赖：**
- Provider 基础模块
- 工具基础模块
- Anthropic SDK

### OpenAI Provider 模块

**文件：** `src/mewcode/providers/openai_provider.py`

**职责变化：**
- 请求时接收 OpenAI tools 定义列表。
- 解析 Responses API 文本 delta 为 `ProviderTextDelta`。
- 解析 function/tool call 名称与 arguments delta，拼成 `ToolCallRequest`。
- 把 `ToolResult` 转成 OpenAI function/tool result 输入项。
- 仍不实现 Chat Completions。

**依赖：**
- Provider 基础模块
- 工具基础模块
- OpenAI SDK

### 会话模块

**文件：** `src/mewcode/conversation.py`

**职责变化：**
- `Conversation.ask()` 产出 `ConversationEvent`，而不是纯字符串。
- 第一阶段 provider 调用带工具定义。
- 收到工具调用后执行 registry。
- 工具结果回灌后进行第二次 provider 调用生成最终文本。
- 第二次调用如果再次请求工具，产出 skipped 状态并停止。
- 无工具调用时保持纯聊天历史追加逻辑。

**依赖：**
- Provider 基础模块
- 工具基础模块

### REPL 模块

**文件：** `src/mewcode/repl.py`

**职责变化：**
- 识别 `ConversationTextDelta` 并按原逻辑流式打印。
- 识别 `ConversationToolStatus` 并打印简短工具状态。
- 不打印 JSON 参数碎片或完整工具结果。

**依赖：**
- 会话模块

### CLI 入口模块

**文件：** `src/mewcode/cli.py`

**职责变化：**
- 创建 `Workspace(Path.cwd())`。
- 创建内置 `ToolRegistry`。
- 把 registry 注入 `Conversation`。

## 模块交互

### 启动流程

```text
main()
  -> load_active_profile(DEFAULT_CONFIG_PATH)
  -> create_provider(active_profile)
  -> Workspace(Path.cwd())
  -> create_builtin_registry(workspace)
  -> Conversation(provider, tools=registry)
  -> Repl(conversation).run()
```

### 无工具调用流程

```text
用户输入
  -> Repl
  -> Conversation.ask(user_text)
      -> history + user message
      -> provider.stream_reply(messages, tools=registry.to_provider_tools())
          -> ProviderTextDelta*
      -> ConversationTextDelta*
      -> 保存 user message + assistant text
  -> Repl 流式打印文本
```

### 一次工具调用流程

```text
用户输入
  -> Conversation.ask(user_text)
      -> 第一阶段 provider.stream_reply(messages, tools=...)
          -> ProviderTextDelta*（可选，通常为空或少量前言）
          -> ProviderToolCall(request)
      -> ConversationToolStatus(started)
      -> ToolRegistry.execute(request)
          -> ToolResult(ok=True/False)
      -> ConversationToolStatus(succeeded/failed)
      -> provider.tool_result_message(request, result)
      -> 第二阶段 provider.stream_reply(messages + tool result, tools=None)
          -> ProviderTextDelta*
      -> 保存本轮 user message、工具调用相关消息、最终 assistant text
  -> Repl 打印简短工具状态和最终文本
```

### 第二次工具调用被拒绝流程

```text
第二阶段 provider.stream_reply(...)
  -> ProviderToolCall(second_request)
  -> ConversationToolStatus(skipped, "tool call limit reached")
  -> 不执行工具
  -> 保存到历史中的助手文本只包含第二阶段已生成文本
```

### 工具失败流程

```text
ToolRegistry.execute(request)
  -> 未知工具 / JSON 坏参数 / Schema 不通过 / 工具异常 / 超时
  -> ToolResult(ok=False, error=...)
  -> ConversationToolStatus(failed)
  -> provider.tool_result_message(request, failed_result)
  -> 第二阶段 provider 仍有机会基于失败结果回复用户
```

## 文件组织

```text
MewCode/
├── docs/
│   └── tool-system/
│       ├── spec.md
│       ├── plan.md
│       ├── task.md
│       └── checklist.md
├── src/
│   └── mewcode/
│       ├── cli.py
│       ├── conversation.py
│       ├── repl.py
│       ├── providers/
│       │   ├── base.py
│       │   ├── anthropic_provider.py
│       │   └── openai_provider.py
│       └── tools/
│           ├── __init__.py
│           ├── base.py
│           ├── workspace.py
│           ├── file_tools.py
│           ├── search_tools.py
│           ├── command_tool.py
│           └── builtin.py
└── tests/
    ├── test_tools_base.py
    ├── test_workspace.py
    ├── test_file_tools.py
    ├── test_search_tools.py
    ├── test_command_tool.py
    ├── test_tool_conversation.py
    ├── test_tool_providers.py
    └── test_repl.py（扩展）
```

## 历史消息保存策略

第一阶段无工具调用时，保持上一章行为：

```text
user -> assistant
```

发生工具调用时，历史保存为：

```text
user
assistant/tool-call placeholder（provider-specific content）
tool-result message（provider-specific content）
assistant final text
```

实现上 `Conversation` 不解释 provider-specific content，只通过 provider 提供的构造方法生成消息并保存。普通多轮文本消息仍保持 `ChatMessage(role="user"|"assistant", content=str)`。

## 技术决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 工具调用次数 | 每轮最多一次工具执行，工具结果后再生成一次最终回答 | 严格符合 spec，把自动循环留到下一章。 |
| 工具状态显示 | REPL 显示短状态，不显示 JSON 参数碎片 | 保持用户可见性，同时避免终端噪音和泄露大参数。 |
| 工作区根目录 | `Path.cwd()` | 当前 CLI 从项目目录启动，工作区边界清晰，不新增配置项。 |
| 路径安全 | `Path.resolve()` 后检查是否仍在 workspace root 内 | 同时处理绝对路径、`..` 和符号链接越界。 |
| 文本编码 | 工具默认按 UTF-8 读写 | 第一版只支持文本工具，不处理二进制和编码探测。 |
| 文件读取上限 | 单次工具结果内容上限 20,000 字符 | 避免把过大文件塞回模型上下文，同时足够读取常见源文件片段。 |
| 搜索结果上限 | 最多 100 条匹配，总输出仍受 20,000 字符限制 | 防止搜索全仓库时输出失控。 |
| 命令执行 | `subprocess.run(..., shell=True, cwd=workspace.root, capture_output=True, text=True, timeout=...)` | 用户给的是命令字符串，`shell=True` 兼容常见 CLI；通过危险命令拦截和工作区 cwd 降低风险。 |
| 命令默认超时 | 30 秒 | 足够执行常见检查命令，避免挂住 REPL。 |
| 命令最大超时 | 120 秒 | 允许较慢测试，但避免长时间占用。 |
| 危险命令拦截 | 基于命令字符串正则/分词拦截明显破坏性命令 | 第一版不做完整沙箱；拦截 `rm -rf /`、`del /s`、`format`、`shutdown`、权限修改等高风险模式。 |
| 参数校验 | 工具内部根据 JSON Schema 的 required 和基础类型做轻量校验 | 不引入额外 JSON Schema 依赖，保持实现小而可测。 |
| ToolResult 回灌格式 | JSON 字符串，包含 `ok`、`content`、`error`、`metadata` | 两家 provider 都能接收文本化工具结果；结构清晰，模型可据此调整。 |
| Anthropic 工具定义 | `{name, description, input_schema}` | 匹配 Anthropic Messages tool use 形态。 |
| OpenAI 工具定义 | `{type: "function", name, description, parameters}` | 匹配 Responses API function tool 形态。 |
| Provider 事件模型 | 内部统一为 `ProviderTextDelta` / `ProviderToolCall` | 会话层无需处理供应商原始流式事件差异。 |
| 坏 JSON 处理 | Provider 产出带 raw arguments 的工具调用失败请求，registry 返回坏 JSON 结构化错误 | 不让 JSON 解析失败崩掉；模型能看到错误并修正。 |
| 测试策略 | fake provider、fake SDK stream、临时工作区、危险命令拦截测试 | 默认测试不依赖真实 API，不执行危险命令。 |

## 自检

- F1-F18 都有模块归属。
- 工具调用限制和“不做自动循环”没有冲突。
- provider 只做协议转换，不执行工具。
- 工具执行只发生在 `ToolRegistry`/内置工具层，并受 `Workspace` 限制。
