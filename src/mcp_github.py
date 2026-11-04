"""GitHub access: the official GitHub MCP Server plus direct GraphQL calls.

MCP is used for reading the pull request and writing the review. Review-thread
queries and resolve/unresolve mutations go straight to the GitHub GraphQL API
so the agent gets accurate thread IDs, outdated flags and confirmed results.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from src.config import Settings
from src.context_builder import ReviewContext, build_review_context

logger = logging.getLogger(__name__)

GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"
MAX_THREAD_PAGES = 20
MAX_REVIEW_PAGES = 10
MAX_FILE_PAGES = 30  # GitHub lists at most 3000 files per pull request.
FILES_PER_PAGE = 100
MCP_TOOLSETS = "repos,pull_requests,issues"


class GitHubError(RuntimeError):
    """A GitHub (MCP or GraphQL) operation failed."""


@dataclass
class PullRequestData:
    details: Any
    changed_files: list[dict[str, Any]] = field(default_factory=list)
    raw_diff: str | None = None


_THREADS_QUERY = """
query GetReviewThreads($owner: String!, $repo: String!, $pullNumber: Int!, $after: String) {
  viewer { login }
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $pullNumber) {
      reviewThreads(first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          isResolved
          isOutdated
          path
          line
          originalLine
          comments(first: 5) {
            nodes { body author { login } }
          }
        }
      }
    }
  }
}
"""

_REVIEWS_QUERY = """
query GetReviews($owner: String!, $repo: String!, $pullNumber: Int!, $after: String) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $pullNumber) {
      reviews(first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes { body author { login } }
      }
    }
  }
}
"""

_RESOLVE_MUTATION = """
mutation ResolveThread($threadId: ID!) {
  resolveReviewThread(input: {threadId: $threadId}) { thread { id isResolved } }
}
"""

_UNRESOLVE_MUTATION = """
mutation UnresolveThread($threadId: ID!) {
  unresolveReviewThread(input: {threadId: $threadId}) { thread { id isResolved } }
}
"""


def _as_list(value: Any, *keys: str) -> list[dict[str, Any]]:
    """Return a list of dicts from a list or from a dict wrapping one."""
    if isinstance(value, dict):
        for key in keys:
            if isinstance(value.get(key), list):
                value = value[key]
                break
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _connection(data: Any, *path: str) -> dict[str, Any]:
    """Walk a GraphQL response path, tolerating nulls at every level."""
    node = data
    for key in path:
        node = node.get(key) if isinstance(node, dict) else None
    return node if isinstance(node, dict) else {}


class GitHubMCPClient:
    """Small wrapper around the official GitHub MCP Server and GraphQL API."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._stdio_context: Any = None
        self._session_context: Any = None
        self.session: ClientSession | None = None
        self._http: httpx.AsyncClient | None = None
        self.viewer_login: str | None = None

    # -- lifecycle ---------------------------------------------------------

    async def connect(self) -> None:
        command = os.getenv("GITHUB_MCP_COMMAND", "docker")
        if command == "docker":
            args = [
                "run",
                "--rm",
                "-i",
                "-e",
                "GITHUB_PERSONAL_ACCESS_TOKEN",
                "-e",
                "GITHUB_TOOLSETS",
                self.settings.mcp_image,
            ]
        else:
            # A locally installed github-mcp-server binary.
            args = ["stdio", f"--toolsets={MCP_TOOLSETS}"]

        server = StdioServerParameters(
            command=command,
            args=args,
            env={
                "GITHUB_PERSONAL_ACCESS_TOKEN": self.settings.github_token,
                "GITHUB_TOOLSETS": MCP_TOOLSETS,
            },
        )
        logger.info("Starting GitHub MCP server (%s)", args[-1] if command == "docker" else command)

        self._stdio_context = stdio_client(server)
        read, write = await self._stdio_context.__aenter__()
        self._session_context = ClientSession(read, write)
        self.session = await self._session_context.__aenter__()
        await self.session.initialize()

    async def close(self) -> None:
        for name, ctx in (
            ("MCP session", self._session_context),
            ("MCP stdio", self._stdio_context),
        ):
            if ctx is None:
                continue
            try:
                await ctx.__aexit__(None, None, None)
            except Exception as exc:  # noqa: BLE001 - shutdown must not mask the real result
                logger.warning("Error while closing %s: %s", name, exc)
        self._session_context = self._stdio_context = self.session = None
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    # -- MCP ---------------------------------------------------------------

    async def call(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Call an MCP tool; raise GitHubError when the tool reports an error."""
        if not self.session:
            raise GitHubError("MCP session is not connected.")

        result = await self.session.call_tool(tool_name, arguments)

        text = "\n".join(
            item.text for item in getattr(result, "content", None) or [] if hasattr(item, "text")
        ).strip()
        method = arguments.get("method", "")
        if getattr(result, "isError", False):
            raise GitHubError(f"MCP tool {tool_name}({method}) failed: {text[:500]}")

        logger.debug("MCP %s(%s) returned %d chars", tool_name, method, len(text))

        structured = getattr(result, "structuredContent", None)
        if structured:
            return structured
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    async def fetch_pull_request(self, owner: str, repo: str, pull_number: int) -> PullRequestData:
        """Fetch PR details and all changed files (with per-file patches)."""
        base = {"owner": owner, "repo": repo, "pullNumber": pull_number}
        details = await self.call("pull_request_read", {**base, "method": "get"})

        files: list[dict[str, Any]] = []
        for page in range(1, MAX_FILE_PAGES + 1):
            batch = _as_list(
                await self.call(
                    "pull_request_read",
                    {**base, "method": "get_files", "perPage": FILES_PER_PAGE, "page": page},
                ),
                "files",
            )
            files.extend(batch)
            if len(batch) < FILES_PER_PAGE:
                break

        raw_diff = None
        if not any(f.get("patch") for f in files):
            # Older MCP servers may not return patches: fall back to the full diff.
            diff = await self.call("pull_request_read", {**base, "method": "get_diff"})
            raw_diff = diff if isinstance(diff, str) else json.dumps(diff, default=str)

        logger.info("Fetched pull request #%s with %d changed file(s)", pull_number, len(files))
        return PullRequestData(details=details, changed_files=files, raw_diff=raw_diff)

    def build_context(self, data: PullRequestData) -> ReviewContext:
        ctx = build_review_context(
            data.details,
            data.changed_files,
            self.settings.max_review_context_chars,
            raw_diff=data.raw_diff,
        )
        if ctx.truncated:
            logger.warning(
                "Review context truncated to %d chars; files not reviewed: %s",
                self.settings.max_review_context_chars,
                ", ".join(ctx.omitted_files) or "(partial hunks only)",
            )
        return ctx

    async def get_pull_request_context(self, owner: str, repo: str, pull_number: int) -> str:
        """Backward-compatible helper returning only the context text."""
        return self.build_context(await self.fetch_pull_request(owner, repo, pull_number)).text

    async def get_review_comments(self, owner: str, repo: str, pull_number: int) -> Any:
        """Existing review threads/comments via MCP (fallback path)."""
        return await self.call(
            "pull_request_read",
            {
                "owner": owner,
                "repo": repo,
                "pullNumber": pull_number,
                "method": "get_review_comments",
                "perPage": 100,
            },
        )

    async def create_review(self, owner: str, repo: str, pull_number: int, body: str) -> Any:
        """Create a pending review."""
        return await self.call(
            "pull_request_review_write",
            {
                "owner": owner,
                "repo": repo,
                "pullNumber": pull_number,
                "method": "create",
                "body": body,
            },
        )

    async def add_inline_comment(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        path: str,
        line: int,
        body: str,
    ) -> Any:
        """Add an inline comment to the current pending review."""
        return await self.call(
            "add_comment_to_pending_review",
            {
                "owner": owner,
                "repo": repo,
                "pullNumber": pull_number,
                "path": path,
                "line": line,
                "side": "RIGHT",
                "subjectType": "LINE",
                "body": body,
            },
        )

    async def submit_review(self, owner: str, repo: str, pull_number: int, body: str) -> Any:
        """Submit the pending review as a COMMENT review (never approve/block)."""
        return await self.call(
            "pull_request_review_write",
            {
                "owner": owner,
                "repo": repo,
                "pullNumber": pull_number,
                "method": "submit_pending",
                "event": "COMMENT",
                "body": body,
            },
        )

    async def delete_pending_review(self, owner: str, repo: str, pull_number: int) -> Any:
        """Delete the token account's pending review (cleanup after a failed submit)."""
        return await self.call(
            "pull_request_review_write",
            {"owner": owner, "repo": repo, "pullNumber": pull_number, "method": "delete_pending"},
        )

    # -- GraphQL -----------------------------------------------------------

    def _http_client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=30.0)
        return self._http

    async def execute_graphql(
        self, query: str, variables: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Execute a GraphQL request and return the parsed JSON body.

        Raises GitHubError on HTTP errors, non-JSON bodies and GraphQL errors.
        """
        headers = {
            "Authorization": f"token {self.settings.github_token}",
            "Accept": "application/vnd.github.v4+json",
            "User-Agent": "ai-review-agent",
        }
        payload = {"query": query, "variables": variables or {}}
        try:
            response = await self._http_client().post(
                GITHUB_GRAPHQL_URL, json=payload, headers=headers, timeout=30.0
            )
        except httpx.HTTPError as exc:
            raise GitHubError(
                f"GitHub GraphQL request failed: {type(exc).__name__}: {exc}"
            ) from exc

        if response.status_code != 200:
            raise GitHubError(
                f"GitHub GraphQL HTTP error {response.status_code}: {str(response.text)[:500]}"
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise GitHubError("GitHub GraphQL returned a non-JSON response") from exc
        if not isinstance(data, dict):
            raise GitHubError("GitHub GraphQL returned an unexpected response shape")

        errors = data.get("errors")
        if errors:
            messages = [e.get("message", str(e)) if isinstance(e, dict) else str(e) for e in errors]
            raise GitHubError(f"GitHub GraphQL error: {'; '.join(messages)}")
        return data

    async def _paginate(
        self, query: str, variables: dict[str, Any], path: tuple[str, ...], max_pages: int
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        nodes: list[dict[str, Any]] = []
        cursor: str | None = None
        first_result: dict[str, Any] = {}
        for page in range(max_pages):
            result = await self.execute_graphql(query, {**variables, "after": cursor})
            if page == 0:
                first_result = result
            connection = _connection(result, "data", *path)
            nodes.extend(n for n in connection.get("nodes") or [] if isinstance(n, dict))
            page_info = connection.get("pageInfo") or {}
            if not page_info.get("hasNextPage") or not page_info.get("endCursor"):
                return nodes, first_result
            cursor = page_info["endCursor"]
        logger.warning(
            "Stopped after %d pages of %s; results may be incomplete", max_pages, path[-1]
        )
        return nodes, first_result

    async def get_review_threads_graphql(
        self, owner: str, repo: str, pull_number: int
    ) -> list[dict[str, Any]]:
        """Fetch all review threads (follows pagination). Also records the viewer login."""
        threads, first = await self._paginate(
            _THREADS_QUERY,
            {"owner": owner, "repo": repo, "pullNumber": pull_number},
            ("repository", "pullRequest", "reviewThreads"),
            MAX_THREAD_PAGES,
        )
        self.viewer_login = _connection(first, "data", "viewer").get("login") or self.viewer_login
        return threads

    async def get_reviews_graphql(
        self, owner: str, repo: str, pull_number: int
    ) -> list[dict[str, Any]]:
        """Fetch the bodies and authors of all submitted reviews on the PR."""
        reviews, _ = await self._paginate(
            _REVIEWS_QUERY,
            {"owner": owner, "repo": repo, "pullNumber": pull_number},
            ("repository", "pullRequest", "reviews"),
            MAX_REVIEW_PAGES,
        )
        return reviews

    async def _set_thread_resolution(self, thread_id: str, resolve: bool) -> dict[str, Any]:
        if not isinstance(thread_id, str) or not thread_id.strip():
            raise GitHubError("A review thread ID is required.")

        mutation, field_name = (
            (_RESOLVE_MUTATION, "resolveReviewThread")
            if resolve
            else (_UNRESOLVE_MUTATION, "unresolveReviewThread")
        )
        result = await self.execute_graphql(mutation, {"threadId": thread_id})
        thread = _connection(result, "data", field_name, "thread")
        if not thread:
            raise GitHubError(f"{field_name} mutation returned no thread data for {thread_id}")
        if thread.get("isResolved") is not resolve:
            expected = str(resolve).lower()
            raise GitHubError(
                f"{field_name} mutation did not set isResolved={expected} for {thread_id}"
            )
        return thread

    async def resolve_thread(self, thread_id: str) -> dict[str, Any]:
        """Resolve a review thread. Returns the thread only when GitHub confirms it."""
        return await self._set_thread_resolution(thread_id, resolve=True)

    async def reopen_thread(self, thread_id: str) -> dict[str, Any]:
        """Unresolve (reopen) a review thread via `unresolveReviewThread`."""
        return await self._set_thread_resolution(thread_id, resolve=False)


__all__ = ["GitHubError", "GitHubMCPClient", "PullRequestData"]
