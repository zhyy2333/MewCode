from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from .agent import AgentRunner, ToolScheduler
from .config import load_active_profile
from .context import ContextArchive, ContextConfig, ContextError, ContextManager
from .conversation import Conversation
from .continuity import (
    ContinuityPaths,
    InstructionLoader,
    MemoryError,
    MemoryManager,
    MemoryStore,
    MemoryUpdater,
    SessionBinding,
    SessionError,
    SessionOpenMode,
    SessionOpenRequest,
    SessionRepository,
)
from .continuity.session_codec import session_title
from .continuity.sanitization import MemoryTurnSanitizer
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
    sessions = parser.add_mutually_exclusive_group()
    sessions.add_argument(
        "--new",
        action="store_true",
        help="start a new session instead of restoring the most recent one",
    )
    sessions.add_argument(
        "--resume",
        metavar="ID",
        help="resume a specific session ID",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _argument_parser().parse_args(argv)
    mcp_runtime: McpRuntime | None = None
    context_archive: ContextArchive | None = None
    session_binding: SessionBinding | None = None
    memory_manager: MemoryManager | None = None
    try:
        workspace = Workspace(Path.cwd())
        profile = load_active_profile()
        provider = create_provider(profile)
        continuity_paths = ContinuityPaths.for_workspace(workspace.root)
        instructions = InstructionLoader().load(continuity_paths)
        session_repository = SessionRepository(continuity_paths)
        maintenance_diagnostics = session_repository.maintain()
        session_request = (
            SessionOpenRequest(SessionOpenMode.NEW)
            if arguments.new
            else SessionOpenRequest(SessionOpenMode.RESUME, arguments.resume)
            if arguments.resume
            else SessionOpenRequest()
        )
        opened_session = session_repository.open(session_request)
        session_binding = opened_session.binding
        memory_manager = MemoryManager(
            MemoryStore(continuity_paths, api_key=profile.api_key),
            MemoryUpdater(
                provider,
                sanitizer=MemoryTurnSanitizer(api_key=profile.api_key),
            ),
        )
        context_archive = ContextArchive(workspace.root)
        _write_context_diagnostics(context_archive.start())
        context_manager = ContextManager(
            provider,
            context_archive,
            ContextConfig(profile.context_window),
        )

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
            context_manager=context_manager,
        )
        conversation = Conversation(
            agent_runner,
            registry,
            context_manager=context_manager,
            initial_state=opened_session.state,
            session=opened_session.binding,
            instructions=instructions,
            memory=memory_manager,
        )
        action = "resumed" if opened_session.resumed else "created"
        title = session_title(
            opened_session.state.messages,
            opened_session.state.session_id if opened_session.resumed else "New session",
        )
        startup_messages = [
            "instructions: loaded" if instructions.content else "instructions: none",
            f"session: {action} {opened_session.state.session_id} - {title}",
            f"memory: loaded {len(memory_manager.prompt_view().included_note_ids)} note(s)",
        ]
        startup_messages.extend(
            f"{diagnostic.component.value}: {diagnostic.message}"
            for diagnostic in (
                *instructions.diagnostics,
                *maintenance_diagnostics,
                *opened_session.diagnostics,
            )
            if diagnostic.code not in {"created", "resumed"}
        )
        return Repl(
            conversation,
            permission_controller=permission_controller,
            startup_messages=tuple(startup_messages),
        ).run()
    except PermissionConfigError as exc:
        sys.stderr.write(f"Error: {exc}\n")
        return 1
    except (ConfigError, ProviderError) as exc:
        sys.stderr.write(f"Error: {exc.message}\n")
        return 1
    except ContextError as exc:
        sys.stderr.write(f"Error: {exc}\n")
        return 1
    except (SessionError, MemoryError) as exc:
        sys.stderr.write(f"Error: {exc}\n")
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
        if memory_manager is not None:
            try:
                for diagnostic in asyncio.run(memory_manager.close()):
                    sys.stderr.write(f"Warning: {diagnostic.message}\n")
            except Exception:
                sys.stderr.write("Warning: automatic memory shutdown failed.\n")
        if session_binding is not None:
            session_binding.close()
        if context_archive is not None:
            _write_context_diagnostics(context_archive.close())
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


def _write_context_diagnostics(diagnostics) -> None:
    for diagnostic in diagnostics:
        sys.stderr.write(f"Warning: {diagnostic.message}\n")
