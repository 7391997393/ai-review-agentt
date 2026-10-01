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

        findings = result["findings"]

        # 1. Create a pending review
        await github.create_review(
        owner=settings.github_owner,
        repo=settings.github_repo,
        pull_number=pr_number,
        body="AI Code Review",
        event="", # Create a pending review
        )
       
        # 2. Add inline comments for findings with file and line information
        for finding in findings:
            if isinstance(finding, dict):
               path = finding.get("file")
               line = finding.get("line")
               title = finding.get("title", "Code review finding")
               description = finding.get("description", "")
               recommendation = finding.get("recommendation", "")
            else:
               path = getattr(finding, "file", None)
               line = getattr(finding, "line", None)
               title = getattr(finding, "title", "Code review finding")
               description = getattr(finding, "description", "")
               recommendation = getattr(finding, "recommendation", "")
       
            if not path or not isinstance(line, int):
               print(f"Skipping inline comment without a valid file/line: {title}")
               continue
              
            comment = (
               f"**{title}**\n\n"
               f"{description}\n\n"
               f"**Recommendation:** {recommendation}"
            )
    
            await github.add_inline_comment(
            owner=settings.github_owner,
            repo=settings.github_repo,
            pull_number=pr_number,
            path=path,
            line=line,
            body=comment,
            )
       
        # 3. Submit the pending review
            await github.call(
            "pull_request_review_write",
            {
            "owner": settings.github_owner,
            "repo": settings.github_repo,
            "pullNumber": pr_number,
            "method": "submit_pending",
            "event": "COMMENT",
            },
        )
       
        print("AI inline review submitted.")

        
    finally:
        await github.close()


if __name__ == "__main__":
    asyncio.run(async_main())
