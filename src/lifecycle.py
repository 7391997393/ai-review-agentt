"""Lifecycle helpers for AI review findings.

This module keeps the review lifecycle state small and stable across review runs.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from typing import Any

STATE_MARKER = "ai-review-agentt-state:"


def encode_state(state: dict[str, Any]) -> str:
    """Encode review lifecycle state as a hidden HTML comment.

    The comment is intentionally wrapped in HTML so it does not render on the PR.
    """
    payload = json.dumps(state, separators=(",", ":"), sort_keys=True)
    encoded = base64.b64encode(payload.encode("utf-8")).decode("ascii")
    return f"<!-- {STATE_MARKER}{encoded} -->"


def decode_state(text: str | None) -> dict[str, Any]:
    """Decode hidden lifecycle state from a review comment body."""
    if not text:
        return {}
    match = re.search(rf"{re.escape(STATE_MARKER)}([A-Za-z0-9+/=]+)", text)
    if not match:
        return {}
    encoded = match.group(1)
    try:
        raw = base64.b64decode(encoded.encode("ascii")).decode("utf-8")
        value = json.loads(raw)
        if isinstance(value, dict):
            return value
    except Exception:
        pass
    return {}


def decode_state_from_text(text: str | None) -> dict[str, Any]:
    return decode_state(text)


def finding_key(finding: dict[str, Any] | Any) -> str:
    """Create a stable key for a single finding.

    The key intentionally uses file, line, title, severity and a digest of the
    description so tiny edits to a finding trigger a new detection rather than a
    false duplicate.
    """
    if hasattr(finding, "model_dump"):
        finding = finding.model_dump()
    if not isinstance(finding, dict):
        finding = {"file": "", "line": None, "title": str(finding), "description": ""}

    file = str(finding.get("file") or "")
    line = finding.get("line")
    title = str(finding.get("title") or "")
    desc = str(finding.get("description") or "")
    digest = hashlib.sha256(desc.encode("utf-8")).hexdigest()[:12]
    return f"{file}:{line}:{title.strip().lower()}:{digest}"


def parse_unified_patch(patch: str | None) -> dict[int, list[str]]:
    """Parse a unified diff into a mapping of new-file line numbers to lines."""
    if not patch:
        return {}

    changed: dict[int, list[str]] = {}
    current_line = 1
    in_hunk = False
    for raw in patch.splitlines():
        if raw.startswith("@@"):
            in_hunk = True
            match = re.search(r"\+([0-9]+)(?:,[0-9]+)?", raw)
            if match:
                current_line = int(match.group(1))
            continue

        if not in_hunk:
            continue

        if raw.startswith("+") and not raw.startswith("++"):
            changed.setdefault(current_line, []).append(raw[1:])
            current_line += 1
        elif raw.startswith(" "):
            changed.setdefault(current_line, []).append(raw[1:])
            current_line += 1
        elif raw.startswith("-") and not raw.startswith("--"):
            # deletion does not advance the new-file line pointer
            continue
        elif raw.startswith("\\"):
            continue

    return changed


def is_line_in_patch(patch: str | None, line_number: int | None) -> bool:
    if line_number is None:
        return False
    if not patch:
        return False
    return line_number in parse_unified_patch(patch)


__all__ = [
    "STATE_MARKER",
    "encode_state",
    "decode_state",
    "decode_state_from_text",
    "finding_key",
    "parse_unified_patch",
    "is_line_in_patch",
]
