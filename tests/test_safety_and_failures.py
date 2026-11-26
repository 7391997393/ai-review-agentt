"""Safety guarantees and failure paths found by the adversarial review.

Each test pins down a behaviour that, if it regressed, would either touch a
human's thread, hide a finding, report false success, or break later runs.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import main
from src.context_builder import build_review_context
from src.diff_utils import parse_unified_patch
from src.mcp_github import GitHubError, GitHubMCPClient
from src.thread_resolver import (
    existing_thread_keys,
    finding_key,
    parse_comment_title,
    select_threads_to_reopen,
    select_threads_to_resolve,
    threads_from_mcp_response,
)
from tests.conftest import AGENT, AI_BODY, PATCH, make_finding, make_thread
from tests.test_main import TransportFakeClient


class FailureClient(TransportFakeClient):
    def __init__(
        self,
        settings,
        *,
        graphql_down=False,
        submit_error=False,
        create_error=False,
        reopen_ok=True,
        mcp_threads=None,
        **kwargs,
    ):
        super().__init__(settings, **kwargs)
        self.graphql_down = graphql_down
        self.submit_error = submit_error
        self.create_error = create_error
        self.reopen_ok = reopen_ok
        self.mcp_threads = mcp_threads or []

    async def execute_graphql(self, query, variables=None):
        if self.graphql_down:
            raise GitHubError("GitHub GraphQL HTTP error 502: bad gateway")
        if "unresolveReviewThread" in query and not self.reopen_ok:
            self.graphql_calls.append((query, variables or {}))
            return {"data": {"unresolveReviewThread": None}}
        return await super().execute_graphql(query, variables)

    async def call(self, tool_name, arguments):
        method = arguments.get("method")
        if tool_name == "pull_request_read" and method == "get_review_comments":
            self.mcp_calls.append((tool_name, arguments))
            return {"review_threads": self.mcp_threads}
        if method == "submit_pending" and self.submit_error:
            self.mcp_calls.append((tool_name, arguments))
            raise GitHubError("MCP tool pull_request_review_write(submit_pending) failed: 502")
        if method == "create" and self.create_error:
            self.mcp_calls.append((tool_name, arguments))
            raise GitHubError("MCP tool pull_request_review_write(create) failed: 422")
        return await super().call(tool_name, arguments)


@pytest.fixture
def run(monkeypatch, settings):
    for name, value in {
        "CG_API_KEY": "k",
        "CG_MODEL": "m",
        "GITHUB_TOKEN": "t",
        "GITHUB_OWNER": "test-owner",
        "GITHUB_REPO": "test-repo",
        "PR_NUMBER": "7",
    }.items():
        monkeypatch.setenv(name, value)

    def install(findings, **kwargs):
        class FakeGraph:
            async def ainvoke(self, payload):
                return {"findings": findings}

        client = FailureClient(settings, **kwargs)
        monkeypatch.setattr(main, "build_graph", lambda s: FakeGraph())
        monkeypatch.setattr(main, "GitHubMCPClient", lambda s: client)
        return client

    return install


# -- never touch human threads -----------------------------------------------------


async def test_ai_formatted_thread_by_another_user_is_not_resolved_in_pipeline(run):
    # Mutation guard: if run_review stopped passing viewer_login, this fails.
    client = run(
        [],
        threads=[
            make_thread("MINE", outdated=True, author=AGENT),
            make_thread("COPYCAT", outdated=True, author="human-reviewer", body=AI_BODY),
        ],
    )
    assert await main.async_main() == 0
    assert client.mutation_ids("resolveReviewThread") == ["MINE"]


async def test_reopen_never_targets_another_users_thread(run, monkeypatch):
    monkeypatch.setenv("REOPEN_RESOLVED_THREADS", "true")
    finding = make_finding(line=3, title="Hard-coded password")
    client = run(
        [finding],
        threads=[make_thread("THEIRS", resolved=True, path="app.py", line=3, author="human")],
    )
    assert await main.async_main() == 0
    assert client.mutation_ids("unresolveReviewThread") == []


async def test_graphql_down_uses_mcp_fallback_and_never_resolves(run):
    # In MCP v2 path/line live on the comments and the author is a string.
    mcp_thread = {
        "id": "PRRT_1",
        "is_resolved": False,
        "is_outdated": False,
        "comments": [{"body": AI_BODY, "path": "app.py", "line": 2, "author": AGENT}],
    }
    outdated = {**mcp_thread, "id": "PRRT_2", "is_outdated": True}
    client = run(
        [make_finding(line=2, title="Hard-coded password"), make_finding(line=3, title="New")],
        graphql_down=True,
        mcp_threads=[mcp_thread, outdated],
    )

    assert await main.async_main() == 0
    # Ownership cannot be verified without GraphQL: nothing is resolved.
    assert client.mutation_ids("resolveReviewThread") == []
    # The MCP thread is understood: its finding is a duplicate, the new one is posted.
    inline = client.tool_calls("add_comment_to_pending_review")
    assert [(c["path"], c["line"]) for c in inline] == [("app.py", 3)]


def test_selection_requires_known_agent_login():
    outdated = make_thread(outdated=True)
    assert select_threads_to_resolve([outdated], None) == []
    key = finding_key("src/app.py", 25, "Hard-coded password")
    assert select_threads_to_reopen([make_thread(resolved=True)], {key}, None) == []


def test_human_thread_in_ai_format_does_not_suppress_agent_finding():
    copycat = make_thread("H", path="app.py", line=3, author="human", body=AI_BODY)
    keys = existing_thread_keys([copycat], agent_login=AGENT)
    plan = main.plan_review(
        [make_finding(line=3, title="Hard-coded password")],
        [{"filename": "app.py", "patch": PATCH}],
        keys,
        set(),
    )
    assert len(plan.inline) == 1 and plan.duplicates == []


# -- failure paths never report success ------------------------------------------------


async def test_submit_failure_deletes_our_pending_review_and_fails(run):
    client = run([make_finding(line=3, title="Hard-coded token")], submit_error=True)

    with pytest.raises(GitHubError, match="submit_pending"):
        await main.async_main()

    assert len(client.tool_calls("pull_request_review_write", "delete_pending")) == 1


async def test_create_failure_explains_pending_review_and_deletes_nothing(run):
    client = run([make_finding(line=3, title="Hard-coded token")], create_error=True)

    with pytest.raises(GitHubError, match="pending \\(draft\\) review"):
        await main.async_main()

    assert client.tool_calls("pull_request_review_write", "delete_pending") == []
    assert client.tool_calls("add_comment_to_pending_review") == []


async def test_reopen_failure_exits_non_zero(run, monkeypatch):
    monkeypatch.setenv("REOPEN_RESOLVED_THREADS", "true")
    client = run(
        [make_finding(line=3, title="Hard-coded password")],
        threads=[make_thread("R1", resolved=True, path="app.py", line=3)],
        reopen_ok=False,
    )
    assert await main.async_main() == 1
    assert client.mutation_ids("unresolveReviewThread") == ["R1"]


# -- parsing robustness --------------------------------------------------------------


def test_form_feed_and_unicode_separators_do_not_shift_line_numbers():
    patch_text = "@@ -1,2 +1,4 @@\n line1\n+\x0c\n+x = ' '\n line3"
    assert sorted(parse_unified_patch(patch_text)) == [1, 2, 3, 4]
    assert parse_unified_patch(patch_text)[4] == "line3"


def test_trailing_newline_is_not_an_extra_context_line():
    assert sorted(parse_unified_patch(PATCH + "\n")) == [1, 2, 3, 4]


def test_legacy_title_containing_em_dash_is_parsed():
    body = "**HIGH — Security**\n\n**Use of eval — dangerous**\n\nd\n\n**Recommendation:** r"
    assert parse_comment_title(body) == "Use of eval — dangerous"


def test_mcp_review_threads_are_normalised():
    raw = {"id": "T", "comments": [{"body": AI_BODY, "path": "a.py", "line": 4, "author": "bot"}]}
    thread = threads_from_mcp_response({"review_threads": [raw]})[0]
    assert thread["path"] == "a.py" and thread["line"] == 4
    assert thread["comments"][0]["author"] == {"login": "bot"}


def test_rest_comment_with_null_line_is_outdated():
    pseudo = threads_from_mcp_response(
        [{"path": "a.py", "line": None, "original_line": 9, "body": AI_BODY}]
    )[0]
    assert pseudo["isOutdated"] is True
    assert existing_thread_keys([pseudo]) == set()


def test_raw_diff_fallback_lists_omitted_files_and_never_cuts_mid_hunk():
    diff = (
        "diff --git a/a.py b/a.py\n@@ -1 +1,3 @@\n+a1\n+a2\n+a3\n"
        "diff --git a/b.py b/b.py\n@@ -1 +1,300 @@\n" + "+b\n" * 300
    )
    ctx = build_review_context(
        {"title": "T"}, [{"filename": "a.py"}, {"filename": "b.py"}], 450, raw_diff=diff
    )
    assert ctx.truncated
    assert ctx.included_files == ["a.py"] and ctx.omitted_files == ["b.py"]
    assert "+b" not in ctx.text and len(ctx.text) <= 450

    tiny = build_review_context({"title": "T"}, [], 200, raw_diff="@@ -1 +1,90 @@\n" + "+z\n" * 90)
    assert "+z" not in tiny.text and len(tiny.text) <= 200


def test_patch_without_text_that_does_not_fit_is_listed_as_omitted():
    files = [{"filename": "a.py", "patch": PATCH}, {"filename": "secret.bin", "status": "added"}]
    ctx = build_review_context({"title": "T"}, files, 260)
    assert "secret.bin" in ctx.omitted_files or "secret.bin" in ctx.text
    assert len(ctx.text) <= 260


# -- configuration -------------------------------------------------------------------


@pytest.mark.parametrize("value", ["", "verbose", "  debug  "])
def test_log_level_never_crashes(monkeypatch, value):
    monkeypatch.setenv("LOG_LEVEL", value)
    with patch("logging.basicConfig") as basic:
        main.configure_logging()
    expected = "DEBUG" if value.strip().lower() == "debug" else "INFO"
    assert basic.call_args.kwargs["level"] == expected


async def test_connect_starts_pinned_image_with_limited_toolsets(settings, monkeypatch):
    captured = {}

    class FakeStdio:
        def __init__(self, server):
            captured["server"] = server

        async def __aenter__(self):
            return "read", "write"

        async def __aexit__(self, *exc):
            return None

    class FakeSession:
        def __init__(self, read, write):
            pass

        async def __aenter__(self):
            return SimpleNamespace(initialize=AsyncMock())

        async def __aexit__(self, *exc):
            return None

    monkeypatch.setenv("GITHUB_MCP_COMMAND", "docker")
    monkeypatch.setattr("src.mcp_github.shutil.which", lambda name: name)
    monkeypatch.setattr("src.mcp_github.stdio_client", FakeStdio)
    monkeypatch.setattr("src.mcp_github.ClientSession", FakeSession)
    client = GitHubMCPClient(settings)

    await client.connect()
    await client.close()

    server = captured["server"]
    assert server.command == "docker"
    assert server.args[-1] == settings.mcp_image == "ghcr.io/github/github-mcp-server:v2.0.3"
    assert server.env["GITHUB_TOOLSETS"] == "repos,pull_requests,issues"
    assert server.env["GITHUB_PERSONAL_ACCESS_TOKEN"] == settings.github_token
    # The token is passed through the environment, never on the command line.
    assert settings.github_token not in " ".join(server.args)


async def test_review_body_is_not_logged_at_info(run, caplog):
    caplog.set_level(logging.INFO)
    run([make_finding(line=3, title="Token", description="DESCRIPTION-TEXT-XYZ")])

    assert await main.async_main() == 0

    assert "Review submitted: 1 finding(s), 1 inline comment(s)." in caplog.text
    assert "DESCRIPTION-TEXT-XYZ" not in caplog.text


async def test_another_users_ai_formatted_thread_does_not_hide_finding_in_pipeline(run):
    # Pipeline-level guard: duplicate detection must use the agent login too.
    client = run(
        [make_finding(line=3, title="Hard-coded password")],
        threads=[make_thread("COPY", path="app.py", line=3, author="human", body=AI_BODY)],
    )
    assert await main.async_main() == 0
    inline = client.tool_calls("add_comment_to_pending_review")
    assert [(c["path"], c["line"]) for c in inline] == [("app.py", 3)]


def test_truncation_note_always_survives_within_budget():
    note = "[Review context truncated because the Pull Request is too large.]"
    patch_text = "@@ -1 +1,12 @@\n" + "+value = compute()\n" * 12
    files = [{"filename": f"m{i:03d}.py", "patch": patch_text} for i in range(60)]
    for budget in range(700, 6000, 37):
        ctx = build_review_context({"title": "T"}, files, budget)
        assert len(ctx.text) <= budget, budget
        assert ctx.text.endswith(note), budget


# -- legacy comments and agent identities (found with real PR data) --------------------


OLDEST_LAYOUT = (
    "**Hard-coded secret in source code**\n\n"
    "An API key is hard-coded.\n\n"
    "**Recommendation:** Load it from a secret store."
)


def test_oldest_comment_layout_without_header_is_recognised():
    thread = make_thread(body=OLDEST_LAYOUT, path="app.py", line=3, author="github-actions[bot]")
    assert parse_comment_title(OLDEST_LAYOUT) == "Hard-coded secret in source code"
    keys = existing_thread_keys([thread], agent_login={"ai-bot", "github-actions[bot]"})
    assert keys == {finding_key("app.py", 3, "Hard-coded secret in source code")}


def test_bold_text_without_recommendation_is_not_ai_layout():
    for body in ("**Bug**\n\nthis breaks", "**Bug** here\n\n**Recommendation:** x", "plain"):
        assert existing_thread_keys([make_thread(body=body)], agent_login=AGENT) == set()


async def test_extra_agent_logins_cover_threads_from_older_runs(run, monkeypatch):
    monkeypatch.setenv("AGENT_LOGINS", "github-actions[bot]")
    client = run(
        [],
        threads=[
            make_thread("OLD-BOT", outdated=True, body=OLDEST_LAYOUT, author="github-actions[bot]"),
            make_thread("HUMAN", outdated=True, body=OLDEST_LAYOUT, author="human"),
        ],
    )
    assert await main.async_main() == 0
    assert client.mutation_ids("resolveReviewThread") == ["OLD-BOT"]


async def test_without_extra_logins_older_bot_threads_are_left_alone(run):
    client = run([], threads=[make_thread("OLD-BOT", outdated=True, author="github-actions[bot]")])
    assert await main.async_main() == 0
    assert client.mutation_ids("resolveReviewThread") == []


def test_http_client_loggers_are_quietened_including_httpx2(monkeypatch):
    # A live run showed the HTTP client logging under the name "httpx2".
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    with patch("logging.basicConfig"):
        main.configure_logging()
    for name in ("httpx", "httpx2", "httpcore", "openai", "mcp"):
        assert logging.getLogger(name).level == logging.WARNING
