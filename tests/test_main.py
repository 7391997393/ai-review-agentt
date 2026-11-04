"""Pipeline tests through the real GitHubMCPClient.

Only the two transports are replaced: `execute_graphql` (HTTP) and `call`
(MCP). Everything between main.py and those transports is production code,
which is exactly the path that broke when `resolve_thread` was redefined.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import main
from src.mcp_github import GitHubMCPClient
from src.thread_resolver import (
    AI_COMMENT_MARKER,
    SUMMARY_MARKER_RE,
    summary_fingerprint,
    summary_marker,
)
from tests.conftest import AI_BODY, PATCH, graphql_mutation_response, make_finding, make_thread


class TransportFakeClient(GitHubMCPClient):
    """Real client; MCP and HTTP transports replaced by in-memory fakes."""

    def __init__(self, settings, *, threads=(), reviews=(), resolve_ok=True, inline_error=False):
        super().__init__(settings)
        self.threads = list(threads)
        self.reviews = list(reviews)
        self.resolve_ok = resolve_ok
        self.inline_error = inline_error
        self.graphql_calls: list[tuple[str, dict]] = []
        self.mcp_calls: list[tuple[str, dict]] = []

    async def connect(self) -> None:
        self.session = SimpleNamespace()  # never used: `call` is faked

    async def execute_graphql(self, query: str, variables: dict | None = None) -> dict:
        variables = variables or {}
        self.graphql_calls.append((query, variables))
        if "unresolveReviewThread" in query:
            return graphql_mutation_response("unresolveReviewThread", variables["threadId"], False)
        if "resolveReviewThread" in query:
            return graphql_mutation_response(
                "resolveReviewThread", variables["threadId"], self.resolve_ok
            )
        page = {"pageInfo": {"hasNextPage": False}}
        if "reviewThreads" in query:
            return {
                "data": {
                    "viewer": {"login": "ai-bot"},
                    "repository": {
                        "pullRequest": {"reviewThreads": {**page, "nodes": self.threads}}
                    },
                }
            }
        if "reviews(" in query:
            return {
                "data": {
                    "repository": {"pullRequest": {"reviews": {**page, "nodes": self.reviews}}}
                }
            }
        raise AssertionError(f"unexpected query: {query}")

    async def call(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        self.mcp_calls.append((tool_name, arguments))
        method = arguments.get("method")
        if tool_name == "pull_request_read" and method == "get":
            return {"title": "Add login", "body": "", "user": {"login": "dev"}}
        if tool_name == "pull_request_read" and method == "get_files":
            return [{"filename": "app.py", "status": "modified", "patch": PATCH}]
        if tool_name == "add_comment_to_pending_review" and self.inline_error:
            from src.mcp_github import GitHubError

            raise GitHubError("MCP tool add_comment_to_pending_review failed: invalid line")
        return {"ok": True}

    # helpers for assertions
    def mutation_ids(self, name: str) -> list[str]:
        return [v["threadId"] for q, v in self.graphql_calls if f"{name}(" in q]

    def tool_calls(self, tool: str, method: str | None = None) -> list[dict]:
        return [
            a
            for t, a in self.mcp_calls
            if t == tool and (method is None or a.get("method") == method)
        ]


# -- resolve_outdated_threads with the real client --------------------------------


async def test_resolve_outdated_threads_sends_mutation_for_ai_thread_only(settings):
    client = TransportFakeClient(settings)
    threads = [
        make_thread("AI-OUT", outdated=True, line=None, original_line=3),
        make_thread("HUMAN-OUT", outdated=True, body="Please rename this."),
        make_thread("AI-OPEN", outdated=False),
        make_thread("AI-DONE", resolved=True, outdated=True),
    ]

    resolved = await main.resolve_outdated_threads(client, threads, agent_login="ai-bot")

    assert resolved == ["AI-OUT"]
    assert client.mutation_ids("resolveReviewThread") == ["AI-OUT"]
    query, variables = client.graphql_calls[0]
    assert "mutation ResolveThread" in query
    assert variables == {"threadId": "AI-OUT"}


async def test_resolve_outdated_threads_records_graphql_failure(settings):
    client = TransportFakeClient(settings, resolve_ok=False)
    report = main.RunReport()

    resolved = await main.resolve_outdated_threads(
        client, [make_thread("AI-OUT", outdated=True)], report, "ai-bot"
    )

    assert resolved == []
    assert not report.ok
    assert "AI-OUT" in report.failures[0] and "isResolved=true" in report.failures[0]


async def test_resolve_outdated_threads_respects_agent_login(settings):
    client = TransportFakeClient(settings)
    other = make_thread("X", outdated=True, author="human-reviewer")

    assert await main.resolve_outdated_threads(client, [other], agent_login="ai-bot") == []
    assert client.graphql_calls == []


async def test_reopen_reported_threads_uses_unresolve_mutation(settings):
    client = TransportFakeClient(settings)
    thread = make_thread("R1", resolved=True, path="app.py", line=3, author="ai-bot")
    report = main.RunReport()
    keys = main.inline_keys(
        [make_finding(title="Hard-coded password")], [{"filename": "app.py", "patch": PATCH}]
    )

    reopened = await main.reopen_reported_threads(client, [thread], keys, report, "ai-bot")

    assert reopened == ["R1"]
    assert client.mutation_ids("unresolveReviewThread") == ["R1"]


# -- plan_review -----------------------------------------------------------------


FILES = [{"filename": "app.py", "status": "modified", "patch": PATCH}]


def test_plan_review_splits_inline_summary_and_duplicates():
    existing = make_thread("OPEN", path="app.py", line=2, body=AI_BODY)
    from src.thread_resolver import existing_thread_keys

    findings = [
        make_finding(line=3, title="Hard-coded token"),  # inline
        make_finding(line=2, title="Hard-coded password"),  # duplicate thread
        make_finding(line=99, title="Far away"),  # outside diff -> summary
        make_finding(file="", line=None, title="General design"),  # no file/line -> summary
        make_finding(line=None, title="Old summary"),  # reported before
        make_finding(line=3, title="hard-coded   TOKEN"),  # duplicate within run
    ]
    previous = {summary_fingerprint(make_finding(line=None, title="Old summary"))}

    plan = main.plan_review(findings, FILES, existing_thread_keys([existing]), previous)

    assert [(f.title, p) for f, p in plan.inline] == [("Hard-coded token", "app.py")]
    assert [f.title for f in plan.summary_only] == ["Far away", "General design"]
    assert [f.title for f in plan.duplicates] == [
        "Hard-coded password",
        "Old summary",
        "hard-coded   TOKEN",
    ]


# -- async_main end to end ---------------------------------------------------------


@pytest.fixture
def pipeline(monkeypatch, settings):
    for name, value in {
        "CG_API_KEY": "k",
        "CG_MODEL": "m",
        "GITHUB_TOKEN": "t",
        "GITHUB_OWNER": "test-owner",
        "GITHUB_REPO": "test-repo",
        "PR_NUMBER": "7",
    }.items():
        monkeypatch.setenv(name, value)

    state: dict[str, Any] = {}

    def install(findings, **client_kwargs):
        class FakeGraph:
            async def ainvoke(self, payload):
                state["context"] = payload["context"]
                return {"findings": findings}

        monkeypatch.setattr(main, "build_graph", lambda s: FakeGraph())
        client = TransportFakeClient(settings, **client_kwargs)
        monkeypatch.setattr(main, "GitHubMCPClient", lambda s: client)
        state["client"] = client
        return client

    return install, state


async def test_async_main_full_flow(pipeline):
    install, state = pipeline
    client = install(
        [
            make_finding(line=3, title="Hard-coded token"),
            make_finding(line=2, title="Hard-coded password"),
            make_finding(line=99, title="Far away"),
            make_finding(file="", line=None, title="General design"),
            make_finding(line=None, title="Old summary"),
        ],
        threads=[
            make_thread("OPEN", path="app.py", line=2, author="ai-bot"),
            make_thread("AI-OUT", outdated=True, line=None, original_line=9, author="ai-bot"),
            make_thread("HUMAN-OUT", outdated=True, body="Rename please", author="human"),
        ],
        reviews=[
            {
                "body": summary_marker(
                    summary_fingerprint(make_finding(line=None, title="Old summary"))
                ),
                "author": {"login": "ai-bot"},
            }
        ],
    )

    exit_code = await main.async_main()

    assert exit_code == 0
    # Context: each patch once, with line numbers.
    assert state["context"].count("token = 'abc'") == 1
    assert "     3 +token = 'abc'" in state["context"]
    # Only the agent's outdated thread is resolved.
    assert client.mutation_ids("resolveReviewThread") == ["AI-OUT"]
    # One inline comment, on a valid diff line, in the shared format.
    inline = client.tool_calls("add_comment_to_pending_review")
    assert [(c["path"], c["line"]) for c in inline] == [("app.py", 3)]
    assert AI_COMMENT_MARKER in inline[0]["body"]
    # Summary review: new findings only, markers for summary-only findings.
    assert len(client.tool_calls("pull_request_review_write", "create")) == 1
    submitted = client.tool_calls("pull_request_review_write", "submit_pending")[0]
    assert submitted["event"] == "COMMENT"
    body = submitted["body"]
    assert "Hard-coded token" in body and "Far away" in body and "General design" in body
    assert "Hard-coded password" not in body and "Old summary" not in body
    assert set(SUMMARY_MARKER_RE.findall(body)) == {
        summary_fingerprint(make_finding(line=99, title="Far away")),
        summary_fingerprint(make_finding(file="", line=None, title="General design")),
    }
    # MCP get_diff was not needed (patches present) and fallback not used.
    assert client.tool_calls("pull_request_read", "get_diff") == []
    assert client.tool_calls("pull_request_read", "get_review_comments") == []


async def test_async_main_posts_nothing_when_all_duplicates(pipeline):
    install, _ = pipeline
    client = install(
        [make_finding(line=2, title="Hard-coded password")],
        threads=[make_thread("OPEN", path="app.py", line=2, author="ai-bot")],
    )

    assert await main.async_main() == 0
    assert client.tool_calls("pull_request_review_write") == []


async def test_async_main_fails_when_inline_comment_fails(pipeline):
    install, _ = pipeline
    client = install([make_finding(line=3, title="Hard-coded token")], inline_error=True)

    assert await main.async_main() == 1
    body = client.tool_calls("pull_request_review_write", "submit_pending")[0]["body"]
    # The failed inline finding is still in the summary and tracked by fingerprint.
    assert summary_fingerprint(make_finding(title="Hard-coded token")) in SUMMARY_MARKER_RE.findall(
        body
    )


async def test_async_main_fails_when_thread_resolution_fails(pipeline):
    install, _ = pipeline
    install([], threads=[make_thread("AI-OUT", outdated=True, author="ai-bot")], resolve_ok=False)

    assert await main.async_main() == 1


async def test_async_main_reopens_only_when_enabled(pipeline, monkeypatch):
    install, _ = pipeline
    thread = make_thread("R1", resolved=True, path="app.py", line=3, author="ai-bot")
    finding = make_finding(line=3, title="Hard-coded password")

    client = install([finding], threads=[thread])
    assert await main.async_main() == 0
    assert client.mutation_ids("unresolveReviewThread") == []
    assert client.tool_calls("add_comment_to_pending_review") == []  # resolved = already reported

    monkeypatch.setenv("REOPEN_RESOLVED_THREADS", "true")
    client = install([finding], threads=[thread])
    assert await main.async_main() == 0
    assert client.mutation_ids("unresolveReviewThread") == ["R1"]
    assert client.tool_calls("add_comment_to_pending_review") == []


async def test_load_review_threads_falls_back_to_mcp_and_refuses_unknown(settings):
    client = TransportFakeClient(settings)

    async def broken(*args, **kwargs):
        raise RuntimeError("graphql down")

    client.get_review_threads_graphql = broken

    async def comments(*args, **kwargs):
        return {"review_threads": [make_thread("M1")]}

    client.get_review_comments = comments
    assert [t["id"] for t in await main.load_review_threads(client, settings, 1)] == ["M1"]

    async def garbage(*args, **kwargs):
        return "not a thread list"

    client.get_review_comments = garbage
    with pytest.raises(main.GitHubError, match="refusing to post"):
        await main.load_review_threads(client, settings, 1)


def test_get_pr_number(monkeypatch, tmp_path):
    monkeypatch.setenv("PR_NUMBER", "12")
    assert main.get_pr_number() == 12

    monkeypatch.setenv("PR_NUMBER", "abc")
    with pytest.raises(RuntimeError, match="must be an integer"):
        main.get_pr_number()

    monkeypatch.delenv("PR_NUMBER")
    event = tmp_path / "event.json"
    event.write_text('{"number": 34}', encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    assert main.get_pr_number() == 34
