from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import unicodedata

from mewcode.worktrees.paths import is_link_or_reparse

from .models import MAX_NAME_CHARS, TeamName, TeamValidationError


_SAFE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,63}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


def _canonical(value: Path) -> str:
    return os.path.normcase(os.path.abspath(value))


def _contained(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath((_canonical(path), _canonical(root))) == _canonical(root)
    except ValueError:
        return False


class TeamNamePolicy:
    def parse(self, value: str) -> TeamName:
        if not isinstance(value, str):
            raise TeamValidationError("Team and member names must be strings.")
        normalized = unicodedata.normalize("NFKC", value)
        if normalized != value or not _SAFE_NAME.fullmatch(normalized):
            raise TeamValidationError("Team or member name contains unsafe characters.")
        if len(normalized) > MAX_NAME_CHARS:
            raise TeamValidationError("Team or member name is too long.")
        canonical = normalized.casefold()
        if canonical.split(".", 1)[0] in _WINDOWS_RESERVED:
            raise TeamValidationError("Team or member name is reserved.")
        return TeamName(normalized, canonical)

    def safe_id(self, value: str, field_name: str = "identifier") -> str:
        if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
            raise TeamValidationError(f"{field_name} is unsafe.")
        if value.casefold().split(".", 1)[0] in _WINDOWS_RESERVED:
            raise TeamValidationError(f"{field_name} is reserved.")
        return value


@dataclass(frozen=True)
class TeamPaths:
    user_root: Path
    teams_root: Path
    team_root: Path
    state_file: Path
    lease_file: Path
    state_lock: Path
    lease_lock: Path
    mailboxes_root: Path
    members_root: Path
    transactions_root: Path

    @classmethod
    def for_user(cls, user_root: Path, name: TeamName) -> TeamPaths:
        base = Path(user_root)
        if not base.is_absolute():
            raise TeamValidationError("User data root must be absolute.")
        base = Path(os.path.abspath(base))
        teams = base / "teams"
        root = teams / name.value
        result = cls(
            user_root=base,
            teams_root=teams,
            team_root=root,
            state_file=root / "state.json",
            lease_file=root / "lead-lease.json",
            state_lock=root / "state.lock",
            lease_lock=root / "lead-lease.lock",
            mailboxes_root=root / "mailboxes",
            members_root=root / "members",
            transactions_root=root / "transactions",
        )
        result.validate_containment()
        return result

    def validate_containment(self) -> None:
        for path in (
            self.team_root, self.state_file, self.lease_file, self.state_lock,
            self.lease_lock, self.mailboxes_root, self.members_root,
            self.transactions_root,
        ):
            if not _contained(path, self.teams_root):
                raise TeamValidationError("Team path escapes the user team root.")
        current = self.teams_root
        while _contained(current, self.user_root):
            if current.exists() and is_link_or_reparse(current):
                raise TeamValidationError("Team path contains a link or reparse point.")
            if current == self.user_root:
                break
            current = current.parent

    def ensure_directories(self) -> None:
        self.validate_containment()
        for path in (self.team_root, self.mailboxes_root, self.members_root, self.transactions_root):
            path.mkdir(parents=True, exist_ok=True)
            if is_link_or_reparse(path):
                raise TeamValidationError("Team directory must not be a link.")

    def mailbox_file(self, participant_id: str) -> Path:
        safe = TeamNamePolicy().safe_id(participant_id, "participant_id")
        return self._child(self.mailboxes_root, f"{safe}.jsonl")

    def mailbox_lock(self, participant_id: str) -> Path:
        safe = TeamNamePolicy().safe_id(participant_id, "participant_id")
        return self._child(self.mailboxes_root, f"{safe}.lock")

    def member_session_file(self, member_id: str) -> Path:
        safe = TeamNamePolicy().safe_id(member_id, "member_id")
        return self._child(self.members_root, f"{safe}.jsonl")

    def member_lock(self, member_id: str) -> Path:
        safe = TeamNamePolicy().safe_id(member_id, "member_id")
        return self._child(self.members_root, f"{safe}.lock")

    def member_recovery_lock(self, member_id: str) -> Path:
        safe = TeamNamePolicy().safe_id(member_id, "member_id")
        return self._child(self.members_root, f"{safe}.recovery.lock")

    def journal_file(self, transaction_id: str) -> Path:
        safe = TeamNamePolicy().safe_id(transaction_id, "transaction_id")
        return self._child(self.transactions_root, f"{safe}.json")

    @staticmethod
    def _child(root: Path, name: str) -> Path:
        result = root / name
        if not _contained(result, root):
            raise TeamValidationError("Generated team path escapes its root.")
        return result
