from __future__ import annotations

from mewcode.permissions import (
    PermissionChoice,
    PermissionController,
    PermissionDecision,
    PermissionMode,
    PermissionOutcome,
    PermissionPreflight,
    PermissionRuleSets,
    PermissionRuleStore,
    PermissionSource,
    PermissionTargetBuilder,
)
from mewcode.tools import ValidatedToolCall, Workspace


class _NoPersistentWriter:
    def add_local_allow(self, target):
        raise RuntimeError("Subagent permission rules cannot be persisted.")


def persistent_permission_snapshot(rule_sets: PermissionRuleSets) -> PermissionRuleSets:
    return PermissionRuleSets(
        session=(),
        project_local=tuple(rule for rule in rule_sets.project_local),
        project=tuple(rule for rule in rule_sets.project),
        user=tuple(rule for rule in rule_sets.user),
    )


class SubagentPermissionController:
    def __init__(self, controller: PermissionController) -> None:
        self._controller = controller

    @classmethod
    def from_parent(
        cls,
        workspace: Workspace,
        parent_store: PermissionRuleStore,
        mode: PermissionMode,
    ) -> SubagentPermissionController:
        snapshot = persistent_permission_snapshot(parent_store.snapshot())
        store = PermissionRuleStore(snapshot, _NoPersistentWriter())
        return cls(PermissionController(PermissionTargetBuilder(workspace), store, mode))

    @property
    def mode(self) -> PermissionMode:
        return self._controller.mode

    def evaluate(self, call: ValidatedToolCall) -> PermissionDecision:
        prepared = self.preflight(call)
        if isinstance(prepared, PermissionDecision):
            return prepared
        return self.evaluate_preflight(prepared)

    def preflight(
        self,
        call: ValidatedToolCall,
    ) -> PermissionPreflight | PermissionDecision:
        return self._controller.preflight(call)

    def evaluate_preflight(
        self,
        preflight: PermissionPreflight,
    ) -> PermissionDecision:
        decision = self._controller.evaluate_preflight(preflight)
        if decision.outcome is not PermissionOutcome.ASK:
            return decision
        return PermissionDecision(
            PermissionOutcome.DENY,
            decision.target,
            PermissionSource.SUBAGENT_NON_INTERACTIVE,
            "Subagents run non-interactively; confirmation-required tool calls are denied.",
            decision.match,
        )

    async def apply_choice(
        self,
        decision: PermissionDecision,
        choice: PermissionChoice,
    ) -> PermissionDecision:
        raise RuntimeError("Subagent permission decisions never request user input.")
