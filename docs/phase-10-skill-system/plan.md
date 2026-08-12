# Skill 系统 Plan

## 架构总览

采用“不可变目录快照＋可变激活状态＋每迭代动态运行视图”的架构。

```text
启动：解析全部 Profile
  -> 发现并严格解析三级 Skill
  -> 启动内置工具与 MCP
  -> 校验命令、白名单、Profile 和包工具
  -> 发布不可变 Skill 快照
  -> 恢复会话中的激活名称、顺序和参数

下一条输入
  -> 比较文件元数据快照
  -> 未变化：沿用当前快照
  -> 有变化：构建并校验候选快照
       -> 有效：原子替换并重绑激活项与命令目录
       -> 全局错误：保留上一份有效聚合状态
  -> 处理消息或斜杠命令

统一 Skill 调用协调器
  -> shared：更新共享激活状态，下一次模型迭代读取新 SOP 与工具视图
  -> isolated：创建临时独立 Agent Run，最终回复回流，内部历史销毁
```

### Profile 目录

启动时一次解析配置中的全部 Profile，形成按名称索引的不可变目录。当前对话使用 active Profile；独立 Skill 可从目录选择指定 Profile。解析包含 API Key 环境变量，但目录和错误均不暴露密钥值。

### Skill 目录构建器

负责三级路径扫描、单文件/目录入口解析、严格 frontmatter 校验、包工具静态验证、跨层覆盖和同层冲突检测。构建过程只产生候选数据，不修改运行状态。

启动分成两步：

1. 先解析 Skill 和专属工具公开名，以便将这些名称加入 MCP 保留名集合。
2. MCP 启动完成后，再用实际成功注册的全局工具完成白名单校验并发布快照。

### 不可变 Skill 快照

保存当前有效 Skill、目录摘要、来源、文件指纹、专属工具声明和动态斜杠命令定义。所有校验先在候选快照上完成，成功后才原子替换。

### Skill 运行状态

保存当前快照及按激活顺序排列的“Skill 名称＋最后原始参数”。SOP 和工具实例不持久化；每次恢复、热更新或调用时都由当前定义重新渲染或构造。

### 动态 Agent Run 视图

当前 Agent Run 不再固定持有一份工具与提示快照，而是在每次模型迭代开始时读取：

- 当前人工指令、记忆和共享 Skill SOP；
- 当前共享白名单并集；
- 已激活专属工具；
- 当前 PLAN/只读限制；
- 始终保留的系统 Skill 加载工具。

共享 Skill 在工具调用中激活后，下一次模型迭代立即看到新 SOP 和工具，同时不会改变正在执行的工具批次。

### 统一 Skill 调用协调器

Agent 的系统加载工具与 `/<skill>` 命令都调用同一协调器：

- 共享模式更新激活状态，并让当前或新建 Agent Run 继续执行。
- 独立模式截取完整轮次、创建临时运行、选择 Profile、组合动态指令和工具，完成后只返回最终回复。
- 系统加载工具本身不经过 Skill 白名单，也不触发额外权限确认，因为它不能直接访问文件、命令或网络；独立或共享 Skill 后续实际调用的每个工具仍完整经过模式与权限系统。

### 动态命令目录

保留不可变命令快照，但在外面增加一个可原子换代的命令目录。分发器与终端补全始终查询当前快照，因此热更新无需重建 REPL 或终端对象。

### 会话状态事务

会话状态扩展为“历史＋待执行计划＋激活 Skill”。普通变化继续追加记录；`/reset` 使用临时文件、刷盘和原子替换，一次写入空历史、空计划和空激活状态。只有磁盘替换成功后才更新内存并切回 `[DEFAULT]`。

### 核心依赖方向

```text
CLI 组装
  -> Profile 目录
  -> Skill 目录构建器
  -> MCP / 全局工具目录
  -> Skill 运行状态
  -> 动态命令目录
  -> Conversation / AgentRunner

Conversation
  -> Skill 调用协调器
  -> 动态 Agent Run 视图
  -> AgentRunner
  -> ToolScheduler
  -> 既有权限系统

Skill 运行状态
  -> SessionBinding（只持久化名称、顺序、参数）
```

发现与解析层不依赖 Conversation 或 Agent；执行层只通过窄接口读取主历史和提交折叠结果；Agent 和会话层不反向依赖 CLI，模块间不存在循环所有权。

## 核心数据结构与接口

### SkillDefinition

```text
SkillDefinition
- name: str
- description: str
- visible_tools: tuple[str, ...]
- mode: shared | isolated
- history_turns: int | None
- profile_name: str | None
- source: project | user | builtin
- entry_path: Path
- package_root: Path | None
- body_ref: SkillBodyRef
- declared_tools: tuple[SkillToolDeclaration, ...]
```

`SkillBodyRef` 只保存入口路径、正文起始位置和预期文件指纹。启动时流式读到 frontmatter 结束标记即停止，不把正文载入内存；激活时才读取正文。若激活时指纹已变化，本次加载安全失败，下一条输入边界再刷新目录，避免把不同版本的元信息和正文混用。

frontmatter 示例：

```yaml
---
name: review
description: Review uncommitted workspace changes.
tools:
  - read_file
  - find_files
  - search_code
  - review__git_snapshot
mode: isolated
history: 0
---
```

`model` 仅在独立模式按需出现。`tools` 允许空列表，但必须是无重复、非空字符串组成的列表。

### SkillToolDeclaration

`tools/*.json` 每个文件使用统一结构：

```json
{
  "name": "inspect",
  "description": "Inspect the current project.",
  "parameters": {
    "type": "object",
    "properties": {
      "target": {"type": "string"}
    },
    "required": ["target"],
    "additionalProperties": false
  },
  "command": ["python", "scripts/inspect.py"],
  "safety": "read_only",
  "timeout_seconds": 60
}
```

规则：

- `name`、`description`、`parameters`、`command`、`safety` 必填。
- `timeout_seconds` 可选，默认 60。
- 未知字段、空命令、重复局部名或不合法 JSON Schema 使所属 Skill 定义无效。
- 局部名使用小写 snake_case，组合后的 `<skill-name>__<tool-name>` 必须满足 Provider 的 64 字符安全名称限制。
- `parameters` 按 JSON Schema Draft 2020-12 校验；启动时校验 schema 本身，调用时在启动子进程前校验参数。
- 结果 JSON 只允许 `ok`、`content`、`error`、`metadata`；类型不符或出现未知字段均视为协议错误。

### 目录与激活状态

```text
SkillCatalogSnapshot
- definitions: Mapping[str, SkillDefinition]
- available_prompt: str
- command_definitions: tuple[CommandDefinition, ...]
- fingerprint: SkillTreeFingerprint
- diagnostics: tuple[SkillDiagnostic, ...]
- declared_tool_names: frozenset[str]

StoredSkillActivation
- name: str
- input: str

ActiveSkill
- definition: SkillDefinition
- raw_input: str
- rendered_sop: str
- tool_registry: ToolRegistry
```

`SkillRuntime` 内部使用有序映射保存 `ActiveSkill`。同名更新替换值但不移动位置。持久化只写 `StoredSkillActivation`；`ActiveSkill` 始终由当前快照重新构造。

独立 Skill 也进入激活映射，但主提示和主工具视图只选择其中的共享项。独立调用时只加入当前被调用的独立项；其他独立项只用于恢复、热更新重绑和失活追踪。

### ProfileCatalog

```text
ProfileCatalog
- active_name: str
- profiles: Mapping[str, ProviderProfile]
- credential_env_names: frozenset[str]

get(name: str | None) -> ProviderProfile
provider(name: str | None) -> LLMProvider
```

所有 Profile 在启动时完整解析。Provider 对象按 Profile 名延迟创建并缓存，全部包装到同一个 `UsageLedger`，使独立 Skill 的 Token 也进入现有累计统计；启动解析不发起网络请求。

### 动态运行视图

```text
ResolvedRunView
- additions: PromptAdditions
- tools: ToolRegistry

AgentRunView
- resolve() -> ResolvedRunView
```

每个模型迭代只调用一次 `resolve()`，该次迭代的模型请求、未知工具判断和工具调度使用同一个结果，防止迭代中途状态变化造成前后不一致。

提供两种实现：

- `StaticRunView`：兼容现有测试和不需要 Skill 的调用。
- `SkillAwareRunView`：从 SkillRuntime 计算可见目录、共享 SOP、专属工具和白名单交集。

`PromptAdditions` 扩展为：

```text
- custom_instructions
- available_skills
- active_skills
- long_term_memory
```

提示区顺序保持为 Environment → Custom Instructions → Available Skills → Active Skills → Long-Term Memory。

### ToolRegistry 组合能力

```text
merge(other) -> ToolRegistry
select_names(names) -> ToolRegistry
select_safety(safety_set) -> ToolRegistry
without(names) -> ToolRegistry
names() -> frozenset[str]
```

任何重复公开名都显式失败，不再由字典静默覆盖。

工具视图计算顺序固定为：

```text
全局内置/MCP 工具
+ 当前作用域已激活的专属工具
-> 按 Skill 白名单名称筛选
-> 按 DEFAULT/PLAN/READ_ONLY 安全类别筛选
-> 无条件补回 load_skill
```

无共享 Skill 的主对话跳过按名称筛选，保持现有全部全局工具。

### 系统加载工具与嵌套运行

系统工具公开名固定为 `load_skill`：

```json
{
  "name": "load_skill",
  "arguments": {
    "name": "skill-name",
    "input": "optional full input"
  }
}
```

它属于串行的 Agent 控制工具，不能直接访问工作区，也不进入普通权限确认。为支持独立 Skill 内部的实时输出和权限确认，引入：

```text
AgentControlOperation
- events() -> AsyncIterator[AgentEvent]
- result: ToolResult
- cancel() -> awaitable
```

工具调度器识别该受限接口：普通工具继续走现有执行路径；`load_skill` 独占一个串行批次；独立运行产生的文本、工具状态和权限请求通过父调度器转发；父历史最终只接收一个 `load_skill` 工具结果；取消父 Run 时同步取消独立 Run。

### 独立历史模型

```text
ConversationTurn
- messages: tuple[ChatMessage, ...]

PortableHistoryTurn
- user_text: str
- assistant_transcript: str
```

历史切分器只选择以用户消息开始、以自然助手回复结束、中间工具调用与结果完整配对的轮次。滚动摘要、边界提醒、恢复提醒、未完成轮次和内部推理不计入轮数。

选中的轮次整体投影为 Provider 中立文本：保留用户内容；按顺序保留工具公开名、参数、成功/失败结果和最终助手回复；过滤 Provider 内部推理；不拆开调用与结果。因此独立 Skill 即使切换到不同协议的 Profile，也不会接收另一 Provider 的私有消息结构。

### 会话状态接口

`SessionState` 增加：

```text
active_skills: tuple[StoredSkillActivation, ...]
```

`SessionBinding` 增加：

```text
commit_skills(active_skills)
reset_state()
```

会话 codec 新增严格的 `skill_state` 记录。`reset_state()` 在同目录写入完整临时 JSONL、刷盘后原子替换正式文件；只有成功后才更新 Binding 内存状态。

### 统一调用接口

```text
SkillCoordinator
- invoke_from_command(name, input, original_text, conversation_mode)
- invoke_from_agent(name, input, conversation_mode)
- refresh_before_input()
- restore(stored_activations)
- reset()
```

两条入口共享定义解析、激活、持久化、工具构造、独立历史投影和运行工厂；只在最终历史落盘形态上区分命令来源与 Agent 工具来源。

## 模块设计

### ProfileCatalog

一次读取并严格解析全部 Profile，拒绝重复 Profile 名及任何无效字段、协议、上下文窗口或凭据引用；提供 active Profile 和按名查询；延迟创建并缓存 Provider；记录 API Key 环境变量名供专属工具子进程移除。

### SkillPathResolver

生成项目、用户、内置三个根目录；使用 `importlib.resources` 定位随包内置资源；拒绝符号链接入口和越界路径；给诊断生成稳定且安全的来源标签。

### SkillDiscovery

确定性扫描入口；有界读取 frontmatter；验证名称、字段、模式和描述；读取目录包全部工具声明；将单定义错误转为警告；检测同层重复；生成候选集合和文件树指纹。

### SkillCatalogBuilder

完成跨层覆盖、命令冲突、Profile 引用、实际工具清单和白名单校验。每个 Skill 只能引用全局内置/MCP 工具和自己声明的专属工具，禁止跨 Skill 包引用。生成 Available Skills 文本、Skill 命令和最终不可变快照。

### SkillBodyLoader

激活时验证入口指纹，有界读取 UTF-8 SOP，只执行字面量 `{{input}}` 替换；无占位符时保留独立任务参数。

### SkillMaterializer

激活目录包时再次检查源指纹，将包内普通文件复制到安全临时运行目录，拒绝符号链接、越界和超量包，保留执行位，并在换代、`/reset` 和关闭时清理。

### SkillToolFactory / SkillProcessTool

ToolFactory 把静态声明实例化为稳定公开名、参数验证器和工具级权限目标。ProcessTool 使用无 shell 子进程、工作区 cwd、过滤后的环境、有界 I/O、超时/取消终止和严格结果 JSON 解析执行脚本。

### SkillRuntime

保存当前聚合状态；执行激活、同名重渲染、恢复、重绑和自动失活；持久化成功后才替换内存激活状态；仅在文件指纹变化时构建候选；热更新完成全部校验与必要会话写入后才交换目录、激活项和命令快照。

### SkillRunView

每个 Agent 迭代组合 Available Skills、共享 Active Skills、人工指令和长期记忆；按调用作用域合并白名单和专属工具；最后应用安全类别并补回 `load_skill`。

### ConversationTurnProjector

向后识别完整用户轮次，验证工具配对，忽略系统摘要和内部推理，选取最近 N 轮并转换为 Provider 中立、有界的用户/助手文本对。

### IsolatedSkillRunnerFactory

每次创建临时 Direct Agent Run；选择 Profile；使用独立 Token 估算器和熔断状态；复用当前进程上下文归档；不提供会话写入端，不调度独立记忆更新；工具安全上限继承调用时的 DEFAULT/PLAN/READ_ONLY 状态。

### SkillCoordinator

统一斜杠命令和 `load_skill` 调用。共享命令激活后启动主 Run；独立命令转发临时 Run 事件并折叠提交结果；Agent 共享调用返回激活结果；Agent 独立调用把最终文本作为工具结果；取消时终止临时 Run。

### LoadSkillTool / AgentControlOperation

向模型暴露固定 schema，标记为系统控制工具和串行边界，只委托 Coordinator；把独立 Run 事件桥接到父 ToolSchedule，并产生一个标准 ToolResult 保持父 Provider 工具配对。

### DynamicCommandCatalog

内部持有当前不可变 CommandRegistry，通过“静态系统命令＋当前 Skill 命令”构建并原子替换。分发、帮助和补全每次读取当前注册表。系统命令移除硬编码 review，新增 reset。

### SessionState / SessionBinding 扩展

codec 追加严格 skill_state；replay 和 scan 跳过坏记录并恢复最后有效列表；commit_skills 保持追加写失败不改内存；reset_state 使用同目录临时文件和原子替换，保留会话 ID 与原创建时间。

### Prompt、REPL、MCP 与 CLI 适配

- Prompt 增加 Available Skills，并将标题规范为 Active Skills。
- AgentRunner 每迭代取得动态提示和工具。
- ToolScheduler 支持串行 Agent 控制操作及嵌套事件。
- REPL 在每条非空输入解析前刷新 Skill，终端补全读取动态命令目录。
- MCP 启动结果增加每个配置 Server 的成功/失败状态。
- CLI 按 Profile → Skill 预发现 → MCP → Skill 最终目录 → 权限 → 会话恢复 → Conversation 的顺序组装。

## 模块交互

### 启动流程

1. 解析全部 Profile，建立 ProfileCatalog。
2. 创建静态系统命令；移除硬编码 `/review`，加入 `/reset`。
3. 扫描三级 Skill，读取 frontmatter 与目录包工具声明，产生预目录和警告。
4. 解析覆盖、重复、命令冲突、Profile 引用和专属工具名。
5. 以“内置工具＋`load_skill`＋有效专属工具名”为 MCP 保留名称启动 MCP。
6. 汇总实际注册的全局工具和 MCP Server 状态。
7. 校验所有有效 Skill 白名单；缺失工具或失败 MCP 引用使启动失败。
8. 构建不可变 Skill 快照和动态命令注册表。
9. 将全局工具与有效专属工具公开名加入权限配置已知名称；`load_skill` 不接受权限规则。
10. 打开或恢复会话，按保存的名称、顺序和参数恢复激活项。
11. 组装 SkillRuntime、Conversation、Run View、Coordinator、LoadSkillTool 和 REPL。

### 输入边界热更新

```text
REPL.refresh_before_input
  -> SkillRuntime 比较指纹
  -> 未变化：返回
  -> 有变化：CatalogBuilder 构建候选
       -> 全局错误：警告并保留旧聚合状态
       -> 有效：重绑激活项并准备运行副本
            -> 激活列表删除时先 commit_skills
            -> 原子替换 catalog + active_skills + command_registry
```

有效更新为已激活目录包创建新的不可变运行副本，换代后清理旧副本。更新被拒绝时，已激活项继续使用缓存 SOP 和旧运行副本。尚未激活且源文件已经变化的旧定义不会混用新正文，调用时提示修复后重试。

### 普通主对话

Conversation 完成记忆与会话 preflight 后，SkillRunView 解析本迭代视图。无共享 Skill 时，提示只有 Available Skills，工具保持当前模式允许的全部全局工具并加入 `load_skill`。存在共享 Skill 时，按激活顺序渲染 SOP、合并白名单和专属工具、套用模式安全类别并补回 `load_skill`。该模型迭代的请求、未知工具判断和调度固定使用同一视图。

### 用户直接调用共享 Skill

1. 动态命令处理器取得规范化原始斜杠文本；保留命令/参数大小写和内部空格，延续现有规则去除首尾空白。
2. Coordinator 查找 shared 定义。
3. BodyLoader 校验指纹、读取 SOP、替换参数。
4. ToolFactory 构造专属工具运行副本。
5. commit_skills 持久化名称和参数；失败则不激活、不运行。
6. Runtime 原子加入或替换激活项。
7. Conversation 用原始斜杠文本启动主 Run；首次模型请求已经包含新 SOP 和工具。

Provider 后续失败不撤销已经成功持久化的激活状态。

### 主 Agent 调用共享 Skill

父 Run 调用 `load_skill`，控制操作完成正文、工具和激活持久化，返回标准 ToolResult。父历史保持工具调用/结果配对，下一迭代重新解析 Run View 并获得新 SOP 与工具。失败时返回普通工具失败，旧激活状态不变。

### 用户直接调用独立 Skill

1. 完成正文加载、专属工具构造和激活持久化。
2. 从主历史提取最近 N 个完整轮次，当前斜杠调用不计入。
3. 投影为 Provider 中立历史。
4. 选择指定或 active Profile。
5. 组合环境、人工指令、Available Skills、共享 SOP、当前独立 SOP 和长期记忆。
6. 工具采用“共享白名单并集＋当前独立白名单”，再套调用时安全类别。
7. 创建无会话写入端、无独立记忆更新的临时 Direct Run。
8. REPL 转发该 Run 的文本、工具状态、权限和 Token 事件。
9. 成功后一次提交主历史中的原始斜杠 user 消息和最终 assistant 文本，并调度一次主记忆更新。
10. 销毁内部消息和运行状态。

独立运行失败时不写折叠主历史，但已成功持久化的激活状态保留。

### 主 Agent 调用独立 Skill

父 ToolSchedule 串行执行 `load_skill`，Coordinator 创建临时 Run并向父调度器转发事件。成功后 ToolResult.content 等于独立最终回复；父 Provider 写入配对结果并继续下一迭代。主历史只包含普通用户消息、父 load_skill 调用、独立最终回复工具结果和父最终回复；独立内部链路不落盘。父取消同步取消临时 Run 和内部工具。

### 独立运行中的再次加载

- 加载共享 Skill：更新全局共享激活状态，当前独立 Run 下一迭代也继承它。
- 加载独立 Skill：创建新的临时 Run，但仍只从主对话提取历史，不继承调用方独立 Skill 的私有 SOP 或消息。
- 超过固定嵌套深度返回工具失败。

### 专属工具调用

1. Scheduler 以公开名完成工具级权限判断。
2. 参数通过 Draft 2020-12 schema 校验。
3. 构造去除 Profile 凭据的环境。
4. 解析包内相对路径，以工作区为 cwd 无 shell 启动。
5. 同时写 stdin JSON 并有界读取 stdout/stderr。
6. 取消、超时或超量输出时终止进程。
7. 非零退出直接失败；零退出严格解析唯一 JSON 对象。
8. 校验结果字段，截断 content，stderr 仅进入内部有界诊断。
9. 返回普通 ToolResult。

### 会话恢复

replay 取得历史、计划和最后一份 Skill 列表；先修复不完整工具尾部，再按当前目录重绑并重渲染。缺失项被移除并警告，修正列表追加持久化以避免重复警告。会话中不保存旧 SOP 或工具实例。

### `/reset`

1. 拒绝与活动 Run、压缩或其他会话事务并发。
2. 等待上一轮记忆更新完成。
3. Binding 在同目录写完整临时 JSONL，包含原创建记录、空历史、空计划、空 Skill 和 reset 时间。
4. 刷盘并原子替换正式会话。
5. 替换成功后才清空 Conversation 消息/计划、SkillRuntime 激活项和 ContextManager 估算/熔断状态，并将 InteractionState 切回 DEFAULT。
6. 失败时内存与正式文件保持原状。
7. `/clear` 继续只清终端显示。

## 文件组织

### 新增文件

```text
src/mewcode/agent/control.py
src/mewcode/skills/__init__.py
src/mewcode/skills/models.py
src/mewcode/skills/paths.py
src/mewcode/skills/parser.py
src/mewcode/skills/catalog.py
src/mewcode/skills/materialization.py
src/mewcode/skills/process_tool.py
src/mewcode/skills/history.py
src/mewcode/skills/runtime.py
src/mewcode/skills/execution.py
src/mewcode/skills/control.py
src/mewcode/skills/builtin/commit.md
src/mewcode/skills/builtin/test.md
src/mewcode/skills/builtin/review/SKILL.md
src/mewcode/skills/builtin/review/tools/git_snapshot.json
src/mewcode/skills/builtin/review/scripts/git_snapshot.py
tests/test_skill_parser.py
tests/test_skill_discovery.py
tests/test_skill_catalog.py
tests/test_skill_materialization.py
tests/test_skill_process_tool.py
tests/test_skill_history.py
tests/test_skill_runtime.py
tests/test_skill_execution.py
tests/test_skill_integration.py
```

### 修改文件

| 文件 | 改动 |
|---|---|
| `src/mewcode/config.py` | 严格加载全部 Profile，提供 ProfileCatalog 和 active 兼容包装 |
| `src/mewcode/agent/runner.py` | 每迭代解析 AgentRunView |
| `src/mewcode/agent/scheduler.py` | 串行控制工具、嵌套事件与取消传播 |
| `src/mewcode/agent/__init__.py` | 导出控制协议和运行视图 |
| `src/mewcode/tools/base.py` | 重名拒绝、注册表组合和 schema 失败格式 |
| `src/mewcode/tools/__init__.py` | 导出组合能力 |
| `src/mewcode/prompting/models.py` | Available/Active Skills additions |
| `src/mewcode/prompting/sections.py` | 新动态区与优先级 |
| `src/mewcode/prompting/builder.py` | 渲染目录和多个激活 SOP |
| `src/mewcode/commands/core.py` | 原始输入、动态命令查询 |
| `src/mewcode/commands/contracts.py` | Skill 调用、刷新和 reset 接口 |
| `src/mewcode/commands/builtin.py` | 移除硬编码 review，新增 reset |
| `src/mewcode/commands/dispatcher.py` | CommandContext 携带 ParsedInput |
| `src/mewcode/terminal.py` | 补全动态读取命令目录 |
| `src/mewcode/repl.py` | 输入前热更新、Skill 命令与 reset 路由 |
| `src/mewcode/conversation.py` | Skill-aware Run、折叠结果和 reset 编排 |
| `src/mewcode/continuity/session_models.py` | 激活 Skill 状态 |
| `src/mewcode/continuity/session_codec.py` | skill_state 和 reset 文件编码 |
| `src/mewcode/continuity/session_repository.py` | commit_skills 与原子 reset |
| `src/mewcode/continuity/diagnostics.py` | SKILLS 诊断组件 |
| `src/mewcode/context/manager.py` | 无 I/O 运行状态重置 |
| `src/mewcode/mcp/models.py` | Server 启动状态模型 |
| `src/mewcode/mcp/manager.py` | 收集状态 |
| `src/mewcode/mcp/runtime.py` | 返回状态映射 |
| `src/mewcode/cli.py` | 新启动顺序、组装和关闭清理 |
| `pyproject.toml` | jsonschema 依赖和内置资源打包 |
| `README.md` | Skill 格式、模式、命令、热更新、工具协议和边界 |

相关现有测试同步修改：`test_config.py`、`test_tools_base.py`、`test_agent_runner.py`、`test_tool_scheduler.py`、`test_prompt_builder.py`、`test_command_core.py`、`test_command_dispatcher.py`、`test_builtin_commands.py`、`test_terminal.py`、`test_repl.py`、`test_conversation.py`、`test_session_codec.py`、`test_session_repository.py`、`test_session_integration.py`、`test_mcp_runtime.py` 和 `test_mcp_integration.py`。

### 内置 Skill 白名单

`commit.md` 与 `test.md`：

```text
read_file
find_files
search_code
run_command
```

`review/SKILL.md`：

```text
read_file
find_files
search_code
review__git_snapshot
```

`review__git_snapshot` 只运行固定只读 Git 查询并返回结构化 JSON，不接受任意命令。

## 技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 目录状态 | 不可变 SkillCatalogSnapshot | 候选完整校验后一次换代 |
| 激活状态 | 有序映射＋单聚合状态引用 | 同名替换不移动，并与命令快照原子发布 |
| 两阶段正文 | 启动只读 frontmatter；激活读 SOP | 减少启动上下文和常驻内存 |
| 活跃包版本 | 激活时物化安全临时副本 | 更新失败后旧脚本仍稳定可用 |
| 热更新 | 输入边界元数据指纹 | 无后台线程，未变化不重读内容 |
| Agent 工具变化 | 每迭代解析一次 Run View | 下一迭代生效且单迭代一致 |
| load_skill | 串行 Agent 控制工具 | 能转发内部事件与权限请求 |
| 加载权限 | 控制工具免确认，实际工具正常授权 | 加载本身无外部动作 |
| 白名单 | 名称并集→安全类别→补回 load_skill | 只能收窄，不能突破模式上限 |
| 跨 Skill 工具 | 禁止 | 避免隐式包依赖 |
| 独立历史 | 完整轮次的中立文本 | 支持跨 Provider Profile |
| 独立模式 | Direct＋继承工具安全上限 | review 在 PLAN 中仍可审查但不可写 |
| Profile Provider | 延迟缓存并共享 UsageLedger | 启动不联网且统计统一 |
| JSON Schema | Draft 2020-12 / jsonschema | 完整校验嵌套参数 |
| 子进程 | create_subprocess_exec，无 shell | 避免 shell 注入与转义差异 |
| 环境 | 移除 Profile Key 变量 | 保留 PATH 等正常环境且防凭据泄露 |
| 会话激活 | 追加 skill_state | 延续 JSONL 坏行隔离 |
| reset | 临时完整 JSONL＋fsync＋os.replace | 同 ID 原子清空所有会话状态 |
| 内置 review | 独立目录包＋只读 Git 工具 | 保持只读并提供目录包样板 |
| 命令热更新 | 动态包装不可变 Registry | 帮助、补全、分发共享当前快照 |
| MCP 失败 | 被有效 Skill 引用时才致命 | 保留未引用 Server 的故障隔离 |

### 路径解析

- `command[0]` 裸名称由 OS PATH 解析；包内相对路径解析为运行包绝对路径；显式绝对解释器路径必须是现存普通文件。
- 其余 argv 中非选项且具有路径形态、并指向包内文件的值解析为运行包绝对路径；`..` 解析后不得逃逸包根。
- 普通标志和值保持原样；不展开 `${VAR}`、`~`、通配符或命令替换。
- 裸解释器存在性延迟到调用时检查，缺失返回结构化工具失败。

### 固定资源上限

```text
每层最多 Skill 入口                 256
每个目录包最多普通文件              512
每个目录包总大小                    16 MiB
frontmatter 最大                     64 KiB
SOP 正文最大                        128 KiB
单个 Skill 最多专属工具              64
单个工具声明最大                     64 KiB
单个 Skill 白名单最多               128 项
description 最大                    200 个字符且只能一行
单次 {{input}} 最大                  64 KiB
全部已激活共享 SOP 渲染后最大        256 KiB
command 最多 argv                    64 项
单个 argv 最大                       4096 字符
专属工具 stdin JSON 最大             1 MiB
专属工具 stdout 最大                 1 MiB
专属工具 stderr 最大                 64 KiB
回流 ToolResult.content              20,000 字符
独立 Skill 最大嵌套深度               4
超时                                 默认 60 秒，允许 1–600 秒
```

入口或包静态超限按单定义解析失败；激活总 SOP、递归深度和运行 I/O 超限按本次调用失败处理，不破坏已有状态。

### 指纹与并发

- 指纹由根目录、相对路径、文件类型、大小、纳秒 mtime 和可用的平台文件标识组成，并按路径排序。
- 首次扫描和元数据变化后才重新读取受影响 frontmatter/schema。
- 激活和物化前后各检查一次源指纹；复制期间变化则放弃本次加载。
- 热更新只在输入边界运行，不与活动 Agent Run 并发。
- load_skill 改变状态时，当前工具批次继续使用旧视图，下一模型迭代读取新状态。
- 同一模型响应中臆测调用刚加载的新工具仍按未知工具处理。

### 故障分类

单定义警告并回退：frontmatter/YAML/编码错误、路径名不符、条件/未知字段错误、正文边界错误、专属工具声明或脚本错误、包资源超限。

快照级失败：同层有效重名、命令/别名冲突、有效白名单缺失工具、跨 Skill 引用、Profile 无效、被引用 MCP 工具未成功提供。

调用级失败：定义在输入后变化、SOP/包物化失败、激活持久化失败、参数或活跃 SOP 总量超限、嵌套超限、子进程启动/权限/超时/退出/协议错误。

### `/reset` 耐久性

- 临时文件与正式会话位于同一目录。
- 完整写入并 fsync 后才替换。
- POSIX 替换后同步父目录；Windows 使用同卷 os.replace。
- 失败时清理临时文件并保留旧正式文件与全部内存状态。
- 重置 JSONL 保留原 session start 时间和 ID，最后活动时间更新为 reset 时间。
- UI 切换 DEFAULT 必须晚于 Conversation reset 成功。

### 放弃的方案

- 不在启动时读取全部 SOP 或注册全部专属工具。
- 不让 ToolRegistry 在工具执行中原地突变。
- 不使用后台文件监听器。
- 不把脚本导入主进程。
- 不直接复制不同 Provider 的私有工具消息。
- 不为 load_skill 增加第二个执行工具。
- 不删除旧会话或创建新 ID 实现 reset。
- 不让失败热更新覆盖当前有效状态。

## 需求映射

| 需求 | 技术归属 |
|---|---|
| F1–F9 | SkillPathResolver、SkillDiscovery、SkillCatalogBuilder、DynamicCommandCatalog |
| F10–F15 | SkillBodyRef、SkillBodyLoader、SkillRuntime、LoadSkillTool |
| F16–F18 | DynamicCommandCatalog、SkillCoordinator、Conversation |
| F19–F24 | SkillRunView、PromptBuilder、ProfileCatalog |
| F25–F32 | ConversationTurnProjector、IsolatedSkillRunnerFactory、SkillCoordinator |
| F33–F43 | Skill parser、Materializer、ToolFactory、ProcessTool、MCP 状态 |
| F44–F49 | SkillRuntime 聚合状态、指纹刷新、SessionBinding |
| F50–F53 | reset 命令、Conversation、SessionBinding、ContextManager、InteractionState |
| F54–F57 | 内置 commit/review/test 资源与统一 Skill 执行链 |
| N1–N3 | 确定性排序、不可变候选、故障分类 |
| N4–N8 | Run View 安全交集、权限目标、进程隔离、环境过滤 |
| N9–N10 | 两阶段加载、元数据指纹、Provider 延迟创建 |
| N11–N12 | 完整轮次投影、父工具配对、会话事务 |
| N13–N14 | 静态兼容包装、跨平台路径/进程/reset 设计 |
| N15–N16 | 结构化诊断、窄接口、假 Provider/MCP/进程测试 |
| N17–N18 | 统一 Coordinator、动态目录、固定资源上限 |
