from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mewcode.agent import AgentMode, AgentRunConfig, AgentRunner, ToolScheduler
from mewcode.context import ContextArchive, ContextConfig, ContextManager
from mewcode.prompting import PromptAdditions, PromptBuilder, PromptEnvironmentProvider, PromptRunContext
from mewcode.subagents import SubagentPermissionController
from mewcode.tools import ToolRegistry, Workspace, WorkspaceToolBinder

from .inbound import MemberInboundSource
from .models import TeamActor, TeamActorKind
from .policy import build_member_tool_scope
from .runtime import TeamMemberRunBundle, TeamRuntimeBuildContext
from .tools import TeamMessageTool, TeamTaskTool


class TeamMemberRunAssembler:
    """Builds the exact 14A member run without a root Conversation or Lead lease."""

    def __init__(
        self,
        *,
        base_registry: ToolRegistry,
        provider_for_profile: Callable[[str], Any],
        profile_catalog: Any,
        approvals: Any,
        tasks: Any,
        mailbox: Any,
        fence_supplier: Callable[[], tuple[str, int]],
    ) -> None:
        self._base_registry = base_registry
        self._provider_for_profile = provider_for_profile
        self._profiles = profile_catalog
        self._approvals = approvals
        self._tasks = tasks
        self._mailbox = mailbox
        self._fence_supplier = fence_supplier

    async def build(self, context: TeamRuntimeBuildContext) -> TeamMemberRunBundle:
        actor = TeamActor(
            context.member.member_id, context.member.name, TeamActorKind.MEMBER,
            context.state.manifest.team_id, self._fence_supplier(),
        )
        permit = None
        if context.member.requires_approval:
            permit = lambda: self._approvals.side_effect_permit(
                actor, context.member.current_task_id or "no-current-task"
            )
        collaboration = ToolRegistry([
            TeamTaskTool(lambda: self._tasks, lambda: actor, permit=permit),
            TeamMessageTool(lambda: self._mailbox, lambda: self._approvals, lambda: actor, permit=permit),
        ])
        scope = build_member_tool_scope(
            self._base_registry, context.member.role, collaboration_registry=collaboration,
            approvals=self._approvals, actor=actor, task_id=lambda: context.member.current_task_id,
        )
        member_workspace = Workspace(context.worktree_lease.environment.root)
        ordinary = scope.registry.without(collaboration.names)
        bound = WorkspaceToolBinder().bind(
            ordinary, member_workspace,
            process_environment=context.worktree_lease.environment.process_environment,
        ).merge(collaboration)
        permissions = SubagentPermissionController.from_snapshot(
            member_workspace, context.member.role.permission_rules, context.member.role.permission_mode,
        )
        provider = self._provider_for_profile(context.member.role.profile_name)
        archive = ContextArchive(
            member_workspace.root,
            session_id_factory=lambda: f"{context.session.context_archive_id}-{context.member.run_generation}",
        )
        archive.start(skip_stale_cleanup=True)
        manager = ContextManager(
            provider, archive,
            ContextConfig(self._profiles.require(context.member.role.profile_name).context_window),
        )
        runner = AgentRunner(
            provider, ToolScheduler(permissions, policy=scope.policy),
            AgentRunConfig(max_iterations=context.member.role.max_turns, tool_denial_limit=3),
            prompt_builder=PromptBuilder(PromptEnvironmentProvider(member_workspace.root)),
            context_manager=manager, profile_name=context.member.role.profile_name,
            permission_mode_supplier=lambda: context.member.role.permission_mode,
            hook_component="team_member",
        )
        run = runner.start(
            context.history, context.resume_prompt, bound, AgentMode.DIRECT,
            PromptRunContext(context.resume_prompt, additions=PromptAdditions(agent_role=context.member.role.system_prompt)),
            history_commit_sink=context.session, inbound_source=MemberInboundSource(self._mailbox, actor),
        )

        async def close() -> None:
            manager.close()
            archive.close()

        return TeamMemberRunBundle(run, close)
