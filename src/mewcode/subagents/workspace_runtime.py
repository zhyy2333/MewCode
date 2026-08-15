from __future__ import annotations

from dataclasses import dataclass, replace
import os
from pathlib import Path
from collections.abc import Mapping, Sequence
from types import MappingProxyType

from mewcode.continuity import ContinuityPaths, InstructionLoader
from mewcode.continuity.memory_prompt import load_readonly_project_memory
from mewcode.hooks import (
    CommandHookAction,
    HookActionExecutor,
    HookCatalog,
    HookConfigLoader,
    HookPaths,
    HookProcessState,
    HookRule,
    HookRuntime,
    HookSource,
    HttpHookAction,
)
from mewcode.mcp import McpConfigLoader, McpConfigPaths, McpRuntime
from mewcode.mcp import McpServerConfig
from mewcode.mcp.naming import permission_namespace_prefix
from mewcode.prompting import PromptAdditions
from mewcode.tools import ToolRegistry, Workspace, create_builtin_registry
from mewcode.worktrees import WorktreeLease

from .runtime import SubagentRuntime, SubagentRuntimeFactory
from .tasks import SubagentLaunch


@dataclass
class WorkspaceRuntimeBundle:
    runtime: SubagentRuntime
    hook_runtime: HookRuntime | None = None
    mcp_runtime: McpRuntime | None = None
    _closed: bool = False

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        errors: list[BaseException] = []
        if self.mcp_runtime is not None:
            try:
                self.mcp_runtime.close()
            except BaseException as exc:
                errors.append(exc)
        if self.hook_runtime is not None:
            try:
                await self.hook_runtime.close()
            except BaseException as exc:
                errors.append(exc)
        try:
            await self.runtime.close()
        except BaseException as exc:
            errors.append(exc)
        if errors:
            raise RuntimeError("Worktree runtime cleanup did not finish cleanly.") from errors[0]


class WorkspaceRuntimeBundleFactory:
    def __init__(
        self,
        runtime_factory: SubagentRuntimeFactory,
        *,
        project_trusted: bool = False,
        api_key_environment_names: Sequence[str] = (),
        hook_once_state: set[object] | None = None,
        hook_process_state: HookProcessState | None = None,
        frozen_user_mcp: Sequence[McpServerConfig] = (),
        frozen_user_hooks: Sequence[HookRule] = (),
    ) -> None:
        self._runtime_factory = runtime_factory
        self._project_trusted = project_trusted
        self._api_key_environment_names = tuple(api_key_environment_names)
        self._hook_once_state = hook_once_state
        self._hook_process_state = hook_process_state
        self._frozen_user_mcp = tuple(frozen_user_mcp)
        self._frozen_user_hooks = tuple(frozen_user_hooks)

    async def create(
        self,
        lease: WorktreeLease,
        *,
        task_id: str,
        launch: SubagentLaunch,
    ) -> WorkspaceRuntimeBundle:
        paths = ContinuityPaths.for_workspace(lease.environment.root)
        project_instructions = InstructionLoader().load_project(paths).project_content
        project_memory = load_readonly_project_memory(lease.environment.root).content
        additions = PromptAdditions(
            custom_instructions=_join(
                _join(
                    _isolation_notice(lease),
                    project_instructions,
                ),
                launch.additions.custom_instructions,
            ),
            long_term_memory=_join(
                project_memory,
                launch.additions.long_term_memory,
            ),
        )
        bound_launch = replace(launch, additions=additions)
        hook_runtime = self._create_hook_runtime(
            lease.environment.root,
            lease.environment.process_environment,
            task_id,
        )
        mcp_runtime, mcp_tools = self._create_mcp_runtime(
            lease.environment.root,
            lease.environment.process_environment,
            launch,
        )
        try:
            runtime = self._runtime_factory.create_bound(
                task_id,
                bound_launch,
                workspace_root=lease.environment.root,
                process_environment=lease.environment.process_environment,
                hook_runtime=hook_runtime,
                additional_tools=mcp_tools,
            )
        except BaseException:
            if mcp_runtime is not None:
                mcp_runtime.close()
            await hook_runtime.close()
            raise
        return WorkspaceRuntimeBundle(runtime, hook_runtime, mcp_runtime)

    def _create_hook_runtime(
        self,
        root: Path,
        environment: Mapping[str, str],
        task_id: str,
    ) -> HookRuntime:
        loader = HookConfigLoader()
        paths = HookPaths.for_workspace(root)
        project_rules = (
            *loader.load_file(paths.project, HookSource.PROJECT),
            *loader.load_file(paths.project_local, HookSource.PROJECT_LOCAL),
        )
        rules = (
            *self._frozen_user_hooks,
            *project_rules,
        )
        by_event: dict[object, list[HookRule]] = {}
        for rule in rules:
            by_event.setdefault(rule.event, []).append(rule)
        catalog = HookCatalog(
            tuple(rules),
            MappingProxyType({event: tuple(items) for event, items in by_event.items()}),
            any(
                rule.key.source is HookSource.PROJECT
                and isinstance(rule.action, (CommandHookAction, HttpHookAction))
                for rule in project_rules
            ),
        )
        if not catalog.rules:
            return HookRuntime.empty(root, f"subagent-{task_id}")
        return HookRuntime(
            catalog,
            HookActionExecutor(
                root,
                api_key_environment_names=self._api_key_environment_names,
                environment_overrides=environment,
            ),
            workspace=root,
            session_id=f"subagent-{task_id}",
            project_trusted=self._project_trusted,
            once_state=self._hook_once_state,
            process_state=self._hook_process_state,
        )

    def _create_mcp_runtime(
        self,
        root: Path,
        environment: Mapping[str, str],
        launch: SubagentLaunch,
    ) -> tuple[McpRuntime | None, ToolRegistry]:
        loader_environment = os.environ.copy()
        loader_environment.update(environment)
        result = McpConfigLoader(loader_environment).load_project(
            McpConfigPaths.for_workspace(Workspace(root)).project
        )
        merged = {config.name: config for config in self._frozen_user_mcp}
        for name in result.project_server_names:
            merged.pop(name, None)
        merged.update({config.name: config for config in result.project_servers})
        required_names = set(launch.tools.names)
        configs = tuple(
            config
            for config in merged.values()
            if any(
                name.startswith(permission_namespace_prefix(config.name))
                for name in required_names
            )
        )
        if not configs:
            return None, ToolRegistry([])
        runtime = McpRuntime(root, environment_overrides=environment)
        reserved = set(create_builtin_registry(Workspace(root)).names)
        started = runtime.start(configs, reserved)
        return runtime, ToolRegistry(started.tools)


def _join(first: str | None, second: str | None) -> str | None:
    values = [item.strip() for item in (first, second) if item and item.strip()]
    return "\n\n".join(values) or None


def _isolation_notice(lease: WorktreeLease) -> str:
    environment = lease.environment
    return (
        "Worktree isolation is active for this task. "
        f"Use only this workspace root for project-relative operations: {environment.root}. "
        f"The temporary branch is {environment.branch_ref}. "
        "Do not merge, synchronize, or modify another working directory; Worktree "
        "isolation separates files but is not an operating-system security sandbox."
    )
