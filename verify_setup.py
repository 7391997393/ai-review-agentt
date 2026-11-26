"""Read-only pre-flight check: MCP server, GitHub token and repository access.

Run before the first review:  python verify_setup.py
It never posts, resolves or changes anything on GitHub.
"""

from __future__ import annotations

import asyncio
import os
import sys

from dotenv import load_dotenv

from src.config import Settings
from src.mcp_github import GitHubError, GitHubMCPClient, resolve_mcp_launch

REQUIRED_TOOLS = {
    "pull_request_read",
    "pull_request_review_write",
    "add_comment_to_pending_review",
}


def _report(ok: bool, label: str, detail: str = "") -> bool:
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f": {detail}" if detail else ""))
    return ok


async def run_checks() -> bool:
    settings = Settings.from_env()
    _report(True, "Environment variables", "CG_API_KEY, CG_MODEL and GitHub token are set")
    if not settings.github_owner or not settings.github_repo:
        return _report(False, "GITHUB_OWNER / GITHUB_REPO", "both are required")

    command, _ = resolve_mcp_launch(settings.mcp_image)
    _report(True, "MCP launcher resolved", command)

    github = GitHubMCPClient(settings)
    ok = True
    try:
        await github.connect()
        _report(True, "MCP session initialised")

        tools = {tool.name for tool in (await github.session.list_tools()).tools}
        missing = sorted(REQUIRED_TOOLS - tools)
        ok &= _report(not missing, "Required MCP tools", f"missing: {missing}" if missing else "")

        # GraphQL gives the token's account; it also proves the PAT is valid.
        result = await github.execute_graphql(
            "query($o:String!,$r:String!){viewer{login} "
            "repository(owner:$o,name:$r){nameWithOwner}}",
            {"o": settings.github_owner, "r": settings.github_repo},
        )
        data = result.get("data") or {}
        login = (data.get("viewer") or {}).get("login")
        repo_name = (data.get("repository") or {}).get("nameWithOwner")
        ok &= _report(bool(login), "GitHub token valid", f"acting as {login}")
        ok &= _report(bool(repo_name), "Repository access", repo_name or "repository not visible")

        pr = os.getenv("PR_NUMBER", "").strip()
        if pr:
            pull = await github.fetch_pull_request(
                settings.github_owner, settings.github_repo, int(pr)
            )
            ok &= _report(
                True, f"Pull request #{pr} readable via MCP", f"{len(pull.changed_files)} file(s)"
            )
        else:
            print("[SKIP] Pull request read: set PR_NUMBER to test it")
    except (GitHubError, RuntimeError, OSError) as exc:
        ok = _report(False, "Connectivity", f"{type(exc).__name__}: {exc}")
    finally:
        await github.close()
    return ok


def main() -> int:
    load_dotenv()
    try:
        return 0 if asyncio.run(run_checks()) else 1
    except RuntimeError as exc:
        _report(False, "Configuration", str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
