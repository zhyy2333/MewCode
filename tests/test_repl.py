from __future__ import annotations

import asyncio
import io

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


def test_repl_streams_event_output_and_hides_json_arguments() -> None:
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
    assert "tool: read_file ..." in output
    assert "tool: read_file ok - README.md" in output
    assert "tokens: in=3 out=2 total=5 cumulative=5" in output
    assert "secret.json" not in output


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


def test_main_normal_path_wires_agent_components(monkeypatch) -> None:
    profile = ProviderProfile("main", "openai", "model", "https://example.test", "secret")
    created = {}

    class FakeProvider:
        pass

    class FakeScheduler:
        pass

    class FakeRunner:
        def __init__(self, provider, scheduler):
            created["provider"] = provider
            created["scheduler"] = scheduler

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
    assert created["tools"] is not None
