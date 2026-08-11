from pathlib import Path

import pytest

from mewcode.continuity import (
    ContinuityComponent,
    ContinuityDiagnostic,
    ContinuityPaths,
    DiagnosticSeverity,
)


def test_paths_use_injected_workspace_and_user_root(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    user = tmp_path / "user-config"
    workspace.mkdir()
    paths = ContinuityPaths.for_workspace(workspace, user_root=user)
    assert paths.project_root_instructions == workspace.resolve() / "MEWCODE.md"
    assert paths.project_local_instructions == workspace.resolve() / ".mewcode" / "instructions.md"
    assert paths.sessions_root == workspace.resolve() / ".mewcode" / "sessions"
    assert paths.user_instructions == user.resolve() / "instructions.md"
    assert paths.user_memory_root == user.resolve() / "memory"


def test_diagnostic_requires_non_empty_safe_fields() -> None:
    diagnostic = ContinuityDiagnostic(
        ContinuityComponent.SESSION,
        "opened",
        DiagnosticSeverity.INFO,
        "A session was opened.",
    )
    assert diagnostic.component.value == "session"
    with pytest.raises(ValueError):
        ContinuityDiagnostic(
            ContinuityComponent.MEMORY,
            "",
            DiagnosticSeverity.ERROR,
            "bad",
        )
