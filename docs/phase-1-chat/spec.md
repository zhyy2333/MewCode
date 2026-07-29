# MewCode 初版纯对话能力 Spec

## 背景
MewCode 是一个从零开始开发的命令行 AI 助手，目标形态类似 Claude Code，但本阶段只实现终端内纯对话能力。当前项目没有已有应用代码，只有项目内 spec 流程 skill，因此第一版需要先建立最小可运行的 CLI/REPL 基础、LLM provider 抽象、YAML 配置读取和流式输出链路。

用户启动 MewCode 后进入终端 REPL，可以连续输入问题。MewCode 根据配置选择 Anthropic Claude 或 OpenAI 后端，把用户输入和当前进程内的对话历史发送给模型，并把模型回复以流式方式逐字或小片段打印到终端。第一版不包含 tool use、文件操作、代码编辑或 agent 自动执行能力。

## 目标
- 提供一个可在终端启动的 MewCode 交互式 REPL。
- 支持当前进程内的多轮对话记忆，退出后不保存历史。
- 支持通过 `~/.mewcode/config.yaml` 中的 `active` 与 `profiles` 在 Anthropic Claude 和 OpenAI 后端之间切换。
- 支持基于环境变量引用的 API key 读取。
- 统一 provider 行为，使 REPL 不依赖具体供应商协议。
- 使用流式响应打印模型输出，不等待完整回复后再一次性显示。
- 支持 Claude thinking 开关：开启时优先使用 adaptive thinking，必要时兼容旧式 manual thinking；终端只显示最终回答文本。

## 功能需求
- F1: 用户在终端启动 MewCode 后，系统进入交互式 REPL，并持续等待用户输入。
- F2: 用户输入一条问题后，系统将该问题发送给当前配置选中的 LLM 后端。
- F3: 系统以流式方式展示模型回复，在回复生成过程中持续打印新增文本，而不是等待完整回复后一次性输出。
- F4: 系统在当前进程内维护多轮对话历史；后续请求应包含此前用户与助手的对话内容，使模型能基于上下文回答。
- F5: 系统从默认用户配置文件读取 LLM 配置，并根据 `active` 选择一个启用的 profile。
- F6: 每个 profile 包含 `name`、`protocol`、`model`、`base_url`、`api_key`、`thinking` 六个配置字段，其中 `thinking` 可选。
- F7: `protocol` 支持 Anthropic Claude 和 OpenAI 两类后端。
- F8: `api_key` 通过环境变量引用取得认证密钥；缺失或无法解析时，系统给出可理解的错误信息。
- F9: 使用 Anthropic Claude 后端时，系统支持流式消息响应；当 `thinking` 开启时，系统启用 Claude thinking 能力，并只向终端展示最终回答文本。
- F10: 使用 OpenAI 后端时，系统通过 OpenAI Responses API 获取流式回答。
- F11: REPL 支持基础退出控制：用户输入 `/exit` 或 `/quit` 时退出程序，Ctrl+C 直接结束程序。
- F12: 第一版只支持纯对话，不执行工具调用、文件读取、文件写入、代码编辑或自动 agent 行为。

## 非功能需求
- N1: 流式输出应尽快展示首个可见文本片段，避免用户感知为“卡住后一次性返回”。
- N2: Provider 抽象应隐藏不同供应商的协议差异，使 REPL 只依赖统一的对话输入与流式文本输出行为。
- N3: 配置错误、认证错误、网络错误和供应商返回错误应以清晰文本提示用户，不输出原始堆栈作为主要反馈。
- N4: API key 不应在正常日志、错误提示或终端输出中明文展示。
- N5: 对话历史只保存在当前进程内存中，程序退出后不持久化。
- N6: 第一版应保持依赖和交互模型简单，优先保证可运行、可测试、可扩展到新 provider。
- N7: 程序应能在常见终端环境中运行，不依赖全屏终端控制能力。

## 不做的事
- 不做 tool use 或函数调用能力。
- 不做文件读取、文件写入、目录扫描或代码编辑能力。
- 不做自动执行 shell 命令、测试命令或构建命令的 agent 行为。
- 不做项目索引、代码库理解、检索增强或上下文自动注入。
- 不做会话持久化、历史记录管理或跨进程恢复。
- 不做全屏 TUI、鼠标交互、消息列表滚动或复杂终端布局。
- 不做多 provider 同时请求、自动 failover 或负载均衡。
- 不做 OpenAI Chat Completions 接口；第一版 OpenAI 后端只使用 Responses API。
- 不做配置文件创建向导或交互式初始化；配置文件缺失时只提示用户如何创建。
- 不做 thinking 内容展示；即使后端返回 thinking 相关事件，终端也只显示最终回答文本。

## 验收标准
- AC1: 用户在终端启动 MewCode 后，能看到交互式输入提示，并可以输入一条问题。
- AC2: 配置文件存在且 `active` 指向有效 profile 时，系统使用该 profile 的后端、模型、地址和认证信息发起请求。
- AC3: 配置文件缺失、`active` 不存在、profile 字段缺失或 API key 环境变量未设置时，系统输出清晰错误提示并退出，不把密钥明文打印出来。
- AC4: 用户输入问题后，模型回复在生成过程中持续显示新增文本，而不是等待完整响应后一次性显示。
- AC5: 用户连续进行至少两轮对话时，第二轮回答能基于第一轮用户问题和助手回答的上下文。
- AC6: 当 `protocol` 选择 Anthropic Claude 且配置有效时，系统能通过 Claude 后端完成一次流式对话。
- AC7: 当 `protocol` 选择 OpenAI 且配置有效时，系统能通过 OpenAI Responses API 完成一次流式对话。
- AC8: 当 Claude profile 设置 `thinking: true` 时，系统会启用 Claude thinking 能力；终端输出仍只展示最终回答文本。
- AC9: 当 profile 未设置 `thinking` 或设置为关闭时，系统不启用扩展思考能力。
- AC10: REPL 对 provider 差异无感；切换后端只需要修改配置，不需要改变用户输入流程。
- AC11: 用户输入 `/exit` 或 `/quit` 后，程序正常退出。
- AC12: 用户按 Ctrl+C 后，程序直接结束，不留下持续运行的前台会话。
- AC13: 第一版不会读取、写入或编辑项目文件，也不会执行 shell 命令或工具调用。
