from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from mewcode.continuity import StoredSkillActivation
from mewcode.prompting import PromptAdditions
from mewcode.tools import Tool, ToolRegistry, ToolSafety
from mewcode.agent import AgentRunView

from .materialization import MaterializedSkill, SkillMaterializer
from .models import (
    MAX_ACTIVE_SHARED_SOP_BYTES,
    MAX_INPUT_BYTES,
    SkillCatalogSnapshot,
    SkillDefinition,
    SkillDefinitionError,
    SkillDiagnostic,
    SkillFingerprint,
    SkillMode,
)
from .process_tool import create_skill_tools


class SkillStateBinding(Protocol):
    def commit_skills(self, active_skills: Sequence[StoredSkillActivation]) -> None:
        ...


@dataclass(frozen=True)
class ActivatedSkill:
    name: str
    input: str
    rendered_sop: str
    definition: SkillDefinition
    package: MaterializedSkill | None
    tools: tuple[Tool, ...]


@dataclass(frozen=True)
class SkillRefreshResult:
    changed: bool
    accepted: bool
    diagnostics: tuple[SkillDiagnostic, ...] = ()


class SkillRuntime:
    def __init__(
        self,
        catalog: SkillCatalogSnapshot,
        workspace_root: Path,
        global_tools: ToolRegistry,
        *,
        binding: SkillStateBinding | None = None,
        materializer: SkillMaterializer | None = None,
        api_key_environment_names: Iterable[str] = (),
    ) -> None:
        self._catalog = catalog
        self._workspace = workspace_root.resolve()
        self._global_tools = global_tools
        self._binding = binding
        self._materializer = materializer or SkillMaterializer()
        self._api_key_names = frozenset(api_key_environment_names)
        self._active: OrderedDict[str, ActivatedSkill] = OrderedDict()

    @property
    def catalog(self) -> SkillCatalogSnapshot:
        return self._catalog

    @property
    def active(self) -> tuple[ActivatedSkill, ...]:
        return tuple(self._active.values())

    def activate(self, name: str, input_text: str = "") -> ActivatedSkill:
        definition = self._catalog.get(name)
        if definition is None:
            raise SkillDefinitionError(f"Unknown Skill: {name}")
        candidate = self._prepare_activation(definition, input_text)
        projected = OrderedDict(self._active)
        previous = projected.get(name)
        projected[name] = candidate
        self._validate_active_sop_limit(projected.values())
        self._commit(projected.values())
        self._active = projected
        if previous is not None:
            self._materializer.release(previous.package)
        return candidate

    def restore(
        self, stored: Sequence[StoredSkillActivation]
    ) -> tuple[SkillDiagnostic, ...]:
        candidate: OrderedDict[str, ActivatedSkill] = OrderedDict()
        diagnostics: list[SkillDiagnostic] = []
        try:
            for item in stored:
                definition = self._catalog.get(item.name)
                if definition is None:
                    diagnostics.append(
                        SkillDiagnostic(item.name, "Saved Skill is no longer available and was ignored.")
                    )
                    continue
                candidate[item.name] = self._prepare_activation(definition, item.input)
            self._validate_active_sop_limit(candidate.values())
            if tuple(candidate) != tuple(item.name for item in stored):
                self._commit(candidate.values())
        except BaseException:
            for item in candidate.values():
                self._materializer.release(item.package)
            raise
        for item in self._active.values():
            self._materializer.release(item.package)
        self._active = candidate
        return tuple(diagnostics)

    def refresh(
        self,
        current_fingerprint: tuple[SkillFingerprint, ...],
        build_candidate: Callable[[], SkillCatalogSnapshot],
    ) -> SkillRefreshResult:
        if current_fingerprint == self._catalog.fingerprint:
            return SkillRefreshResult(False, True)
        try:
            catalog = build_candidate()
            rebound: OrderedDict[str, ActivatedSkill] = OrderedDict()
            diagnostics = list(catalog.diagnostics)
            for old in self._active.values():
                definition = catalog.get(old.name)
                if definition is None:
                    diagnostics.append(
                        SkillDiagnostic(old.name, "Active Skill disappeared and was deactivated.")
                    )
                    continue
                rebound[old.name] = self._prepare_activation(definition, old.input)
            self._validate_active_sop_limit(rebound.values())
            if tuple((item.name, item.input) for item in rebound.values()) != tuple(
                (item.name, item.input) for item in self._active.values()
            ):
                self._commit(rebound.values())
        except Exception as exc:
            for item in locals().get("rebound", {}).values():
                self._materializer.release(item.package)
            return SkillRefreshResult(
                True, False, (SkillDiagnostic("refresh", f"Skill update was rejected: {exc}"),)
            )
        previous = self._active
        self._catalog = catalog
        self._active = rebound
        for item in previous.values():
            self._materializer.release(item.package)
        return SkillRefreshResult(True, True, tuple(diagnostics))

    def prompt_additions(self) -> PromptAdditions:
        available = "\n".join(
            f"- {definition.name}: {definition.description}"
            for definition in self._catalog.definitions.values()
        ) or None
        active_shared = "\n\n".join(
            f"### {item.name}\n{item.rendered_sop}"
            for item in self._active.values()
            if item.definition.mode is SkillMode.SHARED
        ) or None
        return PromptAdditions(
            available_skills=available,
            active_skills=active_shared,
        )

    def shared_tool_names(self) -> frozenset[str]:
        return frozenset(
            name
            for item in self._active.values()
            if item.definition.mode is SkillMode.SHARED
            for name in item.definition.tools
        )

    def active_tool_registry(self) -> ToolRegistry:
        package_tools = ToolRegistry(
            tool for item in self._active.values() for tool in item.tools
        )
        return self._global_tools.merge(package_tools)

    def set_global_tools(self, tools: ToolRegistry) -> None:
        self._global_tools = tools

    def run_view(
        self,
        allowed_safety: set[ToolSafety],
        *,
        isolated_name: str | None = None,
        loader_tool: Tool | None = None,
    ) -> AgentRunView:
        shared = tuple(
            item for item in self._active.values() if item.definition.mode is SkillMode.SHARED
        )
        isolated = self._active.get(isolated_name) if isolated_name is not None else None
        scoped = (*shared, *((isolated,) if isolated is not None else ()))
        package_registry = ToolRegistry(tool for item in scoped for tool in item.tools)
        base = self._global_tools
        if isolated is not None:
            base = base.without({"agent"})
        if loader_tool is not None:
            base = base.without({"load_skill"}).merge(ToolRegistry([loader_tool]))
        combined = base.merge(package_registry)
        if scoped:
            names = {
                name for item in scoped for name in item.definition.tools
            }
            names.add("load_skill")
            if isolated is None and "agent" in combined.names:
                names.add("agent")
            combined = combined.select_names(names)
        safe = combined.select_safety(allowed_safety)
        loader = combined.select_names({"load_skill"})
        if loader.names and "load_skill" not in safe.names:
            safe = safe.merge(loader)
        additions = self.prompt_additions()
        if isolated is not None:
            additions = additions.merged(
                active_skills=f"### {isolated.name}\n{isolated.rendered_sop}"
            )
        return AgentRunView(safe, additions)

    def reset(self, *, persist: bool = True) -> None:
        if persist and self._binding is not None:
            self._binding.commit_skills(())
        previous = self._active
        self._active = OrderedDict()
        for item in previous.values():
            self._materializer.release(item.package)

    def close(self) -> None:
        self.reset(persist=False)
        self._materializer.close()

    def _prepare_activation(
        self, definition: SkillDefinition, input_text: str
    ) -> ActivatedSkill:
        if len(input_text.encode("utf-8")) > MAX_INPUT_BYTES:
            raise SkillDefinitionError("Skill input exceeds 64 KiB.")
        body = _read_body(definition)
        rendered = body.replace("{{input}}", input_text)
        if "{{input}}" not in body and input_text:
            rendered = f"{rendered}\n\nTask input:\n{input_text}"
        package = self._materializer.materialize(definition)
        try:
            tools = create_skill_tools(
                definition.package_tools,
                package,
                self._workspace,
                api_key_environment_names=self._api_key_names,
            )
        except BaseException:
            self._materializer.release(package)
            raise
        return ActivatedSkill(
            definition.name, input_text, rendered, definition, package, tools
        )

    def _validate_active_sop_limit(self, values: Iterable[ActivatedSkill]) -> None:
        total = sum(
            len(item.rendered_sop.encode("utf-8"))
            for item in values
            if item.definition.mode is SkillMode.SHARED
        )
        if total > MAX_ACTIVE_SHARED_SOP_BYTES:
            raise SkillDefinitionError("Active shared Skill SOPs exceed 256 KiB.")

    def _commit(self, values: Iterable[ActivatedSkill]) -> None:
        if self._binding is not None:
            self._binding.commit_skills(
                tuple(StoredSkillActivation(item.name, item.input) for item in values)
            )


def _read_body(definition: SkillDefinition) -> str:
    body = definition.body
    from .paths import fingerprint_source

    try:
        current = fingerprint_source(
            definition.source.root,
            definition.source.entry_path,
            definition.source.package_dir,
        )
    except (OSError, SkillDefinitionError) as exc:
        raise SkillDefinitionError(
            f"Skill '{definition.name}' changed before activation; retry after refresh."
        ) from exc
    if current != body.fingerprint:
        raise SkillDefinitionError(
            f"Skill '{definition.name}' changed before activation; retry after refresh."
        )
    try:
        with body.path.open("rb") as handle:
            handle.seek(body.byte_offset)
            raw = handle.read(body.byte_size + 1)
    except OSError as exc:
        raise SkillDefinitionError(f"Skill '{definition.name}' SOP could not be read.") from exc
    if len(raw) != body.byte_size:
        raise SkillDefinitionError(
            f"Skill '{definition.name}' changed before activation; retry after refresh."
        )
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SkillDefinitionError(f"Skill '{definition.name}' SOP is not UTF-8.") from exc
