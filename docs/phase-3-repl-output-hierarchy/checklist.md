# MewCode REPL 输出层级优化 Checklist

> 每一项通过运行代码或观察输出验证，聚焦终端中可见的字符序列和既有行为。

## 实现完整性

- [x] REPL 能为单次 Agent 运行维护独立排版状态（验证：运行 `python -m pytest tests/test_repl.py -q -k renderer_reset`，期望连续任务的首轮输出均无前导空行）。
- [x] 工具调用、工具结果、Token 用量和工具批次进度使用同一层级规则（验证：运行 `python -m pytest tests/test_repl.py -q -k indent`，期望四类事件行均以两个空格开头）。
- [x] Agent 事件模型和业务模块未因排版发生变化（验证：运行 `git diff -- src/mewcode/agent src/mewcode/conversation.py`，期望无差异）。

## 输出行为

- [x] **AC1：** 迭代标题顶格，所属辅助事件缩进两个空格（验证：运行 `python -m pytest tests/test_repl.py -q -k indent`，期望精确字符串断言通过）。
- [x] **AC2：** 连续两次迭代之间恰好有一个空行，迭代内部没有额外空行（验证：运行 `python -m pytest tests/test_repl.py -q -k iteration_spacing`，期望输出只在迭代边界包含 `\n\n`）。
- [x] **AC3：** 第一轮无前导空行，模型正文和停止状态保持顶格（验证：运行 `python -m pytest tests/test_repl.py -q -k "first_iteration or primary_output"`，期望输出开头和各一级行均无空格缩进）。
- [x] 正文分片未以换行结尾时，后续结构化事件仍从新行开始（验证：运行 `python -m pytest tests/test_repl.py -q -k line_boundary`，期望正文和状态行之间自动补一个换行）。
- [x] 正文已经以换行结尾时不会再产生额外空白行（验证：运行 `python -m pytest tests/test_repl.py -q -k line_boundary`，期望相同边界仅有一个换行）。
- [x] 取消、流错误和内部错误停止文案保持原语义并顶格显示（验证：运行 `python -m pytest tests/test_repl.py -q -k "cancel or error or stopped"`，期望原有状态词存在且无辅助缩进）。

## 流式与安全

- [x] **AC4：** 文本分片按事件顺序立即写入，不等待完整回复（验证：运行 `python -m pytest tests/test_repl.py -q -k streaming`，期望记录到逐分片写入和刷新调用）。
- [x] 工具完整参数仍不会显示（验证：运行 `python -m pytest tests/test_repl.py -q -k output`，期望输出包含工具名但不包含测试参数值）。
- [x] 大段工具结果仍只显示现有摘要（验证：运行 `python -m pytest tests/test_repl.py -q -k output`，期望输出不包含摘要之外的结果内容）。
- [x] 隐藏推理事件仍不会进入 REPL 输出（验证：运行 `python -m pytest tests/test_tool_providers.py tests/test_repl.py -q -k reasoning`，期望隐藏内容无匹配）。

## 集成与兼容

- [x] **AC5：** 普通消息、`/plan`、`/do` 和退出命令路由保持不变（验证：运行 `python -m pytest tests/test_repl.py -q -k "routing or exit or quit"`，期望全部通过）。
- [x] Ctrl+C 取消后仍可处理下一条消息（验证：运行 `python -m pytest tests/test_repl.py -q -k continues_after_cancel`，期望取消提示和下一条回复均出现）。
- [x] 渲染异常会清理当前运行且下一条消息继续处理（验证：运行 `python -m pytest tests/test_repl.py -q -k render_error`，期望错误写入 stderr 且后续输出正常）。
- [x] 新排版不新增运行时依赖或配置字段（验证：运行 `git diff -- pyproject.toml examples/config.yaml`，期望无差异）。

## 编译与测试

- [x] REPL 定向测试全部通过（验证：运行 `python -m pytest tests/test_repl.py -q`，期望零失败）。
- [x] 完整测试套件通过且无异步任务泄漏警告（验证：运行 `python -m pytest -q`，期望零失败且无 pending-task 警告）。
- [x] 源码和测试可编译（验证：运行 `python -m compileall -q src tests`，期望命令以 0 退出且无输出）。
- [x] 改动无空白错误（验证：运行 `git diff --check`，期望命令以 0 退出且无错误）。

## 端到端场景

- [x] 多轮 Agent 场景：用户提交任务，第一轮显示顶格迭代标题及缩进辅助信息，空一行后显示第二轮，最终正文与完成状态顶格（验证：运行 `python -m pytest tests/test_repl.py -q -k end_to_end_hierarchy`，期望完整输出与批准的示例逐字符一致）。
- [x] 连续任务场景：第一条任务完成后输入第二条任务，两条任务各自的第一轮均无继承性空行（验证：运行 `python -m pytest tests/test_repl.py -q -k renderer_reset`，期望两个任务块分别满足首轮规则）。
