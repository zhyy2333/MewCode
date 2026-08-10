# MewCode MCP 客户端 Plan

## 架构概览

MCP 客户端作为一个独立的长生命周期运行时接入现有工具中心。配置加载与 REPL 继续在主线程运行；所有 MCP 网络连接、stdio 子进程、后台读取任务、JSON-RPC 等待者和超时任务集中运行在一个专用后台事件循环中。后台运行时在进入 REPL 前完成 Server 初始化和工具发现，返回一组实现现有 `Tool` 协议的代理对象；之后 Agent、Provider、Scheduler 和权限系统仍只面对统一的 `ToolRegistry`。

整体结构如下：

```text
主线程
  配置加载
    -> 创建 MCP 后台运行时
    -> 并行初始化 Server、发现工具
    -> 内置工具 + MCP 工具组成完整 ToolRegistry
    -> 用完整工具名集合加载权限规则
    -> 创建 Provider / Scheduler / Agent / Conversation
    -> 运行现有同步 REPL
    -> finally 关闭 MCP 运行时

MCP 后台事件循环（全进程一个）
  McpManager
    -> Server A: McpClientSession -> JsonRpcPeer -> StdioTransport
    -> Server B: McpClientSession -> JsonRpcPeer -> StreamableHttpTransport
    -> Server C: McpClientSession -> JsonRpcPeer -> ...

Agent 调用 MCP 工具
  McpTool.execute
    -> 把调用提交到 MCP 后台事件循环
    -> McpClientSession.call_tool
    -> JsonRpcPeer 按 id 等待响应
    -> 结果转换为 ToolResult
    -> 返回 Agent Loop
```

后台事件循环只建立一个线程，不为每个 Server 单独创建线程。每个 Server 仍拥有独立 Session、Transport、请求表和状态机，因此共享运行时不会共享故障状态。

### 异步运行时方案比较

| 方案 | 优点 | 代价与风险 | 结论 |
|------|------|------------|------|
| 专用 MCP 后台事件循环 | 等待终端输入时仍持续排空 stdout/stderr、处理响应和超时；保留现有同步 REPL；所有 MCP 异步资源固定在同一事件循环 | 需要一个受控的跨线程提交桥，并严格传播取消与关闭 | **采用** |
| 把 CLI 与 REPL 全面改为异步 | 所有组件共用一个事件循环，调用链直观 | 跨平台异步终端输入和 `Ctrl+C` 清理需要新依赖或额外线程；改动面扩散到整个 REPL 与既有测试 | 不采用 |
| 启动和每轮对话使用短生命周期事件循环 | 表面改动较少 | 用户等待输入时 stdio 读取与 stderr 排空停止；异步客户端跨事件循环复用不安全，无法满足持续生命周期要求 | 排除 |

### 配置边界

MCP 配置加载器独立于 Provider Profile 解析，但复用相同的用户配置文件，并额外读取项目配置文件。加载器先验证文件级 YAML 与 `mcp_servers` 根结构，再按“用户 map 后项目 map”生成确定顺序的合并条目。每个条目独立解析为 stdio 或 HTTP 配置；条目错误被转成脱敏诊断，不进入运行时。

环境变量只在条目解析阶段展开到不可变的运行时配置对象。原始 header、展开值和完整子进程环境不进入通用日志或异常；后续组件只通过受控配置对象取得连接所需值。

### Manager 与故障隔离

`McpManager` 在后台事件循环中并行启动全部有效配置。每个启动任务依次创建 Transport、建立 JSON-RPC peer、执行初始化、发送 initialized 通知、分页列出工具并构造工具 descriptor。Manager 使用逐 Server 的结果收集，不让单个异常取消同批其他启动任务。

成功 Session 被缓存到 Server 名称索引中；失败 Session 立即清理并留下脱敏警告。运行期 Session 进入失败状态后只快速拒绝自身后续调用，不影响 Manager 中其他 Session，也不触发重建。Manager 对外返回按确定顺序排列的 descriptor 和启动诊断，Runtime 再在主线程构造代理工具。

### 协议分层

协议实现分为三层：

- `McpClientSession` 负责 MCP `2025-11-25` 生命周期、能力校验、工具分页、工具调用、结果语义和 Session 状态机。
- `JsonRpcPeer` 负责 JSON-RPC 2.0 id 分配、pending future 配对、超时、取消通知、响应分派、ping 和未支持 Server 请求的错误响应。
- `McpTransport` 只负责消息送达和接收。`StdioTransport` 处理子进程与逐行 JSON；`StreamableHttpTransport` 处理 POST、JSON/SSE 响应、协议 header、会话 id 和 DELETE 关闭。

Session 不解析传输细节，Transport 不解释 MCP 方法结果。两种传输把收到的单条 JSON-RPC 消息交给同一个 `JsonRpcPeer`，从而共享请求配对与错误行为。

### Tool 与权限集成

每个发现到的有效工具生成一个 `McpTool` 代理。代理保存公开名、原始 Server 工具名、描述、输入 Schema 和指向后台运行时的调用句柄；它声明 `SIDE_EFFECT`，并使用新增的静态工具级权限目标。静态目标值固定为 `invoke`，因此规则表现为 `<public_name>(invoke)`：仅本次决定只影响当前调用，会话或永久规则则匹配该公开工具的所有后续参数。

代理的 `execute` 在 Agent 当前事件循环中等待一个跨线程 future。调用实际在 MCP 后台循环执行；Agent 取消代理任务时同步取消后台请求等待，并按 JSON-RPC 规则尝试通知 Server。返回值跨线程前转换为只含普通 Python 数据的结果，再由代理构造现有 `ToolResult`，不把 Session 或异步对象暴露给 Agent 层。

### 启动与关闭顺序

CLI 先完成 Provider 配置校验和 Provider 创建，再启动 MCP 运行时，避免模型配置本身无效时留下外部进程。MCP 工具发现完成后，CLI 用“内置工具 + 有效 MCP 工具”创建最终注册表，再把完整名称集合交给权限配置加载器，确保已有或新生成的 MCP 权限规则可被识别。

从 MCP 运行时启动开始，CLI 使用 `try/finally` 保证所有后续失败路径都会进入关闭。关闭在后台循环中并行处理各 Session，完成 stdio 分级终止和 HTTP 会话结束后取消残余任务、关闭事件循环并回收后台线程。清理错误只形成警告，不覆盖 REPL 或原始启动错误的退出状态。

## 核心数据结构与接口

### 配置模型

```python
class McpTransportKind(StrEnum):
    STDIO = "stdio"
    HTTP = "http"


@dataclass(frozen=True)
class StdioServerConfig:
    name: str
    command: str
    args: tuple[str, ...] = ()
    env_overrides: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class HttpServerConfig:
    name: str
    url: str
    headers: tuple[tuple[str, str], ...] = ()


McpServerConfig = StdioServerConfig | HttpServerConfig
```

配置对象只保存用户显式覆盖的 stdio 环境，不复制整个父进程环境；`StdioTransport` 在真正启动子进程前把当前进程环境与覆盖项合并。header 和环境覆盖使用有序 tuple，避免冻结 dataclass 内仍保留可变 map，并保证测试和启动顺序确定。

```python
@dataclass(frozen=True)
class McpConfigPaths:
    user: Path
    project: Path

    @classmethod
    def for_workspace(
        cls,
        workspace: Workspace,
        user_home: Path | None = None,
    ) -> McpConfigPaths: ...


@dataclass(frozen=True)
class McpConfigLoadResult:
    servers: tuple[McpServerConfig, ...]
    diagnostics: tuple[McpDiagnostic, ...]
    permission_prefixes: tuple[str, ...]


class McpConfigLoader:
    def load(self, paths: McpConfigPaths) -> McpConfigLoadResult: ...
```

`McpConfigLoader.load` 对文件级错误抛出 `McpConfigError`，对条目级错误返回 diagnostic。`permission_prefixes` 从所有具有非空 Server key 的配置条目生成，即使该条目的其他字段无效或该 Server 随后连接失败也保留，用来识别已有的休眠 MCP 权限规则。

项目级 map 覆盖同名用户级条目时保留该 key 在用户顺序中的位置；项目新增 key 按项目文件顺序追加。最终工具仍按公开名排序后交付注册，因此 YAML map 的等价重排不会影响 Provider 顺序。

### 诊断、阶段与超时

```python
class McpPhase(StrEnum):
    CONFIG = "config"
    STARTUP = "startup"
    CALL = "call"
    SHUTDOWN = "shutdown"


@dataclass(frozen=True)
class McpDiagnostic:
    server_name: str | None
    phase: McpPhase
    message: str


@dataclass(frozen=True)
class McpTimeouts:
    startup_seconds: float = 30.0
    request_seconds: float = 120.0
    shutdown_seconds: float = 5.0
```

启动上限包住单个 Server 的 Transport 创建、initialize、initialized 和全部分页发现，而不是对每一页重新获得 30 秒。`request_seconds` 用于正常工具调用；`shutdown_seconds` 是单个 Session 完成全部关闭步骤的总上限。测试注入极短值，不依赖真实等待。

Diagnostic 只能接收已经脱敏的稳定描述，不保存原始 exception、header、完整环境或 HTTP response body。CLI 统一渲染为 `Warning: MCP server '<name>' <phase> failed: <message>`；文件级配置错误继续走现有 `Error:` 启动失败路径。

### 错误模型

```python
class McpError(RuntimeError):
    server_name: str
    phase: McpPhase
    safe_message: str
    session_fatal: bool


class McpConfigError(ConfigError): ...
class McpTransportError(McpError): ...
class McpProtocolError(McpError): ...
class McpRequestTimeout(McpError): ...
class McpUnavailableError(McpError): ...
```

所有跨后台线程边界传播的异常都必须是上述安全错误之一。底层 `OSError`、HTTP 客户端异常和 JSON 解码异常在其产生层被分类并丢弃可能含 secret 的原始字符串。

传输关闭、HTTP 会话失效、非法 framing 和破坏请求配对可信度的协议错误标记 `session_fatal=True`，使 Session 进入 `FAILED`。单次 `tools/call` 的 JSON-RPC error、`isError: true` 和请求超时只失败当前调用；超时请求被移出 pending 表并忽略迟到响应，不自动判定整个 Session 不可用。

### Transport 接口

```python
JsonRpcMessage = dict[str, Any]
MessageHandler = Callable[[JsonRpcMessage], Awaitable[None]]
FailureHandler = Callable[[McpError], Awaitable[None]]


class McpTransport(Protocol):
    server_name: str

    async def start(
        self,
        on_message: MessageHandler,
        on_failure: FailureHandler,
    ) -> None: ...

    async def send(self, message: JsonRpcMessage) -> None: ...
    def set_protocol_version(self, version: str) -> None: ...
    async def close(self) -> tuple[McpDiagnostic, ...]: ...
```

`send` 的语义是“把一条 JSON-RPC 消息完整交给传输”。stdio 实现只等待单行写入和 drain；HTTP 实现等待当前 POST 的 JSON 或 SSE 响应被完整消费，并把其中每条消息依次交给 `on_message`。两者都拒绝 list 形式的 JSON-RPC batch。

`StdioTransport` 内部持有子进程、stdout reader task、stderr drainer task 和写锁。`StreamableHttpTransport` 内部持有一个 `httpx.AsyncClient`、大小写不敏感的受保护 header 集、协商版本和可选 Session id；多个 POST 可并发使用同一连接池，但用户 header 永远不能覆盖协议 header。

### JSON-RPC peer

```python
class JsonRpcPeer:
    def __init__(
        self,
        transport: McpTransport,
        request_timeout: float,
        id_factory: Callable[[], int] | None = None,
    ) -> None: ...

    async def start(self) -> None: ...

    async def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> Any: ...

    async def notify(
        self,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> None: ...

    async def receive(self, message: JsonRpcMessage) -> None: ...
    async def fail(self, error: McpError) -> None: ...
    async def close(self) -> tuple[McpDiagnostic, ...]: ...
```

Peer 从整数 1 开始单调分配 id，并在 `pending: dict[int, Future[Any]]` 中登记后再发送。response 必须恰好包含 `result` 或 `error`，且 id 必须是受支持的标量类型；命中 pending 时先从表中移除再完成 future。未知、重复或已超时 id 被视为迟到消息并忽略，不得完成其他 future。

`request` 在超时或调用方取消时原子移除 pending，并尽力发送 `notifications/cancelled`。`receive` 对 Server request 只接受 `ping`；其他带 id 的 method 返回 JSON-RPC `-32601`，无 id 的未知通知被安全忽略。Transport fatal failure 调用 `fail`，Peer 用同一个安全错误失败全部 pending。

### Session 状态与 MCP 数据

```python
class McpSessionState(StrEnum):
    NEW = "new"
    STARTING = "starting"
    READY = "ready"
    FAILED = "failed"
    CLOSED = "closed"


@dataclass(frozen=True)
class McpToolDescriptor:
    server_name: str
    original_name: str
    public_name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class McpCallResult:
    is_error: bool
    content: tuple[dict[str, Any], ...]
    structured_content: dict[str, Any] | None


class McpClientSession:
    state: McpSessionState

    async def start(self) -> tuple[dict[str, Any], ...]: ...
    async def call_tool(
        self,
        original_name: str,
        arguments: dict[str, Any],
    ) -> McpCallResult: ...
    async def close(self) -> tuple[McpDiagnostic, ...]: ...
```

`start` 只允许从 `NEW` 进入 `STARTING`。它在统一启动 deadline 内完成 initialize、版本和 tools capability 校验、设置 HTTP 协议版本、发送 initialized，并循环 `tools/list`。分页记录已见 cursor；空字符串、非字符串或重复 cursor 视为 fatal 协议错误，防止恶意 Server 形成无限分页。

Session 返回原始工具定义给 Manager 校验和命名，只有全部握手步骤完成后才进入 `READY`。`call_tool` 只在 `READY` 接受请求，并严格校验 `tools/call` result 的根结构、content 类型、`isError` 和可选 `structuredContent`；Server 报告的工具执行错误仍形成 `McpCallResult`，不改变 Session 状态。

### Manager 与运行时桥

```python
@dataclass(frozen=True)
class McpManagerStartResult:
    descriptors: tuple[McpToolDescriptor, ...]
    diagnostics: tuple[McpDiagnostic, ...]


class McpManager:
    async def start(
        self,
        configs: tuple[McpServerConfig, ...],
        reserved_tool_names: set[str],
    ) -> McpManagerStartResult: ...

    async def call_tool(
        self,
        server_name: str,
        original_name: str,
        arguments: dict[str, Any],
    ) -> McpCallResult: ...

    async def close(self) -> tuple[McpDiagnostic, ...]: ...


@dataclass(frozen=True)
class McpRuntimeStartResult:
    tools: tuple[McpTool, ...]
    diagnostics: tuple[McpDiagnostic, ...]


class McpRuntime:
    def start(
        self,
        configs: tuple[McpServerConfig, ...],
        reserved_tool_names: set[str],
    ) -> McpRuntimeStartResult: ...

    async def call_tool(
        self,
        server_name: str,
        original_name: str,
        arguments: dict[str, Any],
    ) -> McpCallResult: ...

    def close(self) -> tuple[McpDiagnostic, ...]: ...
```

Manager 为每个配置创建独立 Session，并用 `gather(return_exceptions=True)` 收集启动结果。它校验工具定义、去重原始名、生成公开名、检查保留名和规范化碰撞，最终按 `public_name` 排序 descriptor。没有任何有效工具的成功 Session 随即关闭，不保留无用途连接。

Runtime 负责后台线程和事件循环，并在主线程把 descriptor 转成 `McpTool`。`start` 只能调用一次；如果线程、事件循环或 Manager 顶层启动失败，它关闭已创建资源后抛出安全启动错误。`call_tool` 使用 `run_coroutine_threadsafe` 提交 Manager 调用，再以 `asyncio.wrap_future` 让 Agent 异步等待；Agent 侧取消时同步取消后台 future。`close` 幂等，先运行 Manager 关闭，再停止 loop、join 线程并返回清理诊断。

### Tool 代理与权限扩展

```python
class PermissionTargetKind(StrEnum):
    COMMAND = "command"
    PATH = "path"
    PATH_GLOB = "path_glob"
    TOOL = "tool"


@dataclass(frozen=True)
class ToolPermissionSpec:
    argument: str | None
    kind: PermissionTargetKind
    default: str | None = None


class McpTool:
    name: str
    description: str
    parameters_schema: ToolParameterSchema
    safety = ToolSafety.SIDE_EFFECT
    permission_spec = ToolPermissionSpec(
        argument=None,
        kind=PermissionTargetKind.TOOL,
        default="invoke",
    )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult: ...
```

`PermissionTargetBuilder` 对 `TOOL` 不读取调用参数，直接要求 `argument is None` 且 `default` 为非空字符串，然后构造 `<public_name>(invoke)` 目标。规则匹配器把 `TOOL` 当作非路径字符串处理；现有三种目标的构造和匹配不变。

权限加载器增加可选 `deferred_tool_prefixes`。未知工具规则只有在名称以某个已配置 MCP namespace prefix 开头时才允许作为休眠规则载入；其他未知工具仍按现有行为报错。Server 恢复并发现同名工具后，该规则自然参与匹配；Server 未恢复时规则不会匹配任何实际调用。

`McpTool.execute` 只负责调用 Runtime、把 `McpCallResult` 交给纯函数结果适配器，以及把安全 `McpError` 转成失败 `ToolResult`。结果 metadata 只保留 `server_name`、`original_tool_name`、`mcp_is_error`、内容类型和截断标记，不保存 header、Session id 或原始协议包。

### 结果适配接口

```python
def adapt_mcp_result(
    public_name: str,
    result: McpCallResult,
    content_limit: int = DEFAULT_TOOL_CONTENT_LIMIT,
) -> ToolResult: ...


def mcp_failure_result(
    public_name: str,
    server_name: str,
    error: McpError,
) -> ToolResult: ...
```

适配器按 content 原顺序生成文本段；resource link 和 text resource 只展开允许字段；image、audio、blob resource 和未知二进制块生成省略标记。`structuredContent` 使用 `json.dumps(..., ensure_ascii=False, sort_keys=True)` 形成独立段。全部段组合后统一调用现有 `truncate_text`。

`is_error=False` 生成成功结果；`is_error=True` 保留可操作内容但设置 `ok=False`，`error` 使用稳定摘要 `MCP tool reported an execution error.`。协议、传输与超时错误使用各自 `safe_message`，从不把 raw exception 直接写入结果。

## 模块设计

### `mewcode.mcp.models`

**职责：** 保存 MCP 协议版本常量、消息大小上限、配置 dataclass、诊断、超时、错误类型、Session 状态、工具 descriptor 和调用结果。

**对外接口：** `MCP_PROTOCOL_VERSION`、`MCP_MAX_MESSAGE_BYTES`、`McpServerConfig`、`McpTimeouts`、`McpDiagnostic`、`McpError`、`McpToolDescriptor`、`McpCallResult`。

**依赖：** 只依赖标准库以及现有 `ConfigError`；不依赖 Transport、Session、Manager 或 Tool，作为 MCP 包的无环底层模型层。

协议版本固定为 `2025-11-25`，单条 stdio、HTTP JSON 或重组后 SSE data 的上限固定为 4 MiB。超过上限属于 fatal 协议/传输错误；工具结果在通过协议层后仍按现有 20,000 字符限制二次截断。

### `mewcode.mcp.config`

**职责：** 定位用户与项目配置、读取 YAML 根对象、提取与合并 `mcp_servers`、严格校验传输专属字段、展开限定位置的环境引用、过滤保留 HTTP header，并产生条目级脱敏诊断。

**对外接口：** `McpConfigPaths`、`McpConfigLoader`、`McpConfigLoadResult`。

**依赖：** `models`、现有 `Workspace`、PyYAML 和标准库环境变量；不创建进程或网络连接。

环境引用使用完整 token 语法 `\${[A-Za-z_][A-Za-z0-9_]*}`。包含 `${...}` 但内部不是合法变量名的值视为条目错误；已定义为空字符串的变量允许展开为空。保留 header 按大小写不敏感比较，包含 `Content-Type`、`Accept`、`MCP-Protocol-Version`、`MCP-Session-Id`、`Host`、`Content-Length`、`Transfer-Encoding` 和 `Connection`；配置这些名称时忽略用户值并产生非敏感 warning，Server 其余配置仍有效。

### `mewcode.mcp.naming`

**职责：** 生成 Provider 安全的确定性公开名、计算可识别休眠权限规则的 Server namespace prefix，并集中定义名称合法性。

**对外接口：**

```python
def public_tool_name(server_name: str, original_name: str) -> str: ...
def permission_namespace_prefix(server_name: str) -> str: ...
def is_public_tool_name(value: str) -> bool: ...
```

**依赖：** 只依赖标准库 `hashlib` 与 `re`。

算法先构造完整基础值 `<server>__<tool>`；若已满足 `^[A-Za-z0-9_-]{1,64}$` 则原样返回。否则把非法字符逐个替换为 `_`，取前 53 个字符，再追加 `_` 和完整基础值 SHA-256 的前 10 个十六进制字符。namespace prefix 使用相同字符替换：安全 Server 名较短时返回 `<safe_server>__`，较长时返回规范化公开名必然保留的前 53 个字符。Manager 仍对最终名称做显式碰撞检查，不把哈希当作绝对无碰撞保证。

### `mewcode.mcp.transport`

**职责：** 定义 `McpTransport` Protocol、消息/失败 callback 类型、Transport factory Protocol，以及根据配置创建具体传输的默认 factory。

**对外接口：** `McpTransport`、`McpTransportFactory`、`create_transport`。

**依赖：** `models`；默认 factory 延迟导入 stdio/HTTP 实现，避免底层接口依赖具体客户端库。

Manager 构造函数接收可注入的 factory。测试使用内存 Transport，不需要启动子进程或 HTTP Server；集成测试才使用默认 factory。

### `mewcode.mcp.stdio`

**职责：** 使用 `asyncio.create_subprocess_exec` 直接启动程序与 argv，合并环境，逐行发送/读取 JSON-RPC，持续丢弃 stderr，报告 EOF/非法 UTF-8/超限/非法 JSON，并执行跨平台分级关闭。

**对外接口：** `StdioTransport`，只通过 `McpTransport` Protocol 被上层使用。

**依赖：** `models`、`transport` 和标准库 asyncio/json/os；不依赖 Session 或 Manager。

stdout reader 使用 4 MiB stream limit，并要求每次 `readline` 得到恰好一个 JSON object。写入前以紧凑 JSON 编码，拒绝编码结果中的物理换行，使用单一写锁保证并发消息不交错。stderr drainer 只读取并丢弃 byte chunk，不解码、不转发，避免外部日志泄密或填满管道。

关闭顺序在 5 秒总 deadline 内分配剩余时间：关闭 stdin 并等待、调用 `terminate()` 并等待、最后 `kill()` 并等待。reader 在主动关闭期间看到 EOF 是正常完成；其他时刻 EOF 通过 failure callback 使 Session 失败。

### `mewcode.mcp.http`

**职责：** 维护 `httpx.AsyncClient`，发送 Streamable HTTP POST，校验状态码和 Content-Type，按 4 MiB 上限解析单个 JSON object 或请求范围 SSE，捕获并复用 Session id，添加协商版本 header，并在关闭时尝试 DELETE。

**对外接口：** `StreamableHttpTransport`，只通过 `McpTransport` Protocol 被上层使用。

**依赖：** `httpx`、`models`、`transport` 和标准库 json；不依赖 JSON-RPC peer 的具体类型。

AsyncClient 使用系统默认 TLS 校验且 `follow_redirects=False`，防止认证 header 被配置端点以外的重定向接收。每次 POST 明确发送 `Content-Type: application/json` 与 `Accept: application/json, text/event-stream`；初始化后的请求再添加版本和可选 Session header。

JSON 响应必须是单个 object。SSE parser 支持 comment、`event`、多行 `data` 和空行提交，只把拼接后的 `data` 解析为 JSON object；`id` 与 `retry` 被读取但不用于恢复。通知或 response POST 接受 202 空响应，请求 POST 必须最终提供匹配的 JSON-RPC response，否则由 Peer timeout 收敛。初始化 response 的 Session id 必须是可见 ASCII；非法值使 Session 启动失败。关闭 DELETE 的 200/202/204/405 均视为可接受，其他结果形成清理 warning。

### `mewcode.mcp.jsonrpc`

**职责：** 实现 `JsonRpcPeer`，统一构造请求与通知、管理 pending future、校验和分派响应、处理 Server request、传播 fatal failure、发送取消并关闭全部等待者。

**对外接口：** `JsonRpcPeer.request`、`notify`、`receive`、`fail`、`close`。

**依赖：** `models` 与抽象 `transport`；不导入 stdio、HTTP 或 MCP Session。

所有 pending 只在 MCP 后台事件循环访问，不需要线程锁。跨线程 Runtime 只提交完整 Session coroutine，不直接读写 Peer。`request` 用 `asyncio.timeout` 同时覆盖 Transport send 与等待 response；timeout/cancel 清理使用 `finally` 保证只执行一次。取消通知发送失败不覆盖原超时或取消结果。

### `mewcode.mcp.session`

**职责：** 实现 MCP `2025-11-25` 初始化状态机、版本与 capability 校验、initialized 通知、工具分页、原始工具定义校验和 `tools/call` 结果解析。

**对外接口：** `McpClientSession.start`、`call_tool`、`close`、`state`。

**依赖：** `models`、`JsonRpcPeer` 和抽象 Transport；不依赖 Manager、Runtime、McpTool 或权限系统。

初始化 request 使用 `clientInfo.name = "mewcode"`、当前包版本以及空 `capabilities`。Server response 只要求精确协议版本、object 类型 capabilities 和存在 `tools` capability；Server 的其他能力、instructions 和 tool annotations 不进入客户端行为。工具定义要求非空字符串 name、可选字符串 description 和 object 类型 inputSchema；不校验 outputSchema。

### `mewcode.mcp.manager`

**职责：** 为每项配置创建 Transport/Peer/Session，并行启动且逐 Server 隔离；分页结果经 naming 模块生成 descriptor；缓存可用 Session；路由工具调用；运行期失败快速拒绝；并行关闭所有 Session。

**对外接口：** `McpManager.start`、`call_tool`、`close`。

**依赖：** `config` 数据模型、`models`、`naming`、`session` 和抽象 Transport factory；不依赖 Runtime、ToolRegistry 或 Provider。

Manager 接收内置工具名作为 reserved set。每个 Server 内第一次出现的原始工具名可参与注册，后续重复定义被警告并跳过；公开名与 reserved set 或已接受 descriptor 冲突时也跳过。Session 的 tools/list 合法但最终没有有效工具时关闭 Session，并产生 `no usable tools` warning。

### `mewcode.mcp.tool`

**职责：** 定义窄化的 `McpCallGateway` Protocol、实现 `McpTool` 代理、把 MCP 结果转换为 `ToolResult`、截断内容并生成安全 metadata。

**对外接口：** `McpCallGateway`、`McpTool`、`adapt_mcp_result`、`mcp_failure_result`。

**依赖：** `models`、现有 `mewcode.tools`；不导入具体 `McpRuntime`，以 Protocol 消除 Runtime 构造 Tool 时的循环依赖。

McpTool 构造函数接收 gateway 与 descriptor，把 descriptor 的公开字段复制为 Tool 属性。结果适配是同步纯函数，可用固定 payload 直接单测；跨线程调用、错误捕获和 `CancelledError` 传播集中在 `execute`。

### `mewcode.mcp.runtime`

**职责：** 创建和拥有后台线程/事件循环/Manager，实现同步 start/close 与异步 call bridge，构造主线程侧 McpTool，并保证部分启动和重复关闭安全。

**对外接口：** `McpRuntime.start`、`call_tool`、`close`。

**依赖：** `models`、`manager` 和抽象 `McpTool`/gateway；这是 MCP 包内部最高层，不被 Manager 或 Session 反向导入。

线程入口建立 event loop 后通过 `threading.Event` 报告 ready，再运行 loop。主线程提交 Manager.start 并等待一个比单 Server startup deadline 略大的总 bridge deadline；因为 Server 启动在后台并行，总等待不随 Server 数量线性增长。close 即使 start 只完成一部分也能提交清理；loop 已异常退出时直接 join 并返回稳定 diagnostic。

### `mewcode.mcp.__init__`

**职责：** 只导出 CLI 和测试所需的稳定入口：配置路径/加载器、Runtime、超时、诊断和 MCP 错误。不重导出 Peer、具体 Transport 或 Session，避免应用层依赖内部协议细节。

### 现有模块扩展

`mewcode.tools.base` 增加 `PermissionTargetKind.TOOL`，并允许 `ToolPermissionSpec.argument` 为 `None`。内置工具声明保持原样，`ToolRegistry` 不承担 MCP 动态注册或生命周期。

`mewcode.permissions.targets` 增加静态 TOOL 目标分支；`mewcode.permissions.config` 的 loader/writer 接收 deferred MCP namespace prefixes，并只对这些 prefix 放宽“当前未知工具”校验。`rules`、Controller、Scheduler 和权限事件不改变公开行为。

`mewcode.cli` 负责新的启动顺序、warning 渲染、最终注册表组合和 `try/finally` 关闭。`Repl`、`Conversation`、Agent Runner 和两个 Provider 不增加 MCP 分支；它们通过现有 Tool/ToolResult 接口自然获得 MCP 能力。

## 模块交互

### 应用启动

```text
cli.main
  -> 解析 CLI 参数，创建 Workspace
  -> load_active_profile(user config)
  -> create_provider(profile)
  -> McpConfigLoader.load(user config, project config)
       文件错误 -> ConfigError -> main 返回 1
       条目错误 -> McpDiagnostic，继续
  -> create_builtin_registry(workspace)
  -> McpRuntime.start(valid configs, builtin names)
       后台线程 ready
       -> McpManager.start
            为每个 Server 创建独立 startup task
            -> Transport.start
            -> JsonRpcPeer.start
            -> McpClientSession.start（30 秒整体 deadline）
            -> 验证并生成 descriptor
            -> 失败 Server 自清理并产生 diagnostic
       <- 排序后的 descriptors + diagnostics
       在主线程构造 McpTool proxies
  -> ToolRegistry(builtin tools + MCP tools)
  -> PermissionConfigLoader.load(
       known_tools=完整注册表名称,
       deferred_tool_prefixes=已配置 MCP namespaces,
     )
  -> 创建 PermissionController / Scheduler / Agent / Conversation / Repl
  -> Repl.run
  -> finally McpRuntime.close
```

Provider 在 MCP Runtime 之前创建，确保无效模型 Profile 不启动外部 Server。权限规则必须在工具发现之后加载，确保实际 MCP 工具被视为 known；deferred namespace 则保证暂时离线工具的历史规则不会把启动变成全局失败。

配置条目 diagnostic 在 Runtime 启动前输出，Server 启动 diagnostic 在 Runtime 返回后输出。工具注册完成后才进入 REPL，因此单次会话的 Provider 工具集合保持静态。所有 Server startup task 并行，但 CLI 等待它们成功或各自达到 30 秒 deadline 后再构造最终注册表。

### stdio 初始化与请求配对

```text
McpClientSession.start
  -> JsonRpcPeer.start
       -> StdioTransport.start
            create_subprocess_exec(command, *args, cwd=workspace, env=merged)
            启动 stdout reader task
            启动 stderr drainer task
  -> Peer.request("initialize", ...)
       pending[1] = Future
       -> Transport.send(JSON line id=1)

Server stdout line(id=1, result=...)
  -> Stdio reader 解析 JSON object
  -> Peer.receive
       pop pending[1]
       Future.set_result
  -> Session 校验版本与 tools capability
  -> Transport.set_protocol_version("2025-11-25")
  -> Peer.notify("notifications/initialized")
  -> Peer.request("tools/list", {})
  -> 按 nextCursor 重复，直至结束
  -> Session READY
```

stdout reader 在 Session READY 后持续运行。Server 发送 ping request 时，Peer 通过同一写锁回写空 result；未知通知被消费并忽略。Server 在无主动关闭时结束 stdout，Transport 调用 `Peer.fail`：当前 pending 全部失败；若当时没有调用，下一次 request 读取 Peer 已记录的 fatal error 并让 Session 转为 `FAILED`，不会进行探测或重连。

### Streamable HTTP 初始化与请求配对

```text
Peer.request("initialize", ...)
  pending[1] = Future
  -> StreamableHttpTransport.send
       POST endpoint
       headers = user-safe headers + Content-Type + Accept
       读取可选 MCP-Session-Id response header
       application/json:
         解析一个 JSON object -> Peer.receive
       text/event-stream:
         逐事件读取 data -> 每个 JSON object 交给 Peer.receive
  <- pending[1] result
  -> Session 校验版本
  -> Transport.set_protocol_version("2025-11-25")
  -> Peer.notify("notifications/initialized")
       POST + version/session headers -> 202
  -> Peer.request("tools/list", ...)
       POST + version/session headers
```

每个客户端 JSON-RPC 消息对应一个新 POST，但所有 POST 复用同一 AsyncClient 连接池和 Session 状态。请求范围 SSE 可先携带 Server ping 或未知 request；Peer 为这些 request 发起独立 response POST，然后继续消费原 SSE，直到原请求 response 到达。任何 3xx、认证失败、404 Session 失效、非预期状态码、错误 Content-Type 或超限 body 都转换为安全 Transport error；不跟随重定向、不重新 initialize。

### 工具发现、命名与注册

```text
Session 返回各页 raw tool objects
  -> Manager 按 Server 内出现顺序遍历
       校验 name / description / inputSchema
       原始 name 去重
       public_tool_name(server, original)
       检查 builtin reserved names
       检查全局 accepted public names
       接受 -> McpToolDescriptor
       拒绝 -> tool-level diagnostic
  -> descriptors 按 public_name 排序
  -> Runtime 在主线程构造 McpTool
  -> CLI 与 builtin tools 一次性创建 ToolRegistry
```

Manager 的 accepted name set 跨 Server 共享，防止规范化碰撞。descriptor 始终同时保存 public 与 original name，Provider 只看 public name，`tools/call` 只发送 original name。

### Agent 工具调用与权限

```text
Provider 返回 ToolCallRequest(public_name, arguments)
  -> ToolRegistry.validate_call（沿用 input Schema 校验）
  -> ToolScheduler 权限预检
       PermissionTargetBuilder
         kind=TOOL -> PermissionTarget(public_name, "invoke")
       deny -> ToolResult failure；不进入 McpTool
       ask -> REPL 显示 public_name(invoke)，等待选择
       allow -> 继续
  -> Scheduler 按 SIDE_EFFECT 独占执行
  -> McpTool.execute(arguments)
       -> McpRuntime.call_tool(server_name, original_name, arguments)
            run_coroutine_threadsafe 到 MCP loop
            -> Manager.call_tool
                 Session READY?
                 -> Session.call_tool
                      Peer.request("tools/call", {
                        "name": original_name,
                        "arguments": arguments,
                      })
       <- McpCallResult 或安全 McpError
       -> adapt_mcp_result / mcp_failure_result
       <- ToolResult
  -> Scheduler 生成 AgentToolResult
  -> Provider tool result message
  -> Agent Loop 下一轮
```

参数对象只在 JSON 序列化时读取，不被代理重命名或补值。权限拒绝发生在跨线程提交之前，因此 Server 完全看不到被拒绝调用。Session/permanent rule 都匹配固定 `invoke`，参数变化不影响后续匹配。

### 请求超时与用户取消

请求超时路径：

```text
Peer.request deadline 到达
  -> 原子 pop pending[id]
  -> 尽力 notify("notifications/cancelled", requestId=id)
  -> raise McpRequestTimeout(session_fatal=False)
  -> Runtime bridge 返回安全错误
  -> McpTool 生成失败 ToolResult
  -> Session 保持 READY
  -> 迟到 response id 不在 pending，安全忽略
```

用户 `Ctrl+C` 路径：

```text
Repl -> Conversation.cancel_active
  -> AgentRun.cancel
  -> ToolSchedule.cancel
  -> 取消 McpTool.execute task
  -> McpRuntime.call_tool 收到 CancelledError
       cancel concurrent.futures.Future
       后台 Session coroutine 收到取消
       Peer 清理 pending 并尽力发送 cancelled notification
  -> CancelledError 回到 Scheduler
  -> 现有 cancelled ToolResult / Agent stop 行为
```

取消通知是 best effort；通知失败不能把“已取消”改写为传输异常。后台 future 与 Agent task 任一侧先完成时，另一侧只观察一次终态。

### 运行期失败

```text
Transport fatal failure
  -> Peer.fail(safe error)
       保存 failure
       fail 并清空全部 pending
  -> 正在调用的 Session 捕获 fatal error，state=FAILED
  -> Manager 保留失败 Session 记录但不移除其他 Session
  -> 当前 McpTool 返回失败 ToolResult

后续同 Server 调用
  -> Manager/Session 检查 FAILED 或 Peer failure
  -> 立即 McpUnavailableError
  -> 不发送消息，不创建进程，不重新 initialize

其他 Server 调用
  -> 使用各自 Session/Peer/Transport，行为不变
```

`tools/call` 返回 JSON-RPC error 或 `isError: true` 不进入上述 fatal 路径。HTTP 404 Session 失效、stdio EOF、非法 framing 和无法可信继续配对的响应结构才使 Session 失败。

### 结果适配

```text
McpCallResult
  -> 按 content 原顺序：
       text -> 原文
       resource_link -> name / URI / MIME 描述
       resource(text) -> URI / MIME / text
       resource(blob) -> URI / MIME / 已省略
       image/audio -> type / MIME / 已省略
       未知 block -> type / 已省略
  -> structuredContent 存在时追加确定性 JSON 段
  -> 以空行连接各段
  -> truncate_text(20_000)
  -> ToolResult(ok = not is_error, metadata=安全摘要)
```

适配器不会对 resource URI 发请求，也不落盘二进制。若 Server 的 `isError: true` 没有任何可显示 content，content 为空，error 仍使用稳定 MCP 执行错误摘要。

### 正常关闭与部分启动清理

```text
cli finally
  -> McpRuntime.close（幂等）
       提交 McpManager.close 到后台 loop
       -> 为所有已创建 Session 建立并行 close task
            每个 Session 5 秒总 deadline
            stdio: close stdin -> wait -> terminate -> wait -> kill -> wait
            HTTP: 有 Session id 则 DELETE -> AsyncClient.aclose
            Peer.fail/close 清空 pending
       -> 收集 diagnostics，不因一个异常取消其他 close
       -> 取消残余 MCP tasks
       -> loop.stop
       -> join runtime thread
  -> CLI 输出 shutdown warnings
  -> 返回原 REPL/启动退出码
```

Manager 从 Transport 创建成功时就登记 Session，因此 initialize、分页、权限加载或 REPL 构造中途失败都能进入同一关闭路径。Runtime thread 使用 daemon 模式作为解释器异常退出的最后保险，但正常路径必须完成显式 close 和 join；daemon 属性不能作为资源清理机制。

## 配置示例

用户级配置继续保存模型 Profile，并可追加 MCP Server：

```yaml
active: openai-main
profiles:
  - name: openai-main
    protocol: openai
    model: gpt-5.6
    base_url: https://api.openai.com/v1
    api_key: env:OPENAI_API_KEY

mcp_servers:
  local-files:
    transport: stdio
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "."]
    env:
      LOG_LEVEL: info
      SERVICE_TOKEN: "${LOCAL_MCP_TOKEN}"

  team-api:
    transport: http
    url: https://mcp.example.com/mcp
    headers:
      Authorization: "Bearer ${TEAM_MCP_TOKEN}"
```

项目级 `.mewcode/config.yaml` 可以只覆盖 MCP map：

```yaml
mcp_servers:
  local-files:
    transport: stdio
    command: python
    args: ["tools/project_mcp.py"]

  project-search:
    transport: http
    url: http://127.0.0.1:8765/mcp
```

合并后 `local-files` 完整采用项目条目，不继承用户条目的 `env`；`team-api` 与 `project-search` 同时保留。配置文档明确提醒：项目配置可以启动程序和发送认证 header，只有受信任项目才应启用其 MCP Server。

## 文件组织

```text
MewCode/
├── pyproject.toml                         # 新增 httpx 直接依赖
├── README.md                              # MCP 配置、命名、权限与边界说明
├── examples/
│   └── config.yaml                        # stdio / HTTP 配置示例
├── src/mewcode/
│   ├── cli.py                             # MCP 启动、注册、warning、finally 关闭
│   ├── tools/
│   │   └── base.py                        # TOOL 权限目标与可选 argument
│   ├── permissions/
│   │   ├── config.py                      # deferred MCP namespace 规则
│   │   └── targets.py                     # 静态 TOOL 目标构造
│   └── mcp/
│       ├── __init__.py                    # 稳定公开入口
│       ├── models.py                      # 常量、配置、诊断、错误、结果模型
│       ├── config.py                      # 两层 MCP 配置解析与环境展开
│       ├── naming.py                      # 公开名与权限 namespace
│       ├── transport.py                   # Transport/factory Protocol
│       ├── stdio.py                       # stdio 子进程传输
│       ├── http.py                        # Streamable HTTP + SSE 传输
│       ├── jsonrpc.py                     # JSON-RPC peer 与 pending 配对
│       ├── session.py                     # MCP 握手、分页和 tools/call
│       ├── manager.py                     # 多 Server 管理与隔离
│       ├── tool.py                        # McpTool 与结果适配
│       └── runtime.py                     # 后台事件循环与跨线程桥
├── tests/
│   ├── mcp_stdio_fake.py                  # 真实子进程集成 fixture
│   ├── test_mcp_config.py                 # 合并、严格字段、环境、秘密
│   ├── test_mcp_naming.py                 # 合法名、规范化、截断、碰撞
│   ├── test_mcp_jsonrpc.py                # 配对、乱序、超时、取消、ping
│   ├── test_mcp_transports.py             # stdio、HTTP JSON/SSE、关闭
│   ├── test_mcp_session.py                # 握手、capability、分页、调用
│   ├── test_mcp_manager.py                # 并行启动、隔离、注册、路由
│   ├── test_mcp_runtime.py                # 线程桥、取消、幂等关闭
│   ├── test_mcp_tools.py                  # 权限声明、结果适配、Provider 格式
│   ├── test_mcp_integration.py            # stdio/HTTP/混合故障端到端
│   ├── test_permission_config.py          # 增补休眠 MCP 规则
│   ├── test_permission_targets.py         # 增补 TOOL(invoke) 目标
│   └── test_repl.py                       # 增补 CLI 启停与 warning 回归
└── docs/phase-6-mcp-client/
    ├── spec.md
    ├── plan.md
    ├── task.md                            # 下一阶段生成
    └── checklist.md                       # 后续阶段生成
```

不修改 Provider、Conversation、Agent Runner、Scheduler 或 REPL 文件。现有 `mewcode.config` 继续只负责模型 Profile；MCP 两层配置由 `mewcode.mcp.config` 独立读取，避免把项目文件误当作完整 Provider 配置。

## 技术决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| MCP 实现方式 | 为本阶段范围实现小型内部客户端，不引入通用 MCP SDK | 只需固定 `2025-11-25` 的 initialize/tools 子集；当前通用 SDK 会带入非目标能力和版本迁移面，内部层次可精确满足现有 Tool、权限和生命周期语义 |
| 协议版本 | 常量锁定 `2025-11-25`，Server 返回其他版本即失败 | 与批准的握手会话模型一致，避免隐式进入 `2026-07-28` 无握手语义 |
| 异步归属 | 全进程一个 MCP daemon thread 和一个长期事件循环 | 同步 REPL 等待输入时仍持续排空 stdio 和处理请求；避免跨 Server 多线程状态扩散 |
| 跨线程边界 | 只跨越 descriptor、`McpCallResult`、安全错误和 `ToolResult`；不暴露 Session、Transport 或 Future | 降低竞态与 loop affinity 风险，Agent 侧取消可映射到单个提交 future |
| HTTP 客户端 | 在 `pyproject.toml` 直接声明 `httpx>=0.28.1,<1` | 当前环境已有 0.28.1；AsyncClient 同时支持连接池、流式读取、TLS 和可注入 MockTransport，且不依赖 OpenAI 包的传递依赖契约 |
| HTTP 重定向 | `follow_redirects=False` | 防止静态认证 header 被发送到配置 URL 以外的目标，也让 endpoint 错配明确失败 |
| TLS | 使用 httpx/系统默认校验，无关闭开关 | 满足安全边界并避免首版引入危险配置 |
| HTTP Server 主动消息 | 只处理当前 POST 的 request-scoped SSE；不开长期 GET | 满足工具调用所需 Streamable HTTP，同时遵守“不做动态更新与恢复流”的范围 |
| SSE 恢复 | 读取但不使用 event id/retry，不发送 `Last-Event-ID` | 本阶段不做断点续传；连接中断按当前调用失败处理 |
| stdio 启动 | `create_subprocess_exec(command, *args)`，不传 `shell=True` | 保持 argv 边界，不允许配置经过 shell 二次解释 |
| stdio stderr | 持续 drain 后丢弃 | 防止管道死锁，并避免不可信 Server 日志或秘密进入 MewCode 输出 |
| 消息大小 | 协议消息 4 MiB，适配后工具文本 20,000 字符 | 前者限制内存与恶意 framing，后者保持现有 Agent 上下文行为 |
| 请求 id | 每个 Peer 从 1 递增的整数 | 简单、确定、可测；不同 Server 的 Peer 独立，不要求全局唯一 |
| 超时 | 单 Server 启动 30 秒、工具请求 120 秒、单 Session 关闭 5 秒；通过 `McpTimeouts` 注入测试值 | 所有外部等待有界，同时不向首版配置格式增加超时字段 |
| timeout 后 Session | 只失败当前 pending，Session 保持 READY | JSON-RPC 取消与迟到响应隔离足以继续；避免把一次慢调用等同于连接永久损坏 |
| fatal 条件 | EOF、Session 404、非法 framing、超限、无可信配对结构或 Transport 关闭 | 这些状态无法安全继续使用当前会话；后续快速失败且不重连 |
| 工具发现 | 启动时抓取全部分页并冻结快照 | 保持 Provider 工具前缀与权限规则稳定，不引入运行时注册竞态 |
| 工具定义错误 | 单工具 warning 并跳过；握手或分页根结构错误才失败整个 Server | 最大化健康工具可用性，同时不在不可信根协议状态上继续 |
| 名称规范化 | 原名可用时保持；否则非法字符替换、53 字符前缀和 10 位 SHA-256 | 同时满足两个 Provider 的 64 字符约束、确定性与低碰撞；显式 collision set 负责最终正确性 |
| 注册顺序 | descriptor 和 Provider 均按 public name 排序 | 相同输入获得稳定工具定义与 prompt cache 前缀；不依赖 YAML 或 Server 返回顺序 |
| ToolRegistry 组合 | 启动后一次性用 builtin 和 MCP proxies 构造，不增加动态 `register` | 工具快照固定，避免扩大现有注册表 API 和运行期并发面 |
| MCP 工具安全性 | 全部 `SIDE_EFFECT` 和 `TOOL(invoke)` | 不信任 Server annotations；沿用现有独占调度和人工确认，符合已批准权限粒度 |
| 离线工具权限规则 | 只对已配置 MCP namespace 允许未知规则休眠 | Server 临时失败不破坏其他工具启动；任意其他未知工具仍保持现有 fail-closed 校验 |
| 工具调用错误 | JSON-RPC error、`isError` 和 timeout 转 `ToolResult`，不停止 Agent Loop | 与现有工具失败恢复路径一致；只有 Session fatal 状态影响后续调用 |
| 结果序列化 | 文本顺序保留，structuredContent 用 sort-keys JSON，二进制只给标记 | 结果稳定可读，不把 Base64 注入模型，也不触发资源能力 |
| 清理策略 | CLI `finally`、Manager 并行 close、Runtime 幂等 stop/join | 覆盖正常退出、配置后续失败、取消和部分启动，不让单个清理错误遮蔽原退出状态 |
| 测试替身 | 内存 Transport 测 Peer/Session，httpx MockTransport 测 HTTP，真实轻量子进程测 stdio | 核心测试快速确定，关键 OS framing/lifecycle 仍有真实边界证据，无需外部 Server 或网络 |

## Spec 覆盖映射

| Spec 范围 | Plan 归属 |
|-----------|-----------|
| F1-F7 配置发现、合并、字段与环境展开 | `mcp.config`、配置模型、CLI 启动、配置测试 |
| F8-F14 连接、握手、JSON-RPC、超时 | Runtime、Manager、Session、Peer、两种 Transport 及交互时序 |
| F15-F19 分页、命名、注册、静态快照 | Session、naming、Manager、Runtime/ToolRegistry 组合 |
| F20-F23 权限与独占调度 | McpTool 声明、`PermissionTargetKind.TOOL`、deferred rules、现有 Scheduler |
| F24-F28 调用、结果和错误 | Tool proxy、Runtime bridge、Session.call_tool、结果适配器 |
| F29-F32 缓存、隔离与关闭 | Manager Session cache、Runtime 长生命周期、fatal 状态机、并行 close |
| N1-N3 可靠性、隔离、协议兼容 | timeout、独立 Peer/Session、固定协议与 Transport 合规 |
| N4-N5 向后兼容与异步安全 | 条件式 CLI 集成、后台 loop confinement、pending 单终态 |
| N6-N9 执行安全、秘密、外部输入与资源 | 无 shell、TLS/redirect、脱敏错误、4 MiB/20k 上限、严格解析 |
| N10-N13 确定性、可移植、可测与可维护 | 名称/排序算法、跨平台 stdio close、分层 fake、无环模块依赖 |
