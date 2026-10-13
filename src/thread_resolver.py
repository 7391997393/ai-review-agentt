"""Decide which Pull Request review threads the agent may resolve.

This module is pure Python (no GitHub, MCP or LLM imports) so the rules can be
unit-tested without network access.

Safety rules:
* The agent only touches threads that it created itself (AI review threads).
* A thread is resolved only when GitHub marks it ``isOutdated`` (the commented
  code was changed). A finding that is merely missing from the latest AI run is
  NOT treated as "fixed", because the LLM may reword or skip an issue.
* Threads that are outdated or resolved never count for duplicate detection,
  so a still-valid finding can be posted again.
"""

from typing import Any, Iterable


def finding_key(path: str, line: int, title: str) -> str:
    return f"{path}:{line}:{title.strip().lower()}"


def _flag(thread: dict, camel: str, snake: str) -> bool:
    """Read a boolean that may be GraphQL camelCase or MCP snake_case."""
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
    return [c for c in raw if isinstance(c, dict)]


def thread_line(thread: dict) -> Any:
    """Current line, or the original line for outdated threads."""
    return (
        thread.get("line")
        or thread.get("originalLine")
        or thread.get("original_line")
    )


def is_ai_review_thread(thread: dict) -> bool:
    """True when a comment in the thread was written in the agent's format."""
    for comment in thread_comments(thread):
        body = str(comment.get("body", ""))
        if "**Recommendation:**" in body or "** — " in body:
            return True
    return False


def extract_thread_finding_key(thread: dict) -> str | None:
    path = thread.get("path")
    line = thread_line(thread)

    body = ""
    for comment in thread_comments(thread):
        if comment.get("body"):
            body = str(comment["body"])
            break

    if not path or not line or not body:
        return None

    title = ""
    for text in body.splitlines():
        text = text.strip()
        if text.startswith("**") and text.endswith("**"):
            candidate = text.strip("*").strip()
            if "—" not in candidate:
                title = candidate
                break

    if not title:
        return None

    try:
        return finding_key(path, int(line), title)
    except (TypeError, ValueError):
        return None


def select_threads_to_resolve(threads: Iterable[Any]) -> list[tuple[dict, str]]:
    """Return ``(thread, reason)`` for every thread that is safe to resolve."""
    selected: list[tuple[dict, str]] = []

    for thread in threads or []:
        if not isinstance(thread, dict):
            continue
        if is_resolved(thread):
            continue
        if not thread.get("id"):
            continue
        if not is_ai_review_thread(thread):
            continue  # never touch human reviewers' threads
        if is_outdated(thread):
            selected.append((thread, "thread is outdated by code changes"))

    return selected


def open_thread_keys(
    threads: Iterable[Any],
    exclude_ids: Iterable[str] = (),
) -> set[str]:
    """Finding keys of threads that are still open and still on current code.

    Used for duplicate detection. Resolved, outdated or just-resolved threads
    are ignored so their findings can be reported again if still valid.
    """
    excluded = set(exclude_ids)
    keys: set[str] = set()

    for thread in threads or []:
        if not isinstance(thread, dict):
            continue
        if is_resolved(thread) or is_outdated(thread):
            continue
        if thread.get("id") in excluded:
            continue

        key = extract_thread_finding_key(thread)
        if key:
            keys.add(key)

    return keys
