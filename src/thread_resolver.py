 
"""Helpers for selecting and managing Pull Request review threads."""
 
from __future__ import annotations
 
from typing import Any, Iterable
 
 
def finding_key(path: str, line: int, title: str) -> str:
    return f"{path}:{line}:{title.strip().lower()}"
 
 
def _flag(thread: dict, camel: str, snake: str) -> bool:
    """Read a boolean in GraphQL camelCase or MCP snake_case."""
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
    """Current line, or original line for outdated threads."""
    return (
        thread.get("line")
        or thread.get("originalLine")
        or thread.get("original_line")
    )
 
 
def is_ai_review_thread(thread: dict) -> bool:
    """Identify comments written in the AI agent's review format."""
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
 
 
def select_threads_to_resolve(
    threads: Iterable[Any],
) -> list[tuple[dict, str]]:
    """Select only outdated, unresolved AI review threads."""
    selected: list[tuple[dict, str]] = []
 
    for thread in threads or []:
        if not isinstance(thread, dict):
            continue
        if is_resolved(thread):
            continue
        if not thread.get("id"):
            continue
        if not is_ai_review_thread(thread):
            continue
        if is_outdated(thread):
            selected.append((thread, "thread is outdated by code changes"))
 
    return selected
 
 
def open_thread_keys(
    threads: Iterable[Any],
    exclude_ids: Iterable[str] = (),
) -> set[str]:
    """Return finding keys for open, current-code threads."""
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
 
 
async def reopen_thread_graphql(
    github_client, owner: str, repo: str, thread_id: str | None
) -> bool:
    if not thread_id:
        return False
    try:
        return bool(await github_client.reopen_thread(owner, repo, thread_id))
    except Exception:
        return False
 
 
async def resolve_thread_graphql(
    github_client, owner: str, repo: str, thread_id: str | None
) -> bool:
    if not thread_id:
        return False
    try:
        return bool(await github_client.resolve_thread(owner, repo, thread_id))
    except Exception:
        return False
 
 
__all__ = [
    "finding_key",
    "is_resolved",
    "is_outdated",
    "thread_comments",
    "thread_line",
    "is_ai_review_thread",
    "extract_thread_finding_key",
    "select_threads_to_resolve",
    "open_thread_keys",
    "reopen_thread_graphql",
    "resolve_thread_graphql",
]