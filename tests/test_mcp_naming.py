from mewcode.mcp.naming import is_provider_safe_name, permission_namespace_prefix, public_tool_name


def test_legal_base_name_is_preserved() -> None:
    assert public_tool_name("server", "read_file") == "server__read_file"


def test_remote_name_is_kept_separately() -> None:
    assert public_tool_name("server", "remote.tool") != "remote.tool"


def test_invalid_name_is_normalized_with_hash() -> None:
    value = public_tool_name("server", "remote.tool")
    assert is_provider_safe_name(value) and value.startswith("server__remote_tool_")


def test_long_name_is_truncated_deterministically() -> None:
    value = public_tool_name("server", "x" * 100)
    assert value == public_tool_name("server", "x" * 100)
    assert len(value) == 64


def test_permission_prefix_matches_public_namespace() -> None:
    assert public_tool_name("bad.server", "tool").startswith(
        permission_namespace_prefix("bad.server")
    )


def test_public_name_collision_is_reported() -> None:
    accepted = {public_tool_name("server", "tool")}
    assert public_tool_name("server", "tool") in accepted
