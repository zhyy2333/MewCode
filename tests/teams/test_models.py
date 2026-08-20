from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime

import pytest

from mewcode.teams.models import (
    MAX_DIAGNOSTIC_CHARS,
    MAX_MESSAGE_BODY_BYTES,
    PANE_BINDING_SCHEMA_VERSION,
    MemberBackendRequest,
    MemberWakeReceipt,
    MemberWakeReason,
    MemberWakeStatus,
    PaneHealth,
    PlanApprovalStatus,
    PlanDecision,
    TeamMemberBackend,
    TeamMemberRuntimeView,
    TeamMemberStatus,
    TeamMessage,
    TeamProtocol,
    TeamTaskStatus,
    TeamValidationError,
    TerminalPaneBinding,
)

from .helpers import FakeClock, FakeIds, empty_state, team_name


def test_helpers_are_deterministic_and_models_are_frozen(tmp_path) -> None:
    clock = FakeClock()
    ids = FakeIds()
    assert ids() == "id-1"
    assert ids() == "id-2"
    state = empty_state(tmp_path, clock)
    with pytest.raises(FrozenInstanceError):
        state.revision = 2  # type: ignore[misc]


def test_enum_contract_is_exact() -> None:
    assert [item.value for item in TeamMemberStatus] == [
        "provisioning", "queued", "running", "awaiting_approval",
        "idle", "stopped", "interrupted", "failed",
    ]
    assert [item.value for item in TeamMemberBackend] == [
        "in_process", "windows_terminal", "tmux",
    ]
    assert [item.value for item in MemberBackendRequest] == [
        "auto", "in_process", "windows_terminal", "tmux",
    ]
    assert [item.value for item in PaneHealth] == [
        "not_applicable", "connected", "missing", "unavailable",
    ]
    assert [item.value for item in MemberWakeStatus] == [
        "running", "queued", "failed", "not_applicable",
    ]
    assert [item.value for item in TeamTaskStatus] == [
        "pending", "in_progress", "completed", "failed", "cancelled",
    ]
    assert [item.value for item in PlanApprovalStatus] == [
        "pending", "approved", "rejected", "invalidated",
    ]
    assert [item.value for item in PlanDecision] == ["approve", "reject"]
    assert [item.value for item in TeamProtocol] == [
        "text", "task_assignment", "task_status", "plan_request",
        "plan_decision", "member_idle", "stop_request",
    ]
    assert len(MemberWakeReason) == 4


def test_terminal_pane_binding_and_runtime_view_invariants(tmp_path) -> None:
    now = FakeClock().now()
    state = empty_state(tmp_path, FakeClock())
    from .helpers import state_with_members

    member = state_with_members(tmp_path, 1).members["member-1"]
    binding = TerminalPaneBinding(
        PANE_BINDING_SCHEMA_VERSION,
        TeamMemberBackend.TMUX,
        "host-1",
        "%7",
        now,
        now,
        "x" * (MAX_DIAGNOSTIC_CHARS + 10),
    )
    assert len(binding.last_error or "") == MAX_DIAGNOSTIC_CHARS
    terminal_member = member.__class__(
        **{
            **member.__dict__,
            "backend": TeamMemberBackend.TMUX,
            "pane_binding": binding,
        }
    )
    view = TeamMemberRuntimeView(terminal_member, PaneHealth.CONNECTED, "ready")
    assert view.member.pane_binding == binding
    assert MemberWakeReceipt("member-1", MemberWakeStatus.RUNNING).diagnostic is None
    with pytest.raises(TeamValidationError, match="not_applicable"):
        TeamMemberRuntimeView(member, PaneHealth.CONNECTED)
    with pytest.raises(TeamValidationError, match="handle is invalid"):
        TerminalPaneBinding(
            PANE_BINDING_SCHEMA_VERSION,
            TeamMemberBackend.TMUX,
            "host-1",
            "7",
            now,
        )
    with pytest.raises(TeamValidationError, match="Unsupported"):
        TerminalPaneBinding(
            PANE_BINDING_SCHEMA_VERSION + 1,
            TeamMemberBackend.TMUX,
            "host-1",
            "%7",
            now,
        )


def test_names_and_messages_enforce_limits() -> None:
    with pytest.raises(TeamValidationError):
        team_name("x" * 65)
    now = FakeClock().now()
    message = TeamMessage(
        schema_version=1,
        message_id="message-1",
        correlation_id=None,
        sender_id="lead",
        recipient_id="member-1",
        summary="hello",
        body="world",
        protocol=TeamProtocol.TEXT,
        payload={},
        sent_at=now,
    )
    assert message.read is False
    with pytest.raises(TeamValidationError):
        TeamMessage(**{**message.__dict__, "summary": "two\nlines"})
    with pytest.raises(TeamValidationError):
        TeamMessage(**{**message.__dict__, "body": "x" * (MAX_MESSAGE_BODY_BYTES + 1)})
    with pytest.raises(TeamValidationError):
        TeamMessage(**{**message.__dict__, "sent_at": datetime.now()})
