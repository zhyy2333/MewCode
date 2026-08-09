# MewCode 结构化系统提示与提示缓存 Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 新建 | `src/mewcode/prompting/__init__.py` | 提示构建公共出口 |
| 新建 | `src/mewcode/prompting/models.py` | 提示稳定性、模块、环境、可选内容、运行上下文和提示包模型 |
| 新建 | `src/mewcode/prompting/sections.py` | 固定模块注册表、优先级和稳定控制文本 |
| 新建 | `src/mewcode/prompting/environment.py` | 环境白名单采集和安全渲染 |
| 新建 | `src/mewcode/prompting/modes.py` | 模式提醒、阶段切换、注入频率和标签包装 |
| 新建 | `src/mewcode/prompting/builder.py` | 稳定块与动态块的统一排序和渲染 |
| 修改 | `src/mewcode/providers/base.py` | 统一 `ModelRequest` 接口与缓存 Token 字段 |
| 修改 | `src/mewcode/providers/__init__.py` | 导出统一请求与扩展用量类型 |
| 修改 | `src/mewcode/providers/anthropic_provider.py` | Anthropic system 块、缓存断点、工具序列化和缓存用量映射 |
| 修改 | `src/mewcode/providers/openai_provider.py` | OpenAI system 输入、显式缓存、缓存键、兼容回退和缓存用量映射 |
| 修改 | `src/mewcode/agent/runner.py` | 按真实模型调用次数构建提示、阶段切换和统一请求发送 |
| 修改 | `src/mewcode/conversation.py` | 真实用户历史、可选内容入口与 Plan/Execute 动态上下文 |
| 修改 | `src/mewcode/repl.py` | 单次及累计缓存 Token 展示 |
| 修改 | `src/mewcode/cli.py` | 环境提供器、提示构建器与会话依赖组装 |
| 修改 | `src/mewcode/tools/base.py` | 移除 Provider JSON 职责并保留稳定工具访问入口 |
| 修改 | `src/mewcode/tools/file_tools.py` | 强化读、写、编辑工具的先读后改规则 |
| 修改 | `src/mewcode/tools/search_tools.py` | 强化专用查找与搜索优先规则 |
| 修改 | `src/mewcode/tools/command_tool.py` | 将命令工具明确限定为专用工具无法完成时的回退 |
| 修改 | `tests/fakes.py` | 记录统一模型请求的可控 Provider 替身 |
| 新建 | `tests/test_prompt_builder.py` | 模块排序、稳定边界、可选内容和确定性测试 |
| 新建 | `tests/test_prompt_environment.py` | 环境白名单、平台回退和秘密隔离测试 |
| 新建 | `tests/test_prompt_modes.py` | 完整/精简提醒、频率、阶段和转义测试 |
| 修改 | `tests/test_providers.py` | Provider system 请求、缓存能力与缓存用量测试 |
| 修改 | `tests/test_tool_providers.py` | 双 Provider 工具序列化、缓存前缀和语义一致性测试 |
| 修改 | `tests/test_tools_base.py` | 注册顺序独立性、公共接口和工具描述测试 |
| 修改 | `tests/test_agent_runner.py` | 每次调用提示构建、计数重置和缓存累计测试 |
| 修改 | `tests/test_plan_mode.py` | Plan 提醒、只读边界、最终化和计划执行测试 |
| 修改 | `tests/test_conversation.py` | 真实用户历史和可选模块入口测试 |
| 修改 | `tests/test_tool_conversation.py` | 统一请求接入后的多轮工具回归测试 |
| 修改 | `tests/test_stream_collector.py` | 缓存 Token 当前值与未知值累计测试 |
| 修改 | `tests/test_repl.py` | 新 Token 行、CLI 组装和无敏感信息测试 |
| 修改 | `pyproject.toml` | 固定支持缓存字段的最低 SDK 版本 |
| 修改 | `README.md` | 结构化提示、缓存观测与边界说明 |
| 新建 | `docs/phase-4-prompt-architecture/manual-evaluation.md` | 真实缓存验证与五类人工定性场景 |

## T1：定义提示领域模型

**文件：** `src/mewcode/prompting/models.py`、`src/mewcode/prompting/__init__.py`、`tests/test_prompt_builder.py`

**依赖：** 无

**步骤：**

1. 定义 `PromptStability`、`PromptSectionSpec`、`PromptEnvironment`、`PromptAdditions`、`PromptRunContext`、`PromptPhase` 和 `PromptPackage`。
2. 使用不可变默认值表达空的可选内容，并从 `prompting` 包导出公共类型。
3. 增加构造、默认值和枚举测试，确保字段名与 `plan.md` 一致。

**验证：** 运行 `python -m pytest tests/test_prompt_builder.py -q -k prompt_models`，期望提示模型的构造和默认值测试全部通过。

## T2：建立固定模块注册表

**文件：** `src/mewcode/prompting/sections.py`、`tests/test_prompt_builder.py`

**依赖：** T1

**步骤：**

1. 按 100–700 的优先级注册身份、系统约束、任务模式、动作执行、工具使用、语气风格和文本输出七个稳定模块。
2. 按 800–1100 注册环境、自定义指令、已激活 Skill 和长期记忆四个动态模块。
3. 写入英文固定控制文本，并在全局工具规则中明确专用工具优先和编辑已有文件前先读。

**验证：** 运行 `python -m pytest tests/test_prompt_builder.py -q -k section_registry`，期望模块 key、标题、优先级、稳定性和关键规则测试全部通过。

## T3：实现环境白名单采集

**文件：** `src/mewcode/prompting/environment.py`、`tests/test_prompt_environment.py`

**依赖：** T1

**步骤：**

1. 从工作区、平台、注入时钟和 Shell 来源构造 `PromptEnvironment`。
2. Windows 固定渲染 `PowerShell`，其他平台使用 Shell basename，缺失信息使用明确的 unknown 回退。
3. 只输出工作区、操作系统、日期和 Shell，不读取或遍历环境变量值。

**验证：** 运行 `python -m pytest tests/test_prompt_environment.py -q`，期望白名单、固定日期、跨平台回退和秘密隔离测试全部通过。

## T4：实现模式提醒频率

**文件：** `src/mewcode/prompting/modes.py`、`tests/test_prompt_modes.py`

**依赖：** T1

**步骤：**

1. 为 Plan 和 Execute 模式提供完整与精简提醒模板，Direct Mode 返回空提醒。
2. 用 `(iteration - 1) % 4 == 0` 判定完整提醒，使 1、5、9、13、17 次为完整版本。
3. 完整版本覆盖目标、允许动作、禁止动作、完成条件和输出要求；精简版本保留模式、关键边界和继续目标。

**验证：** 运行 `python -m pytest tests/test_prompt_modes.py -q -k cadence`，期望 1–20 次调用的完整/精简序列与新运行重置测试通过。

## T5：实现系统提醒安全包装

**文件：** `src/mewcode/prompting/modes.py`、`tests/test_prompt_modes.py`

**依赖：** T4

**步骤：**

1. 实现 `wrap_system_reminder()`，统一生成单个 `<system-reminder>` 外层边界。
2. 对插入提醒的任务和批准计划做 XML 转义，阻止伪造闭合标签。
3. 为 `PromptPhase.ACTIVE` 与 `PLAN_FINALIZATION` 生成不同目标，且两个 Plan 阶段都保留只读约束。

**验证：** 运行 `python -m pytest tests/test_prompt_modes.py -q -k "wrapper or escaping or finalization"`，期望标签边界、恶意文本转义和阶段切换测试全部通过。

## T6：渲染稳定提示块

**文件：** `src/mewcode/prompting/builder.py`、`tests/test_prompt_builder.py`

**依赖：** T1、T2

**步骤：**

1. 实现 `PromptBuilder` 的集中排序和 Markdown 二级标题渲染。
2. 将七个稳定模块合并到 `PromptPackage.stable_system`，统一使用 LF 且模块间恰好一个空行。
3. 保证构建器不依赖 Provider、Agent、Conversation 或具体工具实现。

**验证：** 运行 `python -m pytest tests/test_prompt_builder.py -q -k stable_system`，期望稳定模块顺序、标题、空行和重复构建字节一致性测试通过。

## T7：渲染动态提示块与可选内容

**文件：** `src/mewcode/prompting/builder.py`、`tests/test_prompt_builder.py`

**依赖：** T3、T5、T6

**步骤：**

1. 在动态块中依次渲染环境、自定义指令、已激活 Skill、长期记忆和当次模式提醒。
2. 空白可选内容完全省略，非空内容保持调用方原文，不做发现、激活、生成或持久化。
3. 验证只改变环境、可选内容或提醒时，稳定块保持字节不变。

**验证：** 运行 `python -m pytest tests/test_prompt_builder.py -q -k "dynamic_system or optional_sections or stable_boundary"`，期望动态排序、省略规则和稳定边界测试全部通过。

## T8：固定 Provider SDK 最低版本

**文件：** `pyproject.toml`

**依赖：** 无

**步骤：**

1. 将依赖下限设置为 `openai>=2.49.0` 和 `anthropic>=0.97.0`。
2. 保持 Python 版本、PyYAML 和开发依赖不变，不引入其他第三方包。

**验证：** 运行 `python -c "import tomllib, pathlib; d=tomllib.loads(pathlib.Path('pyproject.toml').read_text()); assert 'openai>=2.49.0' in d['project']['dependencies']; assert 'anthropic>=0.97.0' in d['project']['dependencies']"`，期望命令以 0 退出。

## T9：引入统一模型请求接口

**文件：** `src/mewcode/providers/base.py`、`src/mewcode/providers/__init__.py`、`tests/fakes.py`、`tests/test_providers.py`

**依赖：** T1

**步骤：**

1. 定义 `ModelRequest(prompt, messages, tools, max_output_tokens)`，其中历史使用 tuple，工具使用 `ToolRegistry | None`。
2. 将 `LLMProvider.stream_reply()` 改为只接收 `ModelRequest`，删除公共 `tool_definitions()` 协议。
3. 更新公共出口和 fake Provider，使其逐次保存完整请求供 Agent 与 Conversation 测试断言。

**验证：** 运行 `python -m pytest tests/test_providers.py -q -k model_request`，期望统一请求构造、不可变历史和 Provider 协议测试通过。

## T10：扩展统一缓存 Token 用量

**文件：** `src/mewcode/providers/base.py`、`tests/test_providers.py`、`tests/test_stream_collector.py`

**依赖：** T9

**步骤：**

1. 为 `TokenUsage` 增加可空的 `cache_read_tokens` 与 `cache_write_tokens`。
2. 扩展 `zero()` 和 `add()`，严格区分缺失 `None` 与明确零 `0`，并保持原输入、输出、总量口径。
3. 验证流收集器继续立即转发文本，并正确生成当前与累计缓存用量。

**验证：** 运行 `python -m pytest tests/test_providers.py tests/test_stream_collector.py -q -k "cache_usage or token_usage"`，期望零值、未知值传播和累计测试全部通过。

## T11：将工具序列化收归 Provider

**文件：** `src/mewcode/tools/base.py`、`src/mewcode/providers/anthropic_provider.py`、`src/mewcode/providers/openai_provider.py`、`tests/test_tools_base.py`、`tests/test_tool_providers.py`

**依赖：** T9

**步骤：**

1. 从 `ToolRegistry` 移除公开的 Anthropic/OpenAI JSON 转换职责，提供 Provider 可读取的稳定工具对象视图。
2. 在两个 Provider 内分别生成协议工具 JSON，并仅在序列化时按工具名排序。
3. 保持注册、选择、执行和工具结果顺序不变，验证不同注册顺序产生相同 Provider 工具定义。

**验证：** 运行 `python -m pytest tests/test_tools_base.py tests/test_tool_providers.py -q -k "tool_serialization or deterministic_tools"`，期望双 Provider 格式、稳定排序和注册表行为测试通过。

## T12：强化具体工具描述

**文件：** `src/mewcode/tools/file_tools.py`、`src/mewcode/tools/search_tools.py`、`src/mewcode/tools/command_tool.py`、`tests/test_tools_base.py`

**依赖：** T2

**步骤：**

1. 在读取、写入和编辑工具描述中说明编辑已有文件前必须读取，新建文件无需预读。
2. 在查找和搜索工具描述中说明应优先于通用命令完成等价操作。
3. 将命令工具限定为专用工具无法完成时的回退，不修改参数 Schema、结果格式或安全分类。

**验证：** 运行 `python -m pytest tests/test_tools_base.py -q -k tool_descriptions`，期望双重强化规则存在且六个工具接口保持不变。

## T13：映射 Anthropic 系统提示

**文件：** `src/mewcode/providers/anthropic_provider.py`、`tests/test_providers.py`

**依赖：** T7、T9、T11

**步骤：**

1. 将统一请求映射为 Anthropic Messages API 参数，历史继续使用原生消息结构。
2. 官方 Anthropic 地址使用两个顶层 system 文本块：稳定块在前、动态块在后。
3. 动态块为空时不产生空内容块，且系统内容不作为 user 消息出现。

**验证：** 运行 `python -m pytest tests/test_providers.py -q -k "anthropic and system_blocks"`，期望 system 层级、块顺序、空动态块和历史语义测试通过。

## T14：实现 Anthropic 缓存断点与兼容回退

**文件：** `src/mewcode/providers/anthropic_provider.py`、`tests/test_providers.py`、`tests/test_tool_providers.py`

**依赖：** T13

**步骤：**

1. 对官方地址的稳定 system 块添加 `cache_control: {type: ephemeral}`，动态块不添加断点。
2. 保证工具定义位于 Anthropic 缓存前缀顺序中，并在工具或稳定提示不变时保持请求前缀一致。
3. 对非官方兼容地址发送普通拼接 system，不发送缓存扩展字段。

**验证：** 运行 `python -m pytest tests/test_providers.py tests/test_tool_providers.py -q -k "anthropic and (cache_breakpoint or compatible_host or stable_prefix)"`，期望官方缓存标记、前缀稳定和兼容回退测试通过。

## T15：解析 Anthropic 缓存用量

**文件：** `src/mewcode/providers/anthropic_provider.py`、`tests/test_providers.py`

**依赖：** T10、T14

**步骤：**

1. 将 `cache_read_input_tokens` 映射为统一缓存读取量。
2. 将 `cache_creation_input_tokens` 映射为统一缓存写入量。
3. 缺失字段保留 `None`，明确零保留 `0`，常规 total 继续按输入加输出计算。

**验证：** 运行 `python -m pytest tests/test_providers.py -q -k "anthropic and cache_usage"`，期望缓存读写、缺失值、零值和常规 Token 测试通过。

## T16：映射 OpenAI 系统输入

**文件：** `src/mewcode/providers/openai_provider.py`、`tests/test_providers.py`

**依赖：** T7、T9、T11

**步骤：**

1. 将稳定提示放在 Responses API input 首部的 system `input_text` 内容块。
2. 将动态提示作为其后的独立 system 消息，再追加原有历史与 continuation items。
3. 动态块为空时省略空消息，并确保提醒没有 user 语义。

**验证：** 运行 `python -m pytest tests/test_providers.py -q -k "openai and system_input"`，期望 system 顺序、空动态块和历史 continuation 回归测试通过。

## T17：启用 OpenAI GPT-5.6 显式缓存

**文件：** `src/mewcode/providers/openai_provider.py`、`tests/test_providers.py`

**依赖：** T16

**步骤：**

1. 仅在 hostname 为 `api.openai.com` 且模型名以 GPT-5.6 系列前缀开头时启用显式缓存。
2. 在稳定 system `input_text` 末尾添加 `prompt_cache_breakpoint`，并发送 `prompt_cache_options={"mode": "explicit"}`。
3. 验证动态 system 和历史位于断点之后，变化时不改写断点前内容。

**验证：** 运行 `python -m pytest tests/test_providers.py -q -k "openai and explicit_cache"`，期望能力判断、显式断点、模式参数和稳定边界测试通过。

## T18：生成稳定 OpenAI 缓存键

**文件：** `src/mewcode/providers/openai_provider.py`、`tests/test_providers.py`、`tests/test_tool_providers.py`

**依赖：** T11、T17

**步骤：**

1. 用模型、稳定提示和按名称排序的规范化工具 JSON 生成 SHA-256 摘要。
2. 以 `mewcode:` 前缀发送 `prompt_cache_key`，键中不包含原始提示、任务、路径或凭据。
3. 验证注册顺序和动态内容变化不改变键，稳定指令、模型或工具变化会改变键。

**验证：** 运行 `python -m pytest tests/test_providers.py tests/test_tool_providers.py -q -k "openai and cache_key"`，期望缓存键确定性、变更敏感性和无明文泄露测试通过。

## T19：实现 OpenAI 旧模型与兼容地址回退

**文件：** `src/mewcode/providers/openai_provider.py`、`tests/test_providers.py`

**依赖：** T16

**步骤：**

1. 对旧模型和非官方地址保留相同的稳定 system 前缀顺序。
2. 不发送 `prompt_cache_breakpoint`、`prompt_cache_options` 或 `prompt_cache_key` 等显式缓存字段。
3. 保持现有 Responses API 流式错误、取消和兼容行为不变。

**验证：** 运行 `python -m pytest tests/test_providers.py -q -k "openai and automatic_cache_fallback"`，期望旧模型与兼容地址请求不含显式字段且原有流行为通过。

## T20：解析 OpenAI 缓存用量

**文件：** `src/mewcode/providers/openai_provider.py`、`tests/test_providers.py`

**依赖：** T10、T16

**步骤：**

1. 从 `input_tokens_details.cached_tokens` 映射统一缓存读取量。
2. 从 `input_tokens_details.cache_write_tokens` 映射统一缓存写入量。
3. 缺失字段保留 `None`，明确零保留 `0`，常规 total 继续采用 API 返回值。

**验证：** 运行 `python -m pytest tests/test_providers.py -q -k "openai and cache_usage"`，期望缓存读写、缺失值、零值和 total 口径测试通过。

## T21：验证双 Provider 提示语义一致性

**文件：** `tests/test_providers.py`、`tests/test_tool_providers.py`

**依赖：** T14、T15、T18、T19、T20

**步骤：**

1. 用同一 `ModelRequest` 捕获 Anthropic 与 OpenAI 请求。
2. 对比稳定指令、动态提醒、历史、工具名称和关键描述的语义与顺序。
3. 验证供应商特有缓存字段只存在于各自适配层，fake 测试不访问网络。

**验证：** 运行 `python -m pytest tests/test_providers.py tests/test_tool_providers.py -q -k prompt_parity`，期望双 Provider 语义等价和协议隔离测试通过。

## T22：向 AgentRunner 注入提示构建上下文

**文件：** `src/mewcode/agent/runner.py`、`tests/test_agent_runner.py`、`tests/fakes.py`

**依赖：** T7、T9

**步骤：**

1. 为 `AgentRunner` 增加可注入 `PromptBuilder`，为 `start()` 增加可选 `PromptRunContext`。
2. 未传上下文时从真实用户任务构造默认上下文，保持现有直接调用方兼容。
3. 让 Runner 向 Provider 发送 `ModelRequest`，不再提前持有 Provider 工具 JSON。

**验证：** 运行 `python -m pytest tests/test_agent_runner.py -q -k "prompt_context or model_request"`，期望默认上下文、显式上下文和统一请求捕获测试通过。

## T23：按实际模型调用构建提示

**文件：** `src/mewcode/agent/runner.py`、`tests/test_agent_runner.py`

**依赖：** T22

**步骤：**

1. 在每次 `stream_reply()` 之前调用 `PromptBuilder.build()`，iteration 使用当前 Agent Run 的真实 Provider 调用次数。
2. 多轮工具循环中依次注入完整或精简提醒；新建 Agent Run 时从 1 重新计数。
3. Direct Mode 不增加动态模式提醒，但仍发送统一稳定提示和环境块。

**验证：** 运行 `python -m pytest tests/test_agent_runner.py -q -k "prompt_cadence or direct_prompt or run_reset"`，期望多轮 1/5/9 节奏、Direct 行为和跨运行重置测试通过。

## T24：以系统阶段完成 Plan 最终化

**文件：** `src/mewcode/agent/runner.py`、`tests/test_plan_mode.py`

**依赖：** T5、T23

**步骤：**

1. 删除 `PLAN_FINAL_PROMPT` 伪造用户消息，改用 `PromptPhase.PLAN_FINALIZATION` 构建动态系统提醒。
2. 最终化调用使用 `tools=None`，调查阶段继续只传只读工具集合。
3. 保存调查阶段完整 assistant 响应到最终历史，但最终化工作消息不以该 assistant 文本作为末尾 prefill。

**验证：** 运行 `python -m pytest tests/test_plan_mode.py -q -k "finalization_system or no_assistant_prefill or readonly_tools"`，期望无伪用户消息、无末尾 prefill、阶段目标和工具边界测试通过。

## T25：累计并传递缓存 Token

**文件：** `src/mewcode/agent/runner.py`、`tests/test_agent_runner.py`、`tests/test_stream_collector.py`

**依赖：** T10、T23

**步骤：**

1. 让每次 `AgentTokenUsage` 携带扩展后的 current 与 cumulative 用量。
2. 在跨迭代累计和最终 `AgentStopped`/outcome 中保留缓存读写字段及未知语义。
3. 验证文本增量仍在完整响应和用量事件之前即时发出。

**验证：** 运行 `python -m pytest tests/test_agent_runner.py tests/test_stream_collector.py -q -k "cache_usage or immediate_text"`，期望单次、累计、停止结果和实时文本测试通过。

## T26：接入 Conversation 可选内容与普通问答

**文件：** `src/mewcode/conversation.py`、`tests/test_conversation.py`

**依赖：** T22、T23

**步骤：**

1. 为 `Conversation` 构造参数增加 `PromptAdditions`，默认三个可选模块均为空。
2. 普通 `ask()` 只提交真实用户消息，并通过 `PromptRunContext` 将调用方内容交给 Runner。
3. 验证不传内容时不扫描项目指令、不激活 Skill、不生成记忆，系统块也不进入会话历史。

**验证：** 运行 `python -m pytest tests/test_conversation.py -q -k "prompt_additions or real_user_history or no_discovery"`，期望可选入口、默认行为和历史隔离测试通过。

## T27：迁移 Plan 会话语义

**文件：** `src/mewcode/conversation.py`、`tests/test_plan_mode.py`

**依赖：** T24、T26

**步骤：**

1. 删除 `PLAN_PROMPT`，`plan(task)` 只将原任务作为真实 user 消息保存。
2. 通过动态运行上下文携带任务、可选内容和 Plan 模式，不改变现有只读工具视图。
3. 保持计划成功替换、失败保留、空任务拒绝和调查轮数行为不变。

**验证：** 运行 `python -m pytest tests/test_plan_mode.py -q -k "plan_history or plan_reminder or plan_lifecycle"`，期望真实历史、模式提醒、只读调查和计划生命周期测试通过。

## T28：迁移批准计划执行语义

**文件：** `src/mewcode/conversation.py`、`tests/test_plan_mode.py`

**依赖：** T27

**步骤：**

1. 删除 `EXECUTE_PROMPT`，将真实 `/do` 动作保存为本次 user 消息。
2. 通过 `PromptRunContext` 的 task 与 approved_plan 传递原任务和完整批准计划。
3. 保持完整工具集合、完成后清除计划、错误或取消后保留计划等原生命周期。

**验证：** 运行 `python -m pytest tests/test_plan_mode.py -q -k "execute_history or execute_reminder or execute_lifecycle"`，期望 `/do` 真实历史、动态计划上下文和生命周期测试通过。

## T29：回归多轮工具会话

**文件：** `tests/test_tool_conversation.py`、`tests/fakes.py`

**依赖：** T11、T26、T28

**步骤：**

1. 将测试替身断言迁移到 `ModelRequest.tools` 和统一提示包。
2. 覆盖多轮工具、未知工具、失败结果回写和最终纯文本响应。
3. 断言运行时提醒不成为 user 历史，工具结果与 assistant continuation 顺序保持不变。

**验证：** 运行 `python -m pytest tests/test_tool_conversation.py -q`，期望全部多轮工具会话回归测试通过。

## T30：组装 CLI 提示依赖

**文件：** `src/mewcode/cli.py`、`tests/test_repl.py`

**依赖：** T3、T21、T28

**步骤：**

1. 用当前工作区创建环境提供器和 `PromptBuilder`。
2. 将构建器注入 `AgentRunner`，并以默认 `PromptAdditions` 创建 `Conversation`。
3. 保持现有配置格式、Provider 选择、工具注册和错误退出码不变。

**验证：** 运行 `python -m pytest tests/test_repl.py -q -k "main and prompt_builder"`，期望 CLI 依赖串接及原错误路径测试通过。

## T31：展示缓存 Token 统计

**文件：** `src/mewcode/repl.py`、`tests/test_repl.py`

**依赖：** T25、T30

**步骤：**

1. 将 Token 行固定为 `tokens: in=... out=... total=... cache-read=... cache-write=... cumulative=... cumulative-cache-read=... cumulative-cache-write=...`。
2. 对 `None` 显示现有的不可用表示，对明确零显示 `0`，不读取供应商原始对象。
3. 验证输出不包含提示正文、API Key、内部推理或 Provider 对象 repr。

**验证：** 运行 `python -m pytest tests/test_repl.py -q -k "token_output or cache_tokens or redacted"`，期望本次/累计格式、未知值和敏感信息隔离测试通过。

## T32：更新用户文档

**文件：** `README.md`

**依赖：** T30、T31

**步骤：**

1. 说明统一系统提示的稳定/动态边界、七个固定模块和三个调用方可选模块。
2. 说明 Plan/Execute 的系统提醒节奏及缓存 Token 行，不承诺每次请求必然命中。
3. 明确本阶段不加载项目指令、不自动激活 Skill、不生成记忆、不接真实 MCP。

**验证：** 运行 `rg -n "system-reminder|cache-read|cache-write|Skill|MCP|1, 5, 9, 13, 17" README.md`，期望每个主题至少出现一次且没有缓存必然命中的表述。

## T33：编写真实缓存与人工对比说明

**文件：** `docs/phase-4-prompt-architecture/manual-evaluation.md`

**依赖：** T21、T28、T31

**步骤：**

1. 写出 Anthropic 与 OpenAI 的真实 API 手工验证步骤，记录 Provider、模型、前缀长度、重复条件和实际 usage 字段。
2. 覆盖相同前缀、只改动态后缀、修改稳定指令或工具三组缓存观察，并允许记录“不具备验证条件”。
3. 固定五个定性场景：先读后改、专用搜索优先、Plan 禁写、动态变化不破坏前缀、提醒不被当成用户问题；每项含输入、轨迹观察点和通过条件。

**验证：** 运行 `rg -n "先读后改|专用搜索|Plan Mode|稳定前缀|系统提醒|cache_read|cache_write|cached_tokens|cache_write_tokens" docs/phase-4-prompt-architecture/manual-evaluation.md`，期望五个场景和两家 Provider 的缓存字段均可检索到。

## T34：完成提示构建层回归

**文件：** `tests/test_prompt_builder.py`、`tests/test_prompt_environment.py`、`tests/test_prompt_modes.py`

**依赖：** T3、T5、T7

**步骤：**

1. 补齐全部模块组合、空白可选内容、恶意标签、跨平台环境和 20 次提醒序列。
2. 对相同输入执行重复构建，断言稳定块和完整包均字节一致。
3. 确认测试使用注入时钟与 fake 环境，不读取真实凭据或网络。

**验证：** 运行 `python -m pytest tests/test_prompt_builder.py tests/test_prompt_environment.py tests/test_prompt_modes.py -q`，期望提示构建层全部测试通过。

## T35：完成 Provider 与工具规则回归

**文件：** `tests/test_providers.py`、`tests/test_tool_providers.py`、`tests/test_tools_base.py`

**依赖：** T12、T21

**步骤：**

1. 补齐官方/兼容地址、支持/旧模型、空工具、工具注册乱序和缓存字段缺失组合。
2. 保留双 Provider 原有流式文本、工具调用、错误脱敏、fallback、取消与 continuation 回归。
3. 断言所有 SDK 测试使用 fake/mock，未发起真实网络请求。

**验证：** 运行 `python -m pytest tests/test_providers.py tests/test_tool_providers.py tests/test_tools_base.py -q`，期望 Provider、工具序列化和工具描述测试全部通过。

## T36：完成 Agent 与会话回归

**文件：** `tests/test_agent_runner.py`、`tests/test_plan_mode.py`、`tests/test_conversation.py`、`tests/test_tool_conversation.py`、`tests/test_stream_collector.py`、`tests/test_repl.py`

**依赖：** T25、T29、T31

**步骤：**

1. 覆盖普通问答、Plan、Plan Finalization、`/do`、20 次工具循环、取消和错误停止。
2. 断言只有真实用户动作进入 user 历史，系统提醒与可选模块始终位于系统层。
3. 验证缓存用量从 Provider 事件贯通到 current、cumulative、outcome 和 REPL。

**验证：** 运行 `python -m pytest tests/test_agent_runner.py tests/test_plan_mode.py tests/test_conversation.py tests/test_tool_conversation.py tests/test_stream_collector.py tests/test_repl.py -q`，期望 Agent、Conversation、流事件和终端测试全部通过。

## T37：执行全量质量与范围回归

**文件：** 全部本阶段修改文件

**依赖：** T8、T32、T33、T34、T35、T36

**步骤：**

1. 编译全部源码和测试并运行完整测试套件。
2. 运行 diff 空白检查，确认没有语法、导入、格式或现有行为回归。
3. 搜索范围外能力，确认未加入项目指令发现、Skill 自动激活、记忆持久化、真实 MCP、缓存预热、费用计算或自动评分。

**验证：** 依次运行 `python -m compileall -q src tests`、`python -m pytest -q`、`git diff --check` 和 `rg -n "AGENTS\.md|activate_skill|persist_memory|MCP Server|cache_warm|cost_savings|auto.*score" src tests`；期望前三条命令以 0 退出、完整测试无失败，最后一条无范围外实现命中（允许测试中的否定断言或文档说明）。

## 执行顺序

```text
T1 -> T2 -------------------------------> T12 -------------------------------┐
 │    ├-> T4 -> T5 -----------------------------------------------------┐     │
 │    └-> T6 ------------------------------------------------------┐     │     │
 ├-> T3 -----------------------------------------------------------┤     │     │
 └-> T9 -> T10 ----------------------------------------------------┤     │     │
           └-> T11 -----------------------------------------------┼-----┼-----┤
T3 + T5 + T6 -> T7 -----------------------------------------------┘     │     │
                                                                          │     │
T7 + T9 + T11 -> T13 -> T14 -> T15 -------------------------------┐       │     │
T7 + T9 + T11 -> T16 -> T17 -> T18 -------------------------------┼-> T21 ─────┤
                         └-> T19                                   │       │     │
T10 + T16 -> T20 --------------------------------------------------┘       │     │
                                                                          │     │
T7 + T9 -> T22 -> T23 -> T24 ---------------------------------------------┤     │
                  └-> T25 -------------------------------------------------┤     │
T22 + T23 -> T26 -> T27 -> T28 -> T29 ------------------------------------┤     │
T3 + T21 + T28 -> T30 -> T31 ---------------------------------------------┤     │
                                                                          v     │
T30 + T31 -> T32                                                        T35 <----┘
T21 + T28 + T31 -> T33                                                    │
T3 + T5 + T7 -> T34                                                       │
T25 + T29 + T31 -> T36                                                    │
                                                                          v
T8 + T32 + T33 + T34 + T35 + T36 --------------------------------------> T37
```

可并行分支：

- T13–T15（Anthropic）与 T16–T20（OpenAI）在公共请求和工具序列化完成后可并行。
- T12（工具描述）与 T13–T20（Provider 映射）可并行。
- T32（README）、T33（人工验证）、T34（提示回归）、T35（Provider 回归）和 T36（Agent 回归）在各自依赖满足后可并行，最后统一进入 T37。
