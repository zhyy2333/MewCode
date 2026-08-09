# MewCode 结构化系统提示与提示缓存 Checklist

> 每一项都通过运行测试、捕获请求或执行固定人工场景验证。自动测试不得联网或读取真实 API Key；真实缓存检查单独执行并记录实际条件。

## 2026-08-09 验收执行记录

- [x] AC1–AC19、AC22–AC28 的结构、请求映射、历史边界、错误隔离、文档和范围控制已由 fake/mock 与静态检查验证；完整套件在 Python 3.12.10 下为 `224 passed`，`python -m pytest -W error -q` 同样通过。
- [x] Anthropic 0.97.0 与 OpenAI 2.49.0 的本地 SDK 契约已核对：所用 system 缓存标记、OpenAI 显式断点、缓存选项和缓存 usage 字段均由对应类型或请求签名支持。
- [x] `python -m compileall -q src tests`、依赖约束断言、`git diff --check` 和范围外能力扫描均通过；Provider、提示、Agent/Conversation、REPL 及两组 Provider 端到端筛选测试均通过。
- [x] AC20：不具备真实缓存验证条件。本次未获授权读取真实凭据或产生 API 费用，因此未发送真实请求，未报告缓存命中；模型、前缀长度和原始 usage 留待按 `manual-evaluation.md` 填写。
- [x] AC21：不具备真实缓存验证条件。相同前缀、动态后缀变化和稳定前缀变化已由捕获请求测试验证边界与缓存键行为，但没有用 mock 结果冒充服务端读取或重新写入。
- [ ] 真实模型定性对比尚未执行：改造前基线、Provider/模型、工具轨迹和最终回答需由操作者按 `manual-evaluation.md` 统一条件补录。
- [ ] 工作树清洁项未完全满足：`git status` 中存在受跟踪的 `__pycache__` 改动；这些是本次实现前已存在并会被编译/测试更新的用户工作树内容，验收未回滚、删除或纳入功能实现。

## 提示结构与稳定边界

- [ ] AC1：构建完整提示时，标题严格按“Identity → System Constraints → Task Mode → Action Execution → Tool Use → Tone and Style → Text Output → Environment”出现，模块间恰好一个空行且统一使用 LF。（验证：运行 `python -m pytest tests/test_prompt_builder.py -q -k stable_system`，期望顺序、空行和换行断言全部通过）
- [ ] AC2：不传可选内容时没有空标题；分别传入一个或全部可选内容时，只渲染实际内容，三项同时存在时按“Custom Instructions → Active Skill → Long-Term Memory”排在 Environment 后。（验证：运行 `python -m pytest tests/test_prompt_builder.py -q -k optional_sections`，期望全部组合测试通过）
- [ ] AC3：相同输入重复构建得到字节一致的提示；以不同顺序注册同一组工具时，两家 Provider 输出的工具前缀仍字节一致。（验证：运行 `python -m pytest tests/test_prompt_builder.py tests/test_tool_providers.py -q -k "deterministic or stable_system"`，期望重复构建与乱序注册测试通过）
- [ ] AC4：分别只改变工作区、日期、历史或模式提醒后，捕获请求中的七个稳定模块和工具定义不变，变化仅出现在缓存边界之后。（验证：运行 `python -m pytest tests/test_prompt_builder.py tests/test_providers.py -q -k stable_boundary`，期望四类变化测试通过）
- [ ] AC5：Environment 可观察到工作区、操作系统、日期和 Shell；在进程中放入测试秘密后，提示、事件和终端输出均不包含该值。（验证：运行 `python -m pytest tests/test_prompt_environment.py tests/test_repl.py -q -k "environment or secret"`，期望白名单和秘密隔离测试通过）
- [ ] AC7：动态补充只存在于一个 `<system-reminder>...</system-reminder>` 块中，捕获的模型历史和会话历史都不存在对应 user 消息。（验证：运行 `python -m pytest tests/test_prompt_modes.py tests/test_conversation.py tests/test_providers.py -q -k "system_reminder or real_user_history"`，期望标签与历史边界测试通过）
- [ ] AC8：任务或批准计划包含换行、`</system-reminder>`、相似标签或指令文本时，外层提醒仍完整，固定模块顺序及缓存边界不变。（验证：运行 `python -m pytest tests/test_prompt_modes.py tests/test_prompt_builder.py -q -k escaping`，期望恶意边界输入测试通过）
- [ ] AC15：同一对话的工具循环和后续用户轮次共享相同稳定前缀，新增消息只追加在稳定边界之后。（验证：运行 `python -m pytest tests/test_agent_runner.py tests/test_conversation.py -q -k stable_prefix`，期望跨迭代与跨轮次捕获请求测试通过）
- [ ] AC23：调用方传入自定义指令、Skill 内容和长期记忆时三者参与正确排序；不传入时程序不扫描文件、不激活 Skill、不创建记忆。（验证：运行 `python -m pytest tests/test_prompt_builder.py tests/test_conversation.py -q -k "prompt_additions or no_discovery"`，期望显式入口和默认无副作用测试通过）
- [ ] 统一提示语义只有一个构建入口，Anthropic 与 OpenAI 捕获请求使用同一稳定块和动态块，不各自维护业务提示副本。（验证：运行 `python -m pytest tests/test_providers.py tests/test_tool_providers.py -q -k prompt_parity`，期望双 Provider 语义一致性测试通过）

## 模式提醒与工具边界

- [ ] AC9：一次包含 20 次模型调用的 Agent Run 中，完整提醒只出现在第 1、5、9、13、17 次，其余为精简提醒；第二个 Agent Run 从第 1 次重新开始。（验证：运行 `python -m pytest tests/test_prompt_modes.py tests/test_agent_runner.py -q -k cadence`，期望两次运行的完整序列测试通过）
- [ ] AC10：Plan 和 Execute 的完整提醒都包含目标、允许动作、禁止动作、完成条件和输出要求；精简提醒只包含模式、关键边界和继续执行目标。（验证：运行 `python -m pytest tests/test_prompt_modes.py -q -k "full_reminder or concise_reminder"`，期望内容集合测试通过）
- [ ] Direct Mode 不额外注入动态模式提醒，但仍包含统一固定模块和 Environment。（验证：运行 `python -m pytest tests/test_agent_runner.py -q -k direct_prompt`，期望动态提醒为空且固定提示存在）
- [ ] AC11：Plan Mode 的完整与精简提醒都明确只读；模型请求只暴露读取、查找、搜索工具，不暴露写入、编辑或命令工具。（验证：运行 `python -m pytest tests/test_plan_mode.py -q -k readonly`，期望 20 次提醒内容与实际工具集合测试通过）
- [ ] Plan 最终化通过系统级阶段提醒完成，不新增伪造 user 消息；该次请求不提供工具，也不把调查文本作为末尾 assistant prefill。（验证：运行 `python -m pytest tests/test_plan_mode.py -q -k "finalization_system or no_assistant_prefill"`，期望历史角色、末尾消息和无工具断言通过）
- [ ] AC12：执行固定“查找文件后修改已有内容”场景时，轨迹首先使用 find/search/read 专用工具；仅在模拟专用工具无法完成时才出现命令工具回退。（验证：按 `manual-evaluation.md` 的“专用搜索优先”场景分别执行正常与回退版本，记录完整工具轨迹并对照通过条件）
- [ ] AC13：修改已有文件场景中，针对相关内容的读取发生在首次编辑之前；新建文件场景不要求读取不存在的目标。（验证：按 `manual-evaluation.md` 的“先读后改”场景执行已有文件和新文件两个变体，记录调用顺序并对照通过条件）
- [ ] AC14：全局 Tool Use 模块和相关工具描述都能观察到专用工具优先与编辑前读取规则，同时六个工具的参数、结果格式和安全分类未改变。（验证：运行 `python -m pytest tests/test_prompt_builder.py tests/test_tools_base.py -q -k tool_rules`，期望双重规则和工具接口回归测试通过）

## Provider 请求与缓存统计

- [ ] AC6：同一上层请求分别映射到 Anthropic 与 OpenAI 后，稳定指令、动态补充、工具规则和历史语义等价，并分别使用各自的 system 结构。（验证：运行 `python -m pytest tests/test_providers.py tests/test_tool_providers.py -q -k prompt_parity`，期望捕获请求对比通过）
- [ ] Anthropic 官方地址的稳定 system 块带缓存断点、动态 system 块位于其后且不带断点；工具定义在稳定缓存前缀中按名称排序。（验证：运行 `python -m pytest tests/test_providers.py tests/test_tool_providers.py -q -k "anthropic and (cache_breakpoint or stable_prefix)"`，期望缓存位置和工具顺序测试通过）
- [ ] Anthropic 非官方兼容地址不发送缓存扩展，并以普通 system 形式保持相同提示语义。（验证：运行 `python -m pytest tests/test_providers.py -q -k "anthropic and compatible_host"`，期望兼容请求无未知缓存字段且内容完整）
- [ ] OpenAI 官方 GPT-5.6 系列请求在稳定 system `input_text` 末尾设置显式断点，发送 explicit 模式和稳定缓存键，动态 system 与历史位于断点之后。（验证：运行 `python -m pytest tests/test_providers.py -q -k "openai and explicit_cache"`，期望断点、模式、缓存键和顺序断言通过）
- [ ] OpenAI 缓存键不含任务、路径、提示正文或凭据；动态内容和注册顺序变化不改变键，模型、稳定提示或工具变化会改变键。（验证：运行 `python -m pytest tests/test_providers.py tests/test_tool_providers.py -q -k "openai and cache_key"`，期望确定性、变更敏感性和无明文测试通过）
- [ ] OpenAI 旧模型和非官方兼容地址不发送显式缓存字段，但仍保持稳定 system 前缀并可依赖自动缓存。（验证：运行 `python -m pytest tests/test_providers.py -q -k "openai and automatic_cache_fallback"`，期望兼容请求和原流式行为测试通过）
- [ ] AC16：模拟 Anthropic 缓存创建/读取字段和 OpenAI 缓存写入/读取字段时，统一统计分别得到相同语义的 `cache-write` 与 `cache-read` 值。（验证：运行 `python -m pytest tests/test_providers.py -q -k cache_usage`，期望两家字段映射测试通过）
- [ ] AC17：供应商未提供缓存字段时终端显示不可用，明确返回零时显示 `0`，两者在单次和累计值中均不混淆。（验证：运行 `python -m pytest tests/test_providers.py tests/test_stream_collector.py tests/test_repl.py -q -k "cache_usage or cache_tokens"`，期望 `None` 与零的所有断言通过）
- [ ] AC18：连续两次响应返回不同缓存值时，每次 Token 事件显示本次值，停止结果和终端显示正确累计值，原 input/output/total 数值不变。（验证：运行 `python -m pytest tests/test_agent_runner.py tests/test_stream_collector.py tests/test_repl.py -q -k cache_usage`，期望当前值、累计值和旧口径测试通过）
- [ ] REPL Token 行严格包含 `in`、`out`、`total`、`cache-read`、`cache-write`、`cumulative`、`cumulative-cache-read`、`cumulative-cache-write`，且只产生一条可读统计行。（验证：运行 `python -m pytest tests/test_repl.py -q -k token_output`，期望完整格式和事件唯一性测试通过）
- [ ] AC19：fake/mock 捕获到的两家请求具有各自正确的缓存标记和边界；自动测试未访问网络、未读取真实 API Key、未产生真实缓存费用。（验证：清空相关 API Key 的测试环境后运行 `python -m pytest tests/test_providers.py tests/test_tool_providers.py -q`，期望测试全部通过且网络 fake 没有未消费请求）
- [ ] AC20：按人工说明使用支持缓存且稳定前缀达到要求的真实模型重复请求时，记录实际缓存写入或后续读取字段；模型、长度、凭据或服务端条件不足时明确记录“无法验证”，不报告命中。（验证：执行 `manual-evaluation.md` 的真实缓存检查，保存模型、前缀长度、请求条件和原始 usage 摘要）
- [ ] AC21：真实验证中只改变稳定边界后的用户消息或动态提醒时，记录稳定前缀的读取结果；改变固定指令或工具定义后，记录失效或重新写入结果。（验证：连续执行 `manual-evaluation.md` 的“相同前缀、动态变化、稳定变化”三组请求并对比 usage；无法满足条件时记录原因）

## 会话、流式事件与错误隔离

- [ ] AC24：普通问答仍即时流式输出并进入后续轮次历史，第二轮能看到第一轮真实对话。（验证：运行 `python -m pytest tests/test_conversation.py -q -k "ask or history or context"`，期望普通多轮测试通过）
- [ ] AC24：Direct 工具执行、多轮工具循环和原有停止原因继续工作，工具调用、结果和 assistant continuation 顺序不变。（验证：运行 `python -m pytest tests/test_agent_runner.py tests/test_tool_conversation.py -q`，期望 Agent 与工具会话全部通过）
- [ ] AC24：`/plan` 完成只读调查和无工具最终化并保存计划；`/do` 使用完整工具集合执行批准计划，成功清除、失败或取消保留。（验证：运行 `python -m pytest tests/test_plan_mode.py -q`，期望完整 Plan/Execute 生命周期测试通过）
- [ ] `/plan` 历史只保存原任务 user 消息，`/do` 历史只保存真实动作；原任务、批准计划和模式提醒不被伪装成新的 user 消息。（验证：运行 `python -m pytest tests/test_plan_mode.py tests/test_conversation.py -q -k history`，期望所有角色和内容边界断言通过）
- [ ] AC25：Provider 发出第一个文本增量后立即出现文本事件，不等待 usage、工具执行、完整响应或 Agent Run 结束。（验证：运行 `python -m pytest tests/test_stream_collector.py tests/test_agent_runner.py -q -k immediate_text`，期望受控事件门证明首个增量先到达）
- [ ] AC26：分别模拟缓存字段缺失、动态提醒、标签攻击、Provider 流错误和取消时，REPL 保持可用且不输出 Provider 对象、隐藏推理、API Key 或测试秘密。（验证：运行 `python -m pytest tests/test_repl.py tests/test_agent_runner.py tests/test_prompt_modes.py -q -k "cache or reminder or escaping or error or cancel or redacted"`，期望无崩溃和无泄露断言通过）
- [ ] 提示构建或缓存解析不改变现有迭代上限、未知工具限制、工具调度、取消、流错误和输出截断行为。（验证：运行 `python -m pytest tests/test_agent_runner.py tests/test_tool_scheduler.py -q`，期望全部既有停止与调度测试通过）

## 人工评估与端到端场景

- [ ] AC22：`manual-evaluation.md` 至少包含“先读后改、专用搜索优先、Plan Mode 禁止写入、动态内容不破坏稳定前缀、系统提醒不被当作用户问题”五个固定场景。（验证：运行 `rg -n "先读后改|专用搜索|Plan Mode|稳定前缀|系统提醒" docs/phase-4-prompt-architecture/manual-evaluation.md`，期望五个标题均命中）
- [ ] AC22：每个人工场景都列出固定输入、Provider、模型、工具轨迹观察点和通过条件，前后对比使用同一条件。（验证：逐节检查 `manual-evaluation.md` 并填写一次空白记录模板，期望每个必填字段都有明确位置）
- [ ] AC12-AC13：执行“先读后改”和“专用搜索优先”场景后，记录的工具轨迹满足先读后改、专用工具优先和有条件回退要求。（验证：按文档运行场景并将实际调用顺序与通过条件逐项对照）
- [ ] AC11：执行 Plan Mode 禁写场景时，所有调用均来自读取、查找、搜索工具，工作区内容和 Git diff 在场景前后完全相同。（验证：场景前后运行 `git diff -- . ':!docs/phase-4-prompt-architecture/manual-evaluation.md'` 并保存对比，同时记录工具轨迹）
- [ ] AC15、AC21：执行动态环境变化场景时，捕获的稳定提示与工具前缀字节一致；若执行真实请求，同时记录缓存读取结果或无法验证原因。（验证：按文档导出两次请求摘要并比较稳定前缀哈希及 usage）
- [ ] AC7、AC24：执行普通问答场景时，模型回答用户问题，不复述或单独回答系统提醒；保存历史只包含真实 user/assistant 语义。（验证：记录最终回答和会话历史摘要并对照文档通过条件）
- [ ] 端到端：使用 fake Provider 从 `/plan <任务>` 经过多轮只读调查、系统级最终化、保存计划，再通过 `/do` 多轮调用工具完成并清除计划；每次请求遵循提醒节奏并贯通缓存统计。（验证：运行 `python -m pytest tests/test_plan_mode.py tests/test_repl.py -q -k end_to_end`，期望完整链路测试通过）
- [ ] 端到端：分别以 Anthropic 和 OpenAI fake 响应走完“用户输入 → 统一提示包 → Provider 请求 → 文本/工具事件 → 缓存用量 → REPL”链路，得到等价上层行为。（验证：运行 `python -m pytest tests/test_providers.py tests/test_agent_runner.py tests/test_repl.py -q -k provider_end_to_end`，期望两个参数化场景通过）

## 编译、测试与范围控制

- [ ] AC27：全部源码和测试可在当前 Python 3.11+ 环境编译，无语法或导入错误。（验证：运行 `python --version` 确认为 3.11 或更高，再运行 `python -m compileall -q src tests`，期望命令以 0 退出）
- [ ] AC27：提示构建、Provider、工具、Agent、Conversation、REPL 的新增与既有测试全部通过。（验证：运行 `python -m pytest -q`，期望零失败）
- [ ] 完整测试在 warning-as-error 模式下没有本阶段引入的未关闭流、遗留异步任务或弃用警告。（验证：运行 `python -m pytest -W error -q`；若仅有既有第三方警告，记录来源并单独判定）
- [ ] `pyproject.toml` 要求 Python 3.11+，缓存所需 SDK 下限为 `openai>=2.49.0` 与 `anthropic>=0.97.0`，且没有新增第三方依赖。（验证：运行 `python -c "import tomllib, pathlib; d=tomllib.loads(pathlib.Path('pyproject.toml').read_text()); assert d['project']['requires-python'] == '>=3.11'; assert set(d['project']['dependencies']) == {'openai>=2.49.0','anthropic>=0.97.0','PyYAML'}"`，期望命令以 0 退出）
- [ ] 现有配置文件没有新增必填字段；不提供三个可选模块时 CLI 能按默认提示启动。（验证：清空可选内容后运行配置与 CLI 测试 `python -m pytest tests/test_config.py tests/test_repl.py -q -k "config or main"`，期望全部通过）
- [ ] AC28：源码中没有项目指令文件发现、Skill 自动激活、长期记忆生成或持久化、真实 MCP 接入、缓存预热、费用计算或自动评分系统。（验证：检查最终 `git diff -- src tests`，并运行 `rg -n "AGENTS\.md|activate_skill|persist_memory|cache_warm|cost_savings|auto.*score" src`；期望无范围外实现命中）
- [ ] README 明确说明结构化提示、1/5/9/13/17 提醒节奏、缓存统计、缓存不保证命中及本阶段边界。（验证：运行 `rg -n "system-reminder|cache-read|cache-write|1, 5, 9, 13, 17|Skill|MCP" README.md`，期望所有主题均命中）
- [ ] `manual-evaluation.md` 的真实 OpenAI 验证步骤与官方 Prompt Caching 文档一致：显式断点位于稳定前缀末尾，并记录 `cached_tokens` 与 `cache_write_tokens`。（验证：对照 OpenAI 官方文档逐项审阅请求字段和 usage 字段）
- [ ] `git diff --check` 无尾随空格或空白错误，且没有修改或提交密钥、用户配置、`__pycache__` 或无关文件。（验证：运行 `git diff --check` 和 `git status --short`，逐项核对输出）
- [ ] `docs/phase-4-prompt-architecture/` 包含已批准的 `spec.md`、`plan.md`、`task.md`、`checklist.md` 以及实施产物 `manual-evaluation.md`。（验证：运行 `Get-ChildItem docs/phase-4-prompt-architecture | Select-Object -ExpandProperty Name`，期望五个文件均存在）
- [ ] 对照 AC1–AC28 全部取得通过证据或按 AC20/AC21 明确记录真实 API 条件不足后，才宣布本阶段完成。（验证：检查本文件每个 AC 编号至少有一个已勾选条目，并附测试输出、请求摘要或人工观察记录）
