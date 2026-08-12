from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys

from mewcode.skills.materialization import MaterializedSkill
from mewcode.skills.models import SkillFingerprint, SkillToolDeclaration
from mewcode.skills.process_tool import SkillProcessTool
from mewcode.tools import ToolSafety


def _tool(tmp_path: Path, script: str, *, timeout: int = 2) -> SkillProcessTool:
    package = tmp_path / "package"
    package.mkdir(parents=True)
    (package / "tool.py").write_text(script, encoding="utf-8")
    declaration = SkillToolDeclaration(
        "check",
        "sample__check",
        "Check",
        {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        (sys.executable, "tool.py"),
        ToolSafety.READ_ONLY,
        timeout,
    )
    return SkillProcessTool(
        declaration,
        MaterializedSkill("sample", package, SkillFingerprint("", ())),
        tmp_path,
        api_key_environment_names={"SECRET_PROFILE_KEY"},
    )


def test_process_tool_uses_json_cwd_and_filtered_environment(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SECRET_PROFILE_KEY", "secret")
    tool = _tool(
        tmp_path,
        """import json, os, sys
args=json.load(sys.stdin)
print(json.dumps({"ok": True, "content": args["value"], "metadata": {"cwd": os.getcwd(), "secret": os.getenv("SECRET_PROFILE_KEY"), "package": os.getenv("MEWCODE_SKILL_DIR")}}))
""",
    )
    result = asyncio.run(tool.execute({"value": "hello"}))
    assert result.ok and result.content == "hello"
    assert Path(result.metadata["cwd"]) == tmp_path
    assert result.metadata["secret"] is None
    assert Path(result.metadata["package"]) == tmp_path / "package"


def test_process_tool_validates_arguments_before_start(tmp_path: Path) -> None:
    tool = _tool(tmp_path, "raise SystemExit(99)")
    result = asyncio.run(tool.execute({}))
    assert not result.ok and "Invalid tool arguments" in (result.error or "")


def test_process_tool_converts_invalid_json_and_nonzero_exit(tmp_path: Path) -> None:
    invalid = _tool(tmp_path / "invalid", "print('nope')")
    failed = asyncio.run(invalid.execute({"value": "x"}))
    assert not failed.ok and failed.error == "Skill tool returned invalid JSON."

    nonzero = _tool(tmp_path / "nonzero", "raise SystemExit(3)")
    failed = asyncio.run(nonzero.execute({"value": "x"}))
    assert not failed.ok and "code 3" in (failed.error or "")


def test_process_tool_rejects_extra_result_fields_and_hides_stderr(tmp_path: Path) -> None:
    tool = _tool(
        tmp_path,
        """import json, sys
print("sensitive diagnostic", file=sys.stderr)
print(json.dumps({"ok": True, "content": "value", "unexpected": True}))
""",
    )
    result = asyncio.run(tool.execute({"value": "x"}))
    assert not result.ok and result.error == "Skill tool result has invalid fields."
    assert "sensitive diagnostic" not in result.error
    assert "sensitive diagnostic" not in result.content


def test_process_tool_times_out_and_reaps_process(tmp_path: Path) -> None:
    tool = _tool(tmp_path, "import time; time.sleep(10)", timeout=1)
    result = asyncio.run(tool.execute({"value": "x"}))
    assert not result.ok and "timed out" in (result.error or "")


def test_process_tool_accepts_structured_failure(tmp_path: Path) -> None:
    payload = json.dumps({"ok": False, "content": "", "error": "expected"})
    tool = _tool(tmp_path, f"print({payload!r})")
    result = asyncio.run(tool.execute({"value": "x"}))
    assert not result.ok and result.error == "expected"


def test_process_tool_bounds_stdout(tmp_path: Path) -> None:
    tool = _tool(tmp_path, "print('x' * (1024 * 1024 + 1))")
    result = asyncio.run(tool.execute({"value": "x"}))
    assert not result.ok and "stdout" in (result.error or "")
