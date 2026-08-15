from __future__ import annotations

from collections.abc import AsyncIterator

from mewcode.worktrees import WorktreeLifecycleService, WorktreeNameFactory

from .models import SubagentProgress, SubagentTaskStatus, WorktreeTaskSummary
from .tasks import SubagentDriverOutcome, SubagentLaunch
from .workspace_runtime import WorkspaceRuntimeBundle, WorkspaceRuntimeBundleFactory


class WorktreeSubagentDriver:
    def __init__(
        self,
        task_id: str,
        launch: SubagentLaunch,
        lifecycle: WorktreeLifecycleService,
        bundles: WorkspaceRuntimeBundleFactory,
        names: WorktreeNameFactory | None = None,
    ) -> None:
        self._task_id = task_id
        self._launch = launch
        self._lifecycle = lifecycle
        self._bundles = bundles
        self._names = names or WorktreeNameFactory()
        self._lease = None
        self._bundle: WorkspaceRuntimeBundle | None = None
        self._outcome: SubagentDriverOutcome | None = None
        self._closed = False
        self._cancelled = False

    async def prepare(self) -> None:
        name = self._names.for_task(self._task_id)
        environment = await self._lifecycle.create_or_recover(name, task_id=self._task_id)
        self._lease = await self._lifecycle.enter(environment, task_id=self._task_id)
        try:
            self._bundle = await self._bundles.create(
                self._lease,
                task_id=self._task_id,
                launch=self._launch,
            )
        except BaseException:
            await self._lifecycle.exit(self._lease)
            self._lease = None
            raise

    async def events(self) -> AsyncIterator[SubagentProgress]:
        if self._bundle is None:
            await self.prepare()
        assert self._bundle is not None
        async for progress in self._bundle.runtime.events():
            yield progress
        base = self._bundle.runtime.outcome
        self._outcome = SubagentDriverOutcome(base.status, base.result, base.error, base.usage)

    @property
    def outcome(self) -> SubagentDriverOutcome:
        if self._outcome is None:
            if self._cancelled:
                return SubagentDriverOutcome(SubagentTaskStatus.CANCELLED, error="Subagent task was cancelled.")
            raise RuntimeError("The Worktree subagent has not completed.")
        return self._outcome

    async def cancel(self) -> None:
        self._cancelled = True
        if self._bundle is not None:
            await self._bundle.runtime.cancel()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        bundle_error: BaseException | None = None
        if self._bundle is not None:
            try:
                await self._bundle.close()
            except BaseException as exc:
                bundle_error = exc
        if self._lease is not None:
            lease = self._lease
            try:
                result = await self._lifecycle.exit(lease)
                summary = WorktreeTaskSummary(
                    result.state.value,
                    str(result.path),
                    result.branch_ref,
                    result.retained_reason,
                )
            except BaseException as exc:
                summary = WorktreeTaskSummary(
                    "retained",
                    str(lease.environment.root),
                    lease.environment.branch_ref,
                    f"Worktree cleanup failed: {type(exc).__name__}.",
                )
                bundle_error = bundle_error or exc
            base = self._outcome or SubagentDriverOutcome(
                SubagentTaskStatus.CANCELLED if self._cancelled else SubagentTaskStatus.FAILED,
                error="Subagent runtime did not produce an outcome.",
            )
            self._outcome = SubagentDriverOutcome(
                SubagentTaskStatus.FAILED if bundle_error is not None else base.status,
                base.result,
                "Subagent runtime cleanup failed." if bundle_error is not None else base.error,
                base.usage,
                summary,
            )
            self._lease = None
