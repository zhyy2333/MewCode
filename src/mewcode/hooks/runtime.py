from __future__ import annotations

import asyncio
from contextlib import contextmanager
import contextvars
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Iterator

from .actions import HookActionExecutor
from .conditions import HookConditionMatcher
from .diagnostics import HookDiagnosticLogger
from .events import make_event, serialize_event
from .models import (
    DEFAULT_HOOK_LIMITS,
    CommandHookAction,
    HookCatalog,
    HookDecision,
    HookDiagnostic,
    HookDispatchResult,
    HookEvent,
    HookEventContext,
    HookLimits,
    HookOutcomeKind,
    HookRule,
    HookSource,
    HttpHookAction,
    PromptHookAction,
    action_type,
)


_scope: contextvars.ContextVar[dict[str, object]] = contextvars.ContextVar(
    "mewcode_hook_scope", default={}
)


class HookRuntime:
    def __init__(
        self,
        catalog: HookCatalog,
        executor: HookActionExecutor,
        *,
        workspace: Path,
        session_id: str,
        resumed: bool = False,
        project_trusted: bool | None = None,
        matcher: HookConditionMatcher | None = None,
        diagnostics: HookDiagnosticLogger | None = None,
        limits: HookLimits = DEFAULT_HOOK_LIMITS,
    ) -> None:
        self.catalog = catalog
        self._executor = executor
        self.workspace = Path(workspace).resolve()
        self.session_id = session_id
        self.resumed = resumed
        self._project_trusted = project_trusted
        self._matcher = matcher or HookConditionMatcher(limits)
        self._diagnostics = diagnostics
        self._limits = limits
        self._dispatch_lock = asyncio.Lock()
        self._once: set[object] = set()
        self._prompts: list[str] = []
        self._task_prompts: dict[str, list[str]] = {}
        self._background: set[asyncio.Task[None]] = set()
        self._closed = False

    @classmethod
    def empty(
        cls,
        workspace: Path,
        session_id: str = "",
        *,
        resumed: bool = False,
    ) -> "HookRuntime":
        return cls(
            HookCatalog.empty(),
            HookActionExecutor(workspace),
            workspace=workspace,
            session_id=session_id,
            resumed=resumed,
            project_trusted=False,
        )

    @property
    def trust_required(self) -> bool:
        return self.catalog.requires_project_trust and self._project_trusted is None

    def resolve_project_trust(self, trusted: bool) -> tuple[HookDiagnostic, ...]:
        self._project_trusted = bool(trusted)
        return ()

    @property
    def scope(self) -> dict[str, object]:
        return dict(_scope.get())

    def update_scope(self, **values: object) -> None:
        current = dict(_scope.get())
        current.update({key: value for key, value in values.items() if value is not None})
        _scope.set(current)

    @contextmanager
    def bind_scope(self, **values: object) -> Iterator[None]:
        merged = dict(_scope.get())
        merged.update({key: value for key, value in values.items() if value is not None})
        token = _scope.set(merged)
        try:
            yield
        finally:
            _scope.reset(token)

    async def dispatch(self, event: HookEventContext) -> HookDispatchResult:
        if self._closed or not self.catalog.rules:
            return HookDispatchResult()
        event = self._with_task_scope(event)
        try:
            async with self._dispatch_lock:
                return await self._dispatch_locked(event)
        except asyncio.CancelledError:
            raise
        except Exception:
            return HookDispatchResult()

    async def _dispatch_locked(self, event: HookEventContext) -> HookDispatchResult:
        envelope = None
        for rule in self.catalog.by_event.get(event.event, ()):
            try:
                if not self._matcher.matches(rule.condition, event):
                    self._record(event, rule, HookOutcomeKind.NOT_MATCHED, "condition did not match")
                    continue
            except Exception:
                self._record(event, rule, HookOutcomeKind.FAILURE, "condition evaluation failed")
                continue
            if self._blocked_by_trust(rule):
                self._record(event, rule, HookOutcomeKind.SKIPPED, "project external action is not trusted")
                continue
            if rule.action.control.once:
                if rule.key in self._once:
                    self._record(event, rule, HookOutcomeKind.SKIPPED, "once rule already consumed")
                    continue
                self._once.add(rule.key)
            if isinstance(rule.action, PromptHookAction):
                if self._queue_prompt(rule.action.content):
                    self._record(event, rule, HookOutcomeKind.SUCCESS, "prompt queued")
                else:
                    self._record(event, rule, HookOutcomeKind.FAILURE, "prompt queue limit exceeded")
                continue
            if rule.action.control.background:
                if len(self._background) >= self._limits.background_tasks:
                    self._record(event, rule, HookOutcomeKind.FAILURE, "background task limit exceeded")
                    continue
                if envelope is None:
                    envelope = serialize_event(event, self._limits)
                task = asyncio.create_task(self._execute_background(rule, event, envelope))
                self._background.add(task)
                task.add_done_callback(self._background_done)
                continue
            if envelope is None:
                envelope = serialize_event(event, self._limits)
            try:
                outcome = await self._executor.execute(
                    rule,
                    envelope,
                    expects_decision=event.event is HookEvent.TOOL_BEFORE,
                )
            except asyncio.CancelledError:
                self._record(event, rule, HookOutcomeKind.CANCELLED, "action cancelled")
                raise
            except Exception:
                self._record(event, rule, HookOutcomeKind.FAILURE, "action execution failed")
                continue
            self._record(event, rule, outcome.kind, outcome.summary, outcome.duration_ms)
            if (
                event.event is HookEvent.TOOL_BEFORE
                and outcome.decision is not None
                and outcome.decision.deny
            ):
                return HookDispatchResult(outcome.decision)
        return HookDispatchResult()

    def _blocked_by_trust(self, rule: HookRule) -> bool:
        return (
            rule.key.source is HookSource.PROJECT
            and isinstance(rule.action, (CommandHookAction, HttpHookAction))
            and self._project_trusted is not True
        )

    def _queue_prompt(self, content: str) -> bool:
        current = sum(len(value.encode("utf-8")) for value in self._prompts)
        current += sum(
            len(value.encode("utf-8"))
            for prompts in self._task_prompts.values()
            for value in prompts
        )
        if current + len(content.encode("utf-8")) > self._limits.prompt_consume_bytes:
            return False
        task_id = _scope.get().get("subagent_task_id")
        if isinstance(task_id, str) and task_id:
            self._task_prompts.setdefault(task_id, []).append(content)
        else:
            self._prompts.append(content)
        return True

    def consume_prompt_context(
        self,
        task_id: str | None = None,
        *,
        preserve_fork_prefix: bool = False,
    ) -> tuple[str, ...]:
        if preserve_fork_prefix:
            return ()
        source = (
            self._prompts
            if task_id is None
            else self._task_prompts.setdefault(task_id, [])
        )
        prompts = tuple(source)
        source.clear()
        if task_id is not None:
            self._task_prompts.pop(task_id, None)
        return prompts

    def cleanup_task_prompts(self, task_id: str) -> None:
        self._task_prompts.pop(task_id, None)

    def _with_task_scope(self, event: HookEventContext) -> HookEventContext:
        scope = _scope.get()
        task_id = scope.get("subagent_task_id")
        parent_run_id = scope.get("parent_run_id")
        component = scope.get("component")
        if not any(value is not None for value in (task_id, parent_run_id)):
            return event
        values = dict(event.values)
        values["task"] = MappingProxyType(
            {
                "id": _bounded_identifier(task_id),
                "parent_run_id": _bounded_identifier(parent_run_id),
                "component": _bounded_identifier(component),
            }
        )
        return HookEventContext(
            event.event,
            event.occurred_at,
            MappingProxyType(values),
            event.match_kinds,
        )

    async def _execute_background(self, rule: HookRule, event: HookEventContext, envelope) -> None:
        try:
            outcome = await self._executor.execute(rule, envelope, expects_decision=False)
            self._record(event, rule, outcome.kind, outcome.summary, outcome.duration_ms)
        except asyncio.CancelledError:
            self._record(event, rule, HookOutcomeKind.CANCELLED, "background action cancelled")
            raise
        except Exception:
            self._record(event, rule, HookOutcomeKind.FAILURE, "background action failed")

    def _background_done(self, task: asyncio.Task[None]) -> None:
        self._background.discard(task)
        try:
            task.exception()
        except (asyncio.CancelledError, Exception):
            pass

    def _record(
        self,
        event: HookEventContext,
        rule: HookRule,
        outcome: HookOutcomeKind,
        summary: str,
        duration_ms: int = 0,
    ) -> None:
        if self._diagnostics is None:
            return
        self._diagnostics.write(
            HookDiagnostic(
                datetime.now(timezone.utc),
                event.event,
                rule.key,
                action_type(rule.action),
                rule.action.control.background,
                outcome,
                duration_ms,
                summary,
            )
        )

    async def system_error(self, component: str, error: BaseException) -> None:
        if self._closed or not self.catalog.by_event.get(HookEvent.SYSTEM_ERROR):
            return
        event = make_event(
            HookEvent.SYSTEM_ERROR,
            workspace=self.workspace,
            session_id=self.session_id,
            resumed=self.resumed,
            values={
                "error": {
                    "id": f"error-{id(error):x}",
                    "component": component,
                    "kind": type(error).__name__,
                    "message": str(error)[: self._limits.summary_chars],
                }
            },
        )
        await self.dispatch(event)

    async def close(self) -> tuple[HookDiagnostic, ...]:
        if self._closed:
            return ()
        self._closed = True
        self._prompts.clear()
        self._task_prompts.clear()
        if self._background:
            done, pending = await asyncio.wait(
                tuple(self._background), timeout=self._limits.close_timeout_seconds
            )
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
        self._background.clear()
        try:
            await self._executor.close()
        except Exception:
            pass
        return ()


def _bounded_identifier(value: object, limit: int = 128) -> str | None:
    if value is None:
        return None
    return str(value)[:limit]
