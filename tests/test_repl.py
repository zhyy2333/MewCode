from __future__ import annotations

import asyncio
import io

import pytest

from mewcode import cli, repl as repl_module
from mewcode.agent import (
    AgentPermissionDecision,
    AgentProgress,
    AgentStopped,
    AgentTextDelta,
    AgentTokenUsage,
    AgentToolCall,
    AgentToolResult,
    StopReason,
)
from mewcode.conversation import ConversationError
from mewcode.permissions import (
    PermissionChallenge,
    PermissionChoice,
    PermissionConfigError,
    PermissionMode,
    PermissionOutcome,
    PermissionSource,
)
from mewcode.providers import ConfigError, ProviderError, ProviderProfile, TokenUsage
from mewcode.repl import Repl
from mewcode.tools import ToolCallRequest, ToolExecution, ToolResult


class FakeConversation:
    def __init__(self, events: list[object] | None = None) -> None:
        self.events = events or []
        self.routes: list[tuple[str, str]] = []
        self.cancelled = 0
        self.error: ConversationError | None = None

    async def ask(self, user_text: str):
        self.routes.append(("ask", user_text))
        async for event in self._yield_events():
            yield event

    async def plan(self, task: str):
        self.routes.append(("plan", task))
        async for event in self._yield_events():
            yield event

    async def execute_plan(self):
        self.routes.append(("do", ""))
        async for event in self._yield_events():
            yield event

    async def cancel_active(self) -> None:
        self.cancelled += 1

    async def _yield_events(self):
        if self.error is not None:
            raise self.error
        for event in self.events:
            await asyncio.sleep(0)
            yield event


def input_sequence(values: list[str]):
    iterator = iter(values)

    def fake_input(prompt: str) -> str:
        return next(iterator)

    return fake_input


def stop_event() -> AgentStopped:
    return AgentStopped("run", 1, StopReason.COMPLETED, "done", TokenUsage.zero())


def render_events(events: list[object]) -> str:
    renderer = repl_module._EventRenderer()
    return "".join(
        text
        for event in events
        if (text := renderer.render(event)) is not None
    )


def test_repl_exit_command_returns_zero() -> None:
    stdout = io.StringIO()
    repl = Repl(FakeConversation(), stdout=stdout, input_func=input_sequence(["/exit"]))
    assert repl.run() == 0
    assert "MewCode" in stdout.getvalue()


def test_repl_quit_command_returns_zero() -> None:
    repl = Repl(FakeConversation(), stdout=io.StringIO(), input_func=input_sequence(["/quit"]))
    assert repl.run() == 0


def test_repl_eof_returns_zero() -> None:
    def raise_eof(prompt: str) -> str:
        raise EOFError

    stdout = io.StringIO()
    assert Repl(FakeConversation(), stdout=stdout, input_func=raise_eof).run() == 0
    assert stdout.getvalue().endswith("\n")


def test_repl_ignores_empty_input_and_routes_direct_message() -> None:
    conversation = FakeConversation([AgentTextDelta("run", 1, "ok"), stop_event()])
    repl = Repl(conversation, stdout=io.StringIO(), input_func=input_sequence(["", "hello", "/exit"]))
    assert repl.run() == 0
    assert conversation.routes == [("ask", "hello")]


def test_repl_event_indent_and_output_hides_json_arguments() -> None:
    request = ToolCallRequest("call", "read_file", {"path": "secret.json"}, '{"path":"secret.json"}')
    result = ToolResult(True, "read_file", "README.md")
    stdout = io.StringIO()
    conversation = FakeConversation([
        AgentProgress("run", 1, "iteration_started"),
        AgentTextDelta("run", 1, "checking"),
        AgentToolCall("run", 1, request),
        AgentProgress("run", 1, "tool_batch_started", 0, 1, "running 1 tool call(s)"),
        AgentToolResult("run", 1, ToolExecution(0, request, result)),
        AgentTokenUsage("run", 1, TokenUsage(3, 2, 5), TokenUsage(3, 2, 5)),
        stop_event(),
    ])
    Repl(conversation, stdout=stdout, input_func=input_sequence(["hello", "/exit"])).run()

    output = stdout.getvalue()
    assert "checking" in output
    assert "  tool: read_file ..." in output
    assert "  tool: read_file ok - README.md" in output
    assert "  tokens: in=3 out=2 total=5 cache-read=n/a cache-write=n/a cumulative=5 cumulative-cache-read=n/a cumulative-cache-write=n/a" in output
    assert "  agent: running 1 tool call(s)" in output
    assert "secret.json" not in output


def test_event_indent_keeps_primary_output_unindented() -> None:
    request = ToolCallRequest("call", "read_file", {}, "{}")
    result = ToolResult(True, "read_file", "README.md")
    output = render_events([
        AgentProgress("run", 1, "iteration_started"),
        AgentToolCall("run", 1, request),
        AgentProgress(
            "run", 1, "tool_batch_started", 0, 1, "running 1 tool call(s)"
        ),
        AgentToolResult("run", 1, ToolExecution(0, request, result)),
        AgentTokenUsage(
            "run", 1, TokenUsage(3, 2, 5), TokenUsage(3, 2, 5)
        ),
        AgentTextDelta("run", 1, "answer"),
        stop_event(),
    ])

    assert output == (
        "agent: iteration 1\n"
        "  tool: read_file ...\n"
        "  agent: running 1 tool call(s)\n"
        "  tool: read_file ok - README.md\n"
        "  tokens: in=3 out=2 total=5 cache-read=n/a cache-write=n/a cumulative=5 cumulative-cache-read=n/a cumulative-cache-write=n/a\n"
        "answer\n"
        "agent: completed\n"
    )


def test_first_iteration_has_no_leading_blank_line() -> None:
    output = render_events([AgentProgress("run", 1, "iteration_started")])

    assert output == "agent: iteration 1\n"


def test_iteration_spacing_has_exactly_one_blank_line() -> None:
    request = ToolCallRequest("call", "read_file", {}, "{}")
    output = render_events([
        AgentProgress("run", 1, "iteration_started"),
        AgentToolCall("run", 1, request),
        AgentProgress("run", 2, "iteration_started"),
        AgentTokenUsage(
            "run", 2, TokenUsage(1, 1, 2), TokenUsage(1, 1, 2)
        ),
    ])

    assert output == (
        "agent: iteration 1\n"
        "  tool: read_file ...\n"
        "\n"
        "agent: iteration 2\n"
        "  tokens: in=1 out=1 total=2 cache-read=n/a cache-write=n/a cumulative=2 cumulative-cache-read=n/a cumulative-cache-write=n/a\n"
    )


def test_line_boundary_after_unterminated_streaming_text() -> None:
    request = ToolCallRequest("call", "read_file", {}, "{}")
    output = render_events([
        AgentTextDelta("run", 1, "thinking"),
        AgentToolCall("run", 1, request),
    ])

    assert output == "thinking\n  tool: read_file ...\n"


def test_line_boundary_does_not_duplicate_existing_newline() -> None:
    request = ToolCallRequest("call", "read_file", {}, "{}")
    output = render_events([
        AgentTextDelta("run", 1, "thinking\n"),
        AgentToolCall("run", 1, request),
    ])

    assert output == "thinking\n  tool: read_file ...\n"


def test_stopped_error_is_primary_output() -> None:
    output = render_events([
        AgentStopped(
            "run",
            1,
            StopReason.STREAM_ERROR,
            "",
            TokenUsage.zero(),
            "provider failed",
        )
    ])

    assert output == "agent: stopped (stream_error) - provider failed\n"


@pytest.mark.parametrize(
    "reason",
    [StopReason.OUTPUT_LIMIT, StopReason.EMPTY_RESPONSE],
)
def test_incomplete_model_response_has_explicit_stop_reason(
    reason: StopReason,
) -> None:
    output = render_events(
        [AgentStopped("run", 1, reason, "", TokenUsage.zero())]
    )

    assert output == f"agent: stopped ({reason.value})\n"


def test_immediate_text_streaming_writes_each_delta() -> None:
    class RecordingStream(io.StringIO):
        def __init__(self) -> None:
            super().__init__()
            self.writes: list[str] = []
            self.flush_count = 0

        def write(self, text: str) -> int:
            self.writes.append(text)
            return super().write(text)

        def flush(self) -> None:
            self.flush_count += 1
            super().flush()

    stdout = RecordingStream()
    conversation = FakeConversation([
        AgentTextDelta("run", 1, "first"),
        AgentTextDelta("run", 1, " second"),
        stop_event(),
    ])

    Repl(
        conversation,
        stdout=stdout,
        input_func=input_sequence(["hello", "/exit"]),
    ).run()

    first_index = stdout.writes.index("first")
    second_index = stdout.writes.index(" second")
    assert second_index == first_index + 1
    assert stdout.flush_count >= len(conversation.events)


def test_renderer_reset_between_user_tasks() -> None:
    stdout = io.StringIO()
    conversation = FakeConversation([
        AgentProgress("run", 1, "iteration_started"),
        stop_event(),
    ])

    Repl(
        conversation,
        stdout=stdout,
        input_func=input_sequence(["first", "second", "/exit"]),
    ).run()

    task_output = (
        "agent: iteration 1\n"
        "agent: completed\n"
        "\n"
        "agent: iteration 1\n"
        "agent: completed\n"
        "\n"
    )
    assert stdout.getvalue().endswith(task_output)
    assert "\n\n\nagent: iteration 1" not in stdout.getvalue()


def test_end_to_end_hierarchy_matches_approved_layout() -> None:
    request = ToolCallRequest("call", "find_files", {}, "{}")
    result = ToolResult(True, "find_files", ".gitignore")
    stdout = io.StringIO()
    conversation = FakeConversation([
        AgentProgress("run", 1, "iteration_started"),
        AgentToolCall("run", 1, request),
        AgentProgress(
            "run", 1, "tool_batch_started", 0, 1, "running 1 tool call(s)"
        ),
        AgentToolResult("run", 1, ToolExecution(0, request, result)),
        AgentTokenUsage(
            "run", 1, TokenUsage(4, 2, 6), TokenUsage(4, 2, 6)
        ),
        AgentProgress("run", 2, "iteration_started"),
        AgentTextDelta("run", 2, "Final answer."),
        stop_event(),
    ])

    Repl(
        conversation,
        stdout=stdout,
        input_func=input_sequence(["work", "/exit"]),
    ).run()

    assert stdout.getvalue().endswith(
        "agent: iteration 1\n"
        "  tool: find_files ...\n"
        "  agent: running 1 tool call(s)\n"
        "  tool: find_files ok - .gitignore\n"
        "  tokens: in=4 out=2 total=6 cache-read=n/a cache-write=n/a cumulative=6 cumulative-cache-read=n/a cumulative-cache-write=n/a\n"
        "\n"
        "agent: iteration 2\n"
        "Final answer.\n"
        "agent: completed\n"
        "\n"
    )


def test_plan_command_do_command_and_routing() -> None:
    conversation = FakeConversation([stop_event()])
    Repl(
        conversation,
        stdout=io.StringIO(),
        input_func=input_sequence(["/plan build it", "/do", "chat", "/exit"]),
    ).run()
    assert conversation.routes == [
        ("plan", "build it"), ("do", ""), ("ask", "chat")
    ]


def test_empty_plan_error_goes_to_stderr_and_continues() -> None:
    stderr = io.StringIO()
    conversation = FakeConversation()
    conversation.error = ConversationError("Usage: /plan <task>")
    Repl(
        conversation,
        stdout=io.StringIO(),
        stderr=stderr,
        input_func=input_sequence(["/plan", "/exit"]),
    ).run()
    assert "Usage: /plan <task>" in stderr.getvalue()


def test_end_to_end_cancel_ctrl_c_continues_after_cancel() -> None:
    class InterruptOnceConversation(FakeConversation):
        def __init__(self) -> None:
            super().__init__()
            self.interrupted = False

        async def ask(self, user_text: str):
            self.routes.append(("ask", user_text))
            if not self.interrupted:
                self.interrupted = True
                raise KeyboardInterrupt
            yield AgentTextDelta("run", 1, "after cancel")
            yield stop_event()

    stdout = io.StringIO()
    conversation = InterruptOnceConversation()
    result = Repl(
        conversation,
        stdout=stdout,
        input_func=input_sequence(["long task", "next task", "/exit"]),
    ).run()

    assert result == 0
    assert conversation.cancelled == 1
    assert conversation.routes == [("ask", "long task"), ("ask", "next task")]
    assert "agent: cancelled" in stdout.getvalue()
    assert "after cancel" in stdout.getvalue()


def test_render_error_cancels_current_run_and_continues(monkeypatch) -> None:
    original = repl_module._format_event
    raised = False

    def fail_once(event):
        nonlocal raised
        if not raised:
            raised = True
            raise RuntimeError("render failed")
        return original(event)

    monkeypatch.setattr(repl_module, "_format_event", fail_once)
    stdout = io.StringIO()
    stderr = io.StringIO()
    conversation = FakeConversation(
        [AgentTextDelta("run", 1, "recovered"), stop_event()]
    )

    result = Repl(
        conversation,
        stdout=stdout,
        stderr=stderr,
        input_func=input_sequence(["first", "second", "/exit"]),
    ).run()

    assert result == 0
    assert conversation.cancelled == 1
    assert conversation.routes == [("ask", "first"), ("ask", "second")]
    assert "event consumer failed: render failed" in stderr.getvalue()
    assert "recovered" in stdout.getvalue()


class FakePermissionController:
    def __init__(self, mode: PermissionMode = PermissionMode.DEFAULT) -> None:
        self.mode = mode

    def set_mode(self, mode: PermissionMode) -> None:
        self.mode = mode


def test_permission_decision_render_is_indented_and_desensitized() -> None:
    event = AgentPermissionDecision(
        "run",
        1,
        "call",
        "write_file",
        "src/a.py",
        PermissionOutcome.DENY,
        PermissionSource.PROJECT_RULE,
        "A permission rule denied this tool call.",
    )
    output = render_events([event])
    assert "  permission: write_file(src/a.py) deny [project_rule]" in output
    assert "file contents are secret" not in output


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("d", PermissionChoice.DENY),
        ("once", PermissionChoice.ONCE),
        ("s", PermissionChoice.SESSION),
        ("permanent", PermissionChoice.PERMANENT),
    ],
)
def test_permission_confirmation_choices(raw: str, expected: PermissionChoice) -> None:
    async def scenario() -> None:
        challenge = PermissionChallenge("p", "c", "read_file", "src/a.py")
        repl = Repl(
            FakeConversation(),
            stdout=io.StringIO(),
            stderr=io.StringIO(),
            input_func=input_sequence(["invalid", raw]),
        )
        event = repl_module.AgentPermissionRequest("run", 1, challenge)
        repl._handle_permission_request(event)
        assert await challenge.wait() == expected

    asyncio.run(scenario())


def test_permission_confirmation_eof_denies() -> None:
    async def scenario() -> None:
        challenge = PermissionChallenge("p", "c", "read_file", "src/a.py")

        def eof(prompt: str) -> str:
            raise EOFError

        repl = Repl(FakeConversation(), stdout=io.StringIO(), input_func=eof)
        repl._handle_permission_request(
            repl_module.AgentPermissionRequest("run", 1, challenge)
        )
        assert await challenge.wait() == PermissionChoice.DENY

    asyncio.run(scenario())


def test_permissions_command_queries_switches_and_rejects_invalid() -> None:
    controller = FakePermissionController()
    conversation = FakeConversation()
    stdout = io.StringIO()
    stderr = io.StringIO()
    result = Repl(
        conversation,
        stdout=stdout,
        stderr=stderr,
        input_func=input_sequence(
            ["/permissions", "/permissions strict", "/permissions unsafe", "/exit"]
        ),
        permission_controller=controller,
    ).run()
    assert result == 0
    assert controller.mode == PermissionMode.STRICT
    assert "permission mode: default" in stdout.getvalue()
    assert "permission mode: strict" in stdout.getvalue()
    assert "Usage: /permissions [strict|default|allow]" in stderr.getvalue()
    assert conversation.routes == []


def test_main_config_error_returns_one(monkeypatch) -> None:
    monkeypatch.setattr(cli, "load_active_profile", lambda: (_ for _ in ()).throw(ConfigError("bad config")))
    stderr = io.StringIO()
    monkeypatch.setattr(cli.sys, "stderr", stderr)
    assert cli.main([]) == 1
    assert "Error: bad config" in stderr.getvalue()


def test_main_provider_startup_error_returns_one(monkeypatch) -> None:
    profile = ProviderProfile("main", "openai", "model", "https://example.test", "secret")
    monkeypatch.setattr(cli, "load_active_profile", lambda: profile)
    monkeypatch.setattr(cli, "create_provider", lambda loaded: (_ for _ in ()).throw(ProviderError("provider missing")))
    monkeypatch.setattr(
        cli,
        "McpRuntime",
        lambda root: (_ for _ in ()).throw(
            AssertionError("MCP runtime must not start before provider validation")
        ),
    )
    stderr = io.StringIO()
    monkeypatch.setattr(cli.sys, "stderr", stderr)
    assert cli.main([]) == 1
    assert "Error: provider missing" in stderr.getvalue()


def test_main_keyboard_interrupt_returns_130(monkeypatch) -> None:
    monkeypatch.setattr(cli, "load_active_profile", lambda: (_ for _ in ()).throw(KeyboardInterrupt()))
    stderr = io.StringIO()
    monkeypatch.setattr(cli.sys, "stderr", stderr)
    assert cli.main([]) == 130


def test_main_prompt_builder_normal_path_wires_agent_components(monkeypatch) -> None:
    profile = ProviderProfile("main", "openai", "model", "https://example.test", "secret")
    created = {}

    class FakeProvider:
        pass

    class FakeScheduler:
        def __init__(self, controller):
            created["controller"] = controller

    class FakeRunner:
        def __init__(self, provider, scheduler, *, prompt_builder):
            created["provider"] = provider
            created["scheduler"] = scheduler
            created["prompt_builder"] = prompt_builder

    class FakeSession:
        def __init__(self, runner, tools):
            created["runner"] = runner
            created["tools"] = tools

    class FakeRepl:
        def __init__(self, session, *, permission_controller):
            created["session"] = session
            assert permission_controller is created["controller"]

        def run(self) -> int:
            return 7

    monkeypatch.setattr(cli, "load_active_profile", lambda: profile)
    monkeypatch.setattr(cli, "create_provider", lambda loaded: FakeProvider())
    monkeypatch.setattr(cli, "ToolScheduler", FakeScheduler)
    monkeypatch.setattr(cli, "AgentRunner", FakeRunner)
    monkeypatch.setattr(cli, "Conversation", FakeSession)
    monkeypatch.setattr(cli, "Repl", FakeRepl)

    assert cli.main(["--permission-mode", "strict"]) == 7
    assert isinstance(created["provider"], FakeProvider)
    assert isinstance(created["scheduler"], FakeScheduler)
    assert created["prompt_builder"] is not None
    assert created["tools"] is not None
    assert created["controller"].mode == PermissionMode.STRICT


def test_main_permission_config_error_returns_one(monkeypatch) -> None:
    profile = ProviderProfile(
        "main", "openai", "model", "https://example.test", "secret"
    )
    monkeypatch.setattr(cli, "load_active_profile", lambda: profile)
    monkeypatch.setattr(cli, "create_provider", lambda loaded: object())
    monkeypatch.setattr(
        cli.PermissionConfigLoader,
        "load",
        lambda *args: (_ for _ in ()).throw(PermissionConfigError("bad permissions")),
    )
    stderr = io.StringIO()
    monkeypatch.setattr(cli.sys, "stderr", stderr)
    assert cli.main([]) == 1
    assert "bad permissions" in stderr.getvalue()


def test_cli_rejects_invalid_permission_mode() -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--permission-mode", "unsafe"])
    assert exc_info.value.code == 2


def test_token_output_shows_cache_tokens_and_unknowns() -> None:
    output = render_events(
        [
            AgentTokenUsage(
                "run",
                1,
                TokenUsage(10, 2, 12, 7, 3),
                TokenUsage(20, 4, 24, None, 0),
            )
        ]
    )
    assert output == (
        "  tokens: in=10 out=2 total=12 cache-read=7 cache-write=3 "
        "cumulative=24 cumulative-cache-read=n/a cumulative-cache-write=0\n"
    )


def _prepare_mcp_cli(monkeypatch, config_result, runtime_class, *, repl_result=0):
    from types import SimpleNamespace
    from mewcode.permissions import PermissionRuleSets
    from mewcode.providers import ProviderProfile

    profile = ProviderProfile(
        "main", "openai", "model", "https://example.test", "secret"
    )
    captured = {}
    monkeypatch.setattr(cli, "load_active_profile", lambda: profile)
    monkeypatch.setattr(cli, "create_provider", lambda loaded: object())
    monkeypatch.setattr(cli.McpConfigLoader, "load", lambda self, paths: config_result)
    monkeypatch.setattr(cli, "McpRuntime", runtime_class)

    def load_permissions(self, paths, known_tools, deferred=()):
        captured["known_tools"] = set(known_tools)
        captured["deferred"] = tuple(deferred)
        return PermissionRuleSets()

    monkeypatch.setattr(cli.PermissionConfigLoader, "load", load_permissions)

    class FakeConversation:
        def __init__(self, runner, registry):
            captured["registry"] = registry

    class FakeRepl:
        def __init__(self, conversation, *, permission_controller):
            pass
        def run(self):
            return repl_result

    monkeypatch.setattr(cli, "Conversation", FakeConversation)
    monkeypatch.setattr(cli, "Repl", FakeRepl)
    return captured


def test_cli_without_mcp_config_preserves_existing_tool_and_exit_behavior(monkeypatch) -> None:
    from mewcode.mcp.config import McpConfigLoadResult

    class RuntimeMustNotStart:
        def __init__(self, root):
            raise AssertionError("runtime must not start")

    captured = _prepare_mcp_cli(
        monkeypatch, McpConfigLoadResult((), (), ()), RuntimeMustNotStart
    )
    assert cli.main([]) == 0
    assert len(captured["registry"].list()) == 6


def test_cli_registers_healthy_mcp_tools_and_deferred_namespaces(monkeypatch) -> None:
    from types import SimpleNamespace
    from mewcode.mcp.config import McpConfigLoadResult
    from mewcode.mcp.models import StdioServerConfig
    from mewcode.mcp.runtime import McpRuntimeStartResult
    from mewcode.tools import PermissionTargetKind, ToolPermissionSpec, ToolSafety

    remote = SimpleNamespace(
        name="server__echo",
        description="Echo",
        parameters_schema={},
        safety=ToolSafety.SIDE_EFFECT,
        permission_spec=ToolPermissionSpec(None, PermissionTargetKind.TOOL, "invoke"),
    )

    class Runtime:
        def __init__(self, root): pass
        def start(self, configs, reserved):
            assert "read_file" in reserved
            return McpRuntimeStartResult((remote,), ())
        def close(self): return ()

    config = McpConfigLoadResult(
        (StdioServerConfig("server", "fake"),), (), ("server__",)
    )
    captured = _prepare_mcp_cli(monkeypatch, config, Runtime)
    assert cli.main([]) == 0
    assert "server__echo" in captured["known_tools"]
    assert captured["deferred"] == ("server__",)


def test_cli_prints_server_warning_without_leaking_secret(monkeypatch) -> None:
    from mewcode.mcp.config import McpConfigLoadResult
    from mewcode.mcp.models import McpDiagnostic, McpPhase

    warning = McpDiagnostic("bad", McpPhase.CONFIG, "safe reason")
    class RuntimeMustNotStart:
        def __init__(self, root): raise AssertionError
    _prepare_mcp_cli(monkeypatch, McpConfigLoadResult((), (warning,), ()), RuntimeMustNotStart)
    stderr = io.StringIO(); monkeypatch.setattr(cli.sys, "stderr", stderr)
    assert cli.main([]) == 0
    assert "bad" in stderr.getvalue() and "sentinel-secret" not in stderr.getvalue()


def test_cli_closes_mcp_runtime_on_normal_exit(monkeypatch) -> None:
    from mewcode.mcp.config import McpConfigLoadResult
    from mewcode.mcp.models import StdioServerConfig
    from mewcode.mcp.runtime import McpRuntimeStartResult

    calls = []
    class Runtime:
        def __init__(self, root): pass
        def start(self, configs, reserved): calls.append("start"); return McpRuntimeStartResult((), ())
        def close(self): calls.append("close"); return ()
    _prepare_mcp_cli(monkeypatch, McpConfigLoadResult((StdioServerConfig("s", "x"),), (), ("s__",)), Runtime)
    assert cli.main([]) == 0 and calls == ["start", "close"]


def test_cli_closes_partial_runtime_when_later_startup_fails(monkeypatch) -> None:
    from mewcode.mcp.config import McpConfigLoadResult
    from mewcode.mcp.models import StdioServerConfig
    from mewcode.mcp.runtime import McpRuntimeStartResult

    calls = []
    class Runtime:
        def __init__(self, root): pass
        def start(self, configs, reserved): calls.append("start"); return McpRuntimeStartResult((), ())
        def close(self): calls.append("close"); return ()
    _prepare_mcp_cli(monkeypatch, McpConfigLoadResult((StdioServerConfig("s", "x"),), (), ("s__",)), Runtime)
    monkeypatch.setattr(cli.PermissionConfigLoader, "load", lambda *args: (_ for _ in ()).throw(PermissionConfigError("bad permissions")))
    assert cli.main([]) == 1 and calls == ["start", "close"]


def test_cli_closes_runtime_on_keyboard_interrupt(monkeypatch) -> None:
    from mewcode.mcp.config import McpConfigLoadResult
    from mewcode.mcp.models import StdioServerConfig
    from mewcode.mcp.runtime import McpRuntimeStartResult

    calls = []
    class Runtime:
        def __init__(self, root): pass
        def start(self, configs, reserved): calls.append("start"); return McpRuntimeStartResult((), ())
        def close(self): calls.append("close"); return ()
    _prepare_mcp_cli(monkeypatch, McpConfigLoadResult((StdioServerConfig("s", "x"),), (), ("s__",)), Runtime)
    class InterruptRepl:
        def __init__(self, *args, **kwargs): pass
        def run(self): raise KeyboardInterrupt
    monkeypatch.setattr(cli, "Repl", InterruptRepl)
    assert cli.main([]) == 130 and calls == ["start", "close"]
