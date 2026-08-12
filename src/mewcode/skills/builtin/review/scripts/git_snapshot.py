from __future__ import annotations

import json
import subprocess
import sys


def _run(*arguments: str) -> dict[str, object]:
    completed = subprocess.run(
        ["git", *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=45,
    )
    return {
        "argv": ["git", *arguments],
        "returncode": completed.returncode,
        "stdout": completed.stdout[:200_000],
    }


def main() -> int:
    try:
        arguments = json.load(sys.stdin)
        if not isinstance(arguments, dict) or arguments:
            raise ValueError("arguments must be an empty JSON object")
        snapshot = {
            "status": _run("status", "--short"),
            "unstaged": _run("diff", "--no-ext-diff", "--"),
            "staged": _run("diff", "--cached", "--no-ext-diff", "--"),
        }
        print(json.dumps({"ok": True, "content": json.dumps(snapshot)}))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "content": "", "error": str(exc)[:500]}))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
