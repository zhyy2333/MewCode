from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
from typing import Any
import uuid

from mewcode.worktrees.paths import is_link_or_reparse

from .codec import decode_json, decode_model, encode_json
from .models import (
    PaneHealth,
    TeamCorruptionError,
    TeamMemberOutcomeKind,
    TeamValidationError,
    bounded_text,
    require_identifier,
    require_utc,
)
from .paths import TeamPaths


CONTROL_SCHEMA_VERSION = 1
CONTROL_MESSAGE_MAX_BYTES = 8192
_LOOPBACK_HOST = "127.0.0.1"


@dataclass(frozen=True)
class ControlEndpoint:
    host: str
    port: int

    def __post_init__(self) -> None:
        if self.host != _LOOPBACK_HOST:
            raise TeamValidationError("Team member control endpoint must use IPv4 loopback.")
        if not isinstance(self.port, int) or isinstance(self.port, bool) or not 1 <= self.port <= 65535:
            raise TeamValidationError("Team member control port is invalid.")


@dataclass(frozen=True)
class ControlDescriptor:
    schema_version: int
    team_id: str
    member_id: str
    host_id: str
    control_generation: int
    endpoint: ControlEndpoint
    token: str

    def __post_init__(self) -> None:
        if self.schema_version != CONTROL_SCHEMA_VERSION:
            raise TeamValidationError("Unsupported team control descriptor version.")
        for field in ("team_id", "member_id", "host_id"):
            require_identifier(getattr(self, field), field)
        if self.control_generation < 1:
            raise TeamValidationError("Control generation is invalid.")
        if not isinstance(self.token, str) or len(self.token) < 32 or len(self.token) > 256:
            raise TeamValidationError("Team control token is invalid.")
        if any(character.isspace() for character in self.token):
            raise TeamValidationError("Team control token is invalid.")


class ControlDescriptorStore:
    def __init__(self, paths: TeamPaths) -> None:
        self._paths = paths

    def write(self, descriptor: ControlDescriptor) -> Path:
        path = self._paths.member_control_file(descriptor.member_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() or path.is_symlink():
            self.read(path)
        temporary = path.with_suffix(path.suffix + ".tmp")
        try:
            with temporary.open("xb") as handle:
                try:
                    os.chmod(temporary, 0o600)
                except OSError:
                    pass
                handle.write(encode_json(descriptor))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return path

    def read(self, path: Path) -> ControlDescriptor:
        self._paths.validate_containment()
        candidate = Path(path)
        expected_root = self._paths.members_root
        try:
            if not candidate.is_absolute() or os.path.commonpath((str(candidate), str(expected_root))) != str(expected_root):
                raise TeamValidationError("Control descriptor path is outside the team member directory.")
        except ValueError as exc:
            raise TeamValidationError("Control descriptor path is outside the team member directory.") from exc
        if candidate.parent != expected_root or not candidate.name.endswith(".control.json"):
            raise TeamValidationError("Control descriptor path is invalid.")
        if is_link_or_reparse(candidate):
            raise TeamValidationError("Control descriptor must not be a link or reparse point.")
        try:
            payload = candidate.read_bytes()
        except OSError as exc:
            raise TeamCorruptionError("Team control descriptor is unavailable.") from exc
        return decode_model(ControlDescriptor, decode_json(payload))


@dataclass(frozen=True)
class HostRegistration:
    team_id: str
    member_id: str
    host_id: str
    control_generation: int
    registered_at: datetime

    def __post_init__(self) -> None:
        for field in ("team_id", "member_id", "host_id"):
            require_identifier(getattr(self, field), field)
        if self.control_generation < 1:
            raise TeamValidationError("Control generation is invalid.")
        object.__setattr__(self, "registered_at", require_utc(self.registered_at, "registered_at"))


@dataclass(frozen=True)
class ControlRunResult:
    run_id: str
    run_generation: int
    outcome: str
    diagnostic: str | None = None
    result_summary: str = ""

    def __post_init__(self) -> None:
        require_identifier(self.run_id, "run_id")
        if self.run_generation < 1:
            raise TeamValidationError("Run generation is invalid.")
        try:
            TeamMemberOutcomeKind(self.outcome)
        except ValueError as exc:
            raise TeamValidationError("Run outcome is invalid.") from exc
        object.__setattr__(self, "diagnostic", bounded_text(self.diagnostic))
        object.__setattr__(self, "result_summary", bounded_text(self.result_summary, 4096) or "")


@dataclass(frozen=True)
class ControlRunRequest:
    run_id: str
    run_generation: int
    reason: str

    def __post_init__(self) -> None:
        require_identifier(self.run_id, "run_id")
        if self.run_generation < 1:
            raise TeamValidationError("Run generation is invalid.")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise TeamValidationError("Run reason is invalid.")
        object.__setattr__(self, "reason", bounded_text(self.reason, 1024) or "")


@dataclass(frozen=True)
class ControlCancelRequest:
    run_id: str
    run_generation: int
    explicit_stop: bool = False

    def __post_init__(self) -> None:
        require_identifier(self.run_id, "run_id")
        if self.run_generation < 1:
            raise TeamValidationError("Run generation is invalid.")
        if not isinstance(self.explicit_stop, bool):
            raise TeamValidationError("Explicit stop flag is invalid.")


@dataclass(frozen=True)
class ControlProgress:
    run_id: str
    run_generation: int
    phase: str
    message: str

    def __post_init__(self) -> None:
        require_identifier(self.run_id, "run_id")
        if self.run_generation < 1:
            raise TeamValidationError("Run generation is invalid.")
        if not isinstance(self.phase, str) or not self.phase.strip():
            raise TeamValidationError("Progress phase is invalid.")
        object.__setattr__(self, "phase", bounded_text(self.phase, 128) or "")
        object.__setattr__(self, "message", bounded_text(self.message, 1024) or "")


@dataclass(frozen=True)
class ControlShutdownRequest:
    pass


class PaneHostConnection:
    def __init__(self, registration: HostRegistration) -> None:
        self.registration = registration
        self._requests: asyncio.Queue[ControlRunRequest] = asyncio.Queue()
        self._events: asyncio.Queue[ControlRunResult] = asyncio.Queue()
        self._progress: asyncio.Queue[ControlProgress] = asyncio.Queue()
        self._writer: asyncio.StreamWriter | None = None
        self._closed = False
        self._closed_event = asyncio.Event()

    @property
    def closed(self) -> bool:
        return self._closed

    async def publish_result(self, result: ControlRunResult) -> None:
        if self._closed:
            raise TeamValidationError("Pane host connection is closed.")
        await self._events.put(result)

    async def publish_progress(self, progress: ControlProgress) -> None:
        if self._closed:
            raise TeamValidationError("Pane host connection is closed.")
        await self._progress.put(progress)

    async def request_run(self, request: ControlRunRequest) -> None:
        if self._closed:
            raise TeamValidationError("Pane host connection is closed.")
        await self._requests.put(request)
        if self._writer is not None:
            message = _identity_message("run_request", self.registration)
            message.update({"run_id": request.run_id, "run_generation": request.run_generation, "reason": request.reason})
            await _write_message(self._writer, message)

    async def request_cancel(self, request: ControlCancelRequest) -> None:
        if self._closed:
            raise TeamValidationError("Pane host connection is closed.")
        if self._writer is None:
            await self._requests.put(request)
            return
        message = _identity_message("cancel_request", self.registration)
        message.update({
            "run_id": request.run_id,
            "run_generation": request.run_generation,
            "explicit_stop": request.explicit_stop,
        })
        await _write_message(self._writer, message)

    def attach_writer(self, writer: asyncio.StreamWriter) -> None:
        self._writer = writer

    async def next_request(self) -> ControlRunRequest | ControlCancelRequest:
        if self._closed and self._requests.empty():
            raise TeamValidationError("Pane host connection is closed.")
        return await self._requests.get()

    async def next_result(self) -> ControlRunResult:
        return await self._next_or_closed(self._events)

    async def next_progress(self) -> ControlProgress:
        return await self._next_or_closed(self._progress)

    async def _next_or_closed(self, queue):
        if self._closed and queue.empty():
            raise TeamValidationError("Pane host connection is closed.")
        item = asyncio.create_task(queue.get())
        closed = asyncio.create_task(self._closed_event.wait())
        done, pending = await asyncio.wait((item, closed), return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        if item in done:
            return item.result()
        raise TeamValidationError("Pane host connection is closed.")

    async def close(self) -> None:
        self._closed = True
        self._closed_event.set()
        if self._writer is not None:
            self._writer.close()

    async def shutdown_host(self) -> None:
        if self._closed:
            return
        if self._writer is not None:
            await _write_message(
                self._writer,
                _identity_message("shutdown", self.registration),
            )
        await self.close()


class MemberControlBroker:
    """Lead-owned loopback control authority; TeamState remains outside this class."""

    def __init__(
        self,
        *,
        paths: TeamPaths | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        new_id: Callable[[], str] = lambda: uuid.uuid4().hex,
        new_token: Callable[[], str] = lambda: secrets.token_urlsafe(32),
        listen: Callable[..., Awaitable[asyncio.AbstractServer]] = asyncio.start_server,
    ) -> None:
        self._now = now
        self._new_id = new_id
        self._new_token = new_token
        self._listen = listen
        self._descriptors = ControlDescriptorStore(paths) if paths is not None else None
        self._team_id: str | None = None
        self._generation = 0
        self._pending: set[tuple[str, str]] = set()
        self._tokens: dict[tuple[str, str], str] = {}
        self._registration_waiters: dict[tuple[str, str], asyncio.Future[PaneHostConnection]] = {}
        self._connections: dict[str, PaneHostConnection] = {}
        self._server: asyncio.AbstractServer | None = None
        self._endpoint: ControlEndpoint | None = None
        self._closed = True

    @property
    def generation(self) -> int:
        if self._closed:
            raise TeamValidationError("Member control broker is not open.")
        return self._generation

    async def open(self, team_id: str, *, control_generation: int | None = None) -> int:
        require_identifier(team_id, "team_id")
        await self.close()
        self._team_id = team_id
        if control_generation is None:
            self._generation += 1
        elif (
            not isinstance(control_generation, int)
            or isinstance(control_generation, bool)
            or control_generation < 1
        ):
            raise TeamValidationError("Control generation is invalid.")
        else:
            self._generation = control_generation
        self._closed = False
        if self._descriptors is not None:
            self._server = await self._listen(
                self._accept_stream,
                host=_LOOPBACK_HOST,
                port=0,
                limit=CONTROL_MESSAGE_MAX_BYTES,
            )
            sockets = self._server.sockets or ()
            if len(sockets) != 1:
                await self.close()
                raise TeamValidationError("Team member control endpoint is unavailable.")
            address = sockets[0].getsockname()
            self._endpoint = ControlEndpoint(_LOOPBACK_HOST, int(address[1]))
        return self._generation

    async def authorize_pending(self, member_id: str, host_id: str | None = None) -> str:
        if self._closed:
            raise TeamValidationError("Member control broker is not open.")
        require_identifier(member_id, "member_id")
        candidate = host_id or self._new_id()
        require_identifier(candidate, "host_id")
        self._pending.add((member_id, candidate))
        self._registration_waiters[(member_id, candidate)] = asyncio.get_running_loop().create_future()
        if self._descriptors is not None:
            if self._endpoint is None or self._team_id is None:
                raise TeamValidationError("Team member control endpoint is not open.")
            token = self._new_token()
            descriptor = ControlDescriptor(
                CONTROL_SCHEMA_VERSION, self._team_id, member_id, candidate,
                self._generation, self._endpoint, token,
            )
            self._descriptors.write(descriptor)
            self._tokens[(member_id, candidate)] = token
        return candidate

    async def wait_for_connection(self, member_id: str, host_id: str, *, timeout: float = 10.0) -> PaneHostConnection:
        key = (member_id, host_id)
        waiter = self._registration_waiters.get(key)
        if waiter is None:
            raise TeamValidationError("Pane host was not authorized for registration.")
        try:
            return await asyncio.wait_for(asyncio.shield(waiter), timeout)
        except asyncio.TimeoutError as exc:
            raise TeamValidationError("Pane host did not register before the provisioning timeout.") from exc

    def descriptor_path(self, member_id: str) -> Path:
        if self._descriptors is None:
            raise TeamValidationError("Team member control storage is not configured.")
        return self._descriptors._paths.member_control_file(member_id)

    def connection(self, member_id: str) -> PaneHostConnection | None:
        connection = self._connections.get(member_id)
        return connection if connection is not None and not connection.closed else None

    async def register(self, registration: HostRegistration) -> PaneHostConnection:
        if self._closed or registration.team_id != self._team_id:
            raise TeamValidationError("Pane host belongs to an inactive team control broker.")
        if registration.control_generation != self._generation:
            raise TeamValidationError("Pane host control generation is stale.")
        existing = self._connections.get(registration.member_id)
        if existing is not None and not existing.closed:
            raise TeamValidationError("A pane host is already connected for this member.")
        key = (registration.member_id, registration.host_id)
        if key not in self._pending:
            raise TeamValidationError("Pane host was not authorized for registration.")
        connection = PaneHostConnection(registration)
        self._connections[registration.member_id] = connection
        self._pending.discard(key)
        waiter = self._registration_waiters.pop(key, None)
        if waiter is not None and not waiter.done():
            waiter.set_result(connection)
        return connection

    async def _accept_stream(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        connection: PaneHostConnection | None = None
        registration: HostRegistration | None = None
        try:
            first = await _read_message(reader)
            if first["type"] != "host_register":
                raise TeamValidationError("Pane host must register before sending control messages.")
            registration = HostRegistration(
                _string_field(first, "team_id"), _string_field(first, "member_id"),
                _string_field(first, "host_id"), _int_field(first, "control_generation"), self._now(),
            )
            token = _string_field(first, "token")
            expected = self._tokens.get((registration.member_id, registration.host_id))
            if expected is None or not secrets.compare_digest(expected, token):
                raise TeamValidationError("Pane host control token was rejected.")
            connection = await self.register(registration)
            connection.attach_writer(writer)
            await _write_message(writer, _identity_message("host_registered", registration))
            while True:
                message = await _read_message(reader)
                _validate_identity(message, registration)
                if message["type"] == "heartbeat":
                    await _write_message(writer, _identity_message("heartbeat", registration))
                elif message["type"] == "run_result":
                    await connection.publish_result(ControlRunResult(
                        _string_field(message, "run_id"), _int_field(message, "run_generation"),
                        _string_field(message, "outcome"),
                        message.get("diagnostic") if isinstance(message.get("diagnostic"), str) else None,
                        message.get("result_summary") if isinstance(message.get("result_summary"), str) else "",
                    ))
                elif message["type"] == "progress":
                    await connection.publish_progress(ControlProgress(
                        _string_field(message, "run_id"),
                        _int_field(message, "run_generation"),
                        _string_field(message, "phase"),
                        _string_field(message, "message"),
                    ))
                elif message["type"] == "error":
                    raise TeamValidationError("Pane host reported a control error.")
                else:
                    raise TeamValidationError("Pane host sent an unsupported control message.")
        except (asyncio.IncompleteReadError, ConnectionError, TeamValidationError, TeamCorruptionError, ValueError):
            pass
        finally:
            if registration is not None:
                await self.disconnect(registration.member_id, registration.host_id)
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass

    def health(self, member_id: str) -> PaneHealth:
        connection = self._connections.get(member_id)
        return PaneHealth.CONNECTED if connection is not None and not connection.closed else PaneHealth.MISSING

    async def disconnect(self, member_id: str, host_id: str) -> None:
        connection = self._connections.get(member_id)
        if connection is not None and connection.registration.host_id == host_id:
            await connection.close()
            self._connections.pop(member_id, None)

    async def shutdown_host(self, host_id: str) -> None:
        for member_id, connection in tuple(self._connections.items()):
            if connection.registration.host_id != host_id:
                continue
            await connection.shutdown_host()
            self._connections.pop(member_id, None)
            return

    async def close(self) -> None:
        connections = tuple(self._connections.values())
        self._connections.clear()
        self._pending.clear()
        self._tokens.clear()
        waiters = tuple(self._registration_waiters.values())
        self._registration_waiters.clear()
        self._closed = True
        self._team_id = None
        self._endpoint = None
        server, self._server = self._server, None
        if server is not None:
            server.close()
            await server.wait_closed()
        for waiter in waiters:
            if not waiter.done():
                waiter.cancel()
        await asyncio.gather(*(connection.close() for connection in connections), return_exceptions=True)


def _identity_message(kind: str, registration: HostRegistration) -> dict[str, object]:
    return {
        "schema_version": CONTROL_SCHEMA_VERSION,
        "type": kind,
        "team_id": registration.team_id,
        "member_id": registration.member_id,
        "host_id": registration.host_id,
        "control_generation": registration.control_generation,
    }


def _string_field(message: Mapping[str, object], name: str) -> str:
    value = message.get(name)
    if not isinstance(value, str):
        raise TeamValidationError(f"Control message field {name} is invalid.")
    return value


def _int_field(message: Mapping[str, object], name: str) -> int:
    value = message.get(name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise TeamValidationError(f"Control message field {name} is invalid.")
    return value


def _validate_identity(message: Mapping[str, object], registration: HostRegistration) -> None:
    if (
        _string_field(message, "team_id") != registration.team_id
        or _string_field(message, "member_id") != registration.member_id
        or _string_field(message, "host_id") != registration.host_id
        or _int_field(message, "control_generation") != registration.control_generation
    ):
        raise TeamValidationError("Pane host control identity was rejected.")


async def _read_message(reader: asyncio.StreamReader) -> dict[str, object]:
    raw = await reader.readline()
    if not raw or len(raw) > CONTROL_MESSAGE_MAX_BYTES or not raw.endswith(b"\n"):
        raise TeamValidationError("Team control message is invalid.")
    value = decode_json(raw)
    if not isinstance(value, dict) or not isinstance(value.get("type"), str):
        raise TeamValidationError("Team control message is invalid.")
    _validate_message_shape(value)
    return value


_IDENTITY_FIELDS = {
    "schema_version", "type", "team_id", "member_id", "host_id", "control_generation",
}
_CONTROL_MESSAGE_FIELDS = {
    "host_register": _IDENTITY_FIELDS | {"token"},
    "host_registered": _IDENTITY_FIELDS,
    "heartbeat": _IDENTITY_FIELDS,
    "run_request": _IDENTITY_FIELDS | {"run_id", "run_generation", "reason"},
    "cancel_request": _IDENTITY_FIELDS | {"run_id", "run_generation", "explicit_stop"},
    "progress": _IDENTITY_FIELDS | {"run_id", "run_generation", "phase", "message"},
    "run_result": _IDENTITY_FIELDS | {"run_id", "run_generation", "outcome", "diagnostic", "result_summary"},
    "shutdown": _IDENTITY_FIELDS,
    "error": _IDENTITY_FIELDS | {"diagnostic"},
}
_OPTIONAL_CONTROL_FIELDS = {
    "run_result": {"diagnostic", "result_summary"},
    "error": {"diagnostic"},
}


def _validate_message_shape(message: Mapping[str, object]) -> None:
    kind = message.get("type")
    if not isinstance(kind, str) or kind not in _CONTROL_MESSAGE_FIELDS:
        raise TeamValidationError("Team control message type is unsupported.")
    if message.get("schema_version") != CONTROL_SCHEMA_VERSION:
        raise TeamValidationError("Team control message version is unsupported.")
    allowed = _CONTROL_MESSAGE_FIELDS[kind]
    unknown = set(message) - allowed
    if unknown:
        raise TeamValidationError("Team control message contains unknown fields.")
    missing = allowed - _OPTIONAL_CONTROL_FIELDS.get(kind, set()) - set(message)
    if missing:
        raise TeamValidationError("Team control message is missing required fields.")
    for field_name in ("team_id", "member_id", "host_id"):
        require_identifier(_string_field(message, field_name), field_name)
    generation = _int_field(message, "control_generation")
    if generation < 1:
        raise TeamValidationError("Control generation is invalid.")
    if kind in {"run_request", "cancel_request", "progress", "run_result"}:
        require_identifier(_string_field(message, "run_id"), "run_id")
        if _int_field(message, "run_generation") < 1:
            raise TeamValidationError("Run generation is invalid.")
    if kind == "cancel_request" and not isinstance(message.get("explicit_stop"), bool):
        raise TeamValidationError("Explicit stop flag is invalid.")
    if kind == "run_result":
        try:
            TeamMemberOutcomeKind(_string_field(message, "outcome"))
        except ValueError as exc:
            raise TeamValidationError("Run outcome is invalid.") from exc
    for field_name in ("reason", "phase", "message", "diagnostic", "result_summary", "token"):
        if field_name in message and not isinstance(message[field_name], str):
            raise TeamValidationError(f"Control message field {field_name} is invalid.")


async def _write_message(writer: asyncio.StreamWriter, message: Mapping[str, object]) -> None:
    payload = encode_json(dict(message))
    if len(payload) > CONTROL_MESSAGE_MAX_BYTES:
        raise TeamValidationError("Team control message is too large.")
    writer.write(payload)
    await writer.drain()


class TcpPaneHostClient:
    """Pane-process side of the local protocol; token is read only from disk."""

    def __init__(
        self,
        descriptor: ControlDescriptor,
        *,
        connect: Callable[..., Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]] = asyncio.open_connection,
    ) -> None:
        self._descriptor = descriptor
        self._connect = connect
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    async def open(self) -> None:
        reader, writer = await self._connect(self._descriptor.endpoint.host, self._descriptor.endpoint.port, limit=CONTROL_MESSAGE_MAX_BYTES)
        registration = HostRegistration(
            self._descriptor.team_id, self._descriptor.member_id, self._descriptor.host_id,
            self._descriptor.control_generation, datetime.now(timezone.utc),
        )
        message = _identity_message("host_register", registration)
        message["token"] = self._descriptor.token
        await _write_message(writer, message)
        response = await _read_message(reader)
        _validate_identity(response, registration)
        if response["type"] != "host_registered":
            writer.close()
            raise TeamValidationError("Pane host registration was rejected.")
        self._reader, self._writer = reader, writer

    async def next_request(
        self,
    ) -> ControlRunRequest | ControlCancelRequest | ControlShutdownRequest:
        reader = self._require_reader()
        message = await _read_message(reader)
        registration = self._registration()
        _validate_identity(message, registration)
        if message["type"] == "shutdown":
            return ControlShutdownRequest()
        if message["type"] == "cancel_request":
            return ControlCancelRequest(
                _string_field(message, "run_id"),
                _int_field(message, "run_generation"),
                bool(message["explicit_stop"]),
            )
        if message["type"] != "run_request":
            raise TeamValidationError("Pane host received an invalid control request.")
        return ControlRunRequest(
            _string_field(message, "run_id"), _int_field(message, "run_generation"), _string_field(message, "reason"),
        )

    async def publish_result(self, result: ControlRunResult) -> None:
        writer = self._require_writer()
        message = _identity_message("run_result", self._registration())
        message.update({"run_id": result.run_id, "run_generation": result.run_generation, "outcome": result.outcome})
        if result.diagnostic is not None:
            message["diagnostic"] = result.diagnostic
        if result.result_summary:
            message["result_summary"] = result.result_summary
        await _write_message(writer, message)

    async def publish_progress(self, progress: ControlProgress) -> None:
        writer = self._require_writer()
        message = _identity_message("progress", self._registration())
        message.update({
            "run_id": progress.run_id,
            "run_generation": progress.run_generation,
            "phase": progress.phase,
            "message": progress.message,
        })
        await _write_message(writer, message)

    async def close(self) -> None:
        if self._writer is not None:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except ConnectionError:
                pass
        self._reader = self._writer = None

    def _registration(self) -> HostRegistration:
        return HostRegistration(
            self._descriptor.team_id, self._descriptor.member_id, self._descriptor.host_id,
            self._descriptor.control_generation, datetime.now(timezone.utc),
        )

    def _require_reader(self) -> asyncio.StreamReader:
        if self._reader is None:
            raise TeamValidationError("Pane host control client is not open.")
        return self._reader

    def _require_writer(self) -> asyncio.StreamWriter:
        if self._writer is None:
            raise TeamValidationError("Pane host control client is not open.")
        return self._writer
