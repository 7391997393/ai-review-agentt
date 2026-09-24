import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from src.config import Settings
from src.formatter import format_review
from src.graph import build_graph
from src.mcp_github import GitHubMCPClient

load_dotenv()


def get_pr_number() -> int:
    """Get the PR number from an explicit env var or the GitHub Actions event payload."""
    explicit = os.getenv("PR_NUMBER")
    if explicit:
        return int(explicit)

    event_path = os.getenv("GITHUB_EVENT_PATH")
    if event_path and Path(event_path).exists():
        event = json.loads(Path(event_path).read_text(encoding="utf-8"))
        number = event.get("number")
        if number:
            return int(number)

    raise RuntimeError(
        "PR number not found. Set PR_NUMBER locally or run from a pull_request GitHub Actions event."
    )


async def async_main() -> None:
    settings = Settings.from_env()
    pr_number = get_pr_number()

    if not settings.github_owner or not settings.github_repo:
        raise RuntimeError("GITHUB_OWNER and GITHUB_REPO are required.")

    github = GitHubMCPClient(settings)
    await github.connect()

    try:
        context = await github.get_pull_request_context(
            owner=settings.github_owner,
            repo=settings.github_repo,
            pull_number=pr_number,
        )

        graph = build_graph(settings)
        result = await graph.ainvoke({"context": context})

        review_body = format_review(
            owner=settings.github_owner,
            repo=settings.github_repo,
            pull_number=pr_number,
            findings=result["findings"],
        )

        await github.create_review(
            owner=settings.github_owner,
            repo=settings.github_repo,
            pull_number=pr_number,
            body=review_body,
            event="COMMENT",
        )

        print(review_body)
    finally:
        await github.close()


if __name__ == "__main__":
    asyncio.run(async_main())
