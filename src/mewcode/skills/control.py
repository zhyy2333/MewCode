from __future__ import annotations

from typing import Any

from mewcode.agent import AgentControlContext, AgentControlOperation
from mewcode.tools import (
    PermissionTargetKind,
    ToolPermissionSpec,
    ToolResult,
    ToolSafety,
)

from .execution import SkillCoordinator


class LoadSkillTool:
    name = "load_skill"
    description = "Load and run an available Skill by name."
    safety = ToolSafety.READ_ONLY
    permission_spec = ToolPermissionSpec(None, PermissionTargetKind.TOOL, default=name)
    parameters_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "input": {"type": "string"},
        },
        "required": ["name"],
        "additionalProperties": False,
    }

    def __init__(self, coordinator: SkillCoordinator) -> None:
        self._coordinator = coordinator

    def control_operation(
        self,
        arguments: dict[str, object],
        context: AgentControlContext | None,
    ) -> AgentControlOperation:
        name = arguments.get("name")
        input_text = arguments.get("input", "")
        return self._coordinator.invoke(
            name if isinstance(name, str) else "",
            input_text if isinstance(input_text, str) else "",
        )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(
            False,
            self.name,
            "",
            "load_skill must be executed by the Agent control scheduler.",
        )
