from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Pattern


@dataclass(frozen=True)
class DangerousCommandMatch:
    category: str
    reason: str


_PATTERN_SPECS: tuple[tuple[str, str, str], ...] = (
    (
        "destructive_delete",
        r"\brm\s+(?:-[^\s]*[rf][^\s]*\s+)+(?:/|/\*|~|\$HOME|\$\{HOME\})(?:\s|$)",
        "destructive deletion of a root or home path",
    ),
    (
        "destructive_delete",
        r"\bdel\b(?=[^\r\n]*\/(?:s|q)\b)(?=[^\r\n]*(?:[a-z]:[\\/]|\\\\))",
        "recursive deletion of a drive or network path",
    ),
    (
        "destructive_delete",
        r"\b(?:rmdir|rd)\b(?=[^\r\n]*\/(?:s|q)\b)(?=[^\r\n]*(?:[a-z]:[\\/]|\\\\))",
        "recursive removal of a drive or network path",
    ),
    (
        "destructive_delete",
        r"\bremove-item\b(?=[^\r\n]*-(?:recurse|r)\b)(?=[^\r\n]*-(?:force|fo)\b)(?=[^\r\n]*(?:[a-z]:[\\/]|\\\\))",
        "forced recursive removal of a drive or network path",
    ),
    ("disk_format", r"\bformat(?:\.com)?\s+[a-z]:", "disk formatting"),
    ("disk_format", r"\bmkfs(?:\.[a-z0-9_+-]+)?\b", "filesystem creation"),
    ("disk_management", r"\bdiskpart\b", "interactive disk management"),
    (
        "disk_overwrite",
        r"\bdd\b(?=[^\r\n]*\bof=/dev/(?:sd|nvme|vd|hd)[a-z0-9]+)",
        "raw disk overwrite",
    ),
    (
        "system_power",
        r"(?:^|[;&|])\s*(?:(?:sudo|doas)\s+)?shutdown(?:\.exe)?\b",
        "system shutdown",
    ),
    (
        "system_power",
        r"(?:^|[;&|])\s*(?:(?:sudo|doas)\s+)?reboot(?:\.exe)?\b",
        "system reboot",
    ),
    (
        "permission_damage",
        r"\bchmod\b(?=[^\r\n]*(?:-R|--recursive))(?=[^\r\n]*\b777\b)",
        "recursive world-writable permission change",
    ),
    (
        "permission_damage",
        r"\bchown\b(?=[^\r\n]*(?:-R|--recursive))",
        "recursive ownership change",
    ),
)

_DANGEROUS_COMMAND_PATTERNS: tuple[tuple[str, Pattern[str], str], ...] = tuple(
    (category, re.compile(pattern, re.IGNORECASE), reason)
    for category, pattern, reason in _PATTERN_SPECS
)


def check_dangerous_command(command: str) -> DangerousCommandMatch | None:
    for category, pattern, reason in _DANGEROUS_COMMAND_PATTERNS:
        if pattern.search(command):
            return DangerousCommandMatch(category=category, reason=reason)
    return None
