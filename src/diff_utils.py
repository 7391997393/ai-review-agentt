"""Unified-diff parsing and validation of inline comment targets."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from src.schemas import Finding

_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def parse_unified_patch(patch: str | None) -> dict[int, str]:
    """Map new-file line numbers to their text for lines visible in the diff.

    Only added ('+') and context (' ') lines exist on the RIGHT side of a PR
    diff, so only those can carry an inline comment. Deleted lines do not
    advance the new-file line counter.
    """
    lines: dict[int, str] = {}
    if not patch:
        return lines

    current: int | None = None
    for raw in patch.splitlines():
        match = _HUNK_RE.match(raw)
        if match:
            current = int(match.group(1))
            continue
        if current is None or raw.startswith("\\"):
            # Outside a hunk, or "\ No newline at end of file".
            continue
        marker = raw[:1]
        if marker == "+" or marker == " " or raw == "":
            lines[current] = raw[1:]
            current += 1
        elif marker == "-":
            continue
        else:
            # Anything else (e.g. a "diff --git" header) ends the hunk.
            current = None
    return lines


def is_line_in_patch(patch: str | None, line_number: int | None) -> bool:
    if line_number is None or not patch:
        return False
    return line_number in parse_unified_patch(patch)


def normalize_path(path: str | None) -> str:
    value = (path or "").strip().replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    return value.lstrip("/")


@dataclass(frozen=True)
class InlineTarget:
    """Result of validating a finding against the PR diff."""

    ok: bool
    path: str | None = None
    reason: str = ""


def _changed_file_name(changed: dict[str, Any]) -> str:
    return normalize_path(
        changed.get("filename")
        or changed.get("fileName")
        or changed.get("path")
        or changed.get("name")
    )


def index_changed_files(changed_files: Iterable[Any] | None) -> dict[str, dict[str, Any]]:
    """Index changed files by current path and by previous path (renames)."""
    index: dict[str, dict[str, Any]] = {}
    for changed in changed_files or []:
        if not isinstance(changed, dict):
            continue
        name = _changed_file_name(changed)
        if not name:
            continue
        index[name] = changed
        previous = normalize_path(changed.get("previous_filename"))
        if previous and previous not in index:
            index[previous] = changed
    return index


def validate_finding_against_changed_files(
    finding: Finding,
    changed_files: Iterable[Any] | dict[str, dict[str, Any]] | None,
) -> InlineTarget:
    """Decide whether a finding can be posted as an inline comment.

    A finding is postable only when its file is part of the PR, the file still
    exists (not deleted) and the line is an added/context line of the diff.
    Findings that fail here are still reported in the summary review.
    """
    index = changed_files if isinstance(changed_files, dict) else index_changed_files(changed_files)
    path = normalize_path(finding.file)
    if not path:
        return InlineTarget(False, reason="finding has no file path")
    if finding.line is None:
        return InlineTarget(False, reason="finding has no line number")

    changed = index.get(path)
    if changed is None and path[:2] in {"a/", "b/"}:
        path = path[2:]
        changed = index.get(path)
    if changed is None:
        return InlineTarget(False, reason=f"{path} is not part of the pull request diff")

    current_path = _changed_file_name(changed)
    if changed.get("status") == "removed":
        return InlineTarget(False, reason=f"{current_path} was deleted in this pull request")

    patch = changed.get("patch") or changed.get("diff") or changed.get("patch_text")
    if not patch:
        return InlineTarget(False, reason=f"no diff is available for {current_path}")
    if not is_line_in_patch(patch, finding.line):
        return InlineTarget(
            False, reason=f"line {finding.line} of {current_path} is not in the diff"
        )
    return InlineTarget(True, path=current_path)


__all__ = [
    "InlineTarget",
    "index_changed_files",
    "is_line_in_patch",
    "normalize_path",
    "parse_unified_patch",
    "validate_finding_against_changed_files",
]
