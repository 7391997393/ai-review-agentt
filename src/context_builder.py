"""Build the Pull Request context that is sent to the LLM.

The diff is sent once (per-file patches), every visible line is prefixed with
its new-file line number so the model can cite valid inline-comment lines, and
truncation only ever happens at hunk boundaries.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
_BACKTICKS_RE = re.compile(r"`+")
MAX_DESCRIPTION_CHARS = 4000


@dataclass
class ReviewContext:
    text: str
    included_files: list[str] = field(default_factory=list)
    omitted_files: list[str] = field(default_factory=list)
    truncated: bool = False


def patch_lines(patch: str) -> list[str]:
    """Split a patch on newlines only.

    `str.splitlines()` would also split on form feeds, U+2028 and similar
    characters that are legal inside source lines, shifting line numbers.
    """
    lines = [line.removesuffix("\r") for line in patch.split("\n")]
    if lines and lines[-1] == "":
        lines.pop()  # trailing newline, not an empty context line
    return lines


_DIFF_HEADER_RE = re.compile(r"^diff --git a/\S+ b/(\S+)$", re.MULTILINE)


def split_hunks(patch: str) -> list[list[str]]:
    """Split a unified patch into hunks (each starting with its @@ header)."""
    hunks: list[list[str]] = []
    for raw in patch_lines(patch):
        if raw.startswith("@@"):
            hunks.append([raw])
        elif hunks:
            hunks[-1].append(raw)
    return hunks


def render_hunk(hunk: list[str]) -> str:
    """Render one hunk with new-file line numbers in a left gutter."""
    header = hunk[0]
    match = _HUNK_RE.match(header)
    current = int(match.group(1)) if match else None
    out = [header]
    for raw in hunk[1:]:
        marker, text = (raw[:1] or " "), raw[1:]
        if raw.startswith("\\"):
            out.append(f"{'':>6}  {raw}")
        elif marker == "-":
            out.append(f"{'':>6} -{text}")
        elif current is not None:
            out.append(f"{current:>6} {marker}{text}")
            current += 1
        else:
            out.append(f"{'':>6} {marker}{text}")
    return "\n".join(out)


def _fence(content: str) -> str:
    longest = max((len(m) for m in _BACKTICKS_RE.findall(content)), default=0)
    return "`" * max(3, longest + 1)


def _value(data: Any, *keys: str) -> Any:
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def describe_pull_request(details: Any) -> str:
    """Compact, model-friendly PR header (only fields useful for review)."""
    if isinstance(details, dict) and "title" not in details:
        for key in ("pull_request", "pullRequest"):
            if isinstance(details.get(key), dict):
                details = details[key]
                break
    if not isinstance(details, dict):
        return "## Pull Request\n(details unavailable)"
    lines = ["## Pull Request"]
    for label, value in (
        ("Title", details.get("title")),
        ("Author", _value(details, "user", "login")),
        ("Base", _value(details, "base", "ref")),
        ("Head", _value(details, "head", "ref")),
    ):
        if value:
            lines.append(f"{label}: {value}")
    body = str(details.get("body") or "").strip()
    if body:
        if len(body) > MAX_DESCRIPTION_CHARS:
            body = body[:MAX_DESCRIPTION_CHARS] + "\n[description truncated]"
        lines += ["", "Description:", body]
    return "\n".join(lines)


def _file_header(changed: dict[str, Any]) -> str:
    name = changed.get("filename") or changed.get("path") or "(unknown file)"
    status = changed.get("status") or "modified"
    header = f"### File: {name} ({status}"
    if changed.get("additions") is not None or changed.get("deletions") is not None:
        header += f", +{changed.get('additions', 0)}/-{changed.get('deletions', 0)}"
    header += ")"
    if changed.get("previous_filename"):
        header += f" — renamed from {changed['previous_filename']}"
    return header


def build_review_context(
    details: Any,
    changed_files: Iterable[Any] | None,
    max_chars: int,
    raw_diff: str | None = None,
) -> ReviewContext:
    """Assemble the review context within `max_chars`.

    `raw_diff` is only used when no per-file patches are available. The
    result never exceeds `max_chars`: when truncation is needed, room is
    reserved for the list of omitted files and the truncation note.
    """
    ctx = _assemble(details, changed_files, max_chars, raw_diff, tail_reserve=0)
    if not ctx.truncated:
        return ctx
    reserve = min(max(max_chars // 10, 200), 4000)
    return _assemble(details, changed_files, max_chars, raw_diff, tail_reserve=reserve)


def _tail(omitted: list[str], truncated: bool, limit: int) -> str:
    """Omitted-files list plus truncation note, clipped to `limit` chars."""
    note = "[Review context truncated because the Pull Request is too large.]"
    if not truncated:
        return ""
    if not omitted:
        return note
    header = "## Files not included (context limit)"
    lines = [header]
    used = len(header) + len(note) + 2
    for index, name in enumerate(omitted):
        rest = len(omitted) - index
        more = f"- … and {rest} more file(s)"
        entry = f"- {name}"
        # Keep room for a final "and N more" line unless this is the last name.
        needed = len(entry) + 1 + (0 if rest == 1 else len(more) + 1)
        if used + needed > limit:
            lines.append(more)
            break
        lines.append(entry)
        used += len(entry) + 1
    return "\n".join(lines) + "\n" + note


def _assemble(
    details: Any,
    changed_files: Iterable[Any] | None,
    max_chars: int,
    raw_diff: str | None,
    tail_reserve: int,
) -> ReviewContext:
    parts = [describe_pull_request(details), "", "## Changed files"]
    used = sum(len(p) + 1 for p in parts)
    ctx = ReviewContext(text="")
    content_limit = max_chars - tail_reserve

    files = [f for f in (changed_files or []) if isinstance(f, dict)]
    have_patches = any(f.get("patch") for f in files)

    if files and have_patches:
        for changed in files:
            name = str(changed.get("filename") or changed.get("path") or "")
            patch = changed.get("patch")
            header = _file_header(changed)
            if not patch:
                note = f"{header}\n(no textual diff available: binary, too large or rename only)\n"
                if used + len(note) + 1 <= content_limit:
                    parts.append(note)
                    used += len(note) + 1
                else:
                    ctx.omitted_files.append(name)
                    ctx.truncated = True
                continue

            rendered = [render_hunk(h) for h in split_hunks(patch)]
            fence = _fence(patch)
            truncation_note = 60  # "[N more hunk(s) omitted: context limit]"
            overhead = len(header) + 2 * len(fence) + len("diff") + 8 + truncation_note
            budget = content_limit - used - overhead
            kept: list[str] = []
            for hunk in rendered:
                if len(hunk) + 1 > budget:
                    break
                kept.append(hunk)
                budget -= len(hunk) + 1

            if not kept:
                ctx.omitted_files.append(name)
                ctx.truncated = True
                continue

            block = f"{header}\n{fence}diff\n" + "\n".join(kept) + f"\n{fence}"
            if len(kept) < len(rendered):
                block += f"\n[{len(rendered) - len(kept)} more hunk(s) omitted: context limit]"
                ctx.truncated = True
            parts.append(block + "\n")
            used += len(block) + 2
            ctx.included_files.append(name)
    elif raw_diff:
        diff_text = str(raw_diff)
        fence_len = len(_fence(diff_text))
        budget = max(0, content_limit - used - 2 * fence_len - 8)
        all_paths = _DIFF_HEADER_RE.findall(diff_text)
        if len(diff_text) > budget:
            # Cut at the last hunk/file boundary that fits; never mid-hunk.
            cut = max(
                diff_text.rfind("\n@@", 0, budget), diff_text.rfind("\ndiff --git", 0, budget)
            )
            diff_text = diff_text[:cut] if cut > 0 else ""
            # Drop a trailing file header whose hunks were all cut off.
            last_header = diff_text.rfind("\ndiff --git")
            if last_header > diff_text.rfind("\n@@"):
                diff_text = diff_text[:last_header]
            ctx.truncated = True
        if all_paths:
            kept = set(_DIFF_HEADER_RE.findall(diff_text))
            ctx.included_files = [p for p in all_paths if p in kept]
            ctx.omitted_files = [p for p in all_paths if p not in kept]
        elif not ctx.truncated:
            ctx.included_files = [str(f.get("filename") or "") for f in files]
        if diff_text:
            fence = _fence(diff_text)
            parts.append(f"{fence}diff\n{diff_text}\n{fence}")
        else:
            parts.append("(diff too large to include)")
    else:
        parts.append("(no diff available)")

    tail = _tail(ctx.omitted_files, ctx.truncated, max_chars - used - 1)
    if tail:
        parts.append(tail)

    ctx.text = "\n".join(parts)
    if len(ctx.text) > max_chars:
        # Only reachable with a tiny budget (header alone too big): hard cap.
        ctx.text = ctx.text[:max_chars]
        ctx.truncated = True
    return ctx


__all__ = [
    "ReviewContext",
    "build_review_context",
    "describe_pull_request",
    "render_hunk",
    "split_hunks",
]
