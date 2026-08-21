from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Callable, Iterator, TypeVar

from mewcode.locking import FileLock
from mewcode.worktrees.paths import is_link_or_reparse

from .codec import (
    decode_coordinator_journal,
    decode_coordinator_settings,
    decode_decomposition_run,
    decode_integration_batch,
    decode_integration_step,
    encode_coordinator_journal,
    encode_coordinator_settings,
    encode_decomposition_run,
    encode_integration_batch,
    encode_integration_step,
)
from .coordinator_models import (
    COORDINATOR_SCHEMA_VERSION,
    CoordinatorJournal,
    CoordinatorJournalEntry,
    CoordinatorSettings,
    DecompositionRun,
    IntegrationBatch,
    IntegrationStep,
)
from .models import TeamConflictError, TeamCorruptionError, TeamName, TeamValidationError
from .repository import TeamRepository, atomic_write


MAX_COORDINATOR_FILE_BYTES = 4 * 1024 * 1024
T = TypeVar("T")


class CoordinatorRepository:
    def __init__(
        self,
        teams: TeamRepository,
        team: TeamName,
        *,
        lock_factory: Callable[[Path], FileLock] = FileLock,
    ) -> None:
        self._teams = teams
        self._team = team
        self._paths = teams.paths(team)
        self._lock_factory = lock_factory

    @property
    def paths(self):
        return self._paths

    @property
    def initialized(self) -> bool:
        return self._paths.coordinator_settings_file.is_file()

    def initialize(self, settings: CoordinatorSettings) -> CoordinatorSettings:
        if not settings.enabled:
            raise TeamValidationError("Disabled coordinator settings cannot be persisted.")
        self._paths.ensure_coordinator_directories()
        path = self._paths.coordinator_settings_file
        with self._locked(self._paths.coordinator_lock_file("settings", "settings")):
            if path.exists():
                existing = self._read(path, decode_coordinator_settings, CoordinatorSettings)
                if (
                    existing.schema_version != settings.schema_version
                    or existing.configuration_enabled != settings.configuration_enabled
                    or existing.environment_enabled != settings.environment_enabled
                    or existing.enabled != settings.enabled
                    or existing.safety_policy_version != settings.safety_policy_version
                    or existing.terminal_backends_verified != settings.terminal_backends_verified
                ):
                    raise TeamValidationError("Persisted coordinator settings do not match this runtime.")
                return existing
            atomic_write(path, encode_coordinator_settings(settings))
            return settings

    def load_settings(self) -> CoordinatorSettings:
        return self._read(
            self._paths.coordinator_settings_file,
            decode_coordinator_settings,
            CoordinatorSettings,
        )

    def create_decomposition(self, run: DecompositionRun) -> DecompositionRun:
        self._assert_team(run.team_id)
        path = self._paths.coordinator_decomposition_file(run.run_id)
        self._create(path, encode_decomposition_run(run), "decomposition", run.run_id)
        return run

    def load_decomposition(self, run_id: str) -> DecompositionRun:
        return self._read(
            self._paths.coordinator_decomposition_file(run_id),
            decode_decomposition_run,
            DecompositionRun,
        )

    def list_decompositions(self, *, active_only: bool = False) -> tuple[DecompositionRun, ...]:
        values = self._list(
            self._paths.coordinator_decompositions_root,
            decode_decomposition_run,
            DecompositionRun,
        )
        if active_only:
            values = tuple(item for item in values if not item.status.terminal)
        return tuple(sorted(values, key=lambda item: (item.created_at, item.run_id)))

    def update_decomposition(self, run: DecompositionRun, *, expected_revision: int) -> DecompositionRun:
        self._assert_team(run.team_id)
        return self._update(
            self._paths.coordinator_decomposition_file(run.run_id),
            run,
            expected_revision,
            decode_decomposition_run,
            encode_decomposition_run,
            DecompositionRun,
            "decomposition",
            run.run_id,
        )

    def create_batch(
        self,
        batch: IntegrationBatch,
        steps: tuple[IntegrationStep, ...],
    ) -> IntegrationBatch:
        self._assert_team(batch.team_id)
        if tuple(item.step_id for item in sorted(steps, key=lambda item: item.ordinal)) != batch.step_ids:
            raise TeamValidationError("Integration batch steps do not match the batch plan.")
        if any(item.batch_id != batch.batch_id for item in steps):
            raise TeamValidationError("Integration step belongs to another batch.")
        with self._locked(self._paths.coordinator_lock_file("batches", batch.batch_id)):
            batch_path = self._paths.coordinator_integration_file(batch.batch_id)
            if batch_path.exists():
                existing = self._read(batch_path, decode_integration_batch, IntegrationBatch)
                existing_steps = tuple(self.load_step(item) for item in existing.step_ids)
                if existing != batch or existing_steps != steps:
                    raise TeamConflictError("Integration batch already exists with different content.")
                return existing
            for step in steps:
                path = self._paths.coordinator_step_file(step.step_id)
                if path.exists():
                    if self._read(path, decode_integration_step, IntegrationStep) != step:
                        raise TeamConflictError("Integration step already exists with different content.")
            for step in steps:
                path = self._paths.coordinator_step_file(step.step_id)
                if not path.exists():
                    atomic_write(path, encode_integration_step(step))
            atomic_write(batch_path, encode_integration_batch(batch))
        return batch

    def load_batch(self, batch_id: str) -> IntegrationBatch:
        return self._read(
            self._paths.coordinator_integration_file(batch_id),
            decode_integration_batch,
            IntegrationBatch,
        )

    def list_batches(self, *, active_only: bool = False) -> tuple[IntegrationBatch, ...]:
        values = self._list(
            self._paths.coordinator_integrations_root,
            decode_integration_batch,
            IntegrationBatch,
        )
        if active_only:
            values = tuple(item for item in values if not item.status.terminal)
        return tuple(sorted(values, key=lambda item: (item.created_at, item.batch_id)))

    def update_batch(self, batch: IntegrationBatch, *, expected_revision: int) -> IntegrationBatch:
        self._assert_team(batch.team_id)
        return self._update(
            self._paths.coordinator_integration_file(batch.batch_id),
            batch,
            expected_revision,
            decode_integration_batch,
            encode_integration_batch,
            IntegrationBatch,
            "batches",
            batch.batch_id,
        )

    def load_step(self, step_id: str) -> IntegrationStep:
        return self._read(
            self._paths.coordinator_step_file(step_id),
            decode_integration_step,
            IntegrationStep,
        )

    def update_step(self, step: IntegrationStep, *, expected_revision: int) -> IntegrationStep:
        return self._update(
            self._paths.coordinator_step_file(step.step_id),
            step,
            expected_revision,
            decode_integration_step,
            encode_integration_step,
            IntegrationStep,
            "steps",
            step.step_id,
        )

    def create_journal(self, journal: CoordinatorJournal) -> CoordinatorJournal:
        self._assert_team(journal.team_id)
        path = self._paths.coordinator_journal_file(journal.journal_id)
        self._create(path, encode_coordinator_journal(journal), "journals", journal.journal_id)
        return journal

    def load_journal(self, journal_id: str) -> CoordinatorJournal:
        return self._read(
            self._paths.coordinator_journal_file(journal_id),
            decode_coordinator_journal,
            CoordinatorJournal,
        )

    def list_journals(self) -> tuple[CoordinatorJournal, ...]:
        values = self._list(
            self._paths.coordinator_journals_root,
            decode_coordinator_journal,
            CoordinatorJournal,
        )
        return tuple(sorted(values, key=lambda item: item.journal_id))

    def append_journal(
        self,
        journal_id: str,
        entry: CoordinatorJournalEntry,
    ) -> CoordinatorJournal:
        path = self._paths.coordinator_journal_file(journal_id)
        with self._locked(self._paths.coordinator_lock_file("journals", journal_id)):
            current = self._read(path, decode_coordinator_journal, CoordinatorJournal)
            updated = current.appended(entry)
            atomic_write(path, encode_coordinator_journal(updated))
            return updated

    @contextmanager
    def task_lock(self, task_id: str) -> Iterator[None]:
        with self._locked(self._paths.coordinator_lock_file("tasks", task_id)):
            yield

    @contextmanager
    def action_lock(self, action_id: str) -> Iterator[None]:
        with self._locked(self._paths.coordinator_lock_file("actions", action_id)):
            yield

    @contextmanager
    def branch_lock(self, repository_id: str, target_branch: str) -> Iterator[None]:
        path = self._paths.coordinator_branch_lock(repository_id, target_branch)
        with self._locked(path):
            yield

    def _create(self, path: Path, payload: bytes, kind: str, identifier: str) -> None:
        self._require_initialized()
        with self._locked(self._paths.coordinator_lock_file(kind, identifier)):
            if path.exists():
                raise TeamConflictError(f"Coordinator {kind} record already exists.")
            atomic_write(path, payload)

    def _update(
        self,
        path: Path,
        candidate: T,
        expected_revision: int,
        decoder: Callable[[bytes], object],
        encoder: Callable[[object], bytes],
        model_type: type[T],
        kind: str,
        identifier: str,
    ) -> T:
        with self._locked(self._paths.coordinator_lock_file(kind, identifier)):
            current = self._read(path, decoder, model_type)
            current_revision = getattr(current, "revision")
            candidate_revision = getattr(candidate, "revision")
            if current_revision != expected_revision:
                raise TeamConflictError(
                    f"Coordinator revision conflict: expected {expected_revision}, current {current_revision}."
                )
            if candidate_revision != expected_revision + 1:
                raise TeamValidationError("Coordinator candidate revision is invalid.")
            atomic_write(path, encoder(candidate))
            return candidate

    def _list(
        self,
        root: Path,
        decoder: Callable[[bytes], object],
        model_type: type[T],
    ) -> tuple[T, ...]:
        if not root.exists():
            return ()
        if not root.is_dir() or is_link_or_reparse(root):
            raise TeamCorruptionError("Coordinator record directory is invalid.")
        return tuple(self._read(path, decoder, model_type) for path in sorted(root.glob("*.json")))

    def _read(
        self,
        path: Path,
        decoder: Callable[[bytes], object],
        model_type: type[T],
    ) -> T:
        self._paths.validate_containment()
        if is_link_or_reparse(path) or not path.is_file():
            raise TeamCorruptionError("Coordinator record is missing or is not a regular file.")
        payload = path.read_bytes()
        if not payload or len(payload) > MAX_COORDINATOR_FILE_BYTES or not payload.endswith(b"\n"):
            raise TeamCorruptionError("Coordinator record is truncated or exceeds its size limit.")
        value = decoder(payload)
        if not isinstance(value, model_type):
            raise TeamCorruptionError("Coordinator record type is invalid.")
        return value

    def _assert_team(self, team_id: str) -> None:
        if self._teams.load(self._team).manifest.team_id != team_id:
            raise TeamValidationError("Coordinator record belongs to another team.")

    def _require_initialized(self) -> None:
        if not self.initialized:
            raise TeamValidationError("Coordinator repository has not been initialized.")

    @contextmanager
    def _locked(self, path: Path) -> Iterator[None]:
        lock = self._lock_factory(path)
        if not lock.acquire():
            lock.close()
            raise TeamConflictError("Coordinator state is busy.")
        try:
            yield
        finally:
            lock.close()
