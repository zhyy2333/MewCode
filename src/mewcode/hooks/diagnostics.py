from __future__ import annotations

import json
from pathlib import Path
import threading
from urllib.parse import urlsplit, urlunsplit

from .models import DEFAULT_HOOK_LIMITS, HookDiagnostic, HookLimits


def safe_url(value: str) -> str:
    parts = urlsplit(value)
    host = parts.hostname or ""
    if parts.port:
        host += f":{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path, "", ""))


class HookDiagnosticLogger:
    def __init__(
        self,
        path: Path,
        *,
        limits: HookLimits = DEFAULT_HOOK_LIMITS,
        sensitive_values: tuple[str, ...] = (),
    ) -> None:
        self.path = Path(path)
        self._limits = limits
        self._sensitive_values = tuple(value for value in sensitive_values if value)
        self._lock = threading.Lock()

    def write(self, diagnostic: HookDiagnostic) -> None:
        try:
            summary = self._redact(diagnostic.summary)[: self._limits.summary_chars]
            payload = {
                "occurred_at": diagnostic.occurred_at.isoformat(),
                "event": diagnostic.event.value,
                "rule": {
                    "source": diagnostic.rule.source.value,
                    "path": str(diagnostic.rule.path),
                    "index": diagnostic.rule.index,
                },
                "action": diagnostic.action_type,
                "background": diagnostic.background,
                "outcome": diagnostic.outcome.value,
                "duration_ms": max(0, diagnostic.duration_ms),
                "summary": summary,
            }
            encoded = (
                json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
            ).encode("utf-8")
            if len(encoded) > 16 * 1024:
                payload["summary"] = "[truncated]"
                encoded = (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                if self.path.exists() and self.path.stat().st_size + len(encoded) > self._limits.log_bytes:
                    self._rotate()
                with self.path.open("ab") as handle:
                    handle.write(encoded)
                    handle.flush()
        except Exception:
            return

    def _rotate(self) -> None:
        for index in range(self._limits.log_backups, 0, -1):
            source = self.path if index == 1 else self.path.with_name(f"{self.path.name}.{index - 1}")
            target = self.path.with_name(f"{self.path.name}.{index}")
            if source.exists():
                source.replace(target)

    def _redact(self, value: str) -> str:
        cleaned = value.replace("\r", " ").replace("\n", " ")
        for secret in self._sensitive_values:
            cleaned = cleaned.replace(secret, "[redacted]")
        return cleaned
