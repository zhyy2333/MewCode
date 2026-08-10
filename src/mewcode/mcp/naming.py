from __future__ import annotations

import hashlib
import re

_SAFE_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_INVALID_CHARACTER = re.compile(r"[^A-Za-z0-9_-]")
_HASH_LENGTH = 10
_PREFIX_LENGTH = 64 - _HASH_LENGTH - 1


def public_tool_name(server_name: str, original_name: str) -> str:
    base = f"{server_name}__{original_name}"
    if _SAFE_NAME.fullmatch(base):
        return base
    sanitized = _INVALID_CHARACTER.sub("_", base)
    digest = hashlib.sha256(base.encode("utf-8")).hexdigest()[:_HASH_LENGTH]
    return f"{sanitized[:_PREFIX_LENGTH]}_{digest}"


def permission_namespace_prefix(server_name: str) -> str:
    base = _INVALID_CHARACTER.sub("_", f"{server_name}__")
    return base[:_PREFIX_LENGTH]


def is_provider_safe_name(value: str) -> bool:
    return _SAFE_NAME.fullmatch(value) is not None

