# MewCode 工具系统 Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|------|------|------|
| 新建 | `src/mewcode/tools/__init__.py` | tools 包导出 |
| 新建 | `src/mewcode/tools/base.py` | Tool、ToolResult、ToolRegistry、截断和 schema helper |
| 新建 | `src/mewcode/tools/workspace.py` | 工作区路径安全边界 |
| 新建 | `src/mewcode/tools/file_tools.py` | read_file、write_file、edit_file |
| 新建 | `src/mewcode/tools/search_tools.py` | find_files、search_code |
| 新建 | `src/mewcode/tools/command_tool.py` | run_command |
| 新建 | `src/mewcode/tools/builtin.py` | 六个内置工具注册 |
| 修改 | `src/mewcode/providers/base.py` | provider 事件模型、工具结果回灌接口 |
| 修改 | `src/mewcode/providers/anthropic_provider.py` | Anthropic 工具定义传入、流式 tool use 解析、tool result 消息 |
| 修改 | `src/mewcode/providers/openai_provider.py` | OpenAI tools 传入、Responses tool call 解析、tool result 输入 |
| 修改 | `src/mewcode/conversation.py` | 一次工具调用编排和会话事件 |
| 修改 | `src/mewcode/repl.py` | 消费会话事件并显示工具状态 |
| 修改 | `src/mewcode/cli.py` | 创建 Workspace 和内置 ToolRegistry |
| 修改 | `README.md` | 补充工具系统说明和安全边界 |
| 新建 | `tests/test_tools_base.py` | 工具基础与 registry 测试 |
| 新建 | `tests/test_workspace.py` | 工作区路径安全测试 |
| 新建 | `tests/test_file_tools.py` | 文件工具测试 |
| 新建 | `tests/test_search_tools.py` | 搜索工具测试 |
| 新建 | `tests/test_command_tool.py` | 命令工具测试 |
| 新建 | `tests/test_tool_conversation.py` | 工具编排测试 |
| 新建 | `tests/test_tool_providers.py` | provider tool-call 解析测试 |
| 修改 | `tests/test_conversation.py` | 适配 ConversationEvent |
| 修改 | `tests/test_repl.py` | 适配工具状态显示和 CLI 注入 |
| 修改 | `tests/test_providers.py` | 适配 ProviderEvent |
| 新建 | `docs/tool-system/task.md` | 本文档 |
| 新建 | `docs/tool-system/checklist.md` | 下一阶段验收文档 |

## T1: 定义工具基础类型和注册中心

**文件：** `src/mewcode/tools/base.py`, `src/mewcode/tools/__init__.py`, `tests/test_tools_base.py`

**依赖：** 无

**步骤：**
1. 定义 `ToolParameterSchema = dict[str, Any]`。
2. 定义 `ToolResult`，包含 `ok`、`tool_name`、`content`、`error`、`metadata`。
3. 定义 `ToolCallRequest`，包含 `id`、`name`、`arguments`、`raw_arguments`。
4. 定义 `Tool` protocol。
5. 实现 `truncate_text(text, limit)`，超限时截断并返回 `truncated=True`。
6. 实现 required/type 轻量 schema 校验 helper。
7. 实现 `ToolRegistry` 的 `get()`、`list()`、`execute()`。
8. `execute()` 对未知工具、参数校验失败、工具异常都返回 `ToolResult(ok=False)`。
9. 实现 `to_anthropic_tools()` 与 `to_openai_tools()`。
10. 在 `tools/__init__.py` 导出基础类型。
11. 添加测试覆盖 registry 查找、API 格式转换、未知工具、工具异常、截断。

**验证：** 运行 `python -m pytest tests/test_tools_base.py`，期望全部通过。

## T2: 实现工作区路径安全

**文件：** `src/mewcode/tools/workspace.py`, `tests/test_workspace.py`

**依赖：** T1

**步骤：**
1. 定义 `WorkspaceError`。
2. 定义 `Workspace(root: Path)`，初始化时保存 `root.resolve()`。
3. 实现 `resolve_path(path: str) -> Path`。
4. 支持相对路径和工作区内绝对路径。
5. 拒绝空路径、`..` 越界、绝对路径越界。
6. 通过 `Path.resolve()` 拒绝符号链接越界。
7. 实现 `relative_path(path: Path) -> str`。
8. 添加测试覆盖工作区内路径、越界相对路径、越界绝对路径、符号链接越界。

**验证：** 运行 `python -m pytest tests/test_workspace.py`，期望全部通过。

## T3: 实现文件工具

**文件：** `src/mewcode/tools/file_tools.py`, `tests/test_file_tools.py`

**依赖：** T1, T2

**步骤：**
1. 实现 `ReadFileTool` 的元信息和 schema。
2. `read_file` 使用 `Workspace.resolve_path()`，按 UTF-8 读取文本，输出超限时截断并在 metadata 标记。
3. 实现 `WriteFileTool` 的元信息和 schema。
4. `write_file` 使用 `Workspace.resolve_path()`，创建父目录并写入 UTF-8 文本。
5. 实现 `EditFileTool` 的元信息和 schema。
6. `edit_file` 读取 UTF-8 文本，统计 `old_text` 出现次数。
7. 出现 1 次时替换并写回；出现 0 次或多次时返回失败结果，不修改文件。
8. 所有越界、文件不存在、编码错误都返回结构化失败结果。
9. 添加测试覆盖读取、写入、唯一替换、0 次匹配、多次匹配、越界路径和截断。

**验证：** 运行 `python -m pytest tests/test_file_tools.py`，期望全部通过。

## T4: 实现搜索工具

**文件：** `src/mewcode/tools/search_tools.py`, `tests/test_search_tools.py`

**依赖：** T1, T2

**步骤：**
1. 实现 `FindFilesTool` 元信息和 schema。
2. `find_files` 用 workspace root 的 `glob()` 查找文件，只返回文件相对路径。
3. 跳过 `.git`、`.pytest_cache`、`__pycache__` 和隐藏目录。
4. 实现 `SearchCodeTool` 元信息和 schema。
5. `search_code` 校验 `query`，可选 `path` 限制搜索子目录。
6. 遍历 UTF-8 文本文件，返回匹配的相对路径、行号、行片段。
7. 匹配数最多 100 条，总内容超限时截断并标记。
8. 添加测试覆盖 glob 查找、隐藏目录跳过、内容搜索、路径限制、越界路径和截断。

**验证：** 运行 `python -m pytest tests/test_search_tools.py`，期望全部通过。

## T5: 实现命令工具

**文件：** `src/mewcode/tools/command_tool.py`, `tests/test_command_tool.py`

**依赖：** T1, T2

**步骤：**
1. 定义 `DEFAULT_COMMAND_TIMEOUT_SECONDS = 30` 和 `MAX_COMMAND_TIMEOUT_SECONDS = 120`。
2. 实现 `RunCommandTool` 元信息和 schema。
3. 校验 `command` 非空字符串。
4. 校验 `timeout_seconds` 可选，必须为正整数且不超过最大值。
5. 拦截明显危险命令字符串：删除根目录/全盘、格式化、关机、权限破坏、Windows `del /s` 等。
6. 使用 `subprocess.run(..., shell=True, cwd=workspace.root, capture_output=True, text=True, timeout=...)` 执行。
7. 返回 stdout、stderr、exit_code、timed_out metadata。
8. 超时时返回 `ok=False` 和超时错误。
9. 输出超限时截断 stdout/stderr 并标记。
10. 添加测试覆盖安全命令、非零 exit code、超时、危险命令拦截、超时参数越界、输出截断。

**验证：** 运行 `python -m pytest tests/test_command_tool.py`，期望全部通过。

## T6: 创建内置工具注册中心

**文件：** `src/mewcode/tools/builtin.py`, `src/mewcode/tools/__init__.py`, `tests/test_tools_base.py`

**依赖：** T3, T4, T5

**步骤：**
1. 实现 `create_builtin_registry(workspace: Workspace) -> ToolRegistry`。
2. 注册六个工具：`read_file`、`write_file`、`edit_file`、`run_command`、`find_files`、`search_code`。
3. 在 `tools/__init__.py` 导出 `Workspace`、`ToolRegistry`、`create_builtin_registry`。
4. 添加测试确认内置 registry 列出六个工具，且按名查找成功。
5. 添加测试确认 Anthropic/OpenAI 工具定义包含六个工具。

**验证：** 运行 `python -m pytest tests/test_tools_base.py`，期望全部通过。

## T7: 扩展 Provider 基础接口和事件模型

**文件：** `src/mewcode/providers/base.py`, `tests/test_providers.py`

**依赖：** T1

**步骤：**
1. 将 `ChatMessage.content` 类型从 `str` 改为 `Any`。
2. 新增 `ProviderTextDelta`、`ProviderToolCall`、`ProviderEvent`。
3. 更新 `LLMProvider.stream_reply()` 签名，增加 `tools: list[dict[str, Any]] | None = None`。
4. 新增 `LLMProvider.tool_result_message()`。
5. 保持 `create_provider()` 行为不变。
6. 更新现有 provider 单测中的 fake provider 以适配事件模型。

**验证：** 运行 `python -m pytest tests/test_providers.py`，期望现有 provider 基础测试通过或只剩具体 provider 适配失败。

## T8: 适配纯文本 provider 行为

**文件：** `src/mewcode/providers/anthropic_provider.py`, `src/mewcode/providers/openai_provider.py`, `tests/test_providers.py`

**依赖：** T7

**步骤：**
1. Anthropic 普通 `text_stream` 输出改为 yield `ProviderTextDelta(text)`。
2. OpenAI `response.output_text.delta` 输出改为 yield `ProviderTextDelta(text)`。
3. 两个 provider 请求时接收可选 `tools` 参数，并在非空时传入供应商请求。
4. 两个 provider 实现基本 `tool_result_message()` 占位逻辑，后续任务补完整格式。
5. 更新上一章 provider 测试断言文本事件。
6. 确认无工具调用时 provider 行为不退化。

**验证：** 运行 `python -m pytest tests/test_providers.py`，期望全部通过。

## T9: 实现 Anthropic tool use 解析和结果回灌

**文件：** `src/mewcode/providers/anthropic_provider.py`, `tests/test_tool_providers.py`

**依赖：** T8

**步骤：**
1. 在 Anthropic 请求中传入 `tools=registry.to_anthropic_tools()` 的定义。
2. 增加事件解析路径，支持 fake stream 中的 tool use start、input_json_delta、stop 事件。
3. 拼接工具参数 JSON 片段，生成 `ToolCallRequest`。
4. JSON 解析失败时生成 `ToolCallRequest(arguments={}, raw_arguments=...)`，由 registry 返回结构化参数错误。
5. 实现 `tool_result_message()`，生成 Anthropic tool_result 需要的 user message content block。
6. 保持 thinking 请求逻辑不退化。
7. 添加 fake Anthropic stream 测试：文本 delta、工具调用名称、JSON 参数碎片拼接、坏 JSON、tool_result message 格式。

**验证：** 运行 `python -m pytest tests/test_tool_providers.py tests/test_providers.py`，期望 Anthropic 相关测试通过。

## T10: 实现 OpenAI Responses tool call 解析和结果回灌

**文件：** `src/mewcode/providers/openai_provider.py`, `tests/test_tool_providers.py`

**依赖：** T8

**步骤：**
1. 在 OpenAI Responses 请求中传入 `tools=registry.to_openai_tools()` 的定义。
2. 解析 fake stream 中的 tool/function call created、arguments delta、completed 事件。
3. 按 call id 累积名称和 JSON 参数片段。
4. completed 后生成统一 `ToolCallRequest`。
5. JSON 解析失败时生成空 arguments 和 raw arguments。
6. 实现 `tool_result_message()`，生成 OpenAI function/tool result 输入项。
7. 添加 fake OpenAI event 测试：文本 delta、工具调用名称、JSON 参数碎片拼接、坏 JSON、tool_result message 格式。

**验证：** 运行 `python -m pytest tests/test_tool_providers.py tests/test_providers.py`，期望 OpenAI 相关测试通过。

## T11: 改造 Conversation 为会话事件和一次工具编排

**文件：** `src/mewcode/conversation.py`, `tests/test_conversation.py`, `tests/test_tool_conversation.py`

**依赖：** T6, T7, T8

**步骤：**
1. 定义 `ConversationTextDelta`、`ConversationToolStatus`、`ConversationEvent`。
2. `Conversation.__init__()` 增加 `tools: ToolRegistry | None = None`。
3. `ask()` 产出 `ConversationTextDelta` 替代纯字符串。
4. 无工具调用时，保存 user 和 assistant 文本历史，保持上一章行为。
5. 有工具调用时，产出 started 状态，执行 registry，产出 succeeded/failed 状态。
6. 调用 provider.tool_result_message() 构造结果消息。
7. 第二次调用 provider 时不传 tools。
8. 第二次调用只允许文本；如果出现 `ProviderToolCall`，产出 skipped 状态，不执行第二次工具。
9. 工具失败也要回灌模型并允许最终总结。
10. 更新旧会话测试，新增工具成功、工具失败、未知工具、二次工具被跳过、无工具退化测试。

**验证：** 运行 `python -m pytest tests/test_conversation.py tests/test_tool_conversation.py`，期望全部通过。

## T12: 改造 REPL 显示会话事件

**文件：** `src/mewcode/repl.py`, `tests/test_repl.py`

**依赖：** T11

**步骤：**
1. REPL 识别 `ConversationTextDelta`，按原逻辑写 stdout 并 flush。
2. REPL 识别 `ConversationToolStatus`。
3. started 输出 `tool: <name> ...`。
4. succeeded 输出 `tool: <name> ok - <summary>`。
5. failed 输出 `tool: <name> failed - <summary>`。
6. skipped 输出 `tool: <name> skipped - <summary>`。
7. 不输出工具参数 JSON 和完整工具结果。
8. 更新 REPL 测试覆盖文本流式、工具状态显示、provider/tool 错误继续循环。

**验证：** 运行 `python -m pytest tests/test_repl.py`，期望全部通过。

## T13: CLI 注入工作区和内置工具

**文件：** `src/mewcode/cli.py`, `tests/test_repl.py`

**依赖：** T6, T11, T12

**步骤：**
1. 在 `main()` 中创建 `Workspace(Path.cwd())`。
2. 创建 `create_builtin_registry(workspace)`。
3. 构造 `Conversation(provider, tools=registry)`。
4. 保持配置错误、provider 启动错误、KeyboardInterrupt 行为不变。
5. 更新 CLI 测试确认 Conversation 收到 tools registry。
6. 确认无配置启动仍返回清晰错误。

**验证：** 运行 `python -m pytest tests/test_repl.py`，期望全部通过。

## T14: 更新文档说明

**文件：** `README.md`

**依赖：** T6, T13

**步骤：**
1. README 增加“工具系统”小节。
2. 列出六个内置工具名称和用途。
3. 写明工作区边界、命令超时、危险命令拦截。
4. 写明本章不支持自动多工具循环。
5. 保持 API key 配置说明不泄露真实密钥。

**验证：** 运行 `rg -n "sk-|ANTHROPIC_API_KEY=.*[^)]|OPENAI_API_KEY=.*[^)]" README.md examples tests src`，期望没有真实密钥命中。

## T15: 全量集成验证

**文件：** 全部实现文件与测试文件

**依赖：** T1-T14

**步骤：**
1. 运行 `python -m compileall src tests`。
2. 运行 `python -m pytest`。
3. 运行 `rg -n "rm -rf /|format C:|shutdown" src tests README.md docs`，人工确认危险命令只存在于拦截规则、测试或文档说明。
4. 使用无配置临时 HOME 运行 `python -m mewcode`，确认仍输出配置错误并返回非零。
5. 使用 fake provider 测试确认工具调用后只执行一次并生成最终回复。

**验证：** 编译和全量测试通过；无配置启动仍按上一章行为返回清晰错误。

## 执行顺序

```text
T1 -> T2 -> T3
      |      -> T6
      -> T4 -> T6
      -> T5 -> T6
T1 -> T7 -> T8 -> T9
              -> T10
T6 + T8 -> T11 -> T12 -> T13 -> T14 -> T15
T9 + T10 ------^
```

## 自检
- `plan.md` 的工具基础、工作区、文件工具、搜索工具、命令工具、provider、conversation、REPL、CLI 都有任务。
- 每个任务都有验证方式。
- 依赖链没有循环。
- 默认测试不调用真实 API，也不执行危险命令。
- 每轮最多一次工具调用的限制在 T11 明确实现和验证。
