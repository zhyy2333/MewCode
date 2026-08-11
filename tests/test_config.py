from __future__ import annotations

from pathlib import Path

import pytest

from mewcode.config import load_active_profile
from mewcode.providers import ConfigError, ProviderProfile, ThinkingMode


def write_config(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def test_load_active_profile_reads_selected_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "openai-secret")
    config_path = tmp_path / "config.yaml"
    write_config(
        config_path,
        """
active: openai-main
profiles:
  - name: claude-main
    protocol: anthropic
    model: claude-sonnet
    base_url: https://api.anthropic.com
    api_key: env:ANTHROPIC_API_KEY
    thinking: true
  - name: openai-main
    protocol: openai
    model: gpt-5.6
    base_url: https://api.openai.com/v1
    api_key: env:OPENAI_API_KEY
""",
    )

    profile = load_active_profile(config_path)

    assert profile == ProviderProfile(
        name="openai-main",
        protocol="openai",
        model="gpt-5.6",
        base_url="https://api.openai.com/v1",
        api_key="openai-secret",
        thinking=ThinkingMode.AUTO,
        context_window=128_000,
    )


def test_context_window_is_optional_and_customizable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("API_KEY", "secret")
    config_path = tmp_path / "config.yaml"
    write_config(
        config_path,
        """
active: main
profiles:
  - name: main
    protocol: openai
    model: model
    base_url: https://example.test
    api_key: env:API_KEY
    context_window: 200000
""",
    )

    assert load_active_profile(config_path).context_window == 200_000


@pytest.mark.parametrize("value", ["true", "1.5", "21192", "text"])
def test_invalid_context_window_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("API_KEY", "secret")
    config_path = tmp_path / "config.yaml"
    write_config(
        config_path,
        f"""
active: main
profiles:
  - name: main
    protocol: openai
    model: model
    base_url: https://example.test
    api_key: env:API_KEY
    context_window: {value}
""",
    )

    with pytest.raises(ConfigError, match="context_window.*21193"):
        load_active_profile(config_path)


@pytest.mark.parametrize(
    ("yaml_value", "expected"),
    [
        ("auto", ThinkingMode.AUTO),
        ("enabled", ThinkingMode.ENABLED),
        ("disabled", ThinkingMode.DISABLED),
        ("true", ThinkingMode.ENABLED),
        ("false", ThinkingMode.DISABLED),
    ],
)
def test_thinking_modes_and_boolean_compatibility(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    yaml_value: str,
    expected: ThinkingMode,
) -> None:
    monkeypatch.setenv("API_KEY", "secret")
    config_path = tmp_path / "config.yaml"
    write_config(
        config_path,
        f"""
active: main
profiles:
  - name: main
    protocol: anthropic
    model: model
    base_url: https://example.test
    api_key: env:API_KEY
    thinking: {yaml_value}
""",
    )

    assert load_active_profile(config_path).thinking is expected


@pytest.mark.parametrize("yaml_value", ["sometimes", "42", "null", "[]"])
def test_invalid_thinking_value_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    yaml_value: str,
) -> None:
    monkeypatch.setenv("API_KEY", "secret")
    config_path = tmp_path / "config.yaml"
    write_config(
        config_path,
        f"""
active: main
profiles:
  - name: main
    protocol: anthropic
    model: model
    base_url: https://example.test
    api_key: env:API_KEY
    thinking: {yaml_value}
""",
    )

    with pytest.raises(ConfigError, match="auto.*enabled.*disabled"):
        load_active_profile(config_path)


def test_missing_config_file_reports_path(tmp_path: Path) -> None:
    config_path = tmp_path / "missing.yaml"

    with pytest.raises(ConfigError, match="Config file not found"):
        load_active_profile(config_path)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("[]", "YAML object"),
        ("profiles: []", "active"),
        ("active: main", "profiles"),
        ("active: missing\nprofiles: []", "not found"),
    ],
)
def test_invalid_top_level_config_errors(tmp_path: Path, content: str, message: str) -> None:
    config_path = tmp_path / "config.yaml"
    write_config(config_path, content)

    with pytest.raises(ConfigError, match=message):
        load_active_profile(config_path)


def test_missing_profile_field_errors(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    write_config(
        config_path,
        """
active: main
profiles:
  - name: main
    protocol: openai
    model: gpt-5.6
    base_url: https://api.openai.com/v1
""",
    )

    with pytest.raises(ConfigError, match="api_key"):
        load_active_profile(config_path)


def test_unknown_protocol_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_KEY", "secret")
    config_path = tmp_path / "config.yaml"
    write_config(
        config_path,
        """
active: main
profiles:
  - name: main
    protocol: other
    model: model
    base_url: https://example.test
    api_key: env:API_KEY
""",
    )

    with pytest.raises(ConfigError, match="Unsupported protocol"):
        load_active_profile(config_path)


def test_api_key_must_use_env_reference(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    write_config(
        config_path,
        """
active: main
profiles:
  - name: main
    protocol: openai
    model: gpt-5.6
    base_url: https://api.openai.com/v1
    api_key: plain-secret
""",
    )

    with pytest.raises(ConfigError, match="env:VAR_NAME"):
        load_active_profile(config_path)


def test_missing_api_key_environment_variable_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config_path = tmp_path / "config.yaml"
    write_config(
        config_path,
        """
active: main
profiles:
  - name: main
    protocol: openai
    model: gpt-5.6
    base_url: https://api.openai.com/v1
    api_key: env:OPENAI_API_KEY
""",
    )

    with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
        load_active_profile(config_path)


def test_error_does_not_include_resolved_api_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_KEY", "super-secret")
    config_path = tmp_path / "config.yaml"
    write_config(
        config_path,
        """
active: main
profiles:
  - name: main
    protocol: invalid
    model: model
    base_url: https://example.test
    api_key: env:API_KEY
""",
    )

    with pytest.raises(ConfigError) as exc_info:
        load_active_profile(config_path)

    assert "super-secret" not in str(exc_info.value)
