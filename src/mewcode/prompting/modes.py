from __future__ import annotations

from xml.sax.saxutils import escape

from .models import PromptPhase, PromptRunContext


def uses_full_mode_reminder(iteration: int) -> bool:
    if iteration < 1:
        raise ValueError("iteration must be at least 1")
    return (iteration - 1) % 4 == 0


def wrap_system_reminder(content: str) -> str:
    return f"<system-reminder>\n{content}\n</system-reminder>"


def build_mode_reminder(
    context: PromptRunContext,
    mode: str,
    phase: PromptPhase,
    iteration: int,
) -> str:
    normalized_mode = str(mode).casefold()
    if normalized_mode == "direct":
        return ""
    if normalized_mode not in {"plan", "execute"}:
        raise ValueError(f"Unsupported prompt mode: {mode}")

    full = uses_full_mode_reminder(iteration)
    task = escape(context.task)
    approved_plan = escape(context.approved_plan or "")
    if normalized_mode == "plan":
        content = _plan_reminder(task, phase, full)
    else:
        content = _execute_reminder(task, approved_plan, full)
    return wrap_system_reminder(content)


def _plan_reminder(task: str, phase: PromptPhase, full: bool) -> str:
    if phase is PromptPhase.PLAN_FINALIZATION:
        if full:
            return "\n".join(
                (
                    "Mode: Plan finalization",
                    "Goal: Produce the complete implementation plan from the workspace evidence already gathered.",
                    "Allowed actions: Reason over the existing conversation and evidence.",
                    "Prohibited actions: Remain read-only. Do not modify the workspace. Do not call tools.",
                    "Completion condition: A concrete, self-contained plan with verification steps is ready.",
                    "Output requirements: Return only the final plan.",
                    f"Task: {task}",
                )
            )
        return "\n".join(
            (
                "Mode: Plan finalization",
                "Boundary: Read-only; do not call tools or modify the workspace.",
                "Continue: Output the complete final plan now.",
                f"Task: {task}",
            )
        )

    if full:
        return "\n".join(
            (
                "Mode: Plan",
                "Goal: Investigate the workspace and design a concrete implementation plan for the task.",
                "Allowed actions: Read files, find files, and search code using read-only tools.",
                "Prohibited actions: Do not write, edit, delete, run commands, or otherwise modify the workspace.",
                "Completion condition: The relevant evidence and implementation approach are understood.",
                "Output requirements: Continue investigating until ready for the separate finalization phase.",
                f"Task: {task}",
            )
        )
    return "\n".join(
        (
            "Mode: Plan",
            "Boundary: Read-only; use only read, find, and search tools.",
            "Continue: Gather the evidence needed to plan the task.",
            f"Task: {task}",
        )
    )


def _execute_reminder(task: str, approved_plan: str, full: bool) -> str:
    if full:
        return "\n".join(
            (
                "Mode: Execute",
                "Goal: Carry out the approved plan and verify the completed work.",
                "Allowed actions: Use the available tools for in-scope inspection, edits, commands, and verification.",
                "Prohibited actions: Do not expand scope, discard unrelated user changes, or claim unverified success.",
                "Completion condition: The approved plan is implemented and relevant verification has passed.",
                "Output requirements: Finish with a concise outcome and verification summary.",
                f"Original task: {task}",
                f"Approved plan: {approved_plan}",
            )
        )
    return "\n".join(
        (
            "Mode: Execute",
            "Boundary: Follow the approved plan and preserve unrelated user changes.",
            "Continue: Implement and verify the remaining plan steps.",
            f"Original task: {task}",
            f"Approved plan: {approved_plan}",
        )
    )
