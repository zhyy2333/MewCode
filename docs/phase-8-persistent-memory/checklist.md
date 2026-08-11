# 项目知识、会话恢复与长期记忆 Checklist

> 每项都通过运行测试或观察外部行为验证。检查结果关注系统行为，不依赖具体内部实现。

## 实现完整性

- [x] 三层人工指令能够加载并进入首个模型请求。（验证：运行 `python -m pytest tests/test_instruction_loader.py tests/test_prompt_builder.py -q`，预期全部通过）
- [x] 持久会话能够新建、追加、关闭和跨进程恢复。（验证：运行 `python -m pytest tests/test_session_codec.py tests/test_session_repository.py tests/test_session_integration.py -q`，预期全部通过）
- [x] 用户级与项目级笔记能够加载、更新并生成索引。（验证：运行 `python -m pytest tests/test_memory_models.py tests/test_memory_store.py tests/test_memory_updater.py -q`，预期全部通过）
- [x] 后台记忆任务与 Conversation 生命周期正确集成。（验证：运行 `python -m pytest tests/test_memory_manager.py tests/test_conversation.py -q`，预期全部通过）
- [x] CLI、REPL、ContextManager、AgentRunner 与双 Provider 集成可用。（验证：运行 `python -m pytest tests/test_repl.py tests/test_agent_runner.py tests/test_context_integration.py tests/test_continuity_integration.py -q`，预期全部通过）

## 分层项目指令

- [x] AC1：同时提供三层指令时，首个请求按项目本地、项目根、用户级顺序包含全部非空内容和来源标签；缺失入口不阻止启动，运行中修改只在重启后生效。（验证：运行 `python -m pytest tests/test_instruction_loader.py -q -k priority`，观察快照和重载断言通过）
- [x] AC2：相对引用、重复引用、直接/间接环路、超过 5 层、父目录、绝对路径、符号链接和缺失文件均得到确定处理；有效内容继续加载，警告不含正文。（验证：运行 `python -m pytest tests/test_instruction_loader.py -q -k include`，预期全部场景通过）
- [x] AC3：项目级 include 不能离开项目根，用户级 include 不能离开用户配置根，相同引用在两个作用域独立解析。（验证：运行 `python -m pytest tests/test_instruction_loader.py -q -k sandbox`，预期所有越界读取在发生前被拒绝）

## 会话写入与元信息

- [x] AC4：固定同一秒连续新建多个会话时，所有 ID 都匹配 `YYYYMMDD-HHMMSS-xxxx` 且唯一。（验证：运行 `python -m pytest tests/test_session_repository.py -q -k id`，预期无碰撞）
- [x] AC5：普通和工具型多轮历史按序写入单行 JSONL；最后一行写入中断后，此前完整记录仍能恢复。（验证：运行 `python -m pytest tests/test_session_codec.py tests/test_session_repository.py -q -k "roundtrip or partial"`，预期只丢失最后残行）
- [x] AC6：不存在独立 meta 文件时，流式扫描仍得到稳定的 ID、标题、消息数和最后活动时间，列表结果不含完整正文。（验证：运行 `python -m pytest tests/test_session_codec.py tests/test_session_repository.py -q -k summary`，预期重复扫描结果一致）
- [x] AC7：模拟追加失败后，既有 JSONL 逐字不变，没有半条有效记录，并出现安全的持久化失败状态。（验证：运行 `python -m pytest tests/test_session_repository.py tests/test_agent_runner.py -q -k persistence_failure`，预期后续 Provider 不被调用）

## 启动恢复与修复

- [x] AC8：默认启动恢复 30 天内最近可恢复会话；无候选时新建；`--new` 强制新建；`--resume ID` 只恢复指定会话；参数冲突在模型调用前报错。（验证：运行 `python -m pytest tests/test_session_repository.py tests/test_repl.py -q -k "auto or explicit or resume"`）
- [x] AC9：默认候选不可恢复时继续尝试下一个；显式指定的不存在、过期、占用或损坏会话明确失败且不回退。（验证：运行 `python -m pytest tests/test_session_repository.py -q -k explicit`）
- [x] AC10：JSONL 开头、中间和末尾的坏 JSON、非法结构及未知版本被跳过，其余记录继续恢复并报告跳过数量。（验证：运行 `python -m pytest tests/test_session_codec.py -q -k malformed`）
- [x] AC11：缺失结果、孤立结果、ID 不符和半个多工具批次均从最早异常组截断；OpenAI 与 Anthropic fake 接受修复后的历史。（验证：运行 `python -m pytest tests/test_session_codec.py tests/test_continuity_integration.py -q -k "pair or provider_parity"`）
- [x] AC12：恢复历史超限时只调用一次压缩；成功后主请求使用压缩历史，失败或仍超限时主模型调用数为零。（验证：运行 `python -m pytest tests/test_session_integration.py tests/test_context_integration.py -q -k restored_capacity`）
- [x] AC13：间隔不超过 24 小时没有提醒；超过 24 小时出现包含两端时间的 system 提醒，立即重启不重复插入。（验证：运行 `python -m pytest tests/test_session_repository.py -q -k gap`）
- [x] AC14：一个进程持有会话锁时，另一进程不能恢复或追加；释放后可恢复，文件中没有交错写入。（验证：运行 `python -m pytest tests/test_locking.py tests/test_session_repository.py -q -k lock`）
- [x] AC15：启动和 24 小时维护检查清理超过 30 天且未占用的会话；活动与未过期会话保留，单个删除失败不影响其他候选。（验证：运行 `python -m pytest tests/test_session_repository.py -q -k cleanup`）

## 自动笔记与索引

- [x] AC16：四类自动笔记均保存为独立 Markdown，并带有效版本、ID、作用域、类别、优先级、创建/更新时间和来源会话。（验证：运行 `python -m pytest tests/test_memory_models.py tests/test_memory_store.py -q -k note`）
- [x] AC17：重复偏好被合并、纠正内容替换旧结论、项目知识进入项目级、跨项目偏好进入用户级，索引中没有同时有效的冲突项。（验证：运行 `python -m pytest tests/test_memory_updater.py tests/test_memory_store.py -q -k mutation`）
- [x] AC18：没有长期价值的回合可返回空更新，笔记与索引字节保持不变。（验证：运行 `python -m pytest tests/test_memory_updater.py tests/test_memory_manager.py -q -k noop`）
- [x] AC19：用户级和项目级索引各自不超过 200 行及 25KB，每个条目都指向存在且可解析的笔记。（验证：运行 `python -m pytest tests/test_memory_store.py -q -k scope_budget`）
- [x] AC20：两份索引合并超限时，总注入仍不超过 200 行及 25KB，项目级完整条目优先，用户级条目不被截断。（验证：运行 `python -m pytest tests/test_memory_store.py -q -k prompt_view`）
- [x] AC21：上一轮更新阻塞时最终回复已显示，但下一轮 Provider 尚未调用；释放后下一轮 Prompt 包含新索引。（验证：运行 `python -m pytest tests/test_continuity_integration.py -q -k next_turn`）
- [x] AC22：人工指令与自动笔记冲突时，Prompt 明确显示人工指令优先，自动记忆仅作为参考知识。（验证：运行 `python -m pytest tests/test_prompt_builder.py tests/test_continuity_integration.py -q -k prompt`）
- [x] AC23：自然最终回复恰好触发一次更新；工具 Loop 结束后也只触发一次；取消、错误、截断、空响应、迭代上限和未执行工具均不触发。（验证：运行 `python -m pytest tests/test_conversation.py tests/test_continuity_integration.py -q -k memory_schedule`）
- [x] AC24：记忆请求只含允许的回合材料和有界索引，tools 为 None，一轮最多请求一次，且不会产生新的 Agent Loop 或递归更新。（验证：运行 `python -m pytest tests/test_memory_updater.py -q -k request`）
- [x] AC25：分别在笔记写入、旧笔记删除、索引校验和索引替换处注入失败，恢复后只能观察到全旧或全新状态，没有悬空引用。（验证：运行 `python -m pytest tests/test_memory_store.py -q -k "transaction_rollback or transaction_recovery"`）
- [x] AC26：更新失败只警告一次、不重试，下一轮使用旧索引继续正常调用主模型。（验证：运行 `python -m pytest tests/test_memory_manager.py tests/test_continuity_integration.py -q -k failure`）
- [x] AC27：自然回复后立即退出时，关闭流程等待更新；成功保存新笔记，失败保留旧状态且仍能退出。（验证：运行 `python -m pytest tests/test_memory_manager.py tests/test_conversation.py -q -k close`）
- [x] AC28：索引超限时按优先级、更新时间和稳定 ID 确定性淘汰；重复运行字节一致，Markdown 和引用完整。（验证：运行 `python -m pytest tests/test_memory_store.py -q -k "scope_budget or deterministic"`）
- [x] AC29：API key、疑似令牌、私钥、内部分析、完整大工具输出和临时路径不会出现在笔记、索引、标题、状态或错误中。（验证：运行 `python -m pytest tests/test_memory_store.py tests/test_continuity_integration.py -q -k "sanitize or security"`）

## 兼容性、安全与容量

- [x] AC30：Windows 与类 Unix 的大小写、父目录、绝对路径、目录联接和符号链接越界均在读取前拒绝。（验证：运行 `python -m pytest tests/test_instruction_loader.py tests/test_continuity_integration.py -q -k sandbox`）
- [x] AC31：恢复首个请求的容量计算包含三层指令、两级索引、工具定义和历史；OpenAI 与 Anthropic fake 得到等价压缩或拒绝结果。（验证：运行 `python -m pytest tests/test_context_integration.py tests/test_continuity_integration.py -q -k "capacity or provider_parity"`）
- [x] AC32：扫描大量会话时逐文件处理，只有最终选中会话的完整历史进入活动内存。（验证：运行 `python -m pytest tests/test_session_repository.py tests/test_continuity_integration.py -q -k streaming`）
- [x] AC33：全新项目和空用户配置无需迁移即可运行，现有 Direct、Plan/Execute、权限、工具、MCP、Prompt 和 Context 测试保持通过。（验证：运行 `python -m pytest tests/test_agent_runner.py tests/test_conversation.py tests/test_permission_integration.py tests/test_mcp_integration.py tests/test_prompt_builder.py tests/test_context_integration.py -q`）
- [x] AC34：新建、自动恢复、指定恢复、坏行、截断、恢复压缩、时间提醒、过期清理和记忆失败的终端状态可区分，且不混入模型回答。（验证：运行 `python -m pytest tests/test_repl.py tests/test_continuity_integration.py -q -k status`）
- [x] AC35：完整测试不需要 API key、网络、真实时间等待或真实用户目录，所有时间、ID、文件故障、锁竞争和 Provider 响应均可控。（验证：清除相关 API key 后运行 `python -m pytest -q`，预期测试仍全部通过且无网络请求）

## 端到端场景

- [x] AC36：执行“新项目启动 → 三层指令加载 → 工具任务 → 用户级和项目级记忆更新 → 正常退出 → 隔日自动恢复 → 下一请求”，恢复模型同时获得合法历史、时间提醒、项目优先有界索引和正确排序的人工指令。（验证：运行 `python -m pytest tests/test_continuity_integration.py -q -k end_to_end`）
- [x] Plan 恢复场景：`/plan` 成功后退出并恢复，`/do` 可执行原计划；Execute 失败时计划仍保留，成功后清除。（验证：运行 `python -m pytest tests/test_session_integration.py tests/test_conversation.py -q -k plan`）
- [x] 手动压缩恢复场景：`/compact` 成功后退出并恢复，只看到压缩后的逻辑历史；压缩或持久化失败时仍看到原历史。（验证：运行 `python -m pytest tests/test_session_integration.py tests/test_context_integration.py -q -k compact`）

## 构建与回归

- [x] 项目可安装且模块可导入。（验证：运行 `python -m pip install -e .[dev]` 和 `python -c "import mewcode; import mewcode.continuity"`，预期退出码为 0）
- [x] 完整测试通过。（验证：运行 `python -m pytest -q`，预期零失败、零错误）
- [x] 没有空白错误或意外生成文件。（验证：运行 `git diff --check` 和 `git status --short`，预期无空白错误，改动仅限 task.md 文件清单所列范围）
- [x] README 与实际 CLI 一致。（验证：运行 `mewcode --help`，对照 README 检查 `--new`、`--resume`、三层指令和记忆路径）
