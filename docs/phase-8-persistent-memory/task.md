# 项目知识、会话恢复与长期记忆 Tasks

## 文件清单

### 新建

| 文件 | 职责 |
|---|---|
| `src/mewcode/locking.py` | 跨平台文件锁 |
| `src/mewcode/continuity/__init__.py` | continuity 公共导出 |
| `src/mewcode/continuity/diagnostics.py` | 安全诊断与错误 |
| `src/mewcode/continuity/paths.py` | 固定路径集合 |
| `src/mewcode/continuity/instructions.py` | 三层指令加载 |
| `src/mewcode/continuity/session_models.py` | 会话模型 |
| `src/mewcode/continuity/session_codec.py` | JSONL 与消息协议 |
| `src/mewcode/continuity/session_repository.py` | 会话仓库与绑定 |
| `src/mewcode/continuity/memory_models.py` | 记忆模型 |
| `src/mewcode/continuity/memory_store.py` | 笔记、索引与事务 |
| `src/mewcode/continuity/memory_updater.py` | LLM 更新请求 |
| `src/mewcode/continuity/memory_manager.py` | 后台任务与 Prompt view |
| `src/mewcode/continuity/sanitization.py` | 秘密过滤与回合裁剪 |
| `tests/test_locking.py` | 锁测试 |
| `tests/test_continuity_paths.py` | 路径测试 |
| `tests/test_instruction_loader.py` | 指令加载测试 |
| `tests/test_session_codec.py` | 会话编解码测试 |
| `tests/test_session_repository.py` | 会话仓库测试 |
| `tests/test_session_integration.py` | 会话与 Agent 集成测试 |
| `tests/test_memory_models.py` | 记忆模型测试 |
| `tests/test_memory_store.py` | 记忆存储与事务测试 |
| `tests/test_memory_updater.py` | 记忆更新器测试 |
| `tests/test_memory_manager.py` | 后台记忆管理测试 |
| `tests/test_continuity_integration.py` | 端到端连续性测试 |

### 修改

| 文件 | 修改 |
|---|---|
| `src/mewcode/providers/base.py` | 增加恢复提醒消息类型 |
| `src/mewcode/agent/__init__.py` | 导出新增 Agent 事件类型 |
| `src/mewcode/agent/events.py` | 增加持久化停止原因与 continuity 状态 |
| `src/mewcode/agent/runner.py` | 增加历史提交钩子 |
| `src/mewcode/conversation.py` | 接入会话、指令和记忆生命周期 |
| `src/mewcode/context/archive.py` | 复用共享锁 |
| `src/mewcode/repl.py` | 渲染 continuity 状态 |
| `src/mewcode/cli.py` | 参数、启动装配和关闭 |
| `src/mewcode/prompting/models.py` | 不可变 additions 合并 |
| `tests/fakes.py` | continuity 所需 fake |
| 现有 Agent、Conversation、Context、Prompt、REPL、CLI 测试 | 兼容与集成覆盖 |
| `README.md` | 用户文档 |

## 基础设施与指令

## T1：定义安全诊断与错误模型

**文件：** `src/mewcode/continuity/diagnostics.py`、`tests/test_continuity_paths.py`  
**依赖：** 无

**步骤：**
1. 定义组件、严重程度、稳定错误码和安全消息模型。
2. 定义 instruction、session、memory 的错误基类。

**验证：** 运行 `python -m pytest tests/test_continuity_paths.py -q`，预期诊断模型不可变且不接受非法组件或级别。

## T2：实现固定路径集合

**文件：** `src/mewcode/continuity/paths.py`、`tests/test_continuity_paths.py`  
**依赖：** T1

**步骤：**
1. 从工作区和可注入用户根生成全部固定路径。
2. 确保返回绝对规范路径且不读取真实用户目录。

**验证：** 运行 `python -m pytest tests/test_continuity_paths.py -q`，预期项目、用户、会话和记忆路径全部符合设计。

## T3：实现共享跨平台文件锁

**文件：** `src/mewcode/locking.py`、`tests/test_locking.py`  
**依赖：** 无

**步骤：**
1. 封装 Windows 和 Unix 的非阻塞获取、释放和幂等关闭。
2. 支持对同一路径的竞争探测，不在锁文件中保存业务状态。

**验证：** 运行 `python -m pytest tests/test_locking.py -q`，预期第二个持有者被拒绝，释放后可重新获取。

## T4：让上下文归档复用共享锁

**文件：** `src/mewcode/context/archive.py`、`tests/test_context_archive.py`  
**依赖：** T3

**步骤：**
1. 删除归档模块内重复锁实现，改用共享锁。
2. 保持启动清理、活动目录跳过和关闭语义不变。

**验证：** 运行 `python -m pytest tests/test_context_archive.py -q`，预期现有测试全部通过。

## T5：建立 continuity 公共导出

**文件：** `src/mewcode/continuity/__init__.py`  
**依赖：** T1、T2

**步骤：**
1. 仅导出稳定的路径、诊断和后续公共协议占位。
2. 避免导入事务内部实现，防止循环依赖。

**验证：** 运行 `python -c "import mewcode.continuity"`，预期无导入错误。

## T6：实现空入口与单层指令加载

**文件：** `src/mewcode/continuity/instructions.py`、`tests/test_instruction_loader.py`  
**依赖：** T1、T2

**步骤：**
1. 定义 scope、source 和 snapshot。
2. 实现缺失入口静默跳过、UTF-8 读取和 LF 规范化。

**验证：** 运行 `python -m pytest tests/test_instruction_loader.py -q -k "empty or single"`，预期空目录得到空快照，单文件正文保持不变。

## T7：实现三层优先级与来源边界

**文件：** `src/mewcode/continuity/instructions.py`、`tests/test_instruction_loader.py`  
**依赖：** T6

**步骤：**
1. 按项目本地、项目根、用户级排序。
2. 为非空来源添加逻辑标题，不输出绝对用户路径。

**验证：** 运行 `python -m pytest tests/test_instruction_loader.py -q -k priority`，预期标题和正文顺序固定。

## T8：实现递归 include

**文件：** `src/mewcode/continuity/instructions.py`、`tests/test_instruction_loader.py`  
**依赖：** T7

**步骤：**
1. 仅识别独占一行的 `@include`，按当前文件目录解析路径。
2. 支持带空格路径，并在原位置展开内容。

**验证：** 运行 `python -m pytest tests/test_instruction_loader.py -q -k include`，预期嵌套顺序正确，行内文本不被展开。

## T9：实现 include 深度、visited 与环路保护

**文件：** `src/mewcode/continuity/instructions.py`、`tests/test_instruction_loader.py`  
**依赖：** T8

**步骤：**
1. 顶层深度按 0 计算，限制为 5。
2. 每个顶层入口维护独立 visited，重复和环路只展开一次并产生诊断。

**验证：** 运行 `python -m pytest tests/test_instruction_loader.py -q -k "depth or cycle or duplicate"`，预期无递归失控或重复正文。

## T10：实现 include 路径沙箱

**文件：** `src/mewcode/continuity/instructions.py`、`tests/test_instruction_loader.py`  
**依赖：** T9

**步骤：**
1. 使用真实路径、平台大小写规则和对应 scope 根执行边界判断。
2. 覆盖父目录、绝对路径、符号链接、缺失和非法编码诊断。

**验证：** 运行 `python -m pytest tests/test_instruction_loader.py -q`，预期 AC1–AC3 场景全部通过。

## 会话格式与仓库

## T11：定义会话模型和恢复提醒类型

**文件：** `src/mewcode/continuity/session_models.py`、`src/mewcode/providers/base.py`、`tests/test_session_codec.py`  
**依赖：** T1

**步骤：**
1. 定义 open mode、summary、state、open result 和记录枚举。
2. 增加 `MessageKind.RESUME_NOTICE`。

**验证：** 运行 `python -m pytest tests/test_session_codec.py -q -k models`，预期模型校验和消息类型正确。

## T12：实现 ChatMessage JSON 往返

**文件：** `src/mewcode/continuity/session_codec.py`、`tests/test_session_codec.py`  
**依赖：** T11

**步骤：**
1. 编解码 role、kind、group_id 和 JSON 兼容 content。
2. 拒绝未知 kind、非字符串字典键和不可序列化对象。

**验证：** 运行 `python -m pytest tests/test_session_codec.py -q -k message`，预期普通、内部、工具和边界消息逐项相等。

## T13：实现版本化 JSONL 记录编解码

**文件：** `src/mewcode/continuity/session_codec.py`、`tests/test_session_codec.py`  
**依赖：** T12

**步骤：**
1. 支持 start、history append/replace 和 plan_state。
2. 统一 RFC3339 时间、紧凑 JSON 和单行 UTF-8 输出。

**验证：** 运行 `python -m pytest tests/test_session_codec.py -q -k record`，预期每条编码只占一行且可重放。

## T14：实现逻辑历史重放

**文件：** `src/mewcode/continuity/session_codec.py`、`tests/test_session_codec.py`  
**依赖：** T13

**步骤：**
1. 按顺序应用 append、replace 和 plan_state。
2. 检查 start ID、记录版本和必要字段。

**验证：** 运行 `python -m pytest tests/test_session_codec.py -q -k replay`，预期替换后只保留最新逻辑历史和计划状态。

## T15：实现坏行与尾残行扫描

**文件：** `src/mewcode/continuity/session_codec.py`、`tests/test_session_codec.py`  
**依赖：** T14

**步骤：**
1. 二进制逐行读取并记录偏移。
2. 跳过完整坏行，识别无换行的最后残行及其截断偏移。

**验证：** 运行 `python -m pytest tests/test_session_codec.py -q -k "malformed or partial"`，预期有效行继续恢复，尾残行位置准确。

## T16：实现 OpenAI 工具配对提取

**文件：** `src/mewcode/continuity/session_codec.py`、`tests/test_session_codec.py`  
**依赖：** T12

**步骤：**
1. 从 function_call 与 function_call_output 提取 ID。
2. 校验 group_id、顺序、重复和未知结果。

**验证：** 运行 `python -m pytest tests/test_session_codec.py -q -k openai_pair`，预期完整组通过，四类异常返回同一确定截断点。

## T17：实现 Anthropic 多工具配对提取

**文件：** `src/mewcode/continuity/session_codec.py`、`tests/test_session_codec.py`  
**依赖：** T16

**步骤：**
1. 从 tool_use 与 tool_result 内容数组提取 ID。
2. 验证一个消息内多调用、多结果和内部消息的原子组。

**验证：** 运行 `python -m pytest tests/test_session_codec.py -q -k anthropic_pair`，预期与 OpenAI 产生等价合法前缀。

## T18：实现会话标题与摘要推导

**文件：** `src/mewcode/continuity/session_codec.py`、`tests/test_session_codec.py`  
**依赖：** T14

**步骤：**
1. 从第一条非空用户文本生成折叠空白、最多 60 字符的标题。
2. 计算逻辑消息数、最后活动时间和 recoverable 状态。

**验证：** 运行 `python -m pytest tests/test_session_codec.py -q -k summary`，预期重复扫描结果一致且不返回完整正文。

## T19：实现会话 ID 与新建流程

**文件：** `src/mewcode/continuity/session_repository.py`、`tests/test_session_repository.py`  
**依赖：** T2、T3、T13

**步骤：**
1. 生成 `YYYYMMDD-HHMMSS-xxxx`，支持注入时钟和随机后缀。
2. 独占创建 JSONL，写 start 并取得锁；碰撞时重试。

**验证：** 运行 `python -m pytest tests/test_session_repository.py -q -k "id or create"`，预期固定同秒下 ID 唯一。

## T20：实现 SessionBinding 的 append/replace

**文件：** `src/mewcode/continuity/session_repository.py`、`tests/test_session_repository.py`  
**依赖：** T19

**步骤：**
1. 比较完整候选历史，选择 no-op、append 或 replace。
2. 追加后 flush、fsync，成功后才更新持久状态。

**验证：** 运行 `python -m pytest tests/test_session_repository.py -q -k binding`，预期三种分支和追加失败状态正确。

## T21：实现会话锁生命周期

**文件：** `src/mewcode/continuity/session_repository.py`、`tests/test_session_repository.py`  
**依赖：** T3、T19

**步骤：**
1. 使用 `sessions/.locks` 获取、探测和释放锁。
2. 保证幂等 close，活动会话不能被第二仓库打开。

**验证：** 运行 `python -m pytest tests/test_session_repository.py -q -k lock`，预期竞争被拒绝，关闭后恢复。

## T22：实现候选流式扫描与 AUTO 恢复

**文件：** `src/mewcode/continuity/session_repository.py`、`tests/test_session_repository.py`  
**依赖：** T15、T18、T21

**步骤：**
1. 扫描每个 JSONL 只保留 SessionSummary。
2. 按最后活动和 ID 降序尝试候选，失败后继续下一个。

**验证：** 运行 `python -m pytest tests/test_session_repository.py -q -k auto`，预期恢复最近可用会话，无候选时新建。

## T23：实现显式 RESUME 错误语义

**文件：** `src/mewcode/continuity/session_repository.py`、`tests/test_session_repository.py`  
**依赖：** T22

**步骤：**
1. 区分不存在、过期、占用和不可恢复。
2. 显式失败不得回退到其他会话。

**验证：** 运行 `python -m pytest tests/test_session_repository.py -q -k explicit`，预期四类安全错误稳定可区分。

## T24：实现恢复修复持久化

**文件：** `src/mewcode/continuity/session_repository.py`、`tests/test_session_repository.py`  
**依赖：** T15、T17、T20

**步骤：**
1. 对尾残行物理截断到最后完整行。
2. 对工具协议异常追加 replace 修复记录并报告截断。

**验证：** 运行 `python -m pytest tests/test_session_repository.py -q -k repair`，预期二次恢复得到相同合法前缀。

## T25：实现 24 小时恢复提醒

**文件：** `src/mewcode/continuity/session_repository.py`、`tests/test_session_repository.py`  
**依赖：** T20、T22

**步骤：**
1. 比较带时区活动时间与恢复时间。
2. 超过阈值追加 RESUME_NOTICE，包含两个时间且角色为 system。

**验证：** 运行 `python -m pytest tests/test_session_repository.py -q -k gap`，预期 24 小时内无提醒，超过后只插入一次。

## T26：实现过期清理与节流

**文件：** `src/mewcode/continuity/session_repository.py`、`tests/test_session_repository.py`  
**依赖：** T21、T22

**步骤：**
1. 清理超过 30 天且可取得锁的会话，损坏文件回退到 mtime。
2. 启动执行，并由 SessionBinding 暴露 24 小时节流后的维护调用；删除失败继续其他候选。

**验证：** 运行 `python -m pytest tests/test_session_repository.py -q -k cleanup`，预期活动和未过期会话保留。

## T27：实现 plan_state 提交与恢复

**文件：** `src/mewcode/continuity/session_repository.py`、`tests/test_session_repository.py`  
**依赖：** T14、T20

**步骤：**
1. 写入设置和清除 pending plan 的记录。
2. 重放时采用最后一个有效 plan_state。

**验证：** 运行 `python -m pytest tests/test_session_repository.py -q -k plan_state`，预期计划跨重启恢复并可清除。

## T28：完成会话仓库验收回归

**文件：** `tests/test_session_codec.py`、`tests/test_session_repository.py`  
**依赖：** T11–T27

**步骤：**
1. 补齐 AC4–AC15 中尚未覆盖的错误注入。
2. 确认诊断不包含历史和工具正文。

**验证：** 运行 `python -m pytest tests/test_session_codec.py tests/test_session_repository.py -q`，预期全部通过。

## Agent 与 Conversation 持久化

## T29：增加持久化停止原因和 continuity 事件

**文件：** `src/mewcode/agent/events.py`、`src/mewcode/agent/__init__.py`、`tests/test_agent_runner.py`  
**依赖：** T1

**步骤：**
1. 增加 SESSION_PERSISTENCE 和 AgentContinuityStatus。
2. 更新 AgentEvent 联合类型及公共导出。

**验证：** 运行 `python -m pytest tests/test_agent_runner.py -q -k event`，预期新事件可构造且旧事件不变。

## T30：接入可选 HistoryCommitSink

**文件：** `src/mewcode/agent/runner.py`、`tests/test_agent_runner.py`  
**依赖：** T29

**步骤：**
1. 为 start/run 增加可选 sink，不配置时走原路径。
2. 提供统一的候选提交辅助逻辑。

**验证：** 运行 `python -m pytest tests/test_agent_runner.py -q -k commit_sink`，预期无 sink 兼容且 fake 能记录提交。

## T31：持久化上下文压缩替换

**文件：** `src/mewcode/agent/runner.py`、`tests/test_agent_runner.py`  
**依赖：** T30

**步骤：**
1. Context preparation changed 时先提交替换历史。
2. 成功后更新 committed history，失败时停止。

**验证：** 运行 `python -m pytest tests/test_agent_runner.py -q -k compaction_commit`，预期主模型只在提交成功后调用。

## T32：持久化完整工具消息组

**文件：** `src/mewcode/agent/runner.py`、`tests/test_agent_runner.py`  
**依赖：** T30

**步骤：**
1. 工具批次全部配对后构造候选历史。
2. 先提交，再进入下一次模型迭代。

**验证：** 运行 `python -m pytest tests/test_agent_runner.py -q -k tool_commit`，预期一个批次一次提交且无孤立结果。

## T33：持久化自然最终回答与失败停止

**文件：** `src/mewcode/agent/runner.py`、`tests/test_agent_runner.py`  
**依赖：** T30

**步骤：**
1. Direct、Plan finalization 和 Execute 最终回答均先提交。
2. sink 异常映射为 SESSION_PERSISTENCE，不提交候选历史。

**验证：** 运行 `python -m pytest tests/test_agent_runner.py -q -k "final_commit or persistence_failure"`，预期不会继续调用 Provider。

## T34：让 Conversation 接受恢复状态与会话绑定

**文件：** `src/mewcode/conversation.py`、`tests/test_conversation.py`  
**依赖：** T20、T27、T30

**步骤：**
1. 从 SessionState 初始化消息和 PendingPlan。
2. 使用空会话适配器保持旧构造方式兼容。

**验证：** 运行 `python -m pytest tests/test_conversation.py -q -k "initial or compatibility"`，预期恢复状态可查询，旧测试不需磁盘。

## T35：接入 Plan/Execute 状态持久化

**文件：** `src/mewcode/conversation.py`、`tests/test_conversation.py`、`tests/test_session_integration.py`  
**依赖：** T33、T34

**步骤：**
1. Plan 成功后提交 pending plan。
2. Execute 仅在成功后清除；失败和取消保留。

**验证：** 运行 `python -m pytest tests/test_conversation.py tests/test_session_integration.py -q -k plan`，预期重启后 `/do` 可用。

## T36：持久化手动 compact

**文件：** `src/mewcode/conversation.py`、`tests/test_context_integration.py`、`tests/test_session_integration.py`  
**依赖：** T34

**步骤：**
1. compact changed 时先提交压缩历史。
2. 提交成功后替换内存消息，失败保持原历史。

**验证：** 运行 `python -m pytest tests/test_context_integration.py tests/test_session_integration.py -q -k compact`，预期 replace 可在重启后重放。

## 记忆模型、索引与事务

## T37：定义记忆模型与配置校验

**文件：** `src/mewcode/continuity/memory_models.py`、`tests/test_memory_models.py`  
**依赖：** T1

**步骤：**
1. 定义 scope、category、note、entry、turn、mutation、plan 和 prompt view。
2. 校验 priority、大小、mutation 数和输出预算。

**验证：** 运行 `python -m pytest tests/test_memory_models.py -q -k models`，预期非法边界均被拒绝。

## T38：实现笔记 frontmatter 往返

**文件：** `src/mewcode/continuity/memory_store.py`、`tests/test_memory_store.py`  
**依赖：** T37

**步骤：**
1. 使用安全 YAML 解析固定 frontmatter 和 Markdown 正文。
2. 验证版本、ID、scope、category、时间和正文大小。

**验证：** 运行 `python -m pytest tests/test_memory_store.py -q -k note_codec`，预期四类笔记逐项往返。

## T39：实现索引编解码与排序

**文件：** `src/mewcode/continuity/memory_store.py`、`tests/test_memory_store.py`  
**依赖：** T38

**步骤：**
1. 生成固定 frontmatter 和单行 Markdown 条目。
2. 转义摘要并按 priority、updated_at、note_id 排序。

**验证：** 运行 `python -m pytest tests/test_memory_store.py -q -k index_codec`，预期重复生成字节一致。

## T40：实现单作用域索引预算

**文件：** `src/mewcode/continuity/memory_store.py`、`tests/test_memory_store.py`  
**依赖：** T39

**步骤：**
1. 把 frontmatter、标题和条目计入 200 行/25KB。
2. 仅在条目边界停止，返回保留与淘汰集合。

**验证：** 运行 `python -m pytest tests/test_memory_store.py -q -k scope_budget`，预期无半条记录或悬空引用。

## T41：实现项目优先的合并 Prompt view

**文件：** `src/mewcode/continuity/memory_store.py`、`tests/test_memory_store.py`  
**依赖：** T40

**步骤：**
1. 先加入项目条目，再在剩余预算加入用户条目。
2. 在内容中标记参考知识不得覆盖人工指令。

**验证：** 运行 `python -m pytest tests/test_memory_store.py -q -k prompt_view`，预期合并仍不超过总限制。

## T42：实现回合清洗与秘密识别

**文件：** `src/mewcode/continuity/sanitization.py`、`tests/test_memory_store.py`  
**依赖：** T37

**步骤：**
1. 清理控制字符、内部边界、API key、Bearer、私钥和常见凭据。
2. 对超长助手文本做带标记首尾裁剪并优先保留用户文本。

**验证：** 运行 `python -m pytest tests/test_memory_store.py -q -k sanitize`，预期敏感样本和完整大输出不残留。

## T43：实现 mutation 语义校验

**文件：** `src/mewcode/continuity/memory_store.py`、`tests/test_memory_store.py`  
**依赖：** T37、T38、T42

**步骤：**
1. 新建由运行时分配 ID；更新/删除仅能引用同 scope 现有项。
2. 校验摘要、正文、priority、秘密和 mutation 数。

**验证：** 运行 `python -m pytest tests/test_memory_store.py -q -k mutation`，预期任一非法 mutation 拒绝整份计划。

## T44：实现双锁与事务准备

**文件：** `src/mewcode/continuity/memory_store.py`、`tests/test_memory_store.py`  
**依赖：** T3、T43

**步骤：**
1. 按规范路径顺序取得两个 memory lock。
2. 创建邻接暂存、备份和不含正文的事务日志。

**验证：** 运行 `python -m pytest tests/test_memory_store.py -q -k transaction_prepare`，预期锁顺序稳定且不同卷路径不被跨卷移动。

## T45：实现事务提交与同步失败回滚

**文件：** `src/mewcode/continuity/memory_store.py`、`tests/test_memory_store.py`  
**依赖：** T44

**步骤：**
1. 原子替换笔记和索引并写提交标记。
2. 在各替换点注入错误，利用备份恢复全旧状态。

**验证：** 运行 `python -m pytest tests/test_memory_store.py -q -k transaction_rollback`，预期每个失败点无混合索引。

## T46：实现崩溃事务恢复

**文件：** `src/mewcode/continuity/memory_store.py`、`tests/test_memory_store.py`  
**依赖：** T45

**步骤：**
1. 未提交日志回滚，已提交日志补齐全新状态。
2. 清理残留暂存和备份，校验固定目标与校验和。

**验证：** 运行 `python -m pytest tests/test_memory_store.py -q -k transaction_recovery`，预期模拟重启只观察到全旧或全新。

## T47：实现索引加载恢复与禁写回退

**文件：** `src/mewcode/continuity/memory_store.py`、`tests/test_memory_store.py`  
**依赖：** T39、T46

**步骤：**
1. 加载前恢复事务，索引缺失或损坏时从有效笔记重建。
2. 无法安全恢复时返回旧/空 view 并禁用写入。

**验证：** 运行 `python -m pytest tests/test_memory_store.py -q -k recovery_fallback`，预期正常对话可使用安全 view。

## T48：完成 MemoryStore 验收回归

**文件：** `tests/test_memory_store.py`、`tests/test_memory_models.py`  
**依赖：** T37–T47

**步骤：**
1. 补齐 AC16–AC20、AC25、AC28–AC29。
2. 验证所有路径和错误消息不包含秘密或正文。

**验证：** 运行 `python -m pytest tests/test_memory_models.py tests/test_memory_store.py -q`，预期全部通过。

## 记忆更新器与后台管理

## T49：构造无工具记忆更新请求

**文件：** `src/mewcode/continuity/memory_updater.py`、`tests/test_memory_updater.py`  
**依赖：** T37、T42

**步骤：**
1. 构造固定 Prompt、两级索引和 MemoryTurn 数据。
2. 设置 tools=None、max_output_tokens=4096，并标记输入不是指令。

**验证：** 运行 `python -m pytest tests/test_memory_updater.py -q -k request`，预期请求不含工具和被排除消息。

## T50：实现更新响应收集器

**文件：** `src/mewcode/continuity/memory_updater.py`、`tests/test_memory_updater.py`  
**依赖：** T49

**步骤：**
1. 收集文本和 usage，要求唯一自然完成。
2. 拒绝工具调用、截断、空响应和 Provider 错误。

**验证：** 运行 `python -m pytest tests/test_memory_updater.py -q -k collector`，预期所有失败无重试。

## T51：实现严格边界与 JSON parser

**文件：** `src/mewcode/continuity/memory_updater.py`、`tests/test_memory_updater.py`  
**依赖：** T50

**步骤：**
1. 要求唯一 memory_update 边界且边界外为空。
2. 解析版本和 mutation 字段，拒绝未知或缺失字段。

**验证：** 运行 `python -m pytest tests/test_memory_updater.py -q -k parser`，预期空 mutation 可通过，畸形计划整体失败。

## T52：增加更新容量预检

**文件：** `src/mewcode/continuity/memory_updater.py`、`tests/test_memory_updater.py`  
**依赖：** T42、T49

**步骤：**
1. 使用现有 TokenEstimator 估算完整更新请求。
2. 无法安全容纳时跳过 Provider 并产生安全失败。

**验证：** 运行 `python -m pytest tests/test_memory_updater.py -q -k capacity`，预期超限时 Provider 调用数为零。

## T53：完成 MemoryUpdater 验收回归

**文件：** `tests/test_memory_updater.py`  
**依赖：** T49–T52

**步骤：**
1. 覆盖重复、纠正、作用域、删除和无操作脚本响应。
2. 验证一次更新最多一个 Provider 请求。

**验证：** 运行 `python -m pytest tests/test_memory_updater.py -q`，预期 AC17–AC18、AC23–AC24 通过。

## T54：实现 MemoryManager 初始加载和空适配器

**文件：** `src/mewcode/continuity/memory_manager.py`、`tests/test_memory_manager.py`  
**依赖：** T47、T53

**步骤：**
1. 加载 catalog 和 prompt view，保存最后有效快照。
2. 提供不创建任务的 NullMemoryManager。

**验证：** 运行 `python -m pytest tests/test_memory_manager.py -q -k initial`，预期空环境无 LLM 调用。

## T55：实现后台成功更新

**文件：** `src/mewcode/continuity/memory_manager.py`、`tests/test_memory_manager.py`  
**依赖：** T54

**步骤：**
1. schedule 创建唯一 asyncio task。
2. updater 和 store 成功后刷新 catalog 与 prompt view。

**验证：** 运行 `python -m pytest tests/test_memory_manager.py -q -k success`，预期下一次读取看到新索引。

## T56：实现失败回退和一次性诊断

**文件：** `src/mewcode/continuity/memory_manager.py`、`tests/test_memory_manager.py`  
**依赖：** T55

**步骤：**
1. 捕获更新、解析和事务错误，保留旧 view。
2. await_pending 只交付一次 warning，不重试。

**验证：** 运行 `python -m pytest tests/test_memory_manager.py -q -k failure`，预期调用数保持一次且旧索引不变。

## T57：实现等待和关闭边界

**文件：** `src/mewcode/continuity/memory_manager.py`、`tests/test_memory_manager.py`  
**依赖：** T55、T56

**步骤：**
1. await_pending 等待阻塞任务并清理引用。
2. close 等待同一任务并返回未交付诊断。

**验证：** 运行 `python -m pytest tests/test_memory_manager.py -q -k "wait or close"`，预期没有并发更新或遗失警告。

## T58：完成 MemoryManager 验收回归

**文件：** `tests/test_memory_manager.py`  
**依赖：** T54–T57

**步骤：**
1. 覆盖下一请求等待、最终回复先显示和正常退出等待。
2. 验证同一会话最多一个 pending task。

**验证：** 运行 `python -m pytest tests/test_memory_manager.py -q`，预期 AC21、AC26–AC27 通过。

## Prompt、Conversation、REPL 与 CLI

## T59：实现不可变 PromptAdditions 合并

**文件：** `src/mewcode/prompting/models.py`、`tests/test_prompt_builder.py`  
**依赖：** T10、T41

**步骤：**
1. 合并发现指令、已有 custom instructions、自动记忆和 active skill。
2. 保持稳定系统前缀不变，空内容不产生区段。

**验证：** 运行 `python -m pytest tests/test_prompt_builder.py -q`，预期顺序和缓存边界保持正确。

## T60：接入请求前等待、维护与动态 Prompt

**文件：** `src/mewcode/conversation.py`、`tests/test_conversation.py`  
**依赖：** T34、T54、T57、T59

**步骤：**
1. 普通、Plan、Execute 和 compact 前等待 pending memory。
2. 调用 session binding 的维护接口，并用最新 view 创建本轮 PromptRunContext。

**验证：** 运行 `python -m pytest tests/test_conversation.py -q -k preflight`，预期 Provider 在等待完成后才被调用。

## T61：只在自然完成后调度记忆

**文件：** `src/mewcode/conversation.py`、`tests/test_conversation.py`  
**依赖：** T55、T60

**步骤：**
1. 从用户文本和 final_text 构造 MemoryTurn。
2. 仅 StopReason.COMPLETED 调度一次；其他停止原因不调度。

**验证：** 运行 `python -m pytest tests/test_conversation.py -q -k memory_schedule`，预期所有停止原因矩阵正确。

## T62：实现 Conversation 关闭顺序

**文件：** `src/mewcode/conversation.py`、`tests/test_conversation.py`  
**依赖：** T57、T60

**步骤：**
1. 取消活动操作、等待 memory、关闭 session、关闭 context。
2. 用 finally 隔离故障并聚合安全 warning。

**验证：** 运行 `python -m pytest tests/test_conversation.py -q -k close_order`，预期每个资源恰好关闭一次。

## T63：渲染 continuity 状态

**文件：** `src/mewcode/repl.py`、`tests/test_repl.py`  
**依赖：** T29、T60

**步骤：**
1. 渲染 instructions、session、memory 前缀。
2. 显示新建/恢复的安全 ID 与标题，不输出正文。

**验证：** 运行 `python -m pytest tests/test_repl.py -q -k continuity`，预期状态与模型文本分行且可区分。

## T64：增加 CLI 会话参数

**文件：** `src/mewcode/cli.py`、`tests/test_repl.py`  
**依赖：** T11

**步骤：**
1. 增加 `--new` 和 `--resume ID` 互斥参数。
2. 转换为 SessionOpenRequest，并更新帮助文本。

**验证：** 运行 `python -m pytest tests/test_repl.py -q -k "new or resume"`，预期合法参数正确、冲突返回 argparse 错误。

## T65：装配指令与持久会话

**文件：** `src/mewcode/cli.py`、CLI 相关现有测试  
**依赖：** T10、T22–T27、T34、T64

**步骤：**
1. 创建 paths、加载 instruction snapshot、维护并打开 session。
2. 把初始状态和 binding 注入 Conversation，输出启动诊断。

**验证：** 运行 `python -m pytest tests/test_repl.py tests/test_conversation.py -q -k startup`，预期自动、新建和指定路径装配正确。

## T66：装配 MemoryManager

**文件：** `src/mewcode/cli.py`、CLI 相关现有测试  
**依赖：** T54、T65

**步骤：**
1. 复用活动 Provider 初始化 store、updater 和 manager。
2. 记忆初始化失败时以空/旧 view 继续并输出 warning。

**验证：** 运行 `python -m pytest tests/test_repl.py tests/test_memory_manager.py -q -k wiring`，预期无额外配置字段。

## T67：完善启动失败与资源关闭

**文件：** `src/mewcode/cli.py`、`tests/test_repl.py`  
**依赖：** T62、T65、T66

**步骤：**
1. 在部分初始化失败时关闭 session、context、memory 和 MCP。
2. 指定恢复错误返回 1，清理 warning 不改变成功退出码。

**验证：** 运行 `python -m pytest tests/test_repl.py -q -k "shutdown or startup_error"`，预期资源按逆序释放。

## 集成、文档与全量验证

## T68：验证 Prompt 优先级和无额外调用

**文件：** `tests/test_continuity_integration.py`  
**依赖：** T59–T67

**步骤：**
1. 同时提供冲突的三层指令、项目记忆和用户记忆。
2. 验证动态 Prompt 顺序、参考声明和空环境零额外 LLM。

**验证：** 运行 `python -m pytest tests/test_continuity_integration.py -q -k prompt`，预期 AC22 与 N21 通过。

## T69：验证恢复会话的上下文压缩

**文件：** `tests/test_session_integration.py`、`tests/test_context_integration.py`  
**依赖：** T31、T36、T65

**步骤：**
1. 恢复超过安全容量的历史并触发一次自动压缩。
2. 验证 replace 先落盘，失败或仍超限时主模型不调用。

**验证：** 运行 `python -m pytest tests/test_session_integration.py tests/test_context_integration.py -q -k restored_capacity`，预期 AC12、AC31 通过。

## T70：验证双 Provider 工具恢复

**文件：** `tests/test_continuity_integration.py`  
**依赖：** T17、T24、T65

**步骤：**
1. 生成 OpenAI 与 Anthropic 的完整和损坏工具历史。
2. 恢复后交给对应 fake Provider，比较合法前缀和诊断。

**验证：** 运行 `python -m pytest tests/test_continuity_integration.py -q -k provider_parity`，预期 AC11、AC31 对等。

## T71：验证异步下一轮一致性

**文件：** `tests/test_continuity_integration.py`、`tests/fakes.py`  
**依赖：** T58、T60、T61

**步骤：**
1. 阻塞后台更新并确认最终回复已显示。
2. 发起下一轮，确认 Provider 等待并收到刚更新索引。

**验证：** 运行 `python -m pytest tests/test_continuity_integration.py -q -k next_turn`，预期 AC21、AC23、AC27 通过。

## T72：实现完整重启端到端场景

**文件：** `tests/test_continuity_integration.py`  
**依赖：** T68–T71

**步骤：**
1. 执行新建、工具任务、记忆更新、退出、隔日恢复和下一请求。
2. 验证历史、时间提醒、指令和项目优先索引同时进入模型。

**验证：** 运行 `python -m pytest tests/test_continuity_integration.py -q -k end_to_end`，预期 AC36 通过。

## T73：补齐安全、清理和流式性能验收

**文件：** `tests/test_continuity_integration.py`、`tests/test_session_repository.py`、`tests/test_memory_store.py`  
**依赖：** T72

**步骤：**
1. 覆盖路径大小写、符号链接、秘密、锁竞争和删除失败。
2. 大量会话扫描时验证仅选中历史进入内存，不读取真实用户目录。

**验证：** 运行 `python -m pytest tests/test_continuity_integration.py tests/test_session_repository.py tests/test_memory_store.py -q -k "security or streaming or cleanup"`，预期 AC29–AC35 通过。

## T74：更新 README

**文件：** `README.md`  
**依赖：** T64–T73

**步骤：**
1. 说明三层指令、include、会话参数、JSONL、自动恢复和 30 天清理。
2. 说明两级记忆、异步一致性、文件位置、隐私边界和暂不支持事项。

**验证：** 运行 `python -m pytest tests/test_repl.py tests/test_config.py -q`，并人工核对 README 示例与 CLI 帮助一致。

## T75：运行完整回归与静态检查

**文件：** 全部改动文件  
**依赖：** T1–T74

**步骤：**
1. 运行完整测试并修复所有回归。
2. 检查工作树、文档格式、秘密样本和无关改动。

**验证：** 运行 `python -m pytest -q`、`git diff --check`，预期全部通过且没有实现范围外改动。

## 执行顺序

```text
T1 -> T2 -> T5
T3 -> T4
T1,T2 -> T6 -> T7 -> T8 -> T9 -> T10

T1,T3,T11 -> T12 -> T13 -> T14 -> T15
T12 -> T16 -> T17
T14 -> T18
T2,T3,T13 -> T19 -> T20 -> T21
T15,T17,T18,T21 -> T22 -> T23 -> T24 -> T25 -> T26
T14,T20 -> T27 -> T28

T1 -> T29 -> T30 -> T31,T32,T33
T20,T27,T30 -> T34 -> T35,T36

T1 -> T37 -> T38 -> T39 -> T40 -> T41
T37 -> T42
T38,T42 -> T43 -> T44 -> T45 -> T46 -> T47 -> T48
T37,T42 -> T49 -> T50 -> T51
T42,T49 -> T52 -> T53
T47,T53 -> T54 -> T55 -> T56 -> T57 -> T58

T10,T41 -> T59
T34,T57,T59 -> T60 -> T61,T62
T29,T60 -> T63
T11 -> T64
T10,T22-T27,T34,T64 -> T65 -> T66 -> T67

T59-T67 -> T68
T31,T36,T65 -> T69
T17,T24,T65 -> T70
T58,T60,T61 -> T71
T68-T71 -> T72 -> T73 -> T74 -> T75
```

可并行组：

- T3–T4 与 T6–T10 可并行。
- T16–T17 与 T18 可并行。
- 会话仓库 T19–T28 与记忆模型 T37–T48 在基础类型完成后可并行。
- MemoryUpdater T49–T53 可与事务 T44–T48 后半段并行。
- T68、T69、T70、T71 在各自依赖满足后可并行。

## 提交检查点

按逻辑组提交，而不是每个微任务单独提交：

1. T1–T10：基础设施与三层指令。
2. T11–T28：JSONL 会话仓库。
3. T29–T36：Agent/Conversation 持久化接入。
4. T37–T58：自动记忆、事务和后台管理。
5. T59–T67：Prompt、REPL 与 CLI 装配。
6. T68–T75：端到端验收与文档。
