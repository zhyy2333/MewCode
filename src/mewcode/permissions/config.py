from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import tempfile
from typing import Any

import yaml

from mewcode.tools import Workspace

from .models import (
    PermissionEffect,
    PermissionRule,
    PermissionRuleSets,
    PermissionTarget,
    RuleScope,
)
from .rules import PermissionRuleError, parse_permission_rule


class PermissionConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class PermissionPaths:
    user: Path
    project: Path
    project_local: Path

    @classmethod
    def for_workspace(
        cls,
        workspace: Workspace,
        user_home: Path | None = None,
    ) -> PermissionPaths:
        home = (user_home or Path.home()).resolve()
        project_dir = workspace.root / ".mewcode"
        return cls(
            user=home / ".mewcode" / "permissions.yaml",
            project=project_dir / "permissions.yaml",
            project_local=project_dir / "permissions.local.yaml",
        )


class PermissionConfigLoader:
    def load(
        self,
        paths: PermissionPaths,
        known_tools: set[str],
    ) -> PermissionRuleSets:
        return PermissionRuleSets(
            session=(),
            project_local=self.load_file(
                paths.project_local, RuleScope.PROJECT_LOCAL, known_tools
            ),
            project=self.load_file(paths.project, RuleScope.PROJECT, known_tools),
            user=self.load_file(paths.user, RuleScope.USER, known_tools),
        )

    def load_file(
        self,
        path: Path,
        scope: RuleScope,
        known_tools: set[str],
    ) -> tuple[PermissionRule, ...]:
        if not path.exists():
            return ()
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            return _parse_document(raw, scope, known_tools)
        except (OSError, UnicodeError, yaml.YAMLError, PermissionRuleError, ValueError) as exc:
            raise PermissionConfigError(f"Invalid permission config at {path}: {exc}") from exc


def _parse_document(
    raw: Any,
    scope: RuleScope,
    known_tools: set[str],
) -> tuple[PermissionRule, ...]:
    if not isinstance(raw, dict):
        raise ValueError("root must be a YAML object")
    if set(raw) - {"rules"}:
        raise ValueError("root contains unknown fields")
    items = raw.get("rules", [])
    if not isinstance(items, list):
        raise ValueError("'rules' must be a list")
    rules: list[PermissionRule] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict) or set(item) != {"rule", "result"}:
            raise ValueError(
                f"rules[{index}] must contain only 'rule' and 'result'"
            )
        expression = item["rule"]
        result = item["result"]
        if not isinstance(expression, str) or not isinstance(result, str):
            raise ValueError(f"rules[{index}] fields must be strings")
        rules.append(parse_permission_rule(expression, result, scope, known_tools))
    return tuple(rules)


class PermissionConfigWriter:
    def __init__(
        self,
        path: Path,
        known_tools: set[str],
        loader: PermissionConfigLoader | None = None,
    ) -> None:
        self._path = path
        self._known_tools = set(known_tools)
        self._loader = loader or PermissionConfigLoader()

    def add_local_allow(self, target: PermissionTarget) -> tuple[PermissionRule, ...]:
        current = self._loader.load_file(
            self._path, RuleScope.PROJECT_LOCAL, self._known_tools
        )
        expression = target.exact_rule()
        if any(
            rule.expression == expression and rule.effect == PermissionEffect.ALLOW
            for rule in current
        ):
            return current

        document = {
            "rules": [
                {"rule": rule.expression, "result": rule.effect.value}
                for rule in current
            ]
            + [{"rule": expression, "result": PermissionEffect.ALLOW.value}]
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            descriptor, raw_path = tempfile.mkstemp(
                prefix=f".{self._path.name}.", suffix=".tmp", dir=self._path.parent
            )
            temporary_path = Path(raw_path)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                yaml.safe_dump(document, stream, sort_keys=False, allow_unicode=True)
                stream.flush()
                os.fsync(stream.fileno())
            updated = self._loader.load_file(
                temporary_path, RuleScope.PROJECT_LOCAL, self._known_tools
            )
            os.replace(temporary_path, self._path)
            temporary_path = None
            return updated
        except PermissionConfigError:
            raise
        except OSError as exc:
            raise PermissionConfigError(
                f"Could not update permission config at {self._path}: {exc}"
            ) from exc
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass
