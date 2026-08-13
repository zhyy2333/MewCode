from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence

from .models import (
    MAX_SELECTED_PROMPT_BYTES,
    AgentCatalogError,
    AgentDefinition,
    AgentDefinitionCatalog,
    AgentDefinitionDiagnostic,
    AgentDefinitionError,
    AgentDefinitionLayer,
    AgentDefinitionSource,
)
from .parser import parse_agent_definition


def build_agent_catalog(
    sources: Sequence[AgentDefinitionSource],
    *,
    profile_names: Iterable[str] | object,
    base_tool_names: Iterable[str],
    globally_forbidden_names: Iterable[str] = ("agent", "load_skill"),
) -> AgentDefinitionCatalog:
    profiles = _profile_names(profile_names)
    known_tools = frozenset(base_tool_names)
    forbidden = frozenset(globally_forbidden_names)
    by_name: dict[str, list[AgentDefinitionSource]] = defaultdict(list)
    for source in sources:
        by_name[source.entry_name].append(source)

    selected: dict[str, AgentDefinition] = {}
    diagnostics: list[AgentDefinitionDiagnostic] = []
    for name in sorted(by_name, key=lambda value: (value.casefold(), value)):
        valid_by_layer: dict[AgentDefinitionLayer, list[AgentDefinition]] = defaultdict(list)
        for source in by_name[name]:
            try:
                definition = parse_agent_definition(source)
                _validate_semantics(definition, profiles, known_tools, forbidden)
            except AgentDefinitionError as exc:
                diagnostics.append(
                    AgentDefinitionDiagnostic(name, source, str(exc))
                )
            else:
                valid_by_layer[source.layer].append(definition)

        for layer, candidates in valid_by_layer.items():
            if len(candidates) > 1:
                origins = ", ".join(
                    sorted(
                        (candidate.source.origin for candidate in candidates),
                        key=lambda value: (value.casefold(), value),
                    )[:8]
                )
                raise AgentCatalogError(
                    f"Conflicting valid agent definitions for '{name}' in "
                    f"{layer.name.lower()} sources: {origins}."
                )
        for layer in sorted(AgentDefinitionLayer, reverse=True):
            candidates = valid_by_layer.get(layer, ())
            if candidates:
                selected[name] = candidates[0]
                break

    total = sum(
        len(definition.system_prompt.encode("utf-8"))
        for definition in selected.values()
    )
    if total > MAX_SELECTED_PROMPT_BYTES:
        raise AgentCatalogError(
            f"Selected agent prompts exceed {MAX_SELECTED_PROMPT_BYTES} bytes."
        )
    diagnostics.sort(
        key=lambda item: (
            item.name.casefold(),
            item.name,
            -int(item.source.layer),
            str(item.source.path).casefold(),
            str(item.source.path),
        )
    )
    return AgentDefinitionCatalog(selected, tuple(diagnostics))


def _validate_semantics(
    definition: AgentDefinition,
    profiles: frozenset[str],
    known_tools: frozenset[str],
    forbidden: frozenset[str],
) -> None:
    if definition.model != "inherit" and definition.model not in profiles:
        raise AgentDefinitionError(
            f"Unknown Profile '{definition.model}'.", source=definition.source
        )
    for tool in (*definition.tools, *definition.disallowed_tools):
        if tool not in known_tools:
            raise AgentDefinitionError(
                f"Unknown agent tool '{tool}'.", source=definition.source
            )
    blocked = forbidden.intersection(definition.tools)
    if blocked:
        raise AgentDefinitionError(
            "Agent tool allowlist contains a globally forbidden tool: "
            + ", ".join(sorted(blocked))
            + ".",
            source=definition.source,
        )


def _profile_names(value: Iterable[str] | object) -> frozenset[str]:
    entries = getattr(value, "entries", None)
    if entries is not None:
        return frozenset(entries)
    return frozenset(value)  # type: ignore[arg-type]
