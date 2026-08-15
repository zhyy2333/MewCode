from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import time
from typing import Mapping

import httpx

from mewcode.processes import ProcessRequest, run_shell
from mewcode.tools.safety import check_dangerous_command

from .diagnostics import safe_url
from .models import (
    DEFAULT_HOOK_LIMITS,
    AgentHookAction,
    CommandHookAction,
    HookActionOutcome,
    HookDecision,
    HookLimits,
    HookOutcomeKind,
    HookRule,
    HttpHookAction,
    PromptHookAction,
    SerializedHookEnvelope,
)


class HookActionExecutor:
    def __init__(
        self,
        workspace: Path,
        *,
        http_client: httpx.AsyncClient | None = None,
        api_key_environment_names: tuple[str, ...] = (),
        limits: HookLimits = DEFAULT_HOOK_LIMITS,
        environment_overrides: Mapping[str, str] | None = None,
    ) -> None:
        self._workspace = Path(workspace).resolve()
        self._http_client = http_client
        self._owns_http_client = False
        self._api_key_environment_names = frozenset(api_key_environment_names)
        self._limits = limits
        self._environment_overrides = dict(environment_overrides or {})

    async def execute(
        self,
        rule: HookRule,
        envelope: SerializedHookEnvelope,
        *,
        expects_decision: bool,
    ) -> HookActionOutcome:
        started = time.monotonic()
        try:
            action = rule.action
            if isinstance(action, CommandHookAction):
                outcome = await self._command(action, envelope, expects_decision)
            elif isinstance(action, HttpHookAction):
                outcome = await self._http(action, envelope, expects_decision)
            elif isinstance(action, PromptHookAction):
                outcome = HookActionOutcome(HookOutcomeKind.SUCCESS, summary="prompt queued")
            elif isinstance(action, AgentHookAction):
                outcome = HookActionOutcome(
                    HookOutcomeKind.SKIPPED,
                    summary="agent action is a placeholder in this release",
                )
            else:  # pragma: no cover - frozen model union
                outcome = HookActionOutcome(HookOutcomeKind.FAILURE, summary="unknown action")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            outcome = HookActionOutcome(
                HookOutcomeKind.FAILURE,
                summary=f"{type(exc).__name__}: action failed",
            )
        return HookActionOutcome(
            kind=outcome.kind,
            decision=outcome.decision,
            summary=outcome.summary[: self._limits.summary_chars],
            duration_ms=max(0, round((time.monotonic() - started) * 1000)),
        )

    async def _command(
        self,
        action: CommandHookAction,
        envelope: SerializedHookEnvelope,
        expects_decision: bool,
    ) -> HookActionOutcome:
        dangerous = check_dangerous_command(action.command)
        if dangerous is not None:
            return HookActionOutcome(
                HookOutcomeKind.FAILURE,
                summary=f"command rejected by safety policy ({dangerous.category})",
            )
        environment = {
            key: value
            for key, value in os.environ.items()
            if key not in self._api_key_environment_names
        }
        environment.update(self._environment_overrides)
        result = await run_shell(
            ProcessRequest(
                command=action.command,
                cwd=self._workspace,
                stdin=envelope.encoded,
                env=environment,
                timeout_seconds=action.timeout_seconds,
                stdout_limit=self._limits.command_output_bytes,
                stderr_limit=self._limits.command_output_bytes,
            )
        )
        if result.timed_out:
            return HookActionOutcome(HookOutcomeKind.FAILURE, summary="command timed out")
        if result.output_exceeded:
            return HookActionOutcome(HookOutcomeKind.FAILURE, summary="command output limit exceeded")
        if result.exit_code != 0:
            return HookActionOutcome(
                HookOutcomeKind.FAILURE,
                summary=f"command exited with {result.exit_code}",
            )
        return self._success_from_body(result.stdout, expects_decision, "command completed")

    async def _http(
        self,
        action: HttpHookAction,
        envelope: SerializedHookEnvelope,
        expects_decision: bool,
    ) -> HookActionOutcome:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(follow_redirects=False)
            self._owns_http_client = True
        try:
            async with self._http_client.stream(
                action.method,
                action.url,
                headers=dict(action.headers),
                content=envelope.encoded,
                timeout=action.timeout_seconds,
                follow_redirects=False,
            ) as response:
                if not 200 <= response.status_code < 300:
                    return HookActionOutcome(
                        HookOutcomeKind.FAILURE,
                        summary=f"HTTP {response.status_code} from {safe_url(action.url)}",
                    )
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > self._limits.http_response_bytes:
                        return HookActionOutcome(
                            HookOutcomeKind.FAILURE,
                            summary=f"HTTP response limit exceeded from {safe_url(action.url)}",
                        )
                    chunks.append(chunk)
        except httpx.TimeoutException:
            return HookActionOutcome(HookOutcomeKind.FAILURE, summary="HTTP request timed out")
        except httpx.HTTPError as exc:
            return HookActionOutcome(
                HookOutcomeKind.FAILURE,
                summary=f"HTTP {type(exc).__name__} from {safe_url(action.url)}",
            )
        return self._success_from_body(
            b"".join(chunks), expects_decision, f"HTTP 2xx from {safe_url(action.url)}"
        )

    def _success_from_body(
        self,
        body: bytes,
        expects_decision: bool,
        summary: str,
    ) -> HookActionOutcome:
        if not expects_decision or not body:
            return HookActionOutcome(HookOutcomeKind.SUCCESS, summary=summary)
        try:
            value = json.loads(body.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError):
            return HookActionOutcome(HookOutcomeKind.FAILURE, summary="invalid decision JSON")
        if not isinstance(value, dict):
            return HookActionOutcome(HookOutcomeKind.FAILURE, summary="decision must be an object")
        decision = value.get("decision")
        if decision == "allow" and set(value) == {"decision"}:
            return HookActionOutcome(
                HookOutcomeKind.SUCCESS,
                decision=HookDecision(False),
                summary="tool allowed",
            )
        if decision == "deny" and set(value) == {"decision", "reason"}:
            reason = value.get("reason")
            if isinstance(reason, str) and 1 <= len(reason) <= self._limits.deny_reason_chars:
                return HookActionOutcome(
                    HookOutcomeKind.DENIED,
                    decision=HookDecision(True, reason),
                    summary="tool denied",
                )
        return HookActionOutcome(HookOutcomeKind.FAILURE, summary="invalid decision protocol")

    async def close(self) -> None:
        if self._owns_http_client and self._http_client is not None:
            await self._http_client.aclose()
        self._http_client = None


class NullHookActionExecutor(HookActionExecutor):
    def __init__(self, workspace: Path) -> None:
        super().__init__(workspace)
