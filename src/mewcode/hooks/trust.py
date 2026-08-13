from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Callable

from mewcode.locking import FileLock


TRUST_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class WorkspaceIdentity:
    digest: str
    path: str


def workspace_identity(workspace: Path) -> WorkspaceIdentity:
    resolved = str(Path(workspace).resolve())
    normalized = os.path.normcase(resolved)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return WorkspaceIdentity(digest=digest, path=resolved)


class WorkspaceTrustStore:
    def __init__(
        self,
        path: Path,
        *,
        lock_factory: Callable[[Path], FileLock] = FileLock,
    ) -> None:
        self.path = Path(path)
        self._lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        self._lock_factory = lock_factory
        self.last_diagnostic: str | None = None

    @classmethod
    def for_user_home(cls, user_home: Path | None = None) -> "WorkspaceTrustStore":
        home = Path.home() if user_home is None else Path(user_home)
        return cls(home / ".mewcode" / "hook-trust.json")

    def read(self, workspace: Path) -> bool | None:
        identity = workspace_identity(workspace)
        try:
            records = self._read_records()
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self.last_diagnostic = self._bounded(f"Hook trust could not be read: {exc}")
            return None
        record = records.get(identity.digest)
        if record is None or record["path"] != identity.path:
            return None
        return record["trusted"]

    def write(self, workspace: Path, trusted: bool) -> bool:
        if type(trusted) is not bool:
            raise TypeError("trusted must be a bool")
        identity = workspace_identity(workspace)
        lock = self._lock_factory(self._lock_path)
        try:
            deadline = time.monotonic() + 2.0
            while not lock.acquire():
                if time.monotonic() >= deadline:
                    raise OSError("timed out acquiring Hook trust lock")
                time.sleep(0.01)
            try:
                try:
                    records = self._read_records()
                except FileNotFoundError:
                    records = {}
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    self.last_diagnostic = self._bounded(
                        f"Hook trust update refused because the store is invalid: {exc}"
                    )
                    return False
                records[identity.digest] = {
                    "path": identity.path,
                    "trusted": trusted,
                }
                payload = {
                    "version": TRUST_SCHEMA_VERSION,
                    "workspaces": [
                        {
                            "identity": digest,
                            "path": value["path"],
                            "trusted": value["trusted"],
                        }
                        for digest, value in sorted(records.items())
                    ],
                }
                self._atomic_write(payload)
            finally:
                lock.close()
            self.last_diagnostic = None
            return True
        except OSError as exc:
            self.last_diagnostic = self._bounded(f"Hook trust could not be saved: {exc}")
            return False

    def _read_records(self) -> dict[str, dict[str, object]]:
        if not self.path.exists():
            return {}
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or set(raw) != {"version", "workspaces"}:
            raise ValueError("invalid root fields")
        if raw["version"] != TRUST_SCHEMA_VERSION or not isinstance(raw["workspaces"], list):
            raise ValueError("unsupported trust schema")
        records: dict[str, dict[str, object]] = {}
        for item in raw["workspaces"]:
            if not isinstance(item, dict) or set(item) != {"identity", "path", "trusted"}:
                raise ValueError("invalid workspace trust entry")
            digest, path, trusted = item["identity"], item["path"], item["trusted"]
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or not isinstance(path, str)
                or type(trusted) is not bool
                or digest in records
            ):
                raise ValueError("invalid or duplicate workspace trust identity")
            records[digest] = {"path": path, "trusted": trusted}
        return records

    def _atomic_write(self, payload: dict[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
        descriptor, temporary_name = tempfile.mkstemp(
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            suffix=".tmp",
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            parsed = json.loads(temporary.read_text(encoding="utf-8"))
            if parsed != payload:
                raise OSError("temporary trust verification failed")
            os.replace(temporary, self.path)
            self._fsync_directory(self.path.parent)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        if os.name == "nt":
            return
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _bounded(value: str) -> str:
        return value.replace("\r", " ").replace("\n", " ")[:1024]
