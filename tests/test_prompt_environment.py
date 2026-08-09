from datetime import date

from mewcode.prompting import PromptEnvironmentProvider, render_environment


def test_environment_uses_only_whitelisted_fields(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MEWCODE_TEST_SECRET", "never-include-this")
    provider = PromptEnvironmentProvider(
        tmp_path,
        clock=lambda: date(2026, 8, 9),
        operating_system=lambda: "Windows",
        shell="ignored-shell",
    )
    text = render_environment(provider.get())
    assert f"Workspace: {tmp_path.resolve()}" in text
    assert "Operating system: Windows" in text
    assert "Current date: 2026-08-09" in text
    assert "Shell: PowerShell" in text
    assert "MEWCODE_TEST_SECRET" not in text
    assert "never-include-this" not in text


def test_environment_uses_shell_basename_on_other_platforms(tmp_path) -> None:
    provider = PromptEnvironmentProvider(
        tmp_path,
        operating_system=lambda: "Linux",
        shell="/usr/bin/zsh",
    )
    assert provider.get().shell == "zsh"


def test_environment_has_explicit_unknown_fallbacks(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("SHELL", raising=False)
    provider = PromptEnvironmentProvider(
        tmp_path,
        operating_system=lambda: "",
        shell="",
    )
    environment = provider.get()
    assert environment.operating_system == "unknown"
    assert environment.shell == "unknown"
