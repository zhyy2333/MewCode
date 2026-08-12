# Skill 系统 Tasks

## 执行约束

- 本清单只能在 `spec.md`、`plan.md`、本文件和后续 `checklist.md` 全部批准后开始实施。
- 每个任务只处理列出的范围；发现需要改变已批准需求或技术设计时，先返回文档阶段，不在实现中自行扩大范围。
- 测试使用临时工作区、临时用户目录、假 Provider、假 MCP 和受控子进程，不读取真实用户 Skill，不依赖网络。
- 每完成一个任务，先运行该任务的定向验证；跨模块里程碑再运行相关测试组，最后运行完整回归。
- 专属工具、独立 Agent 和 `/reset` 涉及安全或持久化边界，相关失败路径必须与成功路径同时实现，不留“随后补安全”的中间状态。

## 文件清单

### 新增实现与资源

| 文件 | 职责 |
|---|---|
| `src/mewcode/agent/control.py` | Agent 控制工具协议、串行边界和嵌套运行事件 |
| `src/mewcode/skills/__init__.py` | Skill 子系统公共导出 |
| `src/mewcode/skills/models.py` | 定义、来源、工具声明、快照、激活和运行视图模型 |
| `src/mewcode/skills/paths.py` | 三级目录、入口发现、路径边界和元数据指纹 |
| `src/mewcode/skills/parser.py` | 严格 frontmatter、SOP 引用和专属工具声明解析 |
| `src/mewcode/skills/catalog.py` | 覆盖、回退、冲突、Profile/工具白名单和候选快照校验 |
| `src/mewcode/skills/materialization.py` | 目录包安全物化、版本保留与清理 |
| `src/mewcode/skills/process_tool.py` | 专属工具实例化、参数校验和无 shell 子进程协议 |
| `src/mewcode/skills/history.py` | 完整轮次识别和 Provider 中立历史投影 |
| `src/mewcode/skills/runtime.py` | 激活状态、重渲染、恢复、重绑、热更新和 Run View |
| `src/mewcode/skills/execution.py` | 独立 Agent 构建与统一 Skill 执行协调器 |
| `src/mewcode/skills/control.py` | `load_skill` 系统工具和控制操作适配 |
| `src/mewcode/skills/builtin/commit.md` | 内置共享 commit Skill |
| `src/mewcode/skills/builtin/test.md` | 内置共享 test Skill |
| `src/mewcode/skills/builtin/review/SKILL.md` | 内置独立 review Skill |
| `src/mewcode/skills/builtin/review/tools/git_snapshot.json` | review 只读 Git 工具声明 |
| `src/mewcode/skills/builtin/review/scripts/git_snapshot.py` | review 固定只读 Git 查询实现 |

### 新增测试

| 文件 | 职责 |
|---|---|
| `tests/test_skill_parser.py` | frontmatter、模板、工具 schema 和资源边界 |
| `tests/test_skill_discovery.py` | 三级发现、确定性、指纹和路径安全 |
| `tests/test_skill_catalog.py` | 覆盖、回退、冲突、Profile/MCP/白名单校验 |
| `tests/test_skill_materialization.py` | 安全副本、源变化、权限位和清理 |
| `tests/test_skill_process_tool.py` | 参数 schema、进程、I/O、超时、取消和失败归一化 |
| `tests/test_skill_history.py` | 完整轮次截取、工具链配对和中立投影 |
| `tests/test_skill_runtime.py` | 激活、白名单、持久化、恢复和热更新事务 |
| `tests/test_skill_execution.py` | shared/isolated 协调、嵌套和父子事件 |
| `tests/test_skill_integration.py` | 命令、会话、内置 Skill、重置和端到端验收 |

### 修改范围

| 文件或区域 | 改动 |
|---|---|
| `src/mewcode/config.py`、`tests/test_config.py` | 全量 ProfileCatalog 与严格启动校验 |
| `src/mewcode/tools/base.py`、`src/mewcode/tools/__init__.py`、`tests/test_tools_base.py` | 工具注册表组合、按名/安全类别筛选和重名拒绝 |
| `src/mewcode/mcp/models.py`、`manager.py`、`runtime.py` 及测试 | MCP Server 启动状态与保留名称 |
| `src/mewcode/prompting/` 及提示测试 | Available Skills、多个 Active Skills 与动态顺序 |
| `src/mewcode/agent/runner.py`、`scheduler.py`、`__init__.py` 及测试 | 每迭代 Run View、控制操作、嵌套事件和取消 |
| `src/mewcode/continuity/session_models.py`、`session_codec.py`、`session_repository.py`、`diagnostics.py` 及测试 | Skill 状态记录、恢复和原子 reset |
| `src/mewcode/context/manager.py`、`tests/test_context_manager.py` | reset 后的估算器和熔断运行状态清理 |
| `src/mewcode/commands/`、`src/mewcode/terminal.py` 及测试 | 动态命令目录、原始输入、移除硬编码 review、增加 reset |
| `src/mewcode/conversation.py`、`src/mewcode/repl.py` 及测试 | Skill-aware 运行、独立结果折叠、刷新和 reset 编排 |
| `src/mewcode/cli.py`、`pyproject.toml` | 启动顺序、依赖、资源打包和关闭清理 |
| `README.md` | 作者格式、两种模式、命令、热更新、工具协议与安全边界 |

## 基础模型、配置与静态校验

## T1：登记 JSON Schema 依赖和内置资源

**文件：** `pyproject.toml`
**依赖：** 无
**覆盖：** F33、F35、N14、N16

**步骤：**

1. 增加 `jsonschema>=4,<5` 运行依赖。
2. 配置构建产物包含三个内置 Markdown、review 工具 JSON 和脚本。
3. 验证源码安装与 wheel 安装都能通过资源 API 枚举内置 Skill，不依赖当前工作目录。

**验证：** 运行 TOML 断言、构建 wheel，并在临时虚拟导入路径检查五个内置资源均可读取。

## T2：实现全量 ProfileCatalog

**文件：** `src/mewcode/config.py`、`tests/test_config.py`
**依赖：** 无
**覆盖：** F24、F32、N8、N10、N13

**步骤：**

1. 将所有 Profile 的协议、模型、地址、思考模式、上下文窗口和 API Key 环境变量解析成不可变目录。
2. 保留当前 Profile 兼容入口；Provider 采用按需创建与缓存，并统一包裹共享 UsageLedger。
3. 启动阶段验证所有配置和所需环境变量，错误只显示 Profile/字段，不显示密钥值。
4. 覆盖当前 Profile、指定 Profile、缺失 Profile、无效字段和缺失凭据测试。

**验证：** `python -m pytest tests/test_config.py -q`

## T3：定义 Skill 核心模型和固定限制

**文件：** `src/mewcode/skills/models.py`、`src/mewcode/skills/__init__.py`、`tests/test_skill_parser.py`
**依赖：** 无
**覆盖：** F1、F6–F8、F33–F42、N1、N18

**步骤：**

1. 定义来源层级、入口类型、正文引用、SkillDefinition、SkillToolDeclaration、目录快照、激活项和诊断模型。
2. 固化 name kebab-case、局部工具 snake_case、模式、历史、模型、超时及全部资源上限。
3. 使用不可变集合/元组保存排序后的结果，避免枚举顺序进入状态。
4. 从 Skill 包只导出稳定公共类型，不在导入时扫描文件系统。

**验证：** `python -m pytest tests/test_skill_parser.py -k 'models or limits or names' -q`

## T4：实现三级路径解析、入口发现和指纹

**文件：** `src/mewcode/skills/paths.py`、`tests/test_skill_discovery.py`
**依赖：** T3
**覆盖：** F2、F3、F33、F44、N1、N5、N14、N18

**步骤：**

1. 解析项目、用户和包内置三级根目录，同时识别 `<name>.md` 与 `<name>/SKILL.md`。
2. 拒绝符号链接入口、目录外解析和超量入口/包文件，所有候选按规范相对路径稳定排序。
3. 生成由根、相对路径、类型、大小、纳秒 mtime 和可用文件标识构成的元数据指纹。
4. 确认无变化比较只读元数据，不读取正文或 schema。

**验证：** `python -m pytest tests/test_skill_discovery.py -q`

## T5：实现严格 frontmatter 与 SOP 引用解析

**文件：** `src/mewcode/skills/parser.py`、`tests/test_skill_parser.py`
**依赖：** T3、T4
**覆盖：** F1、F3、F4、F6–F8、F14、F24、N3、N7、N9、N18

**步骤：**

1. 有界读取 UTF-8 入口，拆分 YAML frontmatter 和 Markdown 正文引用。
2. 强制必填字段、未知字段拒绝、description 单行长度、mode/history/model 条件和入口名完全匹配。
3. 共享模式声明 model/history、独立缺失 history、非法名称/类型等均转为带来源的单定义警告。
4. 启动解析只保留正文位置、大小与指纹，不把正文放入 Available Skills 或工具定义。

**验证：** `python -m pytest tests/test_skill_parser.py -k 'frontmatter or entry or body_ref' -q`

## T6：实现专属工具声明静态解析

**文件：** `src/mewcode/skills/parser.py`、`tests/test_skill_parser.py`
**依赖：** T1、T5
**覆盖：** F33–F35、F37、F38、F42、N3、N5、N6、N18

**步骤：**

1. 对目录包的 `tools/*.json` 逐文件解析一个声明；单文件 Skill 禁止包工具。
2. 严格校验 `name`、`description`、`parameters`、`command`、`safety`、可选 timeout，拒绝未知字段。
3. 使用 Draft 2020-12 校验参数 schema；生成 `<skill-name>__<local-name>` 公开名。
4. 验证 argv 类型/长度、路径形态、包边界和被引用普通文件；不创建 Tool、不启动进程。

**验证：** `python -m pytest tests/test_skill_parser.py -k 'tool or schema or command or timeout' -q`

## T7：实现覆盖、回退和确定性目录构建

**文件：** `src/mewcode/skills/catalog.py`、`tests/test_skill_catalog.py`
**依赖：** T2、T5、T6
**覆盖：** F2、F4–F9、F32、N1–N3、N17

**步骤：**

1. 聚合每层有效/无效候选；高层无效时选择下一层有效版本。
2. 同层同名有效定义、Skill 命令之间或与系统命令/别名的大小写无关冲突作为快照级失败。
3. 校验独立 model 对应有效 Profile；保存简洁诊断和全部冲突来源。
4. 构建只含名称、说明、来源与静态引用的不可变预目录。

**验证：** `python -m pytest tests/test_skill_catalog.py -k 'precedence or fallback or duplicate or command or profile' -q`

## T8：扩展 ToolRegistry 的安全组合能力

**文件：** `src/mewcode/tools/base.py`、`src/mewcode/tools/__init__.py`、`tests/test_tools_base.py`
**依赖：** 无
**覆盖：** F20–F23、F28、F34、F43、N1、N4、N6

**步骤：**

1. 注册时拒绝公开名重复，不再静默覆盖。
2. 增加 `names`、`merge`、`select_names`、`select_safety` 和 `without`，保持输入无突变和稳定顺序。
3. 未知名称返回可用于快照校验的明确结果，运行时仍保持现有未知工具失败语义。
4. 覆盖白名单并集后安全交集及固定工具补回的组合测试。

**验证：** `python -m pytest tests/test_tools_base.py -q`

## T9：记录 MCP Server 启动状态和保留专属名称

**文件：** `src/mewcode/mcp/models.py`、`src/mewcode/mcp/manager.py`、`src/mewcode/mcp/runtime.py`、`tests/test_mcp_runtime.py`、`tests/test_mcp_integration.py`
**依赖：** T7、T8
**覆盖：** F34、F35、F43、N3、N15

**步骤：**

1. 为每个配置 MCP Server 返回成功、失败及有界安全诊断状态。
2. 在启动 MCP 前保留内置工具、`load_skill` 和预目录中的专属公开名，拒绝 MCP 重名。
3. 保持未被 Skill 引用的 MCP 启动失败为非致命诊断。
4. 为后续白名单错误保留“未配置、启动失败、未提供工具”的可区分状态。

**验证：** `python -m pytest tests/test_mcp_runtime.py tests/test_mcp_integration.py -q`

## T10：完成最终目录的工具与 Profile 全局校验

**文件：** `src/mewcode/skills/catalog.py`、`tests/test_skill_catalog.py`
**依赖：** T7、T8、T9
**覆盖：** F9、F32、F34、F43、F47、N2、N3、N15

**步骤：**

1. 以实际全局工具、MCP 状态和各 Skill 自有专属工具校验白名单。
2. 禁止引用其他 Skill 的专属工具；缺失全局/专属/MCP 工具均形成快照级错误。
3. 错误指出 Skill、公开工具名、来源及适用 MCP 状态，不暴露 schema 或凭据。
4. 只有全部全局校验通过才生成可发布 SkillCatalogSnapshot。

**验证：** `python -m pytest tests/test_skill_catalog.py -q`

## 提示、包运行与会话状态

## T11：增加 Available Skills 与多个 Active Skills 提示区

**文件：** `src/mewcode/prompting/models.py`、`src/mewcode/prompting/sections.py`、`src/mewcode/prompting/builder.py`、`tests/test_prompt_builder.py`
**依赖：** T3
**覆盖：** F10、F19、F27、F29、N7、N9

**步骤：**

1. 将动态 additions 拆为 custom instructions、available skills、active skills 和 long-term memory。
2. 按 Environment 800、Custom 900、Available 950、Active 1000、Memory 1100 排序。
3. Available 只渲染名称和一句说明；Active 按激活顺序渲染完整 SOP。
4. 覆盖未激活正文/schema 不进入请求、多个共享 SOP 每轮稳定出现的测试。

**验证：** `python -m pytest tests/test_prompt_builder.py -q`

## T12：实现激活时正文加载和参数渲染

**文件：** `src/mewcode/skills/runtime.py`、`tests/test_skill_runtime.py`
**依赖：** T5
**覆盖：** F12、F14、F15、F19、N7、N9、N18

**步骤：**

1. 激活时重新核对入口指纹并有界读取 SOP。
2. 只做字面量 `{{input}}` 全量替换；无占位符时把原参数作为独立任务上下文附加。
3. 限制单次 input 和全部共享渲染 SOP 总量。
4. 保存原始参数和渲染结果，不写入目录快照或普通对话消息。

**验证：** `python -m pytest tests/test_skill_runtime.py -k 'body or render or input or active_prompt' -q`

## T13：实现目录包安全物化

**文件：** `src/mewcode/skills/materialization.py`、`tests/test_skill_materialization.py`
**依赖：** T4、T6
**覆盖：** F35、F36、F38、N2、N5、N14、N18

**步骤：**

1. 激活目录 Skill 时将普通文件复制到安全临时版本目录，拒绝链接、越界和资源超限。
2. 复制前后核对指纹；源在复制期间变化则丢弃候选。
3. 保留必要执行位，解析命令包内路径到物化目录绝对路径。
4. 支持换代、自动失活、`/reset` 和进程关闭后的确定性清理。

**验证：** `python -m pytest tests/test_skill_materialization.py -q`

## T14：实现专属工具参数和子进程成功协议

**文件：** `src/mewcode/skills/process_tool.py`、`tests/test_skill_process_tool.py`
**依赖：** T1、T6、T8、T13
**覆盖：** F36–F40、N5、N6、N8、N14

**步骤：**

1. 激活时从静态声明建立 Tool 实例和工具级权限规格，调用前用 Draft 2020-12 校验参数。
2. 使用 `asyncio.create_subprocess_exec`，不经 shell，以工作区为 cwd。
3. 继承常规环境但移除所有 Profile API Key 变量，注入 `MEWCODE_SKILL_DIR` 和 `MEWCODE_WORKSPACE_ROOT`。
4. stdin 写入一次 JSON 对象；零退出时严格接受唯一 stdout JSON 对象并校验 `ok`、`content`、可选 `error`/`metadata`。

**验证：** `python -m pytest tests/test_skill_process_tool.py -k 'schema or success or cwd or environment or permission' -q`

## T15：实现专属工具有界失败、超时和取消

**文件：** `src/mewcode/skills/process_tool.py`、`tests/test_skill_process_tool.py`
**依赖：** T14
**覆盖：** F40–F42、N5、N7、N15、N18

**步骤：**

1. 有界并发读取 stdout/stderr，stdin、stdout、stderr 和回流内容分别执行固定上限。
2. 非零退出、启动失败、非法/多余 JSON、字段错误和输出超量转为可区分结构化 ToolResult 失败。
3. 默认 60 秒、自定义 1–600 秒；超时或任务取消时终止并等待子进程回收。
4. stderr 仅进入内部有界诊断，不直接进入模型结果或用户输出。

**验证：** `python -m pytest tests/test_skill_process_tool.py -q`

## T16：扩展会话 Skill 状态编码与回放

**文件：** `src/mewcode/continuity/session_models.py`、`src/mewcode/continuity/session_codec.py`、`src/mewcode/continuity/session_repository.py`、`src/mewcode/continuity/diagnostics.py`、`tests/test_session_codec.py`、`tests/test_session_repository.py`
**依赖：** T3
**覆盖：** F48、F49、N2、N11、N12、N13

**步骤：**

1. 定义 `StoredSkillActivation(name, input)` 和有序 `skill_state` JSONL 记录。
2. replay/scan 使用最后一份有效 Skill 列表，坏记录只产生诊断并沿用上一有效值。
3. `commit_skills` 在追加、刷新成功后才允许调用方更新内存。
4. 保持旧会话无 Skill 记录时恢复为空，并扩展 SKILLS 诊断组件。

**验证：** `python -m pytest tests/test_session_codec.py tests/test_session_repository.py -k 'skill or replay or diagnostics' -q`

## T17：实现同会话 ID 的原子 reset 持久化

**文件：** `src/mewcode/continuity/session_repository.py`、`tests/test_session_repository.py`
**依赖：** T16
**覆盖：** F50–F53、N2、N12、N14

**步骤：**

1. `reset_state()` 在同目录创建临时完整 JSONL，保留原 session start/ID，写入空历史、空计划、空 Skill 和 reset 时间。
2. 完整 flush/fsync 后 `os.replace`；POSIX 再同步父目录，Windows 保证同卷替换。
3. 任一步失败清理临时文件并保留旧正式文件，不修改 Binding 内存。
4. 覆盖替换前、替换时和内存提交前失败注入测试。

**验证：** `python -m pytest tests/test_session_repository.py -k reset -q`

## T18：实现 Skill 激活事务、恢复与重渲染

**文件：** `src/mewcode/skills/runtime.py`、`tests/test_skill_runtime.py`
**依赖：** T10、T12、T13、T16
**覆盖：** F15、F19、F45、F48、F49、N1、N2、N12

**步骤：**

1. 以有序映射保存每个 Skill 单一激活实例；同名新参数替换内容而不移动位置。
2. 共享和独立 Skill 均持久化名称/顺序/原参数；只有提交成功才交换内存状态。
3. 恢复时按当前目录重新加载/物化/渲染，缺失项忽略、警告并把修正列表追加持久化。
4. 清理被替换运行副本，失败时保留原激活和包副本。

**验证：** `python -m pytest tests/test_skill_runtime.py -k 'activate or replace or persist or restore' -q`

## T19：实现输入边界热更新和整批回滚

**文件：** `src/mewcode/skills/runtime.py`、`tests/test_skill_runtime.py`
**依赖：** T10、T18
**覆盖：** F44–F47、N1–N3、N9、N10

**步骤：**

1. 每个新非空输入前比较指纹；无变化直接返回且不重读正文/schema。
2. 有变化时构建完整候选，按名称重绑激活项并以最后参数重渲染。
3. 有低层有效版本则换绑；全层消失则提交自动失活并给出一次警告。
4. 任一快照级错误、物化或必要会话提交失败时拒绝整批更新，继续发布旧目录、命令、激活和运行副本。

**验证：** `python -m pytest tests/test_skill_runtime.py -k 'refresh or rebind or fallback or rollback or deactivate' -q`

## 动态 Agent 视图与执行编排

## T20：实现完整轮次识别和中立历史投影

**文件：** `src/mewcode/skills/history.py`、`tests/test_skill_history.py`
**依赖：** 无
**覆盖：** F25、F26、F31、N7、N11、N18

**步骤：**

1. 从主历史向后识别以用户开始、自然助手回复结束、工具调用/结果完整配对的轮次。
2. 排除滚动摘要、边界/恢复提醒、内部推理和未完成尾部。
3. 选择最近 N 轮且不拆链，转换为 Provider 中立的有界文本，保留工具名、参数、结果与最终助手内容。
4. 覆盖 N=0、跨 Provider、坏尾部、并行工具和超量历史测试。

**验证：** `python -m pytest tests/test_skill_history.py -q`

## T21：实现 SkillRunView 的提示和工具解析

**文件：** `src/mewcode/skills/runtime.py`、`tests/test_skill_runtime.py`
**依赖：** T8、T11、T18
**覆盖：** F10、F19–F23、F27–F29、N1、N4、N9

**步骤：**

1. 无共享激活时提供模式允许的全部全局工具；有共享激活时取其白名单并集。
2. 独立作用域使用共享并集加当前独立 Skill 白名单，且不修改主视图。
3. 所有视图最后与 DEFAULT/PLAN/READ_ONLY 安全类别相交，再强制补回 `load_skill`。
4. 同一视图输出 Available/Active 提示、工具注册表和稳定可见名称。

**验证：** `python -m pytest tests/test_skill_runtime.py -k 'run_view or whitelist or safety or prompt' -q`

## T22：让 AgentRunner 每迭代固定解析动态视图

**文件：** `src/mewcode/agent/runner.py`、`src/mewcode/agent/__init__.py`、`tests/test_agent_runner.py`
**依赖：** T21
**覆盖：** F12、F19–F23、N1、N4、N9、N10

**步骤：**

1. 用 RunViewProvider 替代 Runner 构造期静态工具/提示。
2. 每个模型迭代只解析一次，并让 ModelRequest、未知工具判断和本轮调度共用该视图。
3. 控制工具激活 Skill 后，下一模型迭代立即获得新 SOP/工具；同一响应中提前调用新工具仍按未知处理。
4. 保持没有 SkillRuntime 的兼容构造路径行为不变。

**验证：** `python -m pytest tests/test_agent_runner.py -q`

## T23：增加串行 Agent 控制操作与事件桥接

**文件：** `src/mewcode/agent/control.py`、`src/mewcode/agent/scheduler.py`、`src/mewcode/agent/__init__.py`、`tests/test_tool_scheduler.py`
**依赖：** T22
**覆盖：** F11–F13、F31、N4、N11

**步骤：**

1. 定义 `AgentControlOperation`，作为受信任、串行、可取消的调度边界。
2. Scheduler 遇到控制工具时先保持父工具调用配对，再转发子运行文本、状态、权限和 Token 事件。
3. 控制工具本身不经过用户权限确认，内部实际工具仍走现有模式和权限系统。
4. 父取消传播到控制操作、临时 Agent 和其活动子进程；相邻普通工具调度语义保持兼容。

**验证：** `python -m pytest tests/test_tool_scheduler.py -q`

## T24：实现 `load_skill` 系统工具和共享执行

**文件：** `src/mewcode/skills/control.py`、`src/mewcode/skills/execution.py`、`tests/test_skill_execution.py`
**依赖：** T18、T21、T23
**覆盖：** F11、F12、F14、F15、F22、N4、N10、N17

**步骤：**

1. 暴露固定公开名 `load_skill` 及只含 Skill 名/input 的 schema，不泄露正文或专属工具 schema。
2. 校验名称、输入上限和当前快照，委托统一 SkillCoordinator。
3. shared 调用完成正文加载、包物化、状态持久化和激活，返回标准 ToolResult。
4. 证明工具始终可见且职责只限协调，不直接访问文件系统/网络或绕过内部工具权限。

**验证：** `python -m pytest tests/test_skill_execution.py -k 'load_tool or shared or always_visible or permission' -q`

## T25：实现每次新建的独立 Agent Run

**文件：** `src/mewcode/skills/execution.py`、`tests/test_skill_execution.py`
**依赖：** T2、T15、T20、T21、T23、T24
**覆盖：** F13、F25–F30、F32、N7–N11

**步骤：**

1. 每次调用创建临时 Direct Agent，使用指定或当前 Profile，独立 Token 估算器/熔断状态，不接会话写入和独立记忆更新。
2. 只复制主历史最近 N 个中立完整轮次，继承环境、人工指令、长期记忆和共享 SOP，再追加当前独立 SOP。
3. 使用独立 Run View 和调用时 DEFAULT/PLAN/READ_ONLY 安全上限；不继承其他独立 SOP。
4. 最终回复直接作为结果，不追加总结调用；结束、失败或取消均销毁内部历史。

**验证：** `python -m pytest tests/test_skill_execution.py -k 'isolated or profile or history or context or no_summary' -q`

## T26：实现独立嵌套、父结果配对和深度限制

**文件：** `src/mewcode/skills/execution.py`、`src/mewcode/skills/control.py`、`tests/test_skill_execution.py`
**依赖：** T25
**覆盖：** F13、F25、F27、F31、N4、N11、N18

**步骤：**

1. 父 Agent 自主调用 isolated 时，把独立最终文本作为唯一 ToolResult.content，供父 Run 正常继续。
2. 独立 Run 加载 shared 时更新全局共享激活；加载 isolated 时仍从主历史创建另一临时 Run。
3. 不传递调用方独立 SOP/私有消息，固定最大嵌套深度 4，超限返回普通工具失败。
4. 覆盖父 Provider 工具调用/结果配对、内部链路不落盘和取消传播。

**验证：** `python -m pytest tests/test_skill_execution.py -q`

## 命令、会话与启动装配

## T27：实现动态 Skill 命令目录

**文件：** `src/mewcode/commands/core.py`、`src/mewcode/commands/contracts.py`、`src/mewcode/commands/dispatcher.py`、`src/mewcode/terminal.py`、`tests/test_command_core.py`、`tests/test_command_dispatcher.py`、`tests/test_terminal.py`
**依赖：** T10、T19
**覆盖：** F6、F9、F16、F44、N1、N13、N17

**步骤：**

1. 在不可变 CommandRegistry 外增加原子动态目录，合成静态系统命令和当前 Skill 命令。
2. ParsedInput/CommandContext 保留规范化原始斜杠文本与完整原始参数；命令匹配继续大小写不敏感。
3. help、分发和 Tab 补全每次读取同一当前目录，不维护 Skill 命令副本。
4. 热更新成功后原子换目录，失败时仍使用旧命令；系统命令/别名优先且不可被覆盖。

**验证：** `python -m pytest tests/test_command_core.py tests/test_command_dispatcher.py tests/test_terminal.py -q`

## T28：接入共享 Skill 斜杠调用与输入前刷新

**文件：** `src/mewcode/repl.py`、`src/mewcode/conversation.py`、`tests/test_repl.py`、`tests/test_conversation.py`
**依赖：** T19、T24、T27
**覆盖：** F12、F14–F17、F44、N9–N13、N17

**步骤：**

1. REPL 在处理每个新非空输入/命令前 await 热刷新；当前活动 Run 期间不刷新。
2. Skill 命令与 `load_skill` 共用 Coordinator；shared 先持久化激活，再把原始斜杠文本作为用户消息启动主 Run。
3. 首个模型请求已含渲染 SOP 和新工具，后续正常保存助手回复和工具链；SOP 不复制进历史。
4. 激活成功后的 Provider 失败不撤销 Skill 状态，激活失败不创建用户轮次。

**验证：** `python -m pytest tests/test_repl.py tests/test_conversation.py -k 'skill and shared' -q`

## T29：接入独立 Skill 斜杠调用和折叠提交

**文件：** `src/mewcode/repl.py`、`src/mewcode/conversation.py`、`tests/test_repl.py`、`tests/test_conversation.py`
**依赖：** T25、T26、T27
**覆盖：** F13、F18、F25–F31、N7、N11、N12

**步骤：**

1. 直接 isolated 命令激活后运行临时 Agent，并通过现有渲染路径转发内部事件和权限请求。
2. 当前斜杠调用不计入复制历史；成功后一次性提交原始 user 斜杠消息和最终 assistant 回复。
3. 不提交内部消息、工具链或第二次总结；成功后只调度一次主记忆更新。
4. 独立运行失败不写折叠历史，但保留已成功持久化的激活状态。

**验证：** `python -m pytest tests/test_repl.py tests/test_conversation.py -k 'skill and isolated' -q`

## T30：实现 `/reset` 全栈事务并保留 `/clear`

**文件：** `src/mewcode/commands/contracts.py`、`src/mewcode/commands/builtin.py`、`src/mewcode/conversation.py`、`src/mewcode/context/manager.py`、`src/mewcode/repl.py`、相关测试
**依赖：** T17、T18、T27
**覆盖：** F50–F53、N2、N12、N13

**步骤：**

1. 注册公开 `/reset`，拒绝额外参数；`/clear` 保持只清终端。
2. reset 拒绝与 Agent Run、压缩或会话事务并发，并等待上一轮记忆更新完成。
3. 磁盘原子替换成功后才清空消息、PendingPlan、Skill 激活、运行副本和 ContextManager 估算/熔断状态。
4. 最后切回 DEFAULT；保持 session ID、人工指令、长期记忆、权限模式和原创建时间不变，任一失败保持内存/磁盘旧状态。

**验证：** `python -m pytest tests/test_builtin_commands.py tests/test_conversation.py tests/test_context_manager.py tests/test_repl.py tests/test_session_repository.py -k 'reset or clear' -q`

## T31：按两阶段顺序完成 CLI 装配与关闭

**文件：** `src/mewcode/cli.py`、`src/mewcode/skills/__init__.py`、`tests/test_skill_integration.py`、相关 CLI 测试
**依赖：** T2、T9、T10、T18、T19、T24、T27、T30
**覆盖：** F2、F5、F9–F11、F32、F35、F43、F48、F49、N2、N3、N10、N13、N15

**步骤：**

1. 按 Profile → Skill 预发现 → MCP → Skill 最终目录 → 权限 → 会话恢复 → Conversation 顺序组装。
2. 启动只读取元信息/schema，不加载 SOP、不实例化专属工具、不启动脚本；在显示交互提示前收敛全局错误。
3. 将所有全局工具和有效专属公开名交给权限配置校验，但排除 `load_skill` 的自定义权限规则。
4. 恢复 Skill 后创建动态命令、Run View、Coordinator 和 REPL；关闭时取消运行并清理物化副本、MCP、记忆和归档资源。

**验证：** `python -m pytest tests/test_skill_integration.py -k 'startup or assembly or restore or shutdown' -q`

## 内置样板、文档与端到端验收

## T32：迁移内置 review Skill

**文件：** `src/mewcode/commands/builtin.py`、`src/mewcode/skills/builtin/review/SKILL.md`、`tools/git_snapshot.json`、`scripts/git_snapshot.py`、`tests/test_builtin_commands.py`、`tests/test_skill_integration.py`
**依赖：** T1、T15、T31
**覆盖：** F55、F57、N4–N7、N13

**步骤：**

1. 删除硬编码 review 处理器/提示，由内置目录 Skill 提供同名命令。
2. 定义 isolated、history 0、无 model，白名单为 `read_file`、`find_files`、`search_code`、`review__git_snapshot`。
3. Git 脚本只接受受限查询选项或无参数，运行固定只读 Git 命令并返回协议 JSON，不接受任意 argv。
4. 验证 DEFAULT/PLAN 中均不修改工作区、不复制主历史，并能被更高层有效定义覆盖。

**验证：** `python -m pytest tests/test_builtin_commands.py tests/test_skill_integration.py -k review -q`

## T33：实现内置 commit 与 test Skill

**文件：** `src/mewcode/skills/builtin/commit.md`、`src/mewcode/skills/builtin/test.md`、`tests/test_skill_integration.py`
**依赖：** T1、T31
**覆盖：** F54、F56、F57、N4、N13

**步骤：**

1. 两者均为 shared、无 model/history，最小白名单为 `read_file`、`find_files`、`search_code`、`run_command`。
2. commit SOP 明确范围判断、相称验证、仅相关安全暂存、单次提交和三类不提交条件；input 作为额外意图/信息约束。
3. test SOP 明确先识别项目测试方式、按 input/未提交改动选最小测试、合理扩大、只运行报告不改产品。
4. 在临时 Git 仓库和假 Agent 轨迹中验证模式、提示、白名单、覆盖/回退和不安全条件。

**验证：** `python -m pytest tests/test_skill_integration.py -k 'commit or test_builtin or builtin_override' -q`

## T34：覆盖定义、发现和启动验收

**文件：** `tests/test_skill_parser.py`、`tests/test_skill_discovery.py`、`tests/test_skill_catalog.py`、`tests/test_skill_integration.py`
**依赖：** T31、T32、T33
**覆盖：** AC1–AC5、AC14、AC19、AC30、AC31

**步骤：**

1. 参数化合法/非法单文件、目录包、严格字段、名称和三层覆盖/回退。
2. 覆盖同层重复、系统/Skill 命令冲突、缺失 Profile/凭据和缺失/MCP 失败工具的启动阻断。
3. 验证帮助/补全只来自最终快照，首请求只含名称和说明。
4. 用不同创建顺序重复构建，断言目录、命令、诊断和工具名确定一致。

**验证：** `python -m pytest tests/test_skill_parser.py tests/test_skill_discovery.py tests/test_skill_catalog.py tests/test_skill_integration.py -k 'definition or startup or deterministic or builtin_override' -q`

## T35：覆盖共享执行和工具安全验收

**文件：** `tests/test_skill_runtime.py`、`tests/test_skill_execution.py`、`tests/test_skill_integration.py`
**依赖：** T28、T34
**覆盖：** AC6–AC10、AC32

**步骤：**

1. 验证 Agent 与斜杠两入口统一、`{{input}}`、同名替换和多 Active Skills 常驻。
2. 验证无激活全工具、共享白名单并集、模式安全交集及 `load_skill` 永久可见。
3. 验证专属副作用工具在 DEFAULT 进入权限判断，在 PLAN 不可见。
4. 检查帮助、状态、错误、会话和请求不泄露未激活 SOP/schema、stderr 或密钥。

**验证：** `python -m pytest tests/test_skill_runtime.py tests/test_skill_execution.py tests/test_skill_integration.py -k 'shared or whitelist or privacy or permission' -q`

## T36：覆盖独立执行和历史隔离验收

**文件：** `tests/test_skill_history.py`、`tests/test_skill_execution.py`、`tests/test_skill_integration.py`
**依赖：** T29、T35
**覆盖：** AC11–AC14、AC34

**步骤：**

1. 两次独立调用断言运行实例不同、N 轮不拆链、N=0、无额外摘要请求。
2. 验证人工指令、记忆、共享 SOP 与当前独立 SOP 的继承集合，以及其他独立 SOP 的隔离。
3. 验证直接斜杠折叠两消息与 Agent 调用父工具配对两种持久化形态。
4. 覆盖指定/当前 Profile、跨 Provider 投影、嵌套深度和失败/取消不泄露内部历史。

**验证：** `python -m pytest tests/test_skill_history.py tests/test_skill_execution.py tests/test_skill_integration.py -k 'isolated or history or profile or nested or persistence' -q`

## T37：覆盖目录包和进程协议验收

**文件：** `tests/test_skill_materialization.py`、`tests/test_skill_process_tool.py`、`tests/test_skill_integration.py`
**依赖：** T15、T34
**覆盖：** AC15–AC18、AC32、AC33、AC35

**步骤：**

1. 验证启动静态检查、激活后注册、调用时才启动和完整公开权限名。
2. 覆盖 argv/path/cwd/env、只读与副作用安全类别、合法成功/失败协议。
3. 覆盖非零退出、超时终止、取消、非法 JSON/字段、超量 I/O 和 stderr 隐私。
4. 用平台中立脚本与路径断言，使 Windows/Linux/macOS CI 可运行同一套测试。

**验证：** `python -m pytest tests/test_skill_materialization.py tests/test_skill_process_tool.py tests/test_skill_integration.py -k 'package or process or tool' -q`

## T38：覆盖热更新、恢复和回滚验收

**文件：** `tests/test_skill_runtime.py`、`tests/test_session_integration.py`、`tests/test_skill_integration.py`
**依赖：** T19、T31、T34
**覆盖：** AC20–AC23、AC31

**步骤：**

1. 证明无变化输入不重读，有变化在当前输入前生效并以最后参数重渲染。
2. 覆盖高层删除后回退、全层删除自动失活、顺序保持和一次警告。
3. 逐类制造快照级错误，断言目录、命令、激活 SOP、工具和物化包全部保留旧版本。
4. 重启恢复名称/顺序/参数，缺失项修正后持久化且不重复警告。

**验证：** `python -m pytest tests/test_skill_runtime.py tests/test_session_integration.py tests/test_skill_integration.py -k 'refresh or rollback or restore or deactivate' -q`

## T39：覆盖 `/reset` 原子性与兼容验收

**文件：** `tests/test_session_repository.py`、`tests/test_conversation.py`、`tests/test_repl.py`、`tests/test_skill_integration.py`
**依赖：** T30、T38
**覆盖：** AC24–AC26、AC34

**步骤：**

1. 在 PLAN、消息、旧计划和多个激活 Skill 状态下 reset，验证清空、DEFAULT 和同 ID 重启结果。
2. 验证人工指令、长期记忆、权限模式和源会话创建时间不变。
3. 注入写入/fsync/replace 失败，断言磁盘和内存均无部分变化。
4. 回归 `/clear` 只操作终端，以及普通对话、PLAN、压缩、记忆和 MCP 行为。

**验证：** `python -m pytest tests/test_session_repository.py tests/test_conversation.py tests/test_repl.py tests/test_skill_integration.py -k 'reset or clear or compatibility' -q`

## T40：验证内置 Skill 行为边界

**文件：** `tests/test_skill_integration.py`
**依赖：** T32、T33、T36、T39
**覆盖：** AC27–AC30

**步骤：**

1. 在临时 Git 仓库验证 commit 的 shared 模式、额外 input、相关暂存、验证失败/无改动/范围不明不提交及成功仅一次提交。
2. 验证 review 的 isolated/history 0/只读工作区语义和原命令名。
3. 验证 test 有/无参数时选择相关测试、合理扩大且不修改产品代码。
4. 分别用项目层和用户层覆盖三个内置 Skill，再删除覆盖以确认回退内置。

**验证：** `python -m pytest tests/test_skill_integration.py -k builtin -q`

## T41：更新 README 和作者示例

**文件：** `README.md`
**依赖：** T40
**覆盖：** F1–F57、N7、N13、N17

**步骤：**

1. 记录三级目录、单文件/目录格式、严格 frontmatter、`{{input}}` 和 Profile 规则。
2. 说明两阶段加载、shared/isolated 历史语义、白名单与模式/权限交集。
3. 记录 `tools/*.json`、公开名、safety、argv、环境、JSON I/O、超时和故障规则。
4. 说明自动命令、热更新、恢复、`/reset` 与 `/clear` 差异、三个内置样板和本阶段不做范围。

**验证：** 使用 `rg` 检查关键字段、路径、命令和协议均有说明，并确认文档未承诺市场或版本管理。

## T42：执行完整质量与回归验收

**文件：** 本阶段全部实现、资源、测试和文档
**依赖：** T41
**覆盖：** AC1–AC35、N1–N18

**步骤：**

1. 运行全部测试，修复本阶段引入的普通对话、PLAN、权限、MCP、压缩、记忆、恢复、命令和终端回归。
2. 运行构建/安装资源测试，并确保自动化不依赖真实模型、网络、MCP、用户目录或交互终端。
3. 审计固定资源上限、敏感信息过滤、无 shell、权限身份、父子历史配对和所有原子交换点。
4. 检查差异只覆盖批准范围，无市场、版本管理、后台 watcher、自定义参数权限或其他扩展。

**验证：** 运行 `python -m pytest -q`、构建 wheel/安装烟测和 `git diff --check`，全部成功。

## 执行顺序

```text
T1 ───────────────┐
T2 ────────────┐  │
T3 -> T4 -> T5 -> T6 -> T7 ───────────────┐
T8 -> T9 -----------------------> T10 <────┘
                       │
T3 -> T11              ├-> T12
T4 + T6 -> T13 -> T14 -> T15
T3 -> T16 -> T17
T10 + T12 + T13 + T16 -> T18 -> T19

T20
T8 + T11 + T18 -> T21 -> T22 -> T23 -> T24
T2 + T15 + T20 + T21 + T23 + T24 -> T25 -> T26

T10 + T19 -> T27
T19 + T24 + T27 -> T28
T25 + T26 + T27 -> T29
T17 + T18 + T27 -> T30
T2 + T9 + T10 + T18 + T19 + T24 + T27 + T30 -> T31

T1 + T15 + T31 -> T32
T1 + T31 -> T33
T31 + T32 + T33 -> T34
T28 + T34 -> T35
T29 + T35 -> T36
T15 + T34 -> T37
T19 + T31 + T34 -> T38
T30 + T38 -> T39
T32 + T33 + T36 + T39 -> T40 -> T41 -> T42
```

T1–T4、T8、T11、T16 和 T20 在依赖允许时可并行；T13–T15 的进程分支与 T16–T19 的会话/运行时分支可并行；T35–T39 的验收测试按各自前置实现完成后可分组推进。任何并行工作都必须避免同时修改同一文件，合并后重新运行相关测试组。

## 需求与验收覆盖索引

| 范围 | 主要任务 |
|---|---|
| F1–F9 | T3–T7、T10、T27、T34 |
| F10–F15 | T11、T12、T18、T21、T24、T28、T35 |
| F16–F18 | T27–T29、T34–T36 |
| F19–F24 | T2、T11、T18、T21、T22、T35 |
| F25–F32 | T2、T20、T21、T25、T26、T29、T36 |
| F33–F43 | T1、T3、T4、T6、T8–T10、T13–T15、T37 |
| F44–F49 | T16、T18、T19、T27、T28、T31、T38 |
| F50–F53 | T17、T30、T39 |
| F54–F57 | T32、T33、T40 |
| N1–N3 | T3–T7、T10、T18、T19、T31、T34、T38 |
| N4–N8 | T2、T8–T11、T14、T15、T21–T26、T32、T35–T37 |
| N9–N12 | T11、T12、T16–T25、T28–T31、T35、T36、T38、T39 |
| N13–N18 | T1–T6、T9、T10、T15–T17、T20、T26–T42 |
| AC1–AC5 | T34 |
| AC6–AC10 | T35 |
| AC11–AC14 | T36 |
| AC15–AC19 | T34、T37 |
| AC20–AC23 | T38 |
| AC24–AC26 | T39 |
| AC27–AC30 | T40 |
| AC31–AC35 | T34–T39、T42 |
