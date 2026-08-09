from __future__ import annotations

import asyncio
import io

import pytest

from mewcode import cli, repl as repl_module
from mewcode.agent import (
    AgentProgress,
    AgentStopped,
    AgentTextDelta,
    AgentTokenUsage,
    AgentToolCall,
    AgentToolResult,
    StopReason,
)
from mewcode.conversation import ConversationError
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


def test_main_config_error_returns_one(monkeypatch) -> None:
    monkeypatch.setattr(cli, "load_active_profile", lambda: (_ for _ in ()).throw(ConfigError("bad config")))
    stderr = io.StringIO()
    monkeypatch.setattr(cli.sys, "stderr", stderr)
    assert cli.main() == 1
    assert "Error: bad config" in stderr.getvalue()


def test_main_provider_startup_error_returns_one(monkeypatch) -> None:
    profile = ProviderProfile("main", "openai", "model", "https://example.test", "secret")
    monkeypatch.setattr(cli, "load_active_profile", lambda: profile)
    monkeypatch.setattr(cli, "create_provider", lambda loaded: (_ for _ in ()).throw(ProviderError("provider missing")))
    stderr = io.StringIO()
    monkeypatch.setattr(cli.sys, "stderr", stderr)
    assert cli.main() == 1
    assert "Error: provider missing" in stderr.getvalue()


def test_main_keyboard_interrupt_returns_130(monkeypatch) -> None:
    monkeypatch.setattr(cli, "load_active_profile", lambda: (_ for _ in ()).throw(KeyboardInterrupt()))
    stderr = io.StringIO()
    monkeypatch.setattr(cli.sys, "stderr", stderr)
    assert cli.main() == 130


def test_main_prompt_builder_normal_path_wires_agent_components(monkeypatch) -> None:
    profile = ProviderProfile("main", "openai", "model", "https://example.test", "secret")
    created = {}

    class FakeProvider:
        pass

    class FakeScheduler:
        pass

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
        def __init__(self, session):
            created["session"] = session

        def run(self) -> int:
            return 7

    monkeypatch.setattr(cli, "load_active_profile", lambda: profile)
    monkeypatch.setattr(cli, "create_provider", lambda loaded: FakeProvider())
    monkeypatch.setattr(cli, "ToolScheduler", FakeScheduler)
    monkeypatch.setattr(cli, "AgentRunner", FakeRunner)
    monkeypatch.setattr(cli, "Conversation", FakeSession)
    monkeypatch.setattr(cli, "Repl", FakeRepl)

    assert cli.main() == 7
    assert isinstance(created["provider"], FakeProvider)
    assert isinstance(created["scheduler"], FakeScheduler)
    assert created["prompt_builder"] is not None
    assert created["tools"] is not None


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
