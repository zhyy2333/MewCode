from datetime import datetime, timezone

import pytest

from mewcode.continuity import (
    MemoryAction,
    MemoryCategory,
    MemoryConfig,
    MemoryMutation,
    MemoryScope,
    MemoryTurn,
    MemoryUpdatePlan,
)
from mewcode.continuity.sanitization import MemoryTurnSanitizer, sanitize_text

NOW = datetime(2026, 8, 11, tzinfo=timezone.utc)


def test_memory_models_validate_boundaries() -> None:
    with pytest.raises(ValueError):
        MemoryConfig(index_max_lines=0)
    with pytest.raises(ValueError):
        MemoryUpdatePlan(2, ())
    with pytest.raises(ValueError):
        MemoryMutation(MemoryAction.DELETE, MemoryScope.PROJECT)
    with pytest.raises(ValueError):
        MemoryMutation(
            MemoryAction.UPSERT,
            MemoryScope.PROJECT,
            category=MemoryCategory.PROJECT_KNOWLEDGE,
            summary="summary",
            body="body",
            priority=6,
        )


def test_sanitizer_removes_secrets_and_internal_content() -> None:
    source = (
        "<analysis>private chain</analysis> Bearer abcdefghijklmnop "
        "api_key=super-secret-value sk-abcdefghijklmnopqrst"
    )
    clean = sanitize_text(source)
    assert "private chain" not in clean
    assert "abcdefghijklmnop" not in clean
    assert "super-secret-value" not in clean
    assert "sk-" not in clean


def test_turn_sanitizer_preserves_user_first_and_clips_assistant() -> None:
    turn = MemoryTurn("session", "important user text", "x" * 5000, NOW)
    clean = MemoryTurnSanitizer(max_bytes=1024).sanitize(turn)
    assert clean.user_text == "important user text"
    assert "clipped" in clean.assistant_final_text
    assert len((clean.user_text + clean.assistant_final_text).encode()) <= 1024
