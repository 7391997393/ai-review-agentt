
import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from src.config import Settings
from src.graph import build_graph
from src.mcp_github import GitHubMCPClient

load_dotenv()


def get_pr_number() -> int:
    """Get the PR number from an environment variable or GitHub Actions event."""
    explicit = os.getenv("PR_NUMBER")

    if explicit:
        return int(explicit)

    event_path = os.getenv("GITHUB_EVENT_PATH")

    if event_path and Path(event_path).exists():
        event = json.loads(
            Path(event_path).read_text(encoding="utf-8")
        )
        number = event.get("number")

        if number:
            return int(number)

    raise RuntimeError(
        "PR number not found. Set PR_NUMBER locally or run from a "
        "pull_request GitHub Actions event."
    )


async def async_main() -> None:
    settings = Settings.from_env()
    pr_number = get_pr_number()

    if not settings.github_owner or not settings.github_repo:
        raise RuntimeError(
            "GITHUB_OWNER and GITHUB_REPO are required."
        )

    github = GitHubMCPClient(settings)
    await github.connect()

    try:
        # 1. Get pull request context
        context = await github.get_pull_request_context(
            owner=settings.github_owner,
            repo=settings.github_repo,
            pull_number=pr_number,
        )

        # 2. Run the AI review
        graph = build_graph(settings)
        result = await graph.ainvoke({"context": context})
        findings = result["findings"]

        print(f"AI review produced {len(findings)} findings.")

        # 3. Create a pending review
        review_result = await github.create_review(
            owner=settings.github_owner,
            repo=settings.github_repo,
            pull_number=pr_number,
            body="AI Code Review",
            event="",
        )

        print(f"Pending review response: {review_result}")

        # 4. Add inline comments
        added_comments = 0

        for finding in findings:
            if isinstance(finding, dict):
                path = finding.get("file")
                line = finding.get("line")
                title = finding.get(
                    "title", "Code review finding"
                )
                description = finding.get("description", "")
                recommendation = finding.get(
                    "recommendation", ""
                )
            else:
                path = getattr(finding, "file", None)
                line = getattr(finding, "line", None)
                title = getattr(
                    finding, "title", "Code review finding"
                )
                description = getattr(
                    finding, "description", ""
                )
                recommendation = getattr(
                    finding, "recommendation", ""
                )

            if (
                not path
                or not isinstance(line, int)
                or isinstance(line, bool)
            ):
                print(
                    f"Skipping finding without a valid file/line: "
                    f"{title}"
                )
                continue

            comment = (
                f"**{title}**\n\n"
                f"{description}\n\n"
                f"**Recommendation:** {recommendation}"
            )

            response = await github.add_inline_comment(
                owner=settings.github_owner,
                repo=settings.github_repo,
                pull_number=pr_number,
                path=path,
                line=line,
                body=comment,
            )

            print(
                f"Inline comment response for "
                f"{path}:{line}: {response}"
            )
            added_comments += 1

        print(f"Inline comment requests sent: {added_comments}")

        # 5. Submit the pending review once, after adding comments
        if added_comments > 0:
            submit_result = await github.call(
                "pull_request_review_write",
                {
                    "owner": settings.github_owner,
                    "repo": settings.github_repo,
                    "pullNumber": pr_number,
                    "method": "submit_pending",
                    "event": "COMMENT",
                },
            )

            print(f"Review submission response: {submit_result}")
            print("Review submission request completed.")
        else:
            print(
                "No findings had valid file and line information. "
                "No review submission was attempted."
            )

    finally:
        await github.close()


if __name__ == "__main__":
    asyncio.run(async_main())