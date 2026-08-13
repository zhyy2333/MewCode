from __future__ import annotations

import pytest

from mewcode.matching import (
    GlobPatternError,
    MatchSubjectKind,
    escape_exact_glob,
    glob_fullmatch,
    glob_is_exact,
)


def test_text_glob_crosses_spaces_and_slashes() -> None:
    assert glob_fullmatch("git *", "git push origin/main")
    assert glob_fullmatch("a*b", "a / b")


def test_path_star_and_double_star() -> None:
    assert glob_fullmatch("src/*.py", "src/main.py", MatchSubjectKind.PATH)
    assert not glob_fullmatch("src/*.py", "src/pkg/main.py", MatchSubjectKind.PATH)
    assert glob_fullmatch("src/**/*.py", "src/pkg/main.py", MatchSubjectKind.PATH)
    assert glob_fullmatch("src/**/*.py", "src/main.py", MatchSubjectKind.PATH)


def test_escaped_metacharacters_are_exact() -> None:
    value = r"a*b?[x]\\z"
    escaped = escape_exact_glob(value)
    assert glob_is_exact(escaped)
    assert glob_fullmatch(escaped, value)


@pytest.mark.parametrize("pattern", ["x\\q", "x[", "x]", "x[]", "x[[a]]"])
def test_invalid_glob(pattern: str) -> None:
    with pytest.raises(GlobPatternError):
        glob_fullmatch(pattern, "anything")
