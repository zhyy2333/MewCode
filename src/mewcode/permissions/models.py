from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum

from mewcode.tools import PermissionTargetKind
from mewcode.matching import escape_exact_glob


class PermissionMode(StrEnum):
    STRICT = "strict"
    DEFAULT = "default"
    ALLOW = "allow"


class PermissionEffect(StrEnum):
    ALLOW = "allow"
    DENY = "deny"


class PermissionOutcome(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


class PermissionChoice(StrEnum):
    DENY = "deny"
    ONCE = "once"
    SESSION = "session"
    PERMANENT = "permanent"


class RuleScope(StrEnum):
    SESSION = "session"
    PROJECT_LOCAL = "project_local"
    PROJECT = "project"
    USER = "user"


class PermissionSource(StrEnum):
    BLACKLIST = "blacklist"
    SANDBOX = "sandbox"
    SESSION_RULE = "session_rule"
    PROJECT_LOCAL_RULE = "project_local_rule"
    PROJECT_RULE = "project_rule"
    USER_RULE = "user_rule"
    MODE = "mode"
    USER_CONFIRMATION = "user_confirmation"
    CONFIG_ERROR = "config_error"


def escape_exact_pattern(value: str) -> str:
    return escape_exact_glob(value)


@dataclass(frozen=True)
class PermissionTarget:
    tool_name: str
    value: str
    kind: PermissionTargetKind

    def exact_rule(self) -> str:
        return f"{self.tool_name}({escape_exact_pattern(self.value)})"


@dataclass(frozen=True)
class PermissionRule:
    tool_name: str
    pattern: str
    effect: PermissionEffect
    scope: RuleScope
    is_exact: bool
    specificity: tuple[int, int, int]

    @property
    def expression(self) -> str:
        return f"{self.tool_name}({self.pattern})"


@dataclass(frozen=True)
class PermissionRuleSets:
    session: tuple[PermissionRule, ...] = ()
    project_local: tuple[PermissionRule, ...] = ()
    project: tuple[PermissionRule, ...] = ()
    user: tuple[PermissionRule, ...] = ()


@dataclass(frozen=True)
class PermissionMatch:
    rule: PermissionRule
    source: PermissionSource


@dataclass(frozen=True)
class PermissionDecision:
    outcome: PermissionOutcome
    target: PermissionTarget | None
    source: PermissionSource
    reason: str
    match: PermissionMatch | None = None


class PermissionChallenge:
    def __init__(
        self,
        prompt_id: str,
        tool_call_id: str,
        tool_name: str,
        target: str,
    ) -> None:
        self.prompt_id = prompt_id
        self.tool_call_id = tool_call_id
        self.tool_name = tool_name
        self.target = target
        self._future: asyncio.Future[PermissionChoice] = (
            asyncio.get_running_loop().create_future()
        )

    def resolve(self, choice: PermissionChoice) -> None:
        if self._future.done():
            raise RuntimeError("Permission challenge has already been resolved.")
        self._future.set_result(choice)

    def cancel(self) -> None:
        if self._future.done():
            raise RuntimeError("Permission challenge has already been resolved.")
        self._future.cancel()

    async def wait(self) -> PermissionChoice:
        return await self._future
