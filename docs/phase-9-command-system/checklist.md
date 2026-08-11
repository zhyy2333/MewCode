# 斜杠命令注册与分发系统 Checklist

> 每一项都通过运行代码、自动化测试或观察终端行为验证。验收关注外部行为和稳定边界，不依赖处理函数的内部实现。

## 实现完整性

- [ ] 命令系统公共包可以独立导入，且导入时不创建终端、Provider 或交互循环（验证：运行 `python -c "import mewcode.commands as c; assert c.CommandRegistry and c.CommandDispatcher and c.InteractionState"`，期望成功且无输出）。
- [ ] `prompt-toolkit` 已作为 3.x 运行依赖登记，生产终端可以导入（验证：运行 `python -c "import prompt_toolkit; import mewcode.terminal; assert prompt_toolkit.__version__.split('.')[0] == '3'"`，期望成功）。
- [ ] 命令核心、内置命令、终端、Token 跟踪、Conversation、上下文和记忆状态组件均可被真实调用方使用（验证：运行 `python -m pytest tests/test_command_core.py tests/test_command_dispatcher.py tests/test_builtin_commands.py tests/test_terminal.py tests/test_usage_tracking.py tests/test_conversation.py tests/test_context_manager.py tests/test_memory_manager.py -q`，期望全部通过）。
- [ ] CLI 实际装配内置注册表、共享模式状态、真实终端和同一个跟踪 Provider（验证：运行 `python -m pytest tests/test_repl.py -k 'cli or startup or usage' -q`，期望装配身份和启动测试通过）。
- [ ] 旧会话 JSONL 格式未改变，含旧 StoredPlan 的会话仍可恢复且不会被 `/do` 自动执行或重写（验证：运行 `python -m pytest tests/test_session_codec.py tests/test_session_integration.py tests/test_conversation.py -k 'plan or legacy or resume' -q`，期望旧记录可解析、活动历史不变）。

## 注册与元数据

- [ ] AC1：检查内置注册结果，十个公开命令都具备名称、描述、用法、类型和处理行为，可选字段可缺省，exit/quit 为隐藏项（验证：运行 `python -m pytest tests/test_builtin_commands.py -k metadata -q`，期望元数据完整性测试通过）。
- [ ] AC2：分别制造名称-名称、名称-别名、别名-别名及大小写变体冲突，程序在首次输入提示前以非零状态失败并指出冲突标识（验证：运行 `python -m pytest tests/test_command_core.py tests/test_repl.py -k 'conflict or registration' -q`，期望全部冲突路径通过）。
- [ ] AC3：正常注册表恰好包含十个公开规范名称、隐藏 exit，以及 permissions/quit 两个别名，没有额外内置别名（验证：运行 `python -m pytest tests/test_builtin_commands.py -k metadata -q`，期望数量和集合精确一致）。

## 解析与分流

- [ ] AC4：提交空白、普通消息、大小写不同的命令和含重复空格的参数，观察空白无动作、消息进入当前模式、命令命中且参数内部大小写和空白保真（验证：运行 `python -m pytest tests/test_command_core.py tests/test_repl.py -k 'parse or route' -q`，期望全部场景通过）。
- [ ] AC5：提交 `/does-not-exist`，只看到未知命令和 `/help` 引导，Provider 与 Agent 调用记录为空（验证：运行 `python -m pytest tests/test_command_dispatcher.py tests/test_repl.py -k unknown -q`，期望错误提示和零模型调用断言通过）。
- [ ] AC6：向所有无参数命令追加参数，并向 permission 提交非法或多余参数，只看到对应 Usage 且没有副作用或 AI 请求（验证：运行 `python -m pytest tests/test_builtin_commands.py -k 'arguments or usage' -q`，期望参数化测试全部通过）。
- [ ] AC7：分别执行本地命令、界面命令、review 和普通消息，观察四类输入进入正确路径，只有 review 与普通消息形成对话记录（验证：运行 `python -m pytest tests/test_builtin_commands.py tests/test_repl.py -k 'routing or command_type or review' -q`，期望调用轨迹与会话记录一致）。
- [ ] AC8：让命令处理发生可预期和未预期异常，看到安全错误后继续执行下一条正常命令，消息、模式和会话状态未损坏（验证：运行 `python -m pytest tests/test_command_dispatcher.py tests/test_repl.py -k 'error or recover' -q`，期望错误隔离测试通过）。

## 模式与界面

- [ ] AC9：启动时底栏显示 `[DEFAULT]`，执行 `/plan` 后立即显示 `[PLAN]`，执行 `/do` 后恢复 `[DEFAULT]`，切换期间模型调用数和消息数不变（验证：运行 `python -m pytest tests/test_terminal.py tests/test_builtin_commands.py tests/test_repl.py -k 'toolbar or plan or do' -q`，期望状态、调用和历史断言通过）。
- [ ] AC10：在 PLAN 中要求写文件时只读工具集阻止副作用，切回 DEFAULT 后工具重新服从正常权限系统（验证：运行 `python -m pytest tests/test_conversation.py tests/test_continuity_integration.py -k plan_read_only -q`，期望工具集合和工作区快照符合预期）。
- [ ] AC11：使用不含 `prompt_toolkit` 对象的 fake UI/Runtime 执行显示、清屏、模式、Token 和刷新相关命令，全部成功（验证：运行 `python -m pytest tests/test_command_dispatcher.py tests/test_builtin_commands.py -q`，期望协议 fake 测试通过）。
- [ ] AC12：在 Windows、Linux、macOS 环境分别运行终端与 REPL 测试，流式输出、错误、清屏、连续切换、补全和底栏结果等价（验证：在每个平台运行 `python -m pytest tests/test_terminal.py tests/test_repl.py -q`，期望全部通过且最终模式标记一致）。
- [ ] 清屏、状态输出和 Agent 流式输出完成后，下一次输入提示使用同一共享模式重新绘制底栏（验证：运行 `python -m pytest tests/test_terminal.py tests/test_repl.py -k 'redraw or clear or streaming' -q`，期望无过期模式标记）。

## 帮助与补全

- [ ] AC13：执行 `/help` 看到十个公开命令和 permissions 别名，看不到 exit/quit；执行 `/help permission` 看到描述、用法、参数提示和别名（验证：运行 `python -m pytest tests/test_builtin_commands.py -k help -q`，期望帮助快照通过）。
- [ ] AC14：对单匹配、多个匹配、大小写前缀和隐藏前缀发送真实 Tab 键，观察直接补全、候选菜单、大小写无关和隐藏过滤（验证：运行 `python -m pytest tests/test_terminal.py -k tab -q`，期望真实键序列测试通过）。
- [ ] AC15：只向测试注册表增加一个公开定义，不修改帮助、解析或补全代码，新命令自动可见、可补全、可分发（验证：运行 `python -m pytest tests/test_command_core.py tests/test_command_dispatcher.py tests/test_builtin_commands.py -k extensible -q`，期望扩展测试通过）。
- [ ] AC16：帮助列表和详情由同一注册元数据生成，通过规范名称和 permissions 别名请求详情得到相同行为（验证：运行 `python -m pytest tests/test_builtin_commands.py -k 'help and alias' -q`，期望内容一致）。
- [ ] 输入光标进入参数区域后按 Tab 不再显示命令名称候选，权限询问也不启用斜杠补全（验证：运行 `python -m pytest tests/test_terminal.py -k 'argument_area or permission' -q`，期望候选为空）。

## 内置命令行为

- [ ] AC17：分别制造可压缩、无需压缩和压缩失败历史后执行 `/compact`，只发生一次手动压缩且没有 AgentRun；失败时原历史逐项不变（验证：运行 `python -m pytest tests/test_repl.py tests/test_context_manager.py -k compact -q`，期望三种状态和历史断言通过）。
- [ ] AC18：在含消息、记忆、非默认权限和 PLAN 模式的会话执行 `/clear`，显示被清除并重绘 `[PLAN]`，所有领域状态前后相同（验证：运行 `python -m pytest tests/test_builtin_commands.py tests/test_repl.py -k clear -q`，期望前后快照一致）。
- [ ] AC19：在新会话和恢复会话执行 `/session`，看到正确 ID、清理后的标题、new/resumed、消息数及 idle/busy，不看到消息或工具正文（验证：运行 `python -m pytest tests/test_builtin_commands.py tests/test_conversation.py -k session -q`，期望摘要和隐私断言通过）。
- [ ] AC20：在项目/用户记忆及 idle、running、succeeded、failed、disabled 状态下执行 `/memory`，看到正确条数、容量和状态且无正文（验证：运行 `python -m pytest tests/test_memory_manager.py tests/test_builtin_commands.py -k memory -q`，期望全部状态与容量测试通过）。
- [ ] AC21：无参数 permission 显示当前模式，依次设置 strict/default/allow 后立即生效，permissions 别名行为一致（验证：运行 `python -m pytest tests/test_builtin_commands.py tests/test_permission_integration.py -k permission -q`，期望三档模式和别名测试通过）。
- [ ] AC22：让普通、PLAN、review、压缩和记忆模型调用分别返回可核对 usage，执行 `/status` 后总计等于各调用之和且其余核心状态正确（验证：运行 `python -m pytest tests/test_usage_tracking.py tests/test_continuity_integration.py -k all_model_usage -q`，期望无遗漏、无重复）。
- [ ] AC23：让某次模型调用缺少部分或全部 usage，执行 `/status` 后未知累计项为 `n/a`、已知项仍正确且未使用估算值（验证：运行 `python -m pytest tests/test_usage_tracking.py tests/test_builtin_commands.py -k 'unreported or unknown' -q`，期望未知传播测试通过）。
- [ ] AC24：在 DEFAULT 和 PLAN 中分别执行成功及失败的 `/review`，AI 收到完全相同的固定请求和只读工具集，产生预期会话结果，工作区及持续模式不变（验证：运行 `python -m pytest tests/test_builtin_commands.py tests/test_conversation.py tests/test_continuity_integration.py -k review_read_only -q`，期望固定提示和状态不变断言通过）。
- [ ] AC25：分别通过 `/exit` 与 `/quit` 退出，看到成功返回且会话、后台记忆和资源完成收尾；帮助和补全仍不显示二者（验证：运行 `python -m pytest tests/test_repl.py tests/test_terminal.py tests/test_builtin_commands.py -k 'exit or quit' -q`，期望两条关闭路径通过）。

## 性能、隐私与集成

- [ ] AC26：依次执行 help、clear、plan、do、session、memory、permission 和 status，调用记录中没有 Provider、Agent、网络访问或等待 pending 记忆（验证：运行 `python -m pytest tests/test_continuity_integration.py -k local_commands -q`，期望全部计数为零且命令立即完成）。
- [ ] AC27：把凭据、消息正文、记忆正文、工具参数和异常秘密放入 fake 状态，帮助、状态、摘要、候选和错误均不出现这些值或堆栈（验证：运行 `python -m pytest tests/test_command_dispatcher.py tests/test_builtin_commands.py tests/test_repl.py -k privacy -q`，期望敏感标记完全缺失）。
- [ ] Provider 跟踪器对成功、多个 usage、无 usage、异常和取消的每个模型流恰好登记一次，并原样转发 Provider 事件（验证：运行 `python -m pytest tests/test_usage_tracking.py -q`，期望请求数和原事件序列精确匹配）。
- [ ] 后台记忆更新可在异步输入提示期间推进，而本地命令读取 running 快照时不等待任务完成（验证：运行 `python -m pytest tests/test_memory_manager.py tests/test_repl.py -k 'background or nonblocking' -q`，期望提示保持可用并立即返回状态）。
- [ ] 固定审查提示词不包含运行时 diff、路径、配置或动态拼接内容（验证：运行 `python -m pytest tests/test_builtin_commands.py -k review_prompt -q`，期望不同工作区状态下发送文本逐字相同）。

## 编译、测试与文档

- [ ] 所有源文件可被 Python 3.11 编译（验证：运行 `python -m compileall -q src`，期望成功且无语法错误）。
- [ ] 新增命令与终端测试无需真实网络、真实模型、真实用户目录或人工输入（验证：运行 `python -m pytest tests/test_command_core.py tests/test_command_dispatcher.py tests/test_builtin_commands.py tests/test_terminal.py tests/test_usage_tracking.py -q`，期望在隔离环境全部通过）。
- [ ] AC28：既有普通对话、压缩、权限、恢复、记忆、工具、MCP、OpenAI 和 Anthropic 测试除明确替换的旧 Plan/Do 断言外全部通过（验证：运行 `python -m pytest -q`，期望完整套件通过）。
- [ ] README 同时说明十个公开命令、两个兼容别名、DEFAULT/PLAN、Plan 强制只读、review 单次只读、clear 仅清屏及 Tab 底栏（验证：运行 `rg -n '/help|/compact|/clear|/plan|/do|/session|/memory|/permission|/permissions|/status|/review|/quit|\[DEFAULT\]|\[PLAN\]' README.md`，期望相关说明完整且无旧 `/plan <task>` 用法）。
- [ ] 项目没有独立 lint 配置，本阶段以完整测试、Python 编译和差异格式作为静态质量门（验证：分别运行 `python -m compileall -q src`、`python -m pytest -q`、`git diff --check`，期望三项全部成功）。

## 端到端场景

- [ ] AC29：执行“启动 → `/help` 与 Tab → `/plan` → 只读分析 → `/do` → `/clear` → `/permission strict` → `/session` → `/memory` → `/status` → `/review` → `/compact` → `/exit`”，观察每步路由、底栏、模型调用和会话记录正确，重启后会话可恢复（验证：运行 `python -m pytest tests/test_continuity_integration.py -k command_sequence -q`，期望完整场景通过）。
- [ ] 边界场景：执行空输入、未知命令、大小写别名、非法参数、命令异常、缺失 Token、review 失败、压缩失败、权限 EOF 和普通 EOF，观察循环或关闭行为均符合 Spec（验证：运行 `python -m pytest tests/test_command_core.py tests/test_command_dispatcher.py tests/test_builtin_commands.py tests/test_terminal.py tests/test_repl.py -k 'edge or error or eof or unknown or unreported' -q`，期望全部边界场景通过）。
