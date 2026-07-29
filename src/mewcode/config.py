from __future__ import annotations

import os
from pathlib import Path
from typing import Any, cast

import yaml

from .providers import ConfigError, ProviderProfile

DEFAULT_CONFIG_PATH = Path.home() / ".mewcode" / "config.yaml"
SUPPORTED_PROTOCOLS = {"anthropic", "openai"}
REQUIRED_PROFILE_FIELDS = ("name", "protocol", "model", "base_url", "api_key")


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

    thinking = raw.get("thinking", False)
    if not isinstance(thinking, bool):
        raise ConfigError("Profile field 'thinking' must be a boolean when provided.")

    api_key = _resolve_api_key(api_key_ref)
    return ProviderProfile(
        name=name,
        protocol=cast(Any, protocol),
        model=model,
        base_url=base_url,
        api_key=api_key,
        thinking=thinking,
    )


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
