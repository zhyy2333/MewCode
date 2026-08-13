from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

import pytest

from mewcode.hooks import (
    AgentHookAction,
    CommandHookAction,
    HookConfigError,
    HookConfigLoader,
    HookEvent,
    HookPaths,
    HookSource,
    HttpHookAction,
    PromptHookAction,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_paths_layers_missing_and_stable_order(tmp_path: Path) -> None:
    home = tmp_path / "home"
    workspace = tmp_path / "work"
    paths = HookPaths.for_workspace(workspace, user_home=home)
    _write(paths.user, "hooks:\n- event: session.start\n  action: {type: prompt, content: user}\n")
    _write(paths.project, "hooks:\n- event: turn.start\n  action: {type: prompt, content: project}\n")
    _write(paths.project_local, "hooks:\n- event: turn.end\n  action: {type: prompt, content: local}\n")

    catalog = HookConfigLoader().load(paths)

    assert [rule.key.source for rule in catalog.rules] == [
        HookSource.USER,
        HookSource.PROJECT,
        HookSource.PROJECT_LOCAL,
    ]
    assert [rule.key.index for rule in catalog.rules] == [0, 0, 0]
    assert not catalog.requires_project_trust


def test_four_action_models_and_project_trust(tmp_path: Path) -> None:
    paths = HookPaths.for_workspace(tmp_path, user_home=tmp_path / "home")
    _write(
        paths.project,
        """hooks:
- event: session.start
  action: {type: command, command: echo ok, timeout_seconds: 5, once: true}
- event: turn.end
  action:
    type: http
    url: https://example.test/hook
    headers: {Authorization: secret}
    background: true
- event: message.before
  action: {type: prompt, content: context}
- event: turn.end
  action: {type: agent, task: summarize}
""",
    )
    catalog = HookConfigLoader().load(paths)
    assert isinstance(catalog.rules[0].action, CommandHookAction)
    assert isinstance(catalog.rules[1].action, HttpHookAction)
    assert isinstance(catalog.rules[1].action.headers, MappingProxyType)
    assert isinstance(catalog.rules[2].action, PromptHookAction)
    assert isinstance(catalog.rules[3].action, AgentHookAction)
    assert catalog.requires_project_trust


@pytest.mark.parametrize(
    "fragment",
    [
        "extra: true\n",
        "if: {all: [], any: []}\n",
        "if: {all: []}\n",
        "if: {all: [{field: nope, match: exact, value: x}]}\n",
    ],
)
def test_strict_rule_and_condition_errors(tmp_path: Path, fragment: str) -> None:
    path = tmp_path / "hooks.yaml"
    _write(
        path,
        "hooks:\n- event: tool.before\n  action: {type: prompt, content: x}\n  "
        + fragment.replace("\n", "\n  ").rstrip()
        + "\n",
    )
    with pytest.raises(HookConfigError):
        HookConfigLoader().load_file(path, HookSource.USER)


def test_valid_conditions_and_compiled_regex(tmp_path: Path) -> None:
    path = tmp_path / "hooks.yaml"
    _write(
        path,
        """hooks:
- event: tool.before
  if:
    all:
      - {field: tool.name, match: exact, value: run_command}
      - {field: tool.arguments.command, match: glob, value: 'git *', negate: false}
      - {field: tool.target.value, match: regex, value: '^git\\s+push$'}
  action: {type: prompt, content: stop}
""",
    )
    rule = HookConfigLoader().load_file(path, HookSource.USER)[0]
    assert rule.event is HookEvent.TOOL_BEFORE
    assert rule.condition is not None
    assert rule.condition.clauses[-1].compiled is not None


@pytest.mark.parametrize(
    "action",
    [
        "{type: command, command: x, once: 'true'}",
        "{type: command, command: x, timeout_seconds: 0}",
        "{type: http, url: ftp://example.test}",
        "{type: prompt, content: x, background: true}",
        "{type: agent, task: x, timeout_seconds: 1}",
        "{type: command, command: x, background: true}",
    ],
)
def test_invalid_action_combinations(tmp_path: Path, action: str) -> None:
    path = tmp_path / "hooks.yaml"
    _write(path, f"hooks:\n- event: tool.before\n  action: {action}\n")
    with pytest.raises(HookConfigError):
        HookConfigLoader().load_file(path, HookSource.USER)


def test_import_has_no_side_effect(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    import mewcode.hooks as hooks

    assert hooks.HookCatalog.empty().rules == ()
    assert list(tmp_path.iterdir()) == []


def test_repeated_load_has_stable_keys_and_event_order(tmp_path: Path) -> None:
    paths = HookPaths.for_workspace(tmp_path / "work", user_home=tmp_path / "home")
    _write(
        paths.user,
        """hooks:
- event: turn.end
  action: {type: prompt, content: first}
- event: session.start
  action: {type: prompt, content: second}
- event: turn.end
  action: {type: prompt, content: third}
""",
    )
    first = HookConfigLoader().load(paths)
    second = HookConfigLoader().load(paths)
    assert first.rules == second.rules
    assert tuple(first.by_event) == tuple(second.by_event)
    assert [rule.key.index for rule in first.by_event[HookEvent.TURN_END]] == [0, 2]
