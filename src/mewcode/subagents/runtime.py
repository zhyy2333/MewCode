from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Mapping
from pathlib import Path

from mewcode.agent import (
    AgentContextStatus,
    AgentMode,
    AgentProgress,
    AgentRun,
    AgentRunConfig,
    AgentRunner,
    StopReason,
    ToolScheduler,
)
from mewcode.context import ContextArchive, ContextConfig, ContextManager
from mewcode.hooks import HookRuntime
from mewcode.prompting import (
    PromptAdditions,
    PromptBuilder,
    PromptEnvironmentProvider,
    PromptRunContext,
)
from mewcode.providers import (
    CaptureOnlyRequestBoundary,
    LLMProvider,
    RequestSnapshotSlot,
)
from mewcode.tools import ToolRegistry, Workspace, WorkspaceToolBinder

from .permissions import SubagentPermissionController
from .scoped_tools import FileReadObservationCache, build_task_scoped_registry
from .tasks import (
    SubagentDriverOutcome,
    SubagentKind,
    SubagentLaunch,
    SubagentProgress,
    SubagentTaskStatus,
)


ProviderSupplier = Callable[[str], LLMProvider]
ContextConfigFactory = Callable[[str], ContextConfig]
AdditionsSupplier = Callable[[], PromptAdditions]


class SubagentRuntimeFactory:
    def __init__(
        self,
        *,
        provider_supplier: ProviderSupplier,
        prompt_builder: PromptBuilder,
        workspace: Workspace,
        hook_runtime: HookRuntime | None,
        context_config_factory: ContextConfigFactory,
    ) -> None:
        self._provider_supplier = provider_supplier
        self._prompt_builder = prompt_builder
        self._workspace = workspace
        self._hook_runtime = hook_runtime
        self._context_config_factory = context_config_factory

    @property
    def workspace(self) -> Workspace:
        return self._workspace

    @property
    def hook_runtime(self) -> HookRuntime | None:
        return self._hook_runtime

    def create(self, task_id: str, launch: SubagentLaunch) -> SubagentRuntime:
        return self._create_with(
            task_id,
            launch,
            workspace=self._workspace,
            prompt_builder=self._prompt_builder,
            hook_runtime=self._hook_runtime,
            tools=launch.tools,
        )

    def create_bound(
        self,
        task_id: str,
        launch: SubagentLaunch,
        *,
        workspace_root: Path,
        process_environment: Mapping[str, str],
        hook_runtime: HookRuntime | None = None,
        additional_tools: ToolRegistry | None = None,
    ) -> SubagentRuntime:
        workspace = Workspace(workspace_root)
        tools = WorkspaceToolBinder().bind(
            launch.tools,
            workspace,
            process_environment=process_environment,
            additional=additional_tools,
        )
        return self._create_with(
            task_id,
            launch,
            workspace=workspace,
            prompt_builder=PromptBuilder(PromptEnvironmentProvider(workspace.root)),
            hook_runtime=hook_runtime,
            tools=tools,
        )

    def _create_with(
        self,
        task_id: str,
        launch: SubagentLaunch,
        *,
        workspace: Workspace,
        prompt_builder: PromptBuilder,
        hook_runtime: HookRuntime | None,
        tools: ToolRegistry,
    ) -> SubagentRuntime:
        provider = self._provider_supplier(launch.profile_name)
        observations = FileReadObservationCache(workspace_root=workspace.root)
        tools = build_task_scoped_registry(tools, observations)
        permissions = SubagentPermissionController.from_snapshot(
            workspace,
            launch.permission_rules,
            launch.permission_mode,
        )
        scheduler = ToolScheduler(
            permissions,
            hook_runtime=hook_runtime,
            policy=launch.policy,
        )
        archive = ContextArchive(
            workspace.root,
            session_id_factory=lambda: f"subagent-{task_id}",
        )
        archive.start(skip_stale_cleanup=True)
        context_manager = ContextManager(
            provider,
            archive,
            self._context_config_factory(launch.profile_name),
            hook_runtime,
        )
        max_iterations = (
            launch.definition.max_turns
            if launch.definition is not None
            else (launch.seed.max_iterations if launch.seed is not None else 20)
        )
        runner = AgentRunner(
            provider,
            scheduler,
            AgentRunConfig(max_iterations=max_iterations),
            prompt_builder=prompt_builder,
            context_manager=context_manager,
            hook_runtime=hook_runtime,
            profile_name=launch.profile_name,
            permission_mode_supplier=lambda: launch.permission_mode,
            allowed_safety=launch.allowed_safety,
            request_boundary_factory=lambda slot: CaptureOnlyRequestBoundary(slot),
            hook_component="subagent",
        )
        additions = (
            _defined_additions(launch.additions, launch.definition.system_prompt)
            if launch.kind is SubagentKind.DEFINED and launch.definition is not None
            else PromptAdditions()
        )
        run = runner.start(
            (),
            launch.task_text,
            tools,
            AgentMode.DIRECT,
            PromptRunContext(launch.task_text, additions=additions),
            history_commit_sink=None,
            seed_request=launch.seed,
            allowed_safety=launch.allowed_safety,
        )
        return SubagentRuntime(
            task_id,
            launch,
            run,
            provider,
            workspace,
            hook_runtime,
            context_manager,
            observations,
            permissions,
            scheduler,
        )


class SubagentRuntime:
    def __init__(
        self,
        task_id: str,
        launch: SubagentLaunch,
        run: AgentRun,
        provider: LLMProvider,
        workspace: Workspace,
        hook_runtime: HookRuntime | None,
        context_manager: ContextManager,
        observations: FileReadObservationCache,
        permissions: SubagentPermissionController,
        scheduler: ToolScheduler,
    ) -> None:
        self.task_id = task_id
        self.launch = launch
        self.run = run
        self.provider = provider
        self.workspace = workspace
        self.hook_runtime = hook_runtime
        self.context_manager = context_manager
        self.observations = observations
        self.permissions = permissions
        self.scheduler = scheduler
        self._outcome: SubagentDriverOutcome | None = None
        self._closed = False

    async def events(self) -> AsyncIterator[SubagentProgress]:
        scope = (
            self.hook_runtime.bind_scope(
                component="subagent",
                subagent_task_id=self.task_id,
                parent_run_id=self.launch.parent.run_id,
                preserve_fork_prefix=self.launch.kind is SubagentKind.FORK,
            )
            if self.hook_runtime is not None
            else None
        )
        if scope is not None:
            scope.__enter__()
        try:
            async for event in self.run.events():
                if isinstance(event, AgentProgress):
                    yield SubagentProgress(
                        event.iteration,
                        event.phase,
                        event.message,
                    )
                elif isinstance(event, AgentContextStatus):
                    yield SubagentProgress(
                        event.iteration,
                        "context",
                        event.status.message,
                    )
        finally:
            if scope is not None:
                scope.__exit__(None, None, None)
        outcome = self.run.outcome
        status = (
            SubagentTaskStatus.COMPLETED
            if outcome.completed
            else (
                SubagentTaskStatus.CANCELLED
                if outcome.reason is StopReason.CANCELLED
                else SubagentTaskStatus.FAILED
            )
        )
        self._outcome = SubagentDriverOutcome(
            status,
            outcome.final_text,
            outcome.error,
            outcome.usage,
        )

    @property
    def outcome(self) -> SubagentDriverOutcome:
        if self._outcome is None:
            raise RuntimeError("The subagent runtime has not completed.")
        return self._outcome

    async def cancel(self) -> None:
        await self.run.cancel()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.hook_runtime is not None:
            self.hook_runtime.cleanup_task_prompts(self.task_id)
        self.context_manager.close()


def _defined_additions(
    base: PromptAdditions,
    role: str,
) -> PromptAdditions:
    return PromptAdditions(
        custom_instructions=base.custom_instructions,
        agent_role=role,
        long_term_memory=base.long_term_memory,
        available_skills=None,
        active_skills=None,
        active_skill=None,
    )
