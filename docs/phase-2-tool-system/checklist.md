# MewCode 工具系统 Checklist

> 每一项通过运行代码或观察行为验证，聚焦系统行为。

## 实现完整性
- [ ] 工具注册中心能列出六个内置工具：`read_file`、`write_file`、`edit_file`、`run_command`、`find_files`、`search_code`（验证：运行 `python -m pytest tests/test_tools_base.py`，期望内置 registry 测试通过）
- [ ] 工具注册中心能按名称查找工具，未知工具返回结构化失败结果（验证：运行 `python -m pytest tests/test_tools_base.py`，期望查找和未知工具测试通过）
- [ ] 工具定义能导出为 Anthropic API 格式（验证：运行 `python -m pytest tests/test_tools_base.py`，期望 `to_anthropic_tools()` 测试通过）
- [ ] 工具定义能导出为 OpenAI Responses API 格式（验证：运行 `python -m pytest tests/test_tools_base.py`，期望 `to_openai_tools()` 测试通过）
- [ ] Provider 基础接口产出统一事件流，纯文本响应被包装为文本事件（验证：运行 `python -m pytest tests/test_providers.py`，期望 provider 文本事件测试通过）
- [ ] Conversation 在无工具调用时保持原有纯聊天流式输出和多轮历史（验证：运行 `python -m pytest tests/test_conversation.py`，期望无工具回归测试通过）
- [ ] CLI 启动时创建当前工作区和内置工具注册中心，并注入 Conversation（验证：运行 `python -m pytest tests/test_repl.py`，期望 CLI 注入测试通过）

## 工具行为
- [ ] `read_file` 能读取工作区内 UTF-8 文本文件内容（验证：运行 `python -m pytest tests/test_file_tools.py`，期望 read_file 成功测试通过）
- [ ] `read_file` 对越界路径返回失败结果（验证：运行 `python -m pytest tests/test_file_tools.py tests/test_workspace.py`，期望越界读取测试通过）
- [ ] `write_file` 能在工作区内写入文本并创建父目录（验证：运行 `python -m pytest tests/test_file_tools.py`，期望 write_file 成功测试通过）
- [ ] `write_file` 对越界路径失败且不创建文件（验证：运行 `python -m pytest tests/test_file_tools.py`，期望越界写入测试通过）
- [ ] `edit_file` 在原文恰好出现一次时完成替换（验证：运行 `python -m pytest tests/test_file_tools.py`，期望唯一替换测试通过）
- [ ] `edit_file` 在原文出现 0 次或多次时失败且不修改文件（验证：运行 `python -m pytest tests/test_file_tools.py`，期望 0 次和多次匹配测试通过）
- [ ] `run_command` 能在工作区内执行安全命令并返回 stdout、stderr、exit_code（验证：运行 `python -m pytest tests/test_command_tool.py`，期望安全命令测试通过）
- [ ] `run_command` 超时时返回结构化超时结果（验证：运行 `python -m pytest tests/test_command_tool.py`，期望超时测试通过）
- [ ] `run_command` 拦截明显危险命令且不执行（验证：运行 `python -m pytest tests/test_command_tool.py`，期望危险命令测试通过）
- [ ] `find_files` 按 glob 返回工作区内相对路径，跳过隐藏/缓存目录（验证：运行 `python -m pytest tests/test_search_tools.py`，期望 find_files 测试通过）
- [ ] `search_code` 返回匹配文件、行号和片段，并支持 `path` 限制（验证：运行 `python -m pytest tests/test_search_tools.py`，期望 search_code 测试通过）
- [ ] 工具输出过大时会截断并标记 `truncated`（验证：运行 `python -m pytest tests/test_file_tools.py tests/test_search_tools.py tests/test_command_tool.py`，期望截断测试通过）

## 安全边界
- [ ] 工作区路径解析拒绝 `..` 越界、绝对路径越界和符号链接越界（验证：运行 `python -m pytest tests/test_workspace.py`，期望路径安全测试通过）
- [ ] 命令始终在工作区根目录执行，不支持 shell 会话保持（验证：运行 `python -m pytest tests/test_command_tool.py`，期望 cwd 测试通过）
- [ ] 默认测试不执行危险命令（验证：运行危险命令扫描 `rg -n "rm -rf /|format C:|shutdown|del /s" src tests README.md docs`，人工确认命中只在拦截规则、测试字符串或文档说明中）
- [ ] README、示例和测试不包含真实 API key（验证：运行 `rg -n "sk-|ANTHROPIC_API_KEY=.*[^)]|OPENAI_API_KEY=.*[^)]" README.md examples tests src`，期望没有真实密钥命中）

## Provider 与工具调用
- [ ] Anthropic provider 能从 fake 流式事件中解析工具名称和 JSON 参数碎片（验证：运行 `python -m pytest tests/test_tool_providers.py`，期望 Anthropic tool call 测试通过）
- [ ] Anthropic provider 能把 `ToolResult` 转成 Anthropic tool_result 消息（验证：运行 `python -m pytest tests/test_tool_providers.py`，期望 Anthropic tool_result 测试通过）
- [ ] Anthropic provider 的普通文本流式和 thinking 行为保持不退化（验证：运行 `python -m pytest tests/test_providers.py`，期望上一章 provider 测试通过）
- [ ] OpenAI provider 能从 fake Responses API 事件中解析工具名称和 JSON 参数碎片（验证：运行 `python -m pytest tests/test_tool_providers.py`，期望 OpenAI tool call 测试通过）
- [ ] OpenAI provider 能把 `ToolResult` 转成 OpenAI tool result 输入项（验证：运行 `python -m pytest tests/test_tool_providers.py`，期望 OpenAI tool_result 测试通过）
- [ ] 工具参数 JSON 无法解析时不会崩溃，会形成可回灌的失败结果（验证：运行 `python -m pytest tests/test_tool_providers.py tests/test_tools_base.py`，期望坏 JSON/坏参数测试通过）

## 会话与 REPL
- [ ] 模型请求已注册工具时，Conversation 执行工具、回灌结果，并进行一次最终回复调用（验证：运行 `python -m pytest tests/test_tool_conversation.py`，期望工具成功编排测试通过）
- [ ] 模型请求未知工具、工具失败或工具超时时，Conversation 回灌失败结果并继续最终回复（验证：运行 `python -m pytest tests/test_tool_conversation.py`，期望失败回灌测试通过）
- [ ] 每轮最多执行一次工具调用；第二阶段再次请求工具时不执行，并输出 skipped 状态（验证：运行 `python -m pytest tests/test_tool_conversation.py`，期望工具上限测试通过）
- [ ] REPL 对文本事件继续流式打印（验证：运行 `python -m pytest tests/test_repl.py`，期望文本流式回归测试通过）
- [ ] REPL 显示简短工具状态，不显示参数 JSON 碎片或完整工具结果（验证：运行 `python -m pytest tests/test_repl.py`，期望工具状态输出测试通过）
- [ ] 无配置启动仍输出清晰错误并返回非零退出码（验证：使用临时 HOME 运行 `python -m mewcode`，期望输出 `Error: Config file not found...` 和非零退出码）

## 编译与测试
- [ ] 源码和测试可编译（验证：运行 `python -m compileall src tests`，期望无错误）
- [ ] 全部单元测试通过，且不需要真实 Anthropic/OpenAI API key（验证：运行 `python -m pytest`，期望全部通过）
- [ ] 包入口仍可离线运行到配置加载阶段（验证：运行无配置启动场景，期望行为同上一章）

## 端到端场景
- [ ] 场景 1：fake provider 请求 `read_file` -> 工具执行 -> 工具结果回灌 -> 最终回复输出（验证：运行 `python -m pytest tests/test_tool_conversation.py`，期望 read_file 端到端编排测试通过）
- [ ] 场景 2：fake provider 请求越界 `read_file` -> 工具失败结果回灌 -> 最终回复解释失败（验证：运行 `python -m pytest tests/test_tool_conversation.py`，期望越界失败编排测试通过）
- [ ] 场景 3：fake provider 第一阶段请求工具，第二阶段再次请求工具 -> 第二次不执行并显示上限提示（验证：运行 `python -m pytest tests/test_tool_conversation.py tests/test_repl.py`，期望 skipped 状态可见）
- [ ] 场景 4：无工具调用的普通聊天 -> 行为保持上一章纯对话（验证：运行 `python -m pytest tests/test_conversation.py tests/test_repl.py`，期望纯对话回归测试通过）

## 自检
- `spec.md` 的 AC1-AC18 都至少有一个 checklist 条目。
- 每项都有运行命令或可观察行为。
- 离线测试覆盖默认验收，不要求真实 API key。
- 端到端场景覆盖成功工具、失败工具、二次工具上限和无工具回归。
