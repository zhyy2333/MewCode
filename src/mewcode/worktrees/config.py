from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from .models import (
    MAX_RULES,
    SCHEMA_VERSION,
    WorktreeConfig,
    WorktreeConfigSnapshot,
    WorktreeInitRule,
    WorktreeRuleKind,
    WorktreeValidationError,
)


DEFAULT_RULE_PATHS = (
    ".mewcode/config.yaml",
    ".mewcode/permissions.local.yaml",
    ".mewcode/hooks.local.yaml",
    ".mewcode/instructions.md",
    ".mewcode/memory",
)
MAX_CONFIG_BYTES = 256 * 1024


class _StrictLoader(yaml.SafeLoader):
    pass


def _construct_mapping(loader, node, deep=False):
    result: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


def validate_rule_path(value: object) -> PurePosixPath:
    if not isinstance(value, str) or not value or value != value.strip():
        raise WorktreeValidationError("Rule path must be a non-empty repository-relative string.")
    if "\\" in value or value.startswith("/") or ":" in value or any(ord(ch) < 32 for ch in value):
        raise WorktreeValidationError("Rule path must use safe repository-relative syntax.")
    parts = value.split("/")
    if any(not part or part in {".", ".."} for part in parts):
        raise WorktreeValidationError("Rule path contains an unsafe segment.")
    path = PurePosixPath(*parts)
    if path.is_absolute():
        raise WorktreeValidationError("Rule path must be relative.")
    return path


def default_config() -> WorktreeConfig:
    return WorktreeConfig(
        SCHEMA_VERSION,
        tuple(
            WorktreeInitRule(
                WorktreeRuleKind.COPY,
                validate_rule_path(path),
                False,
                "default",
            )
            for path in DEFAULT_RULE_PATHS
        ),
    )


class WorktreeConfigLoader:
    def load(self, path: Path) -> WorktreeConfigSnapshot:
        try:
            return WorktreeConfigSnapshot(self._load(path), None)
        except (OSError, UnicodeError, yaml.YAMLError, WorktreeValidationError, ValueError) as exc:
            return WorktreeConfigSnapshot(None, f"Invalid Worktree configuration: {type(exc).__name__}.")

    def _load(self, path: Path) -> WorktreeConfig:
        base = default_config()
        if not path.exists():
            return base
        if path.is_symlink() or not path.is_file():
            raise WorktreeValidationError("Worktree config must be a regular file.")
        payload = path.read_bytes()
        if len(payload) > MAX_CONFIG_BYTES:
            raise WorktreeValidationError("Worktree config exceeds its size limit.")
        raw = yaml.load(payload.decode("utf-8"), Loader=_StrictLoader)
        if not isinstance(raw, dict):
            raise WorktreeValidationError("Worktree config must be a YAML object.")
        if set(raw) != {"version", "rules"}:
            raise WorktreeValidationError("Worktree config accepts only version and rules.")
        version = raw["version"]
        if isinstance(version, bool) or version != SCHEMA_VERSION:
            raise WorktreeValidationError("Unsupported Worktree config version.")
        rules_raw = raw["rules"]
        if not isinstance(rules_raw, list) or len(rules_raw) > MAX_RULES:
            raise WorktreeValidationError(f"Worktree config rules must be a list of at most {MAX_RULES} items.")
        project: list[WorktreeInitRule] = []
        seen: set[tuple[WorktreeRuleKind, PurePosixPath]] = set()
        for item in rules_raw:
            rule = self._parse_rule(item)
            key = (rule.kind, rule.path)
            if key in seen:
                raise WorktreeValidationError("Worktree config contains a duplicate rule.")
            seen.add(key)
            project.append(rule)
        replacements = {(rule.kind, rule.path): rule for rule in project}
        merged = [
            replacements.pop((rule.kind, rule.path), rule)
            for rule in base.rules
        ]
        merged.extend(rule for rule in project if (rule.kind, rule.path) in replacements)
        if len(merged) > MAX_RULES:
            raise WorktreeValidationError(f"Merged Worktree config exceeds {MAX_RULES} rules.")
        return WorktreeConfig(SCHEMA_VERSION, tuple(merged))

    @staticmethod
    def _parse_rule(value: Any) -> WorktreeInitRule:
        if not isinstance(value, dict) or set(value) != {"type", "path", "required"}:
            raise WorktreeValidationError("Each Worktree rule requires type, path, and required.")
        if not isinstance(value["required"], bool):
            raise WorktreeValidationError("Rule required must be a boolean.")
        try:
            kind = WorktreeRuleKind(value["type"])
        except (TypeError, ValueError) as exc:
            raise WorktreeValidationError("Unknown Worktree rule type.") from exc
        return WorktreeInitRule(kind, validate_rule_path(value["path"]), value["required"], "project")
