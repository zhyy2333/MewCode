# MewCode MCP 客户端验收 Checklist

> 每一项都必须通过运行代码、自动化测试或观察外部行为来验证。验收时先执行验证，再将 `[ ]` 改为 `[x]` 并在条目后记录实际证据；不能仅凭代码阅读判定通过。

## 验收规则

- 使用 MCP `2025-11-25` 作为唯一协议基线。
- 自动化场景只使用本地 stdio fake、内存 Transport、`httpx.MockTransport` 和 fake Provider，不访问真实 LLM、外部 MCP Server 或公网。
- 任何涉及 secret 的断言均使用唯一哨兵值，并要求该值不出现在结果、warning、异常、终端输出或测试快照中。
- 超时测试使用注入的短时限，不依赖真实的 30/120/5 秒等待。
- 端到端场景必须覆盖配置输入、协议交互、权限、Agent 工具结果回灌和资源清理，不得只直接调用底层适配器。

## A. 配置发现与合并

- [x] **C01 / AC1 — 无 MCP 配置向后兼容。** 使用不含 `mcp_servers` 的现有用户配置启动后，程序正常进入 REPL，模型 Profile 与六个内置工具保持原行为，且没有 MCP 后台线程。（验证：运行 `pytest -q tests/test_repl.py::test_cli_without_mcp_config_preserves_existing_tool_and_exit_behavior`，期望 `1 passed`。）

- [x] **C02 / AC2 — 两层配置按 Server 整项覆盖。** 用户层声明 A/B、项目层声明 B/C 后，启用集合为 A、项目版本 B、C，项目 B 不继承用户 B 未重写的字段。（验证：运行 `pytest -q tests/test_mcp_config.py::test_project_server_replaces_whole_user_entry tests/test_mcp_config.py::test_distinct_servers_are_merged`，期望 `2 passed`。）

- [x] **C03 / AC3 — stdio 配置、环境和无 shell 启动正确。** fake 子进程观察到原始 argv、工作区 cwd、父环境继承及配置覆盖；同一值中的多个 `${VAR}` 均展开，shell 元字符没有被二次解释。（验证：运行 `pytest -q tests/test_mcp_config.py::test_expands_env_and_header_values tests/test_mcp_transports.py::test_stdio_uses_exec_argv_merged_env_and_workspace_cwd tests/test_mcp_transports.py::test_stdio_never_uses_shell`，期望 `3 passed`。）

- [x] **C04 / AC4 — HTTP 自定义 header 与保留 header 边界正确。** 展开后的自定义 header 随请求发送；大小写变体也不能覆盖协议 header；URL、command 和 args 中的 `${VAR}` 保持字面值。（验证：运行 `pytest -q tests/test_mcp_config.py::test_reserved_headers_are_ignored_case_insensitively tests/test_mcp_config.py::test_command_args_and_url_are_not_expanded tests/test_mcp_transports.py::test_http_posts_one_jsonrpc_message_with_protocol_accept_headers`，期望 `3 passed`。）

- [x] **C05 / AC5 — 文件级错误致命、条目级错误隔离。** 非法 YAML、非法根结构或非 map `mcp_servers` 阻止启动并指出文件；同一合法文件中的坏 Server 只被 warning 跳过，健康 Server 仍被解析。（验证：运行 `pytest -q tests/test_mcp_config.py::test_file_level_yaml_error_is_fatal tests/test_mcp_config.py::test_invalid_stdio_entries_are_isolated tests/test_mcp_config.py::test_invalid_http_entries_are_isolated`，期望 `3 passed`。）

- [x] **C06 / AC6 — 缺失变量只禁用对应 Server 且不泄密。** 未定义变量使该 Server 被跳过，warning 可包含 Server 与变量名，但不能包含其它已展开 secret。（验证：运行 `pytest -q tests/test_mcp_config.py::test_missing_or_malformed_variable_skips_server tests/test_mcp_config.py::test_diagnostics_do_not_leak_secret_values`，期望 `2 passed`。）

## B. 传输、握手与 JSON-RPC

- [x] **C07 / AC7 — 多 Server 启动有界且相互隔离。** 健康 Server 与无响应 Server 同时启动时，健康工具被保留；挂起 Server 到独立 deadline 后被跳过，CLI 仍能进入 REPL。（验证：运行 `pytest -q tests/test_mcp_manager.py::test_servers_start_concurrently tests/test_mcp_manager.py::test_hung_server_hits_startup_deadline tests/test_mcp_manager.py::test_one_server_failure_does_not_hide_healthy_tools`，期望 `3 passed`。）

- [x] **C08 / AC8 — stdio 使用 UTF-8 newline JSON，stderr 不干扰。** fake 能逐行收发多条 JSON-RPC；大量 stderr 被持续消费但不进入协议或输出，也不会造成死锁。（验证：运行 `pytest -q tests/test_mcp_transports.py::test_stdio_sends_utf8_newline_json tests/test_mcp_transports.py::test_stdio_receives_multiple_messages_in_order tests/test_mcp_transports.py::test_stdio_stderr_is_drained_without_leaking_content`，期望 `3 passed`。）

- [x] **C09 / AC9 — HTTP JSON 流程携带版本和 Session。** initialize、tools/list、tools/call 使用 JSON response 时均成功；initialize 之后的请求携带固定版本和 Server 返回的 Session id。（验证：运行 `pytest -q tests/test_mcp_transports.py::test_http_delivers_json_response tests/test_mcp_transports.py::test_http_session_and_protocol_headers_are_reused`，期望 `2 passed`。）

- [x] **C10 / AC10 — 请求范围 SSE 可用且不建立长期 GET。** initialize/list/call 任一请求使用 SSE 时能交付对应响应与反向请求；整个场景没有独立 GET、恢复流或 `Last-Event-ID`。（验证：运行 `pytest -q tests/test_mcp_transports.py::test_http_sse_parses_comments_and_multiline_data tests/test_mcp_transports.py::test_http_sse_delivers_server_request_before_final_response tests/test_mcp_transports.py::test_http_never_opens_standalone_get_stream`，期望 `3 passed`。）

- [x] **C11 / AC11 — 握手顺序与能力校验严格。** Server 观察到第一条请求为 `initialize(2025-11-25)`，随后是 initialized notification，再后是 tools/list；版本不符、缺失 tools capability 或畸形响应的 Server 不注册工具。（验证：运行 `pytest -q tests/test_mcp_session.py::test_initialize_payload_and_initialized_order_are_exact tests/test_mcp_session.py::test_rejects_wrong_protocol_version tests/test_mcp_session.py::test_rejects_missing_tools_capability tests/test_mcp_session.py::test_rejects_malformed_initialize_result`，期望 `4 passed`。）

- [x] **C12 / AC12 — 并发响应按 id 单次配对。** 多个请求反序返回时各自获得正确结果；未知、重复、迟到和不可信响应不会错误完成其它 Future 或完成同一请求两次。（验证：运行 `pytest -q tests/test_mcp_jsonrpc.py::test_out_of_order_responses_pair_by_id tests/test_mcp_jsonrpc.py::test_unknown_and_duplicate_ids_are_ignored tests/test_mcp_jsonrpc.py::test_untrustworthy_response_fails_peer`，期望 `3 passed`。）

- [x] **C13 / AC13 — 只响应允许的 Server 请求。** ping 得到空成功 result；资源读取、采样及其它未协商 request 得到 JSON-RPC `-32601`；未知 notification 被消费但不执行能力。（验证：运行 `pytest -q tests/test_mcp_jsonrpc.py::test_ping_request_receives_empty_result tests/test_mcp_jsonrpc.py::test_unknown_server_request_receives_method_not_found tests/test_mcp_jsonrpc.py::test_unknown_notification_is_ignored`，期望 `3 passed`。）

- [x] **C14 / AC14 — timeout/cancel 清理 pending 并尽力通知 Server。** 超时和调用方取消都原子移除原请求，Transport 可写时发送带原 request id 的 `notifications/cancelled`；通知失败不覆盖 timeout/CancelledError；迟到响应被忽略，关闭不继续等待。（验证：运行 `pytest -q tests/test_mcp_jsonrpc.py::test_request_timeout_only_fails_that_pending_call tests/test_mcp_jsonrpc.py::test_timeout_sends_cancelled_notification_when_writable tests/test_mcp_jsonrpc.py::test_caller_cancellation_sends_cancelled_notification_best_effort tests/test_mcp_jsonrpc.py::test_late_response_after_timeout_is_ignored`，期望 `4 passed`。）

## C. 工具发现、命名与注册

- [x] **C15 / AC15 — tools/list 完整分页。** 两页发现结果全部进入快照，第二页请求携带第一页 cursor；重复或非法 cursor 有界失败而不循环。（验证：运行 `pytest -q tests/test_mcp_session.py::test_collects_all_tool_pages_with_cursor tests/test_mcp_session.py::test_repeated_cursor_fails_without_looping`，期望 `2 passed`。）

- [x] **C16 / AC16 — 公开名合法、稳定且不静默碰撞。** 合法 base 精确保留；非法或超长 base 得到满足 `^[A-Za-z0-9_-]{1,64}$` 的确定性短哈希名；重复输入结果一致，碰撞被显式报告。（验证：运行 `pytest -q tests/test_mcp_naming.py::test_legal_base_name_is_preserved tests/test_mcp_naming.py::test_invalid_name_is_normalized_with_hash tests/test_mcp_naming.py::test_long_name_is_truncated_deterministically tests/test_mcp_naming.py::test_public_name_collision_is_reported`，期望 `4 passed`。）

- [x] **C17 / AC17 — 单个坏工具不影响健康兄弟工具。** 非法、重复、与 builtin 冲突或含恶意 metadata 的定义只产生带 Server 名的 warning 并被跳过；健康定义仍可注册，metadata 始终作为 inert data。（验证：运行 `pytest -q tests/test_mcp_manager.py::test_duplicate_remote_tool_is_skipped tests/test_mcp_manager.py::test_bad_tool_does_not_remove_siblings tests/test_mcp_manager.py::test_public_name_collision_with_builtin_is_skipped tests/test_mcp_manager.py::test_malicious_tool_metadata_remains_inert_data`，期望 `4 passed`。）

- [x] **C18 / AC18 — Provider 与 ToolRegistry 无感接入。** MCP 描述和 inputSchema 出现在 OpenAI/Anthropic 工具定义中；模型返回公开名时能从统一注册表找到对应代理，不需要 Provider 专用分支。（验证：运行 `pytest -q tests/test_mcp_tools.py::test_registry_combines_builtin_and_mcp_tools_without_overwrite tests/test_mcp_tools.py::test_existing_provider_formatters_accept_mcp_tools`，期望 `2 passed`。）

- [x] **C19 / AC19 — 工具集合是启动快照。** READY 后收到 `notifications/tools/list_changed` 不改变已注册集合，也不发出新的 tools/list。（验证：运行 `pytest -q tests/test_mcp_manager.py::test_descriptors_are_sorted_and_snapshot_is_static`，期望 `1 passed`。）

- [x] **C20 / AC20 — 工具名称与 Provider 顺序确定。** 相同两层配置和相同分页结果重复启动时，公开名与 Provider 工具顺序完全相同，不依赖 YAML 或 Server 返回顺序。（验证：运行 `pytest -q tests/test_mcp_tools.py::test_provider_tool_order_is_stable_across_identical_discovery_runs`，期望 `1 passed`。）

## D. 权限、调度与调用

- [x] **C21 / AC21 — 所有 MCP 工具固定按副作用独占执行。** readOnly/destructive 等远端注解不降低安全级别；MCP 调用与其它工具同时出现时走现有独占分支并保持模型顺序。（验证：运行 `pytest -q tests/test_mcp_tools.py::test_every_mcp_tool_is_side_effect_with_static_invoke_permission tests/test_mcp_tools.py::test_mcp_tool_uses_existing_exclusive_side_effect_scheduling`，期望 `2 passed`。）

- [x] **C22 / AC22 — 权限作用于整个公开工具且先于远端调用。** deny 不产生 tools/call；once 只允许当前调用；session/permanent 对同一公开工具的不同参数继续生效，权限 key 固定为 `public_name(invoke)`。（验证：运行 `pytest -q tests/test_mcp_tools.py::test_permission_denial_prevents_mcp_server_call tests/test_permission_config.py::test_mcp_permission_scope_is_whole_public_tool tests/test_permission_targets.py::test_builds_static_tool_invoke_target`，期望 `3 passed`。）

- [x] **C23 / AC23 — 权限拒绝是普通工具失败。** Agent 收到包含公开工具名的失败结果，可继续选择其它工具或生成最终回答；REPL/Agent Loop 不终止。（验证：运行 `pytest -q tests/test_mcp_tools.py::test_permission_denial_returns_failure_and_agent_can_continue`，期望 `1 passed`。）

- [x] **C24 / AC24 — 调用使用原名、原参数和缓存 Session。** 连续两次公开工具调用向 Server 发送原始工具名与不变的 arguments object，且只出现一次进程/客户端创建、initialize 和发现流程。（验证：运行 `pytest -q tests/test_mcp_session.py::test_tools_call_uses_original_name_and_unchanged_arguments tests/test_mcp_manager.py::test_calls_reuse_cached_session_without_reinitialize`，期望 `2 passed`。）

## E. 结果、错误与隔离

- [x] **C25 / AC25 — 文本与 structuredContent 均被保留。** 多个文本 block 按原顺序出现，structuredContent 追加为确定性且可解析的 JSON，任一部分都不静默丢失。（验证：运行 `pytest -q tests/test_mcp_tools.py::test_adapts_text_blocks_in_order tests/test_mcp_tools.py::test_structured_content_is_deterministic_json`，期望 `2 passed`。）

- [x] **C26 / AC26 — 资源和二进制安全降级。** resource link/文本资源只形成含 URI、MIME、可用文本的描述且不发资源 RPC；blob/image/audio 只有省略标记，没有 Base64、文件写入或额外读取。（验证：运行 `pytest -q tests/test_mcp_tools.py::test_resource_link_and_embedded_text_are_flattened tests/test_mcp_tools.py::test_resource_blob_is_omitted_without_fetch_or_write tests/test_mcp_tools.py::test_image_audio_and_unknown_blocks_use_markers`，期望 `3 passed`。）

- [x] **C27 / AC27 — 所有调用错误被工具边界吸收。** `isError`、JSON-RPC error、HTTP error、非法响应、timeout 和连接中断均产生含 Server/公开工具上下文的失败 ToolResult，外部 payload 不被执行，Agent 后续调用仍可成功。（验证：运行 `pytest -q tests/test_mcp_tools.py::test_mcp_errors_become_failed_tool_results tests/test_mcp_tools.py::test_mcp_failure_names_server_and_public_tool_without_secrets tests/test_mcp_integration.py::test_recoverable_mcp_call_errors_do_not_stop_later_agent_calls`，期望 `3 passed`。）

- [x] **C28 / AC28 — 输出有界且所有秘密不可观察。** 超长结果按现有 20,000 字符上限截断并标记；env/header/Session 哨兵值不出现在结果、warning、状态、异常或快照。（验证：运行 `pytest -q tests/test_mcp_tools.py::test_mcp_output_is_truncated_to_existing_limit tests/test_mcp_config.py::test_diagnostics_do_not_leak_secret_values tests/test_mcp_transports.py::test_http_errors_do_not_expose_session_id tests/test_repl.py::test_cli_prints_server_warning_without_leaking_secret`，期望 `4 passed`。）

- [x] **C29 / AC29 — 初始化/运行失败后不自动恢复。** 启动失败的 Server 没有注册工具；运行期 EOF 或 Session 失效让 pending 与后续调用快速失败，启动/initialize/连接计数不再增加。（验证：运行 `pytest -q tests/test_mcp_session.py::test_fatal_transport_failure_disables_session_without_reconnect tests/test_mcp_manager.py::test_unknown_or_failed_session_call_fails_fast tests/test_mcp_integration.py::test_mixed_server_failures_are_isolated_and_never_reconnect`，期望 `3 passed`。）

- [x] **C30 / AC30 — 一个 Server 失败不污染其它能力。** 一个 MCP Server 运行期失败后，另一个 MCP Server、六个 builtin、Provider、REPL 和 Agent Loop 均继续可用。（验证：运行 `pytest -q tests/test_mcp_integration.py::test_mixed_server_failures_are_isolated_and_never_reconnect`，期望 `1 passed`，并检查该场景分别断言上述五类能力。）

## F. 关闭、兼容与资源安全

- [x] **C31 / AC31 — 所有退出路径有界清理全部客户端。** 正常退出、启动中止和用户取消均执行关闭；stdio 先关 stdin，再按 wait/terminate/kill 升级；有 Session id 的 HTTP 尝试 DELETE；一个清理失败不阻止其它 Session。（验证：运行 `pytest -q tests/test_repl.py::test_cli_closes_mcp_runtime_on_normal_exit tests/test_repl.py::test_cli_closes_partial_runtime_when_later_startup_fails tests/test_repl.py::test_cli_closes_runtime_on_keyboard_interrupt tests/test_mcp_manager.py::test_close_failure_does_not_cancel_other_sessions`，期望 `4 passed`。）

- [x] **C32 / AC32 — 关闭后没有异步或系统资源泄漏。** timeout、取消、Transport 断开和整体关闭完成后，pending、读取 task、子进程、HTTP client 与 Runtime thread 均已结束，pytest 不报告未等待 coroutine/未处理异常。（验证：运行 `pytest -q tests/test_mcp_integration.py::test_shutdown_leaves_no_mcp_process_client_pending_or_task tests/test_mcp_runtime.py::test_close_after_cancellation_has_no_live_mcp_tasks`，期望 `2 passed` 且无 asyncio resource warning。）

- [x] **C33 / AC33 — Windows 与类 Unix 关闭分支行为等价。** 两个平台分支均覆盖启动、stdin 关闭、wait、terminate、kill 和已退出竞态，获得一致的成功/超时/failure 分类。（验证：运行 `pytest -q tests/test_mcp_transports.py::test_stdio_shutdown_windows_branch tests/test_mcp_transports.py::test_stdio_shutdown_unix_branch tests/test_mcp_transports.py::test_stdio_close_escalates_to_terminate_then_kill`，期望 `3 passed`。）

- [x] **C34 / AC34 — 测试不依赖外部服务。** 在未设置真实 LLM key、没有第三方 MCP Server、HTTP 全部由 mock 拦截的环境中，完整 MCP 测试可重复通过且没有公网请求。（验证：清除测试进程中的 `OPENAI_API_KEY`、`ANTHROPIC_API_KEY` 等真实凭据后运行 T76 聚焦命令，期望全部通过；检查 stdio 只启动仓库内 fake，HTTP 只命中 MockTransport。）

- [x] **C35 / AC35 — stdio 与 HTTP 共享协议语义。** 对相同 initialize、分页、call、error 和结果脚本，两种传输得到相同的公开工具集合及 ToolResult，仅传输观测信息不同。（验证：运行 `pytest -q tests/test_mcp_integration.py::test_same_protocol_scenario_matches_across_stdio_and_http`，期望 `1 passed`。）

## G. 端到端场景

- [x] **C36 / AC36 — stdio 完整用户流程。** 从用户/项目配置合并开始，真实 fake 子进程完成启动、握手、分页、命名、Provider 选择、权限放行、两次复用调用、结果回灌、预期最终回答和退出清理。（验证：运行 `pytest -q tests/test_mcp_integration.py::test_stdio_full_flow_from_merged_config_to_final_answer_and_cleanup`，期望 `1 passed`；协议记录只含一次 initialize。）

- [x] **C37 / AC37 — Streamable HTTP 完整用户流程。** 从 `${VAR}` header 配置开始，经 initialize、Session 复用、SSE 发现、Provider 选择、权限放行、JSON call、结果回灌和预期最终回答，退出时发送 DELETE 且从未发 GET/公网请求。（验证：运行 `pytest -q tests/test_mcp_integration.py::test_http_full_flow_from_env_header_to_final_answer_and_session_delete`，期望 `1 passed`。）

- [x] **C38 / AC38 — 混合故障完整流程。** 同时配置非法、启动 timeout、运行失败和健康 Server 时，只暴露健康工具；每个失败有独立脱敏反馈；健康 MCP/builtin/Provider/REPL/Agent 持续工作；退出后全部资源清理。（验证：运行 `pytest -q tests/test_mcp_integration.py::test_mixed_server_failures_are_isolated_and_never_reconnect tests/test_mcp_integration.py::test_shutdown_leaves_no_mcp_process_client_pending_or_task`，期望 `2 passed`。）

## H. 架构与集成约束

- [x] **I01 — 单一后台 Runtime 且事件循环归属正确。** 配置多个 Server 仍只创建一个 MCP thread/loop；Manager、Session、Peer、Transport 和 pending 均只在该 loop 内访问，主线程只接收普通数据/代理。（验证：运行 `pytest -q tests/test_mcp_runtime.py::test_runtime_starts_one_background_loop_and_returns_proxies tests/test_mcp_runtime.py::test_manager_objects_remain_on_runtime_loop`，期望 `2 passed`。）

- [x] **I02 — Transport 差异不泄漏到 Session/Tool。** stdio 和 HTTP 都通过同一 JSON-RPC/Session 行为完成请求，Tool 适配器无需判断 transport kind。（验证：运行 C35 的双传输一致性测试，并运行 `python -m compileall -q src/mewcode/mcp`，期望均成功。）

- [x] **I03 — CLI 启动顺序避免无效 Provider 启动外部 Server。** Provider/Profile 校验失败时没有创建 MCP Runtime、子进程或 HTTP client；Runtime 启动后的任一后续失败均进入 finally 关闭。（验证：运行 CLI 回归场景并以 fake Runtime 记录 start/close 次数，期望 Provider 失败时 `start=0`，后续失败时 `start=1, close=1`。）

- [x] **I04 — Server 状态、pending 和关闭边界独立。** 一个 Peer fatal 只完成自己的 pending；Manager 关闭按 Session 并行收集，不因一个异常取消其它。（验证：运行 `pytest -q tests/test_mcp_jsonrpc.py::test_transport_failure_completes_all_pending tests/test_mcp_manager.py::test_close_failure_does_not_cancel_other_sessions`，期望 `2 passed`。）

- [x] **I05 — 跨线程取消只有一个终态。** Agent task 取消能到达后台 pending 并发出 best-effort cancelled notification；另一个并发调用不受影响；没有二次完成 Future。（验证：运行 `pytest -q tests/test_mcp_runtime.py::test_runtime_call_cancellation_reaches_background_pending_only tests/test_mcp_jsonrpc.py::test_cancelled_request_is_removed_without_affecting_others`，期望 `2 passed`。）

- [x] **I06 — 离线 MCP 权限规则可休眠，任意未知规则仍 fail-closed。** 配置过但启动失败的 namespace 规则可加载；不匹配配置 namespace 的未知工具仍导致配置错误。（验证：运行 `pytest -q tests/test_permission_config.py::test_allows_rule_for_configured_offline_mcp_namespace tests/test_permission_config.py::test_rejects_unknown_non_mcp_tool`，期望 `2 passed`。）

- [x] **I07 — 注册是一次性静态组合且无静默覆盖。** builtin 和 MCP proxies 一次构造最终 ToolRegistry；冲突工具被拒绝；运行期通知不能改变集合。（验证：运行 `pytest -q tests/test_mcp_tools.py::test_registry_combines_builtin_and_mcp_tools_without_overwrite tests/test_mcp_manager.py::test_descriptors_are_sorted_and_snapshot_is_static`，期望 `2 passed`。）

- [x] **I08 — 正常关闭不依赖 daemon 兜底。** Runtime close 完成 Manager 关闭、残余 task 取消、loop stop 和 thread join；重复 close 仍安全。（验证：运行 `pytest -q tests/test_mcp_runtime.py::test_runtime_close_stops_loop_and_joins_thread tests/test_mcp_runtime.py::test_runtime_close_is_idempotent_after_partial_start`，期望 `2 passed`。）

- [x] **I09 — 已批准的现有运行时模块保持不变。** Provider、Conversation、Agent、Scheduler 和 REPL 源文件没有因 MCP 实现产生 diff，MCP 只经既有 Tool/Registry/权限接口接入。（验证：运行 `git diff --name-only -- src/mewcode/providers src/mewcode/conversation.py src/mewcode/agent.py src/mewcode/scheduler.py src/mewcode/repl.py`，期望无输出。）

## I. 范围与安全边界

- [x] **S01 — 只支持批准的协议和工具能力。** 其它协议版本失败；资源、提示词、采样等反向请求只获 `-32601`；没有资源 RPC、动态工具刷新或 batch 行为。（验证：运行 C11、C13、C19、C26 对应测试，期望全部通过。）

- [x] **S02 — 不存在自动恢复或长期推送能力。** 运行失败后不启动新进程、不重新 initialize、不重连；HTTP 不发长期 GET、不恢复 SSE、不跟随 redirect。（验证：运行 `pytest -q tests/test_mcp_integration.py::test_mixed_server_failures_are_isolated_and_never_reconnect tests/test_mcp_transports.py::test_http_never_opens_standalone_get_stream tests/test_mcp_transports.py::test_http_redirects_are_not_followed`，期望 `3 passed`。）

- [x] **S03 — 不新增危险配置面。** stdio 不经 shell；TLS 使用默认校验且没有关闭校验字段；OAuth、Registry 安装、健康检查、运行时 reload 和二进制落盘配置均不被接受或实现。（验证：用这些越界字段构造 Server 配置，期望被严格字段校验跳过并 warning；再运行 C03/C05/C26 的测试，期望全部通过。）

## J. 文档、构建与测试门

- [x] **V01 — 依赖和包入口可导入。** 安装项目依赖后能导入 `httpx` 与 MCP 包，协议常量为 `2025-11-25`，消息上限为 4 MiB。（验证：运行 T01 的 `python -c` 命令，期望退出码 0。）

- [x] **V02 — 配置示例是有效且无真实 secret 的 YAML。** 示例同时包含 stdio/HTTP、`${VAR}` 与整项覆盖说明，不含真实凭据。（验证：运行 T74 的 YAML 解析命令并人工搜索 token 哨兵，期望解析成功且无凭据。）

- [x] **V03 — README 完整说明使用与边界。** 文档包含两层配置、两种 transport、变量展开、命名、权限、副作用、信任项目配置、固定版本、隔离和不自动重连。（验证：运行 `rg -n "mcp_servers|2025-11-25|Streamable HTTP|SIDE_EFFECT|自动重连" README.md`，期望五类关键说明均有匹配。）

- [x] **V04 — MCP 聚焦测试全部通过。** 新增 MCP 测试和受影响权限/REPL 测试无失败、skip/xfail 掩盖、未等待 coroutine 或 resource warning。（验证：运行 task.md T76 的完整聚焦 pytest 命令，期望退出码 0 且输出无上述 warning。）

- [x] **V05 — 全量项目回归通过。** 现有测试与新增测试共同通过，无 MCP 改动引入的回归。（验证：运行 `pytest -q`，期望退出码 0。）

- [x] **V06 — 源码与测试可编译。** Python 编译检查没有语法、导入时语法或编码错误。（验证：运行 `python -m compileall -q src tests`，期望退出码 0 且无输出。）

- [x] **V07 — lint 状态有记录。** 当前项目未配置 lint 工具；验收时重新检查 `pyproject.toml`，若仍未配置则记录 `N/A`，若开发阶段新增 lint 配置则必须运行其项目命令并要求退出码 0。（验证：检查 `[tool.*]` 与 dev dependency 中的 lint 配置，并在验收证据中记录实际结果。）

- [x] **V08 — 变更范围与用户文件完整。** git status/diff 只包含 task.md 文件清单中的实现、测试和文档；用户原有未跟踪 `hello.txt` 保持原样，没有计划外文件。（验证：运行 `git status --short` 与 `git diff --name-only`，对照 task.md 文件清单，期望范围一致。）

## 验收完成条件

- C01-C38 全部通过，确保每条 Spec 验收标准均有证据。
- I01-I09、S01-S03、V01-V08 全部通过或按条目规则记录明确的 `N/A`。
- 三个端到端场景 C36-C38 都有实际测试输出，不以底层单元测试代替。
- 若任一项失败，先修复并重新执行该项及相关回归；未重新获得通过证据前不得标记完成。

## 验收记录（2026-08-10）

- **结果：58/58 通过。** C01-C38、I01-I09、S01-S03、V01-V08 均已标记完成；V07 因项目未配置 lint 工具，按条目规则记录为 `N/A（通过）`。
- **聚焦测试：** `python -B -m pytest -q` 运行 12 个 MCP/权限/CLI 聚焦文件，结果 `209 passed in 2.06s`，无 asyncio resource warning。
- **全量回归：** `python -B -m pytest -q`，结果 `468 passed in 5.74s`。
- **无写入编译检查：** 对 `src/**/*.py` 与 `tests/**/*.py` 逐个执行内存 `compile(..., "exec")`，结果 `compiled source and tests without writing bytecode`。此前 `python -m compileall -q src tests` 也已成功；因仓库历史跟踪 `.pyc`，最终采用无写入方式避免缓存污染。
- **端到端：** stdio 完整流程、HTTP JSON/SSE/Session DELETE、双传输一致性、混合故障和关闭无泄漏测试均包含在聚焦测试并通过。
- **文档与配置：** MCP 包导入/协议常量检查、`examples/config.yaml` YAML 解析、README 关键说明搜索、`git diff --check` 均通过。
- **范围：** Provider、Conversation、Agent、Scheduler 与 REPL 源文件的定向 diff 无输出；`hello.txt` 保持原有未跟踪状态且未纳入任何操作。
- **测试启动器说明：** 当前机器的独立 `pytest.exe` 被环境中同名第三方 `tests` 包遮蔽，这是实现前已复现的环境基线；模块方式 `python -B -m pytest` 使用同一 pytest 配置并完整通过 468 项。
