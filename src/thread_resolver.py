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
# (posted before the marker existed) are recognised by their exact layout:
# a "**SEVERITY — Category**" header line plus a "**Recommendation:**" line.
AI_COMMENT_MARKER = "<!-- ai-review-agent:finding -->"
# Hidden marker for findings that are only reported in the summary review.
SUMMARY_MARKER_PREFIX = "<!-- ai-review-agent:summary-finding "
SUMMARY_MARKER_RE = re.compile(r"<!-- ai-review-agent:summary-finding ([0-9a-f]{16}) -->")
LEGACY_HEADER_RE = re.compile(
    r"^\*\*(CRITICAL|HIGH|MEDIUM|LOW|INFO) — (Security|Standards|Tests|Performance)\*\*$"
)
LEGACY_RECOMMENDATION = "**Recommendation:**"

# Who the agent is: one login, several logins, or None (unknown).
AgentLogins = str | Iterable[str] | None

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
    return _MENTION_RE.sub("@\u200b", value)


def sanitize_title(title: Any) -> str:
    """Single-line title that round-trips through `parse_comment_title`."""
    value = sanitize_text(title).replace("*", "").replace("—", "-")
    value = _WHITESPACE_RE.sub(" ", value).strip()
    return value or "Code review finding"


# ---------------------------------------------------------------------------
# Finding identity
# ---------------------------------------------------------------------------


_NON_WORD_RE = re.compile(r"[\W_]+")


def normalize_title(title: str) -> str:
    """Comparison form of a title: case, punctuation and spacing are ignored.

    A model that writes "in `find_user`" one run and "in find_user" the next
    (or "Hard-coded" versus "Hard\u2011coded") is still reporting the same issue.
    """
    return _NON_WORD_RE.sub(" ", sanitize_title(title)).strip().casefold()


def finding_key(path: str | None, line: int | None, title: str) -> str:
    """Stable identity of a finding: file, line (may be None) and title.

    The description is deliberately excluded so an LLM rephrasing the same
    issue is still recognised as the same finding.
    """
    line_part = "" if line is None else str(int(line))
    return f"{path or ''}:{line_part}:{normalize_title(title)}"


def finding_slot(path: str | None, line: int | None, category: str | None) -> str:
    """Where a finding sits: file, line and category, ignoring the wording.

    A model rewords titles from run to run ("Default admin password is empty" /
    "ADMIN_PASSWORD defaults to empty string"). The title key alone then lets the
    same issue be posted again on every run, so an open AI thread on the same
    line and category also counts as "already reported".
    """
    line_part = "" if line is None else str(int(line))
    return f"{path or ''}:{line_part}:{(category or '').strip().lower()}"


def summary_fingerprint(finding: Finding) -> str:
    """Line-independent fingerprint for findings reported only in the summary."""
    key = finding_key(finding.file, None, finding.title)
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def summary_marker(fingerprint: str) -> str:
    return f"{SUMMARY_MARKER_PREFIX}{fingerprint} -->"


def summary_fingerprints_from_reviews(
    reviews: Iterable[Any],
    agent_login: AgentLogins = None,
) -> set[str]:
    """Collect fingerprints embedded in the agent's earlier summary reviews."""
    logins = login_set(agent_login)
    found: set[str] = set()
    for review in reviews or []:
        if not isinstance(review, dict):
            continue
        if logins and _author_login(review) not in logins:
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
    "SEVERITY — Category" header (titles may themselves contain "—").
    """
    for text in str(body or "").split("\n"):
        text = text.strip()
        if len(text) > 4 and text.startswith("**") and text.endswith("**"):
            if LEGACY_HEADER_RE.match(text):
                continue
            candidate = text.strip("*").strip()
            if candidate:
                return candidate
    return None


def parse_comment_category(body: Any) -> str | None:
    """Category from the "**SEVERITY — Category**" header of an AI comment."""
    for text in str(body or "").split("\n"):
        match = LEGACY_HEADER_RE.match(text.strip())
        if match:
            return match.group(2).lower()
    return None


def _is_bold_line(line: str) -> bool:
    return len(line) > 4 and line.startswith("**") and line.endswith("**")


def is_ai_comment_body(body: Any) -> bool:
    """True for the agent's comment layouts.

    - current: contains the hidden AI_COMMENT_MARKER;
    - legacy: first line "**SEVERITY — Category**" or a bold-only title, and a
      line starting with "**Recommendation:**" (layouts written by earlier
      versions of the agent).

    Layout alone is not proof of ownership: callers that change threads also
    check the author (see `is_ai_review_thread`).
    """
    text = str(body or "")
    if AI_COMMENT_MARKER in text:
        return True
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if not lines:
        return False
    first = lines[0]
    headed = bool(LEGACY_HEADER_RE.match(first)) or _is_bold_line(first)
    has_recommendation = any(line.startswith(LEGACY_RECOMMENDATION) for line in lines[1:])
    return headed and has_recommendation


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


def login_set(agent_login: AgentLogins) -> frozenset[str]:
    if not agent_login:
        return frozenset()
    if isinstance(agent_login, str):
        return frozenset({agent_login})
    return frozenset(login for login in agent_login if login)


def _author_login(item: dict) -> str | None:
    author = item.get("author") or item.get("user")
    if isinstance(author, dict):
        return author.get("login")
    if isinstance(author, str) and author:
        return author
    return None


def is_ai_review_thread(thread: dict, agent_login: AgentLogins = None) -> bool:
    """True only for threads *started* by the AI agent.

    The first comment decides: a human replying inside an AI thread does not
    change its owner, and an AI-looking reply in a human thread does not make
    it an AI thread. When the agent's login(s) are known, the first comment's
    author must be one of them (a missing author does not match).
    """
    comments = thread_comments(thread)
    if not comments:
        return False
    first = comments[0]
    if not is_ai_comment_body(first.get("body")):
        return False
    logins = login_set(agent_login)
    return not logins or _author_login(first) in logins


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


def _eligible(thread: Any, agent_login: AgentLogins) -> bool:
    """Threads the agent may change: its own, with an ID, owner verified.

    Without the agent's login ownership cannot be verified, so nothing is
    eligible: the agent never resolves or reopens on comment format alone.
    """
    return (
        bool(login_set(agent_login))
        and isinstance(thread, dict)
        and bool(thread.get("id"))
        and is_ai_review_thread(thread, agent_login)
    )


def select_threads_to_resolve(
    threads: Iterable[Any],
    agent_login: AgentLogins = None,
) -> list[tuple[dict, str]]:
    """Unresolved AI threads that GitHub marks as outdated.

    Threads are never resolved merely because the latest LLM run did not repeat
    a finding (LLM output is not deterministic), and human threads are never
    touched. Returns nothing when `agent_login` is unknown.
    """
    return [
        (thread, "thread is outdated by code changes")
        for thread in threads or []
        if _eligible(thread, agent_login) and not is_resolved(thread) and is_outdated(thread)
    ]


def select_threads_to_reopen(
    threads: Iterable[Any],
    current_keys: Iterable[str],
    agent_login: AgentLogins = None,
) -> list[tuple[dict, str]]:
    """Resolved, still-current AI threads whose finding was reported again.

    Returns nothing when `agent_login` is unknown.
    """
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
    agent_login: AgentLogins = None,
) -> set[str]:
    """Finding keys of AI threads that still sit on current code.

    Outdated threads are excluded so a finding that moved can be reported
    again. Resolved threads count as "already reported" by default, so a
    finding a reviewer resolved is not posted again on every push.
    """
    keys = (
        extract_thread_finding_key(thread)
        for thread in _current_ai_threads(threads, exclude_ids, include_resolved, agent_login)
    )
    return {key for key in keys if key}


def _current_ai_threads(
    threads: Iterable[Any],
    exclude_ids: Iterable[str],
    include_resolved: bool,
    agent_login: AgentLogins,
) -> list[dict]:
    """AI threads that still sit on current code (not outdated, not excluded)."""
    excluded = set(exclude_ids)
    current: list[dict] = []
    for thread in threads or []:
        if not isinstance(thread, dict) or is_outdated(thread):
            continue
        if thread.get("id") and thread.get("id") in excluded:
            continue
        if is_resolved(thread) and not include_resolved:
            continue
        if is_ai_review_thread(thread, agent_login):
            current.append(thread)
    return current


def extract_thread_slot(thread: dict) -> str | None:
    comments = thread_comments(thread)
    path, line = thread.get("path"), thread_line(thread)
    category = parse_comment_category(comments[0].get("body")) if comments else None
    if not path or not line or not category:
        return None
    try:
        return finding_slot(path, int(line), category)
    except (TypeError, ValueError):
        return None


def existing_thread_slots(
    threads: Iterable[Any],
    exclude_ids: Iterable[str] = (),
    include_resolved: bool = True,
    agent_login: AgentLogins = None,
) -> set[str]:
    """Slots (file, line, category) already covered by an AI thread on current code."""
    slots = (
        extract_thread_slot(thread)
        for thread in _current_ai_threads(threads, exclude_ids, include_resolved, agent_login)
    )
    return {slot for slot in slots if slot}


def open_thread_keys(
    threads: Iterable[Any],
    exclude_ids: Iterable[str] = (),
    agent_login: AgentLogins = None,
) -> set[str]:
    """Keys of open (unresolved), current-code AI threads."""
    return existing_thread_keys(threads, exclude_ids, False, agent_login)


def _normalize_comment(comment: dict) -> dict:
    author = comment.get("author") or comment.get("user")
    if isinstance(author, str):
        return {**comment, "author": {"login": author}}
    return comment


def _normalize_mcp_thread(thread: dict) -> dict:
    """GitHub MCP v2 threads keep path/line on their comments, not the thread."""
    comments = [_normalize_comment(c) for c in thread_comments(thread)]
    first = comments[0] if comments else {}
    normalized = {**thread, "comments": comments}
    if not normalized.get("path"):
        normalized["path"] = first.get("path")
    if normalized.get("line") is None:
        normalized["line"] = first.get("line")
    if normalized.get("originalLine") is None and normalized.get("original_line") is None:
        normalized["originalLine"] = first.get("original_line") or first.get("originalLine")
    return normalized


def threads_from_mcp_response(response: Any) -> list[dict] | None:
    """Normalise the MCP `get_review_comments` response into thread dicts.

    Supports the `review_threads` shape (path/line copied from the first
    comment, string authors mapped to `{"login": ...}`) and a plain list of
    REST comments. Each REST comment becomes a pseudo-thread without an ID,
    usable for duplicate detection only; a null `line` means it is outdated.
    Returns None for unrecognised shapes.
    """
    if isinstance(response, dict):
        threads = response.get("review_threads")
        if isinstance(threads, list):
            return [_normalize_mcp_thread(t) for t in threads if isinstance(t, dict)]
        response = response.get("comments")
    if isinstance(response, list):
        return [
            {
                "id": None,
                "path": c.get("path"),
                "line": c.get("line"),
                "originalLine": c.get("original_line"),
                "isOutdated": c.get("line") is None,
                "comments": [_normalize_comment(c)],
            }
            for c in response
            if isinstance(c, dict)
        ]
    return None


__all__ = [
    "AI_COMMENT_MARKER",
    "LEGACY_HEADER_RE",
    "existing_thread_keys",
    "existing_thread_slots",
    "extract_thread_finding_key",
    "extract_thread_slot",
    "finding_key",
    "finding_slot",
    "parse_comment_category",
    "format_inline_comment",
    "is_ai_comment_body",
    "is_ai_review_thread",
    "is_outdated",
    "is_resolved",
    "login_set",
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
