# 上下文管理与两层压缩 Plan

## 架构概览

采用会话级 `ContextManager` 作为统一上下文管理入口，由 CLI 创建，并同时注入 `Conversation` 与 `AgentRunner`。

`AgentRun` 仍负责模型迭代和工具调度，但每次调用 Provider 前必须把完整候选请求交给 `ContextManager` 预检。预检依次完成容量估算、自动重量压缩判断和请求重建；工具执行完成后，在转换为 Provider 消息之前先由轻量压缩器处理结果。这样 OpenAI 与 Anthropic 共用同一套阈值和存盘策略。

`Conversation` 负责会话级能力：持有当前完整活动历史、路由 `/compact`、维护活动操作的取消边界，并在运行结果完成后用完整的已提交历史替换旧历史，而不再只追加新消息。正常退出时由 Conversation 关闭上下文会话并触发清理。

上下文管理器内部划分为五个协作组件：

- `TokenEstimator`：维护最近一次实际 input usage 锚点、请求内容足迹和增量字符估算。
- `ContextArchive`：创建隔离会话目录，原子写入工具结果与早期历史，并负责活动锁和生命周期清理。
- `ToolResultCompactor`：对同一轮工具执行结果应用 8K / 12K / 1K 规则，输出供 Provider 转换的轻量结果。
- `HistoryCompactor`：选择近期保留区、构造无工具摘要请求、校验固定章节、生成滚动摘要和边界消息。
- `CompactionCircuitBreaker`：维护连续失败次数、自动熔断状态及 `/compact` 成功后的恢复。

现有 `ChatMessage` 增加 Provider 无关的消息类别和原子分组标识。上下文层只依赖这些元数据来识别用户原文、工具交换、滚动摘要和安全切分点，不解析 OpenAI 或 Anthropic 的内部内容结构；具体请求格式仍由各 Provider 适配器负责。

所有压缩采用“副本计算、最后提交”：

1. 在历史副本上选择和预处理候选内容。
2. 通过临时文件加原子替换完成存盘。
3. 调用摘要 Provider 并校验正式摘要。
4. 全部成功后一次性提交新历史。
5. 失败或取消时保留原活动历史，仅更新允许变化的失败计数和状态。

`AgentRunOutcome` 携带完整的最终已提交历史。这样即使一次 Agent Run 内发生重量压缩，或当前运行后来因 Provider 错误停止，Conversation 也能准确保存已经成功提交的压缩结果与合法工具交换。

## 核心数据结构与接口

### 配置

```python
DEFAULT_CONTEXT_WINDOW = 128_000

@dataclass(frozen=True)
class ProviderProfile:
    ...
    context_window: int = DEFAULT_CONTEXT_WINDOW

@dataclass(frozen=True)
class ContextConfig:
    context_window: int
    single_tool_tokens: int = 8_000
    tool_batch_tokens: int = 12_000
    tool_preview_tokens: int = 1_000
    recent_tokens: int = 10_000
    recent_messages: int = 5
    automatic_margin: int = 13_000
    manual_margin: int = 3_000
    summary_max_output_tokens: int = 8_192
    failure_limit: int = 3
```

`context_window` 必须大于摘要最大输出与自动安全余量之和；当前最低合法值为 21193。配置层拒绝布尔值、浮点值和非正整数。

### Provider 无关消息元数据

```python
class MessageKind(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    INTERNAL = "internal"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    SUMMARY = "summary"
    BOUNDARY = "boundary"

@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: Any
    kind: MessageKind = MessageKind.ASSISTANT
    group_id: str | None = None
```

- `kind` 只描述上下文语义，不替代 Provider 的 `role` 和 `content`。
- 一次模型工具响应及其全部结果共享同一个 `group_id`，近期区切分只能发生在分组之间。
- 用户消息、普通助手回答、滚动摘要与边界各自形成独立分组。
- Provider 负责创建带正确 `kind` 的消息；上下文层不得解析 Provider 私有内容结构。
- 摘要与边界使用系统语义消息。OpenAI 保持系统消息；Anthropic 在构造请求时将它们提升到动态 system 内容，不把非法 system role 放入 messages。

### Token usage 与请求足迹

```python
@dataclass(frozen=True)
class TokenUsage:
    ...
    context_input_tokens: int | None = None

@dataclass(frozen=True)
class CharacterMeasure:
    weighted_characters: int

@dataclass(frozen=True)
class RequestFootprint:
    measure: CharacterMeasure
    message_count: int
    signature: str

@dataclass(frozen=True)
class TokenEstimate:
    input_tokens: int
    anchored: bool
    footprint: RequestFootprint
```

- OpenAI 的 `context_input_tokens` 等于完整 input tokens。
- Anthropic 的值为非缓存输入、缓存读取和缓存写入三部分之和，避免低估实际上下文占用。
- fake 或兼容 Provider 未提供该字段时回退到 `input_tokens`。
- 字符估算使用保守权重：ASCII 字符每 4 个约 1 Token，非 ASCII 字符每个约 1 Token。
- `TokenEstimator.estimate(request)` 返回当前估算和请求足迹。
- `TokenEstimator.observe(footprint, usage)` 用实际 context input usage 替换锚点。
- 当前估算为“锚点 Token + 当前足迹与锚点足迹的加权字符差”；没有锚点时估算完整请求。
- 消息、提示和稳定工具定义分别缓存字符量，正常追加历史时只计算新增对象。

### 存盘记录

```python
class ArchiveKind(StrEnum):
    TOOL_RESULT = "tool_result"
    HISTORY = "history"

@dataclass(frozen=True)
class ArchiveRecord:
    kind: ArchiveKind
    relative_path: str
    estimated_tokens: int
    sequence: int
```

```python
class ContextArchive:
    def start(self) -> tuple[ContextStatus, ...]: ...
    def write_tool_result(self, execution: ToolExecution) -> ArchiveRecord: ...
    def write_history(self, messages: Sequence[ChatMessage]) -> ArchiveRecord: ...
    def close(self) -> tuple[ContextStatus, ...]: ...
```

所有写入先落到同目录临时文件，再通过原子替换发布。文件名仅由会话 UUID 和递增序号生成。`relative_path` 使用工作区相对路径，供模型通过现有读取工具重新读取。

每个会话目录持有跨平台排他锁。启动清理只删除能够取得锁的遗留目录，不触碰仍由其他 MewCode 进程持有的活动目录。

### 轻量压缩结果

```python
@dataclass(frozen=True)
class ToolCompactionResult:
    executions: tuple[ToolExecution, ...]
    archives: tuple[ArchiveRecord, ...]
    statuses: tuple[ContextStatus, ...]
```

```python
class ToolResultCompactor:
    def compact(
        self,
        executions: Sequence[ToolExecution],
    ) -> ToolCompactionResult: ...
```

返回的新 `ToolExecution` 保留原调用编号、工具名、成功状态和必要错误语义，但 Provider 可见负载替换为统一存盘占位。原始执行结果只写入归档，不在后续活动消息中重复保存。

### 重量压缩操作

```python
class CompactionMode(StrEnum):
    AUTOMATIC = "automatic"
    MANUAL = "manual"

@dataclass(frozen=True)
class ContextPreparation:
    request: ModelRequest | None
    messages: tuple[ChatMessage, ...]
    footprint: RequestFootprint | None
    usage: TokenUsage
    changed: bool
```

```python
class ContextOperation:
    async def events(self) -> AsyncIterator[ContextStatus]: ...
    @property
    def outcome(self) -> ContextPreparation: ...
    async def cancel(self) -> None: ...
```

```python
class ContextManager:
    def prepare_request(
        self,
        request: ModelRequest,
    ) -> ContextOperation: ...

    def compact_history(
        self,
        messages: Sequence[ChatMessage],
    ) -> ContextOperation: ...

    def compact_tool_results(
        self,
        executions: Sequence[ToolExecution],
    ) -> ToolCompactionResult: ...

    def observe_usage(
        self,
        footprint: RequestFootprint,
        usage: TokenUsage,
    ) -> None: ...

    def close(self) -> tuple[ContextStatus, ...]: ...
```

- `prepare_request` 用于所有普通 Agent 请求，执行自动阈值判断。
- `compact_history` 只服务 `/compact`，强制尝试并使用 3K 余量。
- 操作先发出“开始”状态，再私下消费摘要流；正式结果通过 `outcome` 取得。
- 摘要请求失败时 `request` 为 `None`，调用方不得继续调用主模型。
- 摘要成功后，`messages` 是滚动摘要、边界和近期原文组成的新活动历史。
- 自动摘要完成后重新估算主请求；若一次摘要后仍不安全，本次预检直接失败，不在同一操作中再次摘要。

### 状态与熔断

```python
class ContextStatusKind(StrEnum):
    TOOL_ARCHIVED = "tool_archived"
    COMPACTION_STARTED = "compaction_started"
    COMPACTION_COMPLETED = "compaction_completed"
    NO_COMPACTION_NEEDED = "no_compaction_needed"
    COMPACTION_FAILED = "compaction_failed"
    CIRCUIT_OPEN = "circuit_open"
    CIRCUIT_RECOVERED = "circuit_recovered"
    CLEANUP_WARNING = "cleanup_warning"

@dataclass(frozen=True)
class ContextStatus:
    kind: ContextStatusKind
    message: str
    usage: TokenUsage = TokenUsage.zero()
```

```python
@dataclass
class CompactionCircuitBreaker:
    consecutive_failures: int = 0
    is_open: bool = False

    def record_failure(self) -> None: ...
    def record_success(self) -> bool: ...
```

用户取消不计为摘要失败。其他 Provider 错误、容量拒绝、输出截断、空响应和结构校验失败均计数。`record_success` 返回本次是否从熔断状态恢复，以便发出恢复状态。

### Agent 运行结果

```python
@dataclass(frozen=True)
class AgentRunOutcome:
    ...
    new_messages: tuple[ChatMessage, ...]
    committed_history: tuple[ChatMessage, ...]
```

`new_messages` 保留现有调用方和测试所需的本轮消息视图；`committed_history` 是压缩和运行停止语义处理后的完整历史。Conversation 每轮结束后用 `committed_history` 整体替换当前历史，从而正确保存运行中发生的压缩。

## 模块设计

### 上下文模型与估算

`context/models.py`

职责：

- 定义上下文阈值、状态、操作结果、归档记录和熔断状态。
- 集中保存 8K / 12K / 1K、10K、13K / 3K、8192 和失败 3 次等常量默认值。
- 校验配置内部不变量。

`context/estimator.py`

职责：

- 把 Prompt、消息和排序后的工具定义转换为稳定请求足迹。
- 缓存不可变消息、稳定 Prompt 和工具定义的字符权重。
- 维护最近一次实际 usage 锚点。
- 支持压缩导致的负增量，不让估算值降到零以下。
- 生成单条消息、单个工具结果和整个请求共用的近似 Token 估算。

依赖方向：只依赖通用 Provider/工具模型，不依赖 Agent、Conversation 或 REPL。

### 会话归档

`context/archive.py`

职责：

- 在 `.mewcode/context/<session-uuid>/` 建立当前会话目录和活动锁。
- 将完整工具结果保存为带版本、调用编号、工具名、成功状态、内容、错误和 metadata 的 UTF-8 JSON。
- 将早期历史保存为带版本、角色、消息类别、分组编号和原始内容的 UTF-8 JSON。
- 使用递增序号生成 `tool-000001.json`、`history-000002.json` 等名称。
- 通过同目录临时文件和原子替换发布记录。
- 摘要失败时删除尚未被历史引用的早期历史归档；删除失败只产生清理警告。
- 正常关闭时释放锁并删除当前会话目录。
- 启动时尝试取得旧目录锁，只清理未被其他进程持有的目录。

锁实现隐藏在平台适配函数中：Windows 使用文件区域锁，类 Unix 使用 advisory file lock。其他模块只调用统一的锁接口。

### 轻量工具结果压缩

`context/tool_results.py`

职责：

1. 将每个 `ToolResult` 序列化为两个 Provider 共用的规范 JSON 负载。
2. 估算每个完整负载的 Token。
3. 先选出单体超过 8K 的结果。
4. 再计算替换预览后的批次总量；若仍超过 12K，按“原始估算降序、执行索引升序”继续选择。
5. 为选中结果写入归档，并生成最多 1K Token 的首尾预览。
6. 返回新的不可变 `ToolExecution` 集合。

存盘占位保留：

- 工具名和调用编号；
- 原始估算大小；
- 工作区相对读取路径；
- 首尾预览；
- 原成功/失败状态；
- 失败时的简短“完整错误已存盘”语义。

Provider 适配器共用工具层提供的规范负载序列化函数，移除当前两份重复实现。

Agent 仍先向终端发送原始 `AgentToolResult` 的短摘要；随后才压缩用于历史和下一次模型请求的结果，因此状态展示不会把存盘占位误报成工具真实输出。

### 重量历史压缩

`context/summary.py`

包含三个内部组件：

- `RecentHistorySelector`
- `SummaryPromptBuilder`
- `SummaryParser`

`RecentHistorySelector`：

- 按连续 `group_id` 形成原子消息组。
- 从尾部向前保留，直到同时达到 10K Token和 5 条消息。
- 永不拆开工具交换组。
- 现有滚动摘要和旧边界无条件加入待摘要输入，并在成功后统一替换，避免多份摘要或边界累积。
- 没有可压缩普通历史时返回无需压缩。

`SummaryPromptBuilder`：

- 使用专用稳定系统提示，不复用普通 Agent 行为 Prompt。
- 明确声明工具不可用、不得请求工具、不得臆测代码或文件内容。
- 要求输出以下边界：

```text
<analysis_draft>
...
</analysis_draft>
<formal_summary>
...
</formal_summary>
```

- 要求正式摘要严格使用八个已批准章节。
- 将早期消息的规范文本、完整历史归档路径和已有滚动摘要交给模型。
- 自动模式按 13K 余量校验摘要输入，手动模式按 3K 余量校验。
- 构造 `tools=None`、`max_output_tokens=8192` 的请求。

`SummaryParser`：

- 只接受自然结束的非空响应。
- 拒绝工具调用、输出上限结束、缺少边界、重复正式摘要、章节缺失、章节乱序或空章节未写“无”。
- 丢弃 `<analysis_draft>` 的全部内容。
- 返回不含草稿和外层标记的正式摘要正文。

摘要成功后生成两个系统语义消息：

1. `SUMMARY`：正式滚动摘要；
2. `BOUNDARY`：要求重新读取文件细节、禁止根据摘要脑补。

两条消息位于近期原文之前。Anthropic Provider 在请求构造时把它们加入动态 system 内容；OpenAI Provider 保持其系统消息语义。

### 上下文编排与熔断

`context/manager.py`

职责：

- 组合估算器、归档、轻量压缩器、重量压缩器和熔断器。
- 为每个普通 `ModelRequest` 执行统一预检。
- 在低于阈值时原样返回请求。
- 达到阈值且熔断关闭时，只尝试一次自动摘要。
- 达到阈值且熔断开启时，不调用摘要或主模型。
- 摘要成功后重建主请求并重新估算；仍不安全时提交有效压缩结果，但阻止本次主模型调用，等待用户再次处理。
- 将有 usage 的摘要请求记录为新的估算锚点，并把摘要成本计入操作 usage。
- 管理失败计数；用户取消不计失败。
- 为 `/compact` 创建强制手动操作，成功时恢复熔断器。
- 将内部错误转换为不包含归档内容和草稿的安全状态。

### Provider 公共模型与适配器

`providers/base.py`

修改：

- `ProviderProfile` 增加 `context_window`。
- `TokenUsage` 增加 `context_input_tokens`，并纳入加总逻辑。
- `ChatMessage` 增加 `kind` 与 `group_id`。
- `assistant_messages` 和 `tool_result_messages` 接受 Agent 分配的分组编号。

`providers/openai_provider.py`

修改：

- 为内部推理、助手文本、工具调用和工具结果设置正确消息类别及分组。
- 填充完整上下文 input usage。
- 继续原生发送系统语义摘要与边界消息。
- 使用统一工具结果负载序列化函数。

`providers/anthropic_provider.py`

修改：

- 为组合内容块和工具结果消息设置类别及分组。
- 将普通 input、cache read 和 cache write 合成为 `context_input_tokens`。
- 从消息序列中提取 `SUMMARY` 与 `BOUNDARY`，按原顺序追加到动态 system 内容，剩余对话消息保持合法角色。
- 使用统一工具结果负载序列化函数。

### Agent 集成

`agent/runner.py`

修改后的每次迭代顺序：

1. 构造 Prompt、候选消息、工具集和最大输出预算。
2. 启动 `ContextManager.prepare_request`。
3. 实时转发上下文状态。
4. 若预检允许，调用主 Provider。
5. 将主请求实际 usage 与对应足迹交回估算器。
6. Provider 请求工具后执行调度。
7. 转发原始工具结果短状态。
8. 对完整工具执行批次运行轻量压缩。
9. 用同一分组编号生成助手工具消息和压缩后结果消息。
10. 更新工作历史与已提交历史。

增加上下文专用停止原因，区分容量拒绝、摘要失败和普通 Provider 错误。

`AgentRun` 分别跟踪：

- `working_messages`：下一次请求候选历史；
- `committed_history`：即使后续请求失败也应保存的合法历史；
- `new_messages`：兼容现有调用方的本轮消息视图；
- 当前上下文操作：供取消路径停止摘要请求。

在首次成功模型响应前，当前用户消息仍未提交；若预检只压缩了旧历史而主请求失败，只提交压缩后的旧历史。工具批次完成后，当前用户消息、工具调用和结果一起进入已提交历史。

### Conversation 与 REPL

`conversation.py`

修改：

- 接收共享 `ContextManager`。
- 每轮结束用 `committed_history` 替换当前历史。
- 新增 `compact()`，拒绝并发运行，执行手动重量压缩且不创建用户消息。
- `cancel_active()` 同时支持 Agent Run 和手动压缩操作。
- 新增 `close()`，关闭上下文会话并返回清理警告。

`repl.py`

修改：

- 精确路由 `/compact`。
- `/compact` 带附加参数时输出用法错误，不把它发送给模型。
- 启动帮助加入 `/compact`。
- 渲染上下文状态，但不渲染摘要草稿或归档正文。
- 无论 `/exit`、EOF、异常还是外层中断，都在事件循环关闭前调用 `Conversation.close()`。

`cli.py`

修改：

- 从活动 Profile 创建 `ContextConfig`。
- 使用当前 Workspace 创建并启动会话归档与 `ContextManager`。
- 将启动清理警告写入 stderr。
- 把同一个管理器注入 AgentRunner 和 Conversation。

### 依赖约束

```text
providers + tools
       ↓
context models / estimator / archive / compactors
       ↓
context manager
       ↓
agent runner
       ↓
conversation
       ↓
repl / cli
```

上下文包不得导入 Agent、Conversation 或 REPL，从而避免循环依赖；用户界面只消费上下文状态，不参与压缩决策。

## 模块交互与数据流

### 普通请求与 Agent Loop

```text
用户输入
  -> Conversation 创建 AgentRun
  -> AgentRun 构造候选 ModelRequest
  -> ContextManager 轻量审计并估算完整输入
     -> 未达阈值：返回原请求
     -> 达到阈值：进入自动重量压缩
  -> AgentRun 调用主 Provider
  -> StreamCollector 收集响应与 usage
  -> TokenEstimator 用实际 usage 更新锚点
     -> 自然结束：提交助手回答
     -> 工具调用：进入工具批次
```

每次 Agent 迭代都重复此流程，包括 Plan 调查、Plan 最终生成、Execute 和 Direct 模式。阈值始终使用该次请求真实的最大输出预算。

### 工具结果轻量压缩

```text
Provider 工具调用
  -> ToolScheduler 执行并产生原始 ToolExecution
  -> AgentRun 向终端发送短工具状态
  -> ToolResultCompactor 估算整批结果
     -> 先选单体 > 8K
     -> 再按大小选择，直到保留量 <= 12K
  -> ContextArchive 原子写入选中结果
  -> 生成每项 <= 1K 的首尾预览占位
  -> Provider 把压缩后的 ToolExecution 转为协议消息
  -> 工作历史与已提交历史同步追加完整工具交换组
  -> 下一次 API 请求重新进入统一预检
```

若任一必需存盘失败：

- 不生成该批次的 Provider 工具结果消息；
- 不调用下一次模型；
- 已完成的工具调用仍可通过终端状态观察；
- 当前运行以上下文错误停止；
- 存盘失败前已提交的对话历史保持不变。

### 自动重量压缩成功路径

```text
主请求估算 >= context_window - 主请求 max_output - 13K
  -> 检查熔断器
  -> RecentHistorySelector 划分早期区和近期区
  -> ContextArchive 写入完整早期区
  -> 构造无工具、8192 输出预算的摘要请求
  -> 校验摘要输入 <= context_window - 8192 - 13K
  -> 发出“自动压缩开始”
  -> 当前 Provider 生成草稿和正式摘要
  -> 私下收集响应，不向终端转发文本 delta
  -> 记录摘要 usage 为最新估算锚点
  -> SummaryParser 校验并只提取正式摘要
  -> 创建 SUMMARY + BOUNDARY + 近期原文
  -> 熔断失败计数清零
  -> 用新历史重建原主请求
  -> 从摘要请求 usage 锚点估算重建请求
     -> 安全：调用主 Provider
     -> 仍不安全：提交有效压缩，但阻止本次主调用
```

一次普通请求预检最多调用一次摘要模型，不因压缩后仍超限而在内部继续循环。

### 自动重量压缩失败路径

以下情况统一视为摘要失败：

- 摘要输入自身超过安全边界；
- Provider 错误；
- 输出达到上限；
- 空响应；
- 返回工具调用；
- 草稿或正式摘要边界错误；
- 八个章节结构错误；
- 历史归档或正式发布失败。

处理顺序：

```text
失败
  -> 取消或删除未被引用的归档记录
  -> 保留原活动历史和旧滚动摘要
  -> 非用户取消：连续失败数 +1
  -> 发出安全失败状态
  -> 不调用主模型
  -> AgentRun 以上下文错误停止
```

用户主动取消不增加失败数，并沿用普通取消停止原因。

### 熔断状态机

```text
CLOSED(0)
  --失败--> CLOSED(1)
  --失败--> CLOSED(2)
  --失败--> OPEN(3)

OPEN
  --普通危险请求--> 请求前拒绝，不调用任何模型
  --普通安全请求--> 正常调用主模型
  --/compact 失败--> 保持 OPEN
  --/compact 成功--> CLOSED(0)，发出恢复状态

CLOSED(n)
  --任意摘要成功--> CLOSED(0)
  --用户取消--> 状态不变
```

熔断只禁止自动重量摘要，不禁止轻量工具存盘，也不禁止低于容量边界的普通请求。

### 手动 `/compact`

```text
/compact
  -> REPL 直接路由，不创建用户消息
  -> Conversation 检查没有其他活动操作
  -> ContextManager 使用 MANUAL 模式
  -> 先确认历史中的工具结果均已轻量处理
  -> RecentHistorySelector 查找早期区
     -> 无早期区：发出“无需压缩”，结束
     -> 有早期区：继续
  -> 写入完整早期历史
  -> 校验摘要输入 <= context_window - 8192 - 3K
  -> 调用一次无工具摘要请求
     -> 成功：Conversation 原子替换完整历史并恢复熔断
     -> 失败：保留原历史和当前熔断状态
```

`/compact` 的文本及其状态消息都不进入对话历史。

### 历史提交语义

Agent Run 维护两个历史视图：

```text
working_messages
  = 准备发送给下一次模型的候选历史

committed_history
  = 即使当前运行随后失败，也应由 Conversation 保存的合法历史
```

提交规则：

- 首次主模型成功响应前，当前用户消息不在 `committed_history`。
- 预检成功压缩旧历史后，压缩后的旧历史立即成为可提交状态。
- 工具批次只有在工具调用消息和压缩后结果消息都准备完成后才整体提交。
- 自然助手回答生成后与当前用户消息一起提交。
- Provider 输出截断或首次请求失败时，不提交部分助手文本。
- Agent Run 结束后，Conversation 用 `committed_history` 整体替换原历史。

### 摘要后的文件细节恢复

```text
后续模型读取 SUMMARY
  -> BOUNDARY 提醒摘要不是文件事实来源
  -> 模型需要具体代码或工具输出
  -> 调用现有 read_file 读取原工作区文件或归档路径
  -> 新读取结果再次接受轻量压缩规则
```

系统不自动重注入归档内容；读取行为继续经过现有工具权限与工作区路径约束。

### 会话启动与关闭

启动：

```text
CLI 创建 Workspace
  -> ContextArchive 扫描旧会话目录
  -> 能取得排他锁：视为遗留并删除
  -> 无法取得锁：视为其他活动进程并跳过
  -> 创建并锁定本会话目录
  -> 启动 REPL
```

关闭：

```text
/exit、EOF、异常或中断
  -> 取消活动 Agent/摘要操作
  -> Conversation.close()
  -> ContextArchive 释放活动锁并删除本会话目录
  -> 报告非敏感清理警告
  -> 关闭事件循环
  -> CLI 清理 MCP Runtime
```

## 文件组织

```text
MewCode/
├── src/mewcode/
│   ├── context/
│   │   ├── __init__.py             # 导出上下文管理公共类型
│   │   ├── models.py               # 配置、状态、归档、操作结果、熔断模型
│   │   ├── estimator.py            # 字符权重、请求足迹、usage 锚定
│   │   ├── archive.py              # 会话目录、原子写入、活动锁、生命周期清理
│   │   ├── tool_results.py         # 8K/12K/1K 轻量压缩
│   │   ├── summary.py              # 近期区选择、摘要 Prompt、响应解析
│   │   └── manager.py              # 自动/手动压缩编排与熔断
│   │
│   ├── providers/
│   │   ├── base.py                 # Profile、TokenUsage、ChatMessage 公共字段
│   │   ├── openai_provider.py      # 消息标记、context usage、系统摘要
│   │   ├── anthropic_provider.py   # 缓存 usage 合并、系统摘要提升
│   │   └── __init__.py             # 导出新增公共类型
│   │
│   ├── tools/
│   │   ├── base.py                 # 统一 ToolResult JSON 负载序列化
│   │   └── __init__.py             # 导出序列化入口
│   │
│   ├── agent/
│   │   ├── events.py               # 上下文状态事件和停止原因
│   │   ├── runner.py               # 每请求预检、工具批次压缩、提交历史
│   │   └── __init__.py             # 导出新增事件
│   │
│   ├── config.py                   # 解析并校验可选 context_window
│   ├── conversation.py             # /compact、完整历史替换、取消和关闭
│   ├── repl.py                     # 命令路由、状态渲染、可靠清理
│   └── cli.py                      # 创建并注入 ContextManager
│
├── tests/
│   ├── test_context_estimator.py   # 字符估算、缓存、锚点与增量
│   ├── test_context_archive.py     # 原子写入、路径安全、锁与清理
│   ├── test_context_tool_results.py# 单体/批次阈值、预览、稳定排序
│   ├── test_context_summary.py     # 保留区、Prompt、解析与滚动摘要
│   ├── test_context_manager.py     # 自动/手动触发、熔断、取消、容量拒绝
│   ├── test_context_integration.py # 两种 Provider 的端到端上下文流程
│   ├── fakes.py                    # 支持消息分组、摘要脚本和 context usage
│   ├── test_config.py              # context_window 默认与校验
│   ├── test_providers.py           # 公共 Provider 契约
│   ├── test_tool_providers.py      # 工具负载与消息元数据
│   ├── test_agent_runner.py        # 每次迭代预检和 committed_history
│   ├── test_conversation.py        # 手动压缩、替换、并发与关闭
│   └── test_repl.py                # /compact 路由、反馈和退出清理
│
├── examples/
│   └── config.yaml                 # 可选 context_window 示例
│
├── docs/
│   └── phase-7-context-management/
│       ├── spec.md
│       ├── plan.md
│       ├── task.md
│       └── checklist.md
│
└── README.md                       # 配置、自动压缩、/compact 与存盘生命周期
```

### 新增文件职责边界

- `models.py` 不执行 I/O，也不调用 Provider。
- `estimator.py` 不修改历史。
- `archive.py` 不决定压缩对象。
- `tool_results.py` 不理解 Provider 消息格式。
- `summary.py` 不维护熔断状态。
- `manager.py` 只做编排，不重复实现估算、存盘或解析逻辑。

### 现有文件修改边界

- Provider 文件只负责协议转换和 usage 归一化，不做阈值判断。
- Agent Runner 只调用上下文接口，不自行实现摘要规则。
- Conversation 只管理会话历史和活动操作，不解析摘要。
- REPL 只路由命令和渲染状态，不参与压缩决策。
- CLI 只负责对象装配和启动诊断。

### 依赖与构建

本阶段不新增第三方运行时依赖。跨平台文件锁、原子替换、JSON 存盘和清理全部使用 Python 标准库实现，因此 `pyproject.toml` 无需变更。

## 技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 上下文管理位置 | 共享会话级 `ContextManager`，同时接入 AgentRunner 与 Conversation | 同时覆盖每次 Provider 请求和 `/compact`，避免状态分裂 |
| K 的含义 | 阈值中的 K 使用十进制：8K=8000、12K=12000、13K=13000 | 与已确认的 128000 默认窗口口径一致 |
| 最小上下文窗口 | 必须大于 `8192 + 13000`，即至少 21193 | 保证摘要输出预算和自动安全余量至少能够同时存在 |
| 字符估算 | ASCII 每 4 字符约 1 Token，非 ASCII 每字符约 1 Token | 比统一除以 4 更适合中文，仍保持无 tokenizer 的低成本实现 |
| 估算范围 | 包含稳定/动态 Prompt、全部消息和排序后的工具定义 | 阈值必须针对真实请求输入，而不只是对话消息 |
| usage 锚点 | 使用 Provider 归一化后的完整上下文 input usage | Anthropic 缓存 Token 也占窗口；不能只看非缓存 input |
| 增量计算 | 保存上次请求足迹，以字符权重差修正实际 usage | 压缩后的负增量和新增消息都能统一处理 |
| 消息建模 | 扩展现有 `ChatMessage` 元数据，不重写为全新的对话 AST | 满足安全切分和 Provider 隔离，同时控制改造范围 |
| 工具结果压缩位置 | 在工具执行完成后、Provider 消息转换前处理 `ToolExecution` | 两种 Provider 共用一套规则，无需解析协议消息 |
| 批次预算计算 | 单体存盘后按占位实际估算重新计算；仍超 12K 才继续选最大项 | 保证发给模型的实际保留量满足预算 |
| 预览分配 | 1K 预算默认首尾各 500 Token；一侧不足时余额给另一侧 | 同时保留开头上下文和末尾错误/结论 |
| 归档格式 | 版本化 UTF-8 JSON | 能无损保存结构、稳定测试并便于现有读取工具查看 |
| 归档路径 | 工作区相对路径，名称只由 UUID 和序号生成 | 可由现有工具读取，且不受不可信工具内容控制 |
| 多进程清理 | 每个会话持有跨平台文件锁，启动时只删除可取得锁的旧目录 | 清理崩溃残留时不破坏同工作区的其他活动会话 |
| 摘要输入 | 把早期消息规范化为文本交给专用摘要 Prompt | 避免把孤立的 Provider 工具消息直接发送给无工具摘要请求 |
| 摘要调用 | 当前 Provider、单次请求、`tools=None`、8192 输出 | 符合已批准范围并避免重试循环 |
| 草稿处理 | 使用显式 XML 风格边界，完整收集后只提取正式摘要 | 能验证草稿与正式内容分离，且不向终端流式泄露草稿 |
| 摘要校验 | 严格验证边界、章节、顺序和空章节；语义正确性由 Prompt 与测试场景约束 | “仍有效约束”的语义无法用确定性解析器可靠判断 |
| 摘要消息角色 | 通用历史中使用系统语义；Anthropic 在适配层提升到 dynamic system | 不冒充用户原始消息，并维持 Provider 协议合法 |
| 滚动摘要 | 每次成功生成一份新摘要，旧摘要和旧边界强制进入替换区 | 防止摘要数量随压缩次数增长 |
| 自动压缩次数 | 每次主请求预检最多一次 | 满足无内部重试要求并防止 Token 消耗循环 |
| 压缩后仍超限 | 保存已成功压缩的历史，但阻止本次主模型调用 | 不丢弃有效工作，也不突破容量安全边界 |
| 失败提交 | 历史副本处理，成功后整体替换 | 保证工具组和摘要的原子性 |
| 失败计数 | Provider、容量、输出和结构失败计数；用户取消不计数 | 区分系统失败与用户主动终止 |
| 手动恢复 | `/compact` 在熔断时允许单次探测，成功立即复位 | 提供明确恢复通道而不自动循环 |
| 运行结果 | Outcome 同时保留本轮消息和完整 `committed_history` | 兼容现有测试，并正确保存运行中压缩 |
| 新依赖 | 不增加第三方依赖 | 标准库足以完成 JSON、原子替换和跨平台锁 |

## 需求追踪

| 需求 | 主要归属 |
|---|---|
| F1 | Profile 公共模型、配置加载、CLI 装配 |
| F2 | TokenEstimator、Provider context usage 归一化 |
| F3 | ContextManager、AgentRunner 请求预检 |
| F4-F6 | ToolResultCompactor、ContextArchive、统一工具负载 |
| F7 | ContextArchive、Conversation.close、REPL 生命周期 |
| F8 | ContextManager 自动阈值与请求重建 |
| F9 | Conversation.compact、REPL `/compact` 路由 |
| F10 | RecentHistorySelector、消息 `group_id` |
| F11-F12 | 历史归档、SummaryPromptBuilder、固定章节 |
| F13 | SummaryPromptBuilder、SummaryParser、当前 Provider |
| F14-F15 | 滚动摘要替换、SUMMARY/BOUNDARY 消息、Provider 适配 |
| F16-F18 | CompactionCircuitBreaker、ContextManager、手动恢复 |
| F19 | ContextStatus、Agent 事件、REPL 渲染 |
