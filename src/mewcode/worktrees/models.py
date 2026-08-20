from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path, PurePosixPath
import os
from types import MappingProxyType
from typing import Mapping


SCHEMA_VERSION = 1
MAX_RULES = 256
MAX_COPY_FILES = 4096
MAX_COPY_FILE_BYTES = 16 * 1024 * 1024
MAX_COPY_TOTAL_BYTES = 64 * 1024 * 1024
MAX_CLEANUP_CANDIDATES = 256
DEFAULT_CLEANUP_AGE = timedelta(hours=24)
DEFAULT_CLEANUP_INTERVAL = timedelta(hours=1)
MAX_DIAGNOSTIC_CHARS = 512


class WorktreeError(RuntimeError):
    pass


class WorktreeValidationError(WorktreeError, ValueError):
    pass


class WorktreeUnavailableError(WorktreeError):
    pass


def _bounded(value: str | None) -> str | None:
    if value is None:
        return None
    collapsed = " ".join(str(value).splitlines())
    return collapsed[:MAX_DIAGNOSTIC_CHARS]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise WorktreeValidationError("Worktree timestamps must be timezone-aware.")
    return value.astimezone(timezone.utc)


def _absolute(path: Path, field_name: str) -> Path:
    if not path.is_absolute():
        raise WorktreeValidationError(f"{field_name} must be absolute.")
    return Path(os.path.abspath(path))


def _oid(value: str, field_name: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) not in {40, 64} or any(ch not in "0123456789abcdef" for ch in normalized):
        raise WorktreeValidationError(f"{field_name} must be a full hexadecimal object ID.")
    return normalized


class WorktreeRuleKind(StrEnum):
    COPY = "copy"
    LINK = "link"
    GIT_HOOKS = "git_hooks"


@dataclass(frozen=True)
class WorktreeInitRule:
    kind: WorktreeRuleKind
    path: PurePosixPath
    required: bool
    origin: str

    def __post_init__(self) -> None:
        if not isinstance(self.required, bool):
            raise WorktreeValidationError("Rule required must be a boolean.")
        if not self.origin.strip():
            raise WorktreeValidationError("Rule origin must not be empty.")


@dataclass(frozen=True)
class WorktreeConfig:
    version: int
    rules: tuple[WorktreeInitRule, ...]
    max_copy_files: int = MAX_COPY_FILES
    max_copy_file_bytes: int = MAX_COPY_FILE_BYTES
    max_copy_total_bytes: int = MAX_COPY_TOTAL_BYTES

    def __post_init__(self) -> None:
        if self.version != SCHEMA_VERSION:
            raise WorktreeValidationError("Unsupported Worktree config version.")
        object.__setattr__(self, "rules", tuple(self.rules))
        if len(self.rules) > MAX_RULES:
            raise WorktreeValidationError(f"Worktree config exceeds {MAX_RULES} rules.")


@dataclass(frozen=True)
class WorktreeConfigSnapshot:
    config: WorktreeConfig | None
    error: str | None = None

    def __post_init__(self) -> None:
        if (self.config is None) == (self.error is None):
            raise WorktreeValidationError("Config snapshot must contain config or error.")
        object.__setattr__(self, "error", _bounded(self.error))


@dataclass(frozen=True)
class WorktreeName:
    value: str
    canonical_key: str


@dataclass(frozen=True)
class RepositoryIdentity:
    workspace_root: Path
    common_dir: Path
    repository_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "workspace_root", _absolute(self.workspace_root, "workspace_root"))
        object.__setattr__(self, "common_dir", _absolute(self.common_dir, "common_dir"))
        if not self.repository_id or len(self.repository_id) > 128:
            raise WorktreeValidationError("repository_id is invalid.")


@dataclass(frozen=True)
class WorktreeLayout:
    name: WorktreeName
    managed_root: Path
    root: Path
    branch_ref: str
    control_root: Path
    record_path: Path
    marker_path: Path
    lock_path: Path

    def __post_init__(self) -> None:
        for field_name in ("managed_root", "root", "control_root", "record_path", "marker_path", "lock_path"):
            object.__setattr__(self, field_name, _absolute(getattr(self, field_name), field_name))
        if not self.branch_ref.startswith("refs/heads/mewcode/worktree/"):
            raise WorktreeValidationError("branch_ref is outside the managed namespace.")


class WorktreeState(StrEnum):
    PROVISIONING = "provisioning"
    READY = "ready"
    ACTIVE = "active"
    RETAINED = "retained"
    DELETING = "deleting"
    DELETED = "deleted"


class WorktreePurpose(StrEnum):
    SUBAGENT_TASK = "subagent_task"
    TEAM_MEMBER = "team_member"


@dataclass(frozen=True)
class WorktreeOwner:
    purpose: WorktreePurpose
    owner_id: str
    persistent: bool

    def __post_init__(self) -> None:
        if not self.owner_id or len(self.owner_id) > 128:
            raise WorktreeValidationError("Worktree owner_id is invalid.")
        if not isinstance(self.persistent, bool):
            raise WorktreeValidationError("Worktree persistent flag must be a boolean.")
        if self.purpose is WorktreePurpose.TEAM_MEMBER and not self.persistent:
            raise WorktreeValidationError("Team member Worktrees must be persistent.")


@dataclass(frozen=True)
class WorktreeRecord:
    schema_version: int
    management_id: str
    repository_id: str
    name: str
    canonical_key: str
    root: Path
    branch_ref: str
    base_oid: str
    git_hooks_path: PurePosixPath | None
    task_id: str
    state: WorktreeState
    created_at: datetime
    last_used_at: datetime
    retained_reason: str | None = None
    purpose: WorktreePurpose = WorktreePurpose.SUBAGENT_TASK
    owner_id: str = ""
    persistent: bool = False

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise WorktreeValidationError("Unsupported Worktree record version.")
        if len(self.management_id) != 32 or any(ch not in "0123456789abcdef" for ch in self.management_id):
            raise WorktreeValidationError("management_id must be 128-bit lowercase hex.")
        if not self.repository_id or not self.task_id:
            raise WorktreeValidationError("Record identity fields must not be empty.")
        if not self.owner_id:
            object.__setattr__(self, "owner_id", self.task_id)
        if self.purpose is WorktreePurpose.TEAM_MEMBER and not self.persistent:
            raise WorktreeValidationError("Team member Worktrees must be persistent.")
        object.__setattr__(self, "root", _absolute(self.root, "root"))
        object.__setattr__(self, "base_oid", _oid(self.base_oid, "base_oid"))
        object.__setattr__(self, "created_at", _utc(self.created_at))
        object.__setattr__(self, "last_used_at", _utc(self.last_used_at))
        object.__setattr__(self, "retained_reason", _bounded(self.retained_reason))


@dataclass(frozen=True)
class WorktreeMarker:
    schema_version: int
    management_id: str
    repository_id: str
    name: str
    branch_ref: str
    base_oid: str
    git_hooks_path: PurePosixPath | None
    task_id: str
    ready: bool
    purpose: WorktreePurpose = WorktreePurpose.SUBAGENT_TASK
    owner_id: str = ""
    persistent: bool = False

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION or not self.ready:
            raise WorktreeValidationError("Worktree marker is not ready.")
        if len(self.management_id) != 32 or any(ch not in "0123456789abcdef" for ch in self.management_id):
            raise WorktreeValidationError("Invalid marker management_id.")
        if not self.owner_id:
            object.__setattr__(self, "owner_id", self.task_id)
        if self.purpose is WorktreePurpose.TEAM_MEMBER and not self.persistent:
            raise WorktreeValidationError("Team member Worktrees must be persistent.")
        object.__setattr__(self, "base_oid", _oid(self.base_oid, "base_oid"))


@dataclass(frozen=True)
class GitCommandResult:
    exit_code: int
    stdout: bytes
    stderr_summary: str
    timed_out: bool = False
    output_exceeded: bool = False


@dataclass(frozen=True)
class WorktreeProtection:
    head_oid: str | None
    tracked_changes: bool
    untracked_count: int
    unpublished_commit_count: int
    remote_refs_available: bool
    check_failed: bool
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.head_oid is not None:
            object.__setattr__(self, "head_oid", _oid(self.head_oid, "head_oid"))
        if self.untracked_count < 0 or self.unpublished_commit_count < 0:
            raise WorktreeValidationError("Protection counts must not be negative.")
        object.__setattr__(self, "reason", _bounded(self.reason))

    @property
    def safe_to_delete(self) -> bool:
        return (
            not self.check_failed
            and self.head_oid is not None
            and not self.tracked_changes
            and self.untracked_count == 0
            and self.unpublished_commit_count == 0
        )


@dataclass(frozen=True)
class InitializationDiagnostic:
    rule_kind: WorktreeRuleKind
    path: str
    message: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", self.path[:256])
        object.__setattr__(self, "message", _bounded(self.message) or "")


@dataclass(frozen=True)
class InitializationResult:
    diagnostics: tuple[InitializationDiagnostic, ...] = ()
    process_environment: Mapping[str, str] = field(default_factory=dict)
    git_hooks_path: PurePosixPath | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))
        object.__setattr__(self, "process_environment", MappingProxyType(dict(self.process_environment)))


@dataclass(frozen=True)
class WorktreeEnvironment:
    repository: RepositoryIdentity
    layout: WorktreeLayout
    record: WorktreeRecord
    process_environment: Mapping[str, str] = field(default_factory=dict)
    diagnostics: tuple[InitializationDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "process_environment", MappingProxyType(dict(self.process_environment)))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))

    @property
    def root(self) -> Path:
        return self.layout.root

    @property
    def branch_ref(self) -> str:
        return self.layout.branch_ref


@dataclass
class WorktreeLease:
    environment: WorktreeEnvironment
    task_id: str
    lock: object
    released: bool = False
    owner: WorktreeOwner | None = None


class WorktreeDeleteStatus(StrEnum):
    DELETED = "deleted"
    ALREADY_ABSENT = "already_absent"
    RETAINED = "retained"
    ACTIVE = "active"
    REJECTED = "rejected"


@dataclass(frozen=True)
class WorktreeExitResult:
    state: WorktreeState
    path: Path
    branch_ref: str
    protection: WorktreeProtection | None
    retained_reason: str | None = None


@dataclass(frozen=True)
class WorktreeDeleteResult:
    status: WorktreeDeleteStatus
    path: Path | None = None
    branch_ref: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "reason", _bounded(self.reason))


@dataclass(frozen=True)
class WorktreeStatus:
    name: str
    state: WorktreeState
    path: Path
    branch_ref: str
    last_used_at: datetime
    retained_reason: str | None = None
    purpose: WorktreePurpose = WorktreePurpose.SUBAGENT_TASK
    persistent: bool = False


@dataclass(frozen=True)
class WorkspaceExecutionContext:
    root: Path
    environment: Mapping[str, str] = field(default_factory=dict)
    isolation_name: str | None = None
    branch_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", _absolute(self.root, "root"))
        object.__setattr__(self, "environment", MappingProxyType(dict(self.environment)))


@dataclass(frozen=True)
class CleanupDiagnostic:
    name: str | None
    message: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "message", _bounded(self.message) or "")


@dataclass(frozen=True)
class CleanupReport:
    checked: int = 0
    deleted: int = 0
    retained: int = 0
    diagnostics: tuple[CleanupDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))
