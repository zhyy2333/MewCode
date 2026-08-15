from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit

import yaml

from mewcode.tools import Workspace

from .models import (
    HttpServerConfig,
    McpConfigError,
    McpDiagnostic,
    McpPhase,
    McpServerConfig,
    StdioServerConfig,
)
from .naming import permission_namespace_prefix

_TOKEN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_RESERVED_HEADERS = {
    "accept",
    "connection",
    "content-length",
    "content-type",
    "host",
    "mcp-protocol-version",
    "mcp-session-id",
    "transfer-encoding",
}
_STDIO_FIELDS = {"transport", "command", "args", "env"}
_HTTP_FIELDS = {"transport", "url", "headers"}


@dataclass(frozen=True)
class McpConfigPaths:
    user: Path
    project: Path

    @classmethod
    def for_workspace(
        cls,
        workspace: Workspace,
        user_home: Path | None = None,
    ) -> McpConfigPaths:
        home = (user_home or Path.home()).resolve()
        return cls(
            user=home / ".mewcode" / "config.yaml",
            project=workspace.root / ".mewcode" / "config.yaml",
        )


@dataclass(frozen=True)
class McpConfigLoadResult:
    servers: tuple[McpServerConfig, ...]
    diagnostics: tuple[McpDiagnostic, ...]
    permission_prefixes: tuple[str, ...]
    user_servers: tuple[McpServerConfig, ...] = ()
    project_servers: tuple[McpServerConfig, ...] = ()
    project_server_names: tuple[str, ...] = ()


class McpConfigLoader:
    def __init__(self, environment: dict[str, str] | None = None) -> None:
        self._environment = environment if environment is not None else os.environ

    def load(self, paths: McpConfigPaths) -> McpConfigLoadResult:
        user = self._read_file(paths.user, project=False)
        project = self._read_file(paths.project, project=True)
        user_servers = self._server_map(user, paths.user)
        project_servers = self._server_map(project, paths.project)
        merged = dict(user_servers)
        merged.update(project_servers)

        configs: list[McpServerConfig] = []
        user_configs: list[McpServerConfig] = []
        project_configs: list[McpServerConfig] = []
        diagnostics: list[McpDiagnostic] = []
        prefixes: list[str] = []
        for raw_name, raw_config in merged.items():
            if not isinstance(raw_name, str) or not raw_name.strip():
                diagnostics.append(
                    McpDiagnostic(None, McpPhase.CONFIG, "server name must be a non-empty string")
                )
                continue
            name = raw_name
            prefixes.append(permission_namespace_prefix(name))
            try:
                configs.append(self._parse_server(name, raw_config))
            except ValueError as exc:
                diagnostics.append(McpDiagnostic(name, McpPhase.CONFIG, str(exc)))
        for mapping, target in ((user_servers, user_configs), (project_servers, project_configs)):
            for raw_name, raw_config in mapping.items():
                if not isinstance(raw_name, str) or not raw_name.strip():
                    continue
                try:
                    target.append(self._parse_server(raw_name, raw_config))
                except ValueError:
                    pass
        return McpConfigLoadResult(
            servers=tuple(configs),
            diagnostics=tuple(diagnostics),
            permission_prefixes=tuple(dict.fromkeys(prefixes)),
            user_servers=tuple(user_configs),
            project_servers=tuple(project_configs),
            project_server_names=tuple(
                name for name in project_servers if isinstance(name, str) and name.strip()
            ),
        )

    def load_project(self, path: Path) -> McpConfigLoadResult:
        """Load one project layer without touching the live user config file."""
        raw = self._read_file(path, project=True)
        server_map = self._server_map(raw, path)
        configs: list[McpServerConfig] = []
        diagnostics: list[McpDiagnostic] = []
        prefixes: list[str] = []
        names: list[str] = []
        for raw_name, raw_config in server_map.items():
            if not isinstance(raw_name, str) or not raw_name.strip():
                diagnostics.append(
                    McpDiagnostic(None, McpPhase.CONFIG, "server name must be a non-empty string")
                )
                continue
            names.append(raw_name)
            prefixes.append(permission_namespace_prefix(raw_name))
            try:
                configs.append(self._parse_server(raw_name, raw_config))
            except ValueError as exc:
                diagnostics.append(McpDiagnostic(raw_name, McpPhase.CONFIG, str(exc)))
        frozen = tuple(configs)
        return McpConfigLoadResult(
            servers=frozen,
            diagnostics=tuple(diagnostics),
            permission_prefixes=tuple(dict.fromkeys(prefixes)),
            project_servers=frozen,
            project_server_names=tuple(names),
        )

    def _read_file(self, path: Path, *, project: bool) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise McpConfigError(f"Invalid MCP config at {path}: file could not be parsed.") from exc
        if not isinstance(raw, dict):
            raise McpConfigError(f"Invalid MCP config at {path}: root must be a YAML object.")
        return raw

    @staticmethod
    def _server_map(raw: dict[str, Any], path: Path) -> dict[Any, Any]:
        servers = raw.get("mcp_servers", {})
        if not isinstance(servers, dict):
            raise McpConfigError(
                f"Invalid MCP config at {path}: 'mcp_servers' must be a map."
            )
        return servers

    def _parse_server(self, name: str, raw: Any) -> McpServerConfig:
        if not isinstance(raw, dict):
            raise ValueError("entry must be a map")
        transport = raw.get("transport")
        if transport == "stdio":
            return self._parse_stdio(name, raw)
        if transport == "http":
            return self._parse_http(name, raw)
        raise ValueError("transport must be 'stdio' or 'http'")

    def _parse_stdio(self, name: str, raw: dict[str, Any]) -> StdioServerConfig:
        self._reject_unknown(raw, _STDIO_FIELDS)
        command = self._nonempty_string(raw.get("command"), "command")
        args = raw.get("args", [])
        env = raw.get("env", {})
        if not isinstance(args, list) or any(not isinstance(item, str) for item in args):
            raise ValueError("args must be a list of strings")
        if not isinstance(env, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in env.items()
        ):
            raise ValueError("env must be a string map")
        expanded = tuple((key, self._expand(value)) for key, value in env.items())
        return StdioServerConfig(name, command, tuple(args), expanded)

    def _parse_http(self, name: str, raw: dict[str, Any]) -> HttpServerConfig:
        self._reject_unknown(raw, _HTTP_FIELDS)
        url = self._nonempty_string(raw.get("url"), "url")
        parsed = urlsplit(url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("url must be an http/https URL without userinfo")
        headers = raw.get("headers", {})
        if not isinstance(headers, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in headers.items()
        ):
            raise ValueError("headers must be a string map")
        expanded = tuple(
            (key, self._expand(value))
            for key, value in headers.items()
            if key.lower() not in _RESERVED_HEADERS
        )
        return HttpServerConfig(name, url, expanded)

    @staticmethod
    def _reject_unknown(raw: dict[str, Any], allowed: set[str]) -> None:
        unknown = set(raw) - allowed
        if unknown:
            raise ValueError("entry contains unknown or mixed transport fields")

    @staticmethod
    def _nonempty_string(value: Any, field: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must be a non-empty string")
        return value.strip()

    def _expand(self, value: str) -> str:
        # Any '${' not consumed by the strict token grammar is malformed.
        pieces: list[str] = []
        cursor = 0
        for match in _TOKEN.finditer(value):
            if "${" in value[cursor:match.start()]:
                raise ValueError("environment reference is malformed")
            pieces.append(value[cursor:match.start()])
            name = match.group(1)
            if name not in self._environment:
                raise ValueError(f"environment variable '{name}' is not defined")
            pieces.append(self._environment[name])
            cursor = match.end()
        if "${" in value[cursor:]:
            raise ValueError("environment reference is malformed")
        pieces.append(value[cursor:])
        return "".join(pieces)
