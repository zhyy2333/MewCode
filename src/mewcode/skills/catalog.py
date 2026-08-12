from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping

from mewcode.config import ProfileCatalog

from .models import (
    SkillCatalogError,
    SkillCatalogSnapshot,
    SkillDefinition,
    SkillDefinitionError,
    SkillDiagnostic,
    SkillSource,
)
from .parser import parse_skill


def build_skill_catalog(
    sources: Iterable[SkillSource],
    *,
    system_command_identifiers: Iterable[str] = (),
    profiles: ProfileCatalog | None = None,
    global_tool_names: Iterable[str] | None = None,
    mcp_status: Mapping[str, str] | None = None,
) -> SkillCatalogSnapshot:
    diagnostics: list[SkillDiagnostic] = []
    by_name_layer: dict[tuple[str, int], list[SkillDefinition]] = defaultdict(list)
    fingerprints = []
    for source in sources:
        fingerprints.append(source.fingerprint)
        try:
            definition = parse_skill(source)
        except (SkillDefinitionError, OSError) as exc:
            diagnostics.append(SkillDiagnostic(source.label, str(exc)))
            continue
        by_name_layer[(definition.name, int(source.layer))].append(definition)

    conflicts = [
        (name, definitions)
        for (name, _layer), definitions in by_name_layer.items()
        if len(definitions) > 1
    ]
    if conflicts:
        details = "; ".join(
            f"'{name}': {', '.join(item.source.label for item in definitions)}"
            for name, definitions in conflicts
        )
        raise SkillCatalogError(f"Duplicate Skill definitions in one layer: {details}")

    by_name: dict[str, list[SkillDefinition]] = defaultdict(list)
    for definitions in by_name_layer.values():
        by_name[definitions[0].name].append(definitions[0])
    selected = {
        name: max(definitions, key=lambda item: int(item.source.layer))
        for name, definitions in by_name.items()
    }
    reserved: dict[str, str] = {
        identifier.casefold(): f"system command '{identifier}'"
        for identifier in system_command_identifiers
    }
    for name, definition in selected.items():
        key = name.casefold()
        if key in reserved:
            raise SkillCatalogError(
                f"Skill command conflict for '{name}' from {definition.source.label} with {reserved[key]}."
            )
        reserved[key] = definition.source.label
        if definition.model is not None:
            if profiles is None:
                raise SkillCatalogError(
                    f"Skill '{name}' references Profile '{definition.model}' but no Profile catalog is available."
                )
            try:
                profiles.require(definition.model)
            except Exception as exc:
                raise SkillCatalogError(
                    f"Skill '{name}' from {definition.source.label} references missing Profile '{definition.model}'."
                ) from exc

    if global_tool_names is not None:
        _validate_whitelists(selected, set(global_tool_names), mcp_status or {})
    return SkillCatalogSnapshot.create(
        selected,
        tuple(diagnostics),
        tuple(sorted(fingerprints, key=lambda item: (item.root, item.files))),
    )


def _validate_whitelists(
    definitions: Mapping[str, SkillDefinition],
    global_names: set[str],
    mcp_status: Mapping[str, str],
) -> None:
    owners = {
        tool.public_name: definition.name
        for definition in definitions.values()
        for tool in definition.package_tools
    }
    errors: list[str] = []
    for public_name, owner in owners.items():
        if public_name in global_names:
            errors.append(
                f"Skill '{owner}' package tool '{public_name}' conflicts with a registered global tool."
            )
    for definition in definitions.values():
        own = definition.package_tool_names
        for name in definition.tools:
            owner = owners.get(name)
            if owner is not None and owner != definition.name:
                errors.append(
                    f"Skill '{definition.name}' references package tool '{name}' owned by Skill '{owner}'."
                )
            elif name not in global_names and name not in own:
                status = _mcp_detail(name, mcp_status)
                errors.append(
                    f"Skill '{definition.name}' from {definition.source.label} references missing tool '{name}'{status}."
                )
    if errors:
        raise SkillCatalogError(" ".join(errors))


def _mcp_detail(tool_name: str, statuses: Mapping[str, str]) -> str:
    server, separator, _local = tool_name.partition("__")
    if separator and server in statuses:
        return f" (MCP status: {statuses[server]})"
    return ""
