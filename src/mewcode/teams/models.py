from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, TypeVar

from mewcode.permissions import PermissionMode, PermissionRuleSets
from mewcode.providers import ChatMessage


SCHEMA_VERSION = 1
MAX_TEAMS = 128
MAX_MEMBERS = 32
MAX_NAME_CHARS = 64
MAX_TASK_TITLE_CHARS = 256
MAX_TASK_DESCRIPTION_BYTES = 64 * 1024
MAX_TASK_DEPENDENCIES = 64
MAX_MESSAGE_SUMMARY_CHARS = 256
MAX_MESSAGE_BODY_BYTES = 64 * 1024
MAX_PROTOCOL_PAYLOAD_BYTES = 64 * 1024
MAX_DIAGNOSTIC_CHARS = 512
MAX_RESULT_CHARS = 20_000


class TeamError(RuntimeError):
    """Base error for persistent team operations."""


class TeamValidationError(TeamError, ValueError):
    pass


class TeamConflictError(TeamError):
    pass


class TeamPermissionError(TeamError):
    pass


class TeamNotFoundError(TeamError):
    pass


class TeamLeaseError(TeamError):
    pass


class TeamCorruptionError(TeamError):
    pass


def bounded_text(value: str | None, limit: int = MAX_DIAGNOSTIC_CHARS) -> str | None:
    if value is None:
        return None
    return " ".join(str(value).splitlines())[:limit]


def require_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise TeamValidationError(f"{field_name} must be timezone-aware.")
    return value.astimezone(timezone.utc)


def require_identifier(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 128:
        raise TeamValidationError(f"{field_name} is invalid.")
    if any(ch in value for ch in "\x00\r\n"):
        raise TeamValidationError(f"{field_name} is invalid.")
    return value


def require_absolute(value: Path, field_name: str) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        raise TeamValidationError(f"{field_name} must be absolute.")
    return candidate


K = TypeVar("K")
V = TypeVar("V")


def frozen_mapping(value: Mapping[K, V]) -> Mapping[K, V]:
    return MappingProxyType(dict(value))


class TeamMemberStatus(StrEnum):
    PROVISIONING = "provisioning"
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    IDLE = "idle"
    STOPPED = "stopped"
    INTERRUPTED = "interrupted"
    FAILED = "failed"

    @property
    def active(self) -> bool:
        return self in {self.QUEUED, self.RUNNING}


class TeamMemberBackend(StrEnum):
    IN_PROCESS = "in_process"


class TeamTaskStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        return self in {self.COMPLETED, self.FAILED, self.CANCELLED}


class PlanApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    INVALIDATED = "invalidated"


class PlanDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class TeamProtocol(StrEnum):
    TEXT = "text"
    TASK_ASSIGNMENT = "task_assignment"
    TASK_STATUS = "task_status"
    PLAN_REQUEST = "plan_request"
    PLAN_DECISION = "plan_decision"
    MEMBER_IDLE = "member_idle"
    STOP_REQUEST = "stop_request"


class MemberWakeReason(StrEnum):
    MESSAGE = "message"
    EXPLICIT_RESUME = "explicit_resume"
    APPROVAL_DECISION = "approval_decision"
    RECOVERED_QUEUE = "recovered_queue"


class TeamActorKind(StrEnum):
    LEAD = "lead"
    MEMBER = "member"
    SYSTEM = "system"


class TeamMemberOutcomeKind(StrEnum):
    IDLE = "idle"
    AWAITING_APPROVAL = "awaiting_approval"
    STOPPED = "stopped"
    INTERRUPTED = "interrupted"
    FAILED = "failed"


@dataclass(frozen=True)
class TeamName:
    value: str
    canonical_key: str

    def __post_init__(self) -> None:
        if not self.value or len(self.value) > MAX_NAME_CHARS:
            raise TeamValidationError("Team or member name is invalid.")
        if not self.canonical_key or len(self.canonical_key) > MAX_NAME_CHARS:
            raise TeamValidationError("Canonical name is invalid.")


@dataclass(frozen=True)
class TeamActor:
    participant_id: str
    name: TeamName
    kind: TeamActorKind
    team_id: str
    lease_fence: tuple[str, int]

    def __post_init__(self) -> None:
        require_identifier(self.participant_id, "participant_id")
        require_identifier(self.team_id, "team_id")
        lease_id, generation = self.lease_fence
        require_identifier(lease_id, "lease_id")
        if generation < 0:
            raise TeamValidationError("Lease generation must not be negative.")


@dataclass(frozen=True)
class TeamDiagnostic:
    code: str
    message: str
    team_id: str | None = None
    member_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "message", bounded_text(self.message) or "")


@dataclass(frozen=True)
class RepositoryBinding:
    repository_marker_id: str
    repository_id: str
    workspace_root: Path
    common_dir: Path
    proof_nonce: str
    created_at: datetime
    relinked_at: datetime | None = None

    def __post_init__(self) -> None:
        require_identifier(self.repository_marker_id, "repository_marker_id")
        require_identifier(self.repository_id, "repository_id")
        require_identifier(self.proof_nonce, "proof_nonce")
        object.__setattr__(self, "workspace_root", require_absolute(self.workspace_root, "workspace_root"))
        object.__setattr__(self, "common_dir", require_absolute(self.common_dir, "common_dir"))
        object.__setattr__(self, "created_at", require_utc(self.created_at, "created_at"))
        if self.relinked_at is not None:
            object.__setattr__(self, "relinked_at", require_utc(self.relinked_at, "relinked_at"))


@dataclass(frozen=True)
class TeamManifest:
    team_id: str
    name: TeamName
    leader_name: str
    repository: RepositoryBinding
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        require_identifier(self.team_id, "team_id")
        require_identifier(self.leader_name, "leader_name")
        object.__setattr__(self, "created_at", require_utc(self.created_at, "created_at"))
        object.__setattr__(self, "updated_at", require_utc(self.updated_at, "updated_at"))


@dataclass(frozen=True)
class FrozenRoleSnapshot:
    snapshot_id: str
    role_name: str
    source_fingerprint: str
    description: str
    system_prompt: str
    profile_name: str
    max_turns: int
    permission_mode: PermissionMode
    allowed_tool_names: tuple[str, ...]
    denied_tool_names: tuple[str, ...]
    permission_rules: PermissionRuleSets
    created_at: datetime

    def __post_init__(self) -> None:
        for field_name in ("snapshot_id", "role_name", "source_fingerprint", "profile_name"):
            require_identifier(getattr(self, field_name), field_name)
        if self.profile_name == "inherit":
            raise TeamValidationError("Frozen roles must resolve the profile name.")
        if self.max_turns < 1:
            raise TeamValidationError("max_turns must be positive.")
        allowed = tuple(self.allowed_tool_names)
        denied = tuple(self.denied_tool_names)
        if len(set(allowed)) != len(allowed) or len(set(denied)) != len(denied):
            raise TeamValidationError("Frozen role tools must not contain duplicates.")
        object.__setattr__(self, "allowed_tool_names", allowed)
        object.__setattr__(self, "denied_tool_names", denied)
        object.__setattr__(self, "created_at", require_utc(self.created_at, "created_at"))


@dataclass(frozen=True)
class TeamMemberRecord:
    member_id: str
    name: TeamName
    role: FrozenRoleSnapshot
    backend: TeamMemberBackend
    requires_approval: bool
    status: TeamMemberStatus
    worktree_name: str
    worktree_root: Path
    worktree_owner_id: str
    mailbox_name: str
    session_name: str
    current_task_id: str | None
    active_run_id: str | None
    run_generation: int
    last_error: str | None
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        for field_name in ("member_id", "worktree_name", "worktree_owner_id", "mailbox_name", "session_name"):
            require_identifier(getattr(self, field_name), field_name)
        if not isinstance(self.requires_approval, bool):
            raise TeamValidationError("requires_approval must be a boolean.")
        if self.run_generation < 0:
            raise TeamValidationError("run_generation must not be negative.")
        object.__setattr__(self, "worktree_root", require_absolute(self.worktree_root, "worktree_root"))
        object.__setattr__(self, "last_error", bounded_text(self.last_error))
        object.__setattr__(self, "created_at", require_utc(self.created_at, "created_at"))
        object.__setattr__(self, "updated_at", require_utc(self.updated_at, "updated_at"))


@dataclass(frozen=True)
class TeamTask:
    task_id: str
    revision: int
    approval_epoch: int
    title: str
    description: str
    status: TeamTaskStatus
    assignee_id: str | None
    dependency_ids: tuple[str, ...]
    created_by: str
    result: str
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None

    def __post_init__(self) -> None:
        require_identifier(self.task_id, "task_id")
        require_identifier(self.created_by, "created_by")
        if self.revision < 0 or self.approval_epoch < 0:
            raise TeamValidationError("Task revisions must not be negative.")
        if not self.title or len(self.title) > MAX_TASK_TITLE_CHARS:
            raise TeamValidationError("Task title is invalid.")
        if len(self.description.encode("utf-8")) > MAX_TASK_DESCRIPTION_BYTES:
            raise TeamValidationError("Task description is too large.")
        dependencies = tuple(self.dependency_ids)
        if len(dependencies) > MAX_TASK_DEPENDENCIES:
            raise TeamValidationError("Task has too many dependencies.")
        if len(set(dependencies)) != len(dependencies):
            raise TeamValidationError("Task dependencies must not contain duplicates.")
        if len(self.result) > MAX_RESULT_CHARS:
            raise TeamValidationError("Task result is too large.")
        object.__setattr__(self, "dependency_ids", dependencies)
        for field_name in ("created_at", "updated_at", "started_at", "finished_at"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, require_utc(value, field_name))


@dataclass(frozen=True)
class TeamTaskView:
    task: TeamTask
    blocked: bool
    blocking_task_ids: tuple[str, ...]
    claimable: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "blocking_task_ids", tuple(self.blocking_task_ids))


@dataclass(frozen=True)
class PlanApprovalRecord:
    request_id: str
    member_id: str
    task_id: str
    task_revision: int
    approval_epoch: int
    plan_version: int
    plan_text: str
    summary: str
    status: PlanApprovalStatus
    decision: PlanDecision | None
    feedback: str | None
    requested_at: datetime
    decided_at: datetime | None = None

    def __post_init__(self) -> None:
        for field_name in ("request_id", "member_id", "task_id"):
            require_identifier(getattr(self, field_name), field_name)
        if min(self.task_revision, self.approval_epoch, self.plan_version) < 0:
            raise TeamValidationError("Approval versions must not be negative.")
        if not self.plan_text or len(self.plan_text.encode("utf-8")) > MAX_MESSAGE_BODY_BYTES:
            raise TeamValidationError("Plan text is invalid.")
        _validate_summary(self.summary)
        object.__setattr__(self, "feedback", bounded_text(self.feedback, MAX_MESSAGE_BODY_BYTES))
        object.__setattr__(self, "requested_at", require_utc(self.requested_at, "requested_at"))
        if self.decided_at is not None:
            object.__setattr__(self, "decided_at", require_utc(self.decided_at, "decided_at"))


@dataclass(frozen=True)
class MailboxRegistration:
    participant_id: str
    participant_name: TeamName
    mailbox_name: str
    is_lead: bool


def _validate_summary(value: str) -> None:
    if not value or len(value) > MAX_MESSAGE_SUMMARY_CHARS or "\n" in value or "\r" in value:
        raise TeamValidationError("Message summary must be a non-empty single line.")


@dataclass(frozen=True)
class TeamMessage:
    schema_version: int
    message_id: str
    correlation_id: str | None
    sender_id: str
    recipient_id: str
    summary: str
    body: str
    protocol: TeamProtocol
    payload: Mapping[str, object]
    sent_at: datetime
    read: bool = False

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise TeamValidationError("Unsupported team message version.")
        for field_name in ("message_id", "sender_id", "recipient_id"):
            require_identifier(getattr(self, field_name), field_name)
        _validate_summary(self.summary)
        if len(self.body.encode("utf-8")) > MAX_MESSAGE_BODY_BYTES:
            raise TeamValidationError("Message body is too large.")
        if not isinstance(self.read, bool):
            raise TeamValidationError("Message read must be a boolean.")
        object.__setattr__(self, "payload", frozen_mapping(self.payload))
        object.__setattr__(self, "sent_at", require_utc(self.sent_at, "sent_at"))


@dataclass(frozen=True)
class MailboxMessageRecord:
    message: TeamMessage


@dataclass(frozen=True)
class MailboxReadRecord:
    receipt_id: str
    message_ids: tuple[str, ...]
    read_at: datetime

    def __post_init__(self) -> None:
        require_identifier(self.receipt_id, "receipt_id")
        object.__setattr__(self, "message_ids", tuple(self.message_ids))
        object.__setattr__(self, "read_at", require_utc(self.read_at, "read_at"))


@dataclass(frozen=True)
class MemberQueueEntry:
    queue_id: str
    sequence: int
    member_id: str
    reason: MemberWakeReason
    message_ids: tuple[str, ...]
    requested_at: datetime

    def __post_init__(self) -> None:
        require_identifier(self.queue_id, "queue_id")
        require_identifier(self.member_id, "member_id")
        if self.sequence < 0:
            raise TeamValidationError("Queue sequence must not be negative.")
        object.__setattr__(self, "message_ids", tuple(dict.fromkeys(self.message_ids)))
        object.__setattr__(self, "requested_at", require_utc(self.requested_at, "requested_at"))


@dataclass(frozen=True)
class TeamOutboxEntry:
    outbox_id: str
    message: TeamMessage
    delivered: bool
    created_at: datetime
    delivered_at: datetime | None = None
    last_error: str | None = None

    def __post_init__(self) -> None:
        require_identifier(self.outbox_id, "outbox_id")
        object.__setattr__(self, "created_at", require_utc(self.created_at, "created_at"))
        if self.delivered_at is not None:
            object.__setattr__(self, "delivered_at", require_utc(self.delivered_at, "delivered_at"))
        object.__setattr__(self, "last_error", bounded_text(self.last_error))


@dataclass(frozen=True)
class TeamState:
    schema_version: int
    revision: int
    manifest: TeamManifest
    members: Mapping[str, TeamMemberRecord]
    registry: Mapping[str, MailboxRegistration]
    tasks: Mapping[str, TeamTask]
    approvals: Mapping[str, PlanApprovalRecord]
    queue: tuple[MemberQueueEntry, ...]
    outbox: tuple[TeamOutboxEntry, ...]
    updated_at: datetime

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION or self.revision < 0:
            raise TeamValidationError("Team state version or revision is invalid.")
        if len(self.members) > MAX_MEMBERS:
            raise TeamValidationError(f"A team may contain at most {MAX_MEMBERS} members.")
        object.__setattr__(self, "members", frozen_mapping(self.members))
        object.__setattr__(self, "registry", frozen_mapping(self.registry))
        object.__setattr__(self, "tasks", frozen_mapping(self.tasks))
        object.__setattr__(self, "approvals", frozen_mapping(self.approvals))
        object.__setattr__(self, "queue", tuple(self.queue))
        object.__setattr__(self, "outbox", tuple(self.outbox))
        object.__setattr__(self, "updated_at", require_utc(self.updated_at, "updated_at"))


@dataclass(frozen=True)
class TeamSummary:
    team_id: str
    name: str
    leader_name: str
    repository_id: str
    member_count: int
    persistence_root: Path


@dataclass(frozen=True)
class TeamLeadLeaseRecord:
    schema_version: int
    team_id: str
    lease_id: str
    generation: int
    holder_session_id: str
    holder_process_id: str
    heartbeat_at: datetime

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION or self.generation < 0:
            raise TeamValidationError("Lead lease version or generation is invalid.")
        for field_name in ("team_id", "lease_id", "holder_session_id", "holder_process_id"):
            require_identifier(getattr(self, field_name), field_name)
        object.__setattr__(self, "heartbeat_at", require_utc(self.heartbeat_at, "heartbeat_at"))


@dataclass(frozen=True)
class TeamLeadLease:
    record: TeamLeadLeaseRecord
    released: bool = False

    @property
    def fence(self) -> tuple[str, int]:
        return self.record.lease_id, self.record.generation


@dataclass(frozen=True)
class TeamAttachment:
    state: TeamState
    lease: TeamLeadLease
    root_session_id: str


@dataclass(frozen=True)
class MemberSessionState:
    member_id: str
    session_id: str
    messages: tuple[ChatMessage, ...]
    delivered_message_ids: frozenset[str]
    context_archive_id: str
    last_activity: datetime | None
    last_complete_boundary: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "messages", tuple(self.messages))
        object.__setattr__(self, "delivered_message_ids", frozenset(self.delivered_message_ids))
        if self.last_complete_boundary < 0 or self.last_complete_boundary > len(self.messages):
            raise TeamValidationError("Session boundary is invalid.")
        if self.last_activity is not None:
            object.__setattr__(self, "last_activity", require_utc(self.last_activity, "last_activity"))


@dataclass(frozen=True)
class AgentInboundBatch:
    batch_id: str
    messages: tuple[ChatMessage, ...]
    mailbox_message_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "messages", tuple(self.messages))
        object.__setattr__(self, "mailbox_message_ids", tuple(self.mailbox_message_ids))


@dataclass(frozen=True)
class DeliveryResult:
    recipient_id: str
    message_id: str
    delivered: bool
    error: str | None = None
    safe_pause: bool = False


@dataclass(frozen=True)
class BroadcastResult:
    correlation_id: str
    results: tuple[DeliveryResult, ...]


@dataclass(frozen=True)
class MailboxPage:
    messages: tuple[TeamMessage, ...]
    next_cursor: str | None = None


@dataclass(frozen=True)
class OutboxFlushResult:
    delivered_ids: tuple[str, ...] = ()
    failed_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class MemberRemovalResult:
    removed: bool
    retained_worktree: Path | None = None
    reason: str | None = None


@dataclass(frozen=True)
class TeamMemberOutcome:
    kind: TeamMemberOutcomeKind
    result_summary: str = ""
    error: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "result_summary", bounded_text(self.result_summary, 4096) or "")
        object.__setattr__(self, "error", bounded_text(self.error))


@dataclass(frozen=True)
class TeamMemberProgress:
    phase: str
    message: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "message", bounded_text(self.message, 1024) or "")


@dataclass(frozen=True)
class TeamMessageDraft:
    recipient: str
    summary: str
    body: str
    protocol: TeamProtocol
    payload: Mapping[str, object] = field(default_factory=dict)
    message_id: str | None = None
    correlation_id: str | None = None


@dataclass(frozen=True)
class ProtocolTransition:
    message: TeamMessage
    candidate_state: TeamState
    safe_pause: bool = False
