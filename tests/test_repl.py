from __future__ import annotations

import io

from mewcode import cli
from mewcode.providers import ProviderError, ProviderProfile
from mewcode.repl import Repl


class FakeConversation:
    def __init__(self, parts: list[str] | None = None, fail: bool = False) -> None:
        self.parts = parts or []
        self.fail = fail
        self.asked: list[str] = []

    def ask(self, user_text: str):
        self.asked.append(user_text)
        if self.fail:
            raise ProviderError("provider failed")
        yield from self.parts


def input_sequence(values: list[str]):
    iterator = iter(values)

    def fake_input(prompt: str) -> str:
        return next(iterator)

    return fake_input


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
    repl = Repl(FakeConversation(), stdout=stdout, input_func=raise_eof)

    assert repl.run() == 0
    assert stdout.getvalue().endswith("\n")


def test_repl_ignores_empty_input() -> None:
    conversation = FakeConversation(["ok"])
    repl = Repl(conversation, stdout=io.StringIO(), input_func=input_sequence(["", "hello", "/exit"]))

    assert repl.run() == 0
    assert conversation.asked == ["hello"]


def test_repl_streams_output_parts() -> None:
    stdout = io.StringIO()
    conversation = FakeConversation(["hel", "lo"])
    repl = Repl(conversation, stdout=stdout, input_func=input_sequence(["hello", "/exit"]))

    assert repl.run() == 0
    assert "hello\n" in stdout.getvalue()


def test_repl_provider_error_goes_to_stderr_and_continues() -> None:
    stderr = io.StringIO()
    conversation = FakeConversation(fail=True)
    repl = Repl(
        conversation,
        stdout=io.StringIO(),
        stderr=stderr,
        input_func=input_sequence(["hello", "/exit"]),
    )

    assert repl.run() == 0
    assert "Error: provider failed" in stderr.getvalue()
    assert conversation.asked == ["hello"]


def test_main_config_error_returns_one(monkeypatch) -> None:
    def fail_load():
        from mewcode.providers import ConfigError

        raise ConfigError("bad config")

    stderr = io.StringIO()
    monkeypatch.setattr(cli, "load_active_profile", fail_load)
    monkeypatch.setattr(cli.sys, "stderr", stderr)

    assert cli.main() == 1
    assert "Error: bad config" in stderr.getvalue()


def test_main_provider_startup_error_returns_one(monkeypatch) -> None:
    profile = ProviderProfile(
        name="main",
        protocol="openai",
        model="model",
        base_url="https://example.test",
        api_key="secret",
    )
    stderr = io.StringIO()
    monkeypatch.setattr(cli, "load_active_profile", lambda: profile)
    monkeypatch.setattr(
        cli,
        "create_provider",
        lambda loaded: (_ for _ in ()).throw(ProviderError("provider missing")),
    )
    monkeypatch.setattr(cli.sys, "stderr", stderr)

    assert cli.main() == 1
    assert "Error: provider missing" in stderr.getvalue()


def test_main_keyboard_interrupt_returns_130(monkeypatch) -> None:
    def interrupt():
        raise KeyboardInterrupt

    stderr = io.StringIO()
    monkeypatch.setattr(cli, "load_active_profile", interrupt)
    monkeypatch.setattr(cli.sys, "stderr", stderr)

    assert cli.main() == 130


def test_main_normal_path_returns_repl_exit_code(monkeypatch) -> None:
    profile = ProviderProfile(
        name="main",
        protocol="openai",
        model="model",
        base_url="https://example.test",
        api_key="secret",
    )
    created = {}

    class FakeProvider:
        pass

    class FakeRepl:
        def __init__(self, conversation) -> None:
            created["conversation"] = conversation

        def run(self) -> int:
            return 7

    monkeypatch.setattr(cli, "load_active_profile", lambda: profile)
    monkeypatch.setattr(cli, "create_provider", lambda loaded: FakeProvider())
    monkeypatch.setattr(cli, "Repl", FakeRepl)

    assert cli.main() == 7
    assert created["conversation"].messages() == []
