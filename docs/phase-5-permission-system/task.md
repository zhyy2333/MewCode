# MewCode 权限系统 Tasks

## 文件清单

### 新建文件

| 文件 | 职责 |
|---|---|
| `src/mewcode/tools/safety.py` | 不可配置危险命令黑名单与匹配结果 |
| `src/mewcode/permissions/__init__.py` | 权限子系统公共出口 |
| `src/mewcode/permissions/models.py` | 权限枚举、规则模型、决定和确认句柄 |
| `src/mewcode/permissions/config.py` | 三层路径、YAML 加载、校验与原子写入 |
| `src/mewcode/permissions/rules.py` | 规则解析、glob 编译、具体度与分层匹配 |
| `src/mewcode/permissions/targets.py` | 权限目标规范化、黑名单和路径沙箱预检 |
| `src/mewcode/permissions/controller.py` | 权限模式裁决与人工选择应用 |
| `examples/permissions.yaml` | 用户、项目和本地权限规则示例 |
| `tests/test_permission_config.py` | 权限文件加载、校验和原子写入测试 |
| `tests/test_permission_rules.py` | 规则解析、转义、glob、具体度与层级测试 |
| `tests/test_permission_targets.py` | 工具目标与硬安全边界测试 |
| `tests/test_permission_controller.py` | 三档模式和放行范围测试 |
| `tests/test_permission_integration.py` | Scheduler、Agent Loop 和端到端权限测试 |

### 修改文件

| 文件 | 职责 |
|---|---|
| `.gitignore` | 允许共享权限文件、继续忽略本地权限与配置 |
| `README.md` | 权限模式、规则、确认行为和沙箱边界文档 |
| `src/mewcode/cli.py` | 启动参数、权限对象组装与配置错误处理 |
| `src/mewcode/repl.py` | 权限确认、决定渲染和 `/permissions` 命令 |
| `src/mewcode/agent/__init__.py` | 导出权限事件 |
| `src/mewcode/agent/events.py` | 权限请求与决定事件 |
| `src/mewcode/agent/scheduler.py` | 执行前权限预检、确认、拒绝与取消 |
| `src/mewcode/tools/__init__.py` | 导出权限元数据与安全检查 |
| `src/mewcode/tools/base.py` | 工具权限元数据和两阶段注册表执行 |
| `src/mewcode/tools/workspace.py` | 安全路径 glob 和实际匹配项校验 |
| `src/mewcode/tools/builtin.py` | 六个内置工具权限元数据保持完整 |
| `src/mewcode/tools/command_tool.py` | 复用不可配置命令安全检查 |
| `src/mewcode/tools/file_tools.py` | 声明路径权限目标并保持最终复检 |
| `src/mewcode/tools/search_tools.py` | 声明搜索目标并安全遍历 glob 结果 |
| `tests/fakes.py` | 测试工具元数据、允许控制器与确认辅助对象 |
| `tests/test_tools_base.py` | 两阶段注册表和权限元数据测试 |
| `tests/test_workspace.py` | glob、绝对路径、`..` 与符号链接测试 |
| `tests/test_command_tool.py` | 黑名单复检测试 |
| `tests/test_file_tools.py` | 文件工具沙箱回归测试 |
| `tests/test_search_tools.py` | 查找与搜索越界回归测试 |
| `tests/test_tool_scheduler.py` | 权限预检、并发、顺序和取消测试 |
| `tests/test_agent_runner.py` | 权限失败后继续迭代测试 |
| `tests/test_plan_mode.py` | 只读 Plan Mode 权限回归测试 |
| `tests/test_conversation.py` | 显式权限控制器装配回归测试 |
| `tests/test_tool_conversation.py` | 工具对话权限装配回归测试 |
| `tests/test_repl.py` | 确认交互、模式命令和 CLI 测试 |

## A. 工具安全基础

## T1：定义工具权限元数据

**文件：** `src/mewcode/tools/base.py`、`src/mewcode/tools/__init__.py`、`tests/fakes.py`

**依赖：** 无

**步骤：**

1. 新增 `PermissionTargetKind`、`ToolPermissionSpec` 和 `ValidatedToolCall`。
2. 在 `Tool` 协议中声明必需的 `permission_spec`。
3. 为 `ControlledTool` 增加可配置且默认安全的权限目标元数据。
4. 从工具包公共出口导出新增类型。

**验证：** 运行 `python -m pytest tests/test_tools_base.py tests/test_tool_scheduler.py -q`，期望现有测试仍通过且测试工具可读取 `permission_spec`。

## T2：拆分注册表校验与执行

**文件：** `src/mewcode/tools/base.py`、`tests/test_tools_base.py`

**依赖：** T1

**步骤：**

1. 实现 `validate_call()`，保留未知工具和参数 Schema 的原有失败结构。
2. 实现 `execute_validated()`，保留异常包装与工具名。
3. 让现有 `execute()` 组合前两步以保持直接调用兼容。
4. 增加未知工具、坏参数、有效调用和工具异常的两阶段测试。

**验证：** 运行 `python -m pytest tests/test_tools_base.py -q`，期望未知工具、参数错误和异常包装断言全部通过。

## T3：抽取不可配置危险命令检查

**文件：** `src/mewcode/tools/safety.py`、`src/mewcode/tools/command_tool.py`、`src/mewcode/tools/__init__.py`、`tests/test_command_tool.py`

**依赖：** T1

**步骤：**

1. 将危险命令模式移入独立安全模块并在导入时编译。
2. 定义包含类别和短原因的 `DangerousCommandMatch`。
3. 实现大小写不敏感的 `check_dangerous_command()`。
4. 让命令工具在创建子进程前调用共享检查。
5. 扩充 Windows、类 Unix、大小写变体和安全相邻命令测试。

**验证：** 运行 `python -m pytest tests/test_command_tool.py -q`，期望危险样例全部被拒绝，安全样例保持原行为。

## T4：实现安全路径 glob 规范化

**文件：** `src/mewcode/tools/workspace.py`、`tests/test_workspace.py`

**依赖：** 无

**步骤：**

1. 实现路径 glob 非空、非绝对和无 `..` 路径段校验。
2. 提取首个 glob 元字符之前的固定前缀。
3. 解析固定前缀的已有符号链接并检查项目边界。
4. 返回统一 `/` 分隔的项目相对 glob。
5. 增加合法递归 glob、绝对 glob、`..` 和符号链接前缀测试。

**验证：** 运行 `python -m pytest tests/test_workspace.py -q`，期望普通路径回归及新增 glob 边界测试全部通过。

## T5：复检查找与搜索结果边界

**文件：** `src/mewcode/tools/workspace.py`、`src/mewcode/tools/search_tools.py`、`tests/test_search_tools.py`

**依赖：** T4

**步骤：**

1. 实现 `validate_match()`，解析实际匹配项并确认仍位于项目内。
2. 让 `find_files` 在遍历前规范化 glob，并对每个结果复检。
3. 让越界符号链接结果返回沙箱失败且不泄露项目外路径内容。
4. 保持 `search_code` 的搜索根路径复检和取消行为。
5. 增加合法结果、绝对 glob、`..` 和符号链接逃逸测试。

**验证：** 运行 `python -m pytest tests/test_search_tools.py tests/test_workspace.py -q`，期望越界目标失败且合法查找、搜索和取消测试通过。

## T6：为六个内置工具声明权限目标

**文件：** `src/mewcode/tools/command_tool.py`、`src/mewcode/tools/file_tools.py`、`src/mewcode/tools/search_tools.py`、`src/mewcode/tools/builtin.py`、`tests/test_tools_base.py`

**依赖：** T1、T3、T5

**步骤：**

1. 为命令工具声明 `command / COMMAND`。
2. 为读、写、编辑工具声明 `path / PATH`。
3. 为查找工具声明 `pattern / PATH_GLOB`。
4. 为搜索工具声明 `path / PATH` 且默认值为 `.`。
5. 验证内置注册表中的每个工具都有唯一权限目标。

**验证：** 运行 `python -m pytest tests/test_tools_base.py tests/test_file_tools.py tests/test_search_tools.py tests/test_command_tool.py -q`，期望六个工具元数据和原有行为全部通过。

## B. 权限模型、规则与配置

## T7：建立权限领域模型

**文件：** `src/mewcode/permissions/models.py`、`tests/test_permission_rules.py`

**依赖：** T1

**步骤：**

1. 定义模式、效果、结果、用户选择、层级和来源枚举。
2. 定义目标、规则、规则集合、匹配和决定数据类。
3. 实现 `PermissionTarget.exact_rule()` 的基础格式。
4. 增加枚举值、不可变性和规则表达式格式测试。

**验证：** 运行 `python -m pytest tests/test_permission_rules.py -q`，期望领域模型测试通过。

## T8：实现精确规则转义

**文件：** `src/mewcode/permissions/models.py`、`tests/test_permission_rules.py`

**依赖：** T7

**步骤：**

1. 定义反斜杠及 `*`、`?`、`[`、`]` 的字面量转义。
2. 让 `exact_rule()` 转义真实目标中的上述字符。
3. 增加普通命令、Windows 反斜杠、通配符字符和括号目标测试。

**验证：** 运行 `python -m pytest tests/test_permission_rules.py -q -k exact_rule`，期望生成的表达式可无损表示原目标且不会扩大匹配。

## T9：实现一次性确认句柄

**文件：** `src/mewcode/permissions/models.py`、`tests/test_permission_controller.py`

**依赖：** T7

**步骤：**

1. 实现基于当前事件循环 Future 的 `PermissionChallenge`。
2. 实现一次性 `resolve()`、`cancel()` 和 `wait()`。
3. 拒绝重复响应并确保取消可唤醒等待方。
4. 增加先响应后等待、先等待后响应、重复响应和取消测试。

**验证：** 运行 `python -m pytest tests/test_permission_controller.py -q -k challenge`，期望所有生命周期测试结束且无挂起任务。

## T10：解析规则表达式与转义

**文件：** `src/mewcode/permissions/rules.py`、`tests/test_permission_rules.py`

**依赖：** T7、T8

**步骤：**

1. 以首个 `(` 和末个 `)` 拆分实际工具名和模式。
2. 校验空工具名、未知工具、缺失括号、外层多余文本和非法转义。
3. 区分未转义 glob 元字符与精确模式。
4. 将合法转义还原为匹配器可消费的 token。
5. 增加合法内部括号和全部非法语法测试。

**验证：** 运行 `python -m pytest tests/test_permission_rules.py -q -k parse`，期望合法表达式解析稳定，非法表达式给出明确错误。

## T11：实现命令 glob 完整匹配

**文件：** `src/mewcode/permissions/rules.py`、`tests/test_permission_rules.py`

**依赖：** T10

**步骤：**

1. 将命令 `*`、`?` 和字符集合编译为大小写敏感的完整匹配正则。
2. 让命令中的 `/` 与空格可由 `*` 匹配。
3. 让转义的 glob 字符只按字面量匹配。
4. 增加 `git *`、大小写差异、空格余部和转义通配符测试。

**验证：** 运行 `python -m pytest tests/test_permission_rules.py -q -k command_glob`，期望命令规则只匹配完整目标且保持大小写敏感。

## T12：实现路径 glob 与具体度

**文件：** `src/mewcode/permissions/rules.py`、`tests/test_permission_rules.py`

**依赖：** T10

**步骤：**

1. 将路径 `*`、`?`、字符集合限制在单个 `/` 路径段。
2. 将 `**` 编译为可跨路径段的递归匹配。
3. 按当前平台规范化路径匹配大小写。
4. 计算精确标记、固定文本数和路径段长度具体度。
5. 增加 `src/*`、`src/**`、平台大小写和具体度排序测试。

**验证：** 运行 `python -m pytest tests/test_permission_rules.py -q -k "path_glob or specificity"`，期望路径段语义和具体度断言通过。

## T13：实现分层规则匹配

**文件：** `src/mewcode/permissions/rules.py`、`tests/test_permission_rules.py`

**依赖：** T11、T12

**步骤：**

1. 在单层内选择具体度最高的候选。
2. 具体度完全相同时让 `deny` 获胜。
3. 按会话、本地项目、共享项目、用户全局逐层停止。
4. 确认配置声明顺序不影响结果。
5. 增加跨层冲突、精确覆盖 glob、窄 glob 覆盖宽 glob和并列拒绝测试。

**验证：** 运行 `python -m pytest tests/test_permission_rules.py -q -k "scope or precedence"`，期望全部优先级场景通过。

## T14：实现权限文件路径与缺失文件加载

**文件：** `src/mewcode/permissions/config.py`、`tests/test_permission_config.py`

**依赖：** T7、T10

**步骤：**

1. 实现用户全局、项目共享和项目本地固定路径。
2. 支持测试注入用户主目录。
3. 将缺失文件和缺失 `rules` 字段加载为空层。
4. 给加载出的规则标注正确 scope。

**验证：** 运行 `python -m pytest tests/test_permission_config.py -q -k "paths or missing"`，期望路径和空规则集测试通过且不创建文件。

## T15：实现 YAML 结构和规则校验

**文件：** `src/mewcode/permissions/config.py`、`tests/test_permission_config.py`

**依赖：** T10、T14

**步骤：**

1. 使用 `yaml.safe_load` 读取 UTF-8 文件。
2. 校验根节点、`rules` 列表、规则项字段、字符串类型和 `allow/deny`。
3. 用实际注册工具名集合解析每条规则。
4. 将 YAML 和规则语法错误包装为含路径的 `PermissionConfigError`。
5. 增加损坏 YAML、未知工具、未知结果、额外字段和合法三层文件测试。

**验证：** 运行 `python -m pytest tests/test_permission_config.py -q -k load`，期望合法文件完整加载，所有无效文件失败关闭。

## T16：实现项目本地规则原子写入

**文件：** `src/mewcode/permissions/config.py`、`tests/test_permission_config.py`

**依赖：** T15

**步骤：**

1. 写入前重新读取并验证磁盘上的本地文件。
2. 去重相同精确 `allow`，保留全部其他规则数据。
3. 在目标目录创建临时文件并安全转储 YAML。
4. 刷新后重新加载临时文件，再用 `os.replace` 替换目标。
5. 清理失败临时文件并保持原文件完整。
6. 增加新文件、去重、外部新增规则、损坏磁盘文件和替换失败测试。

**验证：** 运行 `python -m pytest tests/test_permission_config.py -q -k "write or persist or atomic"`，期望成功写入可重载，失败路径不修改旧文件。

## T17：实现规则仓库与会话放行

**文件：** `src/mewcode/permissions/rules.py`、`tests/test_permission_rules.py`

**依赖：** T13

**步骤：**

1. 在规则模块声明窄 `LocalRuleWriter` 协议，并通过构造参数接收实现。
2. 保存三层持久化规则和独立会话规则。
3. 以不可变快照暴露四层规则集。
4. 添加会话精确 `allow` 并去重。
5. 让 `match()` 委托分层匹配器。
6. 增加会话规则优先、去重和新仓库无残留测试。

**验证：** 运行 `python -m pytest tests/test_permission_rules.py -q -k store`，期望会话规则仅存在于当前仓库实例且优先级最高。

## T18：集成永久规则写入与内存刷新

**文件：** `src/mewcode/permissions/rules.py`、`src/mewcode/permissions/config.py`、`tests/test_permission_config.py`

**依赖：** T16、T17

**步骤：**

1. 让 `PermissionConfigWriter` 以鸭子类型实现 `LocalRuleWriter` 协议。
2. 在线程中调用注入的项目本地配置写入器。
3. 写入成功后以磁盘最新规则替换仓库的本地层快照。
4. 写入失败时保持会话与内存持久层不变。
5. 增加写入成功立即匹配和失败无状态变化测试。

**验证：** 运行 `python -m pytest tests/test_permission_config.py tests/test_permission_rules.py -q -k permanent`，期望磁盘与内存结果一致。

## T19：整理权限包公共出口

**文件：** `src/mewcode/permissions/__init__.py`

**依赖：** T7、T13、T18

**步骤：**

1. 导出配置、模型、规则仓库和匹配器的稳定类型。
2. 避免在包导入时读取配置或创建 Future。
3. 检查工具包与权限包可按任意顺序导入。

**验证：** 运行 `python -c "import mewcode.tools; import mewcode.permissions; import mewcode.agent"`，期望无循环导入和运行期副作用。

## C. 权限目标与模式控制

## T20：构造命令权限目标并执行硬拦截

**文件：** `src/mewcode/permissions/targets.py`、`tests/test_permission_targets.py`

**依赖：** T2、T3、T7

**步骤：**

1. 从有效命令调用提取并去除命令首尾空白。
2. 在目标返回前执行共享黑名单检查。
3. 安全命令返回 `COMMAND` 目标，危险命令返回 `DENY / BLACKLIST`。
4. 确保决定原因不包含无关参数。

**验证：** 运行 `python -m pytest tests/test_permission_targets.py -q -k command`，期望安全命令目标规范化，危险命令无目标且不可询问。

## T21：构造普通路径权限目标

**文件：** `src/mewcode/permissions/targets.py`、`tests/test_permission_targets.py`

**依赖：** T2、T4、T7

**步骤：**

1. 读取 `PATH` 参数或声明的默认值。
2. 用 Workspace 解析符号链接并验证项目边界。
3. 返回 `/` 分隔的项目相对目标。
4. 将绝对越界、`..` 和符号链接越界转换为 `DENY / SANDBOX`。
5. 验证写入内容、替换文本和搜索词不影响目标。

**验证：** 运行 `python -m pytest tests/test_permission_targets.py -q -k path`，期望项目内目标成功且所有越界形式拒绝。

## T22：构造路径 glob 并拒绝未声明工具

**文件：** `src/mewcode/permissions/targets.py`、`tests/test_permission_targets.py`

**依赖：** T4、T20、T21

**步骤：**

1. 用 Workspace 规范化 `PATH_GLOB` 目标。
2. 将非法 glob 转换为 `DENY / SANDBOX`。
3. 对缺少 `permission_spec`、参数或默认值的有效工具失败关闭。
4. 增加 `find_files` 合法递归模式和未声明测试工具场景。

**验证：** 运行 `python -m pytest tests/test_permission_targets.py -q`，期望三类目标和失败关闭场景全部通过。

## T23：实现三档权限模式矩阵

**文件：** `src/mewcode/permissions/controller.py`、`tests/test_permission_controller.py`

**依赖：** T17、T20、T21、T22

**步骤：**

1. 保存并切换当前 `PermissionMode`。
2. 在规则匹配前尊重目标构造器的硬拒绝。
3. 实现显式 `deny` 在三种模式均拒绝。
4. 实现会话 `allow` 在三种模式均放行。
5. 实现持久化 `allow` 和未命中项的严格、默认、放行矩阵。

**验证：** 运行 `python -m pytest tests/test_permission_controller.py -q -k mode`，期望决策矩阵全部组合通过。

## T24：应用拒绝、本次与会话选择

**文件：** `src/mewcode/permissions/controller.py`、`tests/test_permission_controller.py`

**依赖：** T23

**步骤：**

1. 将 `DENY` 转为用户确认来源的拒绝决定。
2. 将 `ONCE` 转为只影响当前调用的允许决定。
3. 将 `SESSION` 写入会话精确规则后允许。
4. 验证不同目标不会被会话规则误放行。
5. 验证包含 glob 字符的目标仍生成精确会话规则。

**验证：** 运行 `python -m pytest tests/test_permission_controller.py -q -k "once or session or deny"`，期望三种选择作用域正确。

## T25：应用永久选择与失败关闭

**文件：** `src/mewcode/permissions/controller.py`、`src/mewcode/permissions/__init__.py`、`tests/test_permission_controller.py`

**依赖：** T18、T24

**步骤：**

1. 对 `PERMANENT` 先等待项目本地持久化成功。
2. 成功后加入会话精确规则并允许当前调用。
3. 将配置写入错误转换为 `DENY / CONFIG_ERROR`。
4. 确认失败时不增加会话规则且当前工具不能执行。
5. 从权限包公共出口导出目标构造器和控制器的稳定类型。

**验证：** 运行 `python -m pytest tests/test_permission_controller.py -q -k permanent`，期望成功路径同时更新两层，失败路径无权限状态变化。

## D. Agent 事件与工具调度

## T26：增加权限 Agent 事件

**文件：** `src/mewcode/agent/events.py`、`src/mewcode/agent/__init__.py`、`tests/test_permission_integration.py`

**依赖：** T9、T19

**步骤：**

1. 定义 `AgentPermissionRequest` 和 `AgentPermissionDecision`。
2. 将事件加入 `AgentEvent` 联合类型和公共出口。
3. 验证请求事件只含挑战句柄及脱敏字段。

**验证：** 运行 `python -m pytest tests/test_permission_integration.py -q -k events`，期望事件可构造、导入且不包含完整工具参数。

## T27：接入 Scheduler 的校验与自动放行预检

**文件：** `src/mewcode/agent/scheduler.py`、`tests/fakes.py`、`tests/test_tool_scheduler.py`、`tests/test_agent_runner.py`、`tests/test_plan_mode.py`、`tests/test_conversation.py`、`tests/test_tool_conversation.py`

**依赖：** T2、T23、T26

**步骤：**

1. 让 `ToolScheduler` 必须接收权限控制器。
2. 为现有非权限测试提供显式自动允许控制器假对象。
3. 更新所有 Scheduler 构造点，不提供隐式放行默认值。
4. 在每批开始后按原始顺序调用 `validate_call()` 和 `evaluate()`。
5. 让自动允许的调用进入原有执行路径并发出允许决定事件。

**验证：** 运行 `python -m pytest tests/test_tool_scheduler.py tests/test_agent_runner.py tests/test_plan_mode.py tests/test_conversation.py tests/test_tool_conversation.py -q`，期望原调度和 Agent 行为保持通过。

## T28：生成权限拒绝结果并保持批次独立

**文件：** `src/mewcode/agent/scheduler.py`、`tests/test_tool_scheduler.py`、`tests/test_permission_integration.py`

**依赖：** T27

**步骤：**

1. 将拒绝决定转换为带权限 metadata 的失败 `ToolResult`。
2. 发出拒绝决定事件和普通工具结果事件。
3. 不调用被拒绝工具的 `execute()`。
4. 继续执行同批其他获准工具。
5. 按原始索引保存最终 executions。

**验证：** 运行 `python -m pytest tests/test_tool_scheduler.py tests/test_permission_integration.py -q -k "deny or mixed"`，期望拒绝项零调用、允许项正常执行且结果排序正确。

## T29：实现确认请求与串行响应

**文件：** `src/mewcode/agent/scheduler.py`、`tests/test_tool_scheduler.py`、`tests/test_permission_integration.py`

**依赖：** T24、T25、T26、T28

**步骤：**

1. 对 `ASK` 创建并记录活动 `PermissionChallenge`。
2. 发出请求事件，在消费者响应后等待并应用选择。
3. 发出最终允许或拒绝决定事件。
4. 对同批多个请求按模型顺序逐个确认。
5. 确认结束后清除活动句柄。

**验证：** 运行 `python -m pytest tests/test_tool_scheduler.py tests/test_permission_integration.py -q -k "ask or prompt or serial"`，期望提示顺序稳定且每个选择只作用于对应调用。

## T30：保持只读并发和 Provider 结果顺序

**文件：** `src/mewcode/agent/scheduler.py`、`tests/test_tool_scheduler.py`

**依赖：** T28、T29

**步骤：**

1. 在整个只读批次预检完成后才启动获准任务。
2. 保持最大只读并发限制。
3. 保持副作用调用独占屏障。
4. 允许结果事件按完成时间出现，但 executions 按原始顺序保存。
5. 增加读批次中部分拒绝后的并发测试。

**验证：** 运行 `python -m pytest tests/test_tool_scheduler.py -q`，期望原并发上限、屏障、完成顺序和新增权限批次测试全部通过。

## T31：扩展权限确认取消语义

**文件：** `src/mewcode/agent/scheduler.py`、`tests/test_tool_scheduler.py`、`tests/test_permission_integration.py`

**依赖：** T29、T30

**步骤：**

1. `ToolSchedule.cancel()` 取消当前确认句柄。
2. 阻止尚未获准和后续批次工具启动。
3. 保持活动工具任务的现有取消行为。
4. 确保取消后没有未完成 Future 或后台任务。
5. 增加确认期间取消和确认后执行期间取消测试。

**验证：** 运行 `python -m pytest tests/test_tool_scheduler.py tests/test_permission_integration.py -q -k cancel`，期望一秒内结束且未获准工具调用次数为零。

## T32：验证权限拒绝后 Agent Loop 继续

**文件：** `tests/test_agent_runner.py`、`tests/test_permission_integration.py`

**依赖：** T28、T31

**步骤：**

1. 用脚本化 Provider 首轮请求被拒绝工具。
2. 验证拒绝结果被回写为普通工具消息。
3. 让 Provider 下一轮改用获准工具或返回最终文本。
4. 验证任务以 `COMPLETED` 而非权限停止原因结束。
5. 验证权限拒绝不增加连续未知工具计数。

**验证：** 运行 `python -m pytest tests/test_agent_runner.py tests/test_permission_integration.py -q -k "permission and loop"`，期望拒绝后至少再发生一次模型迭代并正常完成。

## E. REPL、CLI 与用户配置

## T33：渲染脱敏权限决定事件

**文件：** `src/mewcode/repl.py`、`tests/test_repl.py`

**依赖：** T26、T28

**步骤：**

1. 为权限决定事件增加次级缩进输出。
2. 区分自动允许、黑名单、沙箱、规则、用户和配置错误来源。
3. 只显示工具名、规范化目标、结果和短原因。
4. 增加文件内容、替换文本和完整规则不出现在输出中的测试。

**验证：** 运行 `python -m pytest tests/test_repl.py -q -k permission`，期望各类别文本可区分且敏感样例不出现在输出中。

## T34：处理四种确认输入

**文件：** `src/mewcode/repl.py`、`tests/test_repl.py`

**依赖：** T9、T29、T33

**步骤：**

1. 收到请求事件时显示固定四选项提示。
2. 将 `d/o/s/p` 及完整单词映射到对应选择。
3. 对空输入和非法输入重复提示。
4. 将 EOF 解析为拒绝，将 KeyboardInterrupt 交给现有 Agent 取消流程。
5. 增加每种输入、非法重试、EOF 和取消测试。

**验证：** 运行 `python -m pytest tests/test_repl.py -q -k "permission_request or confirmation"`，期望响应句柄获得正确选择且异常路径不放行。

## T35：实现 `/permissions` 模式命令

**文件：** `src/mewcode/repl.py`、`tests/test_repl.py`

**依赖：** T23、T34

**步骤：**

1. 让 Repl 接收共享权限控制器。
2. 在普通消息路由前处理模式查询。
3. 支持 strict、default、allow 三种切换。
4. 对非法参数显示用法且不调用 Conversation 或 Provider。
5. 更新启动帮助文本。

**验证：** 运行 `python -m pytest tests/test_repl.py -q -k permissions`，期望查询和切换输出正确且 FakeConversation 无新增调用。

## T36：解析 CLI 权限模式参数

**文件：** `src/mewcode/cli.py`、`tests/test_repl.py`

**依赖：** T23

**步骤：**

1. 使用参数解析器处理 `argv`。
2. 新增 `--permission-mode` 三个合法选择并默认 `default`。
3. 保持无参数启动和 `main()` 返回码语义。
4. 增加默认、三个合法值和非法值测试。

**验证：** 运行 `python -m pytest tests/test_repl.py -q -k "cli and permission_mode"`，期望合法值进入组装流程，非法值产生用法错误且不启动 Provider。

## T37：在 CLI 组装完整权限对象

**文件：** `src/mewcode/cli.py`、`src/mewcode/repl.py`、`tests/test_repl.py`

**依赖：** T18、T19、T23、T27、T35、T36

**步骤：**

1. 按批准顺序创建 Workspace、工具注册表、权限路径与规则。
2. 用实际工具名校验配置并创建目标构造器、仓库和控制器。
3. 将控制器注入 Scheduler 与 Repl。
4. 捕获 `PermissionConfigError`，输出短错误并返回非零状态。
5. 更新现有 CLI fake 以断言所选模式和共享实例。

**验证：** 运行 `python -m pytest tests/test_repl.py -q -k cli`，期望成功组装、Provider 错误、权限配置错误和 KeyboardInterrupt 返回码均正确。

## T38：配置共享与本地文件忽略规则

**文件：** `.gitignore`、`examples/permissions.yaml`

**依赖：** T15

**步骤：**

1. 将根目录 `.mewcode` 忽略规则改为忽略内容。
2. 单独放行 `.mewcode/permissions.yaml`。
3. 确认 `.mewcode/permissions.local.yaml` 和 `.mewcode/config.yaml` 仍被忽略。
4. 新增覆盖 allow、deny、精确、命令 glob 和路径 glob 的示例文件。

**验证：** 运行 `git check-ignore -v .mewcode/permissions.local.yaml .mewcode/config.yaml`，期望两者被忽略；运行 `git check-ignore .mewcode/permissions.yaml`，期望退出码为 1；运行 `python -c "import yaml; yaml.safe_load(open('examples/permissions.yaml', encoding='utf-8'))"`，期望成功。

## T39：更新权限系统用户文档

**文件：** `README.md`

**依赖：** T35、T36、T38

**步骤：**

1. 说明默认模式、启动参数和 `/permissions` 命令。
2. 说明三层 YAML 路径、规则格式、glob 和反斜杠转义。
3. 说明四种确认选择和永久放行仅写项目本地。
4. 明确黑名单和路径沙箱不可绕过。
5. 明确路径沙箱不隔离命令子进程，并列出本阶段排除项。

**验证：** 运行 `rg -n "permission-mode|/permissions|permissions\.local\.yaml|run_command\(git|路径沙箱|命令子进程" README.md`，期望每个主题至少出现一次。

## F. 集成验证与收尾

## T40：完成权限专项集成测试

**文件：** `tests/test_permission_integration.py`、`tests/test_permission_config.py`、`tests/test_permission_rules.py`、`tests/test_permission_targets.py`、`tests/test_permission_controller.py`

**依赖：** T1-T39

**步骤：**

1. 覆盖黑名单和沙箱在放行模式与显式 allow 下仍拒绝。
2. 覆盖四层优先级、具体度、三档模式和四种确认选择。
3. 覆盖永久写入、严格模式新会话首次确认和默认模式直接采用。
4. 覆盖同批拒绝与允许、确认串行、取消及 Agent Loop 恢复。
5. 覆盖输出脱敏和无真实外部文件访问。

**验证：** 运行 `python -m pytest tests/test_permission_config.py tests/test_permission_rules.py tests/test_permission_targets.py tests/test_permission_controller.py tests/test_permission_integration.py -q`，期望权限专项测试全部通过。

## T41：执行全量回归与构建检查

**文件：** 全部实现与测试文件

**依赖：** T40

**步骤：**

1. 运行完整测试套件。
2. 编译全部 Python 源文件。
3. 检查文档和源码不存在占位标记。
4. 检查权限实现没有网络限制、资源配额或审计日志模块。
5. 检查工作树只包含本阶段预期文件。

**验证：** 运行 `python -m pytest -q` 和 `python -m compileall -q src`，期望退出码均为 0；运行 `rg -n "T[B]D|TO[D]O" src tests docs/phase-5-permission-system README.md`，期望无本阶段遗留项。

## 执行顺序

```text
T1 -> T2
 ├─> T3
 └─> T4 -> T5
          \-> T6

T1 -> T7 -> T8 -> T10 -> T11 -> T12 -> T13
          \-> T9
T13 -> T14 -> T15 -> T16 -> T17 -> T18 -> T19

T2 + T3 + T7  -> T20
T2 + T4 + T7  -> T21
T4 + T20 + T21 -> T22
T17 + T20-T22 -> T23 -> T24
T18 + T24     -> T25

T9 + T19 -> T26
T2 + T23 + T26 -> T27 -> T28 -> T30
T24 + T25 + T26 + T28 -> T29 -> T31
T28 + T31 -> T32

T26 + T28 -> T33
T9 + T29 + T33 -> T34 -> T35
T23 -> T36
T18 + T19 + T23 + T27 + T35 + T36 -> T37
T15 -> T38
T35 + T36 + T38 -> T39

T1-T39 -> T40 -> T41
```

## 提交节点

每组完成且对应验证通过后提交一次，提交内容不得混入后续未验证任务：

1. T1-T6：工具权限元数据、黑名单与工作区安全基础。
2. T7-T19：权限模型、规则、配置与持久化。
3. T20-T25：目标构造、模式矩阵与放行范围。
4. T26-T32：Agent 事件、Scheduler 和 Loop 集成。
5. T33-T39：REPL、CLI、示例与用户文档。
6. T40-T41：专项测试补齐与全量验收修正。
