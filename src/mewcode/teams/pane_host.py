from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
import sys

from .control import (
    ControlCancelRequest,
    ControlDescriptorStore,
    ControlRunRequest,
    ControlRunResult,
    ControlShutdownRequest,
    PaneHostConnection,
    TcpPaneHostClient,
)
from .member_worker import MEMBER_RUN_SCHEMA_VERSION, MemberRunDescriptor, MemberRunDescriptorStore
from .models import TeamMemberOutcomeKind, TeamValidationError
from .paths import TeamNamePolicy, TeamPaths


WorkerRunner = Callable[[ControlRunRequest], Awaitable[ControlRunResult]]


class ManagedPaneHost:
    """One long-lived pane host.  It serializes managed worker processes."""

    def __init__(self, connection: PaneHostConnection, run_worker: WorkerRunner) -> None:
        self._connection = connection
        self._run_worker = run_worker
        self._closed = False
        self._serving = False
        self._serve_task: asyncio.Task[ControlRunResult] | None = None
        self._active: asyncio.Task[ControlRunResult] | None = None

    async def serve_once(self) -> ControlRunResult:
        if self._closed:
            raise TeamValidationError("Pane host is closed.")
        if self._serving:
            raise TeamValidationError("Pane host already has a running member worker.")
        self._serving = True
        self._serve_task = asyncio.current_task()
        try:
            request = await self._connection.next_request()
            if isinstance(request, ControlCancelRequest):
                raise TeamValidationError("Pane host has no matching active member worker to cancel.")
            self._active = asyncio.create_task(self._run_worker(request))
            try:
                result = await self._active
            except asyncio.CancelledError:
                result = ControlRunResult(
                    request.run_id,
                    request.run_generation,
                    TeamMemberOutcomeKind.INTERRUPTED.value,
                    "Pane host cancelled the member worker.",
                )
            except BaseException as exc:
                result = ControlRunResult(
                    request.run_id,
                    request.run_generation,
                    TeamMemberOutcomeKind.FAILED.value,
                    f"Pane host worker failed: {type(exc).__name__}.",
                )
            await self._connection.publish_result(result)
            return result
        finally:
            self._active = None
            self._serving = False
            self._serve_task = None

    async def close(self) -> None:
        self._closed = True
        serving = self._serve_task
        if self._active is not None and not self._active.done():
            self._active.cancel()
        elif serving is not None and serving is not asyncio.current_task() and not serving.done():
            serving.cancel()
        if serving is not None and serving is not asyncio.current_task():
            await asyncio.gather(serving, return_exceptions=True)
        await self._connection.close()


ChildWaiter = Callable[[tuple[str, ...]], Awaitable[int]]


async def _default_child_waiter(argv: tuple[str, ...]) -> int:
    process = await asyncio.create_subprocess_exec(*argv)
    try:
        return await process.wait()
    except asyncio.CancelledError:
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
        raise


async def run_pane_host(
    control_file: Path,
    *,
    child_waiter: ChildWaiter = _default_child_waiter,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    max_reconnect_attempts: int | None = None,
) -> int:
    """Hidden-process host loop.  It has no REPL, session, or TeamState writer."""
    paths = _paths_for_control_file(control_file)
    store = MemberRunDescriptorStore(paths)
    attempts = 0
    while True:
        client: TcpPaneHostClient | None = None
        try:
            descriptor = ControlDescriptorStore(paths).read(control_file)
            client = TcpPaneHostClient(descriptor)
            await client.open()
            attempts = 0
            shutdown = await _serve_tcp_host(client, descriptor, store, child_waiter)
            if shutdown:
                return 0
        except asyncio.CancelledError:
            raise
        except Exception:
            attempts += 1
            if max_reconnect_attempts is not None and attempts >= max_reconnect_attempts:
                return 1
        finally:
            if client is not None:
                await client.close()
        await sleep(min(0.1 * (2 ** min(attempts, 6)), 5.0))


async def _serve_tcp_host(
    client: TcpPaneHostClient,
    descriptor,
    store: MemberRunDescriptorStore,
    child_waiter: ChildWaiter,
) -> bool:
    active: asyncio.Task[ControlRunResult] | None = None
    active_request: ControlRunRequest | None = None
    try:
        while True:
            if active is None:
                request = await client.next_request()
                if isinstance(request, ControlShutdownRequest):
                    return True
                if isinstance(request, ControlCancelRequest):
                    continue
                active_request = request
                active = asyncio.create_task(
                    _run_worker_request(request, descriptor, store, child_waiter)
                )

            incoming = asyncio.create_task(client.next_request())
            done, _pending = await asyncio.wait(
                (active, incoming),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if active in done:
                if incoming in done:
                    extra = incoming.result()
                    if isinstance(extra, ControlShutdownRequest):
                        await client.publish_result(active.result())
                        return True
                    if isinstance(extra, ControlRunRequest):
                        await client.publish_result(ControlRunResult(
                            extra.run_id,
                            extra.run_generation,
                            TeamMemberOutcomeKind.FAILED.value,
                            "Pane host already has a running member worker.",
                        ))
                else:
                    incoming.cancel()
                    await asyncio.gather(incoming, return_exceptions=True)
                await client.publish_result(active.result())
                active = None
                active_request = None
                continue

            try:
                command = incoming.result()
            except BaseException:
                active.cancel()
                await asyncio.gather(active, return_exceptions=True)
                raise
            if isinstance(command, ControlShutdownRequest):
                active.cancel()
                await asyncio.gather(active, return_exceptions=True)
                return True
            if isinstance(command, ControlCancelRequest):
                if (
                    active_request is not None
                    and command.run_id == active_request.run_id
                    and command.run_generation == active_request.run_generation
                ):
                    active.cancel()
                    await asyncio.gather(active, return_exceptions=True)
                    kind = (
                        TeamMemberOutcomeKind.STOPPED
                        if command.explicit_stop
                        else TeamMemberOutcomeKind.INTERRUPTED
                    )
                    await client.publish_result(ControlRunResult(
                        command.run_id,
                        command.run_generation,
                        kind.value,
                        "Pane host cancelled the member worker.",
                    ))
                    active = None
                    active_request = None
                continue
            await client.publish_result(ControlRunResult(
                command.run_id,
                command.run_generation,
                TeamMemberOutcomeKind.FAILED.value,
                "Pane host already has a running member worker.",
            ))
    finally:
        if active is not None and not active.done():
            active.cancel()
            await asyncio.gather(active, return_exceptions=True)


async def _run_worker_request(
    request: ControlRunRequest,
    descriptor,
    store: MemberRunDescriptorStore,
    child_waiter: ChildWaiter,
) -> ControlRunResult:
    run = MemberRunDescriptor(
        MEMBER_RUN_SCHEMA_VERSION,
        descriptor.team_id,
        descriptor.member_id,
        request.run_id,
        request.run_generation,
        request.reason,
        datetime.now(timezone.utc),
    )
    run_file = store.write_descriptor(run)
    code = await child_waiter((
        sys.executable,
        "-m",
        "mewcode",
        "--team-member-worker",
        "--run-file",
        str(run_file),
    ))
    try:
        result = store.read_result(descriptor.member_id, request.run_id)
        if (
            result.team_id != descriptor.team_id
            or result.member_id != descriptor.member_id
            or result.run_generation != request.run_generation
        ):
            raise TeamValidationError("Member worker result identity was rejected.")
        response = ControlRunResult(
            result.run_id,
            result.run_generation,
            result.outcome.kind.value,
            result.outcome.error,
            result.outcome.result_summary,
        )
    except Exception:
        response = ControlRunResult(
            request.run_id,
            request.run_generation,
            TeamMemberOutcomeKind.FAILED.value,
            "Managed member worker did not produce a valid result.",
        )
    if code != 0 and response.outcome == TeamMemberOutcomeKind.IDLE.value:
        return ControlRunResult(
            request.run_id,
            request.run_generation,
            TeamMemberOutcomeKind.FAILED.value,
            "Managed member worker exited unsuccessfully.",
        )
    return response


def _paths_for_control_file(path: Path) -> TeamPaths:
    candidate = Path(path)
    if not candidate.is_absolute() or candidate.parent.name != "members" or not candidate.name.endswith(".control.json"):
        raise TeamValidationError("Control descriptor path is invalid.")
    team_root = candidate.parent.parent
    if team_root.parent.name != "teams":
        raise TeamValidationError("Control descriptor path is invalid.")
    return TeamPaths.for_user(team_root.parent.parent, TeamNamePolicy().parse(team_root.name))
