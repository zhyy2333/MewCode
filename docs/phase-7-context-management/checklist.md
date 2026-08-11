# 上下文管理与两层压缩 Checklist

> 每一项都通过运行命令或观察系统行为验证，不依赖逐行阅读实现代码。

## 实现完整性

- [x] 上下文包的公共模块均可导入，且不存在缺失导出或循环导入（验证：运行 `python -c "from mewcode.context import ContextConfig, ContextManager, ContextStatus, TokenEstimator"`，期望退出码为 0）。
- [x] Provider、Agent、Conversation、REPL 和 CLI 均能使用新的上下文公共契约（验证：运行 `python -m compileall -q src`，期望无语法或导入编译错误）。
- [x] 上下文包不反向依赖 Agent、Conversation 或 REPL（验证：运行 `rg -n "mewcode\.(agent|conversation|repl)" src/mewcode/context`，期望无匹配）。
- [x] 不新增未批准的第三方运行时依赖（验证：运行 `git diff -- pyproject.toml`，期望依赖列表没有新增项）。
- [x] 47 个实施任务对应的新增和修改文件均已完成（验证：按 `task.md` 文件清单运行 `rg --files src/mewcode/context tests | sort`，期望七个上下文模块和六个上下文测试文件全部存在）。

## 配置与 Token 估算

- [x] AC1：未配置窗口时使用 128000，自定义合法值生效，非法值在 Provider 调用前报错（验证：运行 `python -m pytest tests/test_config.py -k context_window -q`，期望全部通过）。
- [x] AC2：首次完整估算、usage 锚定和后续增量修正符合规则（验证：运行 `python -m pytest tests/test_context_estimator.py -k "anchor or incremental" -q`，期望全部通过）。
- [x] 请求足迹覆盖稳定/动态 Prompt、消息和排序后的工具定义（验证：运行 `python -m pytest tests/test_context_estimator.py -k footprint -q`，期望任一输入部分变化都会改变足迹）。
- [x] 中文、英文和混合文本采用批准的加权字符规则（验证：运行 `python -m pytest tests/test_context_estimator.py -k character -q`，期望 ASCII 四字符约一 Token、非 ASCII 一字符约一 Token）。
- [x] OpenAI 与 Anthropic 都提供归一化的完整上下文 input usage（验证：运行 `python -m pytest tests/test_providers.py -k "context_input_tokens or cache_usage" -q`，期望缓存与非缓存场景全部通过）。

## 轻量工具结果压缩

- [x] AC3：同一请求同时需要轻量和重量处理时，先完成工具存盘，再判断整体阈值，最后才调用主模型（验证：运行 `python -m pytest tests/test_context_integration.py -k preflight_order -q`，期望调用记录顺序为轻量存盘、重量摘要、主模型）。
- [x] AC4：单体超过 8K 时完整内容存盘，模型只收到大小、路径和不超过 1K 的首尾预览（验证：运行 `python -m pytest tests/test_context_tool_results.py -k "single or preview" -q`，期望 8000/8001 边界及内容对比通过）。
- [x] AC5：批次超过 12K 时按原始大小降序、执行索引升序稳定选择，最终保留量不超过预算（验证：运行 `python -m pytest tests/test_context_tool_results.py -k batch -q`，期望全部通过）。
- [x] AC6：轻量压缩后两种 Provider 的工具调用和结果仍完整配对（验证：运行 `python -m pytest tests/test_context_integration.py -k tool_pairing -q`，期望 OpenAI 与 Anthropic 请求均合法）。
- [x] AC7：任一必需存盘失败时不调用后续模型、不提交部分占位并保持原历史（验证：运行 `python -m pytest tests/test_context_tool_results.py tests/test_agent_runner.py -k "atomic or tool_compaction_failure" -q`，期望全部通过）。
- [x] 工具存盘 JSON 保留成功状态、完整内容、错误和 metadata（验证：运行 `python -m pytest tests/test_context_archive.py -k tool_result -q`，期望存盘内容与原 `ToolResult` 逐项一致）。

## 会话归档与生命周期

- [x] AC8：会话中可读取归档，正常退出删除当前目录，下次启动清理崩溃遗留目录（验证：运行 `python -m pytest tests/test_context_archive.py -k "cleanup or close" -q`，期望全部通过）。
- [x] 同工作区的另一个活动会话目录不会被启动清理删除（验证：运行 `python -m pytest tests/test_context_archive.py -k active_session -q`，期望持锁目录保留）。
- [x] Windows 与类 Unix 文件锁分支均可重复验证（验证：运行 `python -m pytest tests/test_context_archive.py -k "windows_lock or unix_lock" -q`，期望全部通过）。
- [x] 归档写入使用原子发布，失败后没有被历史引用的半成品文件（验证：运行 `python -m pytest tests/test_context_archive.py -k "atomic or rollback" -q`，期望全部通过）。

## 重量压缩触发与保留区

- [x] AC9：自动边界严格按 `context_window - max_output_tokens - 13000` 计算，边界以下不摘要、达到边界先摘要（验证：运行 `python -m pytest tests/test_context_manager.py -k automatic_threshold -q`，期望全部通过）。
- [x] AC10：`/compact` 使用当前 Profile、8192 输出、空工具集合和 3K 余量（验证：运行 `python -m pytest tests/test_context_manager.py -k manual_request -q`，期望请求属性全部匹配）。
- [x] AC11：低于自动阈值时 `/compact` 仍强制摘要；无早期区时只报告无需压缩，且命令不进入历史（验证：运行 `python -m pytest tests/test_conversation.py tests/test_context_manager.py -k "compact_force or no_compaction_needed" -q`，期望全部通过）。
- [x] AC12：近期区同时满足约 10K 和至少 5 条，并且不拆开工具交换组（验证：运行 `python -m pytest tests/test_context_summary.py -k recent -q`，期望 Token、条数和分组边界全部通过）。
- [x] AC13：近期消息保持原对象和原顺序，早期完整历史可按索引路径读取（验证：运行 `python -m pytest tests/test_context_summary.py -k compaction_success -q`，期望近期逐项相同且归档原文一致）。

## 摘要生成与历史替换

- [x] AC14：摘要 Prompt 禁止工具、要求先草稿后正式摘要、逐字保留有效约束并禁止脑补文件细节（验证：运行 `python -m pytest tests/test_context_summary.py -k prompt -q`，期望全部强制语义存在）。
- [x] AC15：有效响应只保留八章节正式摘要；草稿、截断和结构错误均不进入历史或状态（验证：运行 `python -m pytest tests/test_context_summary.py -k "parser_success or parser_rejects" -q`，期望全部通过）。
- [x] AC16：有效约束逐字出现，已完成或被替代要求允许概括，全部原文可从归档恢复（验证：运行 `python -m pytest tests/test_context_integration.py -k active_constraints -q`，期望脚本化摘要与归档对比通过）。
- [x] AC17：连续两次重量压缩后活动历史只有一份最新摘要和一条新边界（验证：运行 `python -m pytest tests/test_context_summary.py -k rolling -q`，期望旧摘要和旧边界均被替换）。
- [x] AC18：摘要与近期原文之间始终存在要求重新读取、禁止臆测的边界消息（验证：运行 `python -m pytest tests/test_context_integration.py -k boundary -q`，期望后续每个主请求都包含该语义）。
- [x] 摘要文本 delta 和 Provider 内部块不会作为 Agent 文本事件输出（验证：运行 `python -m pytest tests/test_context_summary.py tests/test_repl.py -k "collector or context_status" -q`，期望终端输出中找不到草稿标记）。

## 失败、熔断与恢复

- [x] AC19：Provider 错误、输出截断、空响应、结构错误和取消均保持历史原子；只有非用户取消增加失败计数（验证：运行 `python -m pytest tests/test_context_summary.py tests/test_context_manager.py -k "rollback or failure_matrix or cancel" -q`，期望全部通过）。
- [x] AC20：连续三次失败后自动熔断；第四个危险请求不调用摘要或主模型，安全请求仍可运行（验证：运行 `python -m pytest tests/test_context_manager.py -k automatic_failure -q`，期望 Provider 调用次数与状态机一致）。
- [x] AC21：熔断后 `/compact` 只探测一次，失败保持开路，成功替换历史并恢复自动摘要（验证：运行 `python -m pytest tests/test_context_manager.py -k manual_recovery -q`，期望全部通过）。
- [x] 自动压缩后仍超限时保存有效新摘要，但当前主请求在调用前停止且不自动二次摘要（验证：运行 `python -m pytest tests/test_context_manager.py -k still_over_limit -q`，期望一次摘要、零次主调用）。
- [x] Agent 在摘要或主流程取消时停止活动 Provider 流并只提交合法历史（验证：运行 `python -m pytest tests/test_agent_runner.py tests/test_conversation.py -k "context_cancel or committed_history" -q`，期望无未处理异步任务）。

## 用户反馈与命令行为

- [x] AC22：轻量存盘、自动压缩、手动压缩、无需压缩、失败、熔断和恢复均有可区分状态，且不包含完整结果或草稿（验证：运行 `python -m pytest tests/test_repl.py -k "compact or context_status" -q`，期望批准的状态文本全部出现且敏感正文不出现）。
- [x] `/compact` 带参数时只显示用法错误，不把文本发送给模型（验证：运行 `python -m pytest tests/test_repl.py -k compact_arguments -q`，期望 Provider 调用数为 0）。
- [x] `/exit`、`/quit`、EOF、异常和 KeyboardInterrupt 都在事件循环关闭前清理上下文会话（验证：运行 `python -m pytest tests/test_repl.py -k "closes_conversation or keyboard_interrupt" -q`，期望所有关闭路径通过）。

## 兼容性、安全与确定性

- [x] AC23：OpenAI 与 Anthropic 得到等价压缩语义，未触发压缩的既有行为保持不变（验证：运行 `python -m pytest tests/test_context_integration.py -k parity -q` 以及 `python -m pytest tests/test_providers.py tests/test_tool_providers.py -q`，期望全部通过）。
- [x] AC24：Provider 无 usage 时仍能靠字符估算触发保护，重新获得 usage 后正确重锚（验证：运行 `python -m pytest tests/test_context_estimator.py tests/test_context_manager.py -k "missing_usage or reanchor" -q`，期望全部通过）。
- [x] AC25：轻量处理不调用 LLM；每次重量预检最多一次无工具摘要调用（验证：运行 `python -m pytest tests/test_context_manager.py -k call_budget -q`，期望调用计数严格匹配）。
- [x] AC26：并发只读工具、存盘/摘要取消和不同 Provider 消息格式不产生部分历史、孤立结果或不稳定顺序（验证：运行 `python -m pytest tests/test_context_integration.py -k concurrency -q`，期望重复运行结果一致）。
- [x] AC27：恶意工具名称和结果不能控制路径，状态、异常和文件名不泄露完整秘密文本（验证：运行 `python -m pytest tests/test_context_archive.py tests/test_context_tool_results.py -k security -q`，期望全部通过）。
- [x] AC28：删除拒绝、文件占用和损坏目录不会阻塞其余清理，警告不含存盘正文（验证：运行 `python -m pytest tests/test_context_archive.py -k cleanup_failure -q`，期望有限时间内完成）。
- [x] 相同历史、usage 和配置重复运行得到相同轻量选择、预览和消息切分（验证：重复运行 `python -m pytest tests/test_context_tool_results.py tests/test_context_summary.py -k deterministic -q` 两次，期望结果均通过）。

## 编译、测试与文档

- [x] 所有上下文单元测试通过（验证：运行 `python -m pytest tests/test_context_estimator.py tests/test_context_archive.py tests/test_context_tool_results.py tests/test_context_summary.py tests/test_context_manager.py -q`，期望全部通过）。
- [x] Agent、Conversation、REPL、配置和 Provider 回归测试通过（验证：运行 `python -m pytest tests/test_agent_runner.py tests/test_conversation.py tests/test_repl.py tests/test_config.py tests/test_providers.py tests/test_tool_providers.py -q`，期望全部通过）。
- [x] README 和示例配置说明窗口默认值、两层阈值、`/compact`、熔断及存盘生命周期（验证：运行 `rg -n "context_window|128000|/compact|熔断|\.mewcode/context" README.md examples/config.yaml`，期望所有主题均有匹配）。
- [x] 项目未配置独立 lint 工具时，以编译检查和完整测试作为静态/行为门禁（验证：运行 `python -m compileall -q src tests`，期望退出码为 0）。

## 端到端场景

- [x] AC29：长对话中大工具结果先存盘，累计历史再生成滚动摘要，模型按边界重新读取并完成任务，所有请求均低于容量边界（验证：运行 `python -m pytest tests/test_context_integration.py -k long_conversation -q`，期望完整链路通过）。
- [x] 手动场景：低于自动阈值执行 `/compact`，历史缩短且命令不入历史，随后普通对话继续工作（验证：运行 `python -m pytest tests/test_context_integration.py -k manual_end_to_end -q`，期望完整链路通过）。
- [x] 故障场景：三次无效摘要触发熔断，危险请求被拒绝，手动成功摘要恢复后任务继续（验证：运行 `python -m pytest tests/test_context_integration.py -k circuit_end_to_end -q`，期望完整链路通过）。
- [x] 生命周期场景：产生工具与历史归档后正常退出，再次启动看不到遗留目录且其他活动会话未受影响（验证：运行 `python -m pytest tests/test_context_integration.py -k lifecycle_end_to_end -q`，期望完整链路通过）。
- [x] AC30：完整测试不使用真实 API key、外部网络或精确 tokenizer，并可重复通过（验证：清除 LLM key 后连续运行两次 `python -m pytest -q`，期望两次均全部通过且无网络依赖失败）。
- [x] 测试完成后不存在未清理临时文件、活动会话目录或未处理异步任务（验证：完整测试结束后检查 `.mewcode/context`，期望不存在测试遗留；pytest 输出中没有 pending task 或 unclosed client 警告）。
