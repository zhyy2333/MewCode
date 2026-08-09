# MewCode 权限系统 Plan

## 架构概览

权限系统作为工具注册与实际执行之间的统一前置管线接入。Provider、对话历史和工具协议保持不变；Agent Runner 仍把模型返回的工具调用交给 Tool Scheduler，Scheduler 在启动每个工具前完成参数校验、权限预检和必要的人工确认。

整体调用链如下：

```text
Provider 工具调用
  -> 工具存在性与参数 Schema 校验
  -> 构造规范化权限目标
  -> 不可绕过的黑名单或路径沙箱
  -> 分层规则匹配
  -> 权限模式裁决
  -> 必要时发出人工确认事件并等待选择
  -> 获准：按现有调度规则执行工具
  -> 拒绝：生成结构化失败结果
  -> 工具结果回写模型
  -> Agent Loop 继续
```

### 权限配置与会话状态

权限配置组件读取用户全局、项目共享和项目本地三个 YAML 文件，解析为独立规则集。缺失文件产生空规则集，任一现存文件格式错误则启动失败并给出配置错误，不在不完整策略下执行工具。

权限模式不写入规则文件。CLI 默认以 `default` 模式启动，可由 `--permission-mode strict|default|allow` 覆盖。运行期间，REPL 通过 `/permissions` 查询当前模式，通过 `/permissions <mode>` 修改当前会话模式。

会话状态组件保存当前权限模式和人工确认产生的精确临时规则。退出进程后会话规则消失；永久放行同时写入项目本地规则并加入当前会话规则。

### 权限目标与硬安全边界

每个内置工具声明自己的权限目标类型和安全相关参数：

- `run_command` 使用完整命令字符串。
- `read_file`、`write_file`、`edit_file` 使用规范化项目相对路径。
- `find_files` 使用受工作区约束的路径 glob。
- `search_code` 使用规范化搜索路径，未提供路径时使用项目根目录。

目标构造器只读取安全决策所需参数，不把文件内容、替换文本、搜索词或超时值带入提示和规则匹配。

命令黑名单和路径沙箱作为硬安全边界独立于可配置规则。权限预检首先调用它们；命令工具和文件工具在真正产生副作用前保留同源的最终防御检查，避免其他内部调用路径绕过统一管线。

### 规则仓库与匹配引擎

规则仓库按会话、项目本地、项目共享、用户全局保存四个有序规则集。匹配引擎逐层查找，并在单层内按照精确程度排序；它只返回当前最高优先级匹配的 `allow`、`deny` 或“未命中”，不负责权限模式和用户交互。

项目本地规则写入采用临时文件替换方式，先生成并校验完整 YAML，再原子替换目标文件。新增永久精确规则前先去重，已有其他规则保持不变。

### 权限决策引擎

权限决策引擎组合硬安全结果、规则匹配结果、当前权限模式和会话规则，输出以下三种状态之一：

- `allow`：可交给 Scheduler 执行。
- `deny`：转换为结构化工具失败结果。
- `ask`：创建一次等待用户选择的权限确认。

严格模式只自动接受当前会话已经确认的精确放行；默认模式采用明确规则并对未命中项询问；放行模式自动接受非 `deny` 调用。任何模式均不能覆盖硬安全拒绝或解析所得 `deny`。

### 人工确认与事件流

权限确认不直接从核心模块读取终端输入。Scheduler 在预检返回 `ask` 时发出权限请求事件，事件只包含调用标识、工具名和规范化权限目标，并携带一次性响应句柄。

REPL 收到事件后显示四个选项：拒绝、仅本次、本会话、永久。用户选择被写回响应句柄，Scheduler 恢复执行。其他界面或测试可以用相同事件提供自己的响应方式，不依赖终端实现。

每个权限结果再产生独立的权限决定事件，记录允许或拒绝、决定来源及安全类别；终端只渲染脱敏摘要。多个确认在实际工具启动前按模型调用顺序串行处理，之后获准的只读调用仍可按原有上限并发执行。

### 工具调度与 Agent Loop

Tool Scheduler 先对当前批次中的调用逐个进行权限预检：

- 未知工具和参数错误直接生成原有失败结果。
- 被权限拒绝的调用生成对应 `ToolExecution`，但不进入工具实现。
- 获准调用继续使用现有“只读批次并发、副作用调用独占”的执行策略。
- 批次最终结果仍按模型原始调用顺序提供给 Provider。

权限拒绝不增加新的 Agent 停止原因。Agent Runner 将其与普通工具失败一样写回会话，现有迭代、未知工具上限、取消和最终完成判断保持不变。

## 核心数据结构

### PermissionMode

```python
class PermissionMode(StrEnum):
    STRICT = "strict"
    DEFAULT = "default"
    ALLOW = "allow"
```

表示当前会话的整体权限上限。CLI 未指定时使用 `DEFAULT`。

### PermissionEffect、PermissionOutcome 与 PermissionChoice

```python
class PermissionEffect(StrEnum):
    ALLOW = "allow"
    DENY = "deny"


class PermissionOutcome(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


class PermissionChoice(StrEnum):
    DENY = "deny"
    ONCE = "once"
    SESSION = "session"
    PERMANENT = "permanent"
```

`PermissionEffect` 只用于规则；`PermissionOutcome` 是权限引擎的裁决；`PermissionChoice` 是用户对确认请求的响应。

### RuleScope 与 PermissionSource

```python
class RuleScope(StrEnum):
    SESSION = "session"
    PROJECT_LOCAL = "project_local"
    PROJECT = "project"
    USER = "user"


class PermissionSource(StrEnum):
    BLACKLIST = "blacklist"
    SANDBOX = "sandbox"
    SESSION_RULE = "session_rule"
    PROJECT_LOCAL_RULE = "project_local_rule"
    PROJECT_RULE = "project_rule"
    USER_RULE = "user_rule"
    MODE = "mode"
    USER_CONFIRMATION = "user_confirmation"
    CONFIG_ERROR = "config_error"
```

`RuleScope` 决定规则层级；`PermissionSource` 用于结构化结果和脱敏终端状态。

### ToolPermissionSpec

```python
class PermissionTargetKind(StrEnum):
    COMMAND = "command"
    PATH = "path"
    PATH_GLOB = "path_glob"


@dataclass(frozen=True)
class ToolPermissionSpec:
    argument: str
    kind: PermissionTargetKind
    default: str | None = None
```

每个工具通过 `permission_spec` 声明安全相关参数。现有工具映射如下：

| 工具 | 参数 | 类型 | 默认值 |
|---|---|---|---|
| `run_command` | `command` | `COMMAND` | 无 |
| `read_file` | `path` | `PATH` | 无 |
| `write_file` | `path` | `PATH` | 无 |
| `edit_file` | `path` | `PATH` | 无 |
| `find_files` | `pattern` | `PATH_GLOB` | 无 |
| `search_code` | `path` | `PATH` | `.` |

未声明权限目标的工具不能进入实际执行阶段，以失败关闭方式处理。

### PermissionTarget

```python
@dataclass(frozen=True)
class PermissionTarget:
    tool_name: str
    value: str
    kind: PermissionTargetKind

    def exact_rule(self) -> str:
        ...
```

`value` 已完成首尾空白处理或路径规范化，可直接用于规则匹配、确认提示和精确规则生成。`exact_rule()` 生成类似 `run_command(git status)` 的表达式；目标中的反斜杠和 glob 元字符会被转义，保证自动生成的规则保持精确语义。

### PermissionRule

```python
@dataclass(frozen=True)
class PermissionRule:
    tool_name: str
    pattern: str
    effect: PermissionEffect
    scope: RuleScope
    is_exact: bool
    specificity: tuple[int, int, int]
```

`specificity` 依次记录精确或 glob、固定文本数量和路径段长度。候选规则按该值降序排列；值相同时 `deny` 优先。

### PermissionRuleSets

```python
@dataclass(frozen=True)
class PermissionRuleSets:
    session: tuple[PermissionRule, ...]
    project_local: tuple[PermissionRule, ...]
    project: tuple[PermissionRule, ...]
    user: tuple[PermissionRule, ...]
```

加载后保持四层分离，不提前合并，以免丢失层级优先语义。会话规则由可变仓库在运行期维护，对外仍以不可变快照参与匹配。

### PermissionMatch

```python
@dataclass(frozen=True)
class PermissionMatch:
    rule: PermissionRule
    source: PermissionSource
```

只表示最高优先级层中胜出的规则；低层匹配不包含在结果里。

### PermissionDecision

```python
@dataclass(frozen=True)
class PermissionDecision:
    outcome: PermissionOutcome
    target: PermissionTarget | None
    source: PermissionSource
    reason: str
    match: PermissionMatch | None = None
```

黑名单或沙箱可在目标不可安全构造时返回 `target=None`。`reason` 是适合模型和终端使用的短消息，不包含规则文件全文或敏感参数。

### ValidatedToolCall

```python
@dataclass(frozen=True)
class ValidatedToolCall:
    request: ToolCallRequest
    tool: Tool
```

表示工具存在且参数 Schema 已通过校验。只有该结构可以进入权限预检和实际执行接口。

### PermissionChallenge

```python
class PermissionChallenge:
    prompt_id: str
    tool_call_id: str
    tool_name: str
    target: str

    def resolve(self, choice: PermissionChoice) -> None:
        ...

    def cancel(self) -> None:
        ...

    async def wait(self) -> PermissionChoice:
        ...
```

一次性确认句柄内部持有当前事件循环的 Future。重复响应被拒绝；普通 EOF 由 REPL 显式响应 `DENY`，Agent 或 Schedule 取消则取消等待并进入现有取消流程，不遗留等待任务。

### 权限 Agent 事件

```python
@dataclass(frozen=True)
class AgentPermissionRequest:
    run_id: str
    iteration: int
    challenge: PermissionChallenge


@dataclass(frozen=True)
class AgentPermissionDecision:
    run_id: str
    iteration: int
    tool_call_id: str
    tool_name: str
    target: str | None
    outcome: PermissionOutcome
    source: PermissionSource
    reason: str
```

两种事件加入 `AgentEvent` 联合类型。请求事件供界面收集用户选择；决定事件供终端显示和自动化测试观察。

## 规则文件格式

三个持久化文件使用相同 YAML 结构：

```yaml
rules:
  - rule: "run_command(git status)"
    result: allow

  - rule: "run_command(git push *)"
    result: deny

  - rule: "write_file(src/**)"
    result: allow
```

文件位置固定为：

```text
用户全局：~/.mewcode/permissions.yaml
项目共享：<workspace>/.mewcode/permissions.yaml
项目本地：<workspace>/.mewcode/permissions.local.yaml
```

根节点必须是 YAML 对象；`rules` 缺失时视为空列表。每项必须只包含非空 `rule` 和合法 `result`。解析时使用实际注册工具名集合校验规则，非法工具名、括号结构、转义序列、结果值或字段类型统一抛出 `PermissionConfigError`。

规则模式使用反斜杠转义字面量反斜杠和 glob 元字符：`\\`、`\*`、`\?`、`\[`、`\]`。只有未转义的 glob 元字符会使规则成为 glob；因此人工确认可以为包含通配符字符的真实命令或文件名生成不会扩大的精确规则。

项目 `.gitignore` 调整为允许提交 `.mewcode/permissions.yaml`，同时继续忽略 `.mewcode/config.yaml`、`.mewcode/permissions.local.yaml` 和其他本地状态。

## 核心接口

### PermissionConfigLoader

```python
@dataclass(frozen=True)
class PermissionPaths:
    user: Path
    project: Path
    project_local: Path

    @classmethod
    def for_workspace(
        cls,
        workspace: Workspace,
        user_home: Path | None = None,
    ) -> "PermissionPaths":
        ...


class PermissionConfigLoader:
    def load(
        self,
        paths: PermissionPaths,
        known_tools: set[str],
    ) -> PermissionRuleSets:
        ...
```

负责读取 UTF-8 YAML、验证完整结构并标注规则来源。缺失文件返回空层；存在但无效的文件抛出带文件路径的配置错误。

```python
class PermissionConfigWriter:
    def add_local_allow(
        self,
        path: Path,
        target: PermissionTarget,
        known_tools: set[str],
    ) -> tuple[PermissionRule, ...]:
        ...
```

写入器返回重新读取并成功落盘后的完整项目本地规则，供仓库原子更新内存快照。

### PermissionRuleStore

```python
class PermissionRuleStore:
    def __init__(
        self,
        rule_sets: PermissionRuleSets,
        local_writer: LocalRuleWriter,
    ) -> None:
        ...

    def snapshot(self) -> PermissionRuleSets:
        ...

    def match(self, target: PermissionTarget) -> PermissionMatch | None:
        ...

    def add_session_allow(self, target: PermissionTarget) -> None:
        ...

    async def persist_project_local_allow(
        self,
        target: PermissionTarget,
    ) -> None:
        ...
```

`LocalRuleWriter` 是规则模块声明的窄协议，配置写入器以鸭子类型实现；规则模块不反向导入配置模块。`match()` 实现层级与具体度选择。永久写入前重新读取并验证磁盘上的项目本地文件，把精确放行合并到最新有效规则；随后在线程中完成同目录临时文件、完整 YAML 校验和原子替换。成功后同时更新内存中的项目本地规则。相同精确 `allow` 已存在时不重复写入；磁盘文件已变为无效内容时拒绝写入和当前调用。

### PermissionTargetBuilder

```python
class PermissionTargetBuilder:
    def build(
        self,
        call: ValidatedToolCall,
        workspace: Workspace,
    ) -> PermissionTarget | PermissionDecision:
        ...
```

构造规范化目标并运行硬安全检查：

- 命令先检查不可配置黑名单。
- 普通路径先解析符号链接并验证工作区边界。
- 路径 glob 拒绝绝对模式和 `..` 越界，并验证无通配符前缀及搜索结果边界。
- 硬拒绝直接返回 `PermissionDecision(DENY, ...)`。

### PermissionRuleMatcher

```python
class PermissionRuleMatcher:
    def match(
        self,
        target: PermissionTarget,
        rule_sets: PermissionRuleSets,
    ) -> PermissionMatch | None:
        ...
```

命令使用大小写敏感的完整字符串 glob；路径先转换为 `/` 分隔，并按当前平台文件系统语义处理大小写。路径 `*` 不跨 `/`，`**` 可跨目录。

### PermissionController

```python
class PermissionController:
    @property
    def mode(self) -> PermissionMode:
        ...

    def set_mode(self, mode: PermissionMode) -> None:
        ...

    def evaluate(
        self,
        call: ValidatedToolCall,
    ) -> PermissionDecision:
        ...

    async def apply_choice(
        self,
        decision: PermissionDecision,
        choice: PermissionChoice,
    ) -> PermissionDecision:
        ...
```

`evaluate()` 依次执行目标构造、硬安全检查、规则匹配和模式裁决。返回 `ASK` 时由 Scheduler 创建确认句柄。

`apply_choice()` 把用户选择转成最终 `ALLOW` 或 `DENY`。`SESSION` 增加会话精确规则；`PERMANENT` 必须先成功持久化本地规则，再增加会话规则并允许执行。写入失败返回 `CONFIG_ERROR` 拒绝。

### ToolRegistry 执行接口

```python
class ToolRegistry:
    def validate_call(
        self,
        request: ToolCallRequest,
    ) -> ValidatedToolCall | ToolResult:
        ...

    async def execute_validated(
        self,
        call: ValidatedToolCall,
    ) -> ToolResult:
        ...

    async def execute(
        self,
        request: ToolCallRequest,
    ) -> ToolResult:
        ...
```

现有未知工具、参数校验和异常包装拆分为前后两步。Scheduler 使用 `validate_call()` 和 `execute_validated()`，确保权限只发生在有效调用上。`execute()` 保留为组合式兼容入口，但生产 Agent 路径只经过 Scheduler；工具自身继续保留硬安全复检。

### ToolScheduler

```python
class ToolScheduler:
    def __init__(
        self,
        permissions: PermissionController,
        max_read_concurrency: int = 4,
    ) -> None:
        ...
```

Scheduler 必须显式接收权限控制器，不提供隐式“全部允许”默认值。测试使用明确构造的规则、模式和脚本化确认响应。

### REPL 权限接口

```python
class Repl:
    def _handle_permission_request(
        self,
        event: AgentPermissionRequest,
    ) -> None:
        ...

    def _handle_permissions_command(
        self,
        user_text: str,
    ) -> bool:
        ...
```

确认处理将终端输入映射到 `PermissionChoice` 并立即解析事件句柄。模式命令只修改 `PermissionController` 的会话状态，不调用 Provider，也不写入 YAML。

## 模块设计

### 工具基础模型与注册表

**位置：** `mewcode.tools.base`

**职责：**

- 在 `Tool` 协议中增加必需的 `permission_spec` 元数据。
- 定义 `PermissionTargetKind`、`ToolPermissionSpec` 和 `ValidatedToolCall`。
- 将现有工具注册表执行过程拆成“查找与参数校验”和“执行已校验调用”两步。
- 保留现有工具异常包装与结构化失败结果。

**对外接口：**

- `ToolRegistry.validate_call()`
- `ToolRegistry.execute_validated()`
- `ToolRegistry.execute()`
- `Tool.permission_spec`

**依赖：**

- 只依赖标准库。
- 不依赖权限控制器、Agent、REPL 或配置加载器，避免底层工具抽象反向依赖上层策略。

### 不可配置命令安全规则

**位置：** `mewcode.tools.safety`

**职责：**

- 保存不可由 YAML 修改的危险命令正则。
- 编译并以大小写不敏感方式匹配命令。
- 返回稳定的危险类别和脱敏原因。
- 同时供权限预检和命令启动前复检使用。

**对外接口：**

- `check_dangerous_command(command)`
- `DangerousCommandMatch`

**依赖：**

- 只依赖标准库正则模块。
- 不读取配置，不接收权限模式，不提供动态注册接口。

### 工作区路径边界

**位置：** `mewcode.tools.workspace`

**职责：**

- 延续普通路径的绝对化、符号链接解析和项目边界判断。
- 增加路径 glob 的规范化与静态前缀检查。
- 拒绝绝对 glob、包含越界 `..` 的 glob，以及解析后位于项目外的固定前缀。
- 提供统一 `/` 分隔的项目相对路径和相对 glob。
- 为查找工具逐个验证实际匹配结果，避免符号链接结果越界。

**对外接口：**

- `Workspace.resolve_path()`
- `Workspace.relative_path()`
- `Workspace.normalize_glob()`
- `Workspace.validate_match()`

**依赖：**

- 只依赖标准库路径功能。
- 不依赖规则匹配或用户确认。

### 权限领域模型

**位置：** `mewcode.permissions.models`

**职责：**

- 定义权限模式、规则效果、决策结果、用户选择、规则层级和决定来源。
- 定义规范化目标、规则、规则集合、匹配结果和权限决定。
- 实现一次性 `PermissionChallenge`，管理确认 Future、重复响应和取消。

**对外接口：**

- 所有已批准的权限枚举与数据类。
- `PermissionChallenge.resolve()`、`cancel()` 和 `wait()`。

**依赖：**

- 依赖标准库以及 `mewcode.tools.base` 中的目标类型。
- 不依赖配置、规则算法、Agent 或终端。

### 权限配置加载与持久化

**位置：** `mewcode.permissions.config`

**职责：**

- 计算用户、项目共享和项目本地权限文件位置。
- 读取 UTF-8 YAML 并验证根节点、规则项、工具名、括号语法与结果值。
- 把规则表达式拆为工具名和模式，并标注来源层级。
- 将永久精确放行追加到项目本地数据模型。
- 在同一目录生成临时文件，校验后原子替换本地权限文件。
- 写入失败时保持旧文件不变并抛出脱敏配置错误。

**对外接口：**

- `PermissionPaths.for_workspace()`
- `PermissionConfigLoader.load()`
- `PermissionConfigWriter.add_local_allow()`
- `PermissionConfigError`

**依赖：**

- 依赖 PyYAML、权限领域模型、规则解析函数和工具名集合。
- 不依赖 Agent、Scheduler 或 REPL。

### 规则解析与匹配

**位置：** `mewcode.permissions.rules`

**职责：**

- 识别精确规则和 glob 规则。
- 将命令 glob 与路径 glob 编译成各自的完整匹配器。
- 计算确定性的规则具体度。
- 在单层内选择最具体匹配，并在并列时让 `deny` 胜出。
- 按会话、项目本地、项目共享、用户全局逐层停止查找。
- 管理会话精确放行和持久层内存快照。

**对外接口：**

- `parse_rule()`
- `PermissionRuleMatcher.match()`
- `PermissionRuleStore.snapshot()`
- `PermissionRuleStore.match()`
- `PermissionRuleStore.add_session_allow()`
- `PermissionRuleStore.persist_project_local_allow()`

**依赖：**

- 依赖权限领域模型，并在本模块声明窄 `LocalRuleWriter` 协议。
- 不导入配置模块；具体写入器由 CLI 组合根注入。
- 不依赖工具实现、Agent 或终端。

### 权限目标构造与硬门禁

**位置：** `mewcode.permissions.targets`

**职责：**

- 根据工具的 `permission_spec` 提取唯一安全相关参数。
- 规范化命令、普通路径和路径 glob。
- 对命令调用执行黑名单预检。
- 对路径调用执行工作区沙箱预检。
- 返回规范化 `PermissionTarget` 或不可覆盖的拒绝决定。
- 不读取文件内容、替换文本、搜索词或其他无关参数。

**对外接口：**

- `PermissionTargetBuilder.build()`

**依赖：**

- 依赖工具基础模型、命令安全规则、工作区路径边界和权限领域模型。
- 不依赖规则文件、权限模式、Agent 或 REPL。

### 权限决策控制器

**位置：** `mewcode.permissions.controller`

**职责：**

- 保存当前会话权限模式。
- 组合目标构造、硬门禁、规则匹配和安全上限模式。
- 将用户确认选择转为最终决定。
- 管理本次、会话和永久三种放行范围。
- 永久写入失败时拒绝当前调用，不产生副作用。
- 生成适合工具结果和终端事件使用的脱敏原因。

**对外接口：**

- `PermissionController.mode`
- `PermissionController.set_mode()`
- `PermissionController.evaluate()`
- `PermissionController.apply_choice()`

**依赖：**

- 依赖权限模型、目标构造器和规则仓库。
- 不依赖 Agent 事件、Provider、Conversation 或 REPL。

### 权限包公共出口

**位置：** `mewcode.permissions.__init__`

**职责：**

- 只导出 CLI、Scheduler、测试和工具元数据需要使用的稳定公共类型。
- 不在包初始化时构造工作区、读取配置或创建 Future。
- 控制导入顺序，避免 `tools -> permissions -> tools` 循环。

### Agent 权限事件

**位置：** `mewcode.agent.events`

**职责：**

- 增加 `AgentPermissionRequest` 和 `AgentPermissionDecision`。
- 把两种事件加入统一 `AgentEvent` 类型。
- 保持 Provider 事件、工具调用事件和停止原因不变。

**依赖：**

- 依赖权限领域模型。
- 不依赖终端输入或规则文件。

### 权限感知工具调度

**位置：** `mewcode.agent.scheduler`

**职责：**

- 显式接收 `PermissionController`。
- 在每批工具启动前依次完成注册表校验和权限预检。
- 对 `ask` 创建确认句柄、发出请求事件并等待响应。
- 发出每项最终权限决定事件。
- 为拒绝项生成结构化 `ToolExecution`，不调用工具实现。
- 仅把获准调用交给现有只读并发或副作用串行执行逻辑。
- 取消时解析或取消活动确认，并保证未获准工具不启动。

**对外接口：**

- 保持 `ToolScheduler.schedule()` 和 `ToolSchedule.events()` 的整体形态。
- `ToolScheduler` 构造时新增必需的权限控制器。
- `ToolSchedule.cancel()` 同时处理活动工具任务和活动确认。

**依赖：**

- 依赖工具注册表、权限控制器和 Agent 事件。
- 不读取 YAML，不直接读取终端输入。

### Agent Runner 与 Conversation

**位置：** `mewcode.agent.runner`、`mewcode.conversation`

**职责：**

- 继续转发 Scheduler 产生的所有事件。
- 将权限拒绝的 `ToolExecution` 与其他工具结果一起回写 Provider。
- 不新增权限停止原因，不因权限拒绝中断迭代。
- Conversation 继续负责一次只运行一个 Agent，权限会话状态由共享控制器维护。

**依赖：**

- Runner 不直接匹配规则，也不处理确认输入。

### REPL 权限交互

**位置：** `mewcode.repl`

**职责：**

- 收到权限请求事件时，用现有可注入输入函数显示四种选择并解析响应。
- 输入非法时重新提示；EOF、取消键或输入异常时选择拒绝。
- 渲染脱敏权限决定事件，区分自动允许、规则拒绝、黑名单、沙箱和用户拒绝。
- 处理 `/permissions` 和 `/permissions <mode>`，不调用 Provider。
- 模式切换只影响后续尚未裁决的调用。

**对外接口：**

- `Repl` 构造时接收共享 `PermissionController`。
- 保持 `run()` 返回值和普通消息路由行为。

**依赖：**

- 依赖 Agent 权限事件和权限控制器。
- 不读取或直接修改权限 YAML。

### CLI 组合根

**位置：** `mewcode.cli`

**职责：**

- 用参数解析器读取 `--permission-mode`，默认 `default`。
- 按“工作区 → 工具注册表 → 权限路径与配置 → 规则仓库 → 权限控制器 → Scheduler → Agent → Conversation → REPL”的顺序组装对象。
- 将实际注册工具名交给权限配置加载器。
- 捕获 `PermissionConfigError` 并以清晰错误和非零退出码结束启动。
- 不在 CLI 层实现规则匹配或权限提示细节。

### 内置工具复检

**位置：** `mewcode.tools.command_tool`、`file_tools`、`search_tools`

**职责：**

- 为六个工具补充 `permission_spec`。
- 命令工具在创建子进程前再次调用同一不可配置黑名单。
- 普通文件工具在每次实际文件操作前继续调用工作区路径解析。
- 查找和搜索工具只遍历已验证搜索范围，并逐个排除解析后越界的结果。
- 工具层复检失败仍返回结构化安全结果，作为统一权限管线之外的最后防线。

## 模块交互

### 启动与对象组装

```text
CLI 解析 --permission-mode
  -> 创建 Workspace
  -> 创建六个内置工具及 ToolRegistry
  -> 从 ToolRegistry 取得实际工具名集合
  -> 计算三层 PermissionPaths
  -> 加载并校验三层 YAML
  -> 创建 PermissionRuleStore
  -> 创建 PermissionTargetBuilder
  -> 创建 PermissionController
  -> 将 PermissionController 注入 ToolScheduler
  -> 创建 AgentRunner、Conversation、Repl
```

任一现存权限文件无效时，配置加载器抛出 `PermissionConfigError`。CLI 输出包含文件路径和错误类别的短消息并返回非零退出码；Provider 和 REPL 不启动。

缺失权限文件不创建空文件。只有用户选择永久放行时，系统才按需创建项目 `.mewcode` 目录和本地权限文件。

### 单次工具调用权限流程

```text
ToolCallRequest
  -> ToolRegistry.validate_call
     -> 未知工具：原有 unknown ToolResult
     -> 参数错误：原有 validation ToolResult
     -> 有效：ValidatedToolCall
  -> PermissionController.evaluate
     -> PermissionTargetBuilder.build
        -> 黑名单拒绝：DENY / BLACKLIST
        -> 沙箱拒绝：DENY / SANDBOX
        -> 安全目标：PermissionTarget
     -> PermissionRuleStore.match
     -> 权限模式裁决
        -> ALLOW
        -> DENY
        -> ASK
```

每次最终裁决都产生 `AgentPermissionDecision`。拒绝决定立即转换为失败 `ToolExecution`；允许决定进入待执行集合；询问决定进入确认流程。

### 权限模式裁决矩阵

| 硬门禁或规则状态 | 严格模式 | 默认模式 | 放行模式 |
|---|---|---|---|
| 黑名单拒绝 | deny | deny | deny |
| 沙箱拒绝 | deny | deny | deny |
| 胜出规则为 `deny` | deny | deny | deny |
| 会话精确 `allow` | allow | allow | allow |
| 持久化 `allow` | ask | allow | allow |
| 没有匹配规则 | ask | ask | allow |

严格模式只把当前会话中已经由用户确认的精确规则视为自动放行。项目本地、项目共享和用户全局的 `allow` 都只能让确认目标更明确，不能跳过严格模式的首次确认。

### 规则查找流程

```text
规范化 PermissionTarget
  -> 检查会话规则
     -> 有匹配：选择该层最具体规则并停止
  -> 检查项目本地规则
     -> 有匹配：选择该层最具体规则并停止
  -> 检查项目共享规则
     -> 有匹配：选择该层最具体规则并停止
  -> 检查用户全局规则
     -> 有匹配：选择该层最具体规则并停止
  -> 未命中
```

单层候选排序键依次为：

1. 精确匹配高于 glob。
2. glob 固定文本字符数更多者优先。
3. 固定文本数量相同时，路径段更长者优先。
4. 仍然并列时，`deny` 优先。

配置声明顺序不参与裁决，重新排列 YAML 不改变结果。

### 路径目标构造

普通路径调用的数据流：

```text
原始 path
  -> 相对路径拼接 workspace，或保留绝对路径
  -> 规范化并解析已有符号链接
  -> 验证属于解析后的 workspace root
  -> 转换为使用 / 的项目相对路径
  -> PermissionTarget
```

写入尚不存在的文件时，解析其已存在祖先目录中的符号链接，再拼接剩余路径段。工具真正读写前重新调用相同工作区检查。

路径 glob 调用的数据流：

```text
原始 pattern
  -> 拒绝绝对模式
  -> 按路径段拒绝 ..
  -> 提取第一个 glob 元字符之前的固定前缀
  -> 解析固定前缀符号链接并检查工作区边界
  -> 规范化为 / 分隔的项目相对 glob
  -> PermissionTarget
```

查找过程中每个实际匹配项再次解析并验证；越界符号链接结果被排除并形成沙箱失败，而不是返回给模型。

### 人工确认流程

```text
PermissionDecision(ASK)
  -> Scheduler 创建 PermissionChallenge
  -> 记录为当前活动确认
  -> 发出 AgentPermissionRequest
  -> Repl 显示工具名和规范化目标
  -> 用户选择
  -> Repl.resolve(choice)
  -> Scheduler 等待完成
  -> PermissionController.apply_choice
  -> 发出 AgentPermissionDecision
```

终端提示采用固定选项：

```text
Permission required: run_command(git status)
[d] deny  [o] once  [s] session  [p] permanent
choice>
```

处理规则：

- 空输入或未知选项重新提示，不改变权限状态。
- `deny` 返回用户拒绝。
- `once` 只允许当前 `ValidatedToolCall`。
- `session` 先加入会话精确规则，再允许当前调用。
- `permanent` 先完成项目本地文件原子写入，再加入会话精确规则并允许当前调用。
- 永久写入失败时返回 `deny / config_error`，不加入会话规则，也不执行工具。
- EOF、确认句柄取消或界面无法响应时解析为拒绝。
- 请求事件只包含规范化目标，不包含文件内容、替换文本、搜索词或完整参数对象。

### 工具批次调度

Scheduler 保留现有批次划分方式：连续只读工具形成并发批次，每个副作用工具及未知工具形成独占批次。

每个批次执行以下步骤：

```text
发出 tool_batch_started
  -> 按模型调用顺序逐项校验和权限预检
  -> 需要确认的调用逐项串行确认
  -> 立即产出未知、参数错误和拒绝结果
  -> 收集所有获准调用
  -> 只读获准调用按 max_read_concurrency 并发
     或副作用获准调用独占执行
  -> 收集全部 ToolExecution
  -> 发出 tool_batch_completed
```

一个调用被拒绝只移除该调用，不取消同批其他获准调用。完成事件仍可按实际完成时间出现；`schedule.executions` 在回写 Provider 前按原始索引排序。

权限预检阶段不占用只读并发槽，人工确认完成前对应工具不会启动。

### 权限拒绝与 Agent Loop

权限拒绝生成普通失败工具结果：

```python
ToolResult(
    ok=False,
    tool_name=...,
    content="",
    error="Permission denied: <short reason>",
    metadata={
        "tool_call_id": ...,
        "permission": {
            "outcome": "deny",
            "source": "blacklist|sandbox|...|user_confirmation",
        },
    },
)
```

Provider 仍只收到现有工具结果消息，不接收权限事件或确认对象。Agent Runner 将拒绝结果加入工作消息并开始下一次模型迭代，不增加连续未知工具计数，也不产生新的停止原因。

模型可以在下一轮：

- 将越界路径改为项目内路径。
- 将危险命令拆成更安全的专用工具操作。
- 放弃被规则拒绝的操作。
- 解释权限限制并结束任务。

### 模式查询与切换

REPL 在启动普通消息路由前识别权限命令：

```text
/permissions
  -> 输出 permission mode: <current>

/permissions strict
/permissions default
/permissions allow
  -> PermissionController.set_mode
  -> 输出新的当前模式

/permissions <非法值>
  -> 输出用法
  -> 不调用 Provider
```

模式切换不修改已有会话规则，也不写入持久化文件。由于 REPL 同一时间只消费一个 Agent Run，执行中的确认期间不能并行输入模式命令；新模式只作用于下一次尚未开始裁决的调用。

### Plan Mode

`/plan` 继续只向模型暴露只读工具，但这些工具仍经过完整权限系统：

- 严格模式首次读取需要确认。
- 默认模式按规则处理，未命中时确认。
- 放行模式自动允许未被规则或沙箱拒绝的读取。

`/do` 使用全部工具并沿用同一个权限控制器、当前模式和会话规则。

### 取消与异常

取消流程按以下顺序处理：

```text
Conversation.cancel_active
  -> AgentRun.cancel
  -> ToolSchedule.cancel
     -> 设置 cancel_requested
     -> 取消当前 PermissionChallenge
     -> 取消活动工具任务
     -> 阻止后续工具启动
  -> AgentStopped(CANCELLED)
```

确认期间按下取消键时，REPL 不把它解释为放行。尚未启动的调用生成取消结果或随 Agent 取消结束，任何工具实现都不会被调用。

权限请求的事件消费者异常、确认 Future 异常或权限持久化异常都在权限边界内转换为拒绝或 Agent 的现有错误处理，不遗留后台任务、未解析确认或临时文件。

## 文件组织

```text
MewCode/
├── .gitignore
├── README.md
├── examples/
│   ├── config.yaml
│   └── permissions.yaml                         # 新增：规则格式示例
├── src/mewcode/
│   ├── cli.py                                   # 修改：启动参数与对象组装
│   ├── repl.py                                  # 修改：确认交互和模式命令
│   ├── conversation.py                          # 保持：继续转发统一事件
│   ├── permissions/                             # 新增：权限子系统
│   │   ├── __init__.py                          # 公共出口
│   │   ├── models.py                            # 枚举、规则、决定、确认句柄
│   │   ├── config.py                            # 路径、YAML 加载、原子写入
│   │   ├── rules.py                             # 解析、glob、具体度、分层匹配
│   │   ├── targets.py                           # 目标规范化与硬门禁
│   │   └── controller.py                        # 模式裁决与放行范围
│   ├── agent/
│   │   ├── __init__.py                          # 修改：导出权限事件
│   │   ├── events.py                            # 修改：请求与决定事件
│   │   ├── scheduler.py                         # 修改：执行前权限管线
│   │   └── runner.py                            # 最小修改或不改
│   └── tools/
│       ├── __init__.py                          # 修改：导出权限元数据
│       ├── base.py                              # 修改：元数据和两阶段执行
│       ├── safety.py                            # 新增：不可配置命令黑名单
│       ├── workspace.py                         # 修改：glob 与边界能力
│       ├── builtin.py                           # 修改：工具元数据组装
│       ├── command_tool.py                      # 修改：共享黑名单复检
│       ├── file_tools.py                        # 修改：权限目标声明
│       └── search_tools.py                      # 修改：安全遍历与目标声明
├── tests/
│   ├── fakes.py                                 # 修改：测试工具权限元数据
│   ├── test_permission_config.py                # 新增
│   ├── test_permission_rules.py                 # 新增
│   ├── test_permission_targets.py               # 新增
│   ├── test_permission_controller.py            # 新增
│   ├── test_permission_integration.py           # 新增
│   ├── test_tool_scheduler.py                   # 修改：预检、批次与取消
│   ├── test_tools_base.py                       # 修改：两阶段注册表
│   ├── test_workspace.py                        # 修改：glob 和符号链接
│   ├── test_command_tool.py                     # 修改：共享黑名单
│   ├── test_file_tools.py                       # 修改：最终路径复检
│   ├── test_search_tools.py                     # 修改：越界结果过滤
│   ├── test_agent_runner.py                     # 修改：拒绝后继续 Loop
│   └── test_repl.py                             # 修改：确认和模式命令
└── docs/phase-5-permission-system/
    ├── spec.md
    ├── plan.md
    ├── task.md
    └── checklist.md
```

### `.gitignore` 调整

当前 `/.mewcode/` 整目录被忽略，无法提交项目共享规则。调整为忽略目录内容、单独放回共享文件：

```gitignore
# Local MewCode config and secrets
/.mewcode/*
!/.mewcode/permissions.yaml
/config.yaml
/config.yml
/.codex
```

因此：

- `.mewcode/permissions.yaml` 可被版本控制。
- `.mewcode/permissions.local.yaml` 继续被忽略。
- `.mewcode/config.yaml` 和其他本地状态继续被忽略。

## 技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 权限接入位置 | Scheduler 在实际工具执行前统一预检 | Scheduler 已掌握批次、顺序、取消和结果组装，能保证拒绝不产生副作用且不终止 Agent Loop。 |
| 参数校验顺序 | 工具存在性与 Schema 校验先于权限确认 | 避免为未知工具或无效参数打扰用户，保持现有失败语义。 |
| 人工确认传递 | 使用带一次性响应句柄的 Agent 事件 | 保持核心执行与终端解耦，测试和未来其他界面可以提供自己的响应。 |
| 确认并发 | 预检阶段按模型调用顺序串行确认 | 防止提示交错和输入错配；确认完成后仍保留只读并发。 |
| 工具权限描述 | 每个工具声明一个主要权限目标 | 配置规则无需序列化完整参数，也不会暴露文件内容等无关信息。 |
| 未声明目标的工具 | 失败关闭 | 防止未来新增工具因遗漏权限元数据而默认获得执行权。 |
| 硬门禁位置 | 预检统一检查，工具启动前同源复检 | 前者提供一致事件与确认语义，后者防止内部直接执行路径绕过不可配置安全边界。 |
| 命令黑名单 | 固定编译正则，不进入 YAML | 满足不可配置放开要求，并避免运行时规则覆盖。 |
| 路径沙箱 | `Path.resolve()` 后用路径归属判断 | 避免字符串前缀漏洞，并覆盖绝对路径、`..` 与已有符号链接逃逸。 |
| 写入不存在路径 | 解析已有祖先后保留剩余路径段 | 可安全创建新文件，同时检查父目录符号链接。 |
| 路径 glob | 自定义完整匹配编译器 | 明确定义 `*` 不跨目录、`**` 可递归，避免不同平台 `Path.match` 行为差异。 |
| 命令 glob | 大小写敏感的自定义完整字符串 glob | 保持 shell 命令语义，并与路径规则共享明确的转义处理；黑名单另行大小写不敏感。 |
| glob 元字符 | 支持 `*`、`**`、`?` 和字符集合；无未转义元字符为精确规则 | 提供标准 glob 能力，同时允许目标本身安全包含通配符字符。 |
| glob 转义 | `\\`、`\*`、`\?`、`\[`、`\]` 表示字面字符 | 保证人工确认生成的永久规则始终是当前目标的精确授权，不会因目标含通配符而扩大权限。 |
| 规则表达式解析 | 以第一个 `(` 和最后一个 `)` 划分工具与模式 | 允许命令模式内部包含括号；缺失或多余外层文本视为配置错误。 |
| 层级冲突 | 先选最高匹配层，再比较该层具体度 | 严格落实会话、本地项目、共享项目、用户全局的覆盖顺序。 |
| 同层冲突 | 精确度优先，完全并列时 `deny` 优先 | 允许声明窄例外，同时在无法区分时安全收敛。 |
| 配置加载时机 | 启动时一次性加载，不做文件热重载 | 本阶段没有配置监听需求；会话内仅由永久放行安全更新内存快照。 |
| 配置与规则依赖 | 规则模块声明写入协议，配置模块实现并由 CLI 注入 | 配置可以复用规则解析，同时避免规则仓库反向导入配置造成循环。 |
| YAML 读写 | `yaml.safe_load` / `safe_dump` | 项目已经依赖 PyYAML，无需增加新依赖。永久写入保留全部规则数据，但可能规范化注释和排版。 |
| 永久写入 | 重新读取最新本地文件，再用同目录临时文件、刷新、重新解析和 `os.replace` | 避免覆盖启动后新增的有效规则和产生半写文件；校验失败时旧文件仍完整。 |
| 持久化范围 | 永久确认只写项目本地文件 | 避免一次交互扩大到其他项目、团队成员或机器。 |
| 权限模式存储 | 启动参数和会话内状态，不写 YAML | 避免再引入一套模式配置优先级；符合用户选择的切换方式。 |
| 默认模式 | `default` | 未命中时交回用户，兼顾规则自动化与安全。 |
| 拒绝结果 | 复用 `ToolResult`，增加脱敏权限 metadata | Provider 协议和对话回灌无需改变，模型仍能据此调整策略。 |
| Agent 停止语义 | 权限拒绝不是停止原因 | 满足拒绝后继续 Agent Loop，并保持现有迭代与完成逻辑。 |
| Plan Mode | 与普通模式共享同一权限控制器 | 只读工具也遵循批准的权限模式语义，会话授权可跨 `/plan` 与 `/do` 使用。 |
| 取消语义 | 取消确认、活动工具及未启动调用 | 保证确认期间取消不会意外启动工具，也不遗留 Future 或后台任务。 |
| 非交互环境 | 需要确认时自动拒绝 | 失败关闭，不因 stdin 不可用而默认放行。 |
| 错误策略 | 启动配置错误阻止启动；运行期写入错误拒绝当前调用 | 两类错误都不在不确定策略下执行，同时避免运行期写入失败摧毁 REPL。 |
| 终端输出 | 权限事件只显示工具名、规范化目标、结果和来源 | 满足可观察性，同时不泄露文件内容、替换文本、密钥或完整规则集。 |
| Provider 集成 | 不修改 Anthropic/OpenAI 适配层 | 权限是本地执行策略，Provider 继续只处理工具调用与工具结果。 |
| 测试方式 | 临时工作区、脚本化挑战响应、假工具和假 Provider | 无网络、无真实危险命令、无真实用户目录读写即可覆盖全部行为。 |
