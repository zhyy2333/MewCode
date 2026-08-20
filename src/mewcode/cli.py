from __future__ import annotations

import argparse
import asyncio
import inspect
import os
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

from .agent import AgentCapacityPool, AgentMode, AgentRunConfig, AgentRunner, ToolScheduler
from .commands import (
    CommandRegistrationError,
    InteractionState,
    create_builtin_command_registry,
)
from .config import (
    ProfileCatalog,
    ProfileEntry,
    load_active_profile,
    load_profile_catalog,
)
from .context import ContextArchive, ContextConfig, ContextError, ContextManager
from .conversation import Conversation
from .continuity import (
    ContinuityPaths,
    InstructionLoader,
    MemoryError,
    MemoryManager,
    MemoryStore,
    MemoryUpdater,
    SessionBinding,
    SessionError,
    SessionOpenMode,
    SessionOpenRequest,
    SessionRepository,
)
from .continuity.session_codec import session_title
from .continuity.sanitization import MemoryTurnSanitizer
from .mcp import McpConfigLoader, McpConfigPaths, McpDiagnostic, McpError, McpRuntime
from .permissions import (
    PermissionConfigError,
    PermissionConfigLoader,
    PermissionConfigWriter,
    PermissionController,
    PermissionMode,
    PermissionPaths,
    PermissionRuleStore,
    PermissionTargetBuilder,
)
from .prompting import PromptAdditions, PromptBuilder, PromptEnvironmentProvider, PromptRunContext
from .providers import (
    ConfigError,
    ProviderError,
    RequestBoundaryProvider,
    UsageLedger,
    UsageTrackingProvider,
    create_provider,
)
from .repl import Repl
from .terminal import PromptToolkitTerminal
from .tools import ToolRegistry, ToolSafety, Workspace, WorkspaceToolBinder, create_builtin_registry
from .hooks import (
    HookActionExecutor,
    HookConfigError,
    HookConfigLoader,
    HookDiagnosticLogger,
    HookPaths,
    HookRuntime,
    HookedProvider,
    WorkspaceTrustStore,
)
from .skills import (
    LoadSkillTool,
    SkillCatalogError,
    SkillDefinitionError,
    SkillRefreshResult,
    SkillRoots,
    SkillRuntime,
    SkillCoordinator,
    build_skill_catalog,
    discover_sources,
)
from .commands import DynamicCommandCatalog, create_skill_command_definition
from .subagents import (
    AgentCatalogError,
    AgentDefinitionError,
    AgentDefinitionRoots,
    AgentTool,
    SubagentCoordinator,
    SubagentNotificationQueue,
    SubagentRuntimeFactory,
    SubagentTaskManager,
    WorkspaceRuntimeBundleFactory,
    SubagentPermissionController,
    build_agent_catalog,
    discover_agent_sources,
)
from .teams import (
    FrozenRoleFactory,
    MemberBackendResolver,
    MemberControlBroker,
    MemberSessionStore,
    TeamApprovalService,
    TeamCoordinator,
    TeamCoordinatorServices,
    TeamLifecycleTool,
    TeamMailboxService,
    TeamMemberRunAssembler,
    TeamMemberRuntimeFactory,
    TeamMemberRuntimeRouter,
    TeamMemberScheduler,
    TeamMemberTool,
    TeamMessageTool,
    TeamProtocolRouter,
    TeamRepository,
    TeamRepositoryBindingService,
    TeamRosterService,
    TeamRunViewComposer,
    TeamTaskService,
    TeamTaskTool,
    TeamLeaseService,
    TerminalHostProvisioner,
    TerminalMemberRuntimeFactory,
    TmuxPaneAdapter,
    WindowsTerminalPaneAdapter,
    run_member_worker_file,
    run_pane_host,
    run_process,
)
from .teams.models import TeamMemberBackend, TeamValidationError
from .teams.repository import TeamMutationRunner
from .teams.codec import decode_lead_lease
from .teams.paths import TeamNamePolicy, TeamPaths
from .teams.member_worker import MemberRunDescriptorStore
from .worktrees import (
    WorktreeConfigLoader,
    WorktreeJanitor,
    WorktreeLifecycleService,
)

_ORIGINAL_LOAD_ACTIVE_PROFILE = load_active_profile


def _load_profiles() -> ProfileCatalog:
    if load_active_profile is _ORIGINAL_LOAD_ACTIVE_PROFILE:
        return load_profile_catalog()
    profile = load_active_profile()
    return ProfileCatalog(
        profile.name,
        MappingProxyType({profile.name: ProfileEntry(profile, "")}),
        UsageLedger(),
        _provider_factory=create_provider,
    )


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mewcode")
    parser.add_argument(
        "--permission-mode",
        choices=[mode.value for mode in PermissionMode],
        default=PermissionMode.DEFAULT.value,
        help="permission safety ceiling (default: default)",
    )
    sessions = parser.add_mutually_exclusive_group()
    sessions.add_argument(
        "--new",
        action="store_true",
        help="start a new session instead of restoring the most recent one",
    )
    sessions.add_argument(
        "--resume",
        metavar="ID",
        help="resume a specific session ID",
    )
    hidden = parser.add_mutually_exclusive_group()
    hidden.add_argument("--team-pane-host", action="store_true", help=argparse.SUPPRESS)
    hidden.add_argument("--team-member-worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--control-file", help=argparse.SUPPRESS)
    parser.add_argument("--run-file", help=argparse.SUPPRESS)
    return parser


def _load_agent_catalog(
    workspace: Workspace,
    profiles: ProfileCatalog,
    base_registry: ToolRegistry,
    *,
    plugin_roots: Sequence[Path] = (),
):
    roots = AgentDefinitionRoots.defaults(workspace.root, plugin_roots)
    return build_agent_catalog(
        discover_agent_sources(roots),
        profile_names=profiles,
        base_tool_names=base_registry.names,
        globally_forbidden_names={"agent", "load_skill"},
    )


def _optional_keyword(factory, name: str, value: object) -> dict[str, object]:
    try:
        parameters = inspect.signature(factory).parameters
    except (TypeError, ValueError):
        return {}
    return {name: value} if name in parameters else {}


async def _run_hidden_member_worker(run_file: Path) -> int:
    candidate = Path(run_file)
    if (
        not candidate.is_absolute()
        or candidate.parent.name != "members"
        or ".run." not in candidate.name
        or not candidate.name.endswith(".json")
    ):
        raise TeamValidationError("Member run descriptor path is invalid.")
    team_root = candidate.parent.parent
    if team_root.parent.name != "teams":
        raise TeamValidationError("Member run descriptor path is invalid.")
    paths = TeamPaths.for_user(
        team_root.parent.parent,
        TeamNamePolicy().parse(team_root.name),
    )
    repository = TeamRepository(paths.user_root)
    team_name = TeamNamePolicy().parse(paths.team_root.name)
    state = repository.load(team_name)
    lease = decode_lead_lease(paths.lease_file.read_bytes())
    if lease.team_id != state.manifest.team_id:
        raise TeamValidationError("Member worker Lead lease belongs to another team.")
    fence = lambda: (lease.lease_id, lease.generation)
    profiles = _load_profiles()
    workspace = Workspace(state.manifest.repository.workspace_root)
    run_parts = candidate.name.split(".run.", 1)
    if len(run_parts) != 2 or not run_parts[1].endswith(".json"):
        raise TeamValidationError("Member run descriptor path is invalid.")
    descriptor = MemberRunDescriptorStore(paths).read_descriptor(
        run_parts[0], run_parts[1][:-5]
    )
    worktree_config = WorktreeConfigLoader().load(
        workspace.root / ".mewcode" / "worktrees.yaml"
    )
    worktrees = WorktreeLifecycleService(workspace.root, worktree_config)
    approvals = TeamApprovalService(repository, team_name)
    tasks = TeamTaskService(repository, team_name)
    mailbox = TeamMailboxService(
        repository,
        team_name,
        TeamProtocolRouter(repository, team_name),
        lease_fence=fence,
    )
    sessions = MemberSessionStore(paths)
    hook_catalog = HookConfigLoader().load(HookPaths.for_workspace(workspace.root))
    trust_store = WorkspaceTrustStore.for_user_home()
    project_trusted = (
        trust_store.read(workspace.root)
        if hook_catalog.requires_project_trust
        else False
    )
    if hook_catalog.rules:
        hook_runtime = HookRuntime(
            hook_catalog,
            HookActionExecutor(
                workspace.root,
                api_key_environment_names=tuple(profiles.api_key_environment_names),
            ),
            workspace=workspace.root,
            session_id=f"team-worker-{descriptor.run_id}",
            resumed=True,
            project_trusted=project_trusted,
            diagnostics=HookDiagnosticLogger(
                Path.home() / ".mewcode" / "logs" / "hooks.jsonl",
                sensitive_values=tuple(
                    entry.profile.api_key for entry in profiles.entries.values()
                ),
            ),
        )
    else:
        hook_runtime = HookRuntime.empty(
            workspace.root,
            f"team-worker-{descriptor.run_id}",
            resumed=True,
        )
    wrapped_providers: dict[str, object] = {}

    def worker_provider(name: str):
        wrapped = wrapped_providers.get(name)
        if wrapped is None:
            wrapped = HookedProvider(
                RequestBoundaryProvider(profiles.provider(name)),
                hook_runtime,
                name,
            )
            wrapped_providers[name] = wrapped
        return wrapped

    builtin_registry = create_builtin_registry(workspace)
    static_commands = create_builtin_command_registry()
    command_identifiers = {
        identifier
        for definition in static_commands.definitions()
        for identifier in (definition.name, *definition.aliases)
    }
    skill_sources = discover_sources(SkillRoots.defaults(workspace.root))
    pre_catalog = build_skill_catalog(
        skill_sources,
        system_command_identifiers=command_identifiers,
        profiles=profiles,
    )
    config_result = McpConfigLoader().load(McpConfigPaths.for_workspace(workspace))
    mcp_runtime: McpRuntime | None = None
    mcp_tools = ()
    if config_result.servers:
        mcp_runtime = McpRuntime(workspace.root)
        mcp_tools = mcp_runtime.start(
            config_result.servers,
            {
                *builtin_registry.names,
                "load_skill",
                "agent",
                *(
                    tool.public_name
                    for definition in pre_catalog.definitions.values()
                    for tool in definition.package_tools
                ),
            },
        ).tools
    base_registry = builtin_registry.merge(ToolRegistry(mcp_tools))
    assembler = TeamMemberRunAssembler(
        base_registry=base_registry,
        provider_for_profile=worker_provider,
        profile_catalog=profiles,
        approvals=approvals,
        tasks=tasks,
        mailbox=mailbox,
        fence_supplier=fence,
    )
    factory = TeamMemberRuntimeFactory(worktrees, sessions, assembler.build)
    try:
        return await run_member_worker_file(
            candidate,
            runtime_factory=factory,
            state_loader=lambda _team_id: repository.load(team_name),
        )
    finally:
        await hook_runtime.close()
        if mcp_runtime is not None:
            mcp_runtime.close()


def main(argv: list[str] | None = None) -> int:
    parser = _argument_parser()
    arguments = parser.parse_args(argv)
    if arguments.team_pane_host:
        if not arguments.control_file or arguments.run_file:
            parser.error("--team-pane-host requires --control-file only")
        return asyncio.run(run_pane_host(Path(arguments.control_file)))
    if arguments.team_member_worker:
        if not arguments.run_file or arguments.control_file:
            parser.error("--team-member-worker requires --run-file only")
        return asyncio.run(_run_hidden_member_worker(Path(arguments.run_file)))
    if arguments.control_file or arguments.run_file:
        parser.error("hidden team file arguments require a matching hidden mode")
    mcp_runtime: McpRuntime | None = None
    context_archive: ContextArchive | None = None
    session_binding: SessionBinding | None = None
    memory_manager: MemoryManager | None = None
    hook_runtime: HookRuntime | None = None
    task_manager: SubagentTaskManager | None = None
    worktree_janitor: WorktreeJanitor | None = None
    team_coordinator: TeamCoordinator | None = None
    capacity_pool: AgentCapacityPool | None = None
    try:
        static_command_registry = create_builtin_command_registry()
        command_registry = DynamicCommandCatalog(static_command_registry)
        interaction_state = InteractionState()
        workspace = Workspace(Path.cwd())
        capacity_pool = AgentCapacityPool()
        worktree_config = WorktreeConfigLoader().load(
            workspace.root / ".mewcode" / "worktrees.yaml"
        )
        worktree_lifecycle = WorktreeLifecycleService(
            workspace.root,
            worktree_config,
        )
        worktree_janitor = WorktreeJanitor(worktree_lifecycle)
        hook_catalog = HookConfigLoader().load(
            HookPaths.for_workspace(workspace.root)
        )
        profile_catalog = _load_profiles()
        profile = profile_catalog.active_profile
        usage_ledger = profile_catalog.usage_ledger
        provider = profile_catalog.provider()
        skill_roots = SkillRoots.defaults(workspace.root)
        skill_sources = discover_sources(skill_roots)
        command_identifiers = {
            identifier
            for definition in static_command_registry.definitions()
            for identifier in (definition.name, *definition.aliases)
        }
        pre_catalog = build_skill_catalog(
            skill_sources,
            system_command_identifiers=command_identifiers,
            profiles=profile_catalog,
        )
        continuity_paths = ContinuityPaths.for_workspace(workspace.root)
        instructions = InstructionLoader().load(continuity_paths)
        session_repository = SessionRepository(continuity_paths)
        maintenance_diagnostics = session_repository.maintain()
        session_request = (
            SessionOpenRequest(SessionOpenMode.NEW)
            if arguments.new
            else SessionOpenRequest(SessionOpenMode.RESUME, arguments.resume)
            if arguments.resume
            else SessionOpenRequest()
        )
        opened_session = session_repository.open(session_request)
        session_binding = opened_session.binding
        hook_trust_store = WorkspaceTrustStore.for_user_home()
        project_trusted = (
            hook_trust_store.read(workspace.root)
            if hook_catalog.requires_project_trust
            else False
        )
        if hook_catalog.rules:
            hook_runtime = HookRuntime(
                hook_catalog,
                HookActionExecutor(
                    workspace.root,
                    api_key_environment_names=tuple(
                        profile_catalog.api_key_environment_names
                    ),
                ),
                workspace=workspace.root,
                session_id=opened_session.state.session_id,
                resumed=opened_session.resumed,
                project_trusted=project_trusted,
                diagnostics=HookDiagnosticLogger(
                    Path.home() / ".mewcode" / "logs" / "hooks.jsonl",
                    sensitive_values=tuple(
                        entry.profile.api_key
                        for entry in profile_catalog.entries.values()
                    ),
                ),
            )
        else:
            hook_runtime = HookRuntime.empty(
                workspace.root,
                opened_session.state.session_id,
                resumed=opened_session.resumed,
            )
        hooked_providers: dict[str, object] = {}

        def hooked_provider(name: str | None = None):
            selected = name or profile_catalog.active_name
            wrapped = hooked_providers.get(selected)
            if wrapped is None:
                wrapped = HookedProvider(
                    RequestBoundaryProvider(profile_catalog.provider(selected)),
                    hook_runtime,
                    selected,
                )
                hooked_providers[selected] = wrapped
            return wrapped

        provider = hooked_provider()
        memory_manager = MemoryManager(
            MemoryStore(continuity_paths, api_key=profile.api_key),
            MemoryUpdater(
                provider,
                sanitizer=MemoryTurnSanitizer(api_key=profile.api_key),
            ),
        )
        context_archive = ContextArchive(workspace.root)
        _write_context_diagnostics(context_archive.start())
        context_manager = ContextManager(
            provider,
            context_archive,
            ContextConfig(profile.context_window),
            hook_runtime=hook_runtime,
        )

        builtin_registry = create_builtin_registry(workspace)
        builtin_tools = builtin_registry.list()
        config_result = McpConfigLoader().load(
            McpConfigPaths.for_workspace(workspace)
        )
        _write_mcp_diagnostics(config_result.diagnostics)
        mcp_tools = ()
        if config_result.servers:
            mcp_runtime = McpRuntime(workspace.root)
            runtime_result = mcp_runtime.start(
                config_result.servers,
                {
                    *(tool.name for tool in builtin_tools),
                    "load_skill",
                    "agent",
                    *(
                        tool.public_name
                        for definition in pre_catalog.definitions.values()
                        for tool in definition.package_tools
                    ),
                },
            )
            mcp_tools = runtime_result.tools
            _write_mcp_diagnostics(runtime_result.diagnostics)
        base_registry = ToolRegistry([*builtin_tools, *mcp_tools])
        agent_catalog = _load_agent_catalog(
            workspace,
            profile_catalog,
            base_registry,
        )
        mcp_statuses = {
            status.server_name: (
                status.state.value
                if status.message is None
                else f"{status.state.value}: {status.message}"
            )
            for status in (runtime_result.statuses if config_result.servers else ())
        }
        catalog = build_skill_catalog(
            skill_sources,
            system_command_identifiers=command_identifiers,
            profiles=profile_catalog,
            global_tool_names={*base_registry.names, "load_skill", "agent"},
            mcp_status=mcp_statuses,
        )
        known_tools = {
            *base_registry.names,
            *(
                tool.public_name
                for definition in catalog.definitions.values()
                for tool in definition.package_tools
            ),
        }
        permission_paths = PermissionPaths.for_workspace(workspace)
        rule_sets = PermissionConfigLoader().load(
            permission_paths,
            known_tools,
            config_result.permission_prefixes,
        )
        writer = PermissionConfigWriter(
            permission_paths.project_local,
            known_tools,
            deferred_tool_prefixes=config_result.permission_prefixes,
        )
        rule_store = PermissionRuleStore(rule_sets, writer)
        permission_controller = PermissionController(
            PermissionTargetBuilder(workspace),
            rule_store,
            PermissionMode(arguments.permission_mode),
        )

        scheduler = ToolScheduler(
            permission_controller,
            **_optional_keyword(ToolScheduler, "hook_runtime", hook_runtime),
        )
        prompt_builder = PromptBuilder(PromptEnvironmentProvider(workspace.root))
        agent_runner = AgentRunner(
            provider,
            scheduler,
            prompt_builder=prompt_builder,
            context_manager=context_manager,
            **_optional_keyword(
                AgentRunner, "profile_name", profile_catalog.active_name
            ),
            **_optional_keyword(
                AgentRunner,
                "permission_mode_supplier",
                lambda: permission_controller.mode,
            ),
            **_optional_keyword(AgentRunner, "hook_runtime", hook_runtime),
        )
        skill_runtime = SkillRuntime(
            catalog,
            workspace.root,
            base_registry,
            binding=opened_session.binding,
            api_key_environment_names=profile_catalog.api_key_environment_names,
        )
        restore_diagnostics = skill_runtime.restore(
            getattr(opened_session.state, "active_skills", ())
        )
        conversation_ref: dict[str, Conversation] = {}

        def isolated_runner(profile_name: str | None) -> AgentRunner:
            selected = profile_catalog.require(profile_name or profile_catalog.active_name)
            isolated_context = ContextManager(
                hooked_provider(profile_name),
                context_archive,
                ContextConfig(selected.context_window),
                hook_runtime=hook_runtime,
            )
            return AgentRunner(
                hooked_provider(profile_name),
                scheduler,
                prompt_builder=prompt_builder,
                context_manager=isolated_context,
                **_optional_keyword(AgentRunner, "profile_name", selected.name),
                **_optional_keyword(
                    AgentRunner,
                    "permission_mode_supplier",
                    lambda: permission_controller.mode,
                ),
                **_optional_keyword(AgentRunner, "hook_runtime", hook_runtime),
            )

        coordinator = SkillCoordinator(
            skill_runtime,
            runner_factory=isolated_runner,
            history_supplier=lambda: conversation_ref["value"].messages(),
            base_additions_supplier=lambda: conversation_ref["value"].skill_base_additions(),
            allowed_safety_supplier=lambda: conversation_ref["value"].current_skill_safety(),
        )
        load_skill = LoadSkillTool(coordinator)
        subagent_runtime_factory = SubagentRuntimeFactory(
            provider_supplier=lambda name: hooked_provider(name),
            prompt_builder=prompt_builder,
            workspace=workspace,
            hook_runtime=hook_runtime,
            context_config_factory=lambda name: ContextConfig(
                profile_catalog.require(name).context_window
            ),
        )
        workspace_runtime_factory = WorkspaceRuntimeBundleFactory(
            subagent_runtime_factory,
            project_trusted=project_trusted,
            api_key_environment_names=profile_catalog.api_key_environment_names,
            hook_once_state=hook_runtime.once_state,
            hook_process_state=hook_runtime.process_state,
            frozen_user_mcp=config_result.user_servers,
            frozen_user_hooks=tuple(
                rule
                for rule in hook_catalog.rules
                if rule.key.source.value == "user"
            ),
        )
        notifications = SubagentNotificationQueue()
        task_manager = SubagentTaskManager(notifications, capacity_pool=capacity_pool)
        subagent_coordinator = SubagentCoordinator(
            agent_catalog,
            subagent_runtime_factory,
            base_registry,
            rule_store,
            background_capable_names=base_registry.names,
            additions_supplier=lambda: conversation_ref["value"].skill_base_additions(),
            worktree_additions_supplier=lambda: conversation_ref["value"].subagent_user_additions(),
            worktree_lifecycle=worktree_lifecycle,
            workspace_runtime_factory=workspace_runtime_factory,
        )
        agent_tool = AgentTool(subagent_coordinator, task_manager)
        registry_without_team = base_registry.merge(ToolRegistry([load_skill, agent_tool]))

        team_repository = TeamRepository(Path.home() / ".mewcode")
        team_leases = TeamLeaseService(team_repository)
        team_bindings = TeamRepositoryBindingService()
        role_factory = FrozenRoleFactory(
            agent_catalog,
            profile_names=profile_catalog.entries,
            permission_rules=rule_store.snapshot(),
        )

        async def create_team_services(team_name, fence_supplier):
            broker = team_coordinator.control_broker
            if broker is None:
                raise TeamValidationError("Team member control broker is unavailable.")
            approvals = TeamApprovalService(team_repository, team_name)
            tasks = TeamTaskService(team_repository, team_name)
            router = TeamProtocolRouter(team_repository, team_name)
            mailbox = TeamMailboxService(
                team_repository,
                team_name,
                router,
                lease_fence=fence_supplier,
            )
            sessions = MemberSessionStore(team_repository.paths(team_name))

            member_run_assembler = TeamMemberRunAssembler(
                base_registry=base_registry,
                provider_for_profile=hooked_provider,
                profile_catalog=profile_catalog,
                approvals=approvals,
                tasks=tasks,
                mailbox=mailbox,
                fence_supplier=fence_supplier,
            )
            member_runtime_factory = TeamMemberRuntimeFactory(
                worktree_lifecycle,
                sessions,
                member_run_assembler.build,
            )
            backend_resolver = MemberBackendResolver()
            adapters = {
                TeamMemberBackend.WINDOWS_TERMINAL: WindowsTerminalPaneAdapter(
                    backend_resolver, run_process
                ),
                TeamMemberBackend.TMUX: TmuxPaneAdapter(backend_resolver, run_process),
            }
            terminal_hosts = TerminalHostProvisioner(broker, adapters)

            async def ensure_terminal_connection(member):
                existing = broker.connection(member.member_id)
                if existing is not None:
                    return existing
                binding = await terminal_hosts.provision(
                    team_repository.load(team_name).manifest.team_id,
                    member,
                )
                try:
                    def publish(current):
                        latest = current.members.get(member.member_id)
                        if (
                            latest is None
                            or latest.active_run_id != member.active_run_id
                            or latest.run_generation != member.run_generation
                        ):
                            raise TeamValidationError("Terminal member changed during pane recovery.")
                        members = dict(current.members)
                        members[member.member_id] = replace(latest, pane_binding=binding)
                        return replace(current, members=members)

                    TeamMutationRunner(team_repository).run(
                        team_name,
                        lease_fence=fence_supplier(),
                        transform=publish,
                    )
                except BaseException:
                    await terminal_hosts.terminate(binding)
                    raise
                connection = broker.connection(member.member_id)
                if connection is None:
                    raise TeamValidationError("Terminal pane host disappeared after registration.")
                return connection

            terminal_runtime_factory = TerminalMemberRuntimeFactory(
                broker,
                ensure_connection=ensure_terminal_connection,
            )
            runtime_router = TeamMemberRuntimeRouter(
                member_runtime_factory,
                terminal_runtime_factory,
            )
            member_scheduler = TeamMemberScheduler(
                team_repository,
                team_name,
                capacity_pool,
                runtime_router,
                lease_fence=fence_supplier,
            )
            mailbox.set_wake_sink(member_scheduler)
            roster = TeamRosterService(
                team_repository,
                team_name,
                role_factory,
                worktree_lifecycle,
                sessions,
                current_profile_name=lambda: profile_catalog.active_name,
                stop_sink=member_scheduler.stop,
                wake_sink=member_scheduler,
                backend_resolver=backend_resolver,
                terminal_hosts=terminal_hosts,
            )
            return TeamCoordinatorServices(
                scheduler=member_scheduler,
                mailbox=mailbox,
                roster=roster,
                tasks=tasks,
                approvals=approvals,
            )

        team_coordinator = TeamCoordinator(
            team_repository,
            team_leases,
            team_bindings,
            workspace.root,
            process_id=str(os.getpid()),
            services_factory=create_team_services,
            control_broker_factory=lambda name: MemberControlBroker(
                paths=team_repository.paths(name)
            ),
        )
        team_lifecycle_tool = TeamLifecycleTool(
            team_coordinator,
            root_session_id=lambda: opened_session.state.session_id,
        )

        def lead_tools():
            services = team_coordinator.services
            if services is None:
                return ToolRegistry([])
            return ToolRegistry(
                [
                    TeamMemberTool(team_coordinator),
                    TeamTaskTool(lambda: services.tasks, team_coordinator.lead_actor),
                    TeamMessageTool(
                        lambda: services.mailbox,
                        lambda: services.approvals,
                        team_coordinator.lead_actor,
                    ),
                ]
            )

        team_view = TeamRunViewComposer(
            team_coordinator,
            ToolRegistry([team_lifecycle_tool]),
            lead_tools,
        )
        registry = registry_without_team.merge(ToolRegistry([team_lifecycle_tool]))
        skill_runtime.set_global_tools(registry)
        command_registry.replace(
            create_skill_command_definition(item.name, item.description)
            for item in catalog.definitions.values()
        )

        def refresh_skills() -> SkillRefreshResult:
            try:
                sources = discover_sources(skill_roots)
                fingerprint = tuple(
                    sorted(
                        (item.fingerprint for item in sources),
                        key=lambda item: (item.root, item.files),
                    )
                )
                result = skill_runtime.refresh(
                    fingerprint,
                    lambda: build_skill_catalog(
                        sources,
                        system_command_identifiers=command_identifiers,
                        profiles=profile_catalog,
                        global_tool_names=set(registry.names),
                        mcp_status=mcp_statuses,
                    ),
                )
                if result.accepted and result.changed:
                    command_registry.replace(
                        create_skill_command_definition(item.name, item.description)
                        for item in skill_runtime.catalog.definitions.values()
                    )
                return result
            except Exception as exc:
                from .skills import SkillDiagnostic

                return SkillRefreshResult(
                    True,
                    False,
                    (SkillDiagnostic("refresh", f"Skill update was rejected: {exc}"),),
                )

        conversation = Conversation(
            agent_runner,
            registry,
            context_manager=context_manager,
            initial_state=opened_session.state,
            session=opened_session.binding,
            instructions=instructions,
            memory=memory_manager,
            resumed=opened_session.resumed,
            skill_runtime=skill_runtime,
            skill_coordinator=coordinator,
            skill_refresher=refresh_skills,
            hook_runtime=hook_runtime,
            task_manager=task_manager,
            worktree_lifecycle=worktree_lifecycle,
            worktree_janitor=worktree_janitor,
            team_run_view_composer=team_view,
            team_inbound_source=team_coordinator,
            team_coordinator=team_coordinator,
        )
        conversation_ref["value"] = conversation
        action = "resumed" if opened_session.resumed else "created"
        title = session_title(
            opened_session.state.messages,
            opened_session.state.session_id if opened_session.resumed else "New session",
        )
        startup_messages = [
            "instructions: loaded" if instructions.content else "instructions: none",
            f"session: {action} {opened_session.state.session_id} - {title}",
            f"memory: loaded {len(memory_manager.prompt_view().included_note_ids)} note(s)",
        ]
        startup_messages.extend(
            f"{diagnostic.component.value}: {diagnostic.message}"
            for diagnostic in (
                *instructions.diagnostics,
                *maintenance_diagnostics,
                *opened_session.diagnostics,
            )
            if diagnostic.code not in {"created", "resumed"}
        )
        startup_messages.extend(
            f"skills: {diagnostic.message}"
            for diagnostic in (*catalog.diagnostics, *restore_diagnostics)
        )
        startup_messages.extend(
            f"agents: {diagnostic.message}"
            for diagnostic in agent_catalog.diagnostics
        )
        terminal = PromptToolkitTerminal(command_registry, interaction_state)
        return Repl(
            conversation,
            permission_controller=permission_controller,
            startup_messages=tuple(startup_messages),
            registry=command_registry,
            state=interaction_state,
            terminal=terminal,
            usage_ledger=usage_ledger,
            memory_manager=memory_manager,
            context_manager=context_manager,
            hook_runtime=hook_runtime,
            hook_trust_store=hook_trust_store,
            workspace=workspace.root,
        ).run()
    except CommandRegistrationError as exc:
        sys.stderr.write(f"Error: {exc}\n")
        return 1
    except (SkillCatalogError, SkillDefinitionError, AgentCatalogError, AgentDefinitionError) as exc:
        sys.stderr.write(f"Error: {exc}\n")
        return 1
    except PermissionConfigError as exc:
        sys.stderr.write(f"Error: {exc}\n")
        return 1
    except HookConfigError as exc:
        sys.stderr.write(f"Error: {exc}\n")
        return 1
    except (ConfigError, ProviderError) as exc:
        sys.stderr.write(f"Error: {exc.message}\n")
        return 1
    except ContextError as exc:
        sys.stderr.write(f"Error: {exc}\n")
        return 1
    except (SessionError, MemoryError) as exc:
        sys.stderr.write(f"Error: {exc}\n")
        return 1
    except McpError as exc:
        sys.stderr.write(
            f"Error: MCP server '{exc.server_name}' {exc.phase.value} failed: "
            f"{exc.safe_message}\n"
        )
        return 1
    except KeyboardInterrupt:
        sys.stderr.write("\n")
        return 130
    finally:
        if team_coordinator is not None:
            try:
                asyncio.run(team_coordinator.close())
            except Exception:
                sys.stderr.write("Warning: team coordinator shutdown failed.\n")
        if memory_manager is not None:
            try:
                for diagnostic in asyncio.run(memory_manager.close()):
                    sys.stderr.write(f"Warning: {diagnostic.message}\n")
            except Exception:
                sys.stderr.write("Warning: automatic memory shutdown failed.\n")
        if task_manager is not None:
            try:
                asyncio.run(task_manager.close())
            except Exception:
                sys.stderr.write("Warning: subagent task shutdown failed.\n")
        if capacity_pool is not None:
            try:
                asyncio.run(capacity_pool.close())
            except Exception:
                sys.stderr.write("Warning: agent capacity shutdown failed.\n")
        if worktree_janitor is not None:
            try:
                asyncio.run(worktree_janitor.close())
            except Exception:
                sys.stderr.write("Warning: Worktree cleanup shutdown failed.\n")
        if session_binding is not None:
            session_binding.close()
        if context_archive is not None:
            _write_context_diagnostics(context_archive.close())
        if mcp_runtime is not None:
            try:
                _write_mcp_diagnostics(mcp_runtime.close())
            except Exception:
                sys.stderr.write("Warning: MCP runtime shutdown failed.\n")
        if hook_runtime is not None:
            try:
                asyncio.run(hook_runtime.close())
            except Exception:
                sys.stderr.write("Warning: Hook runtime shutdown failed.\n")


def _write_mcp_diagnostics(diagnostics: tuple[McpDiagnostic, ...]) -> None:
    for diagnostic in diagnostics:
        server = diagnostic.server_name or "configuration"
        sys.stderr.write(
            f"Warning: MCP server '{server}' {diagnostic.phase.value} failed: "
            f"{diagnostic.message}\n"
        )


def _write_context_diagnostics(diagnostics) -> None:
    for diagnostic in diagnostics:
        sys.stderr.write(f"Warning: {diagnostic.message}\n")
