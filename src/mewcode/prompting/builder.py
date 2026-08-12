from __future__ import annotations

from .environment import PromptEnvironmentProvider, render_environment
from .models import (
    PromptPackage,
    PromptPhase,
    PromptRunContext,
    PromptStability,
)
from .modes import build_mode_reminder
from .sections import SECTION_SPECS, STABLE_SECTION_CONTENT


class PromptBuilder:
    def __init__(self, environment_provider: PromptEnvironmentProvider) -> None:
        self._environment_provider = environment_provider

    def build(
        self,
        context: PromptRunContext,
        mode: str,
        phase: PromptPhase = PromptPhase.ACTIVE,
        iteration: int = 1,
    ) -> PromptPackage:
        stable_sections = [
            _render_section(spec.title, STABLE_SECTION_CONTENT[spec.key])
            for spec in sorted(SECTION_SPECS, key=lambda item: item.priority)
            if spec.stability is PromptStability.STABLE
        ]

        additions = context.additions
        dynamic_content = {
            "environment": render_environment(self._environment_provider.get()),
            "custom_instructions": additions.custom_instructions,
            "available_skills": additions.available_skills,
            "active_skills": _active_skills(additions),
            "long_term_memory": additions.long_term_memory,
        }
        dynamic_sections = [
            _render_section(spec.title, content)
            for spec in sorted(SECTION_SPECS, key=lambda item: item.priority)
            if spec.stability is PromptStability.DYNAMIC
            if (content := dynamic_content[spec.key]) is not None
            if content.strip()
        ]
        reminder = build_mode_reminder(context, mode, phase, iteration)
        if reminder:
            dynamic_sections.append(reminder)

        return PromptPackage(
            stable_system="\n\n".join(stable_sections),
            dynamic_system="\n\n".join(dynamic_sections),
        )


def _render_section(title: str, content: str) -> str:
    return f"## {title}\n{content}"


def _active_skills(additions) -> str | None:
    values = [
        value.strip()
        for value in (additions.active_skills, additions.active_skill)
        if value and value.strip()
    ]
    return "\n\n".join(values) or None
