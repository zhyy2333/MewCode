from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .models import (
    MAX_CANDIDATES_PER_ROOT,
    AgentDefinitionError,
    AgentDefinitionLayer,
    AgentDefinitionSource,
)


@dataclass(frozen=True)
class AgentDefinitionRoots:
    project: Path
    user: Path
    builtin: Path
    plugins: tuple[Path, ...] = ()

    @classmethod
    def defaults(
        cls,
        workspace_root: Path,
        plugin_roots: Sequence[Path] = (),
    ) -> AgentDefinitionRoots:
        return cls(
            Path(workspace_root).resolve() / ".mewcode" / "agents",
            Path.home().resolve() / ".mewcode" / "agents",
            Path(__file__).resolve().parent / "builtin",
            tuple(Path(root).resolve() for root in plugin_roots),
        )


def discover_agent_sources(
    roots: AgentDefinitionRoots,
) -> tuple[AgentDefinitionSource, ...]:
    discovered: list[AgentDefinitionSource] = []
    entries = (
        (AgentDefinitionLayer.PROJECT, roots.project, "project"),
        (AgentDefinitionLayer.USER, roots.user, "user"),
        (AgentDefinitionLayer.BUILTIN, roots.builtin, "builtin"),
        *(
            (AgentDefinitionLayer.PLUGIN, root, f"plugin:{index}")
            for index, root in enumerate(roots.plugins)
        ),
    )
    for layer, root, origin in entries:
        discovered.extend(_discover_root(layer, Path(root), origin))
    return tuple(
        sorted(
            discovered,
            key=lambda item: (
                -int(item.layer),
                item.entry_name.casefold(),
                item.entry_name,
                str(item.path).casefold(),
                str(item.path),
            ),
        )
    )


def _discover_root(
    layer: AgentDefinitionLayer,
    root: Path,
    origin: str,
) -> tuple[AgentDefinitionSource, ...]:
    try:
        if not root.exists():
            return ()
        if not root.is_dir():
            raise AgentDefinitionError(
                f"Agent definition root is not a directory ({origin})."
            )
        candidates = [
            child
            for child in root.iterdir()
            if child.name.lower().endswith(".md") and not child.is_dir()
        ]
    except AgentDefinitionError:
        raise
    except OSError as exc:
        raise AgentDefinitionError(
            f"Unable to enumerate agent definition root ({origin}): {type(exc).__name__}."
        ) from exc
    candidates.sort(key=lambda item: (item.name.casefold(), item.name))
    if len(candidates) > MAX_CANDIDATES_PER_ROOT:
        raise AgentDefinitionError(
            f"Agent definition root exceeds {MAX_CANDIDATES_PER_ROOT} candidates "
            f"({origin})."
        )
    sources = []
    for path in candidates:
        linked = path.is_symlink()
        sources.append(
            AgentDefinitionSource(
                layer,
                root.resolve(),
                path.absolute(),
                path.stem,
                origin,
                "Symbolic-link agent definitions are not allowed." if linked else None,
            )
        )
    return tuple(sources)
