from __future__ import annotations

import math
from pathlib import Path
from types import MappingProxyType
from typing import Mapping
from urllib.parse import urlsplit

import regex
import yaml

from mewcode.matching import GlobPatternError, tokenize_glob

from .events import is_allowed_field
from .models import (
    DEFAULT_HOOK_LIMITS,
    AgentHookAction,
    CommandHookAction,
    HookAction,
    HookCatalog,
    HookCondition,
    HookConditionClause,
    HookEvent,
    HookExecutionControl,
    HookLimits,
    HookLogic,
    HookMatchKind,
    HookRule,
    HookRuleKey,
    HookScalar,
    HookSource,
    HttpHookAction,
    PromptHookAction,
)


class HookConfigError(ValueError):
    def __init__(
        self,
        path: Path,
        rule_index: int | None,
        field_path: str,
        message: str,
    ) -> None:
        self.path = path
        self.rule_index = rule_index
        self.field_path = field_path
        self.message = message
        location = str(path)
        if rule_index is not None:
            location += f":hooks[{rule_index}]"
        if field_path:
            location += f".{field_path}"
        super().__init__(f"{location}: {message}")


class HookPaths:
    def __init__(
        self,
        user: Path,
        project: Path,
        project_local: Path,
    ) -> None:
        self.user = Path(user)
        self.project = Path(project)
        self.project_local = Path(project_local)

    @classmethod
    def for_workspace(
        cls,
        workspace: Path,
        *,
        user_home: Path | None = None,
    ) -> "HookPaths":
        root = Path(workspace).resolve()
        home = Path.home() if user_home is None else Path(user_home)
        return cls(
            home / ".mewcode" / "hooks.yaml",
            root / ".mewcode" / "hooks.yaml",
            root / ".mewcode" / "hooks.local.yaml",
        )

    def ordered(self) -> tuple[tuple[Path, HookSource], ...]:
        return (
            (self.user, HookSource.USER),
            (self.project, HookSource.PROJECT),
            (self.project_local, HookSource.PROJECT_LOCAL),
        )


class HookConfigLoader:
    def __init__(self, limits: HookLimits = DEFAULT_HOOK_LIMITS) -> None:
        self._limits = limits

    def load(self, paths: HookPaths) -> HookCatalog:
        merged: list[HookRule] = []
        for path, source in paths.ordered():
            merged.extend(self.load_file(path, source))
        if len(merged) > self._limits.merged_rules:
            raise HookConfigError(
                paths.project,
                None,
                "hooks",
                f"Merged Hook count exceeds {self._limits.merged_rules}.",
            )
        by_event: dict[HookEvent, list[HookRule]] = {}
        for rule in merged:
            by_event.setdefault(rule.event, []).append(rule)
        frozen_by_event = MappingProxyType(
            {event: tuple(rules) for event, rules in by_event.items()}
        )
        trust = any(
            rule.key.source is HookSource.PROJECT
            and isinstance(rule.action, (CommandHookAction, HttpHookAction))
            for rule in merged
        )
        return HookCatalog(tuple(merged), frozen_by_event, trust)

    def load_file(self, path: Path, source: HookSource) -> tuple[HookRule, ...]:
        path = Path(path)
        if not path.exists():
            return ()
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise HookConfigError(path, None, "", f"Cannot read YAML: {exc}") from exc
        if raw is None:
            raw = {"hooks": []}
        if not isinstance(raw, dict):
            raise HookConfigError(path, None, "", "Root must be a mapping.")
        self._expect_keys(path, None, "", raw, required={"hooks"})
        hooks = raw["hooks"]
        if not isinstance(hooks, list):
            raise HookConfigError(path, None, "hooks", "Must be a list.")
        if len(hooks) > self._limits.rules_per_file:
            raise HookConfigError(
                path,
                None,
                "hooks",
                f"Rule count exceeds {self._limits.rules_per_file}.",
            )
        resolved = path.resolve()
        return tuple(
            self._parse_rule(path, source, resolved, index, value)
            for index, value in enumerate(hooks)
        )

    def _parse_rule(
        self,
        display_path: Path,
        source: HookSource,
        resolved_path: Path,
        index: int,
        raw: object,
    ) -> HookRule:
        if not isinstance(raw, dict):
            raise HookConfigError(display_path, index, "", "Rule must be a mapping.")
        self._expect_keys(
            display_path,
            index,
            "",
            raw,
            required={"event", "action"},
            optional={"if"},
        )
        try:
            event = HookEvent(raw["event"])
        except (TypeError, ValueError) as exc:
            raise HookConfigError(
                display_path, index, "event", "Unknown Hook event."
            ) from exc
        condition = (
            self._parse_condition(display_path, index, event, raw["if"])
            if "if" in raw
            else None
        )
        action = self._parse_action(display_path, index, event, raw["action"])
        return HookRule(
            HookRuleKey(source, resolved_path, index), event, condition, action
        )

    def _parse_condition(
        self,
        path: Path,
        index: int,
        event: HookEvent,
        raw: object,
    ) -> HookCondition:
        if not isinstance(raw, dict):
            raise HookConfigError(path, index, "if", "Must be a mapping.")
        if set(raw) not in ({"all"}, {"any"}):
            raise HookConfigError(
                path, index, "if", "Must contain exactly one of 'all' or 'any'."
            )
        key = next(iter(raw))
        clauses = raw[key]
        if not isinstance(clauses, list) or not clauses:
            raise HookConfigError(path, index, f"if.{key}", "Must be a non-empty list.")
        if len(clauses) > self._limits.conditions_per_rule:
            raise HookConfigError(
                path,
                index,
                f"if.{key}",
                f"Condition count exceeds {self._limits.conditions_per_rule}.",
            )
        parsed = tuple(
            self._parse_clause(path, index, event, key, position, clause)
            for position, clause in enumerate(clauses)
        )
        return HookCondition(HookLogic(key), parsed)

    def _parse_clause(
        self,
        path: Path,
        index: int,
        event: HookEvent,
        logic: str,
        position: int,
        raw: object,
    ) -> HookConditionClause:
        prefix = f"if.{logic}[{position}]"
        if not isinstance(raw, dict):
            raise HookConfigError(path, index, prefix, "Clause must be a mapping.")
        self._expect_keys(
            path,
            index,
            prefix,
            raw,
            required={"field", "match", "value"},
            optional={"negate"},
        )
        field = raw["field"]
        if not isinstance(field, str) or not field or len(field) > self._limits.field_chars:
            raise HookConfigError(path, index, f"{prefix}.field", "Invalid field path.")
        if not is_allowed_field(event, field):
            raise HookConfigError(
                path, index, f"{prefix}.field", "Field is not available for this event."
            )
        try:
            match = HookMatchKind(raw["match"])
        except (TypeError, ValueError) as exc:
            raise HookConfigError(
                path, index, f"{prefix}.match", "Must be exact, glob, or regex."
            ) from exc
        value = raw["value"]
        if not self._is_scalar(value):
            raise HookConfigError(
                path, index, f"{prefix}.value", "Must be a finite JSON scalar."
            )
        if isinstance(value, str) and len(value) > self._limits.value_chars:
            raise HookConfigError(path, index, f"{prefix}.value", "Value is too long.")
        compiled: object | None = None
        if match is not HookMatchKind.EXACT and not isinstance(value, str):
            raise HookConfigError(
                path, index, f"{prefix}.value", "Glob and regex values must be strings."
            )
        if match is HookMatchKind.GLOB:
            try:
                tokenize_glob(value)
            except GlobPatternError as exc:
                raise HookConfigError(path, index, f"{prefix}.value", str(exc)) from exc
        elif match is HookMatchKind.REGEX:
            if len(value) > self._limits.regex_chars:
                raise HookConfigError(path, index, f"{prefix}.value", "Regex is too long.")
            try:
                compiled = regex.compile(value)
            except regex.error as exc:
                raise HookConfigError(
                    path, index, f"{prefix}.value", f"Invalid regex: {exc}"
                ) from exc
        negate = raw.get("negate", False)
        if type(negate) is not bool:
            raise HookConfigError(
                path, index, f"{prefix}.negate", "Must be a YAML boolean."
            )
        return HookConditionClause(field, match, value, negate, compiled)

    def _parse_action(
        self,
        path: Path,
        index: int,
        event: HookEvent,
        raw: object,
    ) -> HookAction:
        if not isinstance(raw, dict):
            raise HookConfigError(path, index, "action", "Must be a mapping.")
        action_type = raw.get("type")
        if action_type == "command":
            self._expect_keys(path, index, "action", raw, {"type", "command"}, {"timeout_seconds", "once", "background"})
            command = self._non_empty_string(path, index, "action.command", raw["command"])
            timeout = self._bounded_int(path, index, "action.timeout_seconds", raw.get("timeout_seconds", 60), 1, 600)
            control = self._control(path, index, event, raw)
            return CommandHookAction(command, timeout, control)
        if action_type == "prompt":
            self._expect_keys(path, index, "action", raw, {"type", "content"}, {"once"})
            content = self._non_empty_string(path, index, "action.content", raw["content"])
            if len(content.encode("utf-8")) > self._limits.prompt_bytes:
                raise HookConfigError(path, index, "action.content", "Prompt is too large.")
            return PromptHookAction(content, self._control(path, index, event, raw))
        if action_type == "http":
            self._expect_keys(path, index, "action", raw, {"type", "url"}, {"method", "headers", "timeout_seconds", "once", "background"})
            url = self._non_empty_string(path, index, "action.url", raw["url"])
            parts = urlsplit(url)
            if parts.scheme not in {"http", "https"} or not parts.netloc:
                raise HookConfigError(path, index, "action.url", "Must be an absolute HTTP(S) URL.")
            method = raw.get("method", "POST")
            if method not in {"POST", "PUT", "PATCH", "DELETE"}:
                raise HookConfigError(path, index, "action.method", "Unsupported HTTP method.")
            headers = raw.get("headers", {})
            if not isinstance(headers, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in headers.items()):
                raise HookConfigError(path, index, "action.headers", "Headers must map strings to strings.")
            timeout = self._bounded_int(path, index, "action.timeout_seconds", raw.get("timeout_seconds", 30), 1, 120)
            return HttpHookAction(url, method, MappingProxyType(dict(headers)), timeout, self._control(path, index, event, raw))
        if action_type == "agent":
            self._expect_keys(path, index, "action", raw, {"type", "task"}, {"once"})
            task = self._non_empty_string(path, index, "action.task", raw["task"])
            return AgentHookAction(task, self._control(path, index, event, raw))
        raise HookConfigError(path, index, "action.type", "Unknown action type.")

    def _control(
        self,
        path: Path,
        index: int,
        event: HookEvent,
        raw: Mapping[str, object],
    ) -> HookExecutionControl:
        once = raw.get("once", False)
        background = raw.get("background", False)
        if type(once) is not bool:
            raise HookConfigError(path, index, "action.once", "Must be a YAML boolean.")
        if type(background) is not bool:
            raise HookConfigError(path, index, "action.background", "Must be a YAML boolean.")
        if event is HookEvent.TOOL_BEFORE and background:
            raise HookConfigError(path, index, "action.background", "tool.before actions cannot run in background.")
        return HookExecutionControl(once, background)

    @staticmethod
    def _expect_keys(
        path: Path,
        index: int | None,
        prefix: str,
        raw: Mapping[object, object],
        required: set[str],
        optional: set[str] | None = None,
    ) -> None:
        optional = optional or set()
        keys = set(raw)
        unknown = keys - required - optional
        missing = required - keys
        if missing:
            field = sorted(missing)[0]
            raise HookConfigError(path, index, f"{prefix}.{field}".strip("."), "Required field is missing.")
        if unknown:
            field = str(sorted(unknown, key=str)[0])
            raise HookConfigError(path, index, f"{prefix}.{field}".strip("."), "Unknown field.")

    @staticmethod
    def _is_scalar(value: object) -> bool:
        if isinstance(value, bool) or isinstance(value, str):
            return True
        if type(value) is int:
            return True
        return type(value) is float and math.isfinite(value)

    @staticmethod
    def _non_empty_string(path: Path, index: int, field: str, value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise HookConfigError(path, index, field, "Must be a non-empty string.")
        return value

    @staticmethod
    def _bounded_int(path: Path, index: int, field: str, value: object, minimum: int, maximum: int) -> int:
        if type(value) is not int or not minimum <= value <= maximum:
            raise HookConfigError(path, index, field, f"Must be an integer from {minimum} to {maximum}.")
        return value
