# Hook 自动化系统 Checklist

> 本清单在实现开始时全部保持未勾选。只有对应实现、自动化验证和必要的人工观察都完成，并保存可复查证据后，才能把 `[ ]` 改为 `[x]`。
>
> 验收以已批准的 `spec.md` 外部行为为准；若实现需要改变事件语义、YAML 契约、安全顺序、信任模型、资源限制或排除范围，必须先回到文档阶段重新批准。Windows、Linux、macOS 等价性只有三个平台实际运行成功后才能勾选。

## 实施门禁与工程完整性

- [ ] `spec.md`、`plan.md`、`task.md` 和本 `checklist.md` 均已获得用户明确批准，且首个实现改动发生在四份文档批准之后（证据：批准记录与首个实现提交时间/差异）。
- [ ] `pyproject.toml` 登记支持超时完整匹配的 `regex` 运行依赖；执行 `python -c "import regex; assert regex.fullmatch('a+', 'aaa', timeout=0.05)"`，观察退出码为 0。
- [ ] `mewcode.matching`、`mewcode.processes` 和 `mewcode.hooks` 的批准模块均已建立；从仓库外工作目录导入公共 API，观察不读取 Hook YAML、不创建日志或 HTTP client、不启动任务或进程。
- [ ] 权限规则与 Hook glob 使用同一共享匹配实现，`run_command` 与 Hook command 使用同一有界进程实现；运行专项回归，观察权限优先级、命令工具文案及原有 30/120 秒边界不变。
- [ ] CLI、REPL、Conversation、ContextManager、AgentRunner、ToolScheduler 和全部 Profile Provider 入口均接入同一个会话 HookRuntime；主回复、独立 Skill、压缩和记忆更新的 Provider 各只装饰一层。
- [ ] 测试只使用临时用户目录/工作区、假 Provider、`httpx.MockTransport`、假时钟和受控短命子进程；观察测试期间无真实模型、真实网络、真实用户 Hook、危险命令或人工输入。
- [ ] 实现范围未加入显式 priority、热重载、重试、跨重启 `once`、真实子 Agent、OS 沙箱或跨平台 shell 语法转换；代码和 README 均把这些能力标为本阶段排除项。
- [ ] 用户已有改动和被跟踪的 `__pycache__/*.pyc` 未被清理、覆盖或混入实现提交；检查最终 `git status --short` 和提交差异，观察只包含批准范围及必要测试/文档。

## 配置加载与工作区信任

- [ ] **AC1（F1–F7）：** 分别准备仅用户全局、项目共享、项目本地及三层同时存在的合法 YAML，启动后观察缺失文件等同空配置、规则严格按用户→项目共享→项目本地及各文件声明顺序追加；再向任一文件加入未知字段、非法事件或非法动作，观察整批启动失败且没有任何 Hook 动作、日志、HTTP client、进程或信任写入（证据：`python -m pytest tests/test_hook_config.py tests/test_hook_integration.py -q -k 'layers or order or missing or atomic or startup'`）。
- [ ] **AC2（F8–F11）：** 在未记录信任的项目共享配置中同时声明 command、HTTP、prompt、agent，观察首次交互前仅出现一次独立 yes/no 信任提示；选择拒绝后 command/HTTP 不执行、prompt 仍注入、agent 仍以占位跳过，用户全局和项目本地规则不受影响（证据：`python -m pytest tests/test_hook_trust.py tests/test_terminal.py tests/test_repl.py tests/test_hook_integration.py -q -k 'untrusted or reject or source or prompt or agent'`）。
- [ ] **AC3（F9–F12）：** 同意工作区 A 后重启，观察决定从用户级信任文件恢复；工作区 B、路径变化和损坏记录不继承决定；即使 A 已信任，危险命令、路径边界和普通权限拒绝仍生效（证据：`python -m pytest tests/test_hook_trust.py tests/test_permission_integration.py tests/test_hook_integration.py -q -k 'persist or isolated or path_change or corrupt or safety'`）。
- [ ] 信任文件读改写在并发、锁失败、临时写入失败、fsync/replace 失败和外部修改场景下保持原子；观察失败时旧文件可读、本进程不启用项目共享外部动作、其他工作区记录不丢失。
- [ ] `examples/hooks.yaml` 能被正式加载器解析，覆盖三要素、all/any、exact/glob/regex/negate、四类动作和 once/background/timeout；`git check-ignore -v .mewcode/hooks.local.yaml` 观察本地文件仍被忽略，而项目共享 `.mewcode/hooks.yaml` 可提交。

## 生命周期事件与事件信封

- [ ] **AC4（F13–F18）：** 运行一次含两次真实 Provider 调用和一次工具调用的成功轮次，记录事件序列；观察只出现批准的 11 种名称，适用的 session/turn/message/tool 事件按真实边界成对且次数准确（证据：`python -m pytest tests/test_hook_events.py tests/test_hook_provider.py tests/test_hook_integration.py -q -k 'successful_turn or lifecycle or event_names'`）。
- [ ] **AC5（F16–F20）：** 分别注入 Provider 失败、工具失败、权限拒绝、Hook 拒绝、调用方取消、压缩 no-op 和压缩失败；对每个已开始的生命周期观察恰好一个 after/end，状态分别为 success、failure、denied 或 cancelled，未真正开始的自动压缩不产生半对事件（证据：`python -m pytest tests/test_hook_provider.py tests/test_tool_scheduler.py tests/test_context_integration.py tests/test_conversation.py tests/test_hook_integration.py -q -k 'failure or denied or cancel or no_compaction or paired'`）。
- [ ] **AC6（F19、F20、F55）：** 制造一次 Provider/Agent/持久化等系统失败，观察恰好一个脱敏 `system.error`；再让匹配、动作和诊断写入各自失败，观察只记录/吞掉 Hook 失败、不生成递归 `system.error`、Agent 主流程继续（证据：`python -m pytest tests/test_hook_runtime.py tests/test_hook_provider.py tests/test_agent_runner.py tests/test_repl.py -q -k 'system_error or recursion or hook_failure'`）。
- [ ] **AC7（F21–F25、F38）：** 对同一事件同时捕获 command stdin 和 HTTP JSON body，观察语义一致且包含 schema、事件、时间、工作区、session/turn/run/iteration/message/tool 标识、状态及适用上下文；输入超限时出现稳定 `truncated_fields`，并确认外发数据不含完整历史、PromptPackage、隐藏 reasoning/provider parts、API Key 或认证头（证据：`python -m pytest tests/test_hook_events.py tests/test_hook_actions.py tests/test_hook_integration.py -q -k 'envelope or stdin or body or truncate or privacy'`）。
- [ ] 手动与自动历史压缩只在真正调用 compactor 时触发 `system.compact.before/after`；观察 `compact.before` 产生的 prompt 可进入本次摘要 Provider 请求，circuit-open 和无需压缩路径不伪造 before。
- [ ] session.start 在会话恢复和信任解决后触发并区分 new/resumed；关闭时先结束活动运行和记忆请求、再触发一次 session.end、最后清理 Hook 后台任务，重复 start/close 不产生重复事件。

## 条件表达式与共享匹配

- [ ] **AC8（F26–F27）：** 加载无 `if`、仅 `all` 和仅 `any` 的规则，观察分别按无条件、全部满足、任一满足触发；加载 all/any 混用、空组、嵌套组、未知字段或非标量值，观察启动时精确定位文件/规则/字段并整批拒绝（证据：`python -m pytest tests/test_hook_config.py tests/test_hook_conditions.py -q -k 'unconditional or all or any or mixed or empty or nested'`）。
- [ ] **AC9（F28–F31）：** 对工具名和多层 `tool.arguments.*` 分别验证 exact、glob、完整 regex 和 negate；观察权限 glob 的转义/完整匹配结果保持一致，缺失字段先不匹配再应用 negate，非法 regex 启动失败，运行时 regex 超时只让该条件不匹配（证据：`python -m pytest tests/test_matching.py tests/test_permission_rules.py tests/test_hook_config.py tests/test_hook_conditions.py -q`）。
- [ ] **AC10（F26–F31）：** 连续执行同名工具但传入两组不同嵌套参数，观察只有目标参数对应规则执行；非目标调用没有外部动作且诊断为 `NOT_MATCHED`，不存在属性访问、表达式执行或对象字符串化绕过（证据：`python -m pytest tests/test_hook_conditions.py tests/test_hook_integration.py -q -k 'nested or same_tool or not_matched or type'`）。
- [ ] 以不同文件创建顺序、映射键顺序和进程哈希种子重复加载同一配置，观察规则键、匹配结果和声明顺序稳定；运行期不扫描目录或热更新配置。

## 动作协议与失败隔离

- [ ] **AC11（F25、F32–F34、F38、F42、F51）：** 执行 command 的成功、非零退出、启动错误、超时、stdout/stderr 超限和调用方取消用例；观察 cwd 为工作区、stdin 为有界信封、无参数模板替换、API Key 环境变量已移除、进程树被回收，除调用方取消清理后继续传播外其他失败只记诊断且 Agent 继续（证据：`python -m pytest tests/test_processes.py tests/test_hook_actions.py -q -k 'command or timeout or output or cancel or environment'`）。
- [ ] **AC12（F35–F36）：** 分别从 session.start、turn.start、message.before 和 tool.after 注入可区分 prompt，观察它们按规则顺序只进入下一次真实 Provider 请求的单一 `## Hook Context`，不写入 stable system、历史或原请求对象；Provider 失败后不恢复已消费 prompt，会话结束丢弃剩余 prompt（证据：`python -m pytest tests/test_hook_provider.py tests/test_hook_runtime.py tests/test_hook_integration.py -q -k 'prompt or next_request or history or discard'`）。
- [ ] **AC13（F25、F37–F38、F42、F48）：** 用 MockTransport 覆盖 HTTP 2xx、非 2xx、网络错误、超时、重定向和响应超限，观察请求 body 为有界事件信封、响应读取受限、失败互相隔离；终端、模型上下文和诊断均不含 Authorization/Cookie 值、URL userinfo/query/fragment 或响应正文（证据：`python -m pytest tests/test_hook_actions.py tests/test_hook_runtime.py -q -k 'http or redirect or response_limit or redacted'`）。
- [ ] **AC14（F39）：** 加载并触发合法 agent 动作，观察启动校验通过、诊断结果为明确 `SKIPPED`，没有创建 Provider 调用、子 Agent、后台任务或权限挑战，主流程继续（证据：`python -m pytest tests/test_hook_actions.py tests/test_hook_runtime.py tests/test_hook_integration.py -q -k 'agent and skipped'`）。
- [ ] command 再次经过危险命令检查，HTTP 禁止自动重定向，两个动作的默认/最大超时分别保持 60/600 秒与 30/120 秒；越界值在启动时拒绝而不是运行时静默修正。

## 工具执行前拦截与权限顺序

- [ ] **AC15（F40–F45）：** 对 `tool.before` 依次返回空响应、`{"decision":"allow"}` 和带原因的合法 deny；观察前两者继续后续 Hook/权限，deny 立即停止剩余 before 规则、不执行工具，并以带有界原因的结构化失败 ToolResult 反馈给模型（证据：`python -m pytest tests/test_hook_actions.py tests/test_hook_runtime.py tests/test_tool_scheduler.py -q -k 'empty_decision or allow or deny or short_circuit'`）。
- [ ] **AC16（F41–F42）：** 让 command 非零、HTTP 非 2xx/网络错误，并返回非法 JSON、未知 decision、额外字段及缺 reason 的 deny；观察每项均成为可区分 Hook 失败并放行到后续 Hook 与权限，不误拦工具、不向模型暴露原始输出（证据：`python -m pytest tests/test_hook_actions.py tests/test_tool_scheduler.py -q -k 'invalid_decision or missing_reason or failure_allows'`）。
- [ ] **AC17（F12、F43–F45）：** Hook 返回 allow 后，分别触发危险命令、工作区路径越界、YAML deny、用户拒绝和受限 permission mode；观察五类限制仍拒绝执行，Hook 无法扩展工具集、改变权限目标或伪造权限决定（证据：`python -m pytest tests/test_permission_controller.py tests/test_permission_integration.py tests/test_tool_scheduler.py tests/test_hook_integration.py -q -k 'allow and (dangerous or boundary or rule or user or mode)'`）。
- [ ] **AC18（F12、F43）：** 用记录型 fakes 核对严格顺序为硬安全预检→Hook before→普通权限规则/人工确认；观察硬门禁拒绝时不提示无意义权限确认、不调用外部 Hook，原始危险/越界参数不进入 shell stdin 或 HTTP body（证据：`python -m pytest tests/test_tool_scheduler.py tests/test_hook_integration.py -q -k 'safety_order or hard_denied or no_external'`）。
- [ ] **AC19（F22、F40–F45）：** 分别由 Hook 和权限拒绝同类工具，观察模型都收到可调整的失败工具结果、工具实现零调用，并各产生恰好一个状态为 denied 的 tool.after；after Hook 失败不覆盖原拒绝结果（证据：`python -m pytest tests/test_tool_scheduler.py tests/test_hook_integration.py -q -k 'hook_denied or permission_denied or tool_after or model_feedback'`）。
- [ ] 未知工具、参数校验失败、普通工具失败、硬拒绝、Hook 拒绝、权限拒绝和取消均走统一完成路径；每个已接收调用观察恰好一个 tool.after，原 ToolResult/排序不被 Hook 普通错误改变。

## 执行控制、并发与诊断

- [ ] **AC20（F46–F47）：** 并发分派同一 `once: true` 规则并让首次动作失败，观察本进程仅一次动作尝试且失败不重试；同一进程恢复 session 仍不触发，完整重启后重新触发，磁盘上没有 once 标记（证据：`python -m pytest tests/test_hook_runtime.py tests/test_hook_integration.py -q -k 'once or concurrent or restart or resume'`）。
- [ ] **AC21（F48–F51）：** 同一事件交错声明同步/后台 command 与 HTTP，观察同步项严格串行、后台项按声明顺序启动且不阻塞事件返回；正常退出在有界窗口内等待，随后取消 HTTP、终止 command 进程树，任务表为空且没有孤儿进程（证据：`python -m pytest tests/test_processes.py tests/test_hook_runtime.py -q -k 'background or sequence or nonblocking or close or orphan'`）。
- [ ] **AC22（F48–F49）：** 加载 `tool.before + background`、prompt background 和 agent background，观察均在启动时拒绝并定位字段；其他事件上的合法 command/HTTP background 正常加载与执行（证据：`python -m pytest tests/test_hook_config.py tests/test_hook_runtime.py -q -k 'background and (invalid or tool_before or prompt or valid)'`）。
- [ ] **AC23（F50、F52、F55）：** 在一组同步规则中让中间的条件、动作、日志分别抛出普通异常，观察后续规则继续、turn/message/tool 原业务结果不变；再加入合法 deny，观察只有它会短路剩余 `tool.before`（证据：`python -m pytest tests/test_hook_runtime.py tests/test_hook_provider.py tests/test_tool_scheduler.py -q -k 'failure_continues or deny_short_circuit or isolation'`）。
- [ ] **AC24（F53–F55）：** 触发 NOT_MATCHED、SKIPPED、SUCCESS、FAILURE、DENIED、后台完成/取消及日志轮转，观察 JSONL 每行含时间、事件、规则来源/索引、动作类型、后台状态、耗时、结果和有界摘要；文件为当前加 `.1`–`.3`、单个约 1 MiB，且无原始堆栈、无限输出、headers、信封、凭据或敏感 URL 部分（证据：`python -m pytest tests/test_hook_runtime.py -q -k 'diagnostic or rotation or bounded or redacted'`）。
- [ ] 空 Hook 目录的 dispatch、prompt consume 和 close 不创建诊断目录、HTTP client、任务或终端 Hook 文案；后台达到 32 项、prompt 单条/总量、deny reason、摘要和关闭窗口上限时均有界降级。

## 确定性、安全性与兼容性

- [ ] **AC25（N1、N13）：** 对同一配置和事件序列重复运行，并并发执行多项工具；观察匹配、规则顺序、first-deny、once、prompt 消费、后台启动及 tool.after 映射稳定，权限/Hook glob 与命令/Hook 进程终止分别共享单一实现而无语义漂移（证据：`python -m pytest tests/test_matching.py tests/test_processes.py tests/test_hook_runtime.py tests/test_tool_scheduler.py tests/test_hook_integration.py -q -k 'deterministic or concurrent or shared'`）。
- [ ] **AC26（N2、N4–N7、N11）：** 在未信任工作区确认零项目共享外部动作；信任后确认仍不能扩权；对规则数、条件数、字段、值、regex、prompt、信封、输出、HTTP body、reason、摘要和后台任务逐项测试边界内成功与超限有界失败，观察 secrets 不进入命令环境、日志、终端或模型上下文（证据：`python -m pytest tests/test_hook_config.py tests/test_hook_events.py tests/test_hook_actions.py tests/test_hook_runtime.py tests/test_hook_integration.py -q -k 'limit or trust or permission or credential or privacy'`）。
- [ ] **AC27（N10、N13）：** 移除三层 Hook 文件后运行普通对话、持续 PLAN/execute、只读并发/副作用串行工具、权限交互、MCP、共享/独立 Skill、手动/自动压缩、会话恢复、记忆更新、`/clear` 和退出；观察用户可见行为与基线一致、没有 Hook 日志/提示/网络/进程噪声，状态接口仅在有 Hook 时显示有界摘要（证据：相关既有专项测试与 `python -m pytest -q`）。
- [ ] **AC28（N8、N11–N12）：** Windows、Linux、macOS 均实际运行路径规范化、shell stdin、stdout/stderr 上限、超时、取消、后台关闭和进程树终止测试；观察三平台无孤儿进程，核心套件只用 fakes/MockTransport/临时目录且不依赖真实网络、用户配置或危险命令（证据：保存三平台 CI/等价运行记录，命令为 `python -m pytest tests/test_matching.py tests/test_processes.py tests/test_hook_actions.py tests/test_hook_runtime.py tests/test_hook_integration.py -q`）。
- [ ] `asyncio.CancelledError` 在 Provider、工具、command、后台和会话关闭边界完成必要清理后继续传播；普通 Hook 异常被吞掉，既不伪装取消也不改变原 Agent 状态。
- [ ] ContextVar 的 session/turn/run/mode/component/iteration 在普通 Run、独立 Skill、压缩、记忆和并发工具间正确继承且互不串值；退出/取消后下一 Run 观察不到旧作用域。

## 文档、构建与最终回归

- [ ] README 准确说明三层路径与顺序、严格 YAML、11 个事件、事件信封、all/any 条件、exact/glob/regex/negate、四类动作、信任、安全顺序、决策协议、once/background/timeout、诊断与资源限制，并明确本阶段排除项。
- [ ] README 和 `examples/hooks.yaml` 对字段、默认值、超时、决策 JSON、信任范围及 agent placeholder 的描述一致；运行 `rg -n "hooks\.yaml|tool\.before|message\.before|workspace trust|once|background|Hook Context|hooks\.jsonl|agent.*placeholder" README.md`，观察所有主题均命中。
- [ ] Hook、匹配、进程、权限、工具、Provider、Agent、Context、Conversation、Skill、MCP、记忆、session、terminal、REPL 和 CLI 定向测试全部通过，且没有为通过验收而选择性跳过本阶段失败项。
- [ ] 全量测试通过（验证：`python -m pytest -q`，保存用例数、耗时、失败/跳过数和退出码）。
- [ ] 所有源文件和测试可编译（验证：`python -m compileall -q src tests`，观察退出码为 0）。
- [ ] 项目构建成功（验证：`python -m build`）；从生成 wheel 的隔离导入路径导入 `mewcode.hooks` 并读取 `examples/hooks.yaml`（若打包契约包含示例），观察不依赖源码当前目录且无导入副作用。
- [ ] 若项目在实施时存在 lint、format-check 或 type-check 配置，运行对应命令并观察退出码为 0；若仍未配置，最终验收记录明确写明“项目未配置”，不虚构 lint 已通过。
- [ ] `git diff --check` 退出码为 0；对实现差异执行凭据/认证头/原始堆栈泄露审计，观察没有把秘密写入测试快照、日志样例或 README。
- [ ] 最终验收记录包含所有命令和输出摘要、AC1–AC28 状态、三平台状态、未勾选项及原因、已知限制、构建产物烟测和最终 Git 状态；不得用一句“测试通过”替代逐项行为证据。

## 端到端场景

- [ ] **场景 A——三层配置与信任：** 在全新临时工作区同时放置三层规则后启动，先观察无外部动作早于信任提示；拒绝时仅跳过项目共享 command/HTTP，重启保持拒绝；改为信任后按三层声明顺序执行，同时危险命令和权限拒绝仍无法绕过。
- [ ] **场景 B——完整工具轮次与拦截反馈：** 发起需要工具的任务，首个 Provider 请求产生工具调用；tool.before 的前两条规则 allow/失败后，第三条合法 deny，观察工具零调用、剩余 before 短路、一个 denied tool.after、拒绝原因作为 ToolResult 进入第二次 Provider 请求，模型据此调整并完成 turn。
- [ ] **场景 C——提示的下一请求语义：** 从 session.start、turn.start、message.before、tool.after 和 compact.before 排队不同提示，依次让主回复、压缩、记忆更新和独立 Skill 成为下一真实 Provider 请求；观察每段只消费一次、顺序稳定、历史无副本，Provider 失败和 session.end 后也不重放。
- [ ] **场景 D——生命周期失败矩阵：** 在连续会话中制造 Provider 失败、工具失败、权限拒绝、Hook 拒绝、压缩 no-op/失败和调用方取消；观察每个已开始边界恰好一个 after/end、状态准确，只有非 Hook 系统失败产生一次 system.error，随后会话仍可继续。
- [ ] **场景 E——once、后台与关闭：** 并发触发一个首次即失败的 once command，同时启动多条后台 command/HTTP；观察 once 只尝试一次、前台不等待后台、诊断按完成结果更新，退出时在关闭窗口后全部回收且重启可再次触发 once。
- [ ] **场景 F——无 Hook 基线：** 在三个配置文件都缺失时完成普通对话、PLAN→execute、并发工具、权限确认、MCP、共享与独立 Skill、压缩、恢复、记忆和退出；观察与阶段 10 基线相同，文件系统、终端和网络侧均无 Hook 痕迹。
- [ ] **场景 G——资源与隐私压力：** 使用超长嵌套工具参数、接近上限 regex/prompt/输出/HTTP 响应/reason 及超过后台任务上限的输入，观察条件仍用内部完整事件、外发信封带截断标记、所有输出有界、Agent 可继续，任何 API Key、Authorization/Cookie 或隐藏模型内容均未泄露。
