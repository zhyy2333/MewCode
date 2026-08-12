from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, SchemaError

from mewcode.tools import ToolSafety

from .models import (
    DEFAULT_TOOL_TIMEOUT_SECONDS,
    MAX_COMMAND_ARGV,
    MAX_COMMAND_ARG_CHARS,
    MAX_DESCRIPTION_CHARS,
    MAX_FRONTMATTER_BYTES,
    MAX_SOP_BYTES,
    MAX_TOOL_DECLARATION_BYTES,
    MAX_TOOL_TIMEOUT_SECONDS,
    MAX_TOOL_WHITELIST,
    MAX_TOOLS_PER_SKILL,
    MIN_TOOL_TIMEOUT_SECONDS,
    SKILL_NAME_PATTERN,
    TOOL_LOCAL_NAME_PATTERN,
    SkillBodyRef,
    SkillDefinition,
    SkillDefinitionError,
    SkillMode,
    SkillSource,
    SkillToolDeclaration,
)
from .paths import ensure_package_path

_SKILL_FIELDS = frozenset({"name", "description", "tools", "mode", "history", "model"})
_TOOL_FIELDS = frozenset(
    {"name", "description", "parameters", "command", "safety", "timeout_seconds"}
)


def parse_skill(source: SkillSource) -> SkillDefinition:
    metadata, body_offset, body_size = _read_frontmatter(source.entry_path)
    unknown = set(metadata) - _SKILL_FIELDS
    if unknown:
        raise SkillDefinitionError(f"Unknown frontmatter field(s): {', '.join(sorted(unknown))}")
    required = {"name", "description", "tools", "mode"}
    missing = required - set(metadata)
    if missing:
        raise SkillDefinitionError(f"Missing frontmatter field(s): {', '.join(sorted(missing))}")
    name = _required_string(metadata, "name")
    if not re.fullmatch(SKILL_NAME_PATTERN, name):
        raise SkillDefinitionError(f"Invalid Skill name: {name}")
    if name != source.entry_name:
        raise SkillDefinitionError(
            f"Skill name '{name}' does not match entry name '{source.entry_name}'."
        )
    description = _required_string(metadata, "description")
    if len(description) > MAX_DESCRIPTION_CHARS or "\n" in description or "\r" in description:
        raise SkillDefinitionError("Skill description must be one line and at most 200 characters.")
    raw_tools = metadata["tools"]
    if not isinstance(raw_tools, list) or any(not isinstance(item, str) or not item for item in raw_tools):
        raise SkillDefinitionError("Skill field 'tools' must be a list of non-empty strings.")
    if len(raw_tools) > MAX_TOOL_WHITELIST or len(set(raw_tools)) != len(raw_tools):
        raise SkillDefinitionError("Skill tool whitelist is too large or contains duplicates.")
    try:
        mode = SkillMode(metadata["mode"])
    except (ValueError, TypeError) as exc:
        raise SkillDefinitionError("Skill mode must be 'shared' or 'isolated'.") from exc
    history = metadata.get("history")
    model = metadata.get("model")
    if mode is SkillMode.SHARED:
        if "history" in metadata or "model" in metadata:
            raise SkillDefinitionError("Shared Skills forbid 'history' and 'model'.")
        history = None
        model = None
    else:
        if not isinstance(history, int) or isinstance(history, bool) or history < 0:
            raise SkillDefinitionError("Isolated Skills require non-negative integer 'history'.")
        if model is not None and (not isinstance(model, str) or not model.strip()):
            raise SkillDefinitionError("Skill field 'model' must be a non-empty Profile name.")
        model = model.strip() if isinstance(model, str) else None
    package_tools = _parse_package_tools(source, name)
    return SkillDefinition(
        name=name,
        description=description,
        tools=tuple(raw_tools),
        mode=mode,
        history=history,
        model=model,
        body=SkillBodyRef(source.entry_path, body_offset, body_size, source.fingerprint),
        source=source,
        package_tools=package_tools,
    )


def _read_frontmatter(path: Path) -> tuple[dict[str, Any], int, int]:
    size = path.stat().st_size
    with path.open("rb") as handle:
        prefix = handle.read(MAX_FRONTMATTER_BYTES + 5)
    if prefix.startswith(b"\xef\xbb\xbf"):
        prefix = prefix[3:]
        bom = 3
    else:
        bom = 0
    if not prefix.startswith(b"---\n") and not prefix.startswith(b"---\r\n"):
        raise SkillDefinitionError("Skill entry must start with YAML frontmatter delimiter '---'.")
    match = re.search(br"\r?\n---(?:\r?\n|$)", prefix[3:])
    if match is None:
        raise SkillDefinitionError("Skill frontmatter is missing a closing delimiter or exceeds 64 KiB.")
    start = 3 + match.start()
    end = 3 + match.end()
    yaml_bytes = prefix[3:start]
    try:
        raw = yaml.safe_load(yaml_bytes.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise SkillDefinitionError("Skill frontmatter is not valid UTF-8 YAML.") from exc
    if not isinstance(raw, dict):
        raise SkillDefinitionError("Skill frontmatter must be a YAML object.")
    offset = bom + end
    body_size = size - offset
    if body_size < 0 or body_size > MAX_SOP_BYTES:
        raise SkillDefinitionError(f"Skill SOP exceeds {MAX_SOP_BYTES} bytes.")
    return raw, offset, body_size


def _parse_package_tools(source: SkillSource, skill_name: str) -> tuple[SkillToolDeclaration, ...]:
    if source.package_dir is None:
        return ()
    tools_dir = source.package_dir / "tools"
    if not tools_dir.exists():
        return ()
    if not tools_dir.is_dir() or tools_dir.is_symlink():
        raise SkillDefinitionError("Skill tools path must be a regular directory.")
    paths = tuple(sorted(tools_dir.glob("*.json"), key=lambda item: item.name))
    if len(paths) > MAX_TOOLS_PER_SKILL:
        raise SkillDefinitionError(f"Skill exceeds {MAX_TOOLS_PER_SKILL} package tools.")
    declarations = tuple(_parse_tool(path, source.package_dir, skill_name) for path in paths)
    names = [item.local_name for item in declarations]
    if len(names) != len(set(names)):
        raise SkillDefinitionError("Skill package contains duplicate local tool names.")
    return declarations


def _parse_tool(path: Path, package: Path, skill_name: str) -> SkillToolDeclaration:
    if path.is_symlink() or path.stat().st_size > MAX_TOOL_DECLARATION_BYTES:
        raise SkillDefinitionError(f"Invalid or oversized tool declaration: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SkillDefinitionError(f"Invalid tool JSON: {path}") from exc
    if not isinstance(raw, dict):
        raise SkillDefinitionError(f"Tool declaration must be a JSON object: {path}")
    unknown = set(raw) - _TOOL_FIELDS
    missing = {"name", "description", "parameters", "command", "safety"} - set(raw)
    if unknown or missing:
        detail = unknown or missing
        raise SkillDefinitionError(f"Invalid tool fields in {path}: {', '.join(sorted(detail))}")
    local = _required_string(raw, "name")
    if not re.fullmatch(TOOL_LOCAL_NAME_PATTERN, local):
        raise SkillDefinitionError(f"Invalid local tool name '{local}' in {path}")
    description = _required_string(raw, "description")
    parameters = raw["parameters"]
    if not isinstance(parameters, dict):
        raise SkillDefinitionError(f"Tool parameters must be a JSON Schema object: {path}")
    try:
        Draft202012Validator.check_schema(parameters)
    except SchemaError as exc:
        raise SkillDefinitionError(f"Invalid Draft 2020-12 parameters schema: {path}") from exc
    command = raw["command"]
    if (
        not isinstance(command, list)
        or not command
        or len(command) > MAX_COMMAND_ARGV
        or any(not isinstance(item, str) or not item or len(item) > MAX_COMMAND_ARG_CHARS for item in command)
    ):
        raise SkillDefinitionError(f"Tool command must be a bounded non-empty string array: {path}")
    _validate_command_paths(tuple(command), package)
    try:
        safety = ToolSafety(raw["safety"])
    except (TypeError, ValueError) as exc:
        raise SkillDefinitionError(f"Tool safety must be read_only or side_effect: {path}") from exc
    timeout = raw.get("timeout_seconds", DEFAULT_TOOL_TIMEOUT_SECONDS)
    if (
        not isinstance(timeout, int)
        or isinstance(timeout, bool)
        or not MIN_TOOL_TIMEOUT_SECONDS <= timeout <= MAX_TOOL_TIMEOUT_SECONDS
    ):
        raise SkillDefinitionError(f"Tool timeout_seconds must be 1–600: {path}")
    return SkillToolDeclaration(
        local,
        f"{skill_name}__{local}",
        description,
        parameters,
        tuple(command),
        safety,
        timeout,
        path,
    )


def _validate_command_paths(command: tuple[str, ...], package: Path) -> None:
    first = Path(command[0])
    if first.is_absolute() and (not first.exists() or not first.is_file()):
        raise SkillDefinitionError(f"Executable does not exist: {command[0]}")
    for index, argument in enumerate(command):
        if index == 0 and not Path(argument).is_absolute():
            continue
        if index > 0 and not _looks_like_package_path(argument):
            continue
        if Path(argument).is_absolute():
            if index == 0:
                continue
            raise SkillDefinitionError(f"Only the executable may use an absolute path: {argument}")
        ensure_package_path(package, argument)


def _looks_like_package_path(value: str) -> bool:
    return (
        not value.startswith("-")
        and (
            value.startswith(".")
            or "/" in value
            or "\\" in value
            or bool(Path(value).suffix)
        )
    )


def _required_string(raw: dict[str, Any], field: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value.strip():
        raise SkillDefinitionError(f"Field '{field}' must be a non-empty string.")
    return value.strip()
