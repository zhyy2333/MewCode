from __future__ import annotations

import json
from pathlib import Path

from mewcode.hooks.trust import WorkspaceTrustStore, workspace_identity


def test_identity_and_workspaces_are_isolated(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    store = WorkspaceTrustStore(tmp_path / "home" / "trust.json")
    assert len(workspace_identity(first).digest) == 64
    assert store.read(first) is None
    assert store.write(first, True)
    assert store.read(first) is True
    assert store.read(second) is None
    assert store.write(second, False)
    assert store.read(first) is True
    assert store.read(second) is False


def test_corrupt_store_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "trust.json"
    path.write_text("{broken", encoding="utf-8")
    store = WorkspaceTrustStore(path)
    assert store.read(tmp_path) is None
    assert store.last_diagnostic
    assert store.write(tmp_path, True) is False
    assert path.read_text(encoding="utf-8") == "{broken"


def test_duplicate_identity_fails_closed(tmp_path: Path) -> None:
    identity = workspace_identity(tmp_path)
    entry = {"identity": identity.digest, "path": identity.path, "trusted": True}
    path = tmp_path / "trust.json"
    path.write_text(json.dumps({"version": 1, "workspaces": [entry, entry]}), encoding="utf-8")
    assert WorkspaceTrustStore(path).read(tmp_path) is None


def test_write_failure_keeps_old_file(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "trust.json"
    store = WorkspaceTrustStore(path)
    assert store.write(tmp_path / "one", True)
    old = path.read_bytes()

    def fail_replace(_source, _target):
        raise OSError("replace failed")

    monkeypatch.setattr("mewcode.hooks.trust.os.replace", fail_replace)
    assert store.write(tmp_path / "two", True) is False
    assert path.read_bytes() == old
