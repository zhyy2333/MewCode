from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import inspect
from pathlib import Path
from typing import Any
import uuid

from mewcode.agent import AgentInboundBatch, AgentRunView
from mewcode.prompting import PromptAdditions
from mewcode.tools import ToolRegistry

from .inbound import LeadInboundSource
from .leases import LEASE_HEARTBEAT_SECONDS, TeamLeaseService
from .models import (
    MailboxRegistration,
    MAX_TEAMS,
    SCHEMA_VERSION,
    TeamActor,
    TeamActorKind,
    TeamAttachment,
    TeamDiagnostic,
    TeamManifest,
    TeamMemberStatus,
    TeamName,
    TeamState,
    TeamValidationError,
)
from .paths import TeamNamePolicy
from .repository import TeamMutationRunner, TeamRepository
from .repository_binding import TeamRepositoryBindingService


@dataclass
class TeamCoordinatorServices:
    scheduler: Any = None
    mailbox: Any = None
    roster: Any = None
    tasks: Any = None
    approvals: Any = None


ServicesFactory = Callable[
    [TeamName, Callable[[], tuple[str, int]]],
    TeamCoordinatorServices | Awaitable[TeamCoordinatorServices],
]


class NullInboundSource:
    async def poll(self, committed_ids: frozenset[str]) -> AgentInboundBatch | None:
        del committed_ids
        return None

    async def acknowledge(self, batch: AgentInboundBatch) -> None:
        del batch


class TeamCoordinator:
    def __init__(
        self,
        repository: TeamRepository,
        leases: TeamLeaseService,
        bindings: TeamRepositoryBindingService,
        workspace: Path,
        *,
        process_id: str,
        services_factory: ServicesFactory | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        new_id: Callable[[], str] = lambda: uuid.uuid4().hex,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._repository = repository
        self._leases = leases
        self._bindings = bindings
        self._workspace = Path(workspace)
        self._process_id = process_id
        self._services_factory = services_factory
        self._now = now
        self._new_id = new_id
        self._sleep = sleep
        self._names = TeamNamePolicy()
        self._mutations = TeamMutationRunner(repository)
        self._attachment: TeamAttachment | None = None
        self._services: TeamCoordinatorServices | None = None
        self._background: asyncio.Task[None] | None = None
        self._diagnostics: list[TeamDiagnostic] = []
        self._closing = False
        self._lease_valid = False
        self._inbound_batches: dict[str, Any] = {}

    async def create(
        self,
        name: str,
        *,
        root_session_id: str,
        leader_name: str = "lead",
    ) -> TeamAttachment:
        self._ensure_detached()
        team_name = self._names.parse(name)
        lead_name = self._names.parse(leader_name)
        summaries = self._repository.list()
        if any(item.name.casefold() == team_name.canonical_key for item in summaries):
            raise TeamValidationError("Team name is already registered.")
        if len(summaries) >= MAX_TEAMS:
            raise TeamValidationError("Team storage limit has been reached.")
        team_id = self._new_id()
        binding = await self._bindings.create_binding(team_id, self._workspace)
        current = self._now()
        state = TeamState(
            SCHEMA_VERSION,
            0,
            TeamManifest(
                team_id,
                team_name,
                lead_name.value,
                binding,
                current,
                current,
            ),
            {},
            {
                lead_name.canonical_key: MailboxRegistration(
                    "lead",
                    lead_name,
                    "lead.jsonl",
                    True,
                )
            },
            {},
            {},
            (),
            (),
            current,
        )
        try:
            self._repository.create(state)
        except BaseException:
            cleanup = getattr(self._bindings, "remove_binding", None)
            if callable(cleanup):
                await cleanup(team_id, binding)
            raise
        return await self.attach(name, root_session_id=root_session_id)

    def list(self):
        return self._repository.list()

    async def attach(self, name: str, *, root_session_id: str) -> TeamAttachment:
        self._ensure_detached()
        team_name = self._names.parse(name)
        state = self._repository.load(team_name)
        await self._bindings.verify(state.manifest.repository, self._workspace)
        lease = await self._leases.acquire(
            team_name,
            root_session_id=root_session_id,
            process_id=self._process_id,
        )
        try:
            converged = self._converge_interrupted(state, lease.fence)
            self._attachment = TeamAttachment(converged, lease, root_session_id)
            self._lease_valid = True
            if self._services_factory is not None:
                created = self._services_factory(team_name, self.current_fence)
                self._services = await created if inspect.isawaitable(created) else created
                if self._services.roster is not None:
                    await self._services.roster.recover()
                if self._services.mailbox is not None:
                    await self._services.mailbox.flush_outbox()
                if self._services.scheduler is not None:
                    await self._services.scheduler.restore()
            self._background = asyncio.create_task(self._maintenance_loop())
            return self._attachment
        except BaseException:
            self._attachment = None
            self._lease_valid = False
            await self._leases.release(lease)
            raise

    async def relink(self, workspace: Path) -> TeamAttachment:
        attachment = self._require_attachment()
        binding = await self._bindings.relink(attachment, workspace)
        name = attachment.state.manifest.name

        def transform(state):
            manifest = replace(state.manifest, repository=binding, updated_at=self._now())
            return replace(state, manifest=manifest, updated_at=self._now())

        state = self._mutations.run(
            name,
            lease_fence=attachment.lease.fence,
            transform=transform,
        )
        self._workspace = Path(workspace)
        self._attachment = replace(attachment, state=state)
        return self._attachment

    async def detach(self) -> None:
        attachment = self._require_attachment()
        current = self._repository.load(attachment.state.manifest.name)
        blockers = [
            member.name.value
            for member in current.members.values()
            if member.status in {TeamMemberStatus.RUNNING, TeamMemberStatus.QUEUED}
        ]
        if self._services is not None and self._services.scheduler is not None:
            blockers.extend(getattr(self._services.scheduler, "active_member_ids", ()))
        blockers = sorted(set(blockers))
        if blockers:
            raise TeamValidationError(
                "Cannot detach while members are active or queued: " + ", ".join(blockers)
            )
        await self._shutdown_attachment(force=False)

    async def close(self) -> tuple[TeamDiagnostic, ...]:
        if self._closing:
            return tuple(self._diagnostics)
        self._closing = True
        if self._attachment is not None:
            await self._shutdown_attachment(force=True)
        return tuple(self._diagnostics)

    def active_attachment(self) -> TeamAttachment | None:
        return self._attachment if self._lease_valid else None

    @property
    def services(self) -> TeamCoordinatorServices | None:
        return self._services if self._lease_valid else None

    def current_fence(self) -> tuple[str, int]:
        return self._require_attachment().lease.fence

    def lead_actor(self) -> TeamActor:
        attachment = self._require_attachment()
        registration = next(
            item for item in attachment.state.registry.values() if item.is_lead
        )
        return TeamActor(
            registration.participant_id,
            registration.participant_name,
            TeamActorKind.LEAD,
            attachment.state.manifest.team_id,
            attachment.lease.fence,
        )

    def root_inbound_source(self):
        services = self.services
        if services is None or services.mailbox is None:
            return NullInboundSource()
        return LeadInboundSource(services.mailbox, self.lead_actor())

    async def poll(self, committed_ids: frozenset[str]) -> AgentInboundBatch | None:
        source = self.root_inbound_source()
        batch = await source.poll(committed_ids)
        if batch is not None:
            self._inbound_batches[batch.batch_id] = source
        return batch

    async def acknowledge(self, batch: AgentInboundBatch) -> None:
        source = self._inbound_batches.pop(batch.batch_id, self.root_inbound_source())
        await source.acknowledge(batch)

    def _converge_interrupted(
        self,
        state: TeamState,
        fence: tuple[str, int],
    ) -> TeamState:
        def transform(current):
            members = {
                member_id: (
                    replace(
                        member,
                        status=(
                            TeamMemberStatus.INTERRUPTED
                            if member.status is TeamMemberStatus.RUNNING
                            else TeamMemberStatus.FAILED
                        ),
                        active_run_id=None,
                        last_error="Recovered after Lead interruption.",
                        updated_at=self._now(),
                    )
                    if member.status in {
                        TeamMemberStatus.RUNNING,
                        TeamMemberStatus.PROVISIONING,
                    }
                    else member
                )
                for member_id, member in current.members.items()
            }
            return replace(current, members=members, updated_at=self._now())

        return self._mutations.run(
            state.manifest.name,
            lease_fence=fence,
            transform=transform,
        )

    async def _maintenance_loop(self) -> None:
        while self._attachment is not None and not self._closing:
            try:
                await self._sleep(LEASE_HEARTBEAT_SECONDS)
                attachment = self._require_attachment()
                renewed = await self._leases.renew(attachment.lease)
                self._attachment = replace(attachment, lease=renewed)
                if self._services is not None and self._services.mailbox is not None:
                    await self._services.mailbox.flush_outbox()
            except asyncio.CancelledError:
                return
            except Exception as exc:
                team_id = self._attachment.state.manifest.team_id if self._attachment else None
                self._diagnostics.append(
                    TeamDiagnostic(
                        "lease_lost",
                        f"Team maintenance stopped: {type(exc).__name__}.",
                        team_id,
                    )
                )
                self._lease_valid = False
                if self._services is not None and self._services.scheduler is not None:
                    await self._services.scheduler.close()
                return

    async def _shutdown_attachment(self, *, force: bool) -> None:
        del force
        attachment = self._attachment
        if attachment is None:
            return
        background = self._background
        self._background = None
        if background is not None and background is not asyncio.current_task():
            background.cancel()
            await asyncio.gather(background, return_exceptions=True)
        services = self._services
        if services is not None and services.scheduler is not None:
            await services.scheduler.close()
        if services is not None and services.mailbox is not None:
            try:
                await services.mailbox.flush_outbox()
            except Exception as exc:
                self._diagnostics.append(
                    TeamDiagnostic(
                        "outbox_flush_failed",
                        f"Final outbox flush failed: {type(exc).__name__}.",
                        attachment.state.manifest.team_id,
                    )
                )
        await self._leases.release(attachment.lease)
        self._lease_valid = False
        self._services = None
        self._attachment = None

    def _require_attachment(self) -> TeamAttachment:
        if self._attachment is None or not self._lease_valid:
            raise TeamValidationError("No valid team is attached to this root session.")
        return self._attachment

    def _ensure_detached(self) -> None:
        if self._attachment is not None:
            raise TeamValidationError("This root session already has an attached team.")


class TeamRunViewComposer:
    def __init__(
        self,
        coordinator: TeamCoordinator,
        lifecycle_tools: ToolRegistry,
        lead_tools: Callable[[], ToolRegistry],
    ) -> None:
        self._coordinator = coordinator
        self._lifecycle_tools = lifecycle_tools
        self._lead_tools = lead_tools

    def compose(self, base: AgentRunView) -> AgentRunView:
        tools = base.tools.without(self._lifecycle_tools.names).merge(self._lifecycle_tools)
        additions = base.additions
        attachment = self._coordinator.active_attachment()
        if attachment is not None:
            lead_tools = self._lead_tools()
            tools = tools.without(lead_tools.names).merge(lead_tools)
            lead_prompt = (
                f"You are Team Lead for persistent team {attachment.state.manifest.name.value}. "
                "Decompose work into shared tasks, delegate implementation, and make final decisions."
            )
            additions = (additions or PromptAdditions()).merged(agent_role=lead_prompt)
        return AgentRunView(tools, additions)
