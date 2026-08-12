from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Sequence
from typing import Protocol

from mewcode.agent import AgentEvent, AgentMode, AgentRun, AgentRunner
from mewcode.prompting import PromptAdditions, PromptRunContext
from mewcode.providers import ChatMessage
from mewcode.tools import ToolResult, ToolSafety

from .history import project_recent_turns
from .models import MAX_ISOLATED_DEPTH, SkillDefinitionError, SkillMode
from .runtime import ActivatedSkill, SkillRuntime


class IsolatedRunnerFactory(Protocol):
    def __call__(self, profile_name: str | None) -> AgentRunner:
        ...


class SkillInvocation:
    def __init__(
        self,
        coordinator: SkillCoordinator,
        name: str,
        input_text: str,
        depth: int,
    ) -> None:
        self._coordinator = coordinator
        self._name = name
        self._input = input_text
        self._depth = depth
        self._result: ToolResult | None = None
        self._active_run: AgentRun | None = None
        self._started = False

    async def events(self) -> AsyncIterator[AgentEvent]:
        if self._started:
            raise RuntimeError("A Skill invocation can only be consumed once.")
        self._started = True
        try:
            definition = self._coordinator.runtime.catalog.get(self._name)
            if definition is None:
                raise SkillDefinitionError(f"Unknown Skill: {self._name}")
            if (
                definition.mode is SkillMode.ISOLATED
                and self._depth >= MAX_ISOLATED_DEPTH
            ):
                self._result = ToolResult(
                    False,
                    "load_skill",
                    "",
                    f"Isolated Skill nesting exceeds {MAX_ISOLATED_DEPTH} levels.",
                )
                return
            activated = self._coordinator.runtime.activate(self._name, self._input)
            if activated.definition.mode is SkillMode.SHARED:
                self._result = ToolResult(
                    True,
                    "load_skill",
                    f"Shared Skill '{self._name}' is active.",
                )
                return
            async for event in self._run_isolated(activated):
                yield event
        except asyncio.CancelledError:
            await self.cancel()
            raise
        except Exception as exc:
            self._result = ToolResult(False, "load_skill", "", str(exc))

    async def _run_isolated(
        self, activated: ActivatedSkill
    ) -> AsyncIterator[AgentEvent]:
        definition = activated.definition
        history = project_recent_turns(
            self._coordinator.history_supplier(), definition.history or 0
        )
        runner = self._coordinator.runner_factory(definition.model)
        additions = self._coordinator.base_additions_supplier()
        child_coordinator = SkillCoordinator(
            self._coordinator.runtime,
            runner_factory=self._coordinator.runner_factory,
            history_supplier=self._coordinator.history_supplier,
            base_additions_supplier=self._coordinator.base_additions_supplier,
            allowed_safety_supplier=self._coordinator.allowed_safety_supplier,
            depth=self._depth + 1,
        )
        from .control import LoadSkillTool

        child_loader = LoadSkillTool(child_coordinator)
        context = PromptRunContext(
            task=self._input or f"Run Skill '{definition.name}'.",
            additions=additions,
        )
        run = runner.start(
            history,
            self._input or f"Run Skill '{definition.name}'.",
            self._coordinator.runtime.active_tool_registry(),
            AgentMode.DIRECT,
            context,
            run_view_provider=lambda: self._coordinator.runtime.run_view(
                self._coordinator.allowed_safety_supplier(),
                isolated_name=definition.name,
                loader_tool=child_loader,
            ),
        )
        self._active_run = run
        try:
            async for event in run.events():
                yield event
            outcome = run.outcome
            if outcome.completed:
                self._result = ToolResult(
                    True, "load_skill", outcome.final_text
                )
            else:
                self._result = ToolResult(
                    False,
                    "load_skill",
                    "",
                    outcome.error or f"Isolated Skill stopped: {outcome.reason.value}",
                )
        finally:
            self._active_run = None

    @property
    def result(self) -> ToolResult:
        if self._result is None:
            raise RuntimeError("Skill invocation has not completed.")
        return self._result

    async def cancel(self) -> None:
        if self._active_run is not None:
            await self._active_run.cancel()


class SkillCoordinator:
    def __init__(
        self,
        runtime: SkillRuntime,
        *,
        runner_factory: IsolatedRunnerFactory,
        history_supplier: Callable[[], Sequence[ChatMessage]],
        base_additions_supplier: Callable[[], PromptAdditions] = PromptAdditions,
        allowed_safety_supplier: Callable[[], set[ToolSafety]] = lambda: {
            ToolSafety.READ_ONLY,
            ToolSafety.SIDE_EFFECT,
        },
        depth: int = 0,
    ) -> None:
        self.runtime = runtime
        self.runner_factory = runner_factory
        self.history_supplier = history_supplier
        self.base_additions_supplier = base_additions_supplier
        self.allowed_safety_supplier = allowed_safety_supplier
        self.depth = depth

    def invoke(self, name: str, input_text: str = "") -> SkillInvocation:
        if not isinstance(name, str) or not name:
            raise SkillDefinitionError("Skill name must be a non-empty string.")
        if not isinstance(input_text, str):
            raise SkillDefinitionError("Skill input must be a string.")
        return SkillInvocation(self, name, input_text, self.depth)
