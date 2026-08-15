from __future__ import annotations

from pathlib import Path
import subprocess


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={
            "PATH": __import__("os").environ["PATH"],
            "GIT_CONFIG_NOSYSTEM": "1",
            "HOME": str(cwd),
            "USERPROFILE": str(cwd),
        },
    )


def repository(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.email", "tests@example.invalid")
    git(root, "config", "user.name", "MewCode Tests")
    (root / ".gitignore").write_text("/.mewcode/*\n!/.mewcode/worktrees.yaml\n/.mewcode/worktrees/\n/local/\n", encoding="utf-8")
    (root / "tracked.txt").write_text("base\n", encoding="utf-8")
    git(root, "add", ".gitignore", "tracked.txt")
    git(root, "commit", "-m", "base")
    return root.resolve()
