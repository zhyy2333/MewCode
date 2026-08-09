from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .agent import AgentRunner, ToolScheduler
from .config import load_active_profile
from .conversation import Conversation
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
from .tools import Workspace, create_builtin_registry


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
    try:
        workspace = Workspace(Path.cwd())
        registry = create_builtin_registry(workspace)
        known_tools = {tool.name for tool in registry.list()}
        permission_paths = PermissionPaths.for_workspace(workspace)
        rule_sets = PermissionConfigLoader().load(permission_paths, known_tools)
        writer = PermissionConfigWriter(permission_paths.project_local, known_tools)
        rule_store = PermissionRuleStore(rule_sets, writer)
        permission_controller = PermissionController(
            PermissionTargetBuilder(workspace),
            rule_store,
            PermissionMode(arguments.permission_mode),
        )

        profile = load_active_profile()
        provider = create_provider(profile)
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
    except KeyboardInterrupt:
        sys.stderr.write("\n")
        return 130
