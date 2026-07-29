# MewCode 初版纯对话能力 Checklist

> 每一项通过运行代码或观察行为来验证，聚焦系统行为。

## 实现完整性

- [ ] MewCode 可以作为 Python 包导入，且 `python -m mewcode` 有可执行入口（验证：运行 `python -m compileall src`，期望编译通过；运行 `python -m mewcode`，期望进入启动流程或输出配置错误）
- [ ] 默认配置路径为用户目录下的 `~/.mewcode/config.yaml`（验证：无配置文件时运行 `python -m mewcode`，期望错误提示包含该路径或明确指向默认配置）
- [ ] YAML 配置支持顶层 `active` 与 `profiles`，并能根据 active 选择 profile（验证：运行 `python -m pytest tests/test_config.py`，期望 active 选择测试通过）
- [ ] 每个 profile 支持 `name`、`protocol`、`model`、`base_url`、`api_key`、`thinking` 六个字段，且 `thinking` 可缺省为关闭（验证：运行 `python -m pytest tests/test_config.py`，期望字段校验和默认值测试通过）
- [ ] `api_key` 只通过 `env:VAR_NAME` 解析，环境变量缺失时给出清晰错误（验证：运行 `python -m pytest tests/test_config.py`，期望 api_key 错误路径测试通过）
- [ ] REPL 可以显示提示符、接收普通输入、忽略空输入，并识别 `/exit` 与 `/quit`（验证：运行 `python -m pytest tests/test_repl.py`，期望 REPL 控制测试通过）
- [ ] 会话在当前进程内维护多轮历史，并在 provider 成功后保存用户消息和完整助手回复（验证：运行 `python -m pytest tests/test_conversation.py`，期望多轮历史测试通过）
- [ ] provider 失败时不会把不完整助手回复写入历史（验证：运行 `python -m pytest tests/test_conversation.py`，期望失败回滚测试通过）

## Provider 与流式行为

- [ ] Provider 层提供统一的文本片段流，REPL 不依赖 Anthropic 或 OpenAI 原始事件（验证：运行 `python -m pytest tests/test_conversation.py tests/test_repl.py`，期望 fake provider 流式测试通过）
- [ ] Anthropic profile 会转换为 Messages streaming 请求，并逐段输出最终回答文本（验证：运行 `python -m pytest tests/test_providers.py`，期望 Anthropic 普通流式测试通过）
- [ ] Anthropic `thinking: true` 会先尝试 adaptive thinking，且设置 omitted display，不向终端输出 thinking 内容（验证：运行 `python -m pytest tests/test_providers.py`，期望 adaptive thinking 参数与输出过滤测试通过）
- [ ] Anthropic adaptive thinking 不支持时，会回退到 manual thinking 1024 token 预算并重试一次（验证：运行 `python -m pytest tests/test_providers.py`，期望 fallback 测试通过）
- [ ] OpenAI profile 会通过 Responses API `stream=True` 获取流式事件，并只输出 `response.output_text.delta` 文本（验证：运行 `python -m pytest tests/test_providers.py`，期望 OpenAI Responses 测试通过）
- [ ] 切换 Anthropic 与 OpenAI profile 不改变 REPL 用户输入流程（验证：运行 `python -m pytest tests/test_providers.py tests/test_repl.py`，期望 provider 工厂和 REPL fake provider 测试通过）

## 错误、安全与边界

- [ ] 配置文件缺失、active 无效、字段缺失、未知 protocol、api_key 环境变量缺失时，程序输出 `Error:` 开头的用户可读错误并返回非零退出码（验证：运行 `python -m pytest tests/test_config.py tests/test_repl.py`，期望错误路径测试通过）
- [ ] 错误提示、README 和示例配置不包含真实 API key（验证：运行 `rg -n "sk-|ANTHROPIC_API_KEY=.*[^)]|OPENAI_API_KEY=.*[^)]" README.md examples tests src`，期望没有真实密钥；示例中只出现 env 变量名）
- [ ] SDK 异常或 provider 错误会被包装成用户可读 `ProviderError`，不输出原始堆栈作为主要反馈（验证：运行 `python -m pytest tests/test_providers.py tests/test_repl.py`，期望 provider 错误测试通过）
- [ ] 第一版不会执行工具调用、shell 命令、文件读取写入或代码编辑 agent 行为（验证：运行 `rg -n "subprocess|os\\.system|open\\(|Path\\(.*write|write_text|tool" src tests`，人工确认命中只属于配置读取、测试夹具或文档说明，不是 agent 行为）
- [ ] Ctrl+C 会结束前台程序并返回 130（验证：运行 `python -m pytest tests/test_repl.py`，期望 KeyboardInterrupt 入口测试通过；必要时手工运行后按 Ctrl+C 观察退出）

## 编译与测试

- [ ] 所有源码和测试文件可编译（验证：运行 `python -m compileall src tests`，期望无错误）
- [ ] 全部单元测试通过且默认不调用真实 API（验证：运行 `python -m pytest`，期望全部通过；测试中使用 fake provider 或 fake SDK client）
- [ ] 包入口可以离线运行到配置加载阶段（验证：运行 `python -m mewcode`，在无配置时看到 `Error:` 开头的配置提示）
- [ ] 示例配置格式可被配置加载器解析（验证：运行配置加载相关测试，或用临时环境变量和 `examples/config.yaml` 调用配置加载器，期望能返回 active profile）

## 端到端场景

- [ ] 场景 1：无配置启动 -> 程序输出清晰配置错误并退出（验证：在没有 `~/.mewcode/config.yaml` 的环境中运行 `python -m mewcode`，期望 stderr 以 `Error:` 开头且进程非零退出）
- [ ] 场景 2：fake provider 两轮对话 -> 第二轮请求包含第一轮上下文（验证：运行 `python -m pytest tests/test_conversation.py`，期望 fake provider 记录到完整历史）
- [ ] 场景 3：fake provider 流式回复 -> 终端逐段打印文本（验证：运行 `python -m pytest tests/test_repl.py`，期望 stdout 收到多个片段且按顺序拼接）
- [ ] 场景 4：Anthropic 配置 + 真实 API key -> 完成一次流式对话，thinking 开启时终端只显示最终回答文本（验证：手工配置 `~/.mewcode/config.yaml` 和 `ANTHROPIC_API_KEY` 后运行 `python -m mewcode`，输入问题，观察流式最终回答；此项需要真实 Anthropic API 访问）
- [ ] 场景 5：OpenAI 配置 + 真实 API key -> 通过 Responses API 完成一次流式对话（验证：手工配置 `~/.mewcode/config.yaml` 和 `OPENAI_API_KEY` 后运行 `python -m mewcode`，输入问题，观察流式最终回答；此项需要真实 OpenAI API 访问）

## 自检

- `spec.md` 的 AC1-AC13 都至少对应一个 checklist 条目。
- 每一项都有运行命令或可观察行为。
- 条目聚焦用户行为、配置行为、provider 行为和安全边界，不依赖具体函数重命名。
- 至少包含一个完整端到端场景，并区分离线 fake 验收和真实 API 手工验收。
