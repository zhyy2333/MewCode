# Skill 系统 Checklist

> 本清单在实现开始时全部保持未勾选。只有对应代码、自动化测试和必要的人工观察都完成，并保留可复查证据后，才能把 `[ ]` 改为 `[x]`。
>
> 验收以 `spec.md` 的外部行为为准；实现细节若与 `plan.md` 不一致，必须先更新并重新批准设计文档。Windows、Linux、macOS 的等价性只有三个平台实际运行成功后才能勾选。

## 实施门禁与工程完整性

- [ ] `spec.md`、`plan.md`、`task.md` 和本 `checklist.md` 均已获得明确批准，实施没有早于四份文档批准。
- [ ] `pyproject.toml` 已登记 `jsonschema>=4,<5`，构建产物包含 commit、test、review 入口以及 review 的工具声明和脚本（证据：构建 wheel，在隔离导入路径枚举并读取五个资源）。
- [ ] `mewcode.skills` 可以独立导入，导入时不扫描真实用户目录、不创建 Provider/MCP/终端、不启动脚本（证据：隔离导入测试与进程调用计数均通过）。
- [ ] Skill 定义、发现、目录、物化、进程工具、历史、运行时、执行和集成测试文件均已建立，并能在临时目录运行（证据：运行全部 `tests/test_skill_*.py`）。
- [ ] 全量 Profile、MCP 状态、动态命令、提示构建、Agent Runner/Scheduler、会话、Context、Conversation、REPL 与 CLI 的兼容测试均已更新（证据：相关既有测试与新增测试一起通过）。
- [ ] 测试不读取真实 `~/.mewcode/skills/`，不连接真实模型、网络或 MCP，不要求人工输入，不修改仓库外数据（证据：测试夹具审计及隔离环境运行记录）。
- [ ] 所有新增诊断使用安全、可区分的用户消息，不以原始堆栈替代说明，不包含 API Key、完整 SOP、schema、独立内部历史或原始 stderr。
- [ ] 未实现 Skill 市场、安装分发、版本管理、后台 watcher、调用时模式覆盖、自定义参数级权限或其他 Spec 排除项（证据：代码和公开文档差异审计）。

## 定义、发现与命令

- [ ] AC1（F1、F3、F6–F8）：合法单文件和目录包都能解析 YAML 元信息及 Markdown SOP；名称不匹配、非法 kebab-case、字段缺失、mode/history/model 冲突及未知字段只跳过该定义并显示来源（证据：`python -m pytest tests/test_skill_parser.py -k 'frontmatter or entry or strict or name' -q`）。
- [ ] AC2（F2、F4）：同名 Skill 按项目＞用户＞内置选择；高层定义无效时回退下一有效层且其他定义不受影响（证据：`python -m pytest tests/test_skill_discovery.py tests/test_skill_catalog.py -k 'precedence or fallback or invalid' -q`）。
- [ ] AC3（F5、F9）：同层有效重名、Skill 命令互撞、与系统命令/别名大小写变体冲突都在首次交互提示前失败，并列出冲突名与全部来源（证据：`python -m pytest tests/test_skill_catalog.py tests/test_skill_integration.py -k 'duplicate or command_conflict or startup_failure' -q`）。
- [ ] AC4（F16）：`/help` 和真实 Tab 补全显示最终快照中的全部有效 `/<skill-name> [input]`，不显示无效或被覆盖入口；热更新后帮助、补全与分发读取同一命令快照（证据：`python -m pytest tests/test_command_core.py tests/test_terminal.py tests/test_skill_integration.py -k 'skill_command or help or completion' -q`）。

## 两阶段加载与共享执行

- [ ] AC5（F10）：首个模型请求只包含有效 Skill 名称和单行说明，不含未激活 SOP、专属工具 schema、脚本内容或工具定义；启动阶段没有专属脚本进程（证据：检查假 Provider 首请求和进程 spy，运行 `python -m pytest tests/test_prompt_builder.py tests/test_skill_integration.py -k 'available or two_stage or first_request' -q`）。
- [ ] AC6（F11–F14）：Agent 自主调用固定 `load_skill` 后，共享 SOP 与专属工具在同一 Agent Run 的下一迭代可用；工具始终可见；`{{input}}` 只做字面替换，无占位符时 input 仍作为本次任务内容（证据：`python -m pytest tests/test_skill_execution.py -k 'load_tool or shared or input or same_run' -q`）。
- [ ] AC7（F15、F17）：连续用不同参数调用同一共享 Skill，主历史原样保存两次斜杠输入及正常工具链，激活实例仅一个、SOP 为最新渲染且顺序不变，历史中没有 SOP 副本（证据：`python -m pytest tests/test_skill_runtime.py tests/test_conversation.py tests/test_skill_integration.py -k 'replace or shared_history or raw_slash' -q`）。
- [ ] AC8（F19）：多个共享 Skill 按首次激活顺序持续出现在显著 `Active Skills` 区，经历多次模型迭代、上下文检查和新用户轮次仍存在（证据：`python -m pytest tests/test_prompt_builder.py tests/test_agent_runner.py tests/test_skill_integration.py -k 'active_skills or prompt_rebuild' -q`）。

## 工具白名单与系统限制

- [ ] AC9（F20–F24）：无共享 Skill 时看到模式允许的全部注册工具；激活两个共享 Skill 后取白名单并集；PLAN 再取只读交集；`load_skill` 始终保留；共享定义声明 model 时被单独跳过（证据：`python -m pytest tests/test_skill_runtime.py tests/test_skill_catalog.py tests/test_agent_runner.py -k 'whitelist or safety or model or load_skill' -q`）。
- [ ] AC10（F23、F37）：同一副作用专属工具在 DEFAULT 中可见并以完整公开名进入现有工具级权限判断，在 PLAN/READ_ONLY 中不可见且不能经 Skill 重新开放（证据：`python -m pytest tests/test_skill_process_tool.py tests/test_skill_execution.py tests/test_skill_integration.py -k 'side_effect or permission or plan' -q`）。

## 独立执行与历史隔离

- [ ] AC11（F18、F25、F26、F30）：直接调用同一独立 Skill 两次会创建两个临时上下文，只复制最近 N 个完整轮次且不拆工具链；每次主历史只增加原始斜杠 user 与最终 assistant，Provider 调用中没有额外摘要请求（证据：`python -m pytest tests/test_skill_history.py tests/test_skill_execution.py tests/test_skill_integration.py -k 'fresh or complete_turn or direct_isolated or no_summary' -q`）。
- [ ] AC12（F27–F29）：独立 Run 只继承环境、项目/用户指令、长期记忆、当前共享 SOP 和本次独立 SOP；其工具为共享并集加当前独立白名单再取模式交集；其他独立 SOP 不进入，主提示与主工具集不被污染（证据：`python -m pytest tests/test_skill_execution.py tests/test_skill_integration.py -k 'inherit or isolation or isolated_view' -q`）。
- [ ] AC13（F31）：主 Agent 自主调用 isolated 后，主历史精确保留普通用户消息、`load_skill` 调用、内容为独立最终回复的工具结果及主 Agent 最终回复；工具配对合法，内部消息/工具链不落盘（证据：`python -m pytest tests/test_skill_execution.py tests/test_session_integration.py -k 'parent_pairing or agent_isolated or private_history' -q`）。
- [ ] AC14（F32）：当前 Profile 和有效指定 Profile 可运行；缺失 Profile、无效完整配置、缺少 API Key 环境变量均在启动时失败且不泄露值；不同 Provider 仍能接收中立历史（证据：`python -m pytest tests/test_config.py tests/test_skill_catalog.py tests/test_skill_execution.py -k 'profile or credential or cross_provider' -q`）。

## 目录包与专属工具

- [ ] AC15（F33–F36）：目录包的每个 `tools/*.json` 只声明一个工具并暴露 `<skill-name>__<tool-name>`；启动只静态验证，激活前模型不可见且无实例/进程，激活后才注册，实际调用时才启动脚本（证据：`python -m pytest tests/test_skill_parser.py tests/test_skill_materialization.py tests/test_skill_integration.py -k 'package or public_name or lazy' -q`）。
- [ ] AC16（F35、F38、F39）：非数组 command、缺失脚本、相对路径逃逸均使单定义无效；合法 argv 不经 shell、包内路径解析为物化绝对路径、cwd 为工作区，脚本可读 `MEWCODE_SKILL_DIR`/`MEWCODE_WORKSPACE_ROOT`（证据：`python -m pytest tests/test_skill_parser.py tests/test_skill_process_tool.py -k 'command or path or shell or cwd or skill_dir' -q`）。
- [ ] AC17（F37）：read_only 与 side_effect 专属工具按声明参加模式筛选，以完整公开名显示在权限决策；工具 JSON 无法声明参数级权限目标或改变权限身份（证据：`python -m pytest tests/test_skill_parser.py tests/test_skill_process_tool.py tests/test_skill_integration.py -k 'safety or permission_target' -q`）。
- [ ] AC18（F40–F42）：合法成功/失败对象正确转换；非零退出、非法或多余 JSON、缺字段、超量输出和超时成为可区分有界失败；stderr 不直接显示；默认 60 秒、自定义只接受 1–600 秒，超时/取消进程被回收（证据：`python -m pytest tests/test_skill_process_tool.py -q`）。
- [ ] AC19（F43）：白名单引用不存在的全局工具、未注册/跨 Skill 专属工具及未配置或启动失败 MCP 工具时，交互前失败并指出 Skill、公开工具名和适用 MCP 状态（证据：`python -m pytest tests/test_skill_catalog.py tests/test_mcp_integration.py tests/test_skill_integration.py -k 'missing_tool or cross_skill or mcp_failure' -q`）。

## 热更新与恢复

- [ ] AC20（F44、F45）：连续无变化输入只检查元数据且不重读正文/schema；修改激活 Skill 的 SOP、白名单或模板后，下一输入前按名称绑定最高有效版本，以最后参数重渲染并保持顺序（证据：`python -m pytest tests/test_skill_runtime.py tests/test_skill_integration.py -k 'unchanged or refresh or rerender or rebind' -q`）。
- [ ] AC21（F46）：删除高层激活版本后立即回退低层并换用其 SOP/工具；删除所有有效版本后自动失活、清理运行副本并只显示一次清晰警告（证据：`python -m pytest tests/test_skill_runtime.py tests/test_skill_integration.py -k 'fallback or deactivate or cleanup' -q`）。
- [ ] AC22（F47）：热更新制造命令冲突、同层重复、白名单缺工具或无效 Profile 时整批候选被拒绝，当前输入继续使用旧目录、命令、激活 SOP、工具和物化包，无新旧混合（证据：`python -m pytest tests/test_skill_runtime.py tests/test_skill_integration.py -k 'rollback or rejected_snapshot or old_version' -q`）。
- [ ] AC23（F48、F49）：激活多个 Skill 并重复传参后重启，恢复名称、顺序和最后原始参数并用当前定义重渲染；定义缺失时忽略并警告、修正状态持久化且其余历史/Skill 正常（证据：`python -m pytest tests/test_session_codec.py tests/test_session_repository.py tests/test_session_integration.py tests/test_skill_integration.py -k 'skill_state or restore or missing_activation' -q`）。

## `/reset` 与兼容性

- [ ] AC24（F50–F53）：在 PLAN、存在消息、PendingPlan 和多个激活 Skill 时执行 `/reset`，一次性清空这些状态并恢复 `[DEFAULT]`；session ID、原创建时间、人工指令、长期记忆和权限模式不变，重启不恢复旧历史（证据：`python -m pytest tests/test_conversation.py tests/test_repl.py tests/test_session_repository.py tests/test_skill_integration.py -k 'reset_success or reset_restart' -q`）。
- [ ] AC25（F51–F53）：分别注入临时写入、fsync、replace 和提交失败，用户得到明确 reset 失败，正式文件与内存中的消息、计划、Skill 和模式仍为重置前完整状态（证据：`python -m pytest tests/test_session_repository.py tests/test_conversation.py tests/test_skill_integration.py -k 'reset_failure or atomic_reset' -q`）。
- [ ] AC26（F50）：`/clear` 仍只清终端并重绘，不改变历史、模式、计划、Skill、记忆或任何持久化记录（证据：`python -m pytest tests/test_builtin_commands.py tests/test_repl.py tests/test_skill_integration.py -k clear -q`）。

## 内置样板

- [ ] AC27（F54、F57）：`/commit [input]` 采用 shared、当前 Profile 和 `read_file/find_files/search_code/run_command`；临时 Git 仓库中能检查改动、运行相称验证、只暂存相关安全文件并恰好提交一次，无改动、验证失败或范围不明均不提交（证据：`python -m pytest tests/test_skill_integration.py -k commit_builtin -q`）。
- [ ] AC28（F55、F57）：硬编码 review 已删除，`/review` 由内置 isolated Skill 提供，history=0、当前 Profile、只读最小工具集，只依据当前工作区且执行前后工作树相同（证据：`python -m pytest tests/test_builtin_commands.py tests/test_skill_integration.py -k review_builtin -q`）。
- [ ] AC29（F56、F57）：`/test [input]` 采用 shared、当前 Profile 和最小工具集；有参数选描述/改动相关最小测试，无参数选未提交改动相关测试并可合理扩大，只运行和报告且工作区内容不变（证据：`python -m pytest tests/test_skill_integration.py -k test_builtin -q`）。
- [ ] AC30（F54–F57）：项目层和用户层分别覆盖 commit/review/test 时命令执行最高有效版本；删除覆盖后恢复内置定义，且无重复命令注册（证据：`python -m pytest tests/test_skill_catalog.py tests/test_skill_integration.py -k builtin_override -q`）。

## 质量属性

- [ ] AC31（N1–N3、N17）：以不同文件创建/枚举顺序重复启动和刷新，有效集合、覆盖、诊断、命令排序、激活顺序和工具集合一致；单定义错误隔离，全局错误原子失败，命令/加载入口共用同一 Coordinator（证据：`python -m pytest tests/test_skill_discovery.py tests/test_skill_catalog.py tests/test_skill_runtime.py -k 'deterministic or isolation or atomic' -q`）。
- [ ] AC32（N4–N8）：Skill 不能扩大模式安全类别、绕过权限或借脚本路径改变权限身份；子进程环境剔除所有 Profile Key 变量；帮助、状态、错误、会话和模型上下文不泄露 SOP、schema、独立内部历史、stderr 原文或凭据（证据：`python -m pytest tests/test_skill_process_tool.py tests/test_skill_execution.py tests/test_skill_integration.py -k 'safety or permission or privacy or credential' -q`）。
- [ ] AC33（N9、N10、N18）：最大边界内行为正常，超过入口/包/SOP/工具/白名单/argv/input/I/O/嵌套限制时有界失败；大型未激活 Skill 不进入模型请求，无变化刷新不重读，本地目录/共享加载不调用 Provider 或脚本（证据：`python -m pytest tests/test_skill_parser.py tests/test_skill_discovery.py tests/test_skill_process_tool.py tests/test_skill_runtime.py -k 'limit or bounded or lazy or unchanged' -q`）。
- [ ] AC34（N11–N13）：普通对话、PLAN、权限、压缩、恢复、记忆、MCP、帮助、补全、`/clear` 和退出回归均通过；所有落盘历史的助手工具调用与结果合法配对，除明确迁移的 `/review` 和新增 `/reset` 外行为兼容（证据：运行相关模块测试和完整 `python -m pytest -q`）。
- [ ] AC35（N14–N16）：Windows、Linux、macOS 都实际通过发现、路径边界、无 shell、cwd、JSON I/O、超时/取消终止及核心隔离测试；三平台均无真实模型、网络、MCP、用户目录或人工输入依赖（证据：保存三平台 CI 或等价运行记录，命令为 `python -m pytest tests/test_skill_discovery.py tests/test_skill_materialization.py tests/test_skill_process_tool.py tests/test_skill_history.py tests/test_skill_runtime.py tests/test_skill_execution.py -q`）。

## 会话、并发与失败边界补充检查

- [ ] 同一模型迭代的请求、未知工具判定和调度使用同一 Run View；加载后新工具只在下一模型迭代生效，同一响应中的臆测调用仍为未知工具。
- [ ] `load_skill` 是串行控制边界并免自身权限确认，但其启动的每个普通/专属工具仍经过模式筛选和现有权限系统。
- [ ] 父 Run 取消会终止嵌套独立 Run 及活动脚本；正常工具批次原有只读并发、副作用串行语义没有回归。
- [ ] 独立嵌套最多四层；嵌套 isolated 始终从主历史取轮次，不继承调用方独立私有 SOP 或历史。
- [ ] 热更新不与活动 Agent Run 并发；激活/物化前后源指纹变化会放弃调用，不会把新正文与旧元数据/脚本混合。
- [ ] Skill 激活、恢复修正、自动失活和 reset 的磁盘写入失败都不会先改变内存；成功后内存、目录、命令和物化副本一次换代。
- [ ] session replay 能跳过损坏的 `skill_state` 记录并使用最后有效列表；旧会话无该记录时按空激活恢复，不重写无关历史。
- [ ] reset 与 Agent、压缩、记忆 pending 的协调顺序经过竞态测试，失败不会留下只清了一部分的状态。

## 构建、文档与最终回归

- [ ] 所有源文件可被目标 Python 版本编译（验证：`python -m compileall -q src`）。
- [ ] Skill 相关定向测试全部通过（验证：`python -m pytest tests/test_skill_parser.py tests/test_skill_discovery.py tests/test_skill_catalog.py tests/test_skill_materialization.py tests/test_skill_process_tool.py tests/test_skill_history.py tests/test_skill_runtime.py tests/test_skill_execution.py tests/test_skill_integration.py -q`）。
- [ ] 受影响既有模块测试全部通过（验证：运行 config、tools、agent、prompt、command、terminal、conversation、session、context、MCP 和 REPL 测试组）。
- [ ] 完整测试套件通过且没有选择性跳过本阶段失败项（验证：`python -m pytest -q`）。
- [ ] wheel 构建与隔离安装烟测通过，内置资源路径不依赖源码树或当前工作目录。
- [ ] README 准确记录三级目录、严格格式、shared/isolated、Profile、白名单、专属工具、热更新、恢复、`/reset`、`/clear` 和三个内置 Skill，且不承诺本阶段排除能力。
- [ ] `git diff --check` 无空白错误；实现差异只覆盖批准文件和必要测试，没有覆盖或删除用户无关改动。
- [ ] 最终验收记录包含：测试命令及结果、wheel 烟测结果、三平台状态、未勾选项及原因、已知限制、最终 Git 状态。

## 端到端场景

- [ ] 场景 A：启动只看到 Skill 目录 → Agent 调用 shared Skill → 下一迭代获得 SOP/工具 → 再次传参替换 SOP → PLAN 收窄工具 → `/reset` 清空并重启，所有提示、权限、历史和持久化断言符合 Spec。
- [ ] 场景 B：准备含完整工具链的主历史 → 直接调用 isolated Skill → 观察 N 轮投影和临时工具事件 → 主历史只折叠两条消息 → 再次调用得到全新上下文。
- [ ] 场景 C：主 Agent 调用 isolated Skill → 子 Run 调用只读专属工具并返回最终文本 → 父历史保存配对 ToolResult 并继续回复 → 磁盘中不存在子内部链路。
- [ ] 场景 D：激活项目层目录 Skill → 修改高层文件并成功热更新 → 制造全局错误观察旧快照继续工作 → 删除高层回退用户/内置 → 删除全部后自动失活。
- [ ] 场景 E：依次运行 `/commit`、`/review`、`/test`，验证各模式、历史、工具最小集和工作区副作用；再用项目层覆盖并删除以验证回退。
- [ ] 场景 F：在 reset 写入失败、独立 Run 取消、专属脚本超时、MCP 被引用但失败、Profile 缺凭据等边界后继续交互，旧有效状态保持可用且诊断不泄密。
