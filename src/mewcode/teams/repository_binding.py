from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import uuid

from mewcode.worktrees import GitWorktreeBackend, RepositoryIdentity

from .codec import decode_json, encode_json
from .models import RepositoryBinding, TeamAttachment, TeamValidationError
from .paths import TeamNamePolicy
from .repository import atomic_write


MARKER_SCHEMA_VERSION = 1


class TeamRepositoryBindingService:
    def __init__(
        self,
        git: GitWorktreeBackend | None = None,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        new_id: Callable[[], str] = lambda: uuid.uuid4().hex,
    ) -> None:
        self._git = git or GitWorktreeBackend()
        self._now = now
        self._new_id = new_id

    async def create_binding(self, team_id: str, workspace: Path) -> RepositoryBinding:
        identity = self._git.discover_repository(workspace)
        marker_id = self._new_id()
        proof = self._new_id()
        binding = RepositoryBinding(
            repository_marker_id=marker_id,
            repository_id=identity.repository_id,
            workspace_root=identity.workspace_root,
            common_dir=identity.common_dir,
            proof_nonce=proof,
            created_at=self._now(),
        )
        path = self._marker_path(identity, team_id)
        if path.exists():
            raise TeamValidationError("Repository already contains a marker for this team.")
        atomic_write(path, encode_json(self._marker_payload(team_id, binding)))
        return binding

    async def verify(self, binding: RepositoryBinding, workspace: Path) -> RepositoryIdentity:
        identity = self._git.discover_repository(workspace)
        if identity.repository_id != binding.repository_id:
            raise TeamValidationError("Current workspace belongs to a different Git repository.")
        if identity.workspace_root != binding.workspace_root or identity.common_dir != binding.common_dir:
            raise TeamValidationError("Repository path changed; explicit relink is required.")
        marker = self._find_marker(identity, binding.repository_marker_id)
        self._verify_marker(marker, binding)
        return identity

    async def relink(self, attachment: TeamAttachment, workspace: Path) -> RepositoryBinding:
        identity = self._git.discover_repository(workspace)
        old = attachment.state.manifest.repository
        marker = self._marker_path(identity, attachment.state.manifest.team_id)
        if not marker.exists():
            raise TeamValidationError("Moved repository does not contain the team proof.")
        self._verify_marker(self._read_marker(marker), old, team_id=attachment.state.manifest.team_id)
        return replace(
            old,
            repository_id=identity.repository_id,
            workspace_root=identity.workspace_root,
            common_dir=identity.common_dir,
            relinked_at=self._now(),
        )

    async def remove_binding(self, team_id: str, binding: RepositoryBinding) -> None:
        identity = RepositoryIdentity(
            binding.workspace_root,
            binding.common_dir,
            binding.repository_id,
        )
        path = self._marker_path(identity, team_id)
        if not path.exists():
            return
        marker = self._read_marker(path)
        self._verify_marker(marker, binding, team_id=team_id)
        path.unlink()

    @staticmethod
    def _marker_path(identity: RepositoryIdentity, team_id: str) -> Path:
        safe = TeamNamePolicy().safe_id(team_id, "team_id")
        return identity.common_dir / "mewcode" / "teams" / f"{safe}.json"

    def _find_marker(self, identity: RepositoryIdentity, marker_id: str) -> dict[str, object]:
        root = identity.common_dir / "mewcode" / "teams"
        if not root.is_dir():
            raise TeamValidationError("Repository team proof is missing.")
        matches = []
        for path in root.glob("*.json"):
            marker = self._read_marker(path)
            if marker.get("repository_marker_id") == marker_id:
                matches.append(marker)
        if len(matches) != 1:
            raise TeamValidationError("Repository team proof is missing or ambiguous.")
        return matches[0]

    @staticmethod
    def _read_marker(path: Path) -> dict[str, object]:
        value = decode_json(path.read_bytes())
        if not isinstance(value, dict):
            raise TeamValidationError("Repository team proof is invalid.")
        expected = {"schema_version", "team_id", "repository_marker_id", "proof_nonce"}
        if set(value) != expected or value.get("schema_version") != MARKER_SCHEMA_VERSION:
            raise TeamValidationError("Repository team proof has an unsupported format.")
        return value

    @staticmethod
    def _verify_marker(
        marker: dict[str, object],
        binding: RepositoryBinding,
        *,
        team_id: str | None = None,
    ) -> None:
        if marker.get("repository_marker_id") != binding.repository_marker_id:
            raise TeamValidationError("Repository team marker ID does not match.")
        if marker.get("proof_nonce") != binding.proof_nonce:
            raise TeamValidationError("Repository team proof does not match.")
        if team_id is not None and marker.get("team_id") != team_id:
            raise TeamValidationError("Repository team proof belongs to another team.")

    @staticmethod
    def _marker_payload(team_id: str, binding: RepositoryBinding) -> dict[str, object]:
        return {
            "schema_version": MARKER_SCHEMA_VERSION,
            "team_id": team_id,
            "repository_marker_id": binding.repository_marker_id,
            "proof_nonce": binding.proof_nonce,
        }
