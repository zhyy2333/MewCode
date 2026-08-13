from __future__ import annotations

import asyncio
import json
from pathlib import Path

from mewcode.hooks import (
    HookActionOutcome,
    HookConfigLoader,
    HookEvent,
    HookOutcomeKind,
    HookPaths,
    HookRuntime,
    make_event,
)


class RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, dict[str, object]]] = []

    async def execute(self, rule, envelope, *, expects_decision):
        self.calls.append(
            (rule.key.source.value, rule.key.index, json.loads(envelope.encoded))
        )
        return HookActionOutcome(HookOutcomeKind.SUCCESS)

    async def close(self):
        return None


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_three_layer_config_conditions_trust_and_runtime_order(tmp_path: Path) -> None:
    workspace = tmp_path / "work"
    paths = HookPaths.for_workspace(workspace, user_home=tmp_path / "home")
    common = """hooks:
- event: tool.before
  if:
    all:
      - {field: tool.name, match: exact, value: run_command}
      - {field: tool.arguments.command, match: glob, value: 'git *'}
  action: {type: command, command: echo checked}
"""
    _write(paths.user, common)
    _write(paths.project, common)
    _write(paths.project_local, common)
    catalog = HookConfigLoader().load(paths)
    executor = RecordingExecutor()
    runtime = HookRuntime(
        catalog,
        executor,
        workspace=workspace,
        session_id="s",
        project_trusted=False,
    )
    event = make_event(
        HookEvent.TOOL_BEFORE,
        workspace=workspace,
        session_id="s",
        resumed=False,
        values={
            "tool": {
                "call_id": "1",
                "name": "run_command",
                "arguments": {"command": "git status"},
                "target": {"kind": "command", "value": "git status"},
            }
        },
    )
    asyncio.run(runtime.dispatch(event))
    assert [(source, index) for source, index, _ in executor.calls] == [
        ("user", 0),
        ("project_local", 0),
    ]
    assert all(call[2]["tool"]["arguments"]["command"] == "git status" for call in executor.calls)


def test_repository_hook_example_loads() -> None:
    root = Path(__file__).resolve().parents[1]
    rules = HookConfigLoader().load_file(
        root / "examples" / "hooks.yaml",
        __import__("mewcode.hooks", fromlist=["HookSource"]).HookSource.USER,
    )
    assert len(rules) == 4
    assert {rule.event for rule in rules} >= {
        HookEvent.SESSION_START,
        HookEvent.TOOL_BEFORE,
        HookEvent.TURN_END,
    }
