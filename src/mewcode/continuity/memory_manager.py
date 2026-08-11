from __future__ import annotations

import asyncio

from .diagnostics import (
    ContinuityComponent,
    ContinuityDiagnostic,
    DiagnosticSeverity,
)
from .memory_models import MemoryPromptView, MemoryTurn
from .memory_store import MemoryStore
from .memory_updater import MemoryUpdater


class MemoryManager:
    def __init__(self, store: MemoryStore, updater: MemoryUpdater) -> None:
        self._store = store
        self._updater = updater
        self._view = store.load_indexes()
        self._pending: asyncio.Task[None] | None = None
        self._diagnostics: list[ContinuityDiagnostic] = []

    def prompt_view(self) -> MemoryPromptView:
        return self._view

    def schedule(self, turn: MemoryTurn) -> None:
        if self._pending is not None:
            raise RuntimeError("A memory update is already pending.")
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
        except Exception:
            self._view = old_view
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

    def schedule(self, turn: MemoryTurn) -> None:
        return None

    async def await_pending(self) -> tuple[ContinuityDiagnostic, ...]:
        return ()

    async def close(self) -> tuple[ContinuityDiagnostic, ...]:
        return ()
