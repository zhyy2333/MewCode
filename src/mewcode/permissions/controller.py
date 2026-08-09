from __future__ import annotations

from .models import (
    PermissionChoice,
    PermissionDecision,
    PermissionEffect,
    PermissionMode,
    PermissionOutcome,
    PermissionSource,
)
from .rules import PermissionRuleStore
from .targets import PermissionTargetBuilder
from mewcode.tools import ValidatedToolCall


class PermissionController:
    def __init__(
        self,
        target_builder: PermissionTargetBuilder,
        rule_store: PermissionRuleStore,
        mode: PermissionMode = PermissionMode.DEFAULT,
    ) -> None:
        self._target_builder = target_builder
        self._rule_store = rule_store
        self._mode = PermissionMode(mode)

    @property
    def mode(self) -> PermissionMode:
        return self._mode

    def set_mode(self, mode: PermissionMode) -> None:
        self._mode = PermissionMode(mode)

    def evaluate(self, call: ValidatedToolCall) -> PermissionDecision:
        built = self._target_builder.build(call)
        if isinstance(built, PermissionDecision):
            return built

        match = self._rule_store.match(built)
        if match is not None and match.rule.effect == PermissionEffect.DENY:
            return PermissionDecision(
                PermissionOutcome.DENY,
                built,
                match.source,
                "A permission rule denied this tool call.",
                match,
            )

        if match is not None and match.source == PermissionSource.SESSION_RULE:
            return PermissionDecision(
                PermissionOutcome.ALLOW,
                built,
                match.source,
                "Allowed by a session permission rule.",
                match,
            )

        if self._mode == PermissionMode.STRICT:
            return PermissionDecision(
                PermissionOutcome.ASK,
                built,
                PermissionSource.MODE,
                "Strict mode requires confirmation for this tool call.",
                match,
            )

        if self._mode == PermissionMode.DEFAULT:
            if match is not None:
                return PermissionDecision(
                    PermissionOutcome.ALLOW,
                    built,
                    match.source,
                    "Allowed by a permission rule.",
                    match,
                )
            return PermissionDecision(
                PermissionOutcome.ASK,
                built,
                PermissionSource.MODE,
                "No permission rule matched this tool call.",
            )

        return PermissionDecision(
            PermissionOutcome.ALLOW,
            built,
            match.source if match is not None else PermissionSource.MODE,
            "Allowed by the allow permission mode.",
            match,
        )

    async def apply_choice(
        self,
        decision: PermissionDecision,
        choice: PermissionChoice,
    ) -> PermissionDecision:
        if decision.outcome != PermissionOutcome.ASK or decision.target is None:
            raise ValueError("A user choice can only be applied to an ask decision.")
        choice = PermissionChoice(choice)
        if choice == PermissionChoice.DENY:
            return PermissionDecision(
                PermissionOutcome.DENY,
                decision.target,
                PermissionSource.USER_CONFIRMATION,
                "The user denied this tool call.",
                decision.match,
            )
        if choice == PermissionChoice.ONCE:
            return self._confirmed_allow(decision, "Allowed once by the user.")
        if choice == PermissionChoice.SESSION:
            self._rule_store.add_session_allow(decision.target)
            return self._confirmed_allow(decision, "Allowed for this session by the user.")

        try:
            await self._rule_store.persist_project_local_allow(decision.target)
        except Exception as exc:
            return PermissionDecision(
                PermissionOutcome.DENY,
                decision.target,
                PermissionSource.CONFIG_ERROR,
                f"Could not persist the project-local permission: {exc}",
                decision.match,
            )
        self._rule_store.add_session_allow(decision.target)
        return self._confirmed_allow(
            decision, "Allowed permanently for this project by the user."
        )

    @staticmethod
    def _confirmed_allow(
        decision: PermissionDecision, reason: str
    ) -> PermissionDecision:
        return PermissionDecision(
            PermissionOutcome.ALLOW,
            decision.target,
            PermissionSource.USER_CONFIRMATION,
            reason,
            decision.match,
        )
