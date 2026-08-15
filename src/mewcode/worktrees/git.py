from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
import re
import subprocess
from types import MappingProxyType
from typing import Mapping

from mewcode.processes import stop_process

from .models import (
    GitCommandResult,
    RepositoryIdentity,
    WorktreeEnvironment,
    WorktreeError,
    WorktreeLayout,
    WorktreeProtection,
    WorktreeValidationError,
)
from .paths import is_link_or_reparse


DEFAULT_GIT_TIMEOUT = 30.0
MAX_GIT_OUTPUT = 256 * 1024


_URL_USERINFO = re.compile(r"(?i)(https?://)[^/@\s]+@")


def _summary(value: bytes) -> str:
    text = value.decode("utf-8", errors="replace")
    collapsed = " ".join(text.splitlines())
    return _URL_USERINFO.sub(r"\1[redacted]@", collapsed)[:512]


class _GitOutputExceeded(Exception):
    def __init__(self, stream: str, data: bytes) -> None:
        super().__init__(stream)
        self.stream = stream
        self.data = data


async def _read_limited(
    reader: asyncio.StreamReader | None,
    stream: str,
) -> bytes:
    if reader is None:
        return b""
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = await reader.read(16 * 1024)
        if not chunk:
            return b"".join(chunks)
        remaining = max(0, MAX_GIT_OUTPUT - size)
        if remaining:
            chunks.append(chunk[:remaining])
        size += len(chunk)
        if size > MAX_GIT_OUTPUT:
            raise _GitOutputExceeded(stream, b"".join(chunks))


def _task_bytes(task: asyncio.Task[bytes]) -> bytes:
    if not task.done() or task.cancelled():
        return b""
    try:
        return task.result()
    except (Exception, asyncio.CancelledError):
        return b""


class GitCommandRunner:
    async def run(
        self,
        args: tuple[str, ...],
        *,
        cwd: Path,
        environment: Mapping[str, str] = MappingProxyType({}),
        timeout_seconds: float = DEFAULT_GIT_TIMEOUT,
    ) -> GitCommandResult:
        if not args or any(not isinstance(value, str) or "\x00" in value for value in args):
            raise ValueError("Git arguments are invalid.")
        if not cwd.is_absolute() or timeout_seconds <= 0:
            raise ValueError("Git cwd and timeout must be valid.")
        options: dict[str, object]
        if os.name == "nt":
            options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        else:
            options = {"start_new_session": True}
        env = os.environ.copy()
        env.update(environment)
        env.setdefault("GIT_TERMINAL_PROMPT", "0")
        env.setdefault("GIT_OPTIONAL_LOCKS", "0")
        process = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=cwd,
            env=env,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **options,
        )
        stdout_task = asyncio.create_task(_read_limited(process.stdout, "stdout"))
        stderr_task = asyncio.create_task(_read_limited(process.stderr, "stderr"))
        wait_task = asyncio.create_task(process.wait())
        timed_out = False
        exceeded: _GitOutputExceeded | None = None
        try:
            await asyncio.wait_for(
                asyncio.gather(stdout_task, stderr_task, wait_task),
                timeout_seconds,
            )
        except _GitOutputExceeded as exc:
            exceeded = exc
            await stop_process(process)
        except TimeoutError:
            timed_out = True
            await stop_process(process)
        except asyncio.CancelledError:
            await asyncio.shield(stop_process(process))
            raise
        finally:
            for task in (stdout_task, stderr_task, wait_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(
                stdout_task,
                stderr_task,
                wait_task,
                return_exceptions=True,
            )
        stdout = _task_bytes(stdout_task)
        stderr = _task_bytes(stderr_task)
        if exceeded is not None:
            if exceeded.stream == "stdout":
                stdout = exceeded.data
            else:
                stderr = exceeded.data
        return GitCommandResult(
            process.returncode if process.returncode is not None else -1,
            stdout,
            _summary(stderr),
            timed_out,
            exceeded is not None,
        )


class GitWorktreeBackend:
    def __init__(self, runner: GitCommandRunner | None = None) -> None:
        self._runner = runner or GitCommandRunner()

    def discover_repository(self, workspace: Path) -> RepositoryIdentity:
        root = workspace.resolve(strict=False)
        pointer = root / ".git"
        if is_link_or_reparse(pointer):
            raise WorktreeValidationError("Repository .git metadata must not be a link.")
        if pointer.is_dir():
            common = pointer.resolve(strict=False)
        elif pointer.is_file():
            text = self._read_small(pointer)
            if not text.startswith("gitdir: "):
                raise WorktreeValidationError("Repository .git pointer is invalid.")
            gitdir = Path(text[8:])
            if not gitdir.is_absolute():
                gitdir = root / gitdir
            gitdir = gitdir.resolve(strict=False)
            common_file = gitdir / "commondir"
            if common_file.is_file() and not common_file.is_symlink():
                common_value = self._read_small(common_file)
                common_candidate = Path(common_value)
                if not common_candidate.is_absolute():
                    common_candidate = gitdir / common_candidate
                if is_link_or_reparse(common_candidate):
                    raise WorktreeValidationError("Git common directory must not be a link.")
                common = common_candidate.resolve(strict=False)
            else:
                common = gitdir
        else:
            raise WorktreeValidationError("Workspace is not a supported Git working tree.")
        if not common.is_dir() or is_link_or_reparse(common):
            raise WorktreeValidationError("Git common directory is invalid.")
        digest = hashlib.sha256(os.path.normcase(str(common)).encode("utf-8")).hexdigest()[:32]
        return RepositoryIdentity(root, common, digest)

    async def resolve_head(self, repository: RepositoryIdentity) -> str:
        result = await self._run(("rev-parse", "--verify", "HEAD^{commit}"), repository.workspace_root)
        return self._parse_oid(result.stdout, "HEAD")

    async def add(
        self,
        repository: RepositoryIdentity,
        layout: WorktreeLayout,
        base_oid: str,
    ) -> None:
        zeros = "0" * len(base_oid)
        created = await self._runner.run(
            ("update-ref", layout.branch_ref, base_oid, zeros),
            cwd=repository.workspace_root,
            timeout_seconds=DEFAULT_GIT_TIMEOUT,
        )
        self._require(created, "create temporary branch")
        short_branch = layout.branch_ref.removeprefix("refs/heads/")
        added = await self._runner.run(
            ("worktree", "add", str(layout.root), short_branch),
            cwd=repository.workspace_root,
            timeout_seconds=DEFAULT_GIT_TIMEOUT,
        )
        if added.exit_code != 0 or added.timed_out or added.output_exceeded:
            await self._runner.run(
                ("update-ref", "-d", layout.branch_ref, base_oid),
                cwd=repository.workspace_root,
                timeout_seconds=DEFAULT_GIT_TIMEOUT,
            )
            self._require(added, "create Git Worktree")

    async def protection(self, environment: WorktreeEnvironment) -> WorktreeProtection:
        try:
            head_result = await self._run(("rev-parse", "--verify", "HEAD^{commit}"), environment.root, environment.process_environment)
            head = self._parse_oid(head_result.stdout, "HEAD")
            status = await self._run(("status", "--porcelain=v2", "-z", "--untracked-files=all"), environment.root, environment.process_environment)
            tracked = False
            untracked = 0
            for entry in status.stdout.split(b"\x00"):
                if not entry:
                    continue
                if entry.startswith(b"? "):
                    untracked += 1
                elif not entry.startswith(b"! "):
                    tracked = True
            refs = await self._run(("for-each-ref", "--format=%(objectname)", "refs/remotes"), environment.root, environment.process_environment)
            remote_oids = [line.strip() for line in refs.stdout.decode("ascii", errors="ignore").splitlines() if line.strip()]
            rev_args = ("rev-list", f"{environment.record.base_oid}..HEAD")
            if remote_oids:
                rev_args += ("--not", "--remotes")
            commits = await self._run(rev_args, environment.root, environment.process_environment)
            unpublished = len([line for line in commits.stdout.splitlines() if line.strip()])
            reasons = []
            if tracked:
                reasons.append("tracked changes")
            if untracked:
                reasons.append("untracked files")
            if unpublished:
                reasons.append("unpublished commits")
            return WorktreeProtection(head, tracked, untracked, unpublished, bool(remote_oids), False, ", ".join(reasons) or None)
        except (WorktreeError, OSError, ValueError) as exc:
            return WorktreeProtection(None, False, 0, 0, False, True, f"Protection check failed: {type(exc).__name__}.")

    async def remove_worktree(self, environment: WorktreeEnvironment, *, force: bool) -> None:
        args = ("worktree", "remove") + (("--force",) if force else ()) + (str(environment.root),)
        result = await self._runner.run(args, cwd=environment.repository.workspace_root, timeout_seconds=DEFAULT_GIT_TIMEOUT)
        self._require(result, "remove Git Worktree")

    async def delete_branch(self, environment: WorktreeEnvironment, *, expected_oid: str) -> None:
        result = await self._runner.run(
            ("update-ref", "-d", environment.branch_ref, expected_oid),
            cwd=environment.repository.workspace_root,
            timeout_seconds=DEFAULT_GIT_TIMEOUT,
        )
        self._require(result, "delete temporary branch")

    async def branch_oid(self, repository: RepositoryIdentity, branch_ref: str) -> str | None:
        result = await self._runner.run(
            ("show-ref", "--verify", "--hash", branch_ref),
            cwd=repository.workspace_root,
            timeout_seconds=DEFAULT_GIT_TIMEOUT,
        )
        if result.exit_code == 1:
            return None
        self._require(result, "read temporary branch")
        return self._parse_oid(result.stdout, "branch")

    async def prune(self, repository: RepositoryIdentity) -> None:
        result = await self._runner.run(("worktree", "prune", "--expire", "now"), cwd=repository.workspace_root, timeout_seconds=DEFAULT_GIT_TIMEOUT)
        self._require(result, "prune Worktree metadata")

    async def _run(self, args: tuple[str, ...], cwd: Path, environment: Mapping[str, str] = MappingProxyType({})) -> GitCommandResult:
        result = await self._runner.run(args, cwd=cwd, environment=environment, timeout_seconds=DEFAULT_GIT_TIMEOUT)
        self._require(result, args[0])
        return result

    @staticmethod
    def _require(result: GitCommandResult, operation: str) -> None:
        if result.timed_out:
            raise WorktreeError(f"Git {operation} timed out.")
        if result.output_exceeded:
            raise WorktreeError(f"Git {operation} exceeded its output limit.")
        if result.exit_code != 0:
            raise WorktreeError(f"Git {operation} failed: {result.stderr_summary}")

    @staticmethod
    def _parse_oid(payload: bytes, field: str) -> str:
        value = payload.decode("ascii", errors="strict").strip().lower()
        if len(value) not in {40, 64} or any(ch not in "0123456789abcdef" for ch in value):
            raise WorktreeError(f"Git returned an invalid {field} object ID.")
        return value

    @staticmethod
    def _read_small(path: Path) -> str:
        payload = path.read_bytes()
        if len(payload) > 4096:
            raise WorktreeValidationError("Git metadata is too large.")
        return payload.decode("utf-8").strip()
