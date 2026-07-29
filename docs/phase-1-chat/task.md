# MewCode 初版纯对话能力 Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|------|------|------|
| 新建 | `pyproject.toml` | 包元数据、依赖、console script、pytest 配置 |
| 新建 | `README.md` | 最小安装、配置和运行说明 |
| 新建 | `examples/config.yaml` | Anthropic 与 OpenAI profile 示例 |
| 新建 | `src/mewcode/__init__.py` | 包初始化和版本号 |
| 新建 | `src/mewcode/__main__.py` | 支持 `python -m mewcode` |
| 新建 | `src/mewcode/cli.py` | 程序入口、配置加载、异常收口 |
| 新建 | `src/mewcode/config.py` | YAML 配置读取、校验、环境变量解析 |
| 新建 | `src/mewcode/conversation.py` | 当前进程内会话历史和多轮对话 |
| 新建 | `src/mewcode/repl.py` | 标准输入输出 REPL |
| 新建 | `src/mewcode/providers/__init__.py` | provider 包导出 |
| 新建 | `src/mewcode/providers/base.py` | 通用类型、接口、错误、工厂 |
| 新建 | `src/mewcode/providers/anthropic_provider.py` | Anthropic Messages streaming provider |
| 新建 | `src/mewcode/providers/openai_provider.py` | OpenAI Responses streaming provider |
| 新建 | `tests/test_config.py` | 配置模块测试 |
| 新建 | `tests/test_conversation.py` | 会话模块测试 |
| 新建 | `tests/test_repl.py` | REPL 行为测试 |
| 新建 | `tests/test_providers.py` | provider 转换、流式事件和工厂测试 |

## T1: 创建 Python 包骨架

**文件：** `pyproject.toml`, `src/mewcode/__init__.py`, `src/mewcode/__main__.py`, `src/mewcode/cli.py`, `src/mewcode/providers/__init__.py`

**依赖：** 无

**步骤：**
1. 创建 `src/` layout 和 `mewcode` 包目录。
2. 在 `pyproject.toml` 中配置 Python `>=3.11`、依赖 `anthropic`、`openai`、`PyYAML`，dev 依赖 `pytest`。
3. 配置 console script：`mewcode = "mewcode.cli:main"`。
4. 在 `__init__.py` 中定义 `__version__ = "0.1.0"`。
5. 在 `__main__.py` 中调用 `raise SystemExit(main())`。
6. 在 `cli.py` 中先放最小 `main(argv: list[str] | None = None) -> int` 桩函数，返回 `0`，后续任务替换。

**验证：** 运行 `python -m compileall src`，期望编译通过。

## T2: 定义 provider 通用类型和工厂骨架

**文件：** `src/mewcode/providers/base.py`, `src/mewcode/providers/__init__.py`

**依赖：** T1

**步骤：**
1. 定义 `Protocol = Literal["anthropic", "openai"]` 和 `ChatRole = Literal["user", "assistant"]`。
2. 定义 `ChatMessage`、`RawProviderProfile`、`ProviderProfile`、`AppConfig` dataclass。
3. 定义 `ConfigError` 和 `ProviderError`，构造时只保存用户可读 message。
4. 定义 `LLMProvider` typing protocol，包含 `stream_reply(messages: list[ChatMessage]) -> Iterator[str]`。
5. 定义 `DEFAULT_MAX_TOKENS = 4096`。
6. 创建 `create_provider(profile: ProviderProfile) -> LLMProvider` 骨架，根据 protocol 做 lazy import；未知 protocol 抛 `ConfigError`。
7. 在 `providers/__init__.py` 导出通用类型和工厂。

**验证：** 运行 `python -m compileall src`，期望编译通过。

## T3: 实现配置 happy path

**文件：** `src/mewcode/config.py`, `tests/test_config.py`

**依赖：** T2

**步骤：**
1. 定义 `DEFAULT_CONFIG_PATH = Path.home() / ".mewcode" / "config.yaml"`。
2. 实现 `load_active_profile(path: Path = DEFAULT_CONFIG_PATH) -> ProviderProfile`。
3. 使用 `yaml.safe_load()` 解析 YAML，读取顶层 `active` 和 `profiles`。
4. 按 `active` 匹配 `profiles[].name`。
5. 校验 `protocol` 只能是 `anthropic` 或 `openai`。
6. 解析 `api_key: env:VAR_NAME`，从环境变量读取真实密钥。
7. `thinking` 缺失时默认为 `False`。
8. 添加测试：有效配置 + 环境变量存在时，返回解析后的 `ProviderProfile`。

**验证：** 运行 `python -m pytest tests/test_config.py`，期望配置 happy path 测试通过。

## T4: 补全配置错误处理

**文件：** `src/mewcode/config.py`, `tests/test_config.py`

**依赖：** T3

**步骤：**
1. 配置文件不存在时抛 `ConfigError`，提示默认路径和示例配置位置。
2. YAML 不是对象、缺少 `active`、缺少 `profiles` 或 `profiles` 不是列表时抛 `ConfigError`。
3. active 名称找不到时抛 `ConfigError`。
4. profile 缺少 `name`、`protocol`、`model`、`base_url`、`api_key` 时抛 `ConfigError`。
5. `api_key` 不是 `env:VAR_NAME` 或环境变量为空时抛 `ConfigError`。
6. 错误信息不得包含真实 API key。
7. 添加对应错误路径测试。

**验证：** 运行 `python -m pytest tests/test_config.py`，期望全部配置测试通过。

## T5: 实现会话历史

**文件：** `src/mewcode/conversation.py`, `tests/test_conversation.py`

**依赖：** T2

**步骤：**
1. 实现 `Conversation(provider: LLMProvider)`，内部维护 `_messages: list[ChatMessage]`。
2. `messages()` 返回历史副本，避免外部直接修改内部列表。
3. `ask(user_text: str)` 构造 `pending_messages = history + [user message]`。
4. 调用 provider 的 `stream_reply(pending_messages)` 并逐段 yield。
5. 累积完整 assistant 文本；provider 成功结束后依次追加 user 和 assistant 消息到历史。
6. provider 抛错时保留原历史，不追加不完整消息。
7. 添加 fake provider 测试：流式片段顺序、历史追加、多轮上下文、失败不污染历史。

**验证：** 运行 `python -m pytest tests/test_conversation.py`，期望全部会话测试通过。

## T6: 实现基础 REPL

**文件：** `src/mewcode/repl.py`, `tests/test_repl.py`

**依赖：** T5

**步骤：**
1. 实现 `Repl(conversation, stdout=sys.stdout, stderr=sys.stderr)`。
2. `run()` 启动时输出简短欢迎信息和退出提示。
3. 每轮用 `input("mew> ")` 读取用户输入。
4. 空输入直接进入下一轮，不调用 conversation。
5. `/exit` 和 `/quit` 返回 `0`。
6. 普通输入调用 `conversation.ask()`，每收到片段就 `stdout.write()` 并 `flush()`。
7. 每轮成功回复结束后输出换行。
8. 捕获当前轮 `ProviderError`，向 stderr 输出 `Error: <message>`，继续下一轮。
9. 添加测试覆盖退出命令、空输入、流式打印、provider 错误继续循环。

**验证：** 运行 `python -m pytest tests/test_repl.py`，期望全部 REPL 测试通过。

## T7: 实现 CLI 入口组装

**文件：** `src/mewcode/cli.py`, `tests/test_repl.py`

**依赖：** T3, T5, T6

**步骤：**
1. `main()` 调用 `load_active_profile()`、`create_provider()`、`Conversation()`、`Repl().run()`。
2. 捕获 `ConfigError`，向 stderr 输出 `Error: <message>` 并返回 `1`。
3. 捕获顶层 `KeyboardInterrupt`，输出换行并返回 `130`。
4. 不在错误信息中打印 profile 或 API key 的完整对象。
5. 添加测试：配置错误返回 `1`，KeyboardInterrupt 返回 `130`，正常路径返回 REPL 的退出码。

**验证：** 运行 `python -m pytest tests/test_repl.py`，期望 CLI 入口相关测试通过。

## T8: 实现 Anthropic 普通流式 provider

**文件：** `src/mewcode/providers/anthropic_provider.py`, `tests/test_providers.py`

**依赖：** T2

**步骤：**
1. 实现 `AnthropicProvider(profile: ProviderProfile)`。
2. 构造 `anthropic.Anthropic(api_key=profile.api_key, base_url=profile.base_url)`。
3. 把 `ChatMessage` 列表转换成 Anthropic Messages API 的 `messages` 格式。
4. 当 `thinking` 为 `False` 时，调用 `client.messages.stream(model=..., max_tokens=DEFAULT_MAX_TOKENS, messages=...)`。
5. 使用 SDK stream 的 `text_stream` 逐段 yield 文本。
6. 捕获 Anthropic SDK 异常并转成 `ProviderError`，错误信息不包含 API key。
7. 添加 monkeypatch/fake client 测试：请求参数正确、文本片段按顺序 yield、SDK 异常被包装。

**验证：** 运行 `python -m pytest tests/test_providers.py`，期望 Anthropic 普通流式测试通过。

## T9: 实现 Anthropic thinking 和 fallback

**文件：** `src/mewcode/providers/anthropic_provider.py`, `tests/test_providers.py`

**依赖：** T8

**步骤：**
1. 当 `profile.thinking` 为 `True` 时，第一次请求加入 `thinking={"type": "adaptive", "display": "omitted"}`。
2. 如果第一次请求因 Anthropic 400 且错误信息表示 adaptive thinking 不支持，则重试一次。
3. 重试请求使用 `thinking={"type": "enabled", "budget_tokens": 1024, "display": "omitted"}`。
4. 其他 400 或非 400 错误不重试，直接包装成 `ProviderError`。
5. provider 仍只 yield `text_stream` 文本，不 yield thinking 内容。
6. 添加测试：thinking true 使用 adaptive；adaptive 不支持时 manual fallback；其他错误不 fallback；输出不包含 fake thinking 事件文本。

**验证：** 运行 `python -m pytest tests/test_providers.py`，期望 Anthropic thinking 测试通过。

## T10: 实现 OpenAI Responses provider

**文件：** `src/mewcode/providers/openai_provider.py`, `tests/test_providers.py`

**依赖：** T2

**步骤：**
1. 实现 `OpenAIProvider(profile: ProviderProfile)`。
2. 构造 `openai.OpenAI(api_key=profile.api_key, base_url=profile.base_url)`。
3. 把 `ChatMessage` 列表转换成 Responses API `input` 列表。
4. 调用 `client.responses.create(model=..., input=..., max_output_tokens=DEFAULT_MAX_TOKENS, stream=True)`。
5. 遍历 stream，只在 `event.type == "response.output_text.delta"` 时 yield `event.delta`。
6. 忽略 created/completed 等生命周期事件。
7. 遇到 `error` 事件或 SDK 异常时抛 `ProviderError`。
8. 添加 fake event 测试：只输出 delta 文本，生命周期事件被忽略，错误事件被包装。

**验证：** 运行 `python -m pytest tests/test_providers.py`，期望 OpenAI provider 测试通过。

## T11: 接通 provider 工厂

**文件：** `src/mewcode/providers/base.py`, `tests/test_providers.py`

**依赖：** T8, T10

**步骤：**
1. 完成 `create_provider()` 的 lazy import，`anthropic` 返回 `AnthropicProvider`，`openai` 返回 `OpenAIProvider`。
2. 未知 protocol 抛 `ConfigError`。
3. 避免在导入 `base.py` 时立即导入两个 SDK provider，减少测试和启动副作用。
4. 添加测试：两个协议返回对应 provider 类型，未知协议报错。

**验证：** 运行 `python -m pytest tests/test_providers.py`，期望 provider 工厂测试通过。

## T12: 补充示例配置和 README

**文件：** `examples/config.yaml`, `README.md`

**依赖：** T4, T7, T11

**步骤：**
1. `examples/config.yaml` 写入顶层 `active` 和两个 profiles：Anthropic、OpenAI。
2. 两个 profile 都包含 `name`、`protocol`、`model`、`base_url`、`api_key`、`thinking`。
3. `api_key` 示例只使用 `env:ANTHROPIC_API_KEY` 和 `env:OPENAI_API_KEY`。
4. README 写明安装命令、复制配置到 `~/.mewcode/config.yaml`、设置环境变量、运行 `mewcode` 或 `python -m mewcode`。
5. README 明确第一版只支持纯对话，不支持工具调用、文件操作和代码编辑。

**验证：** 运行 `python -m pytest`，期望不因文档和示例变更引入测试失败；人工检查示例配置不包含真实密钥。

## T13: 本地集成验证

**文件：** 全部实现文件与测试文件

**依赖：** T1-T12

**步骤：**
1. 运行 `python -m compileall src tests`。
2. 运行 `python -m pytest`。
3. 运行 `python -m mewcode`，在无配置文件时确认 stderr 输出清晰配置错误并返回非零退出码。
4. 使用临时 HOME 或 monkeypatch 配置路径运行 CLI 测试，确认 `/exit` 正常退出。
5. 检查测试与 README 中没有真实 API key。

**验证：** `python -m compileall src tests` 和 `python -m pytest` 都通过；无配置启动时看到 `Error:` 开头的配置提示。

## 执行顺序

```text
T1 -> T2 -> T3 -> T4
      |      |
      |      -> T7
      -> T5 -> T6 -> T7
      -> T8 -> T9
      -> T10
T8 + T10 -> T11
T4 + T7 + T11 -> T12
T1-T12 -> T13
```

## 自检

- `plan.md` 的 CLI、配置、会话、REPL、provider、包元数据组件都至少有对应任务。
- 每个任务都有文件、依赖、步骤和具体验证方式。
- 依赖链没有循环。
- 所有测试默认使用 fake provider、fake SDK client 或 monkeypatch，不需要真实 API key。
- 任务没有引入 `spec.md` 明确排除的 tool use、文件操作、代码编辑 agent 行为。
