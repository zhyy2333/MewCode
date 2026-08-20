from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import inspect
import os
from pathlib import Path

from mewcode.worktrees.paths import is_link_or_reparse

from .codec import decode_model, encode_json
from .models import (
    TeamCorruptionError,
    TeamMemberOutcome,
    TeamMemberOutcomeKind,
    TeamMemberProgress,
    TeamMemberStatus,
    TeamState,
    TeamValidationError,
    bounded_text,
    require_identifier,
    require_utc,
)
from .paths import TeamPaths
from .runtime import TeamMemberExecution, TeamMemberRuntimeFactory, _map_outcome


MEMBER_RUN_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class MemberRunDescriptor:
    schema_version: int
    team_id: str
    member_id: str
    run_id: str
    run_generation: int
    reason: str
    created_at: datetime

    def __post_init__(self) -> None:
        if self.schema_version != MEMBER_RUN_SCHEMA_VERSION:
            raise TeamValidationError("Unsupported member run descriptor version.")
        for name in ("team_id", "member_id", "run_id"):
            require_identifier(getattr(self, name), name)
        if self.run_generation < 1:
            raise TeamValidationError("Member run generation is invalid.")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise TeamValidationError("Member run reason is invalid.")
        object.__setattr__(self, "reason", bounded_text(self.reason, 1024) or "")
        object.__setattr__(self, "created_at", require_utc(self.created_at, "created_at"))


@dataclass(frozen=True)
class MemberRunResult:
    schema_version: int
    team_id: str
    member_id: str
    run_id: str
    run_generation: int
    outcome: TeamMemberOutcome
    completed_at: datetime

    def __post_init__(self) -> None:
        if self.schema_version != MEMBER_RUN_SCHEMA_VERSION:
            raise TeamValidationError("Unsupported member run result version.")
        for name in ("team_id", "member_id", "run_id"):
            require_identifier(getattr(self, name), name)
        if self.run_generation < 1:
            raise TeamValidationError("Member run generation is invalid.")
        object.__setattr__(self, "completed_at", require_utc(self.completed_at, "completed_at"))


class MemberRunDescriptorStore:
    """Strict, atomic files exchanged only between a pane host and its worker."""

    def __init__(self, paths: TeamPaths) -> None:
        self._paths = paths

    def write_descriptor(self, descriptor: MemberRunDescriptor) -> Path:
        path = self._paths.member_run_file(descriptor.member_id, descriptor.run_id)
        self._write(path, encode_json(descriptor))
        return path

    def read_descriptor(self, member_id: str, run_id: str) -> MemberRunDescriptor:
        return self._read(self._paths.member_run_file(member_id, run_id), MemberRunDescriptor)

    def write_result(self, result: MemberRunResult) -> Path:
        path = self._paths.member_run_result_file(result.member_id, result.run_id)
        self._write(path, encode_json(result))
        return path

    def read_result(self, member_id: str, run_id: str) -> MemberRunResult:
        return self._read(self._paths.member_run_result_file(member_id, run_id), MemberRunResult)

    def _write(self, path: Path, payload: bytes) -> None:
        self._validate_path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() or path.is_symlink():
            raise TeamCorruptionError("Member worker record already exists and was preserved.")
        temporary = path.with_suffix(path.suffix + ".tmp")
        try:
            with temporary.open("xb") as handle:
                try:
                    os.chmod(temporary, 0o600)
                except OSError:
                    pass
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError as exc:
                raise TeamCorruptionError(
                    "Member worker record already exists and was preserved."
                ) from exc
        finally:
            temporary.unlink(missing_ok=True)

    def _read(self, path: Path, model_type):
        self._validate_path(path)
        if is_link_or_reparse(path):
            raise TeamValidationError("Member worker record must not be a link or reparse point.")
        try:
            payload = path.read_bytes()
        except OSError as exc:
            raise TeamCorruptionError("Member worker record is unavailable.") from exc
        from .codec import decode_json
        return decode_model(model_type, decode_json(payload))

    def _validate_path(self, path: Path) -> None:
        candidate = Path(path)
        if not candidate.is_absolute() or candidate.parent != self._paths.members_root:
            raise TeamValidationError("Member worker record path is outside the team member directory.")
        self._paths.validate_containment()


ProgressSink = Callable[[TeamMemberProgress], Awaitable[None] | None]


class ManagedMemberWorker:
    """Runs exactly one pre-authorized descriptor; it never mutates team state."""

    def __init__(
        self,
        factory: TeamMemberRuntimeFactory,
        store: MemberRunDescriptorStore,
        state: TeamState,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._factory = factory
        self._store = store
        self._state = state
        self._now = now

    async def run(self, descriptor: MemberRunDescriptor, progress: ProgressSink | None = None) -> MemberRunResult:
        self._validate(descriptor)
        execution: TeamMemberExecution | None = None
        outcome: TeamMemberOutcome
        try:
            execution = await self._factory.assemble(self._state, descriptor.member_id, reason=descriptor.reason)
            async for event in execution.bundle.run.events():
                if progress is not None:
                    item = TeamMemberProgress("agent", getattr(event, "message", ""))
                    sent = progress(item)
                    if inspect.isawaitable(sent):
                        await sent
            agent_outcome = execution.bundle.run.outcome
            outcome = _map_outcome(agent_outcome.reason, agent_outcome.final_text, agent_outcome.error, False)
        except BaseException as exc:
            outcome = TeamMemberOutcome(
                TeamMemberOutcomeKind.INTERRUPTED
                if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt, GeneratorExit))
                else TeamMemberOutcomeKind.FAILED,
                error=f"Managed member worker failed: {type(exc).__name__}.",
            )
        finally:
            if execution is not None:
                await execution.close()
        result = MemberRunResult(
            MEMBER_RUN_SCHEMA_VERSION, descriptor.team_id, descriptor.member_id,
            descriptor.run_id, descriptor.run_generation, outcome, self._now(),
        )
        self._store.write_result(result)
        return result

    def _validate(self, descriptor: MemberRunDescriptor) -> None:
        if descriptor.team_id != self._state.manifest.team_id:
            raise TeamValidationError("Member worker descriptor belongs to another team.")
        try:
            member = self._state.members[descriptor.member_id]
        except KeyError as exc:
            raise TeamValidationError("Member worker identity is unknown.") from exc
        if (
            member.status is not TeamMemberStatus.RUNNING
            or member.active_run_id != descriptor.run_id
            or member.run_generation != descriptor.run_generation
        ):
            raise TeamValidationError("Member worker descriptor is stale or not running.")


async def run_member_worker_file(
    run_file: Path,
    *,
    runtime_factory: TeamMemberRuntimeFactory | None = None,
    state_loader: Callable[[str], TeamState] | None = None,
) -> int:
    """Hidden entry executes a validated run when supplied the shared 14A factory."""
    paths = _paths_for_run_file(run_file)
    name = run_file.name
    parts = name.split(".run.", 1)
    if len(parts) != 2 or not parts[1].endswith(".json"):
        raise TeamValidationError("Member run descriptor path is invalid.")
    member_id, run_id = parts[0], parts[1][:-5]
    store = MemberRunDescriptorStore(paths)
    descriptor = store.read_descriptor(member_id, run_id)
    if runtime_factory is not None:
        if state_loader is None:
            from .repository import TeamRepository
            from .paths import TeamNamePolicy
            state = TeamRepository(paths.user_root).load(TeamNamePolicy().parse(paths.team_root.name))
        else:
            state = state_loader(descriptor.team_id)
        if state.manifest.team_id != descriptor.team_id:
            raise TeamValidationError("Member worker descriptor belongs to another team.")
        await ManagedMemberWorker(runtime_factory, store, state).run(descriptor)
        return 0
    # This CLI boundary deliberately does not create a root session, Conversation,
    # or Lead lease. The command bootstrap must supply the shared factory.
    result = MemberRunResult(
        MEMBER_RUN_SCHEMA_VERSION, descriptor.team_id, descriptor.member_id,
        descriptor.run_id, descriptor.run_generation,
        TeamMemberOutcome(TeamMemberOutcomeKind.FAILED, error="Managed member worker runtime is unavailable."),
        datetime.now(timezone.utc),
    )
    store.write_result(result)
    return 1


def _paths_for_run_file(path: Path) -> TeamPaths:
    candidate = Path(path)
    if not candidate.is_absolute() or candidate.parent.name != "members" or ".run." not in candidate.name or not candidate.name.endswith(".json"):
        raise TeamValidationError("Member run descriptor path is invalid.")
    team_root = candidate.parent.parent
    if team_root.parent.name != "teams":
        raise TeamValidationError("Member run descriptor path is invalid.")
    from .paths import TeamNamePolicy
    return TeamPaths.for_user(team_root.parent.parent, TeamNamePolicy().parse(team_root.name))
