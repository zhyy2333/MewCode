from __future__ import annotations

from collections.abc import Mapping as AbcMapping
from dataclasses import fields, is_dataclass
from datetime import datetime
from enum import StrEnum
import json
import math
from pathlib import Path
from types import UnionType
from typing import Any, Mapping, TypeVar, Union, get_args, get_origin, get_type_hints

from .models import (
    MailboxMessageRecord,
    MailboxReadRecord,
    RepositoryBinding,
    TeamCorruptionError,
    TeamLeadLeaseRecord,
    TeamState,
    TerminalPaneBinding,
)


T = TypeVar("T")


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise TeamCorruptionError(f"Duplicate JSON field: {key}")
        result[key] = value
    return result


def decode_json(payload: bytes | str) -> object:
    try:
        value = json.loads(payload, object_pairs_hook=_pairs, parse_constant=_reject_constant)
    except TeamCorruptionError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise TeamCorruptionError("Persistent team JSON is invalid.") from exc
    _validate_json(value)
    return value


def encode_json(value: object) -> bytes:
    converted = _to_json(value)
    _validate_json(converted)
    return (
        json.dumps(converted, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _reject_constant(value: str) -> object:
    raise TeamCorruptionError(f"Invalid JSON numeric constant: {value}")


def _validate_json(value: object) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TeamCorruptionError("Persistent JSON contains a non-finite number.")
        return
    if isinstance(value, list):
        for item in value:
            _validate_json(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TeamCorruptionError("Persistent JSON object keys must be strings.")
            _validate_json(item)
        return
    raise TeamCorruptionError(f"Unsupported persistent JSON value: {type(value).__name__}")


def _to_json(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise TeamCorruptionError("Cannot encode a naive timestamp.")
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return {item.name: _to_json(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, AbcMapping):
        return {str(key): _to_json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, frozenset, set)):
        return [_to_json(item) for item in value]
    raise TeamCorruptionError(f"Unsupported persistent value: {type(value).__name__}")


def decode_model(model_type: type[T], value: object) -> T:
    return _decode_type(model_type, value, model_type.__name__)


def _decode_type(expected: object, value: object, field_name: str) -> Any:
    if expected in {Any, object}:
        _validate_json(value)
        return value
    if expected is type(None):
        if value is not None:
            raise TeamCorruptionError(f"{field_name} must be null.")
        return None
    origin = get_origin(expected)
    args = get_args(expected)
    if origin in {Union, UnionType}:
        errors: list[Exception] = []
        for candidate in args:
            try:
                return _decode_type(candidate, value, field_name)
            except (TeamCorruptionError, ValueError, TypeError) as exc:
                errors.append(exc)
        raise TeamCorruptionError(f"{field_name} has an invalid union value.") from errors[-1]
    if origin in {tuple}:
        if not isinstance(value, list):
            raise TeamCorruptionError(f"{field_name} must be an array.")
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(_decode_type(args[0], item, field_name) for item in value)
        if len(args) != len(value):
            raise TeamCorruptionError(f"{field_name} has an invalid tuple length.")
        return tuple(_decode_type(kind, item, field_name) for kind, item in zip(args, value, strict=True))
    if origin is frozenset:
        if not isinstance(value, list):
            raise TeamCorruptionError(f"{field_name} must be an array.")
        return frozenset(_decode_type(args[0], item, field_name) for item in value)
    if origin in {dict, Mapping, AbcMapping}:
        if not isinstance(value, dict):
            raise TeamCorruptionError(f"{field_name} must be an object.")
        key_type, item_type = args or (str, object)
        return {
            _decode_type(key_type, key, field_name): _decode_type(item_type, item, field_name)
            for key, item in value.items()
        }
    if expected is datetime:
        if not isinstance(value, str):
            raise TeamCorruptionError(f"{field_name} must be a timestamp.")
        try:
            result = datetime.fromisoformat(value)
        except ValueError as exc:
            raise TeamCorruptionError(f"{field_name} is not a valid timestamp.") from exc
        if result.tzinfo is None or result.utcoffset() is None:
            raise TeamCorruptionError(f"{field_name} timestamp must include a timezone.")
        return result
    if expected is Path:
        if not isinstance(value, str):
            raise TeamCorruptionError(f"{field_name} must be a path string.")
        return Path(value)
    if isinstance(expected, type) and issubclass(expected, StrEnum):
        if not isinstance(value, str):
            raise TeamCorruptionError(f"{field_name} must be an enum string.")
        try:
            return expected(value)
        except ValueError as exc:
            raise TeamCorruptionError(f"{field_name} contains an unknown enum value.") from exc
    if expected is bool:
        if type(value) is not bool:
            raise TeamCorruptionError(f"{field_name} must be a boolean.")
        return value
    if expected is int:
        if type(value) is not int:
            raise TeamCorruptionError(f"{field_name} must be an integer.")
        return value
    if expected is float:
        if type(value) not in {int, float} or isinstance(value, bool) or not math.isfinite(float(value)):
            raise TeamCorruptionError(f"{field_name} must be a finite number.")
        return float(value)
    if expected is str:
        if not isinstance(value, str):
            raise TeamCorruptionError(f"{field_name} must be a string.")
        return value
    if isinstance(expected, type) and is_dataclass(expected):
        if not isinstance(value, dict):
            raise TeamCorruptionError(f"{field_name} must be an object.")
        hints = get_type_hints(expected)
        expected_fields = {item.name: item for item in fields(expected)}
        unknown = set(value) - set(expected_fields)
        if unknown:
            raise TeamCorruptionError(f"{field_name} contains unknown fields: {', '.join(sorted(unknown))}")
        from dataclasses import MISSING
        required = {
            name for name, item in expected_fields.items()
            if item.default is MISSING and item.default_factory is MISSING
        }
        missing = required - set(value)
        if missing:
            raise TeamCorruptionError(f"{field_name} is missing fields: {', '.join(sorted(missing))}")
        kwargs = {
            name: _decode_type(hints[name], item, f"{field_name}.{name}")
            for name, item in value.items()
        }
        try:
            return expected(**kwargs)
        except (TypeError, ValueError) as exc:
            raise TeamCorruptionError(f"{field_name} failed model validation.") from exc
    raise TeamCorruptionError(f"Unsupported model type for {field_name}: {expected!r}")


def encode_team_state(state: TeamState) -> bytes:
    return encode_json(state)


def decode_team_state(payload: bytes | str) -> TeamState:
    return decode_model(TeamState, decode_json(payload))


def encode_terminal_pane_binding(binding: TerminalPaneBinding) -> bytes:
    return encode_json(binding)


def decode_terminal_pane_binding(payload: bytes | str) -> TerminalPaneBinding:
    return decode_model(TerminalPaneBinding, decode_json(payload))


def encode_control_descriptor(descriptor: object) -> bytes:
    from .control import ControlDescriptor

    if not isinstance(descriptor, ControlDescriptor):
        raise TeamCorruptionError("Control descriptor model is invalid.")
    return encode_json(descriptor)


def decode_control_descriptor(payload: bytes | str) -> object:
    from .control import ControlDescriptor

    return decode_model(ControlDescriptor, decode_json(payload))


def encode_member_run_record(record: object) -> bytes:
    from .member_worker import MemberRunDescriptor, MemberRunResult

    if not isinstance(record, (MemberRunDescriptor, MemberRunResult)):
        raise TeamCorruptionError("Member run record model is invalid.")
    return encode_json(record)


def decode_member_run_descriptor(payload: bytes | str) -> object:
    from .member_worker import MemberRunDescriptor

    return decode_model(MemberRunDescriptor, decode_json(payload))


def decode_member_run_result(payload: bytes | str) -> object:
    from .member_worker import MemberRunResult

    return decode_model(MemberRunResult, decode_json(payload))


def encode_lead_lease(record: TeamLeadLeaseRecord) -> bytes:
    return encode_json(record)


def decode_lead_lease(payload: bytes | str) -> TeamLeadLeaseRecord:
    return decode_model(TeamLeadLeaseRecord, decode_json(payload))


def encode_repository_binding(binding: RepositoryBinding) -> bytes:
    return encode_json(binding)


def decode_repository_binding(payload: bytes | str) -> RepositoryBinding:
    return decode_model(RepositoryBinding, decode_json(payload))


def encode_mailbox_record(record: MailboxMessageRecord | MailboxReadRecord) -> bytes:
    kind = "message" if isinstance(record, MailboxMessageRecord) else "read"
    return encode_json({"record_type": kind, "value": _to_json(record)})


def decode_mailbox_record(payload: bytes | str) -> MailboxMessageRecord | MailboxReadRecord:
    value = decode_json(payload)
    if not isinstance(value, dict) or set(value) != {"record_type", "value"}:
        raise TeamCorruptionError("Mailbox record fields are invalid.")
    if value["record_type"] == "message":
        return decode_model(MailboxMessageRecord, value["value"])
    if value["record_type"] == "read":
        return decode_model(MailboxReadRecord, value["value"])
    raise TeamCorruptionError("Mailbox record type is unknown.")


def encode_coordinator_settings(value: object) -> bytes:
    from .coordinator_models import CoordinatorSettings

    if not isinstance(value, CoordinatorSettings):
        raise TeamCorruptionError("Coordinator settings model is invalid.")
    return encode_json(value)


def decode_coordinator_settings(payload: bytes | str) -> object:
    from .coordinator_models import CoordinatorSettings

    return decode_model(CoordinatorSettings, decode_json(payload))


def encode_decomposition_run(value: object) -> bytes:
    from .coordinator_models import DecompositionRun

    if not isinstance(value, DecompositionRun):
        raise TeamCorruptionError("Decomposition run model is invalid.")
    return encode_json(value)


def decode_decomposition_run(payload: bytes | str) -> object:
    from .coordinator_models import DecompositionRun

    return decode_model(DecompositionRun, decode_json(payload))


def encode_integration_batch(value: object) -> bytes:
    from .coordinator_models import IntegrationBatch

    if not isinstance(value, IntegrationBatch):
        raise TeamCorruptionError("Integration batch model is invalid.")
    return encode_json(value)


def decode_integration_batch(payload: bytes | str) -> object:
    from .coordinator_models import IntegrationBatch

    return decode_model(IntegrationBatch, decode_json(payload))


def encode_integration_step(value: object) -> bytes:
    from .coordinator_models import IntegrationStep

    if not isinstance(value, IntegrationStep):
        raise TeamCorruptionError("Integration step model is invalid.")
    return encode_json(value)


def decode_integration_step(payload: bytes | str) -> object:
    from .coordinator_models import IntegrationStep

    return decode_model(IntegrationStep, decode_json(payload))


def encode_coordinator_journal(value: object) -> bytes:
    from .coordinator_models import CoordinatorJournal

    if not isinstance(value, CoordinatorJournal):
        raise TeamCorruptionError("Coordinator journal model is invalid.")
    return encode_json(value)


def decode_coordinator_journal(payload: bytes | str) -> object:
    from .coordinator_models import CoordinatorJournal

    return decode_model(CoordinatorJournal, decode_json(payload))
