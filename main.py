"""Entry point: review one Pull Request and publish the result to GitHub."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from src.config import Settings
from src.diff_utils import index_changed_files, validate_finding_against_changed_files
from src.formatter import format_review
from src.graph import build_graph
from src.mcp_github import GitHubError, GitHubMCPClient
from src.schemas import Finding
from src.thread_resolver import (
    AgentLogins,
    existing_thread_keys,
    finding_key,
    format_inline_comment,
    select_threads_to_reopen,
    select_threads_to_resolve,
    summary_fingerprint,
    summary_fingerprints_from_reviews,
    threads_from_mcp_response,
)

logger = logging.getLogger("ai_review_agent")


@dataclass
class ReviewPlan:
    """What to publish for the current run."""

    inline: list[tuple[Finding, str]] = field(default_factory=list)  # (finding, valid path)
    summary_only: list[Finding] = field(default_factory=list)
    duplicates: list[Finding] = field(default_factory=list)

    @property
    def new_findings(self) -> list[Finding]:
        return [finding for finding, _ in self.inline] + self.summary_only


@dataclass
class RunReport:
    resolved_threads: list[str] = field(default_factory=list)
    reopened_threads: list[str] = field(default_factory=list)
    inline_posted: int = 0
    summary_only: int = 0
    duplicates: int = 0
    review_posted: bool = False
    failures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


def get_pr_number() -> int:
    explicit = os.getenv("PR_NUMBER", "").strip()
    if explicit:
        try:
            return int(explicit)
        except ValueError as exc:
            raise RuntimeError(f"PR_NUMBER must be an integer, got {explicit!r}") from exc

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


async def load_review_threads(
    github: GitHubMCPClient,
    settings: Settings,
    pull_number: int,
) -> list[dict[str, Any]]:
    """Load review threads via GraphQL, falling back to the MCP server.

    Raises GitHubError when neither source works: posting without knowing the
    existing threads would create duplicate comments.
    """
    try:
        threads = await github.get_review_threads_graphql(
            owner=settings.github_owner, repo=settings.github_repo, pull_number=pull_number
        )
        logger.info("Loaded %d review thread(s) via GraphQL", len(threads))
        return threads
    except Exception as exc:  # noqa: BLE001 - any failure switches to the fallback
        logger.warning("GraphQL review-thread query failed (%s); trying the MCP server", exc)

    response = await github.get_review_comments(
        owner=settings.github_owner, repo=settings.github_repo, pull_number=pull_number
    )
    threads = threads_from_mcp_response(response)
    if threads is None:
        raise GitHubError(
            "Could not load existing review threads; refusing to post a review that "
            "might duplicate earlier comments."
        )
    logger.info("Loaded %d review thread(s) via MCP", len(threads))
    return threads


async def load_summary_fingerprints(
    github: GitHubMCPClient,
    settings: Settings,
    pull_number: int,
    agent_login: AgentLogins,
) -> set[str]:
    try:
        reviews = await github.get_reviews_graphql(
            owner=settings.github_owner, repo=settings.github_repo, pull_number=pull_number
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Could not load earlier reviews (%s); summary-only findings may be repeated", exc
        )
        return set()
    return summary_fingerprints_from_reviews(reviews, agent_login)


async def _apply_to_threads(
    action: str,
    done_label: str,
    operation: Any,
    selected: list[tuple[dict, str]],
    report: RunReport,
) -> list[str]:
    done: list[str] = []
    for thread, reason in selected:
        thread_id = thread["id"]
        try:
            await operation(thread_id=thread_id)
        except Exception as exc:  # noqa: BLE001 - one thread must not stop the run
            message = f"Could not {action} thread {thread_id}: {type(exc).__name__}: {exc}"
            logger.error(message)
            report.failures.append(message)
            continue
        logger.info("%s thread %s (%s)", done_label, thread_id, reason)
        done.append(thread_id)
    return done


async def resolve_outdated_threads(
    github: GitHubMCPClient,
    threads: list[dict[str, Any]],
    report: RunReport | None = None,
    agent_login: AgentLogins = None,
) -> list[str]:
    """Resolve the agent's own review threads that GitHub marks as outdated.

    Open threads are never resolved just because the latest AI run did not
    repeat the finding, and human reviewers' threads are never touched.
    Failures are recorded in `report.failures` (the run then exits non-zero).
    """
    report = report if report is not None else RunReport()
    selected = select_threads_to_resolve(threads, agent_login)
    resolved = await _apply_to_threads(
        "resolve", "Resolved", github.resolve_thread, selected, report
    )
    report.resolved_threads.extend(resolved)
    return resolved


async def reopen_reported_threads(
    github: GitHubMCPClient,
    threads: list[dict[str, Any]],
    current_keys: set[str],
    report: RunReport,
    agent_login: AgentLogins = None,
) -> list[str]:
    """Reopen resolved AI threads whose finding the current run reported again."""
    selected = select_threads_to_reopen(threads, current_keys, agent_login)
    reopened = await _apply_to_threads("reopen", "Reopened", github.reopen_thread, selected, report)
    report.reopened_threads.extend(reopened)
    return reopened


def plan_review(
    findings: list[Finding],
    changed_files: list[dict[str, Any]],
    thread_keys: set[str],
    summary_fingerprints: set[str],
) -> ReviewPlan:
    """Split findings into inline / summary-only / duplicate."""
    plan = ReviewPlan()
    files = index_changed_files(changed_files)
    seen: set[str] = set()

    for finding in findings:
        target = validate_finding_against_changed_files(finding, files)
        if target.ok and target.path:
            key = finding_key(target.path, finding.line, finding.title)
            if key in thread_keys or key in seen:
                plan.duplicates.append(finding)
                continue
            seen.add(key)
            plan.inline.append((finding, target.path))
            continue

        fingerprint = summary_fingerprint(finding)
        if fingerprint in summary_fingerprints or fingerprint in seen:
            plan.duplicates.append(finding)
            continue
        seen.add(fingerprint)
        logger.info("Summary-only finding %r: %s", finding.title, target.reason)
        plan.summary_only.append(finding)

    return plan


def inline_keys(findings: list[Finding], changed_files: list[dict[str, Any]]) -> set[str]:
    files = index_changed_files(changed_files)
    keys = set()
    for finding in findings:
        target = validate_finding_against_changed_files(finding, files)
        if target.ok and target.path:
            keys.add(finding_key(target.path, finding.line, finding.title))
    return keys


async def publish_review(
    github: GitHubMCPClient,
    settings: Settings,
    pull_number: int,
    plan: ReviewPlan,
    report: RunReport,
) -> None:
    owner, repo = settings.github_owner, settings.github_repo
    findings = plan.new_findings
    fingerprints = {summary_fingerprint(f) for f in plan.summary_only}

    try:
        await github.create_review(
            owner=owner,
            repo=repo,
            pull_number=pull_number,
            body=format_review(owner, repo, pull_number, findings, fingerprints),
        )
    except GitHubError as exc:
        # Never delete a pending review we did not create: it may be a person's draft.
        raise GitHubError(
            f"{exc} - if the token's account already has a pending (draft) review on "
            "this pull request, submit or delete it and run the review again."
        ) from exc

    for finding, path in plan.inline:
        try:
            await github.add_inline_comment(
                owner=owner,
                repo=repo,
                pull_number=pull_number,
                path=path,
                line=finding.line,
                body=format_inline_comment(finding),
            )
            report.inline_posted += 1
        except Exception as exc:  # noqa: BLE001 - keep posting the other comments
            message = (
                f"Inline comment failed for {path}:{finding.line}: {type(exc).__name__}: {exc}"
            )
            logger.error(message)
            report.failures.append(message)
            # Still shown in the summary; track it so it is not repeated.
            fingerprints.add(summary_fingerprint(finding))

    body = format_review(owner, repo, pull_number, findings, fingerprints)
    try:
        await github.submit_review(owner=owner, repo=repo, pull_number=pull_number, body=body)
    except Exception as exc:
        # GitHub allows one pending review per user and PR: a leftover draft
        # would make every later run fail at create_review. Remove our own.
        logger.error("Submitting the review failed (%s); deleting the pending review", exc)
        try:
            await github.delete_pending_review(owner=owner, repo=repo, pull_number=pull_number)
        except Exception as cleanup_exc:  # noqa: BLE001 - report the original error
            logger.error("Could not delete the pending review: %s", cleanup_exc)
        raise
    report.review_posted = True
    logger.info(
        "Review submitted: %d finding(s), %d inline comment(s).",
        len(findings),
        report.inline_posted,
    )
    logger.debug("Review body:\n%s", body)


async def run_review(github: GitHubMCPClient, settings: Settings, pull_number: int) -> RunReport:
    report = RunReport()

    data = await github.fetch_pull_request(settings.github_owner, settings.github_repo, pull_number)
    context = github.build_context(data)

    result = await build_graph(settings).ainvoke({"context": context.text})
    findings: list[Finding] = result.get("findings", [])

    threads = await load_review_threads(github, settings, pull_number)
    viewer = getattr(github, "viewer_login", None)
    # The token's account, plus accounts that posted for the agent in the past
    # (AGENT_LOGINS, e.g. github-actions[bot]). Unknown without GraphQL.
    agent_login = {viewer, *settings.extra_agent_logins} if viewer else None

    if agent_login:
        await resolve_outdated_threads(github, threads, report, agent_login)
        if settings.reopen_resolved_threads:
            current = inline_keys(findings, data.changed_files)
            await reopen_reported_threads(github, threads, current, report, agent_login)
    else:
        logger.warning(
            "Agent account unknown (GraphQL unavailable): skipping thread resolve/reopen "
            "because thread ownership cannot be verified."
        )

    plan = plan_review(
        findings,
        data.changed_files,
        existing_thread_keys(threads, exclude_ids=report.resolved_threads, agent_login=agent_login),
        await load_summary_fingerprints(github, settings, pull_number, agent_login),
    )
    report.duplicates = len(plan.duplicates)
    report.summary_only = len(plan.summary_only)
    for finding in plan.duplicates:
        logger.info(
            "Skipping duplicate finding: %s:%s - %s", finding.file, finding.line, finding.title
        )

    if not plan.new_findings:
        logger.info("No new findings to publish (%d duplicate(s) skipped).", report.duplicates)
        return report

    await publish_review(github, settings, pull_number, plan, report)
    return report


async def async_main() -> int:
    settings = Settings.from_env()
    pr_number = get_pr_number()
    if not settings.github_owner or not settings.github_repo:
        raise RuntimeError("GITHUB_OWNER and GITHUB_REPO are required.")

    github = GitHubMCPClient(settings)
    await github.connect()
    try:
        report = await run_review(github, settings, pr_number)
    finally:
        await github.close()

    logger.info(
        "Done: %d inline comment(s), %d summary-only, %d duplicate(s) skipped, "
        "%d thread(s) resolved, %d reopened.",
        report.inline_posted,
        report.summary_only,
        report.duplicates,
        len(report.resolved_threads),
        len(report.reopened_threads),
    )
    if report.failures:
        logger.error("%d GitHub operation(s) failed:", len(report.failures))
        for failure in report.failures:
            logger.error("  - %s", failure)
        return 1
    return 0


LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def configure_logging() -> None:
    requested = (os.getenv("LOG_LEVEL") or "INFO").strip().upper()
    level = requested if requested in LOG_LEVELS else "INFO"
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if requested != level:
        logger.warning("Unknown LOG_LEVEL %r; using INFO", requested)
    # Request logging from HTTP libraries is noise and could include headers.
    for noisy in ("httpx", "httpcore", "openai", "mcp"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def main() -> int:
    load_dotenv()
    configure_logging()
    return asyncio.run(async_main())


if __name__ == "__main__":
    sys.exit(main())
