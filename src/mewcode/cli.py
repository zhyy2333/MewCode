from __future__ import annotations

import sys
from pathlib import Path

from .agent import AgentRunner, ToolScheduler
from .config import load_active_profile
from .conversation import Conversation
from .providers import ConfigError, ProviderError, create_provider
from .repl import Repl
from .tools import Workspace, create_builtin_registry


def main(argv: list[str] | None = None) -> int:
    try:
        profile = load_active_profile()
        provider = create_provider(profile)
        workspace = Workspace(Path.cwd())
        registry = create_builtin_registry(workspace)
        scheduler = ToolScheduler()
        agent_runner = AgentRunner(provider, scheduler)
        conversation = Conversation(agent_runner, registry)
        return Repl(conversation).run()
    except (ConfigError, ProviderError) as exc:
        sys.stderr.write(f"Error: {exc.message}\n")
        return 1
    except KeyboardInterrupt:
        sys.stderr.write("\n")
        return 130
