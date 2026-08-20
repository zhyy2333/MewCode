from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import tempfile
from typing import Mapping

from mewcode.locking import FileLock

from .codec import (
    decode_json,
    decode_lead_lease,
    decode_team_state,
    encode_json,
    encode_team_state,
)
from .models import (
    MAX_TEAMS,
    TeamConflictError,
    TeamCorruptionError,
    TeamLeaseError,
    TeamName,
    TeamState,
    TeamSummary,
    TeamValidationError,
)
from .paths import TeamNamePolicy, TeamPaths


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    except BaseException:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


class TeamRepository:
    def __init__(
        self,
        user_root: Path,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        root = Path(user_root)
        if not root.is_absolute():
            raise TeamValidationError("User data root must be absolute.")
        self._user_root = root
        self._now = now
        self._names = TeamNamePolicy()

    @property
    def user_root(self) -> Path:
        return self._user_root

    def paths(self, name: TeamName) -> TeamPaths:
        return TeamPaths.for_user(self._user_root, name)

    def list(self) -> tuple[TeamSummary, ...]:
        root = self._user_root / "teams"
        if not root.exists():
            return ()
        summaries: list[TeamSummary] = []
        for candidate in sorted(root.iterdir(), key=lambda item: (item.name.casefold(), item.name)):
            if not candidate.is_dir() or candidate.is_symlink():
                continue
            try:
                state = self.load(self._names.parse(candidate.name))
            except (TeamValidationError, TeamCorruptionError, OSError):
                continue
            summaries.append(self._summary(state, candidate))
        return tuple(summaries)

    def create(self, state: TeamState) -> TeamState:
        self.validate(state)
        if len(self.list()) >= MAX_TEAMS:
            raise TeamValidationError(f"At most {MAX_TEAMS} teams may be stored.")
        paths = self.paths(state.manifest.name)
        paths.ensure_directories()
        lock = FileLock(paths.state_lock)
        if not lock.acquire():
            raise TeamConflictError("Team state is busy.")
        try:
            if paths.state_file.exists():
                raise TeamConflictError(f"Team already exists: {state.manifest.name.value}")
            atomic_write(paths.state_file, encode_team_state(state))
        finally:
            lock.close()
        return state

    def load(self, name: TeamName) -> TeamState:
        paths = self.paths(name)
        paths.validate_containment()
        try:
            payload = paths.state_file.read_bytes()
        except FileNotFoundError as exc:
            from .models import TeamNotFoundError
            raise TeamNotFoundError(f"Unknown team: {name.value}") from exc
        try:
            state = decode_team_state(payload)
            self.validate(state)
        except TeamCorruptionError:
            raise
        except (OSError, ValueError, TypeError) as exc:
            raise TeamCorruptionError(f"Team state is invalid: {name.value}") from exc
        if state.manifest.name.canonical_key != name.canonical_key:
            raise TeamCorruptionError("Team directory and manifest name do not match.")
        return state

    def compare_and_swap(
        self,
        name: TeamName,
        *,
        expected_revision: int,
        lease_fence: tuple[str, int],
        candidate: TeamState,
    ) -> TeamState:
        paths = self.paths(name)
        lock = FileLock(paths.state_lock)
        if not lock.acquire():
            raise TeamConflictError("Team state is busy.")
        try:
            current = self.load(name)
            if current.revision != expected_revision:
                raise TeamConflictError(
                    f"Team revision conflict: expected {expected_revision}, current {current.revision}."
                )
            self._validate_fence(paths, current.manifest.team_id, lease_fence)
            if candidate.manifest.team_id != current.manifest.team_id:
                raise TeamValidationError("Candidate belongs to a different team.")
            if candidate.revision not in {expected_revision, expected_revision + 1}:
                raise TeamValidationError("Candidate revision is invalid.")
            committed = replace(candidate, revision=expected_revision + 1, updated_at=self._now())
            self.validate(committed)
            atomic_write(paths.state_file, encode_team_state(committed))
            return committed
        finally:
            lock.close()

    def validate(self, state: TeamState) -> None:
        if state.manifest.updated_at > state.updated_at:
            raise TeamValidationError("Manifest timestamp is newer than team state.")
        if any(key != value.member_id for key, value in state.members.items()):
            raise TeamValidationError("Member map keys do not match member IDs.")
        if any(key != value.task_id for key, value in state.tasks.items()):
            raise TeamValidationError("Task map keys do not match task IDs.")
        if any(key != value.request_id for key, value in state.approvals.items()):
            raise TeamValidationError("Approval map keys do not match request IDs.")
        member_ids = set(state.members)
        participant_ids = {item.participant_id for item in state.registry.values()}
        for key, registration in state.registry.items():
            if key != registration.participant_name.canonical_key:
                raise TeamValidationError("Registry key does not match participant name.")
        for member in state.members.values():
            if member.member_id not in participant_ids:
                raise TeamValidationError("Member is missing from the mailbox registry.")
            if member.current_task_id is not None and member.current_task_id not in state.tasks:
                raise TeamValidationError("Member current task is unknown.")
        for task in state.tasks.values():
            if any(item not in state.tasks for item in task.dependency_ids):
                raise TeamValidationError("Task contains an unknown dependency.")
            if task.assignee_id is not None and task.assignee_id not in member_ids:
                raise TeamValidationError("Task assignee is unknown.")
        for approval in state.approvals.values():
            if approval.member_id not in member_ids or approval.task_id not in state.tasks:
                raise TeamValidationError("Approval references an unknown member or task.")
        queued: set[str] = set()
        for entry in state.queue:
            if entry.member_id not in member_ids or entry.member_id in queued:
                raise TeamValidationError("Queue contains an unknown or duplicate member.")
            queued.add(entry.member_id)

    def _validate_fence(
        self,
        paths: TeamPaths,
        team_id: str,
        expected: tuple[str, int],
    ) -> None:
        try:
            record = decode_lead_lease(paths.lease_file.read_bytes())
        except FileNotFoundError as exc:
            raise TeamLeaseError("Team has no active Lead lease.") from exc
        if record.team_id != team_id or (record.lease_id, record.generation) != expected:
            raise TeamLeaseError("Lead lease fence is stale.")
        age = self._now() - record.heartbeat_at
        if age >= timedelta(seconds=60):
            raise TeamLeaseError("Lead lease has expired.")

    @staticmethod
    def _summary(state: TeamState, root: Path) -> TeamSummary:
        return TeamSummary(
            team_id=state.manifest.team_id,
            name=state.manifest.name.value,
            leader_name=state.manifest.leader_name,
            repository_id=state.manifest.repository.repository_id,
            member_count=len(state.members),
            persistence_root=root,
        )


class TeamProvisioningJournalStore:
    def __init__(self, repository: TeamRepository, team: TeamName) -> None:
        self._paths = repository.paths(team)

    def write(self, transaction_id: str, payload: Mapping[str, object]) -> Path:
        self._paths.ensure_directories()
        path = self._paths.journal_file(transaction_id)
        atomic_write(path, encode_json(dict(payload)))
        return path

    def list(self) -> tuple[tuple[str, Mapping[str, object]], ...]:
        if not self._paths.transactions_root.exists():
            return ()
        values: list[tuple[str, Mapping[str, object]]] = []
        for path in sorted(self._paths.transactions_root.glob("*.json")):
            value = decode_json(path.read_bytes())
            if not isinstance(value, dict):
                raise TeamCorruptionError("Provisioning journal must contain an object.")
            values.append((path.stem, value))
        return tuple(values)

    def delete(self, transaction_id: str) -> None:
        self._paths.journal_file(transaction_id).unlink(missing_ok=True)


class TeamMutationRunner:
    def __init__(self, repository: TeamRepository, *, max_attempts: int = 4) -> None:
        self._repository = repository
        self._max_attempts = max_attempts

    def run(
        self,
        name: TeamName,
        *,
        lease_fence: tuple[str, int],
        transform: Callable[[TeamState], TeamState],
    ) -> TeamState:
        last: TeamConflictError | None = None
        for _attempt in range(self._max_attempts):
            current = self._repository.load(name)
            candidate = transform(current)
            try:
                return self._repository.compare_and_swap(
                    name,
                    expected_revision=current.revision,
                    lease_fence=lease_fence,
                    candidate=candidate,
                )
            except TeamConflictError as exc:
                last = exc
        raise last or TeamConflictError("Team mutation could not be committed.")
