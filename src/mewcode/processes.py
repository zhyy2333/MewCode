from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import os
from pathlib import Path
import signal
import subprocess
import time
from typing import Mapping


PROCESS_STOP_TIMEOUT_SECONDS = 1.0


@dataclass(frozen=True)
class ProcessRequest:
    command: str
    cwd: Path
    stdin: bytes = b""
    env: Mapping[str, str] | None = None
    timeout_seconds: float = 60
    stdout_limit: int = 64 * 1024
    stderr_limit: int = 64 * 1024


@dataclass(frozen=True)
class ProcessResult:
    exit_code: int
    stdout: bytes
    stderr: bytes
    duration_ms: int
    timed_out: bool = False
    stdout_exceeded: bool = False
    stderr_exceeded: bool = False

    @property
    def output_exceeded(self) -> bool:
        return self.stdout_exceeded or self.stderr_exceeded


class _OutputExceeded(Exception):
    def __init__(self, stream: str, data: bytes) -> None:
        super().__init__(stream)
        self.stream = stream
        self.data = data


async def run_shell(request: ProcessRequest) -> ProcessResult:
    if not request.command.strip():
        raise ValueError("command must not be empty")
    if request.timeout_seconds <= 0:
        raise ValueError("timeout must be positive")
    started = time.monotonic()
    process_options: dict[str, object]
    if os.name == "nt":
        process_options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    else:
        process_options = {"start_new_session": True}
    process = await asyncio.create_subprocess_shell(
        request.command,
        cwd=request.cwd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=dict(request.env) if request.env is not None else None,
        **process_options,
    )
    stdout_task = asyncio.create_task(
        _read_limited(process.stdout, request.stdout_limit, "stdout")
    )
    stderr_task = asyncio.create_task(
        _read_limited(process.stderr, request.stderr_limit, "stderr")
    )
    stdin_task = asyncio.create_task(_write_stdin(process, request.stdin))
    wait_task = asyncio.create_task(process.wait())
    timed_out = False
    exceeded: _OutputExceeded | None = None
    try:
        await asyncio.wait_for(
            asyncio.gather(stdin_task, stdout_task, stderr_task, wait_task),
            timeout=request.timeout_seconds,
        )
    except _OutputExceeded as exc:
        exceeded = exc
        await _stop_process(process)
    except TimeoutError:
        timed_out = True
        await _stop_process(process)
    except asyncio.CancelledError:
        await asyncio.shield(_stop_process(process))
        raise
    finally:
        for task in (stdin_task, stdout_task, stderr_task, wait_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(
            stdin_task, stdout_task, stderr_task, wait_task, return_exceptions=True
        )
        _close_process_transport(process)
        await asyncio.sleep(0)

    stdout = _task_bytes(stdout_task)
    stderr = _task_bytes(stderr_task)
    stdout_exceeded = exceeded is not None and exceeded.stream == "stdout"
    stderr_exceeded = exceeded is not None and exceeded.stream == "stderr"
    if stdout_exceeded:
        stdout = exceeded.data
    if stderr_exceeded:
        stderr = exceeded.data
    return ProcessResult(
        exit_code=process.returncode if process.returncode is not None else -1,
        stdout=stdout,
        stderr=stderr,
        duration_ms=max(0, round((time.monotonic() - started) * 1000)),
        timed_out=timed_out,
        stdout_exceeded=stdout_exceeded,
        stderr_exceeded=stderr_exceeded,
    )


async def _read_limited(
    reader: asyncio.StreamReader | None,
    limit: int,
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
        remaining = max(0, limit - size)
        if remaining:
            chunks.append(chunk[:remaining])
        size += len(chunk)
        if size > limit:
            raise _OutputExceeded(stream, b"".join(chunks))


async def _write_stdin(process: asyncio.subprocess.Process, value: bytes) -> None:
    if process.stdin is None:
        return
    try:
        if value:
            process.stdin.write(value)
            await process.stdin.drain()
    except (BrokenPipeError, ConnectionResetError):
        pass
    finally:
        process.stdin.close()


def _task_bytes(task: asyncio.Task[bytes]) -> bytes:
    if task.cancelled() or not task.done():
        return b""
    try:
        return task.result()
    except Exception:
        return b""


async def stop_process(process: asyncio.subprocess.Process) -> None:
    await _stop_process(process)


async def _stop_process(process: asyncio.subprocess.Process) -> None:
    try:
        if process.returncode is None:
            if os.name == "nt":
                await _stop_windows_process_tree(process.pid)
            else:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            try:
                await asyncio.wait_for(
                    process.wait(), timeout=PROCESS_STOP_TIMEOUT_SECONDS
                )
            except TimeoutError:
                if os.name == "nt":
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                else:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                await process.wait()
    finally:
        _close_process_transport(process)
        await asyncio.sleep(0)


async def _stop_windows_process_tree(pid: int) -> None:
    try:
        killer = await asyncio.create_subprocess_exec(
            "taskkill",
            "/PID",
            str(pid),
            "/T",
            "/F",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(
            killer.communicate(), timeout=PROCESS_STOP_TIMEOUT_SECONDS
        )
    except (OSError, TimeoutError):
        pass


def _close_process_transport(process: asyncio.subprocess.Process) -> None:
    transport = getattr(process, "_transport", None)
    if transport is not None:
        transport.close()
