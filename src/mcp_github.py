import json
import os
from typing import Any

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
        # Locally, set GITHUB_MCP_COMMAND to the downloaded
        # github-mcp-server executable. GitHub Actions can continue using
        # Docker on the Ubuntu runner.
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
                "GITHUB_TOOLSETS": "repos,pull_requests",
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

    async def call(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        if not self.session:
            raise RuntimeError("MCP session is not connected.")

        result = await self.session.call_tool(tool_name, arguments)

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
        self, owner: str, repo: str, pull_number: int
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

        return json.dumps(
            {
                "pull_request": pr,
                "changed_files": changed_files,
                "diff": diff,
            },
            indent=2,
            default=str,
        )

    async def create_review(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        body: str,
        event: str = "COMMENT",
    ) -> Any:
        return await self.call(
            "pull_request_review_write",
            {
                "owner": owner,
                "repo": repo,
                "pullNumber": pull_number,
                "method": "create",
                "body": body,
                "event": event,
            },
        )
