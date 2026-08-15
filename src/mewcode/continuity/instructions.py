from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import os
from pathlib import Path
import re

from .diagnostics import (
    ContinuityComponent,
    ContinuityDiagnostic,
    DiagnosticSeverity,
)
from .paths import ContinuityPaths

MAX_INCLUDE_DEPTH = 5
INCLUDE_PATTERN = re.compile(r"^\s*@include\s+(.+?)\s*$")


class InstructionScope(StrEnum):
    PROJECT_LOCAL = "project_local"
    PROJECT_ROOT = "project_root"
    USER = "user"


@dataclass(frozen=True)
class InstructionSource:
    scope: InstructionScope
    entry_path: Path
    sandbox_root: Path
    priority: int
    title: str


@dataclass(frozen=True)
class InstructionSnapshot:
    content: str = ""
    diagnostics: tuple[ContinuityDiagnostic, ...] = ()
    project_content: str = ""
    user_content: str = ""


class InstructionLoader:
    def load(self, paths: ContinuityPaths) -> InstructionSnapshot:
        sources = (
            InstructionSource(
                InstructionScope.PROJECT_LOCAL,
                paths.project_local_instructions,
                paths.workspace_root,
                100,
                "Project-local instructions",
            ),
            InstructionSource(
                InstructionScope.PROJECT_ROOT,
                paths.project_root_instructions,
                paths.workspace_root,
                200,
                "Project-root instructions",
            ),
            InstructionSource(
                InstructionScope.USER,
                paths.user_instructions,
                paths.user_root,
                300,
                "User instructions",
            ),
        )
        return self._load_sources(sources)

    def load_project(self, paths: ContinuityPaths) -> InstructionSnapshot:
        """Load only Worktree-local project layers, without reading user state."""
        return self._load_sources(
            (
                InstructionSource(
                    InstructionScope.PROJECT_LOCAL,
                    paths.project_local_instructions,
                    paths.workspace_root,
                    100,
                    "Project-local instructions",
                ),
                InstructionSource(
                    InstructionScope.PROJECT_ROOT,
                    paths.project_root_instructions,
                    paths.workspace_root,
                    200,
                    "Project-root instructions",
                ),
            )
        )

    def _load_sources(
        self,
        sources: tuple[InstructionSource, ...],
    ) -> InstructionSnapshot:
        sections: list[str] = []
        project_sections: list[str] = []
        user_sections: list[str] = []
        diagnostics: list[ContinuityDiagnostic] = []
        for source in sorted(sources, key=lambda item: item.priority):
            if not source.entry_path.exists():
                continue
            content = self._expand(
                source.entry_path,
                source,
                depth=0,
                visited=set(),
                diagnostics=diagnostics,
                entry=True,
            )
            if content.strip():
                rendered = f"### {source.title}\n{content.strip()}"
                sections.append(rendered)
                if source.scope is InstructionScope.USER:
                    user_sections.append(rendered)
                else:
                    project_sections.append(rendered)
        return InstructionSnapshot(
            "\n\n".join(sections),
            tuple(diagnostics),
            "\n\n".join(project_sections),
            "\n\n".join(user_sections),
        )

    def _expand(
        self,
        path: Path,
        source: InstructionSource,
        *,
        depth: int,
        visited: set[str],
        diagnostics: list[ContinuityDiagnostic],
        entry: bool = False,
    ) -> str:
        try:
            resolved = path.resolve(strict=True)
        except OSError:
            self._warn(diagnostics, "include_unavailable" if not entry else "entry_unreadable")
            return ""
        if not _is_within(resolved, source.sandbox_root):
            self._warn(diagnostics, "include_outside_scope")
            return ""
        key = os.path.normcase(str(resolved))
        if key in visited:
            self._warn(diagnostics, "include_repeated")
            return ""
        visited.add(key)
        try:
            text = resolved.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            self._warn(diagnostics, "include_unavailable" if not entry else "entry_unreadable")
            return ""
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        output: list[str] = []
        for line in text.splitlines(keepends=True):
            candidate = line.rstrip("\n")
            match = INCLUDE_PATTERN.fullmatch(candidate)
            if match is None:
                output.append(line)
                continue
            if depth >= MAX_INCLUDE_DEPTH:
                self._warn(diagnostics, "include_depth_exceeded")
                continue
            include_path = resolved.parent / match.group(1).strip()
            output.append(
                self._expand(
                    include_path,
                    source,
                    depth=depth + 1,
                    visited=visited,
                    diagnostics=diagnostics,
                )
            )
        return "".join(output)

    @staticmethod
    def _warn(
        diagnostics: list[ContinuityDiagnostic],
        code: str,
    ) -> None:
        messages = {
            "entry_unreadable": "An instruction entry could not be read.",
            "include_unavailable": "An included instruction file was unavailable.",
            "include_outside_scope": "An instruction include was outside its allowed scope.",
            "include_repeated": "A repeated or cyclic instruction include was skipped.",
            "include_depth_exceeded": "An instruction include exceeded the maximum depth.",
        }
        diagnostics.append(
            ContinuityDiagnostic(
                ContinuityComponent.INSTRUCTIONS,
                code,
                DiagnosticSeverity.WARNING,
                messages[code],
            )
        )


def _is_within(path: Path, root: Path) -> bool:
    normalized_path = os.path.normcase(str(path.resolve()))
    normalized_root = os.path.normcase(str(root.resolve()))
    try:
        return os.path.commonpath((normalized_path, normalized_root)) == normalized_root
    except ValueError:
        return False
