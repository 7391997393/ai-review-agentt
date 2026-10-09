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
        "PR number not found. Set PR_NUMBER locally or run from a pull_request "
        "GitHub Actions event."
    )


def finding_key(path: str, line: int, title: str) -> str:
    return f"{path}:{line}:{title.strip().lower()}"


def extract_existing_comment_keys(comments) -> set[str]:
    keys = set()

    if not isinstance(comments, list):
        return keys

    for comment in comments:
        if not isinstance(comment, dict):
            continue

        path = comment.get("path")
        line = comment.get("line")
        body = comment.get("body", "")

        if not path or not line or not body:
            continue

        title = ""

        for line_text in str(body).splitlines():
            if line_text.startswith("**") and line_text.endswith("**"):
                candidate = line_text.strip("*").strip()

                if "—" not in candidate:
                    title = candidate
                    break

        if title:
            keys.add(finding_key(path, int(line), title))

    return keys


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

        existing_comments = await github.get_review_comments(
            owner=settings.github_owner,
            repo=settings.github_repo,
            pull_number=pr_number,
        )

        existing_keys = extract_existing_comment_keys(existing_comments)

        # Temporary diagnostic: print response field names only.
        # Do not print review comment bodies or other sensitive content.
        if isinstance(existing_comments, dict):
            print(
                "Review comments response keys:",
                list(existing_comments.keys()),
            )

            for key, value in existing_comments.items():
                if (
                    isinstance(value, list)
                    and value
                    and isinstance(value[0], dict)
                ):
                    print(
                        f"Review comments field '{key}' item keys:",
                        list(value[0].keys()),
                    )
                    for thread in value[:5]:
                        if isinstance(thread, dict):
                            print(
                                "Review thread details:",
                                {
                                    "id": thread.get("id"),
                                    "is_resolved": thread.get("is_resolved"),
                                    "is_outdated": thread.get("is_outdated"),
                                },
                            )

                elif isinstance(value, dict):
                    print(
                        f"Review comments field '{key}' keys:",
                        list(value.keys()),
                    )
        else:
            print(
                "Review comments response type:",
                type(existing_comments).__name__,
            )

        new_findings = []

        for finding in findings:
            if not finding.file or not finding.line:
                new_findings.append(finding)
                continue

            key = finding_key(
                finding.file,
                finding.line,
                finding.title,
            )

            if key in existing_keys:
                print(
                    f"Skipping duplicate finding: "
                    f"{finding.file}:{finding.line} - {finding.title}"
                )
                continue

            new_findings.append(finding)

        if not new_findings:
            print("No new findings. Duplicate findings were skipped.")
            return

        review_body = format_review(
            owner=settings.github_owner,
            repo=settings.github_repo,
            pull_number=pr_number,
            findings=new_findings,
        )

        await github.create_review(
            owner=settings.github_owner,
            repo=settings.github_repo,
            pull_number=pr_number,
            body=review_body,
        )

        for finding in new_findings:
            if finding.file and finding.line:
                comment_body = (
                    f"**{finding.severity.upper()} — "
                    f"{finding.category.title()}**\n\n"
                    f"**{finding.title}**\n\n"
                    f"{finding.description}\n\n"
                    f"**Recommendation:** {finding.recommendation}"
                )

                await github.add_inline_comment(
                    owner=settings.github_owner,
                    repo=settings.github_repo,
                    pull_number=pr_number,
                    path=finding.file,
                    line=finding.line,
                    body=comment_body,
                )

        await github.submit_review(
            owner=settings.github_owner,
            repo=settings.github_repo,
            pull_number=pr_number,
            body=review_body,
        )

        print(review_body)

    finally:
        await github.close()


if __name__ == "__main__":
    asyncio.run(async_main())