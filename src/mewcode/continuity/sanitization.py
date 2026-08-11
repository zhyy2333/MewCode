from __future__ import annotations

from dataclasses import replace
import re

from .memory_models import MemoryTurn

REDACTED = "[REDACTED]"
_PRIVATE_KEY = re.compile(
    r"-----BEGIN [^-\r\n]*PRIVATE KEY-----.*?-----END [^-\r\n]*PRIVATE KEY-----",
    re.IGNORECASE | re.DOTALL,
)
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}")
_CREDENTIAL = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|secret|password)\b\s*[:=]\s*[^\s,;]{6,}"
)
_KNOWN_TOKEN = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16})\b"
)
_INTERNAL_BLOCK = re.compile(
    r"<(?:analysis|analysis_draft|internal|thinking)(?:\s[^>]*)?>.*?</(?:analysis|analysis_draft|internal|thinking)>",
    re.IGNORECASE | re.DOTALL,
)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_text(text: str, *, api_key: str | None = None) -> str:
    clean = _CONTROL.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))
    clean = _INTERNAL_BLOCK.sub("[INTERNAL CONTENT REMOVED]", clean)
    clean = _PRIVATE_KEY.sub(REDACTED, clean)
    clean = _BEARER.sub(REDACTED, clean)
    clean = _CREDENTIAL.sub(REDACTED, clean)
    clean = _KNOWN_TOKEN.sub(REDACTED, clean)
    if api_key and len(api_key) >= 6:
        clean = clean.replace(api_key, REDACTED)
    return clean


class MemoryTurnSanitizer:
    def __init__(self, *, max_bytes: int = 48 * 1024, api_key: str | None = None) -> None:
        if max_bytes < 1024:
            raise ValueError("memory turn budget is too small")
        self._max_bytes = max_bytes
        self._api_key = api_key

    def sanitize(self, turn: MemoryTurn) -> MemoryTurn:
        user = sanitize_text(turn.user_text, api_key=self._api_key)
        assistant = sanitize_text(turn.assistant_final_text, api_key=self._api_key)
        allowance = self._max_bytes - len(user.encode("utf-8"))
        if allowance < 0:
            user = _fit(user, self._max_bytes)
            assistant = "[assistant response omitted: memory input limit]"
        elif len(assistant.encode("utf-8")) > allowance:
            assistant = _fit(assistant, max(allowance, 0))
        return replace(turn, user_text=user, assistant_final_text=assistant)


def _fit(text: str, byte_budget: int) -> str:
    marker = "\n[content clipped for memory update]\n"
    if byte_budget <= len(marker.encode("utf-8")):
        return marker.encode("utf-8")[:byte_budget].decode("utf-8", "ignore")
    half = (byte_budget - len(marker.encode("utf-8"))) // 2
    raw = text.encode("utf-8")
    prefix = raw[:half].decode("utf-8", "ignore")
    suffix = raw[-half:].decode("utf-8", "ignore")
    return prefix + marker + suffix
