from datetime import date

from mewcode.prompting import (
    SECTION_SPECS,
    PromptAdditions,
    PromptBuilder,
    PromptEnvironment,
    PromptEnvironmentProvider,
    PromptPackage,
    PromptPhase,
    PromptRunContext,
    PromptSectionSpec,
    PromptStability,
)


def _builder(tmp_path) -> PromptBuilder:
    provider = PromptEnvironmentProvider(
        tmp_path,
        clock=lambda: date(2026, 8, 9),
        operating_system=lambda: "Windows",
    )
    return PromptBuilder(provider)


def test_prompt_models_have_immutable_defaults() -> None:
    first = PromptRunContext("one")
    second = PromptRunContext("two")
    assert first.additions == PromptAdditions()
    assert first.additions is not second.additions
    assert PromptPhase.ACTIVE.value == "active"
    assert PromptStability.STABLE.value == "stable"
    assert PromptPackage("a", "b").stable_system == "a"
    assert PromptEnvironment("w", "o", "d", "s").shell == "s"
    assert PromptSectionSpec("k", "T", 1, PromptStability.DYNAMIC).priority == 1


def test_section_registry_has_approved_order_and_tool_rules() -> None:
    assert [(item.priority, item.key, item.stability) for item in SECTION_SPECS] == [
        (100, "identity", PromptStability.STABLE),
        (200, "system_constraints", PromptStability.STABLE),
        (300, "task_mode", PromptStability.STABLE),
        (400, "action_execution", PromptStability.STABLE),
        (500, "tool_use", PromptStability.STABLE),
        (600, "tone_style", PromptStability.STABLE),
        (700, "text_output", PromptStability.STABLE),
        (800, "environment", PromptStability.DYNAMIC),
        (900, "custom_instructions", PromptStability.DYNAMIC),
        (1000, "active_skill", PromptStability.DYNAMIC),
        (1100, "long_term_memory", PromptStability.DYNAMIC),
    ]


def test_stable_system_order_spacing_and_determinism(tmp_path) -> None:
    builder = _builder(tmp_path)
    first = builder.build(PromptRunContext("task"), "direct")
    second = builder.build(PromptRunContext("different"), "direct")
    headings = [
        "## Identity",
        "## System Constraints",
        "## Task Mode",
        "## Action Execution",
        "## Tool Use",
        "## Tone and Style",
        "## Text Output",
    ]
    assert [line for line in first.stable_system.splitlines() if line.startswith("## ")] == headings
    assert "\r" not in first.stable_system
    assert "\n\n\n" not in first.stable_system
    assert first.stable_system == second.stable_system
    assert "dedicated" in first.stable_system
    assert "Before editing or overwriting an existing file" in first.stable_system


def test_dynamic_system_optional_sections_and_stable_boundary(tmp_path) -> None:
    builder = _builder(tmp_path)
    base = builder.build(PromptRunContext("task"), "direct")
    additions = PromptAdditions(
        custom_instructions="custom",
        active_skill="skill",
        long_term_memory="memory",
    )
    full = builder.build(PromptRunContext("task", additions=additions), "execute")
    assert base.stable_system == full.stable_system
    assert [line for line in full.dynamic_system.splitlines() if line.startswith("## ")] == [
        "## Environment",
        "## Custom Instructions",
        "## Active Skill",
        "## Long-Term Memory",
    ]
    assert full.dynamic_system.index("custom") < full.dynamic_system.index("skill")
    assert full.dynamic_system.index("skill") < full.dynamic_system.index("memory")


def test_dynamic_system_omits_blank_optional_sections(tmp_path) -> None:
    package = _builder(tmp_path).build(
        PromptRunContext(
            "task",
            additions=PromptAdditions(custom_instructions=" \n", active_skill="skill"),
        ),
        "direct",
    )
    assert "## Custom Instructions" not in package.dynamic_system
    assert "## Active Skill\nskill" in package.dynamic_system
    assert "## Long-Term Memory" not in package.dynamic_system
