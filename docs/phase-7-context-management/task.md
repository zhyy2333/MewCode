# 上下文管理与两层压缩 Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 新建 | `src/mewcode/context/__init__.py` | 导出上下文管理公共接口 |
| 新建 | `src/mewcode/context/models.py` | 配置、状态、归档、操作结果与熔断模型 |
| 新建 | `src/mewcode/context/estimator.py` | 字符权重、请求足迹与 usage 锚定 |
| 新建 | `src/mewcode/context/archive.py` | 会话归档、原子写入、活动锁与清理 |
| 新建 | `src/mewcode/context/tool_results.py` | 工具结果轻量压缩 |
| 新建 | `src/mewcode/context/summary.py` | 近期区选择、摘要 Prompt、响应解析与历史压缩 |
| 新建 | `src/mewcode/context/manager.py` | 自动/手动预检编排与熔断 |
| 修改 | `src/mewcode/providers/base.py` | 上下文窗口、消息元数据、完整 input usage |
| 修改 | `src/mewcode/providers/__init__.py` | 导出新增 Provider 公共类型 |
| 修改 | `src/mewcode/providers/openai_provider.py` | 消息标记与 OpenAI context usage |
| 修改 | `src/mewcode/providers/anthropic_provider.py` | 消息标记、缓存 usage 合并与系统摘要提升 |
| 修改 | `src/mewcode/tools/base.py` | 统一工具结果 JSON 负载序列化 |
| 修改 | `src/mewcode/tools/__init__.py` | 导出工具结果序列化函数 |
| 修改 | `src/mewcode/agent/events.py` | 上下文状态事件与停止原因 |
| 修改 | `src/mewcode/agent/runner.py` | 每请求预检、工具压缩和 committed history |
| 修改 | `src/mewcode/agent/__init__.py` | 导出新增 Agent 事件 |
| 修改 | `src/mewcode/config.py` | 解析并校验 `context_window` |
| 修改 | `src/mewcode/conversation.py` | `/compact`、历史替换、取消与关闭 |
| 修改 | `src/mewcode/repl.py` | 命令路由、状态渲染和退出清理 |
| 修改 | `src/mewcode/cli.py` | 上下文组件装配和启动清理 |
| 新建 | `tests/test_context_estimator.py` | Token 估算单元测试 |
| 新建 | `tests/test_context_archive.py` | 归档与锁单元测试 |
| 新建 | `tests/test_context_tool_results.py` | 轻量压缩单元测试 |
| 新建 | `tests/test_context_summary.py` | 摘要选择、Prompt 与解析测试 |
| 新建 | `tests/test_context_manager.py` | 自动/手动编排与熔断测试 |
| 新建 | `tests/test_context_integration.py` | Provider 对等与端到端测试 |
| 修改 | `tests/fakes.py` | 支持新消息契约、摘要脚本和 context usage |
| 修改 | `tests/test_config.py` | Profile 上下文窗口测试 |
| 修改 | `tests/test_providers.py` | usage、系统摘要和公共契约测试 |
| 修改 | `tests/test_tool_providers.py` | 工具负载、消息类别和分组测试 |
| 修改 | `tests/test_agent_runner.py` | 预检、工具压缩和提交语义测试 |
| 修改 | `tests/test_conversation.py` | 手动压缩、并发、取消和关闭测试 |
| 修改 | `tests/test_repl.py` | `/compact`、状态和 CLI 装配测试 |
| 修改 | `examples/config.yaml` | 可选窗口配置示例 |
| 修改 | `README.md` | 上下文管理用户文档 |

## T1：增加 Profile 上下文窗口配置

**文件：** `src/mewcode/providers/base.py`、`src/mewcode/config.py`、`tests/test_config.py`

**依赖：** 无

**步骤：**

1. 为 Provider Profile 增加默认值为 128000 的 `context_window`。
2. 解析可选配置，拒绝布尔值、非整数及小于 21193 的值。
3. 增加缺省、自定义和非法值测试。

**验证：** 运行 `python -m pytest tests/test_config.py -k context_window -q`，期望缺省值、自定义值和错误消息测试全部通过。

## T2：扩展公共消息与 usage 模型

**文件：** `src/mewcode/providers/base.py`、`src/mewcode/providers/__init__.py`、`tests/test_providers.py`

**依赖：** T1

**步骤：**

1. 增加 `MessageKind`，并给 `ChatMessage` 增加带兼容默认值的 `kind`、`group_id`。
2. 给 `TokenUsage` 增加 `context_input_tokens`，更新 `zero()` 与 `add()`。
3. 补充不可变性、默认兼容和可空加总测试。

**验证：** 运行 `python -m pytest tests/test_providers.py -k "token_usage or message_metadata" -q`，期望新增模型测试和既有 usage 测试通过。

## T3：统一工具结果规范负载

**文件：** `src/mewcode/tools/base.py`、`src/mewcode/tools/__init__.py`、`src/mewcode/providers/openai_provider.py`、`src/mewcode/providers/anthropic_provider.py`、`tests/test_tool_providers.py`

**依赖：** T2

**步骤：**

1. 在工具公共层增加确定性的 UTF-8 JSON 负载序列化函数。
2. 两个 Provider 删除重复实现并调用公共函数。
3. 验证键、Unicode、metadata 和失败结果在两种协议中一致。

**验证：** 运行 `python -m pytest tests/test_tool_providers.py -k serialization -q`，期望两种 Provider 得到语义相同且稳定的负载。

## T4：更新测试 Provider 契约

**文件：** `tests/fakes.py`、`tests/test_agent_runner.py`、`tests/test_conversation.py`

**依赖：** T2

**步骤：**

1. 让 `ScriptedAsyncProvider` 接受消息分组参数并生成正确类别。
2. 支持脚本化 `context_input_tokens` 和摘要响应。
3. 保持现有调用记录与流式错误能力不变。

**验证：** 运行 `python -m pytest tests/test_agent_runner.py tests/test_conversation.py -q`，期望现有测试在新契约下全部通过。

## T5：适配 OpenAI 消息元数据与 context usage

**文件：** `src/mewcode/providers/openai_provider.py`、`tests/test_providers.py`、`tests/test_tool_providers.py`

**依赖：** T2、T3

**步骤：**

1. 标记内部推理、助手文本、工具调用和工具结果类别及分组。
2. 将 OpenAI 完整 input tokens 写入 `context_input_tokens`。
3. 覆盖自然回答、多个工具调用、隐藏推理和缓存 usage。

**验证：** 运行 `python -m pytest tests/test_providers.py tests/test_tool_providers.py -k openai -q`，期望 OpenAI 相关测试全部通过。

## T6：适配 Anthropic 消息元数据与 context usage

**文件：** `src/mewcode/providers/anthropic_provider.py`、`tests/test_providers.py`、`tests/test_tool_providers.py`

**依赖：** T2、T3

**步骤：**

1. 标记组合助手消息和批量工具结果的类别及分组。
2. 将普通输入、缓存读取和缓存写入合成为 `context_input_tokens`。
3. 增加系统语义摘要/边界提升到 dynamic system 的请求测试。

**验证：** 运行 `python -m pytest tests/test_providers.py tests/test_tool_providers.py -k anthropic -q`，期望 Anthropic 相关测试全部通过且 messages 中无 system role。

## T7：建立上下文公共模型与配置

**文件：** `src/mewcode/context/models.py`、`src/mewcode/context/__init__.py`、`tests/test_context_manager.py`

**依赖：** T2

**步骤：**

1. 定义 `ContextConfig`、状态枚举、归档记录和操作结果。
2. 校验全部阈值、余量、输出预算和失败次数的不变量。
3. 从上下文包导出稳定公共接口。

**验证：** 运行 `python -m pytest tests/test_context_manager.py -k config -q`，期望默认值和非法组合测试通过。

## T8：实现熔断器状态模型

**文件：** `src/mewcode/context/models.py`、`tests/test_context_manager.py`

**依赖：** T7

**步骤：**

1. 实现连续失败累加、第三次开路和成功复位。
2. 返回是否从开路状态恢复，供状态层使用。
3. 覆盖失败、成功、开路和重复失败序列。

**验证：** 运行 `python -m pytest tests/test_context_manager.py -k circuit_breaker -q`，期望状态转换完全符合三次熔断规则。

## T9：实现字符权重与近似 Token 基础函数

**文件：** `src/mewcode/context/estimator.py`、`tests/test_context_estimator.py`

**依赖：** T7

**步骤：**

1. 实现 ASCII 四字符一 Token、非 ASCII 一字符一 Token 的权重计算。
2. 支持权重相加、相减、向上折算和不低于零。
3. 覆盖英文、中文、混合文本、空文本和负增量。

**验证：** 运行 `python -m pytest tests/test_context_estimator.py -k character -q`，期望所有字符权重边界通过。

## T10：实现请求足迹生成

**文件：** `src/mewcode/context/estimator.py`、`tests/test_context_estimator.py`

**依赖：** T9

**步骤：**

1. 稳定计量 Prompt、角色、消息内容和排序后的工具定义。
2. 生成不包含敏感正文的稳定签名和消息计数。
3. 缓存不可变消息、稳定 Prompt 和工具定义的权重。

**验证：** 运行 `python -m pytest tests/test_context_estimator.py -k footprint -q`，期望相同请求足迹相同，内容或工具变化时足迹变化。

## T11：实现 usage 锚定与增量估算

**文件：** `src/mewcode/context/estimator.py`、`tests/test_context_estimator.py`

**依赖：** T10

**步骤：**

1. 无 usage 时估算完整请求。
2. 观察有效 usage 后，以足迹差修正锚点 Token。
3. 支持新增、删除、摘要替换、usage 缺失和重新锚定。

**验证：** 运行 `python -m pytest tests/test_context_estimator.py -k "anchor or incremental" -q`，期望增量只计算变化部分且压缩后估算下降。

## T12：建立安全会话归档目录

**文件：** `src/mewcode/context/archive.py`、`tests/test_context_archive.py`

**依赖：** T7

**步骤：**

1. 在工作区私有目录创建 UUID 会话目录和锁文件。
2. 生成只含固定前缀与递增序号的记录名。
3. 返回标准化的工作区相对路径，并验证目标不越界。

**验证：** 运行 `python -m pytest tests/test_context_archive.py -k "session or path" -q`，期望目录隔离、序号和越界保护测试通过。

## T13：实现工具结果原子归档

**文件：** `src/mewcode/context/archive.py`、`tests/test_context_archive.py`

**依赖：** T3、T12

**步骤：**

1. 写入带版本、调用信息和完整 `ToolResult` 的 UTF-8 JSON。
2. 使用同目录临时文件和原子替换发布。
3. 在写入或替换失败时清除临时文件并返回安全错误。

**验证：** 运行 `python -m pytest tests/test_context_archive.py -k tool_result -q`，期望原文无损、原子发布和失败清理测试通过。

## T14：实现早期历史归档与撤销

**文件：** `src/mewcode/context/archive.py`、`tests/test_context_archive.py`

**依赖：** T12

**步骤：**

1. 按原顺序保存角色、类别、分组和原始内容。
2. 增加删除未引用记录的内部撤销能力。
3. 对不可 JSON 化内容产生安全失败，不写部分文件。

**验证：** 运行 `python -m pytest tests/test_context_archive.py -k history -q`，期望顺序、内容、撤销和序列化失败测试通过。

## T15：实现类 Unix 活动锁适配

**文件：** `src/mewcode/context/archive.py`、`tests/test_context_archive.py`

**依赖：** T12

**步骤：**

1. 用 advisory file lock 实现持有、探测和释放。
2. 将平台细节封装在归档私有接口后。
3. 用 monkeypatch 覆盖锁被占用和可取得两种路径。

**验证：** 运行 `python -m pytest tests/test_context_archive.py -k unix_lock -q`，期望活动目录无法被探测锁获取。

## T16：实现 Windows 活动锁适配

**文件：** `src/mewcode/context/archive.py`、`tests/test_context_archive.py`

**依赖：** T12

**步骤：**

1. 用文件区域锁实现持有、探测和释放，确保锁文件至少一个字节。
2. 统一 Windows 锁冲突到“活动会话”结果。
3. 用 monkeypatch 覆盖成功、占用和释放失败。

**验证：** 运行 `python -m pytest tests/test_context_archive.py -k windows_lock -q`，期望 Windows 分支在非 Windows 测试环境也可模拟通过。

## T17：实现遗留清理与正常关闭

**文件：** `src/mewcode/context/archive.py`、`tests/test_context_archive.py`

**依赖：** T13-T16

**步骤：**

1. 启动时只删除能够取得锁的旧会话目录。
2. 正常关闭时释放当前锁并删除当前目录。
3. 单个删除失败时继续处理并返回非敏感警告。

**验证：** 运行 `python -m pytest tests/test_context_archive.py -k "cleanup or close" -q`，期望活动目录保留、遗留目录删除、失败隔离测试通过。

## T18：实现单体工具结果存盘选择

**文件：** `src/mewcode/context/tool_results.py`、`tests/test_context_tool_results.py`

**依赖：** T9、T13

**步骤：**

1. 估算规范工具负载大小。
2. 选择严格超过 8000 Token 的结果，边界值不选。
3. 保持输入执行顺序和未选结果对象不变。

**验证：** 运行 `python -m pytest tests/test_context_tool_results.py -k single -q`，期望 8000/8001 边界和顺序测试通过。

## T19：实现首尾预览与存盘占位

**文件：** `src/mewcode/context/tool_results.py`、`tests/test_context_tool_results.py`

**依赖：** T18

**步骤：**

1. 按 500/500 Token 生成总量不超过 1000 的首尾预览。
2. 一侧不足时把剩余额度分配给另一侧。
3. 生成包含路径、大小、调用标识和原成功/失败语义的占位结果。

**验证：** 运行 `python -m pytest tests/test_context_tool_results.py -k preview -q`，期望中英文预览预算、短结果和失败占位测试通过。

## T20：实现批次 12K 稳定选择

**文件：** `src/mewcode/context/tool_results.py`、`tests/test_context_tool_results.py`

**依赖：** T19

**步骤：**

1. 单体替换后重新估算批次保留量。
2. 超过 12000 时按原始大小降序、执行索引升序继续选择。
3. 每次替换后重新计算，直到实际保留量不超过预算。

**验证：** 运行 `python -m pytest tests/test_context_tool_results.py -k batch -q`，期望阈值、同大小稳定排序和最终预算测试通过。

## T21：保证工具批次压缩原子性

**文件：** `src/mewcode/context/tool_results.py`、`tests/test_context_tool_results.py`

**依赖：** T20

**步骤：**

1. 为选中结果全部存盘成功后才返回替换批次。
2. 中途失败时撤销本批次已写归档并保留原执行集合。
3. 只在成功时生成 `TOOL_ARCHIVED` 状态。

**验证：** 运行 `python -m pytest tests/test_context_tool_results.py -k atomic -q`，期望第二项写入失败时无占位、无有效归档引用。

## T22：实现近期历史基本选择

**文件：** `src/mewcode/context/summary.py`、`tests/test_context_summary.py`

**依赖：** T9、T2

**步骤：**

1. 按连续 `group_id` 构造原子消息组。
2. 从尾部保留直到同时达到 10000 Token 和 5 条消息。
3. 未标分组消息按单条安全分组处理。

**验证：** 运行 `python -m pytest tests/test_context_summary.py -k recent -q`，期望 Token、消息数和完整分组三类边界通过。

## T23：实现滚动摘要替换选择

**文件：** `src/mewcode/context/summary.py`、`tests/test_context_summary.py`

**依赖：** T22

**步骤：**

1. 将现有 SUMMARY 和 BOUNDARY 无条件移入待摘要区。
2. 保证近期普通原文仍按原对象、原顺序保留。
3. 没有可压缩普通消息且没有旧摘要时返回无需压缩。

**验证：** 运行 `python -m pytest tests/test_context_summary.py -k rolling -q`，期望第二次选择不会留下旧摘要或旧边界。

## T24：实现专用摘要 Prompt

**文件：** `src/mewcode/context/summary.py`、`tests/test_context_summary.py`

**依赖：** T23、T14

**步骤：**

1. 写入禁止工具、先草稿后正式摘要、原文约束和禁止臆测指令。
2. 固定八个章节、XML 风格边界和空章节规则。
3. 把规范早期消息及归档相对路径放入摘要输入。

**验证：** 运行 `python -m pytest tests/test_context_summary.py -k prompt -q`，期望 Prompt 包含全部强制语义且不包含普通 Agent Prompt。

## T25：实现摘要请求容量计算

**文件：** `src/mewcode/context/summary.py`、`tests/test_context_summary.py`

**依赖：** T11、T24

**步骤：**

1. 构造 `tools=None`、最大输出 8192 的摘要请求。
2. 自动模式扣除 13000，手动模式扣除 3000。
3. 在 Provider 调用前拒绝达到或超过摘要输入边界的请求。

**验证：** 运行 `python -m pytest tests/test_context_summary.py -k capacity -q`，期望自动/手动边界和无工具请求测试通过。

## T26：实现正式摘要成功解析

**文件：** `src/mewcode/context/summary.py`、`tests/test_context_summary.py`

**依赖：** T24

**步骤：**

1. 精确提取单个草稿和单个正式摘要边界。
2. 验证八个章节存在且顺序正确。
3. 只返回不含草稿和外层标记的正式正文。

**验证：** 运行 `python -m pytest tests/test_context_summary.py -k parser_success -q`，期望草稿无法在返回正文中找到。

## T27：实现摘要结构拒绝矩阵

**文件：** `src/mewcode/context/summary.py`、`tests/test_context_summary.py`

**依赖：** T26

**步骤：**

1. 拒绝缺失/重复边界、缺失/乱序章节和空内容。
2. 拒绝空章节未写“无”、工具调用及非自然结束。
3. 为每类错误返回不含响应正文的安全原因。

**验证：** 运行 `python -m pytest tests/test_context_summary.py -k parser_rejects -q`，期望参数化无效响应全部被拒绝。

## T28：实现私有摘要流收集

**文件：** `src/mewcode/context/summary.py`、`tests/test_context_summary.py`

**依赖：** T25-T27、T4

**步骤：**

1. 私下累积 Provider 文本、usage、finish reason、内部块和意外工具调用。
2. 不产生 AgentTextDelta 或其他草稿输出事件。
3. 在取消时关闭流并向上保留 `CancelledError`。

**验证：** 运行 `python -m pytest tests/test_context_summary.py -k collector -q`，期望成功、截断、工具调用、Provider 错误和取消测试通过。

## T29：实现历史压缩成功提交

**文件：** `src/mewcode/context/summary.py`、`tests/test_context_summary.py`

**依赖：** T14、T23-T28

**步骤：**

1. 归档早期历史并调用摘要请求。
2. 成功后生成单一 SUMMARY、BOUNDARY 和原样近期区。
3. 确认正式摘要包含归档索引且旧摘要被替换。

**验证：** 运行 `python -m pytest tests/test_context_summary.py -k compaction_success -q`，期望近期对象逐项相同且活动历史只有一份新摘要。

## T30：实现历史压缩失败回滚

**文件：** `src/mewcode/context/summary.py`、`tests/test_context_summary.py`

**依赖：** T29

**步骤：**

1. Provider、结构、容量和发布失败时撤销未引用历史归档。
2. 返回原消息且不产生 SUMMARY/BOUNDARY。
3. 删除失败仅返回非敏感清理警告。

**验证：** 运行 `python -m pytest tests/test_context_summary.py -k rollback -q`，期望所有失败场景历史不变且无草稿泄漏。

## T31：实现可观察的 ContextOperation

**文件：** `src/mewcode/context/manager.py`、`tests/test_context_manager.py`

**依赖：** T7、T28

**步骤：**

1. 实现单次消费的异步状态流、完成后 outcome 和完成前访问保护。
2. 在耗时摘要前发出开始状态，在结束后发出完成或失败状态。
3. 实现取消当前摘要任务并等待清理。

**验证：** 运行 `python -m pytest tests/test_context_manager.py -k operation -q`，期望事件顺序、单次消费和取消测试通过。

## T32：实现低于阈值的普通请求预检

**文件：** `src/mewcode/context/manager.py`、`tests/test_context_manager.py`

**依赖：** T11、T21、T31

**步骤：**

1. 对完整 `ModelRequest` 估算输入并计算自动边界。
2. 低于边界时原样返回请求、消息和足迹。
3. `observe_usage` 用主请求足迹更新估算器。

**验证：** 运行 `python -m pytest tests/test_context_manager.py -k below_threshold -q`，期望无摘要 Provider 调用且请求对象保持等价。

## T33：实现自动摘要成功与请求重建

**文件：** `src/mewcode/context/manager.py`、`tests/test_context_manager.py`

**依赖：** T8、T29、T32

**步骤：**

1. 达到边界时执行一次自动历史压缩。
2. 记录摘要 usage，使用新历史重建原 Prompt、工具集和输出预算。
3. 重新估算；安全时返回主请求，不安全时保存压缩历史但拒绝主调用。

**验证：** 运行 `python -m pytest tests/test_context_manager.py -k automatic_success -q`，期望只有一次摘要请求且重建主请求低于边界。

## T34：实现摘要失败计数与自动熔断

**文件：** `src/mewcode/context/manager.py`、`tests/test_context_manager.py`

**依赖：** T8、T30、T32

**步骤：**

1. 每次非取消失败只增加一次计数，不在同一预检重试。
2. 第三次失败发出开路状态。
3. 开路时危险请求在任何模型调用前拒绝，安全请求继续运行。

**验证：** 运行 `python -m pytest tests/test_context_manager.py -k automatic_failure -q`，期望三次调用后开路，第四次危险请求无 Provider 调用。

## T35：实现手动压缩与熔断恢复

**文件：** `src/mewcode/context/manager.py`、`tests/test_context_manager.py`

**依赖：** T29-T31、T34

**步骤：**

1. 强制手动压缩使用 3K 余量且忽略自动触发阈值。
2. 无早期区时返回无需压缩且不调用 Provider。
3. 开路状态下允许一次尝试，成功复位，失败保持开路。

**验证：** 运行 `python -m pytest tests/test_context_manager.py -k manual -q`，期望强制、no-op、失败和恢复测试通过。

## T36：增加上下文 Agent 事件与停止原因

**文件：** `src/mewcode/agent/events.py`、`src/mewcode/agent/__init__.py`、`tests/test_agent_runner.py`

**依赖：** T7

**步骤：**

1. 增加携带 `ContextStatus` 的 Agent 事件。
2. 增加容量拒绝和摘要失败停止原因。
3. 保持现有事件联合类型和停止格式兼容。

**验证：** 运行 `python -m pytest tests/test_agent_runner.py -k context_event -q`，期望状态与停止原因可区分。

## T37：在 Agent 每次请求前接入预检

**文件：** `src/mewcode/agent/runner.py`、`tests/test_agent_runner.py`

**依赖：** T31-T36、T4

**步骤：**

1. 注入共享 `ContextManager`，在所有迭代及 Plan 最终请求前创建预检操作。
2. 实时转发上下文状态，并只调用预检允许的请求。
3. 将主 Provider usage 与预检足迹交回估算器。

**验证：** 运行 `python -m pytest tests/test_agent_runner.py -k preflight -q`，期望每次真实模型调用前恰有一次预检且输出预算正确。

## T38：在 Agent 工具批次接入轻量压缩

**文件：** `src/mewcode/agent/runner.py`、`tests/test_agent_runner.py`

**依赖：** T21、T37、T5-T6

**步骤：**

1. 保持原工具结果事件先输出，再压缩历史负载。
2. 给一次助手工具响应和全部结果分配同一 `group_id`。
3. 存盘失败时阻止下一次 Provider 调用并使用上下文停止原因。

**验证：** 运行 `python -m pytest tests/test_agent_runner.py -k tool_compaction -q`，期望原状态可见、历史为占位、分组完整且失败不续跑。

## T39：实现 Agent committed history 语义

**文件：** `src/mewcode/agent/runner.py`、`tests/test_agent_runner.py`

**依赖：** T37-T38

**步骤：**

1. 分离工作历史、本轮消息和完整已提交历史。
2. 处理首次失败、压缩后失败、工具批次提交、自然完成和输出截断。
3. 将当前上下文操作纳入取消路径。

**验证：** 运行 `python -m pytest tests/test_agent_runner.py -k committed_history -q`，期望各停止路径只保存合法且已提交的消息。

## T40：让 Conversation 使用完整提交历史

**文件：** `src/mewcode/conversation.py`、`tests/test_conversation.py`

**依赖：** T39

**步骤：**

1. 接收共享上下文管理器。
2. Agent Run 结束后整体替换为 `committed_history`。
3. 保持消息副本、PendingPlan 和失败时用户消息不提交的现有行为。

**验证：** 运行 `python -m pytest tests/test_conversation.py -k "history or provider_error" -q`，期望既有行为与压缩替换测试通过。

## T41：实现 Conversation 手动压缩、取消与关闭

**文件：** `src/mewcode/conversation.py`、`tests/test_conversation.py`

**依赖：** T35、T40

**步骤：**

1. 新增不创建用户消息的 `compact()`。
2. 与 Agent Run 共用活动操作互斥和取消入口。
3. 新增幂等 `close()`，取消活动操作并关闭归档。

**验证：** 运行 `python -m pytest tests/test_conversation.py -k "compact or close or active" -q`，期望 no-op、成功、失败、并发、取消和关闭测试通过。

## T42：接入 REPL `/compact` 与状态渲染

**文件：** `src/mewcode/repl.py`、`tests/test_repl.py`

**依赖：** T36、T41

**步骤：**

1. 精确路由 `/compact`，拒绝附加参数并更新帮助文字。
2. 渲染全部上下文状态且不输出草稿或归档正文。
3. 在所有退出路径关闭 Conversation，再关闭事件循环。

**验证：** 运行 `python -m pytest tests/test_repl.py -k "compact or context_status or closes_conversation" -q`，期望命令、输出层级和清理测试通过。

## T43：在 CLI 装配上下文会话

**文件：** `src/mewcode/cli.py`、`tests/test_repl.py`

**依赖：** T1、T17、T35、T37、T41-T42

**步骤：**

1. 从活动 Profile 创建 `ContextConfig`、归档和管理器。
2. 启动归档并输出非敏感清理警告。
3. 将同一管理器注入 AgentRunner 与 Conversation，并保留 MCP 清理顺序。

**验证：** 运行 `python -m pytest tests/test_repl.py -k "main_ and context" -q`，期望正常、配置失败、启动警告、KeyboardInterrupt 和 MCP 清理场景通过。

## T44：增加 OpenAI/Anthropic 上下文对等集成测试

**文件：** `tests/test_context_integration.py`、`tests/fakes.py`

**依赖：** T5-T6、T33-T43

**步骤：**

1. 用等价 fake 历史分别运行两种 Provider 格式。
2. 对比工具选择、保留区、摘要/边界、熔断和最终语义。
3. 验证两边请求消息均满足各自协议约束。

**验证：** 运行 `python -m pytest tests/test_context_integration.py -k parity -q`，期望两条协议路径得到等价上下文结果。

## T45：增加长对话端到端场景

**文件：** `tests/test_context_integration.py`

**依赖：** T44

**步骤：**

1. 构造工具结果逐轮增长并触发两层压缩的完整 Conversation。
2. 让后续模型按边界读取归档文件并继续完成任务。
3. 记录每次请求估算，确认均低于对应容量边界。

**验证：** 运行 `python -m pytest tests/test_context_integration.py -k long_conversation -q`，期望轻量存盘、滚动摘要、重新读取和最终回答全链路通过。

## T46：更新配置示例和用户文档

**文件：** `examples/config.yaml`、`README.md`

**依赖：** T42-T43

**步骤：**

1. 在示例 Profile 中展示可选 `context_window` 和 128000 默认行为。
2. 说明两层压缩阈值、自动/手动余量及 `/compact`。
3. 说明 `.mewcode/context` 的读取与清理生命周期、熔断恢复和不使用精确 tokenizer 的限制。

**验证：** 运行 `rg -n "context_window|/compact|128000|\.mewcode/context" README.md examples/config.yaml`，期望所有用户可见行为均有说明。

## T47：运行完整回归并检查残留

**文件：** 全部实现与测试文件

**依赖：** T1-T46

**步骤：**

1. 运行完整测试套件并修复所有回归。
2. 检查上下文包不存在对 Agent、Conversation 或 REPL 的反向依赖。
3. 检查测试结束后工作区没有遗留活动会话目录、临时文件或未处理异步任务。

**验证：** 运行 `python -m pytest -q`，期望全部测试通过；再运行 `rg -n "mewcode\.(agent|conversation|repl)" src/mewcode/context`，期望无匹配；检查 `.mewcode/context`，期望无测试遗留会话目录。

## 执行顺序

```text
T1 -> T2 -> T3
       ├-> T4
       ├-> T5
       └-> T6

T2 -> T7 -> T8
          -> T9 -> T10 -> T11
          -> T12 -> T13 -> T14
                    ├-> T15
                    └-> T16
T13-T16 -> T17

T9 + T13 -> T18 -> T19 -> T20 -> T21
T9 + T14 -> T22 -> T23 -> T24 -> T25
                              -> T26 -> T27 -> T28 -> T29 -> T30

T8 + T11 + T21 + T28 -> T31 -> T32
T29 + T32 -> T33
T30 + T32 -> T34
T29-T31 + T34 -> T35

T7 -> T36
T4 + T31-T36 -> T37
T5-T6 + T21 + T37 -> T38 -> T39 -> T40 -> T41 -> T42 -> T43

T5-T6 + T33-T43 -> T44 -> T45
T42-T43 -> T46
T1-T46 -> T47
```

T5 与 T6 可并行；T15 与 T16 可并行；估算器、归档和 Provider 适配在依赖满足后也可并行开发。实现时仍按每个任务的验证命令先取得证据，再标记完成。
