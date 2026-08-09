from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from mewcode.permissions import (
    PermissionConfigError,
    PermissionConfigLoader,
    PermissionConfigWriter,
    PermissionPaths,
    PermissionRuleSets,
    PermissionRuleStore,
    PermissionTarget,
    RuleScope,
)
from mewcode.tools import PermissionTargetKind, Workspace


KNOWN = {"run_command", "read_file", "write_file"}


def test_permission_paths_and_missing_files(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path / "project")
    home = tmp_path / "home"
    paths = PermissionPaths.for_workspace(workspace, home)
    assert paths.user == home.resolve() / ".mewcode" / "permissions.yaml"
    assert paths.project == workspace.root / ".mewcode" / "permissions.yaml"
    assert paths.project_local.name == "permissions.local.yaml"
    assert PermissionConfigLoader().load(paths, KNOWN) == PermissionRuleSets()


def test_loads_three_layers_with_correct_scopes(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path / "project")
    paths = PermissionPaths.for_workspace(workspace, tmp_path / "home")
    for path in (paths.user, paths.project, paths.project_local):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            'rules:\n  - rule: "run_command(git *)"\n    result: allow\n',
            encoding="utf-8",
        )
    loaded = PermissionConfigLoader().load(paths, KNOWN)
    assert loaded.user[0].scope == RuleScope.USER
    assert loaded.project[0].scope == RuleScope.PROJECT
    assert loaded.project_local[0].scope == RuleScope.PROJECT_LOCAL


@pytest.mark.parametrize(
    "content",
    [
        "rules: [",
        "- invalid",
        "rules: object",
        "rules:\n  - rule: unknown(x)\n    result: allow\n",
        "rules:\n  - rule: run_command(x)\n    result: maybe\n",
        "rules:\n  - rule: run_command(x)\n    result: allow\n    extra: true\n",
    ],
)
def test_invalid_permission_config_fails_closed(tmp_path: Path, content: str) -> None:
    path = tmp_path / "permissions.yaml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(PermissionConfigError, match="permissions.yaml"):
        PermissionConfigLoader().load_file(path, RuleScope.USER, KNOWN)


def test_writer_creates_and_deduplicates_local_allow(tmp_path: Path) -> None:
    path = tmp_path / ".mewcode" / "permissions.local.yaml"
    writer = PermissionConfigWriter(path, KNOWN)
    target = PermissionTarget("run_command", "git status", PermissionTargetKind.COMMAND)
    first = writer.add_local_allow(target)
    second = writer.add_local_allow(target)
    assert first == second
    assert len(second) == 1
    assert path.read_text(encoding="utf-8").count("run_command") == 1


def test_writer_preserves_external_rules_and_rejects_corrupt_file(tmp_path: Path) -> None:
    path = tmp_path / "permissions.local.yaml"
    path.write_text(
        "rules:\n  - rule: read_file(src/**)\n    result: deny\n", encoding="utf-8"
    )
    writer = PermissionConfigWriter(path, KNOWN)
    target = PermissionTarget("run_command", "git status", PermissionTargetKind.COMMAND)
    updated = writer.add_local_allow(target)
    assert len(updated) == 2
    path.write_text("rules: [", encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(PermissionConfigError):
        writer.add_local_allow(target)
    assert path.read_bytes() == before


def test_store_permanent_refreshes_local_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "permissions.local.yaml"
    writer = PermissionConfigWriter(path, KNOWN)
    store = PermissionRuleStore(PermissionRuleSets(), writer)
    target = PermissionTarget("run_command", "git status", PermissionTargetKind.COMMAND)
    asyncio.run(store.persist_project_local_allow(target))
    assert store.snapshot().project_local
    assert store.match(target) is not None
