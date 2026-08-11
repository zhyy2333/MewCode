from __future__ import annotations

import os
from pathlib import Path
from typing import Any, cast

import yaml

from .providers import ConfigError, ProviderProfile, ThinkingMode

DEFAULT_CONFIG_PATH = Path.home() / ".mewcode" / "config.yaml"
SUPPORTED_PROTOCOLS = {"anthropic", "openai"}
REQUIRED_PROFILE_FIELDS = ("name", "protocol", "model", "base_url", "api_key")
DEFAULT_CONTEXT_WINDOW = 128_000
MIN_CONTEXT_WINDOW = 21_193


def load_active_profile(path: Path = DEFAULT_CONFIG_PATH) -> ProviderProfile:
    if not path.exists():
        raise ConfigError(
            f"Config file not found at {path}. Create it from examples/config.yaml."
        )

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in config file: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError("Config file must contain a YAML object.")

    active = raw.get("active")
    profiles = raw.get("profiles")
    if not isinstance(active, str) or not active.strip():
        raise ConfigError("Config field 'active' must be a non-empty string.")
    if not isinstance(profiles, list):
        raise ConfigError("Config field 'profiles' must be a list.")

    selected = _find_profile(profiles, active)
    return _parse_profile(selected)


def _find_profile(profiles: list[Any], active: str) -> dict[str, Any]:
    for profile in profiles:
        if isinstance(profile, dict) and profile.get("name") == active:
            return profile
    raise ConfigError(f"Active profile '{active}' was not found in profiles.")


def _parse_profile(raw: dict[str, Any]) -> ProviderProfile:
    missing = [field for field in REQUIRED_PROFILE_FIELDS if field not in raw]
    if missing:
        fields = ", ".join(missing)
        raise ConfigError(f"Profile is missing required field(s): {fields}.")

    name = _require_string(raw, "name")
    protocol = _require_string(raw, "protocol")
    model = _require_string(raw, "model")
    base_url = _require_string(raw, "base_url")
    api_key_ref = _require_string(raw, "api_key")

    if protocol not in SUPPORTED_PROTOCOLS:
        raise ConfigError(f"Unsupported protocol '{protocol}'. Use 'anthropic' or 'openai'.")

    thinking = _parse_thinking_mode(raw)
    context_window = _parse_context_window(raw)

    api_key = _resolve_api_key(api_key_ref)
    return ProviderProfile(
        name=name,
        protocol=cast(Any, protocol),
        model=model,
        base_url=base_url,
        api_key=api_key,
        thinking=thinking,
        context_window=context_window,
    )


def _parse_thinking_mode(raw: dict[str, Any]) -> ThinkingMode:
    if "thinking" not in raw:
        return ThinkingMode.AUTO

    value = raw["thinking"]
    if isinstance(value, bool):
        return ThinkingMode.ENABLED if value else ThinkingMode.DISABLED
    if isinstance(value, str):
        try:
            return ThinkingMode(value)
        except ValueError:
            pass
    raise ConfigError(
        "Profile field 'thinking' must be 'auto', 'enabled', 'disabled', "
        "true, or false when provided."
    )


def _parse_context_window(raw: dict[str, Any]) -> int:
    if "context_window" not in raw:
        return DEFAULT_CONTEXT_WINDOW
    value = raw["context_window"]
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < MIN_CONTEXT_WINDOW
    ):
        raise ConfigError(
            "Profile field 'context_window' must be an integer of at least "
            f"{MIN_CONTEXT_WINDOW}."
        )
    return value


def _require_string(raw: dict[str, Any], field: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"Profile field '{field}' must be a non-empty string.")
    return value.strip()


def _resolve_api_key(value: str) -> str:
    prefix = "env:"
    if not value.startswith(prefix) or len(value) == len(prefix):
        raise ConfigError("Profile field 'api_key' must use env:VAR_NAME format.")

    env_name = value[len(prefix) :].strip()
    if not env_name:
        raise ConfigError("Profile field 'api_key' must include an environment variable name.")

    api_key = os.environ.get(env_name)
    if not api_key:
        raise ConfigError(f"Environment variable '{env_name}' is not set or empty.")
    return api_key
