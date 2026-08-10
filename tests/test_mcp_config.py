from __future__ import annotations

from pathlib import Path

import pytest

from mewcode.mcp.config import McpConfigLoader, McpConfigPaths
from mewcode.mcp.models import HttpServerConfig, McpConfigError, StdioServerConfig


def paths(tmp_path: Path) -> McpConfigPaths:
    return McpConfigPaths(tmp_path / "user.yaml", tmp_path / "project.yaml")


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def test_missing_files_return_empty_config(tmp_path: Path) -> None:
    result = McpConfigLoader().load(paths(tmp_path))
    assert result.servers == ()
    assert result.diagnostics == ()


def test_files_without_mcp_servers_are_backward_compatible(tmp_path: Path) -> None:
    config_paths = paths(tmp_path)
    write(config_paths.user, "active: main\nprofiles: []\n")
    assert McpConfigLoader().load(config_paths).servers == ()


def test_project_server_replaces_whole_user_entry(tmp_path: Path) -> None:
    config_paths = paths(tmp_path)
    write(config_paths.user, """mcp_servers:
  shared: {transport: stdio, command: user, env: {X: value}}
""")
    write(config_paths.project, """mcp_servers:
  shared: {transport: stdio, command: project}
""")
    assert McpConfigLoader().load(config_paths).servers == (
        StdioServerConfig("shared", "project"),
    )


def test_distinct_servers_are_merged(tmp_path: Path) -> None:
    config_paths = paths(tmp_path)
    write(config_paths.user, "mcp_servers:\n  a: {transport: stdio, command: one}\n")
    write(config_paths.project, "mcp_servers:\n  b: {transport: http, url: https://example.test/mcp}\n")
    assert [s.name for s in McpConfigLoader().load(config_paths).servers] == ["a", "b"]


def test_server_names_must_be_nonempty_strings(tmp_path: Path) -> None:
    config_paths = paths(tmp_path)
    write(config_paths.user, "mcp_servers:\n  '': {transport: stdio, command: x}\n")
    result = McpConfigLoader().load(config_paths)
    assert result.servers == () and len(result.diagnostics) == 1


def test_parses_stdio_server(tmp_path: Path) -> None:
    config_paths = paths(tmp_path)
    write(config_paths.user, """mcp_servers:
  local:
    transport: stdio
    command: python
    args: [-m, server]
    env: {MODE: test}
""")
    assert McpConfigLoader().load(config_paths).servers == (
        StdioServerConfig("local", "python", ("-m", "server"), (("MODE", "test"),)),
    )


def test_invalid_stdio_entries_are_isolated(tmp_path: Path) -> None:
    config_paths = paths(tmp_path)
    write(config_paths.user, """mcp_servers:
  bad: {transport: stdio, command: '', url: https://bad.test}
  good: {transport: stdio, command: python}
""")
    result = McpConfigLoader().load(config_paths)
    assert [s.name for s in result.servers] == ["good"]
    assert result.diagnostics[0].server_name == "bad"


def test_parses_http_server(tmp_path: Path) -> None:
    config_paths = paths(tmp_path)
    write(config_paths.user, "mcp_servers:\n  api: {transport: http, url: https://example.test/mcp}\n")
    assert McpConfigLoader().load(config_paths).servers == (
        HttpServerConfig("api", "https://example.test/mcp"),
    )


def test_invalid_http_entries_are_isolated(tmp_path: Path) -> None:
    config_paths = paths(tmp_path)
    write(config_paths.user, """mcp_servers:
  bad: {transport: http, url: file:///tmp/x}
  good: {transport: http, url: http://localhost/mcp}
""")
    assert [s.name for s in McpConfigLoader().load(config_paths).servers] == ["good"]


def test_expands_env_and_header_values(tmp_path: Path) -> None:
    config_paths = paths(tmp_path)
    write(config_paths.user, """mcp_servers:
  local: {transport: stdio, command: python, env: {TOKEN: 'x${A}-${B}${A}'}}
  api: {transport: http, url: https://example.test, headers: {Authorization: 'Bearer ${A}'}}
""")
    result = McpConfigLoader({"A": "one", "B": "two"}).load(config_paths)
    assert result.servers[0].env_overrides == (("TOKEN", "xone-twoone"),)
    assert result.servers[1].headers == (("Authorization", "Bearer one"),)


def test_missing_or_malformed_variable_skips_server(tmp_path: Path) -> None:
    config_paths = paths(tmp_path)
    write(config_paths.user, """mcp_servers:
  missing: {transport: stdio, command: x, env: {X: '${NOPE}'}}
  malformed: {transport: stdio, command: x, env: {X: '${BAD-NAME}'}}
""")
    result = McpConfigLoader({}).load(config_paths)
    assert result.servers == () and len(result.diagnostics) == 2


def test_command_args_and_url_are_not_expanded(tmp_path: Path) -> None:
    config_paths = paths(tmp_path)
    write(config_paths.user, """mcp_servers:
  local: {transport: stdio, command: '${CMD}', args: ['${ARG}']}
  api: {transport: http, url: 'https://example.test/${PATH}'}
""")
    servers = McpConfigLoader({"CMD": "bad", "ARG": "bad", "PATH": "bad"}).load(config_paths).servers
    assert servers[0].command == "${CMD}" and servers[0].args == ("${ARG}",)
    assert servers[1].url.endswith("/${PATH}")


def test_reserved_headers_are_ignored_case_insensitively(tmp_path: Path) -> None:
    config_paths = paths(tmp_path)
    write(config_paths.user, """mcp_servers:
  api:
    transport: http
    url: https://example.test
    headers: {content-TYPE: wrong, MCP-Session-ID: secret, X-Test: ok}
""")
    assert McpConfigLoader().load(config_paths).servers[0].headers == (("X-Test", "ok"),)


def test_file_level_yaml_error_is_fatal(tmp_path: Path) -> None:
    config_paths = paths(tmp_path)
    write(config_paths.user, "mcp_servers: [")
    with pytest.raises(McpConfigError) as error:
        McpConfigLoader().load(config_paths)
    assert str(config_paths.user) in str(error.value)


def test_diagnostics_do_not_leak_secret_values(tmp_path: Path) -> None:
    config_paths = paths(tmp_path)
    write(config_paths.user, "mcp_servers:\n  bad: {transport: stdio, command: x, env: {X: '${MISSING}'}}\n")
    result = McpConfigLoader({"SECRET": "sentinel-secret"}).load(config_paths)
    assert "sentinel-secret" not in repr(result.diagnostics)

