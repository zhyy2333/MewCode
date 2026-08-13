from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

from mewcode import cli
from mewcode.config import ProfileCatalog, ProfileEntry
from mewcode.providers import ProviderProfile
from mewcode.subagents import AGENT_TOOL_SCHEMA, AgentDefinitionLayer
from mewcode.tools import ToolRegistry, Workspace, create_builtin_registry


def _profiles() -> ProfileCatalog:
    profile = ProviderProfile(
        "main",
        "openai",
        "model",
        "https://example.test",
        "secret",
    )
    return ProfileCatalog(
        "main",
        MappingProxyType({"main": ProfileEntry(profile, "OPENAI_API_KEY")}),
    )


def test_cli_catalog_helper_loads_builtin_and_injected_plugin_roots(
    tmp_path: Path,
) -> None:
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    (plugin / "plugin-reader.md").write_text(
        """---
name: plugin-reader
description: Read from an injected plugin role.
tools: [read_file]
disallowed_tools: []
model: inherit
max_turns: 4
permission_mode: default
---
Read only and report evidence.
""",
        encoding="utf-8",
    )
    workspace = Workspace(tmp_path)
    base = create_builtin_registry(workspace)

    catalog = cli._load_agent_catalog(
        workspace,
        _profiles(),
        base,
        plugin_roots=(plugin,),
    )

    assert catalog.definitions["explore"].source.layer is AgentDefinitionLayer.BUILTIN
    assert catalog.definitions["plugin-reader"].source.layer is AgentDefinitionLayer.PLUGIN


def test_root_tool_order_and_agent_schema_are_stable_without_roles(tmp_path: Path) -> None:
    from mewcode.subagents import AgentDefinitionCatalog, AgentTool, SubagentTaskManager

    class Coordinator:
        def prepare(self, arguments, context):
            raise AssertionError

    base = create_builtin_registry(Workspace(tmp_path))

    class Load:
        name = "load_skill"
        description = "load"
        parameters_schema = {"type": "object"}
        from mewcode.tools import ToolSafety, ToolPermissionSpec, PermissionTargetKind
        safety = ToolSafety.READ_ONLY
        permission_spec = ToolPermissionSpec(None, PermissionTargetKind.TOOL, "load_skill")

        async def execute(self, arguments):
            raise AssertionError

    agent = AgentTool(Coordinator(), SubagentTaskManager())
    root = base.merge(ToolRegistry([Load(), agent]))

    assert root.names == (*base.names, "load_skill", "agent")
    assert root.get("agent").parameters_schema is AGENT_TOOL_SCHEMA
    assert AgentDefinitionCatalog({}).definitions == {}
