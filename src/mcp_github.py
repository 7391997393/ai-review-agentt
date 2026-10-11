import json
import os
from typing import Any

import httpx

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from src.config import Settings


class GitHubMCPClient:
    """Small wrapper around the official GitHub MCP Server."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._stdio_context = None
        self._session_context = None
        self.session: ClientSession | None = None

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
                "ghcr.io/github/github-mcp-server",
            ]
        else:
            args = ["stdio", "--toolsets=all"]

        server = StdioServerParameters(
            command=command,
            args=args,
            env={
                "GITHUB_PERSONAL_ACCESS_TOKEN": self.settings.github_token,
                "GITHUB_TOOLSETS": "repos,pull_requests,issues",
            },
        )

        self._stdio_context = stdio_client(server)
        read, write = await self._stdio_context.__aenter__()

        self._session_context = ClientSession(read, write)
        self.session = await self._session_context.__aenter__()
        await self.session.initialize()

    async def close(self) -> None:
        if self._session_context:
            await self._session_context.__aexit__(None, None, None)

        if self._stdio_context:
            await self._stdio_context.__aexit__(None, None, None)

    async def call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> Any:
        if not self.session:
            raise RuntimeError("MCP session is not connected.")

        result = await self.session.call_tool(
            tool_name,
            arguments,
        )
        print("DEBUG MCP RESPONSE:", result)

        if getattr(result, "structuredContent", None):
            return result.structuredContent

        text_parts = []

        for item in getattr(result, "content", []):
            if hasattr(item, "text"):
                text_parts.append(item.text)

        text = "\n".join(text_parts).strip()

        if not text:
            return result

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    async def get_pull_request_context(
        self,
        owner: str,
        repo: str,
        pull_number: int,
    ) -> str:
        pr = await self.call(
            "pull_request_read",
            {
                "owner": owner,
                "repo": repo,
                "pullNumber": pull_number,
                "method": "get",
            },
        )

        diff = await self.call(
            "pull_request_read",
            {
                "owner": owner,
                "repo": repo,
                "pullNumber": pull_number,
                "method": "get_diff",
            },
        )

        changed_files = await self.call(
            "pull_request_read",
            {
                "owner": owner,
                "repo": repo,
                "pullNumber": pull_number,
                "method": "get_files",
                "perPage": 100,
            },
        )

        context = json.dumps(
            {
                "pull_request": pr,
                "changed_files": changed_files,
                "diff": diff,
            },
            indent=2,
            default=str,
        )
        max_chars = self.settings.max_review_context_chars

        if len(context) > max_chars:
            context = (
                context[:max_chars]
                + "\n\n[Review context truncated because the Pull Request is too large.]"
            )

        return context

    async def get_review_comments(
        self,
        owner: str,
        repo: str,
        pull_number: int,
    ) -> Any:
        """Get existing Pull Request review comments."""

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

    async def execute_graphql(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a direct GraphQL request against GitHub API.

        GitHub GraphQL accepts a PAT via the `token` auth scheme.
        """
        url = "https://api.github.com/graphql"
        headers = {
            "Authorization": f"token {self.settings.github_token}",
            "Accept": "application/vnd.github.v4+json",
            "User-Agent": "ai-review-agent",
        }
        payload = {"query": query, "variables": variables or {}}

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                json=payload,
                headers=headers,
                timeout=30.0,
            )

        if response.status_code != 200:
            raise RuntimeError(
                f"GitHub GraphQL HTTP error {response.status_code}: {response.text}"
            )

        data = response.json()
        if "errors" in data and data["errors"]:
            error_messages = [e.get("message", str(e)) for e in data["errors"]]
            raise RuntimeError(f"GitHub GraphQL error: {'; '.join(error_messages)}")

        return data

    async def get_review_threads_graphql(
        self,
        owner: str,
        repo: str,
        pull_number: int,
    ) -> list[dict[str, Any]]:
        """Fetch review threads for a pull request using direct GraphQL API."""
        query = """
        query GetReviewThreads($owner: String!, $repo: String!, $pullNumber: Int!) {
          repository(owner: $owner, name: $repo) {
            pullRequest(number: $pullNumber) {
              reviewThreads(first: 100) {
                nodes {
                  id
                  isResolved
                  isOutdated
                  path
                  line
                  comments(first: 5) {
                    nodes {
                      body
                    }
                  }
                }
              }
            }
          }
        }
        """
        variables = {
            "owner": owner,
            "repo": repo,
            "pullNumber": pull_number,
        }
        result = await self.execute_graphql(query, variables)
        pr_data = (
            result.get("data", {})
            .get("repository", {})
            .get("pullRequest", {})
        )
        if not pr_data:
            return []
        threads = pr_data.get("reviewThreads", {}).get("nodes", [])
        return threads or []

    async def resolve_thread_graphql(
        self,
        thread_id: str,
    ) -> dict[str, Any]:
        """Resolve a PR review thread using direct GraphQL mutation.

        Returns the resolved thread object only when GitHub confirms the thread is
        resolved. If GitHub does not confirm, treat it as a failure.
        """
        query = """
        mutation ResolveThread($threadId: ID!) {
          resolveReviewThread(input: {threadId: $threadId}) {
            thread {
              id
              isResolved
            }
          }
        }
        """
        variables = {"threadId": thread_id}
        result = await self.execute_graphql(query, variables)
        thread = (
            result.get("data", {})
            .get("resolveReviewThread", {})
            .get("thread", {})
        )

        if not thread:
            raise RuntimeError(
                f"resolveReviewThread mutation returned no thread data for {thread_id}"
            )

        is_resolved = thread.get("isResolved")
        if is_resolved is not True:
            raise RuntimeError(
                f"resolveReviewThread mutation did not set isResolved=true for {thread_id}"
            )

        return thread

    async def resolve_thread(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        thread_id: str,
    ) -> Any:
        """Resolve an existing Pull Request review thread using direct GraphQL."""
        return await self.resolve_thread_graphql(thread_id=thread_id)

    async def create_review(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        body: str,
    ) -> Any:
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

    async def submit_review(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        body: str,
    ) -> Any:
        """Submit the pending review as a normal comment review."""

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
