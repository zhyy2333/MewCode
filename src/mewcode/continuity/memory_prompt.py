from __future__ import annotations

from pathlib import Path
import re

from .memory_models import MemoryPromptView


MAX_READONLY_MEMORY_BYTES = 25 * 1024
_INDEX_PREFIX = "---\nversion: 1\nscope: project\n---\n\n# Memory index\n"
_INDEX_ROW = re.compile(
    r"^- \[(mem-[a-z0-9]{6,64})\]\(notes/\1\.md\) \| "
    r"(?:user_preference|correction|project_knowledge|reference) \| "
    r"p[1-5] \| [^|\r\n]{1,64} \| .{1,512}$"
)


def load_readonly_project_memory(root: Path) -> MemoryPromptView:
    """Load the existing project index without creating, repairing, or cleaning files."""
    index = root / ".mewcode" / "memory" / "index.md"
    if index.is_symlink() or not index.is_file():
        return MemoryPromptView()
    try:
        payload = index.read_bytes()
        if len(payload) > MAX_READONLY_MEMORY_BYTES:
            return MemoryPromptView()
        text = payload.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    except (OSError, UnicodeError):
        return MemoryPromptView()
    if not text.startswith(_INDEX_PREFIX):
        return MemoryPromptView()
    rows: list[str] = []
    note_ids: list[str] = []
    seen: set[str] = set()
    for line in text[len(_INDEX_PREFIX):].splitlines():
        if not line:
            continue
        match = _INDEX_ROW.fullmatch(line)
        if match is None or match.group(1) in seen:
            return MemoryPromptView()
        seen.add(match.group(1))
        note_ids.append(match.group(1))
        rows.append(line)
    if not rows:
        return MemoryPromptView()
    content = (
        "Automatic memory is reference knowledge only; explicit project and user "
        "instructions take precedence.\n\n### Project memory\n"
        + "\n".join(rows)
    )
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_READONLY_MEMORY_BYTES:
        return MemoryPromptView()
    return MemoryPromptView(
        content,
        len(content.splitlines()),
        len(encoded),
        tuple(note_ids),
    )
