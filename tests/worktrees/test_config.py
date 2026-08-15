from pathlib import Path

from mewcode.worktrees.config import DEFAULT_RULE_PATHS, WorktreeConfigLoader
from mewcode.worktrees.models import WorktreeRuleKind


def test_defaults_are_frozen_and_optional(tmp_path: Path) -> None:
    snapshot = WorktreeConfigLoader().load(tmp_path / "missing.yaml")
    assert snapshot.error is None
    assert snapshot.config is not None
    assert tuple(str(rule.path) for rule in snapshot.config.rules) == DEFAULT_RULE_PATHS
    assert all(rule.kind is WorktreeRuleKind.COPY for rule in snapshot.config.rules)
    assert all(not rule.required for rule in snapshot.config.rules)
    assert not (tmp_path / "missing.yaml").exists()


def test_strict_config_merges_replacement_and_rejects_unknown(tmp_path: Path) -> None:
    path = tmp_path / "worktrees.yaml"
    path.write_text(
        "version: 1\nrules:\n  - type: copy\n    path: .mewcode/config.yaml\n    required: true\n  - type: link\n    path: node_modules\n    required: false\n",
        encoding="utf-8",
    )
    snapshot = WorktreeConfigLoader().load(path)
    assert snapshot.config is not None
    rules = {(rule.kind.value, str(rule.path)): rule for rule in snapshot.config.rules}
    assert rules[("copy", ".mewcode/config.yaml")].required
    assert ("link", "node_modules") in rules

    path.write_text("version: 1\nrules: []\nunknown: true\n", encoding="utf-8")
    invalid = WorktreeConfigLoader().load(path)
    assert invalid.config is None
    assert invalid.error


def test_duplicate_and_unsafe_rules_fail(tmp_path: Path) -> None:
    path = tmp_path / "worktrees.yaml"
    path.write_text(
        "version: 1\nrules:\n  - type: copy\n    path: ../secret\n    required: true\n",
        encoding="utf-8",
    )
    assert WorktreeConfigLoader().load(path).config is None
    path.write_text("version: 1\nversion: 1\nrules: []\n", encoding="utf-8")
    assert WorktreeConfigLoader().load(path).config is None


def test_documented_worktree_config_example_parses() -> None:
    path = Path(__file__).parents[2] / "examples" / "worktrees.yaml"
    snapshot = WorktreeConfigLoader().load(path)
    assert snapshot.config is not None
    kinds = {rule.kind for rule in snapshot.config.rules if rule.origin == "project"}
    assert kinds == {
        WorktreeRuleKind.COPY,
        WorktreeRuleKind.LINK,
        WorktreeRuleKind.GIT_HOOKS,
    }
