# 子 Agent Worktree 隔离 Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 新建 | `src/mewcode/worktrees/__init__.py` | Worktree 稳定公共导出，不产生导入时副作用 |
| 新建 | `src/mewcode/worktrees/models.py` | 配置、仓库身份、记录、状态、租约、保护与清理模型 |
| 新建 | `src/mewcode/worktrees/config.py` | `.mewcode/worktrees.yaml` 严格解析和安全默认规则 |
| 新建 | `src/mewcode/worktrees/paths.py` | 逻辑名称、布局、平台别名及重解析点验证 |
| 新建 | `src/mewcode/worktrees/records.py` | 双份记录、原子写入和纯文件系统身份恢复 |
| 新建 | `src/mewcode/worktrees/git.py` | 结构化 Git 执行、创建、保护检查及条件删除 |
| 新建 | `src/mewcode/worktrees/links.py` | Unix 符号链接与 Windows 目录链接适配 |
| 新建 | `src/mewcode/worktrees/initializer.py` | 复制、链接、Git Hook 环境、诊断及拥有资源回滚 |
| 新建 | `src/mewcode/worktrees/lifecycle.py` | 创建、恢复、进入、退出、列表、删除和并发编排 |
| 新建 | `src/mewcode/worktrees/janitor.py` | 启动扫描、周期扫描、候选限额和三层过滤 |
| 新建 | `src/mewcode/tools/binding.py` | 工作区相关工具重建注册表 |
| 新建 | `src/mewcode/continuity/memory_prompt.py` | 无写入副作用的分作用域记忆 Prompt 加载 |
| 新建 | `src/mewcode/subagents/workspace_runtime.py` | Worktree 任务运行时 bundle 装配与关闭 |
| 新建 | `src/mewcode/subagents/worktree_driver.py` | 子 Agent 运行与 Worktree 生命周期包装 |
| 新建 | `examples/worktrees.yaml`、`examples/agents/worktree-coder.md` | 初始化配置和隔离角色示例 |
| 新建 | `tests/worktrees/helpers.py`、`test_config.py`、`test_paths.py`、`test_records.py`、`test_git.py`、`test_links.py`、`test_initializer.py`、`test_lifecycle.py`、`test_janitor.py`、`test_integration.py` | 临时仓库、本地远端、核心单元、竞态和端到端测试 |
| 新建 | `tests/test_subagent_worktree.py` | Worktree 子 Agent 运行时集成测试 |
| 修改 | `.gitignore`、`README.md` | 忽略托管目录并记录用户配置、命令、保护和非沙箱边界 |
| 修改 | `src/mewcode/processes.py` | 安全合并任务环境且不修改 `os.environ` |
| 修改 | `src/mewcode/tools/__init__.py`、`builtin.py`、`command_tool.py`、`file_tools.py`、`search_tools.py` | 显式工作区绑定、命令 cwd/environment 和绝对路径观察 |
| 修改 | `src/mewcode/continuity/__init__.py`、`instructions.py`、`memory_models.py`、`memory_store.py`、`memory_manager.py` | 指令与记忆分作用域快照、绝对路径缓存和只读加载 |
| 修改 | `src/mewcode/hooks/actions.py`、`config.py`、`models.py`、`runtime.py` | 任务 cwd/environment、共享 once/预算和任务私有状态 |
| 修改 | `src/mewcode/mcp/config.py`、`runtime.py`、`transport.py`、`stdio.py` | 用户/项目配置分层、任务 stdio cwd/environment 和有界关闭 |
| 修改 | `src/mewcode/skills/process_tool.py`、`runtime.py` | Skill 进程工具按工作区上下文重建 |
| 修改 | `src/mewcode/permissions/targets.py` | 冻结权限规则在 Worktree 根重新绑定目标解析 |
| 修改 | `src/mewcode/prompting/builder.py`、`environment.py`、`src/mewcode/context/archive.py`、`manager.py` | 每任务 Prompt/Context 对象与 Worktree 归档路径 |
| 修改 | `src/mewcode/subagents/__init__.py`、`models.py`、`parser.py`、`catalog.py`、`coordinator.py`、`policy.py`、`permissions.py`、`runtime.py`、`scoped_tools.py`、`tasks.py`、`notifications.py`、`control.py` | 隔离声明、冻结能力、驱动选择、权限重绑、绝对路径缓存和状态摘要 |
| 修改 | `src/mewcode/commands/contracts.py`、`builtin.py`、`src/mewcode/conversation.py`、`repl.py` | Worktree 本地命令、状态格式化和 Janitor 生命周期代理 |
| 修改 | `src/mewcode/cli.py` | 唯一组合根、惰性仓库能力和 Provider 分层 |
| 修改 | `tests/test_processes.py`、`test_workspace.py`、`test_command_tool.py`、`test_file_tools.py`、`test_search_tools.py`、`test_instruction_loader.py`、`test_memory_store.py`、`test_memory_manager.py`、`test_hook_actions.py`、`test_hook_config.py`、`test_hook_runtime.py`、`test_mcp_config.py`、`test_mcp_runtime.py`、`test_mcp_transports.py`、`test_skill_process_tool.py`、`test_skill_runtime.py`、`test_permission_targets.py`、`test_prompt_builder.py`、`test_context_archive.py` | 工作区相关既有模块回归和隔离行为测试 |
| 修改 | `tests/test_subagent_parser.py`、`test_subagent_catalog.py`、`test_subagent_coordinator.py`、`test_subagent_permissions.py`、`test_subagent_runtime.py`、`test_subagent_scoped_tools.py`、`test_subagent_tasks.py`、`test_subagent_notifications.py`、`test_subagent_control.py` | 子 Agent 声明、运行时、权限、缓存和结果兼容测试 |
| 修改 | `tests/test_builtin_commands.py`、`test_conversation.py`、`test_cli.py` | 本地命令、启停顺序和组合根测试 |

## T1: 增加角色隔离枚举与严格解析

**文件：** `src/mewcode/subagents/models.py`、`src/mewcode/subagents/parser.py`、`tests/test_subagent_parser.py`

**依赖：** 无

**步骤：**
1. 定义 `AgentIsolation`，为 `AgentDefinition` 增加默认 `shared` 的不可变字段。
2. 让 frontmatter 仅额外接受 `isolation`，严格接受 `shared`/`worktree` 并拒绝未知值，补充新旧角色解析测试。

**验证：** 运行 `python -m pytest tests/test_subagent_parser.py -q`，期望未声明、`shared`、`worktree` 均正确解析，未知值及未知字段失败。

## T2: 建立 Worktree 核心不可变模型

**文件：** `src/mewcode/worktrees/models.py`、`tests/worktrees/test_config.py`

**依赖：** 无

**步骤：**
1. 按 Plan 定义规则、配置快照、仓库身份、布局、记录、标记、环境、租约、保护、退出、删除、状态、清理以及 `WorkspaceExecutionContext` 模型。
2. 在模型边界校验绝对路径、完整分支引用、OID、UTC 时间、状态组合和有界诊断。

**验证：** 运行 `python -m pytest tests/worktrees/test_config.py -k models -q`，期望合法模型可构造，非法路径、OID、引用和状态组合被拒绝。

## T3: 定义初始化配置安全默认值

**文件：** `src/mewcode/worktrees/config.py`、`tests/worktrees/test_config.py`

**依赖：** T2

**步骤：**
1. 实现 `WorktreeConfigLoader` 的缺省路径和版本 1 安全默认规则：可选复制 `.mewcode/config.yaml`、`.mewcode/permissions.local.yaml`、`.mewcode/hooks.local.yaml`、`.mewcode/instructions.md` 和 `.mewcode/memory/`。
2. 固定规则数、文件数、单文件大小、复制总量、扫描候选数、24 小时期限和一小时间隔的默认上限。

**验证：** 运行 `python -m pytest tests/worktrees/test_config.py -k defaults -q`，期望缺少项目配置时返回冻结的安全默认快照且不创建文件。

## T4: 实现初始化配置严格解析

**文件：** `src/mewcode/worktrees/config.py`、`tests/worktrees/test_config.py`

**依赖：** T3

**步骤：**
1. 严格解析 `version`、`copy`、`link`、`git_hooks` 和 `required`，拒绝重复键、未知字段、错误类型及超限规则。
2. 验证仓库相对源/目标路径并按类型与路径合并默认规则和项目覆盖，将失败冻结在快照中。

**验证：** 运行 `python -m pytest tests/worktrees/test_config.py -k 'strict or limits or merge' -q`，期望合法配置确定合并，畸形和超限配置产生安全失败快照。

## T5: 实现逻辑名称校验与任务名称派生

**文件：** `src/mewcode/worktrees/paths.py`、`tests/worktrees/test_paths.py`

**依赖：** T2

**步骤：**
1. 实现 `WorktreePathPolicy.parse_name()` 的字符集、总长、段长、起始字符、`.`/`..`、空段、反斜杠、盘符、UNC、控制字符和 Windows 设备名校验。
2. 实现 `WorktreeNameFactory.for_task()`，把任务 ID 稳定派生为 `task/<32 hex>`，不把外部 ID 直接用作路径。

**验证：** 运行 `python -m pytest tests/worktrees/test_paths.py -k 'name or task' -q`，期望所有合法边界被接受、遍历及平台别名输入在副作用前被拒绝。

## T6: 实现托管布局和祖先安全检查

**文件：** `src/mewcode/worktrees/paths.py`、`tests/worktrees/test_paths.py`

**依赖：** T5

**步骤：**
1. 生成托管根、Worktree 根、`refs/heads/mewcode/worktree/...`、控制记录、就绪标记和锁文件的唯一绝对布局。
2. 实现大小写规范化碰撞、符号链接、目录联接、重解析点、区域逃逸及删除前最终目标复验。

**验证：** 运行 `python -m pytest tests/worktrees/test_paths.py -k 'layout or ancestor or collision or delete_target' -q`，期望所有派生路径位于预期边界且链接/别名攻击失败。

## T7: 实现管理记录严格编解码与原子更新

**文件：** `src/mewcode/worktrees/records.py`、`tests/worktrees/test_records.py`

**依赖：** T2、T6

**步骤：**
1. 实现控制记录与 `.mewcode/worktree.json` 就绪标记的严格 JSON 编解码、重复/未知字段拒绝和原子替换。
2. 实现按 `management_id` 条件更新、删除和状态持久化，不把敏感环境或原始 Git 输出写入记录。

**验证：** 运行 `python -m pytest tests/worktrees/test_records.py -k 'codec or atomic or metadata' -q`，期望往返稳定、损坏数据被拒绝、错误管理 ID 不能覆盖或删除记录。

## T8: 实现零 Git 的文件系统身份恢复

**文件：** `src/mewcode/worktrees/records.py`、`tests/worktrees/test_records.py`

**依赖：** T7

**步骤：**
1. 只读解析 Worktree `.git` 指针、对应管理目录的 `commondir` 与 `HEAD`，交叉验证仓库、名称、路径、分支、基线、任务 ID 和 Hook 相对路径。
2. 仅接受完整 `ready` 状态，拒绝符号链接、损坏/不一致记录和非就绪状态；整个路径不启动进程、不写文件、不扫描工作树。

**验证：** 运行 `python -m pytest tests/worktrees/test_records.py -k 'filesystem_identity or recovery' -q`，期望有效记录恢复成功，各单点伪造均被拒绝且写入/Git 替身调用数为零。

## T9: 增加安全任务环境合并

**文件：** `src/mewcode/processes.py`、`tests/test_processes.py`

**依赖：** 无

**步骤：**
1. 增加不修改 `os.environ` 的环境过滤和覆盖合并辅助函数，显式注入 `MEWCODE_WORKSPACE_ROOT`。
2. 支持有序追加受限 `GIT_CONFIG_COUNT/KEY_n/VALUE_n`，拒绝畸形、重复或超限的既有 Git 配置注入。

**验证：** 运行 `python -m pytest tests/test_processes.py -k environment -q`，期望任务环境正确合并、敏感过滤不被反转且进程全局环境保持不变。

## T10: 实现结构化 Git 命令执行器

**文件：** `src/mewcode/worktrees/git.py`、`tests/worktrees/test_git.py`

**依赖：** T2、T9

**步骤：**
1. 实现 `GitCommandRunner.run()`，仅接收结构化 argv、显式 cwd、受控环境、超时和输出上限。
2. 使用 `asyncio.create_subprocess_exec` 和现有进程停止辅助函数，输出只保留有界脱敏摘要。

**验证：** 运行 `python -m pytest tests/worktrees/test_git.py -k runner -q`，期望参数不经 shell、cwd/environment 明确，超时和超量输出能终止进程并返回确定结果。

## T11: 实现纯文件系统仓库定位与基线解析

**文件：** `src/mewcode/worktrees/git.py`、`tests/worktrees/test_git.py`

**依赖：** T6、T10

**步骤：**
1. 实现 `discover_repository()`，仅解析工作区 `.git` 目录或指针及 `commondir`，形成冻结 `RepositoryIdentity` 而不启动 Git。
2. 实现 `resolve_head()`，在显式 cwd 下把创建基线解析成固定 OID，并对非 Git、不可解析和不支持状态产生有界错误。

**验证：** 运行 `python -m pytest tests/worktrees/test_git.py -k 'discover or resolve_head' -q`，期望身份定位零 Git，基线解析返回固定 OID，错误仓库安全失败。

## T12: 实现临时分支与 Worktree 创建

**文件：** `src/mewcode/worktrees/git.py`、`tests/worktrees/test_git.py`

**依赖：** T10、T11

**步骤：**
1. 实现 `GitWorktreeBackend.add()`，用固定基线 OID、完整临时引用和绝对目标创建分支与 Worktree。
2. 对已存在引用、目录、锁冲突及部分失败返回可供生命周期判断拥有关系的确定错误，不修改主工作树状态。

**验证：** 运行 `python -m pytest tests/worktrees/test_git.py -k add -q`，期望临时仓库中新建目标指向固定 OID，主分支、暂存区和未提交文件保持不变。

## T13: 实现工作区变更与未发布提交保护

**文件：** `src/mewcode/worktrees/git.py`、`tests/worktrees/test_git.py`

**依赖：** T10、T12

**步骤：**
1. 用 porcelain v2 区分已跟踪修改和未忽略 untracked，并解析当前 `HEAD` 为 `head_oid`。
2. 用 `base_oid..HEAD --not --remotes` 判断新提交是否被任一现有远端跟踪引用包含；缺失、损坏或读取失败一律保护。

**验证：** 运行 `python -m pytest tests/worktrees/test_git.py -k protection -q`，期望干净、tracked、untracked、已推送、未推送、无远端及远端读取失败场景得到正确保守状态且无网络调用。

## T14: 实现精确 Worktree 与条件分支删除

**文件：** `src/mewcode/worktrees/git.py`、`tests/worktrees/test_git.py`

**依赖：** T13

**步骤：**
1. 实现精确绝对路径 Worktree 删除，不接受通配符、模糊路径或 shell 字符串。
2. 使用完整引用和保护检查所得 `head_oid` 条件删除临时分支；即使强制模式也不绕过 OID 和归属条件。

**验证：** 运行 `python -m pytest tests/worktrees/test_git.py -k delete -q`，期望只删除目标 Worktree/引用，引用移动或名称相近时拒绝且其他资源不变。

## T15: 实现跨平台目录链接适配

**文件：** `src/mewcode/worktrees/links.py`、`tests/worktrees/test_links.py`

**依赖：** T6

**步骤：**
1. 封装类 Unix 目录符号链接和 Windows 目录链接/重解析点创建与检查。
2. 强制源位于主工作目录内、已存在且类型匹配，目标位于 Worktree；失败时不回退复制。

**验证：** 运行 `python -m pytest tests/worktrees/test_links.py -q`，期望平台替身收到精确源/目标，逃逸、类型冲突和能力缺失均安全失败且不复制内容。

## T16: 实现有界忽略内容复制

**文件：** `src/mewcode/worktrees/initializer.py`、`tests/worktrees/test_initializer.py`

**依赖：** T4、T6、T10

**步骤：**
1. 对明确 `copy` 规则验证源未被跟踪且已被忽略，按相同相对路径复制到 Worktree。
2. 使用不跟随链接的显式遍历，执行 4,096 文件、16 MiB 单文件和 64 MiB 总量限制，并拒绝目标冲突或覆盖。

**验证：** 运行 `python -m pytest tests/worktrees/test_initializer.py -k copy -q`，期望仅声明的安全忽略内容被复制，跟踪内容、链接逃逸、超限和冲突按规则失败。

## T17: 实现依赖目录链接初始化

**文件：** `src/mewcode/worktrees/initializer.py`、`src/mewcode/worktrees/links.py`、`tests/worktrees/test_initializer.py`

**依赖：** T15、T16

**步骤：**
1. 执行声明的 `link` 规则，验证源/目标边界、忽略状态、类型和目标空缺后调用平台适配器。
2. 把创建的链接记入初始化日志，链接失败按必需/可选语义处理且绝不复制目录。

**验证：** 运行 `python -m pytest tests/worktrees/test_initializer.py -k link -q`，期望大型依赖只产生链接，可选失败形成诊断，必需失败进入回滚路径。

## T18: 实现任务级 Git Hook 环境

**文件：** `src/mewcode/worktrees/initializer.py`、`tests/worktrees/test_initializer.py`

**依赖：** T4、T9、T16

**步骤：**
1. 验证 `git_hooks` 仓库相对路径并构造任务环境中的 `core.hooksPath` 覆盖，不写共享或用户 Git 配置。
2. 在初始化结果中返回已验证 Hook 相对路径，使双份记录可持久化并在快速恢复时重建相同环境。

**验证：** 运行 `python -m pytest tests/worktrees/test_initializer.py -k hooks -q`，期望任务 Git 使用目标 Hook，主仓库配置未变化，畸形既有 `GIT_CONFIG_*` 被拒绝。

## T19: 完成初始化诊断与拥有资源回滚

**文件：** `src/mewcode/worktrees/initializer.py`、`tests/worktrees/test_initializer.py`

**依赖：** T16、T17、T18

**步骤：**
1. 实现 `InitializationJournal`，只逆序移除本次调用成功创建的文件、目录或链接，不删除调用前资源。
2. 必需规则失败触发回滚并阻止就绪，可选规则失败保留可用环境并输出有界、脱敏诊断。

**验证：** 运行 `python -m pytest tests/worktrees/test_initializer.py -k 'rollback or diagnostic or required' -q`，期望各阶段故障只回滚本次拥有资源且诊断不泄露内容或环境值。

## T20: 实现生命周期新建协议

**文件：** `src/mewcode/worktrees/lifecycle.py`、`tests/worktrees/test_lifecycle.py`

**依赖：** T7、T11、T12、T19

**步骤：**
1. 在名称级锁和短时仓库锁内按“重查目标→固定 HEAD→写 provisioning→Git add→初始化→写 marker→写 ready”顺序创建。
2. 为每次创建生成随机 `management_id`，记录 `base_oid`、任务 ID 和 Hook 路径；故障只清理本次拥有资源。

**验证：** 运行 `python -m pytest tests/worktrees/test_lifecycle.py -k create -q`，期望调用顺序准确、成功状态完整，逐阶段注入失败不留下可恢复环境或损坏调用前资源。

## T21: 实现生命周期快速恢复

**文件：** `src/mewcode/worktrees/lifecycle.py`、`tests/worktrees/test_lifecycle.py`

**依赖：** T8、T18、T20

**步骤：**
1. 取得名称级锁后重查现有目标并调用纯文件系统身份验证，仅接受同任务 `ready` 记录。
2. 从持久化 Hook 相对路径重建 `WorktreeEnvironment.process_environment`，不运行 Git、不重新初始化、不写文件。

**验证：** 运行 `python -m pytest tests/worktrees/test_lifecycle.py -k recover -q`，期望完整环境零 Git/零写入恢复，任务或状态不匹配确定拒绝且不修复现场。

## T22: 实现进入租约和活动状态

**文件：** `src/mewcode/worktrees/lifecycle.py`、`tests/worktrees/test_lifecycle.py`

**依赖：** T21

**步骤：**
1. 实现 `enter()`，复验任务身份和记录后获取跨进程文件锁，单向持久化 `active` 并返回不可复制 `WorktreeLease`。
2. 防止同一 Worktree 被两个任务同时进入，确保全过程不调用 `chdir()`。

**验证：** 运行 `python -m pytest tests/worktrees/test_lifecycle.py -k enter -q`，期望唯一租约包含规范绝对路径/分支/隔离身份，竞争进入被串行或拒绝且进程 cwd 不变。

## T23: 实现退出保护与保留状态

**文件：** `src/mewcode/worktrees/lifecycle.py`、`tests/worktrees/test_lifecycle.py`

**依赖：** T13、T14、T22

**步骤：**
1. 实现 `exit()`：先从活动集合移除，执行完整保护；安全时精确删除，不安全或不确定时持久化 `retained` 和原因。
2. 在状态持久化后释放文件锁，并使成功、失败、取消都走同一幂等退出路径。

**验证：** 运行 `python -m pytest tests/worktrees/test_lifecycle.py -k exit -q`，期望干净或仅已发布提交自动删除，修改/未发布/检查失败保留，重复退出结果确定。

## T24: 实现列表与显式删除

**文件：** `src/mewcode/worktrees/lifecycle.py`、`tests/worktrees/test_lifecycle.py`

**依赖：** T14、T21、T23

**步骤：**
1. 实现 `list_managed()`，只枚举控制记录并做纯文件系统归属验证，返回有界安全摘要而不递归扫描任意目录。
2. 实现 `delete()`，默认遵守完整保护；仅本次显式 `force=True` 可覆盖变更保护，不能覆盖活动、归属、路径或条件引用保护。

**验证：** 运行 `python -m pytest tests/worktrees/test_lifecycle.py -k 'list_managed or explicit_delete' -q`，期望状态准确，未知/非法/伪造/活动目标均确定处理且强制不越权。

## T25: 完成生命周期锁、幂等与竞态复验

**文件：** `src/mewcode/worktrees/lifecycle.py`、`tests/worktrees/test_lifecycle.py`

**依赖：** T20、T22、T23、T24

**步骤：**
1. 加入名称级异步锁、仓库短锁和现有 `FileLock` 的明确持有顺序，避免循环等待且不全局串行无关 Worktree。
2. 在删除前重新检查锁、记录归属、最终路径和保护状态，覆盖同名创建、退出/删除、路径替换及重复调用竞态。

**验证：** 运行 `python -m pytest tests/worktrees/test_lifecycle.py -k 'concurrent or idempotent or race' -q`，期望同目标状态唯一、不同目标可并行、替换攻击和重复破坏操作被拒绝。

## T26: 实现 Janitor 启动与周期调度

**文件：** `src/mewcode/worktrees/janitor.py`、`tests/worktrees/test_janitor.py`

**依赖：** T24

**步骤：**
1. 实现 `start()`、`scan_once()`、`close()`，启动后后台扫描一次，此后按注入的一小时间隔运行。
2. 注入墙上时钟、单调时钟、sleep 和候选上限；启动不等待扫描完成，关闭有界取消且不强制处理剩余目标。

**验证：** 运行 `python -m pytest tests/worktrees/test_janitor.py -k schedule -q`，期望虚拟时钟下立即扫描、逐小时扫描、关闭及时完成且无需真实等待。

## T27: 实现 Janitor 三层安全过滤

**文件：** `src/mewcode/worktrees/janitor.py`、`src/mewcode/worktrees/lifecycle.py`、`tests/worktrees/test_janitor.py`

**依赖：** T25、T26

**步骤：**
1. 按归属安全、任务占用/24 小时过期、工作区/提交保护三层顺序筛选，单轮最多检查 256 个候选。
2. 只调用生命周期非强制删除入口；单候选超时、损坏或失败形成诊断并继续后续候选，游标在整轮结束后推进。

**验证：** 运行 `python -m pytest tests/worktrees/test_janitor.py -k 'filter or limit or timeout' -q`，期望只有三层全过目标删除，额外候选延期，失败目标保留且不阻塞后续检查。

## T28: 导出 Worktree 公共 API 并提供安全默认忽略

**文件：** `src/mewcode/worktrees/__init__.py`、`.gitignore`、`tests/worktrees/test_config.py`

**依赖：** T2、T4、T25、T27

**步骤：**
1. 只导出 Plan 中稳定公共模型和服务，避免导入时仓库发现或文件写入。
2. 在 `.gitignore` 明确忽略 `.mewcode/worktrees/`，同时允许项目提交 `.mewcode/worktrees.yaml`。

**验证：** 运行 `python -m pytest tests/worktrees/test_config.py -k 'public_api or gitignore' -q`，期望导入无副作用且托管目录被忽略、配置文件不被忽略。

## T29: 建立工作区工具重建注册表

**文件：** `src/mewcode/tools/binding.py`、`src/mewcode/tools/__init__.py`、`src/mewcode/tools/builtin.py`、`tests/test_workspace.py`

**依赖：** T2、T9

**步骤：**
1. 定义可按 `WorkspaceExecutionContext` 重建的工具声明和明确的工作区无关工具声明。
2. 让内置注册表构造接收完整执行上下文；同名工具但无安全声明时不得进入隔离注册表。

**验证：** 运行 `python -m pytest tests/test_workspace.py -k binding -q`，期望可重建工具绑定指定根，工作区无关工具可复用，未知冻结工具被拒绝。

## T30: 让命令工具显式传播 cwd 与任务环境

**文件：** `src/mewcode/tools/command_tool.py`、`src/mewcode/tools/builtin.py`、`tests/test_command_tool.py`

**依赖：** T9、T29

**步骤：**
1. 让 `RunCommandTool` 从工作区执行上下文构造 `ProcessRequest.cwd` 与过滤后的任务环境。
2. 保持现有命令 schema、权限目标及共享模式行为不变，不读取或修改进程当前目录。

**验证：** 运行 `python -m pytest tests/test_command_tool.py -k workspace -q`，期望捕获请求获得 Worktree 绝对 cwd/environment，共享模式输出与旧测试一致。

## T31: 将文件读取观察改为绝对路径键

**文件：** `src/mewcode/subagents/scoped_tools.py`、`src/mewcode/tools/file_tools.py`、`src/mewcode/tools/search_tools.py`、`tests/test_subagent_scoped_tools.py`、`tests/test_file_tools.py`、`tests/test_search_tools.py`

**依赖：** T29

**步骤：**
1. 实现 `AbsolutePathKey`/`AbsolutePathSnapshotCache` 语义，Windows 下额外做大小写规范化。
2. 读操作按解析后的绝对路径记录；写入/编辑成功只失效同任务同绝对路径，不整体清缓存。

**验证：** 运行 `python -m pytest tests/test_subagent_scoped_tools.py tests/test_file_tools.py tests/test_search_tools.py -k 'cache or observation or absolute' -q`，期望不同 Worktree 同相对路径互不命中，精确失效不影响其他目录。

## T32: 为项目指令增加分作用域快照

**文件：** `src/mewcode/continuity/instructions.py`、`src/mewcode/continuity/__init__.py`、`tests/test_instruction_loader.py`

**依赖：** T31

**步骤：**
1. 在保持合并 `content` 兼容字段的同时，保留 `PROJECT_LOCAL`、`PROJECT_ROOT`、`USER` 分作用域内容。
2. 所有入口及 include 先转绝对路径缓存键，允许 Worktree 重载两个项目作用域并复用冻结用户快照。

**验证：** 运行 `python -m pytest tests/test_instruction_loader.py -k 'scope or cache or worktree' -q`，期望主调用输出兼容、不同绝对项目源隔离、用户源可稳定复用。

## T33: 提取只读记忆 Prompt 构造

**文件：** `src/mewcode/continuity/memory_prompt.py`、`src/mewcode/continuity/memory_models.py`、`src/mewcode/continuity/memory_store.py`、`tests/test_memory_store.py`

**依赖：** T31

**步骤：**
1. 把记忆读取、解码、排序和 Prompt 视图构造提取为无写入纯路径。
2. 只读项目加载不创建目录、不写索引、不恢复事务、不清理文件；失败返回诊断和空项目视图。

**验证：** 运行 `python -m pytest tests/test_memory_store.py -k 'prompt or readonly' -q`，期望有效数据稳定排序，损坏项目记忆安全降级且文件系统写入替身调用数为零。

## T34: 为 MemoryManager 增加分作用域视图

**文件：** `src/mewcode/continuity/memory_manager.py`、`src/mewcode/continuity/__init__.py`、`tests/test_memory_manager.py`

**依赖：** T33

**步骤：**
1. 提供项目和用户分作用域 Prompt 视图，同时保留现有合并视图 API。
2. 支持任务创建时冻结用户记忆，Worktree 只读加载项目记忆且不触发自动记忆更新。

**验证：** 运行 `python -m pytest tests/test_memory_manager.py -k 'scope or worktree or snapshot' -q`，期望主 Agent 合并视图不变、任务用户视图冻结、项目视图来自指定 Worktree。

## T35: 让 Hook 动作显式接收工作目录和环境

**文件：** `src/mewcode/hooks/actions.py`、`src/mewcode/hooks/models.py`、`tests/test_hook_actions.py`

**依赖：** T9

**步骤：**
1. 让 `HookActionExecutor` 和命令动作接收不可变 workspace root 与环境覆盖。
2. 确保 Hook 事件中的 `workspace.root`、进程 cwd 和 `MEWCODE_WORKSPACE_ROOT` 都指向任务 Worktree。

**验证：** 运行 `python -m pytest tests/test_hook_actions.py -k workspace -q`，期望命令 Hook 捕获到明确 Worktree cwd/environment 且全局 cwd/environment 未改变。

## T36: 拆分 Hook 共享进程状态与任务私有状态

**文件：** `src/mewcode/hooks/models.py`、`src/mewcode/hooks/runtime.py`、`tests/test_hook_runtime.py`

**依赖：** T35

**步骤：**
1. 把进程级 `once`、后台预算和诊断协调放入共享状态对象，把 Prompt 队列、取消、后台任务和执行器留在任务 runtime。
2. 用来源作用域、仓库相对配置路径、规则索引和指纹计算 once 身份，避免绝对 Worktree 路径导致重复消费。

**验证：** 运行 `python -m pytest tests/test_hook_runtime.py -k 'shared_state or once or task_private' -q`，期望相同项目规则跨 Worktree 只消费一次，而任务 Prompt/取消/关闭互不影响。

## T37: 支持 Worktree Hook 配置重载与冻结信任

**文件：** `src/mewcode/hooks/config.py`、`src/mewcode/hooks/runtime.py`、`tests/test_hook_config.py`、`tests/test_hook_runtime.py`

**依赖：** T32、T36

**步骤：**
1. 从冻结用户规则与 Worktree 项目/项目本地规则构造任务 Hook catalog，保留来源作用域和仓库相对身份。
2. 对项目外部动作复用主仓库已确认信任结果，不重新提示或扩大信任范围。

**验证：** 运行 `python -m pytest tests/test_hook_config.py tests/test_hook_runtime.py -k 'worktree or source or trust' -q`，期望任务读取 Worktree 项目规则、用户规则稳定且信任结果不漂移。

## T38: 支持 MCP 用户与项目配置分层

**文件：** `src/mewcode/mcp/config.py`、`tests/test_mcp_config.py`

**依赖：** T32

**步骤：**
1. 让配置加载结果保留用户和项目来源，支持冻结用户配置与 Worktree 项目配置确定合并。
2. 保持服务器覆盖、环境展开、未知字段和诊断语义兼容，不从主工作目录重用项目配置。

**验证：** 运行 `python -m pytest tests/test_mcp_config.py -k 'layer or worktree or snapshot' -q`，期望用户层冻结、项目层来自 Worktree、覆盖顺序和错误诊断确定。

## T39: 让任务 MCP runtime 绑定 Worktree

**文件：** `src/mewcode/mcp/runtime.py`、`src/mewcode/mcp/transport.py`、`src/mewcode/mcp/stdio.py`、`tests/test_mcp_runtime.py`、`tests/test_mcp_transports.py`

**依赖：** T9、T38

**步骤：**
1. 让 stdio transport 接收 Worktree cwd 和任务环境；每个隔离任务创建独立 `McpRuntime`。
2. 只启动冻结工具名实际需要的服务，缺失工具在模型请求前失败，关闭时有界停止 runtime 和线程。

**验证：** 运行 `python -m pytest tests/test_mcp_runtime.py tests/test_mcp_transports.py -k 'workspace or selected or close' -q`，期望 stdio 绑定正确目录/环境、服务按需启动、缺失工具失败且任务关闭不影响根 runtime。

## T40: 让 Skill 进程工具可按工作区重建

**文件：** `src/mewcode/skills/process_tool.py`、`src/mewcode/skills/runtime.py`、`tests/test_skill_process_tool.py`、`tests/test_skill_runtime.py`

**依赖：** T9、T29

**步骤：**
1. 保存 Skill 进程工具的可重建声明，并按工作区执行上下文创建新实例。
2. 重建实例使用 Worktree cwd/environment；定义式子 Agent 仍不继承活动 Skill 或获得 `load_skill`。

**验证：** 运行 `python -m pytest tests/test_skill_process_tool.py tests/test_skill_runtime.py -k 'workspace or rebuild or subagent' -q`，期望命令绑定 Worktree，工具白名单和活动 Skill 隔离保持不变。

## T41: 让冻结权限规则重新绑定 Worktree 目标

**文件：** `src/mewcode/permissions/targets.py`、`src/mewcode/subagents/permissions.py`、`tests/test_permission_targets.py`、`tests/test_subagent_permissions.py`

**依赖：** T6

**步骤：**
1. 保留冻结权限模式和规则集合，用 Worktree 根重建相对路径目标解析器。
2. 禁止隔离任务写入持久权限，确保同一规则在主目录和 Worktree 中各自解析到正确绝对目标。

**验证：** 运行 `python -m pytest tests/test_permission_targets.py tests/test_subagent_permissions.py -k 'workspace or snapshot' -q`，期望权限语义不变、路径目标按任务根解析且持久写入仍被禁止。

## T42: 创建每 Worktree Prompt 与 Context 对象

**文件：** `src/mewcode/prompting/environment.py`、`src/mewcode/prompting/builder.py`、`src/mewcode/context/archive.py`、`src/mewcode/context/manager.py`、`tests/test_prompt_builder.py`、`tests/test_context_archive.py`

**依赖：** T31、T32、T34

**步骤：**
1. 让 `PromptEnvironmentProvider`/`PromptBuilder` 接受实际 Worktree 根、分支和隔离说明，合并冻结用户与 Worktree 项目上下文。
2. 为每个任务创建独立 `ContextArchive`/`ContextManager`，归档路径位于该 Worktree `.mewcode/context/`。

**验证：** 运行 `python -m pytest tests/test_prompt_builder.py tests/test_context_archive.py -k worktree -q`，期望系统上下文描述真实 Worktree，归档写入该目录且主 Context 不受影响。

## T43: 实现 Worktree 项目上下文加载器

**文件：** `src/mewcode/subagents/workspace_runtime.py`、`tests/test_subagent_worktree.py`

**依赖：** T32、T34、T37、T38

**步骤：**
1. 实现 `WorkspaceProjectContextLoader.load()`，从 Worktree 重载项目指令、项目记忆、项目 Hook 和项目 MCP 配置。
2. 合并 `UserPromptSnapshot` 与 `ProjectPromptSnapshot`，把有界项目诊断限制在当前任务且不写回主会话。

**验证：** 运行 `python -m pytest tests/test_subagent_worktree.py -k project_context -q`，期望 Worktree 项目内容生效、用户内容冻结共享、读取失败只影响任务项目视图。

## T44: 实现 WorkspaceRuntimeBundle 基础装配

**文件：** `src/mewcode/subagents/workspace_runtime.py`、`tests/test_subagent_worktree.py`

**依赖：** T29、T37、T39、T41、T42、T43

**步骤：**
1. 实现 `WorkspaceRuntimeBundleFactory.create()`：从 `WorktreeLease` 创建 `WorkspaceExecutionContext`，按 Worktree 根装配 Workspace、权限、Prompt、Context、Hook 和 MCP。
2. 使用共享底层 Provider/用量账本并在任务外层创建独立 Hook/请求边界包装，保持根 Provider 不变。

**验证：** 运行 `python -m pytest tests/test_subagent_worktree.py -k bundle_components -q`，期望各组件绑定同一 Worktree，Provider 用量共享但 Hook runtime 隔离。

## T45: 完成 bundle 工具选择与关闭顺序

**文件：** `src/mewcode/subagents/workspace_runtime.py`、`tests/test_subagent_worktree.py`

**依赖：** T31、T39、T40、T44

**步骤：**
1. 根据冻结工具名选择可重建内置、MCP、Skill 和明确工作区无关工具，任一缺失时在首次模型请求前关闭已建资源并失败。
2. 实现幂等 `WorkspaceRuntimeBundle.close()`，按 MCP→Hook→Context 顺序有界关闭并汇总安全诊断。

**验证：** 运行 `python -m pytest tests/test_subagent_worktree.py -k 'tool_selection or bundle_close' -q`，期望工具集合精确，缺失工具零模型调用，重复关闭无重复副作用。

## T46: 冻结定义式任务能力并选择隔离驱动

**文件：** `src/mewcode/subagents/catalog.py`、`src/mewcode/subagents/coordinator.py`、`src/mewcode/subagents/policy.py`、`tests/test_subagent_catalog.py`、`tests/test_subagent_coordinator.py`

**依赖：** T1、T41、T45

**步骤：**
1. 为定义式任务冻结允许工具名称、权限策略、用户指令/记忆及用户 Hook/MCP 快照，不冻结绑定主目录的工具实例。
2. 仅对 `isolation: worktree` 选择 Worktree 驱动；共享定义式和 Fork 继续使用原路径、schema 和缓存前缀。

**验证：** 运行 `python -m pytest tests/test_subagent_catalog.py tests/test_subagent_coordinator.py -k 'isolation or frozen or fork' -q`，期望三种任务选择正确且 Agent 委派协议无变化。

## T47: 实现 WorktreeSubagentDriver

**文件：** `src/mewcode/subagents/worktree_driver.py`、`tests/test_subagent_worktree.py`

**依赖：** T21、T22、T23、T45

**步骤：**
1. `prepare()` 依次创建/恢复、进入、装配 bundle，只有全部就绪后创建现有 `SubagentRuntime`。
2. 成功、失败、取消和启动异常统一关闭 runtime/bundle 并退出租约；`close()` 幂等，`outcome()` 分离模型结果和 Worktree 清理结果。

**验证：** 运行 `python -m pytest tests/test_subagent_worktree.py -k driver -q`，期望准备失败零模型调用，所有终态执行保护退出且“因变更保留”不覆盖模型成功结果。

## T48: 让 SubagentRuntime 接受显式运行时 bundle

**文件：** `src/mewcode/subagents/runtime.py`、`tests/test_subagent_runtime.py`

**依赖：** T44、T47

**步骤：**
1. 将运行时创建从硬编码主 Workspace/PromptBuilder/HookRuntime 改为接受显式 bundle，同时保留共享模式默认路径。
2. 确保 Fork 第一次请求缓存前缀、工具 schema、事件流、取消和使用量统计保持兼容。

**验证：** 运行 `python -m pytest tests/test_subagent_runtime.py -q`，期望旧共享/Fork 测试通过，新增 bundle 测试使用注入组件且无全局工作区切换。

## T49: 在任务、通知和控制结果中加入隔离摘要

**文件：** `src/mewcode/subagents/models.py`、`tasks.py`、`notifications.py`、`control.py`、`src/mewcode/subagents/__init__.py`、`tests/test_subagent_tasks.py`、`test_subagent_notifications.py`、`test_subagent_control.py`

**依赖：** T23、T47、T48

**步骤：**
1. 给快照、终端通知和结果加入 `WorktreeTaskSummary`，包含有界状态、路径、分支和保留原因。
2. 任务管理器只在驱动关闭后读取最终 outcome；正常保留不改模型终态，无法确定清理状态才报告清理失败。

**验证：** 运行 `python -m pytest tests/test_subagent_tasks.py tests/test_subagent_notifications.py tests/test_subagent_control.py -k 'worktree or cleanup or summary' -q`，期望前后台结果一致、摘要可定位且无管理 ID/原始 Git 输出。

## T50: 扩展本地命令运行时协议和 Worktree 列表

**文件：** `src/mewcode/commands/contracts.py`、`src/mewcode/commands/builtin.py`、`tests/test_builtin_commands.py`

**依赖：** T24、T49

**步骤：**
1. 为 `CommandRuntime` 增加 `list_worktrees()` 与 `delete_worktree()`，注册不进入模型工具表的 `/worktrees` 和 `/worktree`。
2. 实现 `/worktrees` 的无参数校验及安全格式化，只显示已验证名称、状态、路径、分支和有界保护原因。

**验证：** 运行 `python -m pytest tests/test_builtin_commands.py -k worktrees -q`，期望列表格式确定、额外参数报用法错误、模型工具注册表未增加 Worktree 工具。

## T51: 实现严格本地删除命令

**文件：** `src/mewcode/commands/builtin.py`、`tests/test_builtin_commands.py`

**依赖：** T50

**步骤：**
1. 严格解析 `/worktree delete <逻辑名称>` 和末尾单次 `--force`，拒绝空名称、额外参数、错误顺序和重复标志。
2. 把逐次布尔值原样传给运行时，并确定格式化 `deleted`、`already_absent`、`retained`、`active`、`rejected`。

**验证：** 运行 `python -m pytest tests/test_builtin_commands.py -k worktree_delete -q`，期望合法命令精确调用一次，所有畸形命令零生命周期调用且强制状态不跨命令保存。

## T52: 接入 Conversation 的列表、删除和 Janitor 生命周期

**文件：** `src/mewcode/conversation.py`、`src/mewcode/repl.py`、`tests/test_conversation.py`

**依赖：** T27、T50、T51

**步骤：**
1. 让 `Conversation` 代理 Worktree 列表/删除，`start()` 非阻塞启动 Janitor，REPL 通过既有命令分发路径调用。
2. `close()` 先收敛子 Agent/Worktree 驱动，再关闭 Janitor，最后关闭根运行时；损坏或超时只产生有界诊断。

**验证：** 运行 `python -m pytest tests/test_conversation.py -k 'worktree or janitor or close_order' -q`，期望启停顺序准确、命令代理正确且共享会话无 Worktree 服务时仍兼容。

## T53: 在 CLI 组合根装配 Worktree 能力

**文件：** `src/mewcode/cli.py`、`tests/test_cli.py`

**依赖：** T28、T37、T39、T45、T46、T47、T52

**步骤：**
1. 装配配置快照、路径策略、Git 后端、记录存储、初始化器、生命周期、bundle 工厂和 Janitor，并注入协调器与 Conversation。
2. 分离根 Hooked Provider 与共享底层 Provider；启动只做配置和对象构造，仓库身份/ Git 能力由隔离任务、命令或扫描惰性触发。

**验证：** 运行 `python -m pytest tests/test_cli.py -k worktree -q`，期望普通启动零目录/分支/Git 副作用，非 Git/Git 不可用只使隔离操作失败，共享模式可继续运行。

## T54: 编写用户文档和示例

**文件：** `README.md`、`examples/worktrees.yaml`、`examples/agents/worktree-coder.md`

**依赖：** T4、T1、T50、T51

**步骤：**
1. 文档化 `isolation: worktree`、安全默认配置、复制/链接/Hook 规则、生命周期、保留保护和本地管理命令。
2. 明确 Worktree 不是 OS 沙箱，并列出不自动合并、同步、安装、提交、推送、fetch 或清理外部目录的边界。

**验证：** 运行 `python -m pytest tests/test_subagent_parser.py tests/worktrees/test_config.py -q`，并加载两个示例，期望示例可被正式解析器接受且 README 中命令与配置字段一致。

## T55: 建立临时仓库与本地远端测试夹具

**文件：** `tests/worktrees/helpers.py`、`tests/worktrees/test_integration.py`

**依赖：** T10

**步骤：**
1. 创建隔离临时 Git 仓库、本地裸远端、提交/推送、状态捕获、故障注入和命令记录辅助函数。
2. 清除对用户全局 Git 配置和网络的依赖，为 Windows/类 Unix 路径差异提供明确适配。

**验证：** 运行 `python -m pytest tests/worktrees/test_integration.py -k fixture -q`，期望夹具可重复创建本地仓库/远端且所有 Git 命令只访问临时目录。

## T56: 覆盖创建、初始化与快速恢复集成

**文件：** `tests/worktrees/test_integration.py`

**依赖：** T21、T28、T55

**步骤：**
1. 测试固定已提交基线创建分支/Worktree、默认与声明初始化、Hook 生效和主工作目录不变。
2. 重启式重建服务后恢复完整环境，断言零 Git、零写入、零重新初始化；逐项损坏身份时断言拒绝。

**验证：** 运行 `python -m pytest tests/worktrees/test_integration.py -k 'create_initialize or fast_recovery' -q`，期望创建顺序、初始化结果和只读恢复全部符合 Plan。

## T57: 覆盖变更与远端可达性保护集成

**文件：** `tests/worktrees/test_integration.py`

**依赖：** T23、T24、T55

**步骤：**
1. 分别构造 tracked、untracked、已忽略、未发布提交、无远端提交和被任一远端跟踪引用包含的提交。
2. 验证普通退出/删除的保留或清理结果，以及显式强制仅覆盖真实托管目标的变更保护。

**验证：** 运行 `python -m pytest tests/worktrees/test_integration.py -k protection -q`，期望保护矩阵准确、无 fetch/网络调用且只删除精确目标。

## T58: 覆盖生命周期故障与幂等重试

**文件：** `tests/worktrees/test_lifecycle.py`、`tests/worktrees/test_integration.py`

**依赖：** T25、T55

**步骤：**
1. 在创建、初始化、进入、退出和删除每个阶段注入失败或模拟中断，记录调用前后拥有资源。
2. 对失败操作重试，验证不产生第二分支/Worktree、不删除调用前资源、不把不完整状态交给任务。

**验证：** 运行 `python -m pytest tests/worktrees/test_lifecycle.py tests/worktrees/test_integration.py -k 'fault or retry or interrupted' -q`，期望所有重试结果确定且现场按所有权保守处理。

## T59: 覆盖生命周期并发与路径替换竞态

**文件：** `tests/worktrees/test_lifecycle.py`、`tests/worktrees/test_integration.py`

**依赖：** T25、T55

**步骤：**
1. 并发运行同名创建、退出与清理、显式删除与重新进入，并验证不同 Worktree 可独立推进。
2. 在删除复验前替换路径、标记或引用，验证操作拒绝且不跟随链接、不删除名称相近资源。

**验证：** 运行 `python -m pytest tests/worktrees/test_lifecycle.py tests/worktrees/test_integration.py -k 'concurrent or race or replacement' -q`，期望无死锁、同目标状态唯一、竞态攻击失败。

## T60: 覆盖 Janitor 周期、期限与候选上限

**文件：** `tests/worktrees/test_janitor.py`、`tests/worktrees/test_integration.py`

**依赖：** T27、T55

**步骤：**
1. 用可控时钟测试启动扫描、逐小时间隔、24 小时边界和 256 候选游标。
2. 让首候选超时/失败，验证后续候选继续、主请求不被等待且关闭有界。

**验证：** 运行 `python -m pytest tests/worktrees/test_janitor.py tests/worktrees/test_integration.py -k 'schedule or expiry or candidate_limit' -q`，期望时间和批次边界准确且无真实等待。

## T61: 覆盖 Janitor 三层过滤和伪造现场

**文件：** `tests/worktrees/test_janitor.py`、`tests/worktrees/test_integration.py`

**依赖：** T27、T55

**步骤：**
1. 组合归属、占用、过期、工作区变更、提交可达性及读取失败状态，逐层验证只有全通过候选删除。
2. 加入伪造标记、错误分支、链接/联接父级和被其他 Worktree 使用的分支，断言全部保留且诊断脱敏。

**验证：** 运行 `python -m pytest tests/worktrees/test_janitor.py tests/worktrees/test_integration.py -k 'three_layers or forged or conservative' -q`，期望后台从不强制或越界删除。

## T62: 覆盖隔离任务启动失败和终态收敛

**文件：** `tests/test_subagent_worktree.py`、`tests/test_subagent_runtime.py`、`tests/test_subagent_tasks.py`

**依赖：** T47、T48、T49、T53

**步骤：**
1. 模拟非 Git、Git 不可用、初始化失败、工具缺失和 bundle 构造失败，断言首次模型请求前终止并安全收敛生命周期。
2. 覆盖模型成功、失败、取消以及退出后删除/保留，验证模型结果与 Worktree 清理摘要分离。

**验证：** 运行 `python -m pytest tests/test_subagent_worktree.py tests/test_subagent_runtime.py tests/test_subagent_tasks.py -k 'startup_failure or terminal or retained' -q`，期望失败零模型调用，所有终态释放占用并给出确定摘要。

## T63: 覆盖主 Agent 与两个隔离子 Agent 端到端并行

**文件：** `tests/test_subagent_worktree.py`、`tests/worktrees/test_integration.py`

**依赖：** T53、T55、T62

**步骤：**
1. 保留主工作目录未提交修改，同时启动两个 Worktree 定义式子 Agent 修改同一相对路径为不同内容。
2. 捕获各自文件工具、命令、Hook、Skill、MCP、Prompt 和缓存根，验证三个目录互不覆盖且进程 cwd 始终不变。

**验证：** 运行 `python -m pytest tests/test_subagent_worktree.py tests/worktrees/test_integration.py -k two_isolated_agents -q`，期望主目录和两个 Worktree 内容/状态各自独立，任务可真正并发推进。

## T64: 覆盖 Worktree 项目上下文与绝对路径缓存端到端

**文件：** `tests/test_subagent_worktree.py`、`tests/test_instruction_loader.py`、`tests/test_memory_manager.py`、`tests/test_subagent_scoped_tools.py`

**依赖：** T31、T43、T45、T63

**步骤：**
1. 在主目录和两个 Worktree 的同相对路径放置不同指令、项目记忆、Hook/MCP 配置和普通文件。
2. 验证每个任务加载自身项目来源，用户来源冻结共享；读写缓存按绝对路径命中和失效，无需进入/退出时整体清理。

**验证：** 运行 `python -m pytest tests/test_subagent_worktree.py tests/test_instruction_loader.py tests/test_memory_manager.py tests/test_subagent_scoped_tools.py -k 'absolute_path or project_context or cache_isolation' -q`，期望所有项目级读取按 Worktree 隔离、用户级来源一致。

## T65: 覆盖本地 Worktree 管理命令集成

**文件：** `tests/test_builtin_commands.py`、`tests/test_conversation.py`、`tests/test_cli.py`

**依赖：** T51、T52、T53、T57

**步骤：**
1. 对可清理、受保护、活动和伪造环境执行 `/worktrees`，验证只列出归属可信记录及准确状态/原因。
2. 对干净、修改、未发布、未知、非法和伪造目标执行默认及逐次 `--force` 删除，验证权限边界和确定输出。

**验证：** 运行 `python -m pytest tests/test_builtin_commands.py tests/test_conversation.py tests/test_cli.py -k worktree -q`，期望 AC44–AC45 行为完整且模型工具 schema 无新增项。

## T66: 覆盖安全、平台与兼容性负面场景

**文件：** `tests/worktrees/test_paths.py`、`test_git.py`、`test_links.py`、`test_initializer.py`、`test_integration.py`、`tests/test_subagent_runtime.py`

**依赖：** T56、T58、T59、T61、T62

**步骤：**
1. 覆盖路径遍历、别名、重解析点、敏感/超长错误、Git 输出污染、链接能力缺失和资源上限，断言保守失败且诊断有界脱敏。
2. 覆盖非 Git、Git 不可用及不支持 Worktree 的仓库，确认只有隔离任务失败，共享与 Fork 行为、工具 schema 和缓存前缀不变。

**验证：** 运行 `python -m pytest tests/worktrees tests/test_subagent_runtime.py -k 'security or platform or compatibility or non_git' -q`，期望所有负面场景不越界、不网络访问、不降低保护要求。

## T67: 运行完整回归、编译和文档一致性检查

**文件：** 全部本阶段文件

**依赖：** T54、T56、T57、T58、T59、T60、T61、T62、T63、T64、T65、T66

**步骤：**
1. 运行全量测试和 Python 编译检查，修复任何共享模式、权限、Hook、Skill、Context、Memory、MCP、通知或用量统计回归。
2. 核对 README、示例、公开导出及本地命令帮助与最终行为一致，不引入自动合并、同步、提交、推送、fetch 或模型 Worktree 管理工具。

**验证：** 运行 `python -m compileall -q src` 和 `python -m pytest -q`，期望编译成功、全量测试全部通过且没有未处理的后台任务警告。

## 核心接口归属

| Plan 接口/类型 | 实现任务 |
|---|---|
| `WorktreeRuleKind`、`WorktreeInitRule`、`WorktreeConfig`、`WorktreeConfigSnapshot` | T2–T4 |
| `WorktreeName`、`WorktreeLayout`、`WorktreeNameFactory`、`WorktreePathPolicy` | T5–T6 |
| `WorktreeState`、`WorktreeRecord`、`WorktreeMarker`、`WorktreeRecordStore` | T2、T7–T8 |
| `GitCommandResult`、`GitCommandRunner`、`WorktreeProtection`、`GitWorktreeBackend` | T10–T14 |
| `InitializationDiagnostic`、`InitializationResult`、`InitializationJournal`、`WorktreeInitializer` | T16–T19 |
| `WorktreeEnvironment`、`WorktreeLease`、`WorktreeExitResult`、`WorktreeDeleteStatus`、`WorktreeDeleteResult`、`WorktreeStatus`、`WorktreeLifecycleService` | T20–T25 |
| `WorkspaceExecutionContext`、`UserPromptSnapshot`、`ProjectPromptSnapshot`、`WorkspaceProjectContextLoader` | T2、T42–T43 |
| `WorkspaceRuntimeBundle`、`WorkspaceRuntimeBundleFactory` | T44–T45 |
| `AbsolutePathKey`、`AbsolutePathSnapshotCache` | T31–T34 |
| `WorktreeTaskSummary`、`WorktreeSubagentDriver` | T47–T49 |
| `CleanupDiagnostic`、`CleanupReport`、`WorktreeJanitor` | T26–T27 |

## 执行顺序

```text
基础模型与边界
T1
T2 -> T3 -> T4
T2 -> T5 -> T6 -> T7 -> T8
T9

Git、初始化与生命周期
T2 + T9 -> T10 -> T11 -> T12 -> T13 -> T14
T6 -> T15
T4 + T6 + T10 + T15 -> T16 -> T17 -> T18 -> T19
T7 + T11 + T12 + T19 -> T20 -> T21 -> T22 -> T23 -> T24 -> T25
T24 -> T26 -> T27 -> T28

任务运行时支撑（可按依赖并行）
T2 + T9 -> T29 -> T30 -> T31 -> T32 -> T33 -> T34
T9 -> T35 -> T36 -> T37
T32 -> T38 -> T39
T29 -> T40
T6 -> T41
T31 + T32 + T34 -> T42 -> T43
T29 + T37 + T39 + T41 + T42 + T43 -> T44 -> T45

子 Agent 与本地命令
T1 + T41 + T45 -> T46
T21 + T22 + T23 + T45 -> T47 -> T48 -> T49
T24 + T49 -> T50 -> T51 -> T52
T28 + T37 + T39 + T45 + T46 + T47 + T52 -> T53
T1 + T4 + T50 + T51 -> T54

集成与验收准备
T10 -> T55
T21 + T28 + T55 -> T56
T23 + T24 + T55 -> T57
T25 + T55 -> T58 -> T59
T27 + T55 -> T60 -> T61
T47 + T48 + T49 + T53 -> T62 -> T63 -> T64
T51 + T52 + T53 + T57 -> T65
T56 + T58 + T59 + T61 + T62 -> T66
T54 + T56–T66 -> T67
```

## Plan 组件覆盖

| Plan 组件 | 任务 |
|---|---|
| `worktrees.models`、`config`、`paths`、`records` | T2–T8 |
| `worktrees.git`、`links`、`initializer` | T9–T19 |
| `worktrees.lifecycle`、`janitor`、公共导出 | T20–T28 |
| `processes`、`tools`、绝对路径缓存 | T9、T29–T31 |
| `continuity`、Prompt、Context | T32–T34、T42–T43 |
| Hook、MCP、Skill、权限 | T35–T41 |
| `WorkspaceRuntimeBundleFactory` | T43–T45 |
| 子 Agent 声明、协调、驱动、运行时与结果 | T1、T46–T49 |
| 命令、Conversation、REPL、CLI | T50–T53 |
| 文档、临时仓库、集成、竞态、端到端和回归 | T54–T67 |
