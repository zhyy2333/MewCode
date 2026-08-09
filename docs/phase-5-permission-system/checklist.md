# MewCode 权限系统 Checklist

> 每一项都通过运行测试、命令或观察公开行为验证，不要求逐行阅读实现代码。所有文件系统场景使用 pytest 临时目录，所有模型场景使用脚本化 Provider。

## 实现完整性

- [ ] 权限包、工具包和 Agent 包可以按任意顺序导入，且导入时不读取权限文件、不创建 Future、不启动网络请求（验证：运行 `python -c "import mewcode.tools; import mewcode.permissions; import mewcode.agent"`，期望退出码为 0 且无输出）。
- [ ] 六个内置工具均声明唯一权限目标：命令、三个普通路径、路径 glob、带 `.` 默认值的搜索路径（验证：运行 `python -m pytest tests/test_tools_base.py -q -k permission`，期望六个工具断言全部通过）。
- [ ] 权限配置、规则、目标、控制器、事件、Scheduler、REPL 和 CLI 组件均可由公开组合根构造（验证：运行 `python -m pytest tests/test_permission_integration.py tests/test_repl.py -q -k "construct or cli"`，期望无缺失依赖或循环导入）。
- [ ] 项目共享权限文件可被版本控制，本地权限与本地配置仍被忽略（验证：运行 `git check-ignore -v .mewcode/permissions.local.yaml .mewcode/config.yaml`，期望两者被忽略；运行 `git check-ignore .mewcode/permissions.yaml`，期望退出码为 1）。

## 统一权限入口与硬安全边界

- [ ] AC1：已注册且参数有效的调用在执行前产生权限决定；未知工具和参数错误不触发确认且保持原失败结果（验证：运行 `python -m pytest tests/test_tools_base.py tests/test_permission_integration.py -q -k "unknown or validation or preflight"`，期望无测试工具副作用）。
- [ ] AC2：放行模式和所有层级 `allow` 都不能放开删除根目录、格式化磁盘、关机重启或权限破坏命令，且不会产生确认事件或启动进程（验证：运行 `python -m pytest tests/test_permission_targets.py tests/test_permission_integration.py -q -k "blacklist and override"`）。
- [ ] AC3：危险命令的 Windows、类 Unix 和大小写变体均被同一不可配置安全层识别，安全相邻命令不被误拦（验证：运行 `python -m pytest tests/test_command_tool.py -q -k dangerous`）。
- [ ] AC4：读、写、编辑、查找和搜索工具能在临时项目内完成其原有成功行为（验证：运行 `python -m pytest tests/test_file_tools.py tests/test_search_tools.py -q`）。
- [ ] AC5：项目外绝对路径和通过 `..` 越界的文件调用在放行模式及显式 `allow` 下仍失败，目标文件不被读取、创建或修改（验证：运行 `python -m pytest tests/test_permission_targets.py tests/test_file_tools.py tests/test_search_tools.py -q -k "outside or traversal"`）。
- [ ] AC6：项目内符号链接指向项目外时，读、写、编辑、查找和搜索均拒绝，项目外夹具保持原内容（验证：运行 `python -m pytest tests/test_workspace.py tests/test_file_tools.py tests/test_search_tools.py -q -k symlink`）。
- [ ] AC7：黑名单和沙箱拒绝不进入规则放行或人工确认，权限决定事件和终端输出分别标记 `blacklist`、`sandbox`（验证：运行 `python -m pytest tests/test_permission_integration.py tests/test_repl.py -q -k "hard_gate or sandbox or blacklist"`）。
- [ ] 命令工具在创建子进程前复用同一黑名单，文件工具在实际操作前复用 Workspace 检查（验证：运行 `python -m pytest tests/test_command_tool.py tests/test_file_tools.py tests/test_search_tools.py -q -k "safety or outside or symlink"`，期望直接调用工具也不能绕过硬门禁）。

## 规则解析、glob 与层级

- [ ] AC8：`run_command(git status)` 只精确匹配相同完整命令，`run_command(git *)` 能匹配符合模式且包含空格的命令余部（验证：运行 `python -m pytest tests/test_permission_rules.py -q -k "exact or command_glob"`）。
- [ ] AC9：文件规则目标统一为 `/` 分隔的项目相对路径，并遵循当前平台文件系统的大小写语义（验证：运行 `python -m pytest tests/test_permission_targets.py tests/test_permission_rules.py -q -k "normalize or case"`）。
- [ ] AC10：路径 `*` 不跨目录、`**` 可递归，命令 `*` 可跨空格和 `/`；`?` 与字符集合保持 glob 语义（验证：运行 `python -m pytest tests/test_permission_rules.py -q -k glob`）。
- [ ] 自动精确规则会转义反斜杠和 glob 元字符，包含 `*`、`?` 或 `[` 的真实目标不会扩大为通配授权（验证：运行 `python -m pytest tests/test_permission_rules.py tests/test_permission_controller.py -q -k "escape or exact_rule"`）。
- [ ] AC11：只改变写入内容、替换文本、搜索词或命令超时不会改变权限目标或规则命中（验证：运行 `python -m pytest tests/test_permission_targets.py -q -k irrelevant_arguments`）。
- [ ] AC12：会话、本地项目、共享项目、用户全局同时匹配时，只采用第一个有匹配项的层级（验证：运行 `python -m pytest tests/test_permission_rules.py -q -k scope`）。
- [ ] AC13：同层精确规则优先于 glob，固定文本更多和路径段更长的 glob 优先，完全并列时 `deny` 获胜，YAML 顺序不改变结果（验证：运行 `python -m pytest tests/test_permission_rules.py -q -k "specificity or precedence or order"`）。
- [ ] AC14：未知工具、坏括号、非法转义、未知结果、错误字段类型和额外字段均产生带文件路径的配置错误，工具不执行（验证：运行 `python -m pytest tests/test_permission_config.py tests/test_permission_integration.py -q -k invalid`）。
- [ ] AC15：三个文件均缺失或仅部分缺失时加载为空对应层，不创建文件且其他层正常生效（验证：运行 `python -m pytest tests/test_permission_config.py -q -k missing`）。
- [ ] 示例权限文件可由 PyYAML 解析，并覆盖精确、命令 glob、路径 glob、allow 和 deny（验证：运行 `python -c "import yaml; data=yaml.safe_load(open('examples/permissions.yaml', encoding='utf-8')); assert isinstance(data.get('rules'), list) and data['rules']"`）。

## 权限模式

- [ ] AC16：严格模式遇到持久化 `allow` 仍首次询问；选择会话放行后相同调用不再询问，新控制器会话再次询问（验证：运行 `python -m pytest tests/test_permission_controller.py tests/test_permission_integration.py -q -k "strict and persistent"`）。
- [ ] AC17：严格模式遇到胜出的 `deny` 直接拒绝，不创建确认句柄（验证：运行 `python -m pytest tests/test_permission_controller.py -q -k "strict and deny"`）。
- [ ] AC18：默认模式分别对规则 `allow`、规则 `deny`、未命中执行允许、拒绝、询问，并对只读工具采用相同逻辑（验证：运行 `python -m pytest tests/test_permission_controller.py tests/test_plan_mode.py -q -k default`）。
- [ ] AC19：放行模式自动允许无规则和 `allow`，但仍拒绝胜出 `deny`、黑名单和沙箱越界（验证：运行 `python -m pytest tests/test_permission_controller.py tests/test_permission_integration.py -q -k "allow_mode or hard_gate"`）。
- [ ] CLI 无参数时使用 `default`，三个合法 `--permission-mode` 值正确进入控制器，非法值不启动 Provider（验证：运行 `python -m pytest tests/test_repl.py -q -k "cli and permission_mode"`）。
- [ ] `/permissions` 查询当前模式，三个切换命令只改变会话状态，非法命令显示用法且不调用 Provider（验证：运行 `python -m pytest tests/test_repl.py -q -k permissions`）。

## 人在回路与持久化

- [ ] 权限提示只显示工具名和规范化目标，并提供 deny、once、session、permanent 四个选项（验证：运行 `python -m pytest tests/test_repl.py -q -k permission_request`）。
- [ ] AC20：选择 once 只执行当前调用，相同调用再次出现仍询问，规则仓库和本地文件不变化（验证：运行 `python -m pytest tests/test_permission_controller.py tests/test_permission_integration.py -q -k once`）。
- [ ] AC21：选择 session 后相同规范化调用在当前会话直接执行，不同目标仍判断，新仓库实例没有该规则（验证：运行 `python -m pytest tests/test_permission_controller.py tests/test_permission_integration.py -q -k session`）。
- [ ] AC22：选择 permanent 后当前调用获准、会话规则立即生效、本地 YAML 新增一条不重复精确 allow（验证：运行 `python -m pytest tests/test_permission_config.py tests/test_permission_controller.py tests/test_permission_integration.py -q -k permanent`）。
- [ ] AC23：永久写入不修改用户或共享文件，保留本地其他有效规则，并保持本地文件被版本控制忽略（验证：运行 `python -m pytest tests/test_permission_config.py -q -k "preserve or scope"`，并运行 `git check-ignore .mewcode/permissions.local.yaml`，期望退出码为 0）。
- [ ] 永久写入前重新读取磁盘最新内容，相同 allow 去重，临时文件校验后原子替换，失败时旧文件与内存快照不变（验证：运行 `python -m pytest tests/test_permission_config.py tests/test_permission_rules.py -q -k "atomic or external_change or failure"`）。
- [ ] AC24：重启语义中，严格模式对本地永久 allow 再次首次询问，默认模式直接采用（验证：运行 `python -m pytest tests/test_permission_integration.py -q -k restart`）。
- [ ] AC25：deny、EOF、非交互响应缺失和确认取消都以拒绝结束，工具调用次数为零（验证：运行 `python -m pytest tests/test_repl.py tests/test_permission_integration.py -q -k "deny or eof or noninteractive"`）。
- [ ] AC26：同一批次多个 ask 按模型调用顺序逐个出现，各选择只作用于对应调用（验证：运行 `python -m pytest tests/test_tool_scheduler.py tests/test_permission_integration.py -q -k serial`）。
- [ ] 空输入和非法确认输入会重复提示，不修改权限状态，也不会意外执行工具（验证：运行 `python -m pytest tests/test_repl.py -q -k invalid_confirmation`）。

## Scheduler 与 Agent Loop 集成

- [ ] AC27：黑名单、沙箱、规则和用户拒绝均产生 `ok=False` 的 ToolResult，metadata 含脱敏 `permission.outcome/source`，Provider 消息不含确认句柄（验证：运行 `python -m pytest tests/test_permission_integration.py -q -k "metadata or provider_message"`）。
- [ ] AC28：首轮工具被拒绝后，失败结果回写模型，下一轮可改用其他工具并最终以 `COMPLETED` 结束（验证：运行 `python -m pytest tests/test_agent_runner.py tests/test_permission_integration.py -q -k "permission and loop"`）。
- [ ] 权限拒绝不增加连续未知工具计数，也不新增 Agent 停止原因（验证：运行 `python -m pytest tests/test_agent_runner.py -q -k "permission or unknown"`）。
- [ ] AC29：只读批次中部分拒绝不会取消其他获准调用，完成事件可按完成时间出现，Provider 结果保持原始索引顺序（验证：运行 `python -m pytest tests/test_tool_scheduler.py tests/test_permission_integration.py -q -k "mixed or order"`）。
- [ ] 权限预检完成后，获准只读调用仍遵守最大并发 4，副作用调用仍是独占屏障（验证：运行 `python -m pytest tests/test_tool_scheduler.py -q -k "concurrency or barrier"`）。
- [ ] AC30：终端区分确认、允许、黑名单、沙箱、规则和用户拒绝，且不输出文件内容、替换文本、API Key 或完整规则（验证：运行 `python -m pytest tests/test_repl.py -q -k "permission and redact"`）。
- [ ] AC31：确认期间取消会取消活动 Challenge、阻止当前和后续未获准工具启动，并返回可继续使用的 REPL（验证：运行 `python -m pytest tests/test_tool_scheduler.py tests/test_permission_integration.py tests/test_repl.py -q -k "cancel and permission"`）。
- [ ] 取消和异常后没有未解析确认、活动工具任务或后台 Agent 任务（验证：运行 `python -m pytest tests/test_tool_scheduler.py tests/test_agent_runner.py -q -k cancel`，期望测试在限定时间内完成且无 asyncio pending-task 警告）。
- [ ] AC32：启动时损坏 YAML 返回清晰非零错误；运行期永久写入失败拒绝当前调用但 REPL 仍能处理下一条输入（验证：运行 `python -m pytest tests/test_permission_config.py tests/test_repl.py tests/test_permission_integration.py -q -k "config_error or write_failure"`）。
- [ ] Plan Mode 只暴露只读工具但仍经过当前权限模式和规则，`/do` 复用同一会话授权（验证：运行 `python -m pytest tests/test_plan_mode.py tests/test_permission_integration.py -q -k permission`）。

## 编译、测试与范围约束

- [ ] AC33：权限专项测试在无真实 API Key、无网络、无真实危险命令且只使用临时工作区时全部通过（验证：运行 `python -m pytest tests/test_permission_config.py tests/test_permission_rules.py tests/test_permission_targets.py tests/test_permission_controller.py tests/test_permission_integration.py -q`）。
- [ ] AC34：现有六个工具、双 Provider、Agent Loop、Plan Mode、流式事件、取消与调度测试全部通过（验证：运行 `python -m pytest -q`）。
- [ ] AC35：全部 Python 源文件在当前 Python 3.11+ 环境可编译，完整测试通过（验证：运行 `python --version`、`python -m compileall -q src` 和 `python -m pytest -q`，期望均成功）。
- [ ] 项目没有配置独立 lint 工具；代码至少通过 Python 编译、pytest 和补丁空白检查（验证：运行 `python -m compileall -q src`、`python -m pytest -q` 和 `git diff --check`，期望退出码均为 0）。
- [ ] 本阶段没有新增网络策略、资源配额、审计日志、操作系统级命令沙箱或副作用回滚模块（验证：运行 `git diff --name-only` 并与 `task.md` 文件清单对照，期望没有范围外模块；运行 `rg -n "T[B]D|TO[D]O" src tests docs/phase-5-permission-system README.md`，期望无遗留占位项）。
- [ ] README 明确记录模式、规则文件、glob 转义、四种确认选择、硬门禁及命令子进程不受路径沙箱隔离（验证：运行 `rg -n "permission-mode|/permissions|permissions\.local\.yaml|run_command\(git|glob|路径沙箱|命令子进程" README.md`，期望覆盖全部主题）。

## 端到端场景

- [ ] 场景 1——默认模式会话放行：脚本化模型请求未配置的安全读工具，终端选择 session；当前调用执行，模型再次请求相同目标时不再提示，最终正常完成（验证：运行 `python -m pytest tests/test_permission_integration.py -q -k e2e_default_session`）。
- [ ] 场景 2——严格模式永久规则：临时项目已有精确本地 allow，严格模式仍首次提示；选择 session 后重复调用直通，新建会话后再次提示（验证：运行 `python -m pytest tests/test_permission_integration.py -q -k e2e_strict_persistent`）。
- [ ] 场景 3——放行模式硬拦截恢复：模型请求黑名单命令，系统无提示拒绝并回写原因；模型下一轮改用安全专用工具并完成（验证：运行 `python -m pytest tests/test_permission_integration.py -q -k e2e_blacklist_recovery`）。
- [ ] 场景 4——符号链接沙箱：项目内路径经符号链接指向项目外夹具，即使放行模式和显式 allow 同时存在仍拒绝，夹具内容不变（验证：运行 `python -m pytest tests/test_permission_integration.py -q -k e2e_symlink_escape`）。
- [ ] 场景 5——永久放行重启：默认模式选择 permanent 后本地文件原子生成；新控制器加载后直接允许相同目标，不影响不同项目（验证：运行 `python -m pytest tests/test_permission_integration.py -q -k e2e_permanent_restart`）。
- [ ] 场景 6——混合批次：同一模型响应包含规则拒绝、用户确认允许和自动允许的只读调用；确认串行、允许项并发、拒绝项零调用，Provider 按原顺序收到全部结果（验证：运行 `python -m pytest tests/test_permission_integration.py -q -k e2e_mixed_batch`）。
- [ ] 场景 7——确认中取消：权限提示出现后触发取消，当前及后续工具均未启动，Agent 以 cancelled 结束，REPL 接受下一条模式查询（验证：运行 `python -m pytest tests/test_permission_integration.py tests/test_repl.py -q -k e2e_cancel_prompt`）。
