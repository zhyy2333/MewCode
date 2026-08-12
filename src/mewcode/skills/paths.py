from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .models import (
    FileStamp,
    MAX_PACKAGE_BYTES,
    MAX_PACKAGE_FILES,
    MAX_SKILLS_PER_LAYER,
    SkillDefinitionError,
    SkillFingerprint,
    SkillLayer,
    SkillSource,
)


@dataclass(frozen=True)
class SkillRoots:
    project: Path
    user: Path
    builtin: Path

    @classmethod
    def defaults(cls, workspace_root: Path) -> SkillRoots:
        return cls(
            project=workspace_root / ".mewcode" / "skills",
            user=Path.home() / ".mewcode" / "skills",
            builtin=Path(__file__).parent / "builtin",
        )

    def ordered(self) -> tuple[tuple[SkillLayer, Path], ...]:
        return (
            (SkillLayer.PROJECT, self.project),
            (SkillLayer.USER, self.user),
            (SkillLayer.BUILTIN, self.builtin),
        )


def discover_sources(roots: SkillRoots) -> tuple[SkillSource, ...]:
    sources: list[SkillSource] = []
    for layer, root in roots.ordered():
        sources.extend(discover_layer(root, layer))
    return tuple(sources)


def discover_layer(root: Path, layer: SkillLayer) -> tuple[SkillSource, ...]:
    if not root.exists():
        return ()
    if not root.is_dir():
        raise SkillDefinitionError(f"Skill root is not a directory: {root}")
    candidates: list[tuple[str, Path, Path | None]] = []
    for child in sorted(root.iterdir(), key=lambda item: (item.name.casefold(), item.name)):
        if child.is_symlink():
            continue
        if child.is_file() and child.suffix == ".md":
            candidates.append((child.stem, child, None))
        elif child.is_dir():
            entry = child / "SKILL.md"
            if entry.is_file() and not entry.is_symlink():
                candidates.append((child.name, entry, child))
    if len(candidates) > MAX_SKILLS_PER_LAYER:
        raise SkillDefinitionError(
            f"Skill layer '{root}' exceeds {MAX_SKILLS_PER_LAYER} entries."
        )
    result = [
        SkillSource(
            layer=layer,
            root=root.resolve(),
            entry_path=entry.resolve(),
            package_dir=package.resolve() if package else None,
            entry_name=name,
            fingerprint=fingerprint_source(root, entry, package),
        )
        for name, entry, package in candidates
    ]
    return tuple(result)


def fingerprint_source(root: Path, entry: Path, package: Path | None) -> SkillFingerprint:
    base = package or root
    files = (entry,) if package is None else tuple(_package_files(package))
    if len(files) > MAX_PACKAGE_FILES:
        raise SkillDefinitionError(
            f"Skill package '{package}' exceeds {MAX_PACKAGE_FILES} files."
        )
    stamps: list[FileStamp] = []
    total = 0
    for path in files:
        resolved = path.resolve(strict=True)
        _ensure_within(resolved, base.resolve())
        stat = resolved.stat()
        if not resolved.is_file():
            continue
        total += stat.st_size
        if total > MAX_PACKAGE_BYTES:
            raise SkillDefinitionError(
                f"Skill package '{base}' exceeds {MAX_PACKAGE_BYTES} bytes."
            )
        stamps.append(
            FileStamp(
                resolved.relative_to(base.resolve()).as_posix(),
                "file",
                stat.st_size,
                stat.st_mtime_ns,
                getattr(stat, "st_ino", None),
            )
        )
    return SkillFingerprint(str(root.resolve()), tuple(sorted(stamps)))


def _package_files(package: Path):
    for current, directories, filenames in os.walk(package, followlinks=False):
        current_path = Path(current)
        directories[:] = sorted(
            name
            for name in directories
            if not (current_path / name).is_symlink()
        )
        for filename in sorted(filenames):
            path = current_path / filename
            if path.is_symlink():
                raise SkillDefinitionError(f"Symbolic links are not allowed: {path}")
            yield path


def ensure_package_path(package: Path, value: str, *, must_exist: bool = True) -> Path:
    candidate = Path(value)
    resolved = candidate.resolve() if candidate.is_absolute() else (package / candidate).resolve()
    _ensure_within(resolved, package.resolve())
    if must_exist and (not resolved.exists() or not resolved.is_file()):
        raise SkillDefinitionError(f"Package file does not exist: {value}")
    return resolved


def _ensure_within(path: Path, parent: Path) -> None:
    try:
        path.relative_to(parent)
    except ValueError as exc:
        raise SkillDefinitionError(f"Path escapes Skill package: {path}") from exc
