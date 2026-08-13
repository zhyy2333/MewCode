from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import os
import re


class MatchSubjectKind(StrEnum):
    TEXT = "text"
    PATH = "path"


class GlobPatternError(ValueError):
    pass


@dataclass(frozen=True)
class GlobToken:
    value: str
    escaped: bool = False


def tokenize_glob(pattern: str) -> tuple[GlobToken, ...]:
    if not isinstance(pattern, str):
        raise GlobPatternError("Glob pattern must be a string.")
    tokens: list[GlobToken] = []
    index = 0
    while index < len(pattern):
        character = pattern[index]
        if character != "\\":
            tokens.append(GlobToken(character))
            index += 1
            continue
        if index + 1 >= len(pattern) or pattern[index + 1] not in "\\*?[]":
            raise GlobPatternError(
                "Glob contains an invalid escape; use \\\\, \\*, \\?, \\[ or \\]."
            )
        tokens.append(GlobToken(pattern[index + 1], escaped=True))
        index += 2
    _validate_character_classes(tuple(tokens))
    return tuple(tokens)


def _validate_character_classes(tokens: tuple[GlobToken, ...]) -> None:
    inside = False
    content = 0
    for token in tokens:
        if token.escaped:
            if inside:
                content += 1
            continue
        if token.value == "[":
            if inside:
                raise GlobPatternError("Nested character classes are not supported.")
            inside = True
            content = 0
        elif token.value == "]":
            if not inside:
                raise GlobPatternError("Glob contains an unmatched ']'.")
            if content == 0:
                raise GlobPatternError("Glob contains an empty character class.")
            inside = False
        elif inside:
            content += 1
    if inside:
        raise GlobPatternError("Glob contains an unmatched '['.")


def glob_is_exact(pattern: str) -> bool:
    return not any(
        not token.escaped and token.value in {"*", "?", "["}
        for token in tokenize_glob(pattern)
    )


def glob_specificity(pattern: str) -> tuple[int, int, int]:
    tokens = tokenize_glob(pattern)
    exact = not any(
        not token.escaped and token.value in {"*", "?", "["} for token in tokens
    )
    fixed_text = sum(
        len(token.value)
        for token in tokens
        if token.escaped or token.value not in {"*", "?", "[", "]"}
    )
    return (int(exact), fixed_text, pattern.count("/") + 1)


def compile_glob(
    pattern: str,
    kind: MatchSubjectKind = MatchSubjectKind.TEXT,
) -> re.Pattern[str]:
    tokens = tokenize_glob(pattern)
    parts = ["^"]
    index = 0
    path_mode = kind is MatchSubjectKind.PATH
    star = "[^/]*" if path_mode else ".*"
    question = "[^/]" if path_mode else "."
    while index < len(tokens):
        token = tokens[index]
        if token.escaped:
            parts.append(re.escape(token.value))
        elif token.value == "*":
            if path_mode and index + 1 < len(tokens) and tokens[index + 1] == GlobToken("*"):
                if index + 2 < len(tokens) and tokens[index + 2] == GlobToken("/"):
                    parts.append("(?:.*/)?")
                    index += 2
                else:
                    parts.append(".*")
                    index += 1
            else:
                parts.append(star)
        elif token.value == "?":
            parts.append(question)
        elif token.value == "[":
            class_parts: list[str] = []
            index += 1
            while index < len(tokens) and not (
                tokens[index].value == "]" and not tokens[index].escaped
            ):
                value = tokens[index].value
                if value in {"\\", "]", "^"}:
                    value = "\\" + value
                class_parts.append(value)
                index += 1
            parts.append(("(?!/)" if path_mode else "") + "[" + "".join(class_parts) + "]")
        else:
            parts.append(re.escape(token.value))
        index += 1
    parts.append("$")
    flags = re.IGNORECASE if path_mode and os.name == "nt" else 0
    return re.compile("".join(parts), flags)


def glob_fullmatch(
    pattern: str,
    subject: str,
    kind: MatchSubjectKind = MatchSubjectKind.TEXT,
) -> bool:
    return compile_glob(pattern, kind).fullmatch(subject) is not None


def escape_exact_glob(value: str) -> str:
    escaped: list[str] = []
    for character in value:
        if character in {"\\", "*", "?", "[", "]"}:
            escaped.append("\\")
        escaped.append(character)
    return "".join(escaped)
