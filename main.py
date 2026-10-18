'''import asyncio
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
 
 
def extract_thread_finding_key(thread: dict) -> str | None:
    path = thread.get("path")
    line = thread.get("line")
    raw_comments = thread.get("comments")
    comments = []
    if isinstance(raw_comments, dict):
        comments = raw_comments.get("nodes", [])
    elif isinstance(raw_comments, list):
        comments = raw_comments

    body = ""
    for c in comments:
        if isinstance(c, dict) and c.get("body"):
            body = c.get("body", "")
            break

    if not path or not line or not body:
        return None

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
            return finding_key(path, int(line), title)
        except (TypeError, ValueError):
            return None
    return None


def is_ai_review_thread(thread: dict) -> bool:
    raw_comments = thread.get("comments")
    comments = []
    if isinstance(raw_comments, dict):
        comments = raw_comments.get("nodes", [])
    elif isinstance(raw_comments, list):
        comments = raw_comments

    for c in comments:
        if isinstance(c, dict):
            body = str(c.get("body", ""))
            if "**Recommendation:**" in body or "** — " in body:
                return True
    return False


async def resolve_outdated_threads(
    github: GitHubMCPClient,
    settings: Settings,
    pull_number: int,
    response: Any = None,
    current_findings: list[Any] | None = None,
) -> list[str]:
    """Attempt to resolve outdated or fixed review threads using direct GraphQL."""
    threads = []

    # 1. Fetch threads directly via GraphQL for accurate GraphQL IDs and resolution state
    if hasattr(github, "get_review_threads_graphql"):
        try:
            gql_threads = await github.get_review_threads_graphql(
                owner=settings.github_owner,
                repo=settings.github_repo,
                pull_number=pull_number,
            )
            if isinstance(gql_threads, list) and gql_threads:
                threads = gql_threads
                print(f"Retrieved {len(threads)} review thread(s) via direct GraphQL.")
        except Exception as exc:
            print(f"Direct GraphQL thread query failed, checking response object: {exc}")

    # 2. Fallback to response object if GraphQL didn't return threads
    if not threads and isinstance(response, dict):
        threads = response.get("review_threads", [])

    if not isinstance(threads, list):
        print("Cannot inspect review threads: unexpected response type.")
        return []

    active_finding_keys = set()
    active_locations = set()
    if current_findings is not None:
        for f in current_findings:
            f_file = getattr(f, "file", None)
            f_line = getattr(f, "line", None)
            f_title = getattr(f, "title", None)
            if f_file and f_line:
                try:
                    active_locations.add((f_file, int(f_line)))
                    if f_title:
                        active_finding_keys.add(finding_key(f_file, int(f_line), f_title))
                except (TypeError, ValueError):
                    pass

    resolved_thread_ids: list[str] = []

    for thread in threads:
        if not isinstance(thread, dict):
            continue

        # Handle both GraphQL camelCase (isResolved) and snake_case (is_resolved)
        is_resolved = thread.get("isResolved", thread.get("is_resolved"))
        if is_resolved is True:
            continue

        thread_id = thread.get("id")
        if not thread_id:
            print("Skipping thread without an ID.")
            continue

        is_outdated = thread.get("isOutdated", thread.get("is_outdated"))

        should_resolve = False
        resolve_reason = ""

        # Case 1: GitHub explicitly marked the thread outdated (code changed)
        if is_outdated is True:
            should_resolve = True
            resolve_reason = "thread is outdated by code changes"
        # Case 2: Developer pushed a fix and the issue is no longer reported in current findings
        elif current_findings is not None:
            thread_key = extract_thread_finding_key(thread)
            thread_path = thread.get("path")
            thread_line = thread.get("line")

            if thread_key and thread_key not in active_finding_keys:
                should_resolve = True
                resolve_reason = f"issue fixed in new commit ({thread_key})"
            elif not thread_key and thread_path and thread_line:
                try:
                    if (thread_path, int(thread_line)) not in active_locations and is_ai_review_thread(thread):
                        should_resolve = True
                        resolve_reason = f"issue fixed at {thread_path}:{thread_line}"
                except (TypeError, ValueError):
                    pass

        if not should_resolve:
            continue

        print(f"Attempting to resolve thread {thread_id} ({resolve_reason}) via GraphQL...")

        try:
            result = await github.resolve_thread(
                owner=settings.github_owner,
                repo=settings.github_repo,
                pull_number=pull_number,
                thread_id=thread_id,
            )
            print("Resolve thread response:", result)

            has_error = False
            if not result:
                has_error = True
            elif isinstance(result, dict):
                if result.get("isError") or result.get("error"):
                    has_error = True
                elif "isResolved" in result and not result["isResolved"]:
                    has_error = True
                elif "is_resolved" in result and not result["is_resolved"]:
                    has_error = True
            elif isinstance(result, str) and ("error" in result.lower() or "failed" in result.lower()):
                has_error = True

            if has_error:
                print(f"Failed to resolve thread {thread_id}: response indicated error.")
            else:
                print(f"Successfully resolved thread {thread_id} ({resolve_reason}).")
                resolved_thread_ids.append(thread_id)
        except Exception as exc:
            # Continue the review even if resolution fails for a specific thread
            print(
                "Could not resolve thread:",
                thread_id,
                f"({type(exc).__name__}: {exc})",
            )

    return resolved_thread_ids
 
 
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
 
        # Try to resolve outdated or fixed threads before posting the new review.
        resolved_threads = await resolve_outdated_threads(
            github=github,
            settings=settings,
            pull_number=pr_number,
            response=existing_comments,
            current_findings=findings,
        )
        if resolved_threads:
            print(
                f"Total outdated/fixed threads resolved: {len(resolved_threads)}",
                resolved_threads,
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
 '''
import asyncio
import json
import os

from src.finding_state import decode_state, encode_state
from src.lifecycle_manager import reconcile_state

from pathlib import Path
from typing import Any
 
from dotenv import load_dotenv
 
from src.config import Settings
from src.formatter import format_review
from src.graph import build_graph
from src.mcp_github import GitHubMCPClient
from src.thread_resolver import (
    extract_thread_finding_key,  # noqa: F401  (re-exported for tests)
    finding_key,
    is_ai_review_thread,  # noqa: F401  (re-exported for tests)
    open_thread_keys,
    select_threads_to_resolve,
)
 
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
 
 
async def load_review_threads(
    github: GitHubMCPClient,
    settings: Settings,
    pull_number: int,
    fallback_response: Any = None,
) -> list[dict] | None:
    """Load review threads via GraphQL, falling back to the MCP response.

    Returns None when threads could not be loaded at all.
    """
    try:
        threads = await github.get_review_threads_graphql(
            owner=settings.github_owner,
            repo=settings.github_repo,
            pull_number=pull_number,
        )

        if isinstance(threads, list):
            print(f"Retrieved {len(threads)} review thread(s) via direct GraphQL.")
            return threads

    except Exception as exc:
        print(f"Direct GraphQL thread query failed, checking MCP response: {exc}")

    if isinstance(fallback_response, dict):
        threads = fallback_response.get("review_threads")

        if isinstance(threads, list):
            return threads

    print("Cannot inspect review threads: no thread data available.")
    return None

async def resolve_outdated_threads(
    github: GitHubMCPClient,
    settings: Settings,
    pull_number: int,
    threads: list[dict],
) -> list[str]:
    """Resolve the agent's own review threads that GitHub marks as outdated.

    Open threads are never resolved just because the latest AI run did not
    repeat the finding, and human reviewers' threads are never touched.
    """
    resolved_thread_ids: list[str] = []

    for thread, reason in select_threads_to_resolve(threads):
        thread_id = thread["id"]
        print(f"Attempting to resolve thread {thread_id} ({reason}) via GraphQL...")

        try:
            # Raises unless GitHub confirms isResolved=true.
            await github.resolve_thread(
                owner=settings.github_owner,
                repo=settings.github_repo,
                pull_number=pull_number,
                thread_id=thread_id,
            )
        except Exception as exc:
            # Keep going: one failing thread must not stop the review.
            print(
                "Could not resolve thread:",
                thread_id,
                f"({type(exc).__name__}: {exc})",
            )
            continue

        print(f"Successfully resolved thread {thread_id} ({reason}).")
        resolved_thread_ids.append(thread_id)

    return resolved_thread_ids


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

        previous_states = []

        current_keys = set()

        for finding in findings:
            if finding.file and finding.line:
                current_keys.add(
                    finding_key(
                finding.file,
                finding.line,
                finding.title,
            )
        )

        result_state, updated_states = reconcile_state(
            previous_states=previous_states,
            current_keys=current_keys,
            )

        print("NEW:", result_state.new)
        print("EXISTING:", result_state.existing)
        print("RESOLVED:", result_state.resolved)
        print("REOPENED:", result_state.reopened)

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
 
        # Resolve outdated threads before posting the new review.
        threads = await load_review_threads(
            github=github,
            settings=settings,
            pull_number=pr_number,
            fallback_response=existing_comments,
        )
        resolved_threads: list[str] = []
        if threads is not None:
            resolved_threads = await resolve_outdated_threads(
                github=github,
                settings=settings,
                pull_number=pr_number,
                threads=threads,
            )
        if resolved_threads:
            print(
                f"Total outdated threads resolved: {len(resolved_threads)}",
                resolved_threads,
            )

        # Duplicate detection only looks at threads that are still open and
        # still on current code, so outdated findings can be reported again.
        if threads is not None:
            existing_keys = open_thread_keys(threads, exclude_ids=resolved_threads)
        else:
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
 