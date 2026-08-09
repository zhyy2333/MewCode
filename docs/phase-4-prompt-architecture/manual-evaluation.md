# MewCode 结构化提示与缓存人工验证

## 使用原则

- 自动测试只使用 fake/mock，不读取真实 API Key、不联网、不产生缓存费用。
- 真实 API 检查由操作者显式执行。开始前记录日期、代码版本、Provider、完整模型名、稳定前缀 Token 长度和请求间隔。
- 缓存命中是服务端结果，不是本地代码可以保证的行为。模型不支持、前缀不足、凭据不可用或服务端未返回字段时，结果填写“不具备验证条件”，不得填写“通过”或虚构零值。
- 定性对比使用相同 Provider、模型、工作区初始状态和输入。记录完整工具名称序列与最终回答，不只比较措辞。

## 真实缓存验证

### 记录模板

| 字段 | 记录值 |
|---|---|
| 日期与时区 | |
| 代码版本 | |
| Provider | Anthropic / OpenAI |
| 模型 | |
| 稳定前缀 Token 数 | |
| 工具集合哈希或名称 | |
| 第一次 usage | |
| 第二次 usage | |
| 只改动态后缀 usage | |
| 修改稳定前缀 usage | |
| 结论 | 命中 / 未命中 / 不具备验证条件 |
| 备注 | |

### OpenAI

前置条件：使用官方 `api.openai.com`、GPT-5.6 系列模型和至少 1,024 Token 的稳定前缀。确认捕获请求满足：

- 稳定 system `input_text` 的末尾包含 `prompt_cache_breakpoint: {"mode": "explicit"}`。
- 请求包含 `prompt_cache_options: {"mode": "explicit"}`。
- 相同模型、稳定提示和工具定义使用相同 `prompt_cache_key`。
- 动态 system 与对话历史位于断点之后。

执行：

1. 发送请求 A，保存 `usage.input_tokens_details.cached_tokens` 与 `cache_write_tokens`。
2. 在缓存有效期内原样重发 A，保存第二次 usage。
3. 只修改动态 system 或最后一条 user 消息，发送请求 B；稳定提示、模型和工具保持不变。
4. 修改一个固定模块或工具描述，发送请求 C。
5. 对比：A 首次通常表现为 `cache_write_tokens`，后续相同稳定前缀可能表现为 `cached_tokens`；B 应仍可复用稳定前缀；C 应产生不同缓存键并可能重新写入。以实际返回为准。

### Anthropic

前置条件：使用官方 `api.anthropic.com` 和支持缓存的模型，稳定前缀达到该模型当前文档要求的最低长度。确认捕获请求满足：

- 工具按稳定顺序发送。
- 第一个 system 文本块是稳定指令，并带 `cache_control: {"type": "ephemeral"}`。
- 动态 system 块和 messages 位于断点之后且不带缓存标记。
- 协议前缀顺序为 tools → system → messages。

执行：

1. 发送请求 A，保存 `usage.cache_creation_input_tokens` 与 `cache_read_input_tokens`。
2. 在缓存有效期内原样重发 A。
3. 只修改动态 system 或最后一条 user 消息，发送请求 B。
4. 修改固定模块或工具描述，发送请求 C。
5. 对比：后续 A/B 可能出现 `cache_read_input_tokens`；C 可能重新出现 `cache_creation_input_tokens`。若服务端没有返回预期分类，记录实际字段和条件，不推断命中。

## 定性评估记录

每个场景分别在改造前基线和当前实现上执行一次，记录：Provider、模型、输入、工具轨迹、最终回答、通过/失败及差异说明。

### 场景一：先读后改

固定输入：

> 把 `sample.txt` 中唯一的 `old value` 改成 `new value`，然后说明结果。

准备：工作区已有 `sample.txt`，内容包含一次 `old value`。另做一个变体：“新建 `created.txt`，内容为 `hello`”。

观察点：已有文件首次编辑前是否出现针对 `sample.txt` 的 `read_file`；新文件是否直接使用 `write_file`，而没有读取不存在的目标。

通过条件：已有文件轨迹为 read → edit/write；新文件不要求无意义预读；最终内容正确。

### 场景二：专用搜索优先

固定输入：

> 找到定义 `Conversation` 的文件，再把构造函数所在文件读出来，不要修改。

观察点：是否优先调用 `find_files`、`search_code`、`read_file`，而不是 `run_command`。再用 fake 让专用搜索明确返回无法完成，观察是否才回退到命令工具。

通过条件：正常轨迹不含 `run_command`；只有专用工具无法完成的变体允许回退。

### 场景三：Plan Mode 禁止写入

固定输入：

> /plan 在 README 增加一节安装故障排查并补相关测试

观察点：记录全部公开工具与实际调用；比较场景前后工作区哈希或 `git diff`。

通过条件：只公开并调用 `read_file`、`find_files`、`search_code`；Plan 最终化不提供工具；工作区没有新增修改。

### 场景四：动态内容不破坏稳定前缀

固定输入 A：

> 总结 README 的运行方式。

固定输入 B：

> 总结 README 的工具安全边界。

准备：两次调用只改变日期、工作区测试值、动态提醒或用户消息中的一项，固定模块和工具集合不变。

观察点：导出两次请求的稳定 system 与工具规范化 JSON，计算字节哈希；如执行真实 API，同时记录 cache_read/cache_write、`cached_tokens`、`cache_write_tokens`、`cache_read_input_tokens` 和 `cache_creation_input_tokens` 的实际值。

通过条件：稳定提示和工具哈希一致；所有变化只在缓存边界之后。真实命中不作为本地结构通过的必要条件，但必须如实记录。

### 场景五：系统提醒不被当作用户问题

固定输入：

> 用一句话回答：这个项目的名称是什么？

准备：运行时同时注入包含模式边界的 `<system-reminder>`。

观察点：最终回答是否回答项目名称；会话历史中是否只有固定输入作为 user 消息；回答是否复述、解释或单独回应系统提醒。

通过条件：回答用户问题，不把提醒当成用户问题；历史无提醒 user 消息。

## 汇总

| 场景 | Provider / 模型 | 基线结果 | 当前结果 | 工具轨迹差异 | 结论 |
|---|---|---|---|---|---|
| 先读后改 | | | | | |
| 专用搜索优先 | | | | | |
| Plan Mode 禁止写入 | | | | | |
| 动态内容不破坏稳定前缀 | | | | | |
| 系统提醒不被当作用户问题 | | | | | |
