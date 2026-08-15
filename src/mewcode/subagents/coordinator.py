from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping

from mewcode.agent import AgentControlContext, ForkRequestSeed
from mewcode.permissions import PermissionRuleStore
from mewcode.prompting import PromptAdditions
from mewcode.tools import ToolRegistry
from mewcode.worktrees import WorktreeLifecycleService

from .models import (
    MAX_TASK_BYTES,
    AgentIsolation,
    AgentDefinitionCatalog,
    SubagentKind,
    SubagentParent,
    SubagentPlacement,
)
from .permissions import persistent_permission_snapshot
from .policy import (
    DEFAULT_GLOBALLY_FORBIDDEN_TOOLS,
    build_defined_tool_scope,
    build_fork_tool_policy,
)
from .runtime import SubagentRuntimeFactory
from .tasks import SubagentLaunch
from .workspace_runtime import WorkspaceRuntimeBundleFactory
from .worktree_driver import WorktreeSubagentDriver


class SubagentCoordinationError(ValueError):
    pass


class SubagentCoordinator:
    def __init__(
        self,
        catalog: AgentDefinitionCatalog,
        runtime_factory: SubagentRuntimeFactory,
        base_registry: ToolRegistry,
        parent_rule_store: PermissionRuleStore,
        *,
        background_capable_names: Iterable[str],
        additions_supplier: Callable[[], PromptAdditions] = PromptAdditions,
        worktree_additions_supplier: Callable[[], PromptAdditions] | None = None,
        globally_forbidden_names: Iterable[str] = DEFAULT_GLOBALLY_FORBIDDEN_TOOLS,
        worktree_lifecycle: WorktreeLifecycleService | None = None,
        workspace_runtime_factory: WorkspaceRuntimeBundleFactory | None = None,
    ) -> None:
        self._catalog = catalog
        self._runtime_factory = runtime_factory
        self._base_registry = base_registry
        self._parent_rule_store = parent_rule_store
        self._background_capable_names = frozenset(background_capable_names)
        self._additions_supplier = additions_supplier
        self._worktree_additions_supplier = (
            worktree_additions_supplier or additions_supplier
        )
        self._globally_forbidden_names = frozenset(globally_forbidden_names)
        self._worktree_lifecycle = worktree_lifecycle
        self._workspace_runtime_factory = workspace_runtime_factory

    def prepare(
        self,
        arguments: Mapping[str, object],
        context: AgentControlContext | None,
    ) -> SubagentLaunch:
        allowed_fields = {"type", "task", "role", "background"}
        unknown = set(arguments).difference(allowed_fields)
        if unknown:
            raise SubagentCoordinationError(
                "Unknown agent argument: " + ", ".join(sorted(unknown)) + "."
            )
        if context is None:
            raise SubagentCoordinationError(
                "The agent call is missing its actual parent request context."
            )
        kind_value = arguments.get("type")
        if not isinstance(kind_value, str):
            raise SubagentCoordinationError("Agent type must be 'defined' or 'fork'.")
        try:
            kind = SubagentKind(kind_value)
        except ValueError as exc:
            raise SubagentCoordinationError(
                "Agent type must be 'defined' or 'fork'."
            ) from exc
        task_value = arguments.get("task")
        if not isinstance(task_value, str) or not task_value.strip():
            raise SubagentCoordinationError("Agent task must be a non-empty string.")
        task = task_value.strip()
        if len(task.encode("utf-8")) > MAX_TASK_BYTES:
            raise SubagentCoordinationError(
                f"Agent task exceeds {MAX_TASK_BYTES} UTF-8 bytes."
            )
        role_value = arguments.get("role")
        background_present = "background" in arguments
        background_value = arguments.get("background", False)
        if not isinstance(background_value, bool):
            raise SubagentCoordinationError("Agent background must be a boolean.")
        if kind is SubagentKind.DEFINED:
            if not isinstance(role_value, str) or not role_value.strip():
                raise SubagentCoordinationError(
                    "Defined agent calls require a non-empty role."
                )
            return self._prepare_defined(
                task,
                role_value.strip(),
                background_value,
                context,
            )
        if role_value is not None:
            raise SubagentCoordinationError("Fork agent calls do not accept a role.")
        if background_present:
            raise SubagentCoordinationError(
                "Fork agent calls are always background and do not accept background."
            )
        return self._prepare_fork(task, context)

    def _prepare_defined(
        self,
        task: str,
        role: str,
        background: bool,
        context: AgentControlContext,
    ) -> SubagentLaunch:
        definition = self._catalog.get(role)
        if definition is None:
            raise SubagentCoordinationError(f"Unknown agent role '{role}'.")
        parent_tools = context.parent_request.tools
        parent_names = parent_tools.names if parent_tools is not None else ()
        scope = build_defined_tool_scope(
            self._base_registry,
            definition,
            parent_mode_names=parent_names,
            background_capable_names=self._background_capable_names,
            allowed_safety=context.allowed_safety,
            globally_forbidden_names=self._globally_forbidden_names,
        )
        profile_name = (
            context.profile_name if definition.model == "inherit" else definition.model
        )
        base = (
            self._worktree_additions_supplier()
            if definition.isolation is AgentIsolation.WORKTREE
            else self._additions_supplier()
        )
        additions = PromptAdditions(
            custom_instructions=base.custom_instructions,
            long_term_memory=base.long_term_memory,
        )
        holder: dict[str, SubagentLaunch] = {}

        def create(task_id: str):
            if definition.isolation is AgentIsolation.WORKTREE:
                if self._worktree_lifecycle is None or self._workspace_runtime_factory is None:
                    raise RuntimeError("Worktree isolation is unavailable in this workspace.")
                return WorktreeSubagentDriver(
                    task_id,
                    holder["launch"],
                    self._worktree_lifecycle,
                    self._workspace_runtime_factory,
                )
            return self._runtime_factory.create(task_id, holder["launch"])

        launch = SubagentLaunch(
            SubagentKind.DEFINED,
            definition.name,
            profile_name,
            SubagentParent(context.run_id, context.iteration),
            (
                SubagentPlacement.BACKGROUND
                if background
                else SubagentPlacement.FOREGROUND
            ),
            create,
            task_text=task,
            definition=definition,
            tools=scope.registry,
            policy=scope.policy,
            permission_rules=persistent_permission_snapshot(
                self._parent_rule_store.snapshot()
            ),
            permission_mode=definition.permission_mode,
            allowed_safety=context.allowed_safety,
            additions=additions,
        )
        holder["launch"] = launch
        return launch

    def _prepare_fork(
        self,
        task: str,
        context: AgentControlContext,
    ) -> SubagentLaunch:
        parent_tools = context.parent_request.tools
        parent_names = parent_tools.names if parent_tools is not None else ()
        policy = build_fork_tool_policy(
            parent_tools,
            background_capable_names=self._background_capable_names,
            parent_mode_names=parent_names,
            allowed_safety=context.allowed_safety,
            globally_forbidden_names=self._globally_forbidden_names,
        )
        seed = ForkRequestSeed(
            context.profile_name,
            context.parent_request,
            context.run_id,
            context.iteration,
            context.permission_mode,
            context.max_iterations,
            context.allowed_safety,
        )
        holder: dict[str, SubagentLaunch] = {}

        def create(task_id: str):
            return self._runtime_factory.create(task_id, holder["launch"])

        launch = SubagentLaunch(
            SubagentKind.FORK,
            None,
            context.profile_name,
            SubagentParent(context.run_id, context.iteration),
            SubagentPlacement.BACKGROUND,
            create,
            task_text=task,
            tools=parent_tools or ToolRegistry([]),
            policy=policy,
            permission_rules=persistent_permission_snapshot(
                self._parent_rule_store.snapshot()
            ),
            permission_mode=context.permission_mode,
            allowed_safety=context.allowed_safety,
            additions=PromptAdditions(),
            seed=seed,
        )
        holder["launch"] = launch
        return launch
