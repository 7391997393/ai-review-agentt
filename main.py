import asyncio
import json
import os
from pathlib import Path
from typing import Any
 
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
 
 
def extract_comment_items(response: Any) -> list[dict]:
    """Extract review comments from supported MCP response shapes."""
    if isinstance(response, list):
        return [item for item in response if isinstance(item, dict)]
 
    if not isinstance(response, dict):
        return []
 
    # The current MCP response contains review_threads.
    threads = response.get("review_threads")
    if isinstance(threads, list):
        extracted = []
 
        for thread in threads:
            if not isinstance(thread, dict):
                continue
 
            comments = thread.get("comments", [])
 
            if isinstance(comments, list):
                extracted.extend(
                    comment
                    for comment in comments
                    if isinstance(comment, dict)
                )
            elif isinstance(comments, dict):
                nodes = comments.get("nodes", [])
                if isinstance(nodes, list):
                    extracted.extend(
                        comment
                        for comment in nodes
                        if isinstance(comment, dict)
                    )
 
        return extracted
 
    # Fallback for APIs returning a direct comments list.
    comments = response.get("comments")
    if isinstance(comments, list):
        return [item for item in comments if isinstance(item, dict)]
 
    return []
 
 
def extract_existing_comment_keys(comments: Any) -> set[str]:
    keys = set()
 
    for comment in extract_comment_items(comments):
        path = comment.get("path")
        line = comment.get("line") or comment.get("original_line")
        body = comment.get("body", "")
 
        if not path or not line or not body:
            continue
 
        title = ""
 
        for line_text in str(body).splitlines():
            line_text = line_text.strip()
 
            if line_text.startswith("**") and line_text.endswith("**"):
                candidate = line_text.strip("*").strip()
 
                if "—" not in candidate:
                    title = candidate
                    break
 
        if title:
            try:
                keys.add(finding_key(path, int(line), title))
            except (TypeError, ValueError):
                continue
 
    return keys
 
 
async def resolve_outdated_threads(
    github: GitHubMCPClient,
    settings: Settings,
    pull_number: int,
    response: Any,
) -> None:
    """Attempt to resolve outdated, unresolved review threads."""
    if not isinstance(response, dict):
        print("Cannot inspect review threads: unexpected response type.")
        return
 
    threads = response.get("review_threads", [])
    if not isinstance(threads, list):
        print("Cannot inspect review threads: review_threads is not a list.")
        return
 
    for thread in threads:
        if not isinstance(thread, dict):
            continue
 
        if thread.get("is_resolved") is True:
            continue
 
        if thread.get("is_outdated") is not True:
            continue
 
        thread_id = thread.get("id")
        if not thread_id:
            print("Skipping outdated thread without an ID.")
            continue
 
        print("Attempting to resolve outdated thread:", thread_id)
 
        try:
            result = await github.resolve_thread(
                owner=settings.github_owner,
                repo=settings.github_repo,
                pull_number=pull_number,
                thread_id=thread_id,
            )
            print("Resolve thread response:", result)
        except Exception as exc:
            # Continue the review even if the server does not support
            # the requested resolve operation.
            print(
                "Could not resolve outdated thread:",
                thread_id,
                f"({type(exc).__name__}: {exc})",
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
 
        existing_comments = await github.get_review_comments(
            owner=settings.github_owner,
            repo=settings.github_repo,
            pull_number=pr_number,
        )
 
        if isinstance(existing_comments, dict):
            print(
                "Review comments response keys:",
                list(existing_comments.keys()),
            )
 
            threads = existing_comments.get("review_threads", [])
            if isinstance(threads, list):
                print("Review thread count:", len(threads))
 
                for thread in threads[:5]:
                    if isinstance(thread, dict):
                        print(
                            "Review thread details:",
                            {
                                "id": thread.get("id"),
                                "is_resolved": thread.get("is_resolved"),
                                "is_outdated": thread.get("is_outdated"),
                            },
                        )
 
        # Try to resolve outdated threads before posting the new review.
        await resolve_outdated_threads(
            github=github,
            settings=settings,
            pull_number=pr_number,
            response=existing_comments,
        )
 
        existing_keys = extract_existing_comment_keys(existing_comments)
 
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
                    "Skipping duplicate finding:",
                    f"{finding.file}:{finding.line} - {finding.title}",
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
 
                try:
                    response = await github.add_inline_comment(
                        owner=settings.github_owner,
                        repo=settings.github_repo,
                        pull_number=pr_number,
                        path=finding.file,
                        line=finding.line,
                        body=comment_body,
                    )
                    print(
                        f"Inline comment response for "
                        f"{finding.file}:{finding.line}: {response}"
                    )
                except Exception as exc:
                    print(
                        f"Inline comment failed for "
                        f"{finding.file}:{finding.line}: "
                        f"{type(exc).__name__}: {exc}"
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
 