from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import MappingProxyType

from mewcode import cli
from mewcode.agent import AgentControlContext, AgentMode
from mewcode.config import ProfileCatalog, ProfileEntry
from mewcode.context import ContextConfig
from mewcode.permissions import (
    PermissionEffect,
    PermissionMode,
    PermissionRuleSets,
    PermissionRuleStore,
    RuleScope,
    parse_permission_rule,
)
from mewcode.prompting import PromptBuilder, PromptEnvironmentProvider, PromptPackage
from mewcode.providers import (
    ChatMessage,
    ModelRequest,
    ProviderProfile,
    ProviderTextDelta,
    ProviderToolCall,
    ProviderUsage,
    RequestBoundaryProvider,
    TokenUsage,
)
from mewcode.providers.anthropic_provider import AnthropicProvider
from mewcode.providers.openai_provider import OpenAIProvider
from mewcode.subagents import (
    AGENT_TOOL_SCHEMA,
    AgentDefinition,
    AgentDefinitionCatalog,
    AgentDefinitionLayer,
    AgentDefinitionSource,
    AgentTool,
    SubagentCoordinator,
    SubagentRuntimeFactory,
    SubagentTaskManager,
)
from mewcode.tools import ToolRegistry, ToolSafety, Workspace, create_builtin_registry
from tests.fakes import ControlledTool, ScriptedAsyncProvider, collect_async, tool_call
from tests.test_providers import install_fake_anthropic, install_fake_openai


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


def _fork_request_pair() -> tuple[ModelRequest, ModelRequest]:
    tools = ToolRegistry([ControlledTool("zeta"), ControlledTool("alpha")])
    prompt = PromptPackage(
        "stable parent instructions",
        "dynamic hook and <untrusted-subagent-results>notice</untrusted-subagent-results>",
    )
    messages = (
        ChatMessage("user", "old question"),
        ChatMessage("assistant", "old answer"),
    )
    parent = ModelRequest(prompt, messages, tools, 1777)
    fork = ModelRequest(
        prompt,
        messages + (ChatMessage("user", "new delegated task"),),
        tools,
        1777,
    )
    return parent, fork


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def test_defined_foreground_runs_actual_isolated_runtime_to_completion(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        calls: list[str] = []
        read = ControlledTool("read", calls=calls)
        parent_agent = ControlledTool("agent")
        parent_tools = ToolRegistry([read, parent_agent])
        inner = ScriptedAsyncProvider(
            [
                [
                    ProviderToolCall(tool_call("read-1", "read")),
                    ProviderUsage(TokenUsage(10, 2, 12)),
                ],
                [
                    ProviderTextDelta("review complete"),
                    ProviderUsage(TokenUsage(5, 3, 8)),
                ],
            ]
        )
        provider = RequestBoundaryProvider(inner)
        runtime_factory = SubagentRuntimeFactory(
            provider_supplier=lambda profile: provider,
            prompt_builder=PromptBuilder(PromptEnvironmentProvider(tmp_path)),
            workspace=Workspace(tmp_path),
            hook_runtime=None,
            context_config_factory=lambda profile: ContextConfig(128_000),
        )
        source = AgentDefinitionSource(
            AgentDefinitionLayer.PROJECT,
            tmp_path,
            tmp_path / "reviewer.md",
            "reviewer",
            "project",
        )
        definition = AgentDefinition(
            "reviewer",
            "Review read-only evidence.",
            ("read",),
            (),
            "inherit",
            4,
            PermissionMode.DEFAULT,
            "You are an independent read-only reviewer.",
            source,
        )

        class Writer:
            def add_local_allow(self, target):
                raise AssertionError("the child must not persist permission rules")

        allow_read = parse_permission_rule(
            "read(test)",
            PermissionEffect.ALLOW,
            RuleScope.PROJECT,
            {"read"},
        )
        rules = PermissionRuleStore(
            PermissionRuleSets(project=(allow_read,)),
            Writer(),
        )
        coordinator = SubagentCoordinator(
            AgentDefinitionCatalog({"reviewer": definition}),
            runtime_factory,
            parent_tools,
            rules,
            background_capable_names=parent_tools.names,
        )
        manager = SubagentTaskManager(id_factory=lambda: "defined-task")
        parent_request = ModelRequest(
            PromptPackage("stable parent", "dynamic parent"),
            (ChatMessage("user", "parent history must not leak"),),
            parent_tools,
            4096,
        )
        context = AgentControlContext(
            "parent-run",
            1,
            AgentMode.DIRECT,
            "main",
            PermissionMode.DEFAULT,
            20,
            frozenset({ToolSafety.READ_ONLY}),
            parent_request,
        )
        operation = AgentTool(coordinator, manager).control_operation(
            {"type": "defined", "task": "inspect the repository", "role": "reviewer"},
            context,
        )

        await collect_async(operation.events())
        result = operation.result

        assert result.ok and result.content == "review complete"
        assert result.metadata["usage"]["total_tokens"] == 20
        assert calls == ["read"]
        assert len(inner.calls) == 2
        assert inner.calls[0].messages == (
            ChatMessage("user", "inspect the repository"),
        )
        assert inner.calls[0].tools.names == ("read",)
        assert "independent read-only reviewer" in inner.calls[0].prompt.dynamic_system
        assert "parent history must not leak" not in inner.calls[0].prompt.dynamic_system
        await manager.close()

    asyncio.run(scenario())


def test_anthropic_fork_bytes_preserve_adapter_cache_prefix(monkeypatch) -> None:
    client_type = install_fake_anthropic(monkeypatch)
    provider = AnthropicProvider(
        ProviderProfile(
            "main",
            "anthropic",
            "claude-model",
            "https://api.anthropic.com/v1",
            "secret",
        )
    )
    client_type.created[0].events = [
        {
            "type": "message_start",
            "message": {
                "usage": {
                    "input_tokens": 12,
                    "cache_read_input_tokens": 9,
                    "cache_creation_input_tokens": 2,
                }
            },
        },
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {"output_tokens": 3},
        },
    ]
    parent, fork = _fork_request_pair()

    parent_events = asyncio.run(collect_async(provider.stream_reply(parent)))
    fork_events = asyncio.run(collect_async(provider.stream_reply(fork)))
    parent_payload, fork_payload = client_type.created[0].requests

    assert _json_bytes(parent_payload["system"]) == _json_bytes(fork_payload["system"])
    assert _json_bytes(parent_payload["tools"]) == _json_bytes(fork_payload["tools"])
    assert _json_bytes(parent_payload["messages"]) == _json_bytes(
        fork_payload["messages"][:-1]
    )
    assert fork_payload["messages"][-1] == {
        "role": "user",
        "content": "new delegated task",
    }
    assert parent_payload["system"][0]["cache_control"] == {"type": "ephemeral"}
    usage = ProviderUsage(TokenUsage(12, 3, 15, 9, 2, 23))
    assert usage in parent_events and usage in fork_events
    assert len(client_type.created[0].requests) == 2


def test_openai_fork_bytes_preserve_adapter_cache_prefix(monkeypatch) -> None:
    client_type = install_fake_openai(monkeypatch)
    provider = OpenAIProvider(
        ProviderProfile(
            "main",
            "openai",
            "gpt-5.6-terra",
            "https://api.openai.com/v1",
            "secret",
        )
    )
    parent, fork = _fork_request_pair()

    asyncio.run(collect_async(provider.stream_reply(parent)))
    asyncio.run(collect_async(provider.stream_reply(fork)))
    parent_payload, fork_payload = client_type.created[0].requests

    assert _json_bytes(parent_payload["input"]) == _json_bytes(
        fork_payload["input"][:-1]
    )
    assert fork_payload["input"][-1] == {
        "role": "user",
        "content": "new delegated task",
    }
    assert _json_bytes(parent_payload["tools"]) == _json_bytes(fork_payload["tools"])
    assert parent_payload["prompt_cache_key"] == fork_payload["prompt_cache_key"]
    assert parent_payload["prompt_cache_options"] == fork_payload["prompt_cache_options"]
    assert parent_payload["input"][0]["content"][0]["prompt_cache_breakpoint"] == {
        "mode": "explicit"
    }
    assert len(client_type.created[0].requests) == 2
