"""GitHubMCPClient tests. The HTTP transport and the MCP session are mocked."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.mcp_github import GitHubError, GitHubMCPClient
from tests.conftest import graphql_mutation_response


@pytest.fixture
def github_client(settings):
    return GitHubMCPClient(settings)


def http_response(status=200, json_data=None, text=""):
    response = MagicMock()
    response.status_code = status
    response.text = text
    if isinstance(json_data, Exception):
        response.json.side_effect = json_data
    else:
        response.json.return_value = json_data
    return response


# -- execute_graphql ------------------------------------------------------------


async def test_graphql_auth_uses_token_scheme(github_client):
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as post:
        post.return_value = http_response(json_data={"data": {}})

        await github_client.execute_graphql("query { viewer { login } }")

        headers = post.call_args.kwargs["headers"]
        assert headers["Authorization"] == "token test-pat-token"


async def test_http_client_is_reused_and_closed(github_client):
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as post:
        post.return_value = http_response(json_data={"data": {}})
        await github_client.execute_graphql("q")
        first = github_client._http
        await github_client.execute_graphql("q")
        assert github_client._http is first

    await github_client.close()
    assert github_client._http is None


@pytest.mark.parametrize(
    ("response", "match"),
    [
        (http_response(status=401, text="Unauthorized"), "HTTP error 401"),
        (http_response(json_data={"errors": [{"message": "bad field"}]}), "bad field"),
        (http_response(json_data=ValueError("no json")), "non-JSON"),
        (http_response(json_data=["not", "a", "dict"]), "unexpected response shape"),
    ],
)
async def test_execute_graphql_raises_on_errors(github_client, response, match):
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=response):
        with pytest.raises(GitHubError, match=match):
            await github_client.execute_graphql("query { test }")


async def test_execute_graphql_wraps_transport_errors(github_client):
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as post:
        post.side_effect = httpx.ConnectError("boom")
        with pytest.raises(GitHubError, match="ConnectError"):
            await github_client.execute_graphql("q")


# -- resolve / reopen ------------------------------------------------------------


async def test_resolve_thread_sends_mutation_and_confirms(github_client):
    github_client.execute_graphql = AsyncMock(
        return_value=graphql_mutation_response("resolveReviewThread", "T1", True)
    )

    thread = await github_client.resolve_thread("T1")

    assert thread == {"id": "T1", "isResolved": True}
    query, variables = github_client.execute_graphql.call_args.args
    assert "resolveReviewThread" in query and "unresolve" not in query
    assert variables == {"threadId": "T1"}


async def test_reopen_thread_uses_unresolve_mutation(github_client):
    github_client.execute_graphql = AsyncMock(
        return_value=graphql_mutation_response("unresolveReviewThread", "T2", False)
    )

    thread = await github_client.reopen_thread("T2")

    assert thread["isResolved"] is False
    query, variables = github_client.execute_graphql.call_args.args
    assert "unresolveReviewThread" in query
    assert variables == {"threadId": "T2"}


@pytest.mark.parametrize(
    "payload",
    [
        {"data": None},
        {"data": {"resolveReviewThread": None}},
        {"data": {"resolveReviewThread": {"thread": None}}},
    ],
)
async def test_resolve_thread_null_data_is_an_error(github_client, payload):
    github_client.execute_graphql = AsyncMock(return_value=payload)
    with pytest.raises(GitHubError, match="returned no thread data"):
        await github_client.resolve_thread("T1")


async def test_resolve_thread_fails_if_not_resolved(github_client):
    github_client.execute_graphql = AsyncMock(
        return_value=graphql_mutation_response("resolveReviewThread", "T1", False)
    )
    with pytest.raises(GitHubError, match="did not set isResolved=true"):
        await github_client.resolve_thread("T1")


async def test_reopen_thread_fails_if_still_resolved(github_client):
    github_client.execute_graphql = AsyncMock(
        return_value=graphql_mutation_response("unresolveReviewThread", "T1", True)
    )
    with pytest.raises(GitHubError, match="did not set isResolved=false"):
        await github_client.reopen_thread("T1")


@pytest.mark.parametrize("thread_id", ["", "   ", None])
async def test_missing_thread_id_is_rejected_without_api_call(github_client, thread_id):
    github_client.execute_graphql = AsyncMock()
    with pytest.raises(GitHubError, match="thread ID is required"):
        await github_client.resolve_thread(thread_id)
    github_client.execute_graphql.assert_not_called()


def test_resolve_thread_is_defined_once():
    import inspect

    import src.mcp_github as module

    source = inspect.getsource(module)
    assert source.count("async def resolve_thread(") == 1
    assert source.count("async def reopen_thread(") == 1


# -- thread / review queries -----------------------------------------------------


def threads_page(nodes, has_next=False, cursor=None, viewer="ai-bot"):
    return {
        "data": {
            "viewer": {"login": viewer},
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
                        "nodes": nodes,
                    }
                }
            },
        }
    }


async def test_review_threads_follow_pagination_and_record_viewer(github_client):
    github_client.execute_graphql = AsyncMock(
        side_effect=[
            threads_page([{"id": "A"}], has_next=True, cursor="c1"),
            threads_page([{"id": "B"}]),
        ]
    )

    threads = await github_client.get_review_threads_graphql("o", "r", 1)

    assert [t["id"] for t in threads] == ["A", "B"]
    assert github_client.viewer_login == "ai-bot"
    second_vars = github_client.execute_graphql.call_args_list[1].args[1]
    assert second_vars["after"] == "c1"


async def test_review_threads_null_pull_request_returns_empty(github_client):
    github_client.execute_graphql = AsyncMock(return_value={"data": {"repository": None}})
    assert await github_client.get_review_threads_graphql("o", "r", 1) == []


async def test_reviews_query_returns_bodies(github_client):
    github_client.execute_graphql = AsyncMock(
        return_value={
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviews": {
                            "pageInfo": {"hasNextPage": False},
                            "nodes": [{"body": "x", "author": {"login": "ai-bot"}}],
                        }
                    }
                }
            }
        }
    )
    assert await github_client.get_reviews_graphql("o", "r", 1) == [
        {"body": "x", "author": {"login": "ai-bot"}}
    ]


# -- MCP calls -------------------------------------------------------------------


def mcp_result(text="", is_error=False, structured=None):
    return SimpleNamespace(
        content=[SimpleNamespace(text=text)] if text else [],
        isError=is_error,
        structuredContent=structured,
    )


async def test_mcp_tool_error_raises_instead_of_returning_text(github_client):
    github_client.session = MagicMock()
    github_client.session.call_tool = AsyncMock(
        return_value=mcp_result("line must be part of the diff", is_error=True)
    )

    with pytest.raises(GitHubError, match="line must be part of the diff"):
        await github_client.add_inline_comment("o", "r", 1, "a.py", 3, "body")


async def test_mcp_call_without_session_raises(github_client):
    with pytest.raises(GitHubError, match="not connected"):
        await github_client.call("pull_request_read", {})


async def test_fetch_pull_request_paginates_files_without_raw_diff(github_client):
    page1 = [{"filename": f"f{i}.py", "patch": "@@ -1 +1 @@\n+x"} for i in range(100)]
    page2 = [{"filename": "last.py", "patch": "@@ -1 +1 @@\n+y"}]
    calls = []

    async def fake_call(tool, args):
        calls.append(args["method"])
        if args["method"] == "get":
            return {"title": "T"}
        return page1 if args["page"] == 1 else page2

    github_client.call = fake_call

    data = await github_client.fetch_pull_request("o", "r", 1)

    assert len(data.changed_files) == 101
    assert data.raw_diff is None
    assert calls == ["get", "get_files", "get_files"]


async def test_fetch_pull_request_falls_back_to_diff_when_no_patches(github_client):
    async def fake_call(tool, args):
        return {
            "get": {"title": "T"},
            "get_files": {"files": [{"filename": "a.py"}]},
            "get_diff": "diff --git a/a.py b/a.py",
        }[args["method"]]

    github_client.call = fake_call

    data = await github_client.fetch_pull_request("o", "r", 1)

    assert data.changed_files == [{"filename": "a.py"}]
    assert data.raw_diff == "diff --git a/a.py b/a.py"
