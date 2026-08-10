from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .agent import AgentRunner, ToolScheduler
from .config import load_active_profile
from .conversation import Conversation
from .mcp import McpConfigLoader, McpConfigPaths, McpDiagnostic, McpError, McpRuntime
from .permissions import (
    PermissionConfigError,
    PermissionConfigLoader,
    PermissionConfigWriter,
    PermissionController,
    PermissionMode,
    PermissionPaths,
    PermissionRuleStore,
    PermissionTargetBuilder,
)
from .prompting import PromptBuilder, PromptEnvironmentProvider
from .providers import ConfigError, ProviderError, create_provider
from .repl import Repl
from .tools import ToolRegistry, Workspace, create_builtin_registry


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mewcode")
    parser.add_argument(
        "--permission-mode",
        choices=[mode.value for mode in PermissionMode],
        default=PermissionMode.DEFAULT.value,
        help="permission safety ceiling (default: default)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _argument_parser().parse_args(argv)
    mcp_runtime: McpRuntime | None = None
    try:
        workspace = Workspace(Path.cwd())
        profile = load_active_profile()
        provider = create_provider(profile)

        builtin_registry = create_builtin_registry(workspace)
        builtin_tools = builtin_registry.list()
        config_result = McpConfigLoader().load(
            McpConfigPaths.for_workspace(workspace)
        )
        _write_mcp_diagnostics(config_result.diagnostics)
        mcp_tools = ()
        if config_result.servers:
            mcp_runtime = McpRuntime(workspace.root)
            runtime_result = mcp_runtime.start(
                config_result.servers,
                {tool.name for tool in builtin_tools},
            )
            mcp_tools = runtime_result.tools
            _write_mcp_diagnostics(runtime_result.diagnostics)
        registry = ToolRegistry([*builtin_tools, *mcp_tools])
        known_tools = {tool.name for tool in registry.list()}
        permission_paths = PermissionPaths.for_workspace(workspace)
        rule_sets = PermissionConfigLoader().load(
            permission_paths,
            known_tools,
            config_result.permission_prefixes,
        )
        writer = PermissionConfigWriter(
            permission_paths.project_local,
            known_tools,
            deferred_tool_prefixes=config_result.permission_prefixes,
        )
        rule_store = PermissionRuleStore(rule_sets, writer)
        permission_controller = PermissionController(
            PermissionTargetBuilder(workspace),
            rule_store,
            PermissionMode(arguments.permission_mode),
        )

        scheduler = ToolScheduler(permission_controller)
        prompt_builder = PromptBuilder(PromptEnvironmentProvider(workspace.root))
        agent_runner = AgentRunner(
            provider,
            scheduler,
            prompt_builder=prompt_builder,
        )
        conversation = Conversation(agent_runner, registry)
        return Repl(
            conversation, permission_controller=permission_controller
        ).run()
    except PermissionConfigError as exc:
        sys.stderr.write(f"Error: {exc}\n")
        return 1
    except (ConfigError, ProviderError) as exc:
        sys.stderr.write(f"Error: {exc.message}\n")
        return 1
    except McpError as exc:
        sys.stderr.write(
            f"Error: MCP server '{exc.server_name}' {exc.phase.value} failed: "
            f"{exc.safe_message}\n"
        )
        return 1
    except KeyboardInterrupt:
        sys.stderr.write("\n")
        return 130
    finally:
        if mcp_runtime is not None:
            try:
                _write_mcp_diagnostics(mcp_runtime.close())
            except Exception:
                sys.stderr.write("Warning: MCP runtime shutdown failed.\n")


def _write_mcp_diagnostics(diagnostics: tuple[McpDiagnostic, ...]) -> None:
    for diagnostic in diagnostics:
        server = diagnostic.server_name or "configuration"
        sys.stderr.write(
            f"Warning: MCP server '{server}' {diagnostic.phase.value} failed: "
            f"{diagnostic.message}\n"
        )
