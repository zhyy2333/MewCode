from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class PromptStability(StrEnum):
    STABLE = "stable"
    DYNAMIC = "dynamic"


@dataclass(frozen=True)
class PromptSectionSpec:
    key: str
    title: str
    priority: int
    stability: PromptStability


@dataclass(frozen=True)
class PromptEnvironment:
    workspace_root: str
    operating_system: str
    current_date: str
    shell: str


@dataclass(frozen=True)
class PromptAdditions:
    custom_instructions: str | None = None
    agent_role: str | None = None
    # Kept for callers compiled against the phase-9 singular field.
    active_skill: str | None = None
    long_term_memory: str | None = None
    available_skills: str | None = None
    active_skills: str | None = None

    def merged(
        self,
        *,
        custom_instructions: str | None = None,
        agent_role: str | None = None,
        available_skills: str | None = None,
        active_skills: str | None = None,
        active_skill: str | None = None,
        long_term_memory: str | None = None,
    ) -> PromptAdditions:
        return PromptAdditions(
            custom_instructions=_join(custom_instructions, self.custom_instructions),
            agent_role=_join(self.agent_role, agent_role),
            active_skill=None,
            long_term_memory=_join(self.long_term_memory, long_term_memory),
            available_skills=_join(self.available_skills, available_skills),
            active_skills=_join(
                _join(self.active_skills, self.active_skill),
                _join(active_skills, active_skill),
            ),
        )


@dataclass(frozen=True)
class PromptRunContext:
    task: str
    approved_plan: str | None = None
    additions: PromptAdditions = field(default_factory=PromptAdditions)


class PromptPhase(StrEnum):
    ACTIVE = "active"
    PLAN_FINALIZATION = "plan_finalization"


@dataclass(frozen=True)
class PromptPackage:
    stable_system: str
    dynamic_system: str


def _join(first: str | None, second: str | None) -> str | None:
    values = [value.strip() for value in (first, second) if value and value.strip()]
    return "\n\n".join(values) or None
