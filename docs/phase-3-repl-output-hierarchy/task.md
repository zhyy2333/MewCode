# MewCode REPL 输出层级优化 Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 修改 | `src/mewcode/repl.py` | 增加单次运行事件渲染状态，应用缩进和步骤间距 |
| 修改 | `tests/test_repl.py` | 验证精确输出、流式边界和现有 REPL 行为 |
| 新建 | `docs/phase-3-repl-output-hierarchy/spec.md` | 记录已批准需求 |
| 新建 | `docs/phase-3-repl-output-hierarchy/plan.md` | 记录已批准技术设计 |
| 新建 | `docs/phase-3-repl-output-hierarchy/task.md` | 记录实现任务与顺序 |
| 新建 | `docs/phase-3-repl-output-hierarchy/checklist.md` | 记录可执行验收项 |

## T1：实现辅助事件视觉层级

**文件：** `src/mewcode/repl.py`、`tests/test_repl.py`

**依赖：** 无

**步骤：**

1. 新增 `_EventRenderer`，保留 `_format_event()` 的基础文案职责。
2. 将工具调用、工具结果、Token 用量和工具批次开始事件标记为次级事件。
3. 为次级事件的每个终端行添加两个 ASCII 空格，迭代标题、模型文本和停止状态保持顶格。
4. 更新事件输出测试，使用完整字符串断言层级且继续验证工具参数不会泄漏。

**验证：** 运行 `python -m pytest tests/test_repl.py -q -k "indent or output"`，期望辅助事件全部缩进两个空格，一级事件顶格，敏感参数仍不可见。

## T2：实现迭代分隔和流式行边界

**文件：** `src/mewcode/repl.py`、`tests/test_repl.py`

**依赖：** T1

**步骤：**

1. 在 `_EventRenderer` 中记录是否已输出迭代标题以及当前位置是否为行首。
2. 第一轮迭代标题直接输出；后续迭代标题前补齐恰好一个空白行。
3. 当流式正文未以换行结尾时，在后续结构化状态行前先结束当前行，避免文本粘连。
4. 增加单轮、连续两轮、正文带换行和正文不带换行的精确字符序列测试。

**验证：** 运行 `python -m pytest tests/test_repl.py -q -k "iteration_spacing or line_boundary"`，期望首轮无前导空行、两轮间恰好一个空行且所有状态行独立成行。

## T3：接入单次运行渲染生命周期

**文件：** `src/mewcode/repl.py`、`tests/test_repl.py`

**依赖：** T2

**步骤：**

1. 在每次 `_consume()` 开始时创建新的 `_EventRenderer`。
2. 保持逐事件写入和刷新，不在 REPL 中收集完整模型回复。
3. 验证连续两条用户任务的第一轮都不会继承上一任务的空行状态。
4. 更新渲染异常测试，使其覆盖新的渲染器入口并确认失败后下一条输入仍可处理。

**验证：** 运行 `python -m pytest tests/test_repl.py -q -k "renderer_reset or render_error or streaming"`，期望每轮状态隔离、分片顺序不变且错误后 REPL 可继续。

## T4：执行 REPL 与全量回归

**文件：** `tests/test_repl.py` 及现有测试套件

**依赖：** T3

**步骤：**

1. 运行 REPL 定向测试，修复本次排版变化导致的旧断言差异。
2. 运行完整测试套件，确认 Plan Mode、取消、Provider 和工具行为无回归。
3. 编译源码与测试，并执行 diff 空白检查。
4. 确认没有新增运行时依赖或配置字段。

**验证：** 依次运行 `python -m pytest tests/test_repl.py -q`、`python -m pytest -q`、`python -m compileall -q src tests` 和 `git diff --check`，期望全部以 0 退出且没有异步任务泄漏警告。

## 执行顺序

```text
T1 -> T2 -> T3 -> T4
```
