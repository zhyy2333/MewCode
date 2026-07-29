# MewCode 初版纯对话能力 Plan

## 架构概览

MewCode 采用 Python 分层 CLI 架构：入口层负责启动和错误收口，配置层负责读取并校验 YAML，REPL 层负责交互循环，会话层负责当前进程内的多轮历史，Provider 层负责屏蔽 Anthropic 与 OpenAI 的协议差异。

CLI 启动层只做三件事：加载默认配置、根据 `active` profile 构造 provider、启动 REPL。启动阶段发生的配置错误、环境变量缺失、未知协议等问题，都在这里转成面向用户的短错误提示并退出。

配置层读取 `~/.mewcode/config.yaml`，校验 `active` 与 `profiles`，并把 `api_key: env:VAR_NAME` 解析成真实密钥。配置层返回一个已解析的当前 profile，不把 API key 打印到终端或错误信息中。

REPL 层提供基础终端交互：显示输入提示，读取用户输入，识别 `/exit` 和 `/quit`，把普通输入交给会话层，并把 provider 返回的文本片段立即写到 stdout。REPL 不知道当前后端是 Claude 还是 OpenAI。

会话层维护当前进程内的消息历史。每轮对话先追加用户消息，再调用 provider 流式生成回答；流式过程中同步把文本片段返回给 REPL，同时累积完整助手回答；本轮成功结束后，把完整助手回答追加到历史中。

Provider 层定义统一接口：输入为当前会话消息列表和 profile，输出为文本片段流。`AnthropicProvider` 使用 Anthropic Messages streaming；`OpenAIProvider` 使用 OpenAI Responses API streaming。两者都只向上层产出最终回答文本，不暴露供应商原始事件。

Anthropic provider 在 `thinking: true` 时优先发送 adaptive thinking，并设置 `display: "omitted"` 以避免展示 thinking 内容；如果模型只支持旧式 manual extended thinking，则回退到固定预算的 manual thinking。OpenAI provider 只实现 Responses API，不实现 Chat Completions。

## 核心数据结构

### Protocol

```python
Protocol = Literal["anthropic", "openai"]
```

表示配置中支持的供应商协议。

### ChatRole

```python
ChatRole = Literal["user", "assistant"]
```

表示会话历史中的消息角色。第一版不引入 system、tool 或 developer 角色。

### ChatMessage

```python
@dataclass(frozen=True)
class ChatMessage:
    role: ChatRole
    content: str
```

当前进程内的通用对话消息。REPL、会话层和 provider 层都使用这个结构，不暴露供应商专属消息对象。

### ProviderProfile

```python
@dataclass(frozen=True)
class ProviderProfile:
    name: str
    protocol: Protocol
    model: str
    base_url: str
    api_key: str
    thinking: bool = False
```

已解析、已校验、可直接用于构造 provider 的当前配置。`api_key` 字段保存解析后的真实密钥，只在内存中使用，不进入日志或终端输出。

### RawProviderProfile

```python
@dataclass(frozen=True)
class RawProviderProfile:
    name: str
    protocol: str
    model: str
    base_url: str
    api_key: str
    thinking: bool = False
```

YAML 中读取出的单个 profile。`protocol` 和 `api_key` 尚未完成业务校验，其中 `api_key` 必须是 `env:VAR_NAME` 格式。

### AppConfig

```python
@dataclass(frozen=True)
class AppConfig:
    active: str
    profiles: list[RawProviderProfile]
```

YAML 配置文件的顶层结构。

### ProviderError

```python
class ProviderError(Exception):
    message: str
```

provider 层向上抛出的统一错误。错误信息必须适合直接展示给用户，不能包含 API key。

### ConfigError

```python
class ConfigError(Exception):
    message: str
```

配置层向入口层抛出的统一错误。错误信息说明配置缺失、字段缺失、协议不支持、环境变量缺失等问题。

### LLMProvider

```python
class LLMProvider(Protocol):
    def stream_reply(self, messages: list[ChatMessage]) -> Iterator[str]:
        ...
```

统一 provider 接口。调用方传入完整当前会话消息列表；实现方负责转换成供应商请求格式，并逐个 yield 最终回答文本片段。

### Conversation

```python
class Conversation:
    def __init__(self, provider: LLMProvider) -> None: ...
    def messages(self) -> list[ChatMessage]: ...
    def ask(self, user_text: str) -> Iterator[str]: ...
```

会话管理对象。`ask()` 负责追加用户消息、调用 provider、累积助手回复，并在 provider 成功结束后追加助手消息。如果 provider 失败，不追加不完整助手消息。

### ConfigLoader

```python
def load_active_profile(path: Path) -> ProviderProfile:
    ...
```

读取并解析 YAML 配置，返回当前 active profile。

### ProviderFactory

```python
def create_provider(profile: ProviderProfile) -> LLMProvider:
    ...
```

根据 `profile.protocol` 返回 `AnthropicProvider` 或 `OpenAIProvider`。

### Repl

```python
class Repl:
    def __init__(self, conversation: Conversation, stdout: TextIO, stderr: TextIO) -> None: ...
    def run(self) -> int: ...
```

终端交互循环。`run()` 返回进程退出码：正常退出为 `0`，启动前错误由入口层处理。

### main

```python
def main(argv: list[str] | None = None) -> int:
    ...
```

程序入口，负责组装配置、provider、conversation 和 REPL，并把异常转成用户可读错误。

## 模块设计

### CLI 入口模块

**职责：** 提供 `mewcode` 命令入口，串联配置加载、provider 创建、会话创建和 REPL 运行。捕获 `ConfigError`、`ProviderError` 与 `KeyboardInterrupt`，输出短错误或正常退出。

**对外接口：**
- `main(argv: list[str] | None = None) -> int`

**依赖：**
- 配置模块
- Provider 工厂模块
- 会话模块
- REPL 模块

### 配置模块

**职责：** 读取 `~/.mewcode/config.yaml`，解析 YAML 顶层 `active` 与 `profiles`，校验每个 profile 的六个字段，解析 `api_key: env:VAR_NAME`，返回 active profile。

**对外接口：**
- `load_active_profile(path: Path = DEFAULT_CONFIG_PATH) -> ProviderProfile`
- `DEFAULT_CONFIG_PATH: Path`

**依赖：**
- Python 标准库 `os`、`pathlib`
- YAML 解析库

### 会话模块

**职责：** 在内存中维护多轮对话历史。每次用户提问时，将用户消息加入临时上下文，调用 provider 流式生成回答，成功后追加完整助手消息。

**对外接口：**
- `Conversation(provider: LLMProvider)`
- `Conversation.messages() -> list[ChatMessage]`
- `Conversation.ask(user_text: str) -> Iterator[str]`

**依赖：**
- Provider 接口模块
- 公共类型模块

### REPL 模块

**职责：** 实现基础终端交互。显示欢迎信息和输入提示，读取用户输入，识别 `/exit`、`/quit` 与空输入，打印流式文本片段，并在每轮回复结束后换行。

**对外接口：**
- `Repl(conversation: Conversation, stdout: TextIO = sys.stdout, stderr: TextIO = sys.stderr)`
- `Repl.run() -> int`

**依赖：**
- 会话模块
- Provider 错误类型
- Python 标准库 `sys`

### Provider 接口模块

**职责：** 定义 provider 统一协议、通用消息结构、配置结构和错误类型。上层模块只依赖这里，不依赖具体 SDK。

**对外接口：**
- `ChatMessage`
- `ProviderProfile`
- `LLMProvider`
- `ProviderError`
- `create_provider(profile: ProviderProfile) -> LLMProvider`

**依赖：**
- Python 标准库 `dataclasses`、`typing`

### Anthropic Provider 模块

**职责：** 把通用 `ChatMessage` 列表转换成 Anthropic Messages API 请求，通过 SDK 的 streaming 能力逐段产出文本。启用 thinking 时，先使用 `thinking={"type": "adaptive", "display": "omitted"}`；如果模型只支持旧式 manual extended thinking，则回退到 `thinking={"type": "enabled", "budget_tokens": 1024, "display": "omitted"}` 重试一次。

**对外接口：**
- `AnthropicProvider(profile: ProviderProfile)`
- `AnthropicProvider.stream_reply(messages: list[ChatMessage]) -> Iterator[str]`

**依赖：**
- Provider 接口模块
- `anthropic` Python SDK

### OpenAI Provider 模块

**职责：** 把通用 `ChatMessage` 列表转换成 OpenAI Responses API `input`，使用 `stream=True` 获取事件流，只把 `response.output_text.delta` 事件中的文本向上 yield。

**对外接口：**
- `OpenAIProvider(profile: ProviderProfile)`
- `OpenAIProvider.stream_reply(messages: list[ChatMessage]) -> Iterator[str]`

**依赖：**
- Provider 接口模块
- `openai` Python SDK

### 包元数据与示例配置

**职责：** 定义 Python 包依赖、命令入口和示例配置。示例配置展示 Anthropic 与 OpenAI 两个 profile，以及 `api_key: env:...` 写法。

**对外接口：**
- `mewcode` console script
- `examples/config.yaml`
- `README.md` 中的最小启动说明

**依赖：**
- Python packaging 配置

## 模块交互

启动流程：

```text
main()
  -> load_active_profile(DEFAULT_CONFIG_PATH)
  -> create_provider(active_profile)
  -> Conversation(provider)
  -> Repl(conversation).run()
```

单轮对话流程：

```text
用户输入文本
  -> Repl 过滤空输入和退出命令
  -> Conversation.ask(user_text)
      -> 构造本轮 messages = history + 当前 user message
      -> provider.stream_reply(messages)
          -> AnthropicProvider 或 OpenAIProvider 发起流式请求
          -> provider 逐段 yield 最终回答文本
      -> Conversation 累积 assistant_text
      -> provider 成功结束后追加 user message 与 assistant message 到 history
  -> Repl 每收到一个文本片段就 stdout.write + flush
  -> Repl 本轮结束后输出换行
```

错误流程：

```text
配置/启动错误
  -> main 捕获 ConfigError
  -> stderr 输出 "Error: <message>"
  -> 返回 1

provider 请求错误
  -> provider 转成 ProviderError
  -> Repl 在当前轮 stderr 输出 "Error: <message>"
  -> 不追加不完整 assistant message
  -> 回到下一轮输入提示

Ctrl+C
  -> main 捕获 KeyboardInterrupt
  -> 输出换行
  -> 返回 130
```

## 文件组织

```text
MewCode/
├── pyproject.toml
├── README.md
├── spec.md
├── plan.md
├── task.md
├── checklist.md
├── examples/
│   └── config.yaml
├── src/
│   └── mewcode/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py
│       ├── config.py
│       ├── conversation.py
│       ├── repl.py
│       └── providers/
│           ├── __init__.py
│           ├── base.py
│           ├── anthropic_provider.py
│           └── openai_provider.py
└── tests/
    ├── test_config.py
    ├── test_conversation.py
    ├── test_repl.py
    └── test_providers.py
```

文件职责：

- `pyproject.toml`: 包元数据、依赖、console script、pytest 配置。
- `README.md`: 最小安装、配置和运行说明。
- `examples/config.yaml`: 示例 YAML，包含 `active` 与两个 profiles。
- `src/mewcode/__main__.py`: 支持 `python -m mewcode`。
- `src/mewcode/cli.py`: `main()` 入口和异常收口。
- `src/mewcode/config.py`: YAML 加载、配置校验、环境变量解析。
- `src/mewcode/conversation.py`: 当前进程内对话历史。
- `src/mewcode/repl.py`: 终端 REPL。
- `src/mewcode/providers/base.py`: 通用类型、接口、错误和工厂。
- `src/mewcode/providers/anthropic_provider.py`: Anthropic Messages streaming 实现。
- `src/mewcode/providers/openai_provider.py`: OpenAI Responses streaming 实现。
- `tests/*`: 针对配置、会话、REPL 和 provider 事件解析的单元测试。

## 技术决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 实现语言 | Python 3.11+ | 用户指定 Python；3.11+ 类型能力足够，CLI 与 SDK 生态成熟。 |
| 包结构 | `src/` layout | 避免测试时误导入项目根目录文件，适合后续发布 console script。 |
| CLI 框架 | 标准库 `argparse` 以内的最小入口，第一版不引入 Typer/Click | 当前没有复杂命令树，只需要启动 REPL；少一个运行时依赖。 |
| REPL 形态 | 标准输入输出 REPL，不使用全屏 TUI 框架 | 满足 spec 的纯对话目标，降低终端兼容性风险。 |
| YAML 解析 | `PyYAML` | 简单稳定，足够处理当前配置结构。 |
| Anthropic 调用 | 官方 `anthropic` Python SDK | SDK 已支持 Messages streaming，可减少手写 SSE 解析风险。 |
| OpenAI 调用 | 官方 `openai` Python SDK + Responses API | 符合已批准 spec；OpenAI 官方文档显示 Responses API 支持 `stream=True` 和语义流事件。 |
| Provider 输出 | `Iterator[str]` 文本片段流 | REPL 只关心最终回答文本；隐藏供应商事件差异。 |
| 对话历史 | 内存 `list[ChatMessage]` | 满足当前进程内多轮对话，不引入持久化范围。 |
| 配置路径 | `~/.mewcode/config.yaml` | API 配置属于用户级私密信息，不放项目目录。 |
| API key 格式 | 只支持 `env:VAR_NAME` | 避免配置文件保存明文密钥，符合安全默认值。 |
| Claude thinking | `thinking: true` 时先 adaptive + omitted，adaptive 不支持再 manual 1024 tokens + omitted | 兼容新旧 Claude thinking；`display: "omitted"` 避免输出 thinking 内容并改善首个最终文本延迟。 |
| 输出 token 上限 | provider 内部常量 `DEFAULT_MAX_TOKENS = 4096` | spec 限定 profile 只有六个字段，不能新增配置项；Anthropic 请求需要明确输出上限，OpenAI 可使用同一默认值保持行为一致。 |
| OpenAI protocol | 只支持 Responses API | 与 spec 一致，不混入 Chat Completions 兼容层。 |
| 错误显示 | 转成 `Error: <message>` | 用户可读，避免把 SDK 堆栈和密钥相关内容暴露到终端。 |
| 单元测试策略 | mock SDK clients 与 fake provider，不调用真实 API | 保证默认测试可离线运行，真实 API 手工验收放到 checklist。 |

## 自检

- `spec.md` 的 F1-F12 都有架构归属。
- REPL 只依赖 `Conversation`，不依赖具体 provider。
- Provider 依赖单向向下，没有循环依赖。
- 技术决策没有引入 spec 明确排除的 tool use、文件操作或 agent 行为。
