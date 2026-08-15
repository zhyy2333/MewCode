from __future__ import annotations

import asyncio

from .diagnostics import (
    ContinuityComponent,
    ContinuityDiagnostic,
    DiagnosticSeverity,
)
from .memory_models import (
    MemoryConfig,
    MemoryPromptView,
    MemoryRuntimeStatus,
    MemoryScope,
    MemoryTurn,
    MemoryUpdateState,
)
from .memory_store import MemoryStore
from .memory_store import build_prompt_view
from .memory_updater import MemoryUpdater


class MemoryManager:
    def __init__(self, store: MemoryStore, updater: MemoryUpdater) -> None:
        self._store = store
        self._updater = updater
        self._diagnostics: list[ContinuityDiagnostic] = []
        self._view = store.load_indexes()
        self._pending: asyncio.Task[None] | None = None
        self._update_state = (
            MemoryUpdateState.IDLE
            if store.write_enabled
            else MemoryUpdateState.DISABLED
        )
        if not store.write_enabled:
            self._diagnostics.append(
                ContinuityDiagnostic(
                    ContinuityComponent.MEMORY,
                    "memory_load_failed",
                    DiagnosticSeverity.WARNING,
                    "Automatic memory could not be loaded safely; updates are disabled.",
                )
            )

    def prompt_view(self) -> MemoryPromptView:
        return self._view

    def scope_prompt_view(self, scope: MemoryScope) -> MemoryPromptView:
        entries = tuple(item for item in self._store.catalog() if item.scope is scope)
        return build_prompt_view(
            entries if scope is MemoryScope.PROJECT else (),
            entries if scope is MemoryScope.USER else (),
            self._store.config,
        )

    def status(self) -> MemoryRuntimeStatus:
        catalog = self._store.catalog()
        config = self._store.config
        return MemoryRuntimeStatus(
            project_notes=sum(item.scope is MemoryScope.PROJECT for item in catalog),
            user_notes=sum(item.scope is MemoryScope.USER for item in catalog),
            index_lines=self._view.lines,
            index_bytes=self._view.bytes,
            max_index_lines=config.index_max_lines,
            max_index_bytes=config.index_max_bytes,
            update_state=self._update_state,
        )

    def schedule(self, turn: MemoryTurn) -> None:
        if not self._store.write_enabled:
            return
        if self._pending is not None:
            raise RuntimeError("A memory update is already pending.")
        self._update_state = MemoryUpdateState.RUNNING
        self._pending = asyncio.create_task(self._update(turn))

    async def await_pending(self) -> tuple[ContinuityDiagnostic, ...]:
        task = self._pending
        if task is not None:
            await task
            if self._pending is task:
                self._pending = None
        diagnostics = tuple(self._diagnostics)
        self._diagnostics.clear()
        return diagnostics

    async def close(self) -> tuple[ContinuityDiagnostic, ...]:
        return await self.await_pending()

    async def _update(self, turn: MemoryTurn) -> None:
        old_view = self._view
        try:
            plan = await self._updater.update(turn, self._store.catalog())
            if plan.mutations:
                self._store.apply(plan, turn)
            self._view = self._store.load_indexes()
            self._update_state = MemoryUpdateState.SUCCEEDED
        except Exception:
            self._view = old_view
            self._update_state = MemoryUpdateState.FAILED
            self._diagnostics.append(
                ContinuityDiagnostic(
                    ContinuityComponent.MEMORY,
                    "memory_update_failed",
                    DiagnosticSeverity.WARNING,
                    "Automatic memory could not be updated; the previous indexes were kept.",
                )
            )


class NullMemoryManager:
    def prompt_view(self) -> MemoryPromptView:
        return MemoryPromptView()

    def scope_prompt_view(self, scope: MemoryScope) -> MemoryPromptView:
        del scope
        return MemoryPromptView()

    def status(self) -> MemoryRuntimeStatus:
        config = MemoryConfig()
        return MemoryRuntimeStatus(
            0,
            0,
            0,
            0,
            config.index_max_lines,
            config.index_max_bytes,
            MemoryUpdateState.DISABLED,
        )

    def schedule(self, turn: MemoryTurn) -> None:
        return None

    async def await_pending(self) -> tuple[ContinuityDiagnostic, ...]:
        return ()

    async def close(self) -> tuple[ContinuityDiagnostic, ...]:
        return ()
