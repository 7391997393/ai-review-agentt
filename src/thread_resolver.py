"""Review-thread parsing, AI comment formatting and duplicate detection.

This module is the single place that knows how an AI review comment looks.
`format_inline_comment` writes it and `parse_comment_title` /
`is_ai_review_thread` read it back, so the two can never drift apart.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from typing import Any

from src.schemas import Finding

# Hidden marker added to every inline comment the agent writes. Older comments
# (posted before the marker existed) are still recognised by LEGACY_AI_MARKERS.
AI_COMMENT_MARKER = "<!-- ai-review-agent:finding -->"
# Hidden marker for findings that are only reported in the summary review.
SUMMARY_MARKER_PREFIX = "<!-- ai-review-agent:summary-finding "
SUMMARY_MARKER_RE = re.compile(r"<!-- ai-review-agent:summary-finding ([0-9a-f]{16}) -->")
LEGACY_AI_MARKERS = ("**Recommendation:**", "** — ")

_MENTION_RE = re.compile(r"@(?=[A-Za-z0-9_-])")
_WHITESPACE_RE = re.compile(r"\s+")


# ---------------------------------------------------------------------------
# Sanitising untrusted model output
# ---------------------------------------------------------------------------


def sanitize_text(text: Any) -> str:
    """Neutralise model-generated text before it is posted to GitHub.

    The LLM output is untrusted (a PR can prompt-inject it), so it must not be
    able to @mention people/teams or forge the agent's hidden HTML markers.
    """
    value = str(text or "")
    value = value.replace("<!--", "&lt;!--").replace("-->", "--&gt;")
    return _MENTION_RE.sub("@​", value)


def sanitize_title(title: Any) -> str:
    """Single-line title that round-trips through `parse_comment_title`."""
    value = sanitize_text(title).replace("*", "").replace("—", "-")
    value = _WHITESPACE_RE.sub(" ", value).strip()
    return value or "Code review finding"


# ---------------------------------------------------------------------------
# Finding identity
# ---------------------------------------------------------------------------


def normalize_title(title: str) -> str:
    return _WHITESPACE_RE.sub(" ", sanitize_title(title)).strip().lower()


def finding_key(path: str | None, line: int | None, title: str) -> str:
    """Stable identity of a finding: file, line (may be None) and title.

    The description is deliberately excluded so an LLM rephrasing the same
    issue is still recognised as the same finding.
    """
    line_part = "" if line is None else str(int(line))
    return f"{path or ''}:{line_part}:{normalize_title(title)}"


def summary_fingerprint(finding: Finding) -> str:
    """Line-independent fingerprint for findings reported only in the summary."""
    key = finding_key(finding.file, None, finding.title)
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def summary_marker(fingerprint: str) -> str:
    return f"{SUMMARY_MARKER_PREFIX}{fingerprint} -->"


def summary_fingerprints_from_reviews(
    reviews: Iterable[Any],
    agent_login: str | None = None,
) -> set[str]:
    """Collect fingerprints embedded in the agent's earlier summary reviews."""
    found: set[str] = set()
    for review in reviews or []:
        if not isinstance(review, dict):
            continue
        if agent_login and _author_login(review) not in (None, agent_login):
            continue
        found.update(SUMMARY_MARKER_RE.findall(str(review.get("body") or "")))
    return found


# ---------------------------------------------------------------------------
# Inline comment format (write + read)
# ---------------------------------------------------------------------------


def format_inline_comment(finding: Finding) -> str:
    """Markdown body for an inline review comment."""
    return (
        f"**{finding.severity.upper()} — {finding.category.title()}**\n\n"
        f"**{sanitize_title(finding.title)}**\n\n"
        f"{sanitize_text(finding.description)}\n\n"
        f"**Recommendation:** {sanitize_text(finding.recommendation)}\n\n"
        f"{AI_COMMENT_MARKER}"
    )


def parse_comment_title(body: Any) -> str | None:
    """Return the finding title from an AI comment body.

    The title is the first bold-only line that is not the
    "SEVERITY — Category" header.
    """
    for text in str(body or "").splitlines():
        text = text.strip()
        if len(text) > 4 and text.startswith("**") and text.endswith("**"):
            candidate = text.strip("*").strip()
            if candidate and "—" not in candidate:
                return candidate
    return None


def is_ai_comment_body(body: Any) -> bool:
    text = str(body or "")
    return AI_COMMENT_MARKER in text or any(m in text for m in LEGACY_AI_MARKERS)


# ---------------------------------------------------------------------------
# Thread accessors (GraphQL camelCase and MCP snake_case)
# ---------------------------------------------------------------------------


def _flag(thread: dict, camel: str, snake: str) -> bool:
    return thread.get(camel, thread.get(snake)) is True


def is_resolved(thread: dict) -> bool:
    return _flag(thread, "isResolved", "is_resolved")


def is_outdated(thread: dict) -> bool:
    return _flag(thread, "isOutdated", "is_outdated")


def thread_comments(thread: dict) -> list[dict]:
    raw = thread.get("comments")
    if isinstance(raw, dict):
        raw = raw.get("nodes", [])
    if not isinstance(raw, list):
        return []
    return [comment for comment in raw if isinstance(comment, dict)]


def thread_line(thread: dict) -> Any:
    """Current line, or the original line for outdated threads."""
    return thread.get("line") or thread.get("originalLine") or thread.get("original_line")


def _author_login(item: dict) -> str | None:
    author = item.get("author") or item.get("user")
    if isinstance(author, dict):
        return author.get("login")
    return None


def is_ai_review_thread(thread: dict, agent_login: str | None = None) -> bool:
    """True only for threads *started* by the AI agent.

    The first comment decides: a human replying inside an AI thread does not
    change its owner, and an AI-looking reply in a human thread does not make
    it an AI thread. When the agent's login is known and GitHub returned the
    author, the author must match as well.
    """
    comments = thread_comments(thread)
    if not comments:
        return False
    first = comments[0]
    if not is_ai_comment_body(first.get("body")):
        return False
    author = _author_login(first)
    return not (agent_login and author and author != agent_login)


def extract_thread_finding_key(thread: dict) -> str | None:
    path = thread.get("path")
    line = thread_line(thread)
    comments = thread_comments(thread)
    title = parse_comment_title(comments[0].get("body")) if comments else None
    if not path or not line or not title:
        return None
    try:
        return finding_key(path, int(line), title)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Thread selection
# ---------------------------------------------------------------------------


def _eligible(thread: Any, agent_login: str | None) -> bool:
    return (
        isinstance(thread, dict)
        and bool(thread.get("id"))
        and is_ai_review_thread(thread, agent_login)
    )


def select_threads_to_resolve(
    threads: Iterable[Any],
    agent_login: str | None = None,
) -> list[tuple[dict, str]]:
    """Unresolved AI threads that GitHub marks as outdated.

    Threads are never resolved merely because the latest LLM run did not repeat
    a finding (LLM output is not deterministic), and human threads are never
    touched.
    """
    return [
        (thread, "thread is outdated by code changes")
        for thread in threads or []
        if _eligible(thread, agent_login) and not is_resolved(thread) and is_outdated(thread)
    ]


def select_threads_to_reopen(
    threads: Iterable[Any],
    current_keys: Iterable[str],
    agent_login: str | None = None,
) -> list[tuple[dict, str]]:
    """Resolved, still-current AI threads whose finding was reported again."""
    wanted = set(current_keys)
    selected: list[tuple[dict, str]] = []
    for thread in threads or []:
        if not _eligible(thread, agent_login) or not is_resolved(thread):
            continue
        if is_outdated(thread):
            continue
        key = extract_thread_finding_key(thread)
        if key and key in wanted:
            selected.append((thread, f"finding reported again ({key})"))
    return selected


def existing_thread_keys(
    threads: Iterable[Any],
    exclude_ids: Iterable[str] = (),
    include_resolved: bool = True,
) -> set[str]:
    """Finding keys of AI threads that still sit on current code.

    Outdated threads are excluded so a finding that moved can be reported
    again. Resolved threads count as "already reported" by default, so a
    finding a reviewer resolved is not posted again on every push.
    """
    excluded = set(exclude_ids)
    keys: set[str] = set()
    for thread in threads or []:
        if not isinstance(thread, dict) or is_outdated(thread):
            continue
        if thread.get("id") and thread.get("id") in excluded:
            continue
        if is_resolved(thread) and not include_resolved:
            continue
        if not is_ai_comment_body((thread_comments(thread) or [{}])[0].get("body")):
            continue
        key = extract_thread_finding_key(thread)
        if key:
            keys.add(key)
    return keys


def open_thread_keys(threads: Iterable[Any], exclude_ids: Iterable[str] = ()) -> set[str]:
    """Keys of open (unresolved), current-code AI threads."""
    return existing_thread_keys(threads, exclude_ids, include_resolved=False)


def threads_from_mcp_response(response: Any) -> list[dict] | None:
    """Normalise the MCP `get_review_comments` response into thread dicts.

    Supports the `review_threads` shape and a plain list of comments (each
    comment becomes a pseudo-thread without an ID, usable for duplicate
    detection only). Returns None for unrecognised shapes.
    """
    if isinstance(response, dict):
        threads = response.get("review_threads")
        if isinstance(threads, list):
            return [t for t in threads if isinstance(t, dict)]
        response = response.get("comments")
    if isinstance(response, list):
        return [
            {
                "id": None,
                "path": c.get("path"),
                "line": c.get("line") or c.get("original_line"),
                "comments": [c],
            }
            for c in response
            if isinstance(c, dict)
        ]
    return None


__all__ = [
    "AI_COMMENT_MARKER",
    "existing_thread_keys",
    "extract_thread_finding_key",
    "finding_key",
    "format_inline_comment",
    "is_ai_comment_body",
    "is_ai_review_thread",
    "is_outdated",
    "is_resolved",
    "open_thread_keys",
    "parse_comment_title",
    "sanitize_text",
    "sanitize_title",
    "select_threads_to_reopen",
    "select_threads_to_resolve",
    "summary_fingerprint",
    "summary_fingerprints_from_reviews",
    "summary_marker",
    "thread_comments",
    "thread_line",
    "threads_from_mcp_response",
]
