# Hook 自动化系统 Tasks

## 执行约束

- 本清单只能在 `spec.md`、`plan.md`、本文件和后续 `checklist.md` 全部批准后开始实施。
- 每个任务只处理列出的范围；如需改变已批准的事件语义、YAML 契约、安全顺序、信任模型或资源限制，必须先返回文档阶段。
- 测试默认使用临时工作区、临时用户目录、假 Provider、`httpx.MockTransport`、假时钟和受控短命子进程；不得读取真实用户 Hook、访问真实网络或执行真实危险命令。
- 每完成一个任务，先运行该任务的定向验证；每组集成任务完成后运行对应测试组，最后再执行全量回归。
- 安全与失败路径必须和成功路径在同一任务中完成。不得先提交会执行项目共享命令、泄露凭据、吞掉取消或绕过权限的中间实现。
- Hook 运行期普通错误一律收敛为诊断并放行主流程；`asyncio.CancelledError` 只在完成动作清理后继续传播；合法 `tool.before deny` 是业务结果而不是异常。
- 工作区已有 Python 缓存变动和其他用户改动不属于本阶段范围。实施时不得清理、覆盖或提交这些无关文件。
- 每组逻辑相关任务验证通过后创建一次范围清晰的提交；提交中不得混入无关工作区变动。

## 文件清单

### 新增实现

| 文件 | 职责 |
|---|---|
| `src/mewcode/matching.py` | 权限与 Hook 共用的精确/glob token、转义和完整匹配 |
| `src/mewcode/processes.py` | 有界 shell stdin/stdout/stderr、超时、取消和跨平台进程树终止 |
| `src/mewcode/hooks/__init__.py` | Hook 子系统稳定公共导出 |
| `src/mewcode/hooks/models.py` | 事件、来源、条件、动作、目录、结果、诊断和资源限制模型 |
| `src/mewcode/hooks/config.py` | 三层路径与严格 YAML 解析、编译、排序和原子目录构建 |
| `src/mewcode/hooks/trust.py` | 工作区身份、用户级信任读取、锁和原子持久化 |
| `src/mewcode/hooks/events.py` | 11 个事件工厂、公开字段注册、状态与有界 JSON 信封 |
| `src/mewcode/hooks/conditions.py` | 点路径、exact/glob/regex/negate 和 all/any 求值 |
| `src/mewcode/hooks/actions.py` | command/HTTP/prompt/agent 执行和工具决策协议 |
| `src/mewcode/hooks/diagnostics.py` | 脱敏、有界、轮转 JSONL 诊断日志 |
| `src/mewcode/hooks/runtime.py` | 信任过滤、匹配、`once`、顺序、后台、提示队列和关闭 |
| `src/mewcode/hooks/provider.py` | `HookedProvider` 的 message 前后事件和提示消费 |

### 新增测试与示例

| 文件 | 职责 |
|---|---|
| `tests/test_matching.py` | 共享精确/glob、转义和 TEXT/PATH 语义 |
| `tests/test_processes.py` | 有界 I/O、超时、取消和进程树清理 |
| `tests/test_hook_config.py` | 三层加载、严格字段、动作组合、限制和原子错误 |
| `tests/test_hook_trust.py` | 身份隔离、信任读写、锁、损坏和 fail-closed |
| `tests/test_hook_events.py` | 事件字段、状态、信封截断和隐私 |
| `tests/test_hook_conditions.py` | 字段路径、逻辑、匹配、缺失值和 regex 超时 |
| `tests/test_hook_actions.py` | 四类动作、进程、HTTP、凭据和决策协议 |
| `tests/test_hook_runtime.py` | 顺序、信任、`once`、提示、后台、关闭和故障隔离 |
| `tests/test_hook_provider.py` | 每次 Provider 交互、提示注入、异常与取消 |
| `tests/test_hook_integration.py` | 会话到 Provider、压缩、工具与权限的端到端验收 |
| `tests/test_cli.py` | Hook 启动原子性、Provider 装饰、依赖注入和关闭兜底 |
| `examples/hooks.yaml` | 三要素、三种条件匹配、四类动作和执行控制示例 |

### 修改范围

| 文件或区域 | 改动 |
|---|---|
| `pyproject.toml` | 增加支持匹配超时的 `regex` 依赖 |
| `src/mewcode/permissions/rules.py`、`controller.py`、`models.py`、`__init__.py` 及权限测试 | 复用共享 glob；增加硬预检与常规策略两阶段接口 |
| `src/mewcode/tools/command_tool.py` 及命令工具测试 | 复用有界进程层且保持原有结果与 30/120 秒边界 |
| `src/mewcode/agent/runner.py`、`scheduler.py` 及 Agent/调度测试 | run/iteration 作用域、系统错误、tool 前后事件和拒绝结果 |
| `src/mewcode/context/manager.py` 及上下文测试 | 真正的手动/自动历史压缩前后事件 |
| `src/mewcode/conversation.py` 及会话/Skill 测试 | session/turn 成对生命周期和关闭顺序 |
| `src/mewcode/terminal.py`、`src/mewcode/repl.py` 及终端测试 | 工作区信任交互、session 启停、错误上报和降噪 |
| `src/mewcode/cli.py` 及 CLI 测试 | Hook 配置、信任、日志、运行时、Provider 装饰、依赖注入和关闭 |
| `tests/fakes.py` | 可记录 Hook、时钟、动作和作用域的测试替身 |
| `.gitignore` | 允许项目共享 `hooks.yaml`，继续忽略 `hooks.local.yaml` 和运行日志 |
| `README.md` | 配置、事件、条件、动作、信任、决策协议、日志、限制和边界 |

## 基础匹配、模型与配置

## T1：登记 regex 运行依赖

**文件：** `pyproject.toml`
**依赖：** 无
**覆盖：** F28、N7、N11

**步骤：**

1. 增加带运行时匹配超时能力的 `regex` 依赖并设置兼容版本边界。
2. 保持现有 Python、httpx、PyYAML 和 jsonschema 依赖约束不变。
3. 增加最小导入断言，确认目标 API 支持 `fullmatch(..., timeout=...)`。

**验证：** 运行 `python -c "import regex; assert regex.fullmatch('a+', 'aaa', timeout=0.05)"`，期望无输出且退出码为 0。

## T2：定义 Hook 核心模型和固定限制

**文件：** `src/mewcode/hooks/models.py`、`tests/test_hook_config.py`
**依赖：** T1
**覆盖：** F1、F13、F21、F26–F28、F32、F40–F41、F46–F49、F53–F54、N1、N7

**步骤：**

1. 定义 11 个事件、三种来源、三种匹配、两种逻辑、四类动作、执行控制、规则键、目录、决策、动作结果和诊断模型。
2. 固化规则、条件、prompt、信封、输出、HTTP、拒绝原因、后台数量、关闭窗口和日志轮转限制。
3. 让目录和 headers 使用不可变元组/映射，规则身份只由来源、规范路径和文件索引组成。
4. 验证布尔与整数不会因 Python 类型继承关系混淆，条件标量不接受 null、对象或数组。

**验证：** 运行 `python -m pytest tests/test_hook_config.py -q -k 'models or limits or immutable'`，期望模型、默认值和上限断言通过。

## T3：抽取共享完整 glob 匹配器

**文件：** `src/mewcode/matching.py`、`tests/test_matching.py`
**依赖：** 无
**覆盖：** F28、F31、N1、N13

**步骤：**

1. 从权限规则实现提取 token 化、合法转义、字符集合校验和完整正则编译。
2. 提供 TEXT 与 PATH 两种 subject 语义；TEXT 的 `*` 可跨空格与 `/`，PATH 的 `*` 不跨 `/`、`**` 可递归。
3. 保留 Windows 路径大小写和其他平台大小写语义，普通 TEXT 始终大小写敏感。
4. 覆盖精确、`*`、`**`、`?`、字符集合、反斜杠转义和非法模式。

**验证：** 运行 `python -m pytest tests/test_matching.py -q`，期望 TEXT/PATH 与转义矩阵全部通过。

## T4：让权限规则复用共享匹配器

**文件：** `src/mewcode/permissions/rules.py`、`tests/test_permission_rules.py`
**依赖：** T3
**覆盖：** F28、F31、N10、N13

**步骤：**

1. 删除权限模块内重复的 token、转义和 glob 编译逻辑，改用 `mewcode.matching`。
2. 将 `PermissionTargetKind` 稳定映射到 TEXT 或 PATH，不引入 regex、negate 或新的 YAML 字段。
3. 保持具体度计算、层级优先级、精确高于 glob、并列 deny 获胜等原行为。
4. 增加共享匹配器与权限规则对同一模式产生相同结果的回归断言。

**验证：** 运行 `python -m pytest tests/test_permission_rules.py tests/test_permission_config.py -q`，期望权限专项测试零回归。

## T5：建立事件字段注册表和基础工厂

**文件：** `src/mewcode/hooks/events.py`、`tests/test_hook_events.py`
**依赖：** T2
**覆盖：** F13–F14、F21、F27、N1、N6

**步骤：**

1. 定义每个事件允许的静态字段路径和 `tool.arguments.*` 动态路径规则。
2. 实现公共 schema 版本、UTC 时间、工作区和会话字段的规范化基础工厂。
3. 实现 `session.start/end` 与 `turn.start/end` 工厂，校验状态和值域。
4. 返回只读事件树，不向调用方暴露可修改字典。

**验证：** 运行 `python -m pytest tests/test_hook_events.py -q -k 'registry or session or turn'`，期望固定目录和基础字段断言通过。

## T6：实现字段路径与条件求值

**文件：** `src/mewcode/hooks/conditions.py`、`tests/test_hook_conditions.py`
**依赖：** T1、T2、T3、T5
**覆盖：** F26–F31、N1、N7、N13

**步骤：**

1. 实现只遍历 Mapping 和数组索引的点路径解析，禁止属性访问和代码执行。
2. 实现类型严格的 exact、共享 TEXT/PATH glob、带 50ms 超时的 regex 完整匹配和 `negate`。
3. 缺失字段或类型不符先得到基础 `False`，再应用 `negate`；regex 超时记录条件错误并返回不匹配。
4. 实现无条件、`all` 和 `any`，不支持嵌套组。

**验证：** 运行 `python -m pytest tests/test_hook_conditions.py -q`，期望路径、类型、三种匹配、反向、逻辑和超时用例通过。

## T7：实现三层 HookPaths 与稳定加载顺序

**文件：** `src/mewcode/hooks/config.py`、`tests/test_hook_config.py`
**依赖：** T2
**覆盖：** F3–F4、F6–F7、N1–N2

**步骤：**

1. 定义用户全局、项目共享和项目本地三个固定路径。
2. 缺失文件解析为空，存在文件按用户→项目共享→项目本地合并，文件内保持列表顺序。
3. 每条规则创建稳定 `HookRuleKey`，不依赖目录枚举、哈希随机化或生成 UUID。
4. 只读取启动快照，不实现 watcher 或重载入口。

**验证：** 运行 `python -m pytest tests/test_hook_config.py -q -k 'paths or layers or order or missing'`，期望三层顺序和身份稳定。

## T8：实现严格规则与条件 YAML 解析

**文件：** `src/mewcode/hooks/config.py`、`tests/test_hook_config.py`
**依赖：** T5–T7
**覆盖：** F1–F2、F5、F26–F31、N2、N7

**步骤：**

1. 严格校验根 `hooks`、规则 `event/if/action` 和条件 `all|any` 字段集合。
2. 根据事件字段注册表校验静态路径，并允许 `tool.arguments` 下的动态嵌套路径。
3. 校验条件数量、字段和值长度、标量类型、glob 转义和 regex 长度/编译合法性。
4. 错误包含文件、规则索引和字段路径，不把部分解析结果加入目录。

**验证：** 运行 `python -m pytest tests/test_hook_config.py -q -k 'root or rule or condition or regex or field'`，期望合法条件通过且所有严格错误准确定位。

## T9：实现四类动作 YAML 与原子目录构建

**文件：** `src/mewcode/hooks/config.py`、`tests/test_hook_config.py`
**依赖：** T8
**覆盖：** F5–F6、F32–F39、F46、F48–F49、N1–N2、N7

**步骤：**

1. 按批准契约严格解析 command、prompt、HTTP 和 agent 的专属字段、默认值与限制。
2. 拒绝字符串布尔、未知字段、超时越界、非法方法/URL、prompt/agent 后台和任何 `tool.before + background`。
3. 计算 `requires_project_trust`，只由项目共享 command/HTTP 规则决定。
4. 三个文件全部成功后一次冻结 `rules` 和 `by_event`；失败时不构造 HTTP client、日志或运行时对象。

**验证：** 运行 `python -m pytest tests/test_hook_config.py -q`，期望三层、四动作、非法组合、限制和整批原子失败测试通过。

## T10：导出 Hook 配置与模型公共 API

**文件：** `src/mewcode/hooks/__init__.py`、`tests/test_hook_config.py`
**依赖：** T2、T9
**覆盖：** N13

**步骤：**

1. 只导出业务集成所需的模型、事件工厂、加载器、异常和运行时协议。
2. 避免从公共入口导出内部 YAML、regex、日志轮转或进程实现。
3. 确认导入 Hook 包不会读取文件、创建目录、打开网络或启动任务。

**验证：** 运行 `python -m pytest tests/test_hook_config.py -q -k 'public_api or import_side_effect'`，期望导出稳定且导入无副作用。

## 工作区信任与进程边界

## T11：实现工作区身份与信任读取

**文件：** `src/mewcode/hooks/trust.py`、`tests/test_hook_trust.py`
**依赖：** T2
**覆盖：** F8–F10、N5、N11

**步骤：**

1. 将 `resolve()` 后的平台规范路径按文件系统大小写语义标准化并计算 SHA-256 身份。
2. 定义用户级信任文件 schema，只保存版本、身份摘要、可读路径和布尔决定。
3. 缺失记录返回 `None`；有效同路径记录返回布尔；不同工作区互不继承。
4. 文件损坏、重复身份、字段错误或读取异常按未信任处理并返回有界诊断。

**验证：** 运行 `python -m pytest tests/test_hook_trust.py -q -k 'identity or read or corrupt or isolated'`，期望路径身份和 fail-closed 读取通过。

## T12：实现信任锁与原子持久化

**文件：** `src/mewcode/hooks/trust.py`、`src/mewcode/locking.py`、`tests/test_hook_trust.py`、`tests/test_locking.py`
**依赖：** T11
**覆盖：** F9–F12、N2、N5、N11

**步骤：**

1. 使用专用 `FileLock` 串行化读改写，保留其他工作区的最新记录。
2. 写入同目录临时文件、刷新与 fsync、重新完整校验，再原子替换信任文件。
3. 持久化同意和拒绝；写入失败时保持旧文件并且本进程不启用项目共享外部动作。
4. 覆盖并发写、锁失败、外部修改、临时校验失败和路径变更。

**验证：** 运行 `python -m pytest tests/test_hook_trust.py tests/test_locking.py -q`，期望原子性、并发和失败关闭测试通过。

## T13：实现有界 shell I/O

**文件：** `src/mewcode/processes.py`、`tests/test_processes.py`
**依赖：** 无
**覆盖：** F25、F33–F34、F51、N7、N11

**步骤：**

1. 定义进程请求/结果模型，支持 shell 命令、JSON stdin、cwd、环境、超时和独立 stdout/stderr 上限。
2. 并发写 stdin、读取两路输出和等待退出，任何一路超限都停止整个进程。
3. 返回退出码、输出、耗时、超时/超限标记，不在底层拼接日志或工具结果。
4. 使用短命 Python 子进程覆盖 stdin 回显、两路输出、非零退出和超量输出。

**验证：** 运行 `python -m pytest tests/test_processes.py -q -k 'stdin or output or exit or limit'`，期望 I/O 与限制测试通过。

## T14：实现跨平台进程树终止与取消

**文件：** `src/mewcode/processes.py`、`tests/test_processes.py`
**依赖：** T13
**覆盖：** F34、F51、F52、N3、N7–N8、N11

**步骤：**

1. Windows 使用新进程组和 `taskkill /T /F`，POSIX 使用新会话及 TERM→KILL 升级。
2. 超时、输出超限、调用方取消和显式 runtime close 都复用同一幂等终止入口。
3. 关闭 stdin/stdout/stderr transport 并等待进程回收，不留下后台 zombie 或失管子进程。
4. 测试中将终止窗口缩短，验证超时和取消后子进程不再运行且 `CancelledError` 继续传播。

**验证：** 运行 `python -m pytest tests/test_processes.py -q -k 'timeout or cancel or tree or cleanup'`，期望平台适用的终止用例通过。

## T15：让 run_command 复用有界进程层

**文件：** `src/mewcode/tools/command_tool.py`、`tests/test_command_tool.py`
**依赖：** T13–T14
**覆盖：** F12、N4、N10–N11

**步骤：**

1. 保留命令非空、危险命令检查、默认 30 秒和最大 120 秒规则。
2. 用共享进程层替换重复创建、communicate 和终止实现。
3. 保持 `ToolResult` 的 exit code、stdout、stderr、cwd、timed_out、truncated 和用户可见文案兼容。
4. 证明 Hook 的 60/600 秒边界不会渗入工具参数规则。

**验证：** 运行 `python -m pytest tests/test_command_tool.py -q`，期望命令工具全部原有和新增回归测试通过。

## 事件信封、诊断与动作

## T16：补齐 message、tool、compact 和 error 事件工厂

**文件：** `src/mewcode/hooks/events.py`、`tests/test_hook_events.py`
**依赖：** T5
**覆盖：** F16–F24、N6、N9

**步骤：**

1. 实现 message before/after 的组件、Profile、run、iteration、计数、finish、状态和有界摘要字段。
2. 实现 tool before/after 的调用 ID、名称、原始参数、规范目标、结果状态和摘要字段。
3. 实现自动/手动 compact 与 system.error 工厂，使用稳定 kind 而非原始堆栈。
4. 为 success、failure、denied、cancelled 和无需压缩状态提供显式映射。

**验证：** 运行 `python -m pytest tests/test_hook_events.py -q -k 'message or tool or compact or error or status'`，期望事件字段和状态矩阵通过。

## T17：实现有界外部 JSON 信封

**文件：** `src/mewcode/hooks/events.py`、`tests/test_hook_events.py`
**依赖：** T16
**覆盖：** F21–F25、F38、N6–N7

**步骤：**

1. 递归限制字符串、数组、对象深度与项目数，再限制最终 UTF-8 JSON 为 1 MiB。
2. 保留条件使用的内部完整事件树，只对 command/HTTP 外发副本截断。
3. 顶层加入排序稳定的 `truncated_fields`，不得生成未标记的静默截断。
4. 验证信封不含 PromptPackage、完整历史、隐藏 Provider parts、API Key 或认证头。

**验证：** 运行 `python -m pytest tests/test_hook_events.py -q -k 'envelope or truncate or privacy or stable_json'`，期望预算、标记和敏感字段断言通过。

## T18：实现有界脱敏诊断写入

**文件：** `src/mewcode/hooks/diagnostics.py`、`tests/test_hook_runtime.py`
**依赖：** T2
**覆盖：** F53–F55、N3、N6–N7、N9

**步骤：**

1. 把动作结果编码为一行 JSON，包含时间、事件、规则位置、动作类型、后台状态、耗时、结果和有界摘要。
2. 对 URL 只保留 scheme/host/path，移除 userinfo、query 和 fragment；不接受 headers、事件信封或原始输出进入诊断。
3. 限制摘要和整行字节数，写入前替换控制字符。
4. 任意编码、目录、写入或 flush 错误都被吞掉并禁止触发 system.error。

**验证：** 运行 `python -m pytest tests/test_hook_runtime.py -q -k 'diagnostic and (bounded or redacted or failure)'`，期望日志脱敏和失效隔离通过。

## T19：实现诊断日志轮转

**文件：** `src/mewcode/hooks/diagnostics.py`、`tests/test_hook_runtime.py`
**依赖：** T18
**覆盖：** F53–F55、N7、N9、N11

**步骤：**

1. 默认延迟创建 `~/.mewcode/logs/hooks.jsonl`，空目录不创建文件。
2. 当前文件达到 1 MiB 时轮转 `.1` 至 `.3`，先从最旧文件开始替换。
3. 轮转与写入采用同步窄锁，失败时不删除当前可读日志且不影响 Agent。
4. 使用小容量测试配置验证轮转数量、顺序、每行合法 JSON 和失败降级。

**验证：** 运行 `python -m pytest tests/test_hook_runtime.py -q -k 'log_rotation or lazy_log or log_failure'`，期望轮转和惰性创建通过。

## T20：实现 command 动作执行

**文件：** `src/mewcode/hooks/actions.py`、`tests/test_hook_actions.py`
**依赖：** T13–T14、T17
**覆盖：** F12、F25、F33–F34、F38、F42、N3–N7、N11

**步骤：**

1. 以工作区为 cwd，使用事件信封 encoded bytes 作为 stdin，绝不进行工具参数模板替换。
2. 调用前再次执行危险命令检查，并从环境中移除所有 Profile API Key 变量。
3. 分别处理成功、非零退出、超时、输出超限、启动错误和取消；stderr 只进入有界内部摘要。
4. 普通错误返回 `FAILURE`，不抛给运行时调用方；调用方取消完成进程树清理后继续传播。

**验证：** 运行 `python -m pytest tests/test_hook_actions.py -q -k 'command'`，期望 cwd、stdin、安全检查、环境、失败和取消用例通过。

## T21：实现 HTTP 动作执行

**文件：** `src/mewcode/hooks/actions.py`、`tests/test_hook_actions.py`
**依赖：** T17
**覆盖：** F25、F37–F38、F42、F48、N3、N6–N7

**步骤：**

1. 使用注入的共享 `httpx.AsyncClient`，按动作方法、URL、静态 headers 和超时发送 JSON bytes。
2. 禁止自动重定向，逐块读取并限制响应为 64 KiB。
3. 2xx 视为可解析成功；非 2xx、网络错误、超时、重定向和超量响应返回区分明确的 `FAILURE`。
4. 诊断不得包含 Authorization/Cookie 值、query、userinfo 或响应正文。

**验证：** 运行 `python -m pytest tests/test_hook_actions.py -q -k 'http'`，期望 MockTransport 的成功、状态、错误、超时、限流与脱敏测试通过。

## T22：实现工具决策、prompt 与 agent 动作

**文件：** `src/mewcode/hooks/actions.py`、`tests/test_hook_actions.py`
**依赖：** T20–T21
**覆盖：** F35–F42、F45、N3–N7

**步骤：**

1. 仅在 `expects_decision` 时解析 command stdout 或 HTTP 2xx body；空响应继续，非空必须是严格 UTF-8 JSON 对象。
2. `allow` 只返回继续，`deny` 必须带 1–2048 字符 reason；未知字段、未知 decision、缺原因和无效 JSON 为失败放行。
3. prompt 返回待排队内容但不自行写入历史或 PromptPackage；agent 返回明确 `SKIPPED` 且不调用 Provider。
4. 非 `tool.before` 的普通 command/HTTP 输出只生成有界成功摘要，不解释为拒绝。

**验证：** 运行 `python -m pytest tests/test_hook_actions.py -q`，期望四动作、严格决策、失败放行和占位行为全部通过。

## HookRuntime 与 Provider

## T23：实现运行时匹配、信任过滤与 once

**文件：** `src/mewcode/hooks/runtime.py`、`tests/test_hook_runtime.py`、`tests/fakes.py`
**依赖：** T6、T9、T11–T12、T18、T22
**覆盖：** F8–F12、F26–F31、F46–F47、F50、F52–F55、N1–N5、N8–N9

**步骤：**

1. 从冻结 `by_event` 读取规则并按既定顺序求值，条件不匹配记录 `NOT_MATCHED`。
2. 未信任时只跳过项目共享 command/HTTP；用户、项目本地、prompt 和 agent 保持原语义。
3. 在动作尝试前、单异步调度锁内原子消费 `once`；失败、跳过或后台登记失败均不重试。
4. 信任写入失败时保持外部动作禁用，并产生一次清晰诊断。

**验证：** 运行 `python -m pytest tests/test_hook_runtime.py -q -k 'match or trust or once'`，期望顺序、来源过滤和并发首次消费通过。

## T24：实现同步顺序、提示队列和首次 deny 短路

**文件：** `src/mewcode/hooks/runtime.py`、`tests/test_hook_runtime.py`
**依赖：** T23
**覆盖：** F35–F36、F40–F45、F50、F52、N1、N3–N4、N8

**步骤：**

1. 同一事件的同步规则逐条 await，普通成功、allow、空决策和失败均继续后续规则。
2. prompt 按规则顺序进入队列；单条和每次消费总量超限时只让该动作失败。
3. 只有合法 `tool.before deny` 返回 `HookDispatchResult.decision` 并停止本次剩余规则。
4. 提供原子 `consume_prompt_context()`；取出即消费，Provider 后续失败也不恢复。

**验证：** 运行 `python -m pytest tests/test_hook_runtime.py -q -k 'sequence or prompt or deny or failure_continues'`，期望顺序、短路和单次消费通过。

## T25：实现后台任务登记、完成与有界关闭

**文件：** `src/mewcode/hooks/runtime.py`、`src/mewcode/hooks/actions.py`、`tests/test_hook_runtime.py`
**依赖：** T24
**覆盖：** F48–F52、N1、N3、N7–N8、N11

**步骤：**

1. command/HTTP background 规则按声明顺序创建任务并立即返回，最多跟踪 32 个。
2. 完成回调记录 success/failure/cancelled 并可靠从任务表移除；回调异常不得传播。
3. close 后拒绝新后台任务，先等待可配置关闭窗口，再取消 HTTP 并终止 command 进程树。
4. 验证同步事件不等待后台完成、任务上限不泄漏 coroutine、关闭后任务表为空。

**验证：** 运行 `python -m pytest tests/test_hook_runtime.py -q -k 'background or close or task_limit'`，期望登记、非阻塞、完成和强制清理通过。

## T26：实现运行作用域、system.error 与空目录快速路径

**文件：** `src/mewcode/hooks/runtime.py`、`tests/test_hook_runtime.py`
**依赖：** T25
**覆盖：** F19、F36、F52–F55、N3、N8–N10、N13

**步骤：**

1. 用 ContextVar 管理 turn、run、mode、component 和 iteration，并提供嵌套 `bind_scope()`。
2. `system_error()` 生成脱敏稳定 kind，不接受 Hook 自身异常再次进入分派。
3. 所有入口吞掉普通 Hook 异常，调用方取消只在清理后传播；关闭时丢弃未消费 prompt。
4. 空目录的 dispatch/consume/close 为常数时间，不创建日志、HTTP client、任务或终端诊断。

**验证：** 运行 `python -m pytest tests/test_hook_runtime.py -q`，期望作用域隔离、非递归错误、提示丢弃和空配置回归通过。

## T27：实现 Provider 前置事件与 Hook Context 注入

**文件：** `src/mewcode/hooks/provider.py`、`tests/test_hook_provider.py`
**依赖：** T16–T17、T26
**覆盖：** F16、F21、F23、F35–F36、N6、N9–N10、N13

**步骤：**

1. 每次 `stream_reply()` 创建稳定 message ID，并在调用内部 Provider 前 dispatch `message.before`。
2. 随后原子消费 prompt 队列，作为单一 `## Hook Context` 追加到 `dynamic_system`，不修改 stable_system、历史或原请求对象。
3. 没有 prompt 时把原始请求对象原样交给内部 Provider，保持空配置快速路径。
4. 验证一次 Provider 调用只消费一次提示且 `message.before` 产生的提示进入当前请求。

**验证：** 运行 `python -m pytest tests/test_hook_provider.py -q -k 'before or prompt or request_copy or empty'`，期望前置顺序和动态注入通过。

## T28：实现 Provider 后置事件、委托与错误边界

**文件：** `src/mewcode/hooks/provider.py`、`tests/test_hook_provider.py`
**依赖：** T27
**覆盖：** F16、F19–F20、F23、F52、F55、N3、N6、N10

**步骤：**

1. 原样流式转发 ProviderEvent，只在本地累计有界文本摘要、finish reason、usage presence 和工具数。
2. 正常、ProviderError、意外异常和取消分别触发恰好一次 `message.after` 并携带正确状态。
3. Provider 普通错误额外上报一次 system.error 后按原异常类型继续抛出；Hook 错误不触发该路径。
4. `assistant_messages()` 和 `tool_result_messages()` 无条件委托内部 Provider，保持 group_id 和历史配对。

**验证：** 运行 `python -m pytest tests/test_hook_provider.py -q`，期望流式、后置、异常、取消、委托和隐私测试通过。

## 权限与工具生命周期

## T29：拆分权限硬预检与常规策略

**文件：** `src/mewcode/permissions/models.py`、`controller.py`、`__init__.py`、`tests/test_permission_controller.py`、`tests/test_permission_integration.py`
**依赖：** T4
**覆盖：** F12、F43、N4、N10、N13

**步骤：**

1. 增加不可变 `PermissionPreflight(call, target)`。
2. `preflight()` 只执行权限声明校验、危险命令检查、路径/路径 glob 规范化与工作区边界。
3. `evaluate_preflight()` 只执行 YAML 规则、会话规则和 permission mode 判断。
4. 保留 `evaluate()` 兼容包装，并证明所有旧调用得到与拆分前相同结果。

**验证：** 运行 `python -m pytest tests/test_permission_controller.py tests/test_permission_integration.py -q`，期望两阶段顺序和权限回归通过。

## T30：在 ToolScheduler 接入 tool.before 安全顺序

**文件：** `src/mewcode/agent/scheduler.py`、`tests/test_tool_scheduler.py`
**依赖：** T26、T29
**覆盖：** F17、F22、F40–F45、N1、N4、N8、N10

**步骤：**

1. 给 Scheduler/Schedule 注入 HookRuntime，并为每个已验证调用先执行 `preflight()`。
2. 硬预检通过后构造包含原始参数和规范目标的 `tool.before`；硬拒绝不得 dispatch before。
3. Hook 继续后才执行 `evaluate_preflight()` 和现有人工确认；Hook allow 不改变任何权限结果。
4. 前置 Hook 与权限挑战按原请求索引顺序准备，保持副作用工具串行边界。

**验证：** 运行 `python -m pytest tests/test_tool_scheduler.py -q -k 'preflight or hook_before or safety_order or permission'`，期望硬门禁→Hook→权限顺序精确通过。

## T31：实现 Hook 拒绝工具结果和首次短路

**文件：** `src/mewcode/agent/scheduler.py`、`tests/test_tool_scheduler.py`
**依赖：** T30
**覆盖：** F40–F45、F52、N3–N4

**步骤：**

1. 将合法 Hook deny 转成失败 `ToolResult`，metadata 标明 `hook_denied`、规则来源和有界原因。
2. 不创建权限挑战、不执行工具、不伪造 `AgentPermissionDecision`。
3. invalid decision、动作超时和动作异常继续进入权限系统；只有 runtime 返回合法 deny 才拒绝。
4. 多条 before 规则由 runtime 首次 deny 短路，Scheduler 只消费一个最终原因。

**验证：** 运行 `python -m pytest tests/test_tool_scheduler.py -q -k 'hook_denied or invalid_decision or deny_short_circuit'`，期望拒绝和失败放行边界通过。

## T32：统一所有工具结果的 tool.after

**文件：** `src/mewcode/agent/scheduler.py`、`tests/test_tool_scheduler.py`
**依赖：** T31
**覆盖：** F17、F20、F22、F50、F52、N3、N8–N10

**步骤：**

1. 增加单一 `_finalize_execution()`，在产出 `AgentToolResult` 前同步 dispatch `tool.after`。
2. 覆盖成功、工具失败、未知工具、参数错误、硬拒绝、Hook 拒绝、权限拒绝和取消。
3. 状态映射为 success/failure/denied/cancelled，错误和结果只进入有界摘要。
4. after Hook 的普通失败不改变原 `ToolResult` 或完成状态。

**验证：** 运行 `python -m pytest tests/test_tool_scheduler.py -q -k 'hook_after or unknown or validation or denied or cancelled'`，期望每个调用恰好一个后置事件。

## T33：保持工具并发、控制操作与取消兼容

**文件：** `src/mewcode/agent/scheduler.py`、`tests/test_tool_scheduler.py`、`tests/test_skill_execution.py`
**依赖：** T32
**覆盖：** F17、F47、F50–F52、N8、N10

**步骤：**

1. 只读调用在 before/权限准备后继续按最大并发执行，最终 executions 仍按原索引排序。
2. `AgentControlTool` 保留现有权限豁免，但经过参数校验、硬预检、tool.before 和 tool.after。
3. 取消 read batch、serial tool、权限 challenge 和 control operation 时完成恰好一次 cancelled after。
4. 并发 after 通过 runtime 锁保持 `once` 与规则顺序确定，不串用事件参数。

**验证：** 运行 `python -m pytest tests/test_tool_scheduler.py tests/test_skill_execution.py -q -k 'concurrent or control or cancel or once'`，期望并发和控制工具回归通过。

## Agent、压缩、轮次与会话

## T34：在 AgentRun 绑定 run/iteration 作用域

**文件：** `src/mewcode/agent/runner.py`、`tests/test_agent_runner.py`
**依赖：** T26、T33
**覆盖：** F15–F17、F19、F21、N1、N8、N10

**步骤：**

1. AgentRun 整体绑定 run ID 和 mode，每次迭代叠加 iteration，所有 Provider 与工具子任务继承作用域。
2. 正常完成、受控停止和取消正确退出 ContextVar token，不污染下一次运行或独立 Skill。
3. 意外 Agent/持久化错误通过 runtime.system_error 上报一次；HookedProvider 已上报的 Provider 错误不得在 Agent 层重复上报，预期输出上限、迭代上限和取消不当作 system.error。
4. 不改变现有 AgentEvent、StopReason、历史提交或 Token 用量。

**验证：** 运行 `python -m pytest tests/test_agent_runner.py -q -k 'scope or system_error or cancel or regression'`，期望作用域和原 Agent 行为通过。

## T35：接入手动与自动压缩 Hook

**文件：** `src/mewcode/context/manager.py`、`tests/test_context_manager.py`、`tests/test_context_integration.py`
**依赖：** T26、T28
**覆盖：** F18–F20、F35、N3、N9–N10

**步骤：**

1. 手动 compact 在真正调用 HistoryCompactor 前触发 before，并对 changed/no-op/failure/cancelled 触发一次 after。
2. 自动 prepare 只在估算超过边界且熔断未开启、真正开始压缩时触发；普通安全请求与 circuit-open 不触发。
3. 压缩 Provider 调用继续经 HookedProvider，因此 compact.before prompt 可进入本次摘要请求。
4. Hook 错误不改变 ContextPreparation、breaker、usage 或已有 ContextStatus。

**验证：** 运行 `python -m pytest tests/test_context_manager.py tests/test_context_integration.py -q -k 'hook or compact or no_compaction or circuit'`，期望压缩矩阵和现有回归通过。

## T36：为普通用户 Agent 运行建立 turn 生命周期

**文件：** `src/mewcode/conversation.py`、`tests/test_conversation.py`
**依赖：** T34–T35
**覆盖：** F15、F20–F21、F35–F36、N1、N3、N8–N10

**步骤：**

1. 对被接受的非空普通任务生成 turn ID，在 Agent 启动前 dispatch turn.start 并绑定 turn/mode 作用域。
2. 根据 AgentRunOutcome 或异常映射 success/failure/cancelled，恰好 dispatch 一次 turn.end。
3. turn.end 完成后再退出作用域和安排 MemoryTurn，使其 prompt 按“下一次 Provider 请求”语义可被记忆更新消费。
4. preflight maintenance 和输入校验失败在 turn 开始前发生，不生成半个 turn。

**验证：** 运行 `python -m pytest tests/test_conversation.py -q -k 'turn_hook or send or cancel or memory_order'`，期望普通轮次成对和顺序通过。

## T37：覆盖 Plan、Execute 与 Skill 的 turn 边界

**文件：** `src/mewcode/conversation.py`、`tests/test_conversation.py`、`tests/test_skill_integration.py`
**依赖：** T36
**覆盖：** F15、F20、N10

**步骤：**

1. 持续 PLAN 模式下的普通消息、旧式 `plan(task)` 和 `execute_plan()` 各形成真实模型轮次。
2. 共享 Skill 斜杠调用把后续主 Agent Run 作为一个 turn；独立 Skill 的模型运行也形成一个 turn。
3. 只在本地完成的 `/help`、`/permission`、`/clear`、`/reset` 和模式切换不触发 turn。
4. Skill 内部嵌套 Provider 消息继承当前 turn，但不额外创建用户 turn。

**验证：** 运行 `python -m pytest tests/test_conversation.py tests/test_skill_integration.py -q -k 'turn or plan or execute or isolated or local_command'`，期望各入口的轮次计数准确。

## T38：实现 session.start/end 与关闭顺序

**文件：** `src/mewcode/conversation.py`、`tests/test_conversation.py`
**依赖：** T25、T37
**覆盖：** F14、F20、F36、F51、N3、N8–N10

**步骤：**

1. 增加幂等 `start()`，在会话资源已恢复后 dispatch session.start 并标明 new/resumed。
2. close 先取消活动运行、等待记忆请求，再 dispatch 一次 session.end，然后关闭会话/Skill/Context 和 HookRuntime。
3. 确保 session.end 之后没有记忆 Provider 请求；runtime close 丢弃未消费 prompt 并清理后台任务。
4. 重复 close、start 失败、Hook close 失败和无 Hook 目录都不破坏现有资源清理。

**验证：** 运行 `python -m pytest tests/test_conversation.py -q -k 'session_hook or close_order or repeated_close or prompt_discard'`，期望会话事件和关闭顺序通过。

## 终端、REPL 与 CLI 装配

## T39：增加工作区 Hook 信任终端协议

**文件：** `src/mewcode/terminal.py`、`tests/test_terminal.py`
**依赖：** T12
**覆盖：** F9–F11、N5、N9

**步骤：**

1. 在 `TerminalSession` 增加独立 `prompt_hook_trust(workspace, source)`，不复用工具 permission 的四选项语义。
2. PromptToolkit 与 legacy terminal 只接受明确 yes/no；EOF 和无效输入最终安全拒绝。
3. 提示显示规范工作区和项目共享 hooks 来源，但不显示命令、URL、headers 或规则内容。
4. 保持普通 prompt、permission prompt、补全和 toolbar 行为不变。

**验证：** 运行 `python -m pytest tests/test_terminal.py -q -k 'hook_trust or permission or prompt'`，期望信任交互与现有终端回归通过。

## T40：在 REPL 解决信任并启动会话

**文件：** `src/mewcode/repl.py`、`tests/test_repl.py`
**依赖：** T38–T39
**覆盖：** F9–F11、F14、F19、F52–F55、N3、N5、N9–N10

**步骤：**

1. 输出启动信息后、接受普通输入前检查 runtime.trust_required；没有记录时只询问一次并持久化决定。
2. 信任决定解决后调用 `conversation.start()`，确保 session.start 的项目共享外部动作不会先于用户决定。
3. 拒绝或写入失败只显示一次简洁警告并继续会话；空目录不显示任何 Hook 文案。
4. 事件消费边界的非 Hook 意外错误上报 system.error，Hook 失败不递归且不改变现有用户错误文案。

**验证：** 运行 `python -m pytest tests/test_repl.py -q -k 'hook_trust or session_start or system_error or no_hooks'`，期望启动顺序、失败继续和终端降噪通过。

## T41：完成 REPL 的 session.end 与后台关闭体验

**文件：** `src/mewcode/repl.py`、`tests/test_repl.py`
**依赖：** T40
**覆盖：** F14、F20、F51–F55、N3、N8–N10

**步骤：**

1. EOF、`/exit`、正常循环结束和 KeyboardInterrupt 收尾都只调用一次 Conversation.close。
2. 输出 Hook close 的关键 warning，但普通成功、条件不匹配和后台成功不进入终端正文。
3. conversation shutdown 自身失败仍保留原警告并尝试关闭 HookRuntime，不让后台进程失管。
4. 保持退出码 0/130、Ctrl+C 只取消当前轮次和 REPL 可继续使用的行为。

**验证：** 运行 `python -m pytest tests/test_repl.py -q -k 'shutdown or exit or eof or keyboard or background'`，期望 session.end、清理和退出码通过。

## T42：在 CLI 加载 Hook 配置、信任与运行时

**文件：** `src/mewcode/cli.py`、`tests/test_cli.py`、`tests/test_hook_config.py`
**依赖：** T9–T12、T19、T22、T26
**覆盖：** F3–F12、F32、F53–F55、N2–N7、N10

**步骤：**

1. 在任何交互和动作前加载三层 HookCatalog；`HookConfigError` 显示路径、规则与字段并返回 1。
2. 读取 WorkspaceTrustStore；非空目录构造惰性诊断 sink、共享 HTTP client/action executor 和 HookRuntime，空目录使用不创建日志、client 或任务的空运行时。
3. 传入工作区、会话 ID、resumed、Profile API Key 环境变量名集合和已知敏感值脱敏器。
4. 配置失败路径不得创建日志、HTTP client、进程或信任变更。

**验证：** 运行 `python -m pytest tests/test_cli.py tests/test_hook_config.py -q -k 'hook_config or hook_runtime or startup_error or no_side_effect'`，期望启动原子性和无副作用通过。

## T43：让全部 Profile Provider 经过单层 Hook 装饰

**文件：** `src/mewcode/cli.py`、`tests/test_cli.py`、`tests/test_hook_provider.py`
**依赖：** T28、T42
**覆盖：** F16、F18–F19、F35–F36、N1、N6、N10、N13

**步骤：**

1. 增加按 Profile 名缓存的 helper，在现有 UsageTrackingProvider 外只包一层 HookedProvider。
2. 主 Agent、独立 Skill、ContextManager 和 MemoryUpdater 均从 helper 获得相同 Profile 的装饰实例。
3. 同一 Provider 不重复装饰，不绕过 ProfileCatalog 的 usage ledger 或凭据校验。
4. 覆盖主回复、独立 Skill、历史压缩和记忆更新各自触发 message 前后事件。

**验证：** 运行 `python -m pytest tests/test_cli.py tests/test_hook_provider.py tests/test_skill_execution.py -q -k 'profile or wrapped or isolated or memory or compaction'`，期望所有真实模型入口只触发一对消息事件。

## T44：完成 Hook 依赖注入和 CLI 关闭兜底

**文件：** `src/mewcode/cli.py`、`tests/test_cli.py`
**依赖：** T33–T43
**覆盖：** F14–F20、F43、F51–F55、N2–N5、N8–N10

**步骤：**

1. 将同一 HookRuntime 注入 ToolScheduler、AgentRunner、ContextManager、Conversation 和 Repl。
2. 确保 session 已打开后才绑定 session 信息，信任解决后才执行 session.start。
3. CLI 在 Repl 构造前异常、Repl 正常关闭和 finally 重入时都幂等关闭运行时、HTTP client 和日志。
4. 增加 HookConfigError/Trust 错误处理且不泄露 URL query、headers、API Key 或原始 YAML secrets。

**验证：** 运行 `python -m pytest tests/test_cli.py -q`，期望完整装配、错误顺序、关闭幂等和原 CLI 回归通过。

## 集成验收、示例与文档

## T45：覆盖配置、信任和条件验收

**文件：** `tests/test_hook_integration.py`、`tests/test_hook_config.py`、`tests/test_hook_trust.py`、`tests/test_hook_conditions.py`
**依赖：** T44
**覆盖：** AC1–AC3、AC8–AC10、AC26

**步骤：**

1. 从三层真实临时 YAML 启动，验证追加顺序、原子错误和无动作加载。
2. 完成信任/拒绝/写失败/另一工作区矩阵，确认只有项目共享 command/HTTP 被门禁。
3. 用工具嵌套参数覆盖 exact/glob/regex/negate、all/any、缺失字段与非法组合。
4. 加入规则数、条件数、字段长度和 regex 超时边界。

**验证：** 运行 `python -m pytest tests/test_hook_config.py tests/test_hook_trust.py tests/test_hook_conditions.py tests/test_hook_integration.py -q -k 'config or trust or condition or resource'`，期望 AC1–AC3、AC8–AC10、AC26 场景通过。

## T46：覆盖动作、决策和运行时验收

**文件：** `tests/test_hook_actions.py`、`tests/test_hook_runtime.py`、`tests/test_processes.py`
**依赖：** T44
**覆盖：** AC11–AC16、AC20–AC24

**步骤：**

1. 覆盖 command 成功、退出、超时、输出上限、stdin/cwd、危险命令和 API Key 环境移除。
2. 覆盖 HTTP 成功、状态、网络、超时、重定向、体积和凭据脱敏。
3. 覆盖空/allow/deny/非法协议、prompt 单次注入和 agent 占位。
4. 并发验证 `once`、同步顺序、后台非阻塞、任务上限、关闭取消和日志轮转。

**验证：** 运行 `python -m pytest tests/test_processes.py tests/test_hook_actions.py tests/test_hook_runtime.py -q`，期望 AC11–AC16、AC20–AC24 全部通过。

## T47：覆盖 Provider、工具安全和生命周期验收

**文件：** `tests/test_hook_provider.py`、`tests/test_hook_integration.py`、`tests/test_tool_scheduler.py`、`tests/test_context_integration.py`、`tests/test_conversation.py`
**依赖：** T45–T46
**覆盖：** AC4–AC7、AC12、AC17–AC19、AC25、AC27

**步骤：**

1. 跑通含两次模型交互和一次工具调用的完整成功轮次，核对 11 项事件中适用事件的顺序与次数。
2. 分别制造 Provider/工具/压缩失败、权限拒绝、Hook 拒绝和取消，核对 after/end 状态恰好一次。
3. 证明硬门禁拒绝参数不会进入外部 Hook，allow 不能越过权限，deny 作为工具结果反馈模型。
4. 覆盖提示被主回复、压缩、记忆或独立 Skill 的下一次真实 Provider 请求消费，以及无 Hook 全链路兼容。

**验证：** 运行 `python -m pytest tests/test_hook_provider.py tests/test_hook_integration.py tests/test_tool_scheduler.py tests/test_context_integration.py tests/test_conversation.py -q`，期望 AC4–AC7、AC12、AC17–AC19、AC25、AC27 通过。

## T48：增加作者示例和 Git 忽略边界

**文件：** `examples/hooks.yaml`、`.gitignore`、`tests/test_hook_config.py`
**依赖：** T9
**覆盖：** F1、F3、F26–F39、F46–F49、N5–N6

**步骤：**

1. 示例覆盖无条件 prompt、all/any 条件、exact/glob/regex/negate、command、HTTP、agent 占位、once、background 和 timeout。
2. 示例明确 `tool.before` 决策程序从 stdin/HTTP body 读取事件信封，不插值工具参数。
3. `.gitignore` 允许提交 `/.mewcode/hooks.yaml`，继续忽略 `hooks.local.yaml`、信任文件、日志和其他本地数据。
4. 用正式加载器解析示例，确保文档不存在实现不接受的字段。

**验证：** 运行 `python -m pytest tests/test_hook_config.py -q -k example`，再运行 `git check-ignore -v .mewcode/hooks.local.yaml`，期望示例有效且本地配置仍被忽略。

## T49：更新 README 使用与安全文档

**文件：** `README.md`
**依赖：** T47–T48
**覆盖：** F1–F55、N4–N11

**步骤：**

1. 说明三层路径、追加顺序、严格 YAML、11 个事件和统一事件信封。
2. 说明结构化条件、四类动作、command/HTTP 决策、once/background/timeout 和首期 agent 占位。
3. 说明项目共享信任、硬门禁→Hook→权限顺序、失败放行、凭据保护、诊断日志及资源限制。
4. 明确不做持久 once、priority、热更新、真实子 Agent、重试、操作系统沙箱和跨平台命令语法转换。

**验证：** 运行 `rg -n "hooks\.yaml|tool\.before|message\.before|workspace trust|once|background|Hook Context|hooks\.jsonl|agent.*placeholder" README.md`，期望所有主题均有命中；再人工对照 `examples/hooks.yaml` 确认字段一致。

## T50：执行完整质量与回归验收

**文件：** 全部本阶段文件与现有测试
**依赖：** T49
**覆盖：** AC1–AC28、N1–N13

**步骤：**

1. 运行 Hook、权限、工具、Agent、Context、Conversation、Skill、MCP、记忆、会话和 REPL 专项测试。
2. 运行全量 pytest，确认完全无 Hook 配置时所有既有行为保持兼容。
3. 运行编译、构建、README 示例解析、`git diff --check` 和敏感数据扫描。
4. 在 Windows 执行进程树专项；CI 的 Linux/macOS 执行同组跨平台测试，记录平台差异而不放宽断言。
5. 对照后续 `checklist.md` 逐项保存命令输出和观察证据，不用“测试通过”替代行为验收。

**验证：** 运行 `python -m pytest -q`、`python -m compileall -q src tests`、`python -m build`、`git diff --check`，期望全部退出码为 0；随后按 `checklist.md` 完成 AC1–AC28 的逐项验收。

## 执行顺序

```text
T1 ─┐
T2 ─┼─> T5 ─> T6 ─> T8 ─> T9 ─> T10
T3 ─┼─> T4 ────────────────────────┐
    └──────────────────────────────┤
T11 ─> T12 ────────────────────────┤
T13 ─> T14 ─> T15 ────────────────┤
T5 ─> T16 ─> T17 ─────────────────┤
T2 ─> T18 ─> T19 ─────────────────┤
T14 + T17 ─> T20 ─┐                │
T17 ─────────> T21 ├─> T22 ───────┤
T6 + T9 + T12 + T19 + T22 ─> T23 ─> T24 ─> T25 ─> T26
T16 + T17 + T26 ─> T27 ─> T28
T4 ─> T29
T26 + T29 ─> T30 ─> T31 ─> T32 ─> T33
T26 + T33 ─> T34
T26 + T28 ─> T35
T34 + T35 ─> T36 ─> T37
T25 + T37 ─> T38
T12 ─> T39
T38 + T39 ─> T40 ─> T41
T9 + T12 + T19 + T22 + T26 ─> T42
T28 + T42 ─> T43
T33…T43 ─> T44
T44 ─> T45、T46（可并行）
T45 + T46 ─> T47
T9 ─> T48
T47 + T48 ─> T49 ─> T50
```
