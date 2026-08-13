from __future__ import annotations

import re
from typing import Any

import yaml

from mewcode.permissions import PermissionMode

from .models import (
    AGENT_NAME_PATTERN,
    MAX_DEFINITION_FILE_BYTES,
    MAX_DEFINITION_TURNS,
    AgentDefinition,
    AgentDefinitionError,
    AgentDefinitionSource,
)


_FIELDS = frozenset(
    {
        "name",
        "description",
        "tools",
        "disallowed_tools",
        "model",
        "max_turns",
        "permission_mode",
    }
)
_NAME = re.compile(AGENT_NAME_PATTERN)


class _StrictLoader(yaml.SafeLoader):
    pass


def _construct_mapping(loader, node, deep=False):
    mapping: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


def parse_agent_definition(source: AgentDefinitionSource) -> AgentDefinition:
    if source.error:
        raise AgentDefinitionError(source.error, source=source)
    try:
        with source.path.open("rb") as stream:
            payload = stream.read(MAX_DEFINITION_FILE_BYTES + 1)
    except OSError as exc:
        raise AgentDefinitionError(
            f"Unable to read agent definition: {type(exc).__name__}.",
            source=source,
        ) from exc
    if len(payload) > MAX_DEFINITION_FILE_BYTES:
        raise AgentDefinitionError(
            f"Agent definition exceeds {MAX_DEFINITION_FILE_BYTES} bytes.",
            source=source,
        )
    if payload.startswith(b"\xef\xbb\xbf"):
        payload = payload[3:]
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AgentDefinitionError(
            "Agent definition is not valid UTF-8.", source=source
        ) from exc
    metadata_text, body = _split_frontmatter(text, source)
    try:
        metadata = yaml.load(metadata_text, Loader=_StrictLoader)
    except yaml.YAMLError as exc:
        raise AgentDefinitionError(
            f"Invalid agent definition YAML: {type(exc).__name__}.",
            source=source,
        ) from exc
    if not isinstance(metadata, dict):
        raise AgentDefinitionError(
            "Agent definition frontmatter must be a YAML object.", source=source
        )
    keys = set(metadata)
    if keys != _FIELDS:
        missing = sorted(_FIELDS - keys)
        unknown = sorted(str(key) for key in keys - _FIELDS)
        details = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if unknown:
            details.append("unknown: " + ", ".join(unknown))
        raise AgentDefinitionError(
            "Agent definition requires exactly seven fields (" + "; ".join(details) + ").",
            source=source,
        )
    name = _string(metadata["name"], "name", source)
    if not _NAME.fullmatch(name) or name != source.entry_name:
        raise AgentDefinitionError(
            "Agent name must be kebab-case and match the file name.", source=source
        )
    description = _string(metadata["description"], "description", source)
    if "\n" in description or "\r" in description:
        raise AgentDefinitionError(
            "Agent description must be a single line.", source=source
        )
    tools = _string_list(metadata["tools"], "tools", source)
    disallowed = _string_list(
        metadata["disallowed_tools"], "disallowed_tools", source
    )
    model = _string(metadata["model"], "model", source)
    max_turns = metadata["max_turns"]
    if (
        isinstance(max_turns, bool)
        or not isinstance(max_turns, int)
        or not 1 <= max_turns <= MAX_DEFINITION_TURNS
    ):
        raise AgentDefinitionError(
            f"Agent max_turns must be an integer from 1 to {MAX_DEFINITION_TURNS}.",
            source=source,
        )
    permission_value = _string(
        metadata["permission_mode"], "permission_mode", source
    )
    try:
        permission_mode = PermissionMode(permission_value)
    except ValueError as exc:
        raise AgentDefinitionError(
            "Agent permission_mode must be strict, default, or allow.", source=source
        ) from exc
    system_prompt = body.strip()
    if not system_prompt:
        raise AgentDefinitionError(
            "Agent definition system prompt must not be empty.", source=source
        )
    return AgentDefinition(
        name,
        description,
        tools,
        disallowed,
        model,
        max_turns,
        permission_mode,
        system_prompt,
        source,
    )


def _split_frontmatter(
    text: str,
    source: AgentDefinitionSource,
) -> tuple[str, str]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        raise AgentDefinitionError(
            "Agent definition must start with YAML frontmatter.", source=source
        )
    closing = next(
        (
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.rstrip("\r\n") == "---"
        ),
        None,
    )
    if closing is None:
        raise AgentDefinitionError(
            "Agent definition frontmatter is not closed.", source=source
        )
    return "".join(lines[1:closing]), "".join(lines[closing + 1 :])


def _string(
    value: Any,
    field: str,
    source: AgentDefinitionSource,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AgentDefinitionError(
            f"Agent field '{field}' must be a non-empty string.", source=source
        )
    return value.strip()


def _string_list(
    value: Any,
    field: str,
    source: AgentDefinitionSource,
) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise AgentDefinitionError(
            f"Agent field '{field}' must be a list.", source=source
        )
    result = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise AgentDefinitionError(
                f"Agent field '{field}' must contain non-empty tool names.",
                source=source,
            )
        result.append(item.strip())
    if len(result) != len(set(result)):
        raise AgentDefinitionError(
            f"Agent field '{field}' must not contain duplicates.", source=source
        )
    return tuple(result)
