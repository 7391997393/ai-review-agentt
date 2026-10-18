"""Simple helpers for review thread reopen/resolve actions."""
from __future__ import annotations


async def reopen_thread_graphql(github_client, owner: str, repo: str, thread_id: str | None) -> bool:
    if not thread_id:
        return False
    try:
        return bool(await github_client.reopen_thread(owner, repo, thread_id))
    except Exception:
        return False


async def resolve_thread_graphql(github_client, owner: str, repo: str, thread_id: str | None) -> bool:
    if not thread_id:
        return False
    try:
        return bool(await github_client.resolve_thread(owner, repo, thread_id))
    except Exception:
        return False


__all__ = ["reopen_thread_graphql", "resolve_thread_graphql"]
