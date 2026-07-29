from __future__ import annotations

from pathlib import Path

from mewcode.tools.search_tools import FindFilesTool, SearchCodeTool
from mewcode.tools.workspace import Workspace


def test_find_files_returns_relative_matches(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("a", encoding="utf-8")
    (tmp_path / "src" / "b.txt").write_text("b", encoding="utf-8")

    result = FindFilesTool(Workspace(tmp_path)).execute({"pattern": "src/*.py"})

    assert result.ok is True
    assert result.content == "src/a.py"
    assert result.metadata["matches"] == 1


def test_find_files_skips_hidden_and_cache_dirs(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("x", encoding="utf-8")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "x.pyc").write_text("x", encoding="utf-8")
    (tmp_path / "visible.py").write_text("x", encoding="utf-8")

    result = FindFilesTool(Workspace(tmp_path)).execute({"pattern": "**/*"})

    assert result.ok is True
    assert result.content == "visible.py"


def test_find_files_truncates_output(tmp_path: Path) -> None:
    (tmp_path / "alpha.txt").write_text("x", encoding="utf-8")
    (tmp_path / "beta.txt").write_text("x", encoding="utf-8")

    result = FindFilesTool(Workspace(tmp_path), content_limit=10).execute({"pattern": "*.txt"})

    assert result.ok is True
    assert result.metadata["truncated"] is True


def test_search_code_returns_file_line_and_snippet(tmp_path: Path) -> None:
    path = tmp_path / "src.py"
    path.write_text("first\nneedle here\n", encoding="utf-8")

    result = SearchCodeTool(Workspace(tmp_path)).execute({"query": "needle"})

    assert result.ok is True
    assert result.content == "src.py:2: needle here"
    assert result.metadata["matches"] == 1


def test_search_code_limits_to_path(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("needle", encoding="utf-8")
    (tmp_path / "other.py").write_text("needle", encoding="utf-8")

    result = SearchCodeTool(Workspace(tmp_path)).execute({"query": "needle", "path": "src"})

    assert result.ok is True
    assert result.content == "src/a.py:1: needle"


def test_search_code_rejects_outside_path(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    result = SearchCodeTool(Workspace(workspace_root)).execute(
        {"query": "needle", "path": str(outside)}
    )

    assert result.ok is False
    assert "outside" in (result.error or "")


def test_search_code_skips_hidden_and_cache_dirs(tmp_path: Path) -> None:
    (tmp_path / ".pytest_cache").mkdir()
    (tmp_path / ".pytest_cache" / "x.txt").write_text("needle", encoding="utf-8")
    (tmp_path / "visible.txt").write_text("needle", encoding="utf-8")

    result = SearchCodeTool(Workspace(tmp_path)).execute({"query": "needle"})

    assert result.ok is True
    assert result.content == "visible.txt:1: needle"


def test_search_code_truncates_by_match_count(tmp_path: Path) -> None:
    path = tmp_path / "many.txt"
    path.write_text("\n".join(["needle"] * 5), encoding="utf-8")

    result = SearchCodeTool(Workspace(tmp_path), max_matches=2).execute({"query": "needle"})

    assert result.ok is True
    assert result.metadata["matches"] == 5
    assert result.metadata["returned"] == 2
    assert result.metadata["truncated"] is True


def test_search_code_truncates_by_content_size(tmp_path: Path) -> None:
    path = tmp_path / "long.txt"
    path.write_text("needle " + "x" * 100, encoding="utf-8")

    result = SearchCodeTool(Workspace(tmp_path), content_limit=20).execute({"query": "needle"})

    assert result.ok is True
    assert result.metadata["truncated"] is True
