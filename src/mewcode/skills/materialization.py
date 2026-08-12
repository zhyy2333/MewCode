from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
import shutil
import tempfile

from .models import SkillDefinition, SkillDefinitionError, SkillFingerprint
from .paths import fingerprint_source


@dataclass(frozen=True)
class MaterializedSkill:
    name: str
    root: Path
    source_fingerprint: SkillFingerprint


class SkillMaterializer:
    def __init__(self, runtime_root: Path | None = None) -> None:
        self._owned_root = runtime_root is None
        self._root = runtime_root or Path(tempfile.mkdtemp(prefix="mewcode-skills-"))
        self._root.mkdir(parents=True, exist_ok=True)
        self._active: set[Path] = set()

    def materialize(self, definition: SkillDefinition) -> MaterializedSkill | None:
        package = definition.source.package_dir
        if package is None:
            return None
        before = fingerprint_source(
            definition.source.root, definition.source.entry_path, package
        )
        if before != definition.source.fingerprint:
            raise SkillDefinitionError(
                f"Skill '{definition.name}' changed before activation; retry after refresh."
            )
        target = Path(tempfile.mkdtemp(prefix=f"{definition.name}-", dir=self._root))
        try:
            for current, directories, filenames in os.walk(package, followlinks=False):
                current_path = Path(current)
                directories[:] = sorted(directories)
                relative = current_path.relative_to(package)
                destination = target / relative
                destination.mkdir(parents=True, exist_ok=True)
                for filename in sorted(filenames):
                    source = current_path / filename
                    if source.is_symlink():
                        raise SkillDefinitionError(f"Symbolic links are not allowed: {source}")
                    shutil.copy2(source, destination / filename)
            after = fingerprint_source(
                definition.source.root, definition.source.entry_path, package
            )
            if after != before:
                raise SkillDefinitionError(
                    f"Skill '{definition.name}' changed during activation."
                )
        except BaseException:
            shutil.rmtree(target, ignore_errors=True)
            raise
        self._active.add(target)
        return MaterializedSkill(definition.name, target, before)

    def release(self, materialized: MaterializedSkill | None) -> None:
        if materialized is None:
            return
        if materialized.root in self._active:
            shutil.rmtree(materialized.root, ignore_errors=True)
            self._active.discard(materialized.root)

    def close(self) -> None:
        for path in tuple(self._active):
            self.release(MaterializedSkill("", path, SkillFingerprint("", ())))
        if self._owned_root:
            shutil.rmtree(self._root, ignore_errors=True)
