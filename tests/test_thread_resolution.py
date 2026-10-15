import pytest
from unittest.mock import MagicMock, patch

from src.mcp_github import GitHubMCPClient
from src.config import Settings


@pytest.fixture
def settings():
    """Create test settings."""
    return Settings(
        openai_api_key="test-key",
        openai_model="test-model",
        openai_base_url="https://test.url",
        github_token="test-pat-token",
        github_owner="test-owner",
        github_repo="test-repo",
        max_review_context_chars=120000,
    )


@pytest.fixture
def github_client(settings):
    """Create a GitHubMCPClient for testing."""
    return GitHubMCPClient(settings)


@pytest.mark.asyncio
async def test_graphql_auth_uses_token_scheme(github_client):
    """Verify GraphQL auth uses 'token' scheme, not 'Bearer'."""
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "repository": {
                    "pullRequest": {"reviewThreads": {"nodes": []}}
                }
            }
        }
        mock_post.return_value = mock_response

        await github_client.get_review_threads_graphql("owner", "repo", 1)

        call_args = mock_post.call_args
        headers = call_args.kwargs.get("headers", {})

        assert "Authorization" in headers
        assert headers["Authorization"].startswith("token ")
        assert not headers["Authorization"].startswith("Bearer ")


@pytest.mark.asyncio
async def test_resolve_thread_validates_is_resolved_true(github_client):
    """Verify resolve_thread_graphql validates isResolved is true."""
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "resolveReviewThread": {
                    "thread": {
                        "id": "test-thread-123",
                        "isResolved": True,
                    }
                }
            }
        }
        mock_post.return_value = mock_response

        result = await github_client.resolve_thread_graphql("test-thread-123")

        assert result["isResolved"] is True
        assert result["id"] == "test-thread-123"


@pytest.mark.asyncio
async def test_resolve_thread_fails_if_is_resolved_false(github_client):
    """Verify resolve_thread_graphql raises error if isResolved is false."""
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "resolveReviewThread": {
                    "thread": {
                        "id": "test-thread-123",
                        "isResolved": False,
                    }
                }
            }
        }
        mock_post.return_value = mock_response

        with pytest.raises(RuntimeError, match="did not set isResolved=true"):
            await github_client.resolve_thread_graphql("test-thread-123")


@pytest.mark.asyncio
async def test_resolve_thread_fails_if_no_thread_data(github_client):
    """Verify resolve_thread_graphql raises error if thread data is missing."""
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {"resolveReviewThread": {}}
        }
        mock_post.return_value = mock_response

        with pytest.raises(RuntimeError, match="returned no thread data"):
            await github_client.resolve_thread_graphql("test-thread-123")


@pytest.mark.asyncio
async def test_get_review_threads_extracts_fields(github_client):
    """Verify get_review_threads_graphql extracts all required fields."""
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {
                            "nodes": [
                                {
                                    "id": "thread-1",
                                    "isResolved": False,
                                    "isOutdated": False,
                                    "path": "src/app.py",
                                    "line": 42,
                                    "comments": {
                                        "nodes": [
                                            {"body": "**HIGH — Security**\n\nTest issue"}
                                        ]
                                    },
                                }
                            ]
                        }
                    }
                }
            }
        }
        mock_post.return_value = mock_response

        threads = await github_client.get_review_threads_graphql("owner", "repo", 1)

        assert len(threads) == 1
        assert threads[0]["id"] == "thread-1"
        assert threads[0]["isResolved"] is False
        assert threads[0]["path"] == "src/app.py"
        assert threads[0]["line"] == 42


@pytest.mark.asyncio
async def test_execute_graphql_raises_on_http_error(github_client):
    """Verify execute_graphql raises on HTTP errors."""
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        mock_post.return_value = mock_response

        with pytest.raises(RuntimeError, match="HTTP error 401"):
            await github_client.execute_graphql("query { test }")


@pytest.mark.asyncio
async def test_execute_graphql_raises_on_graphql_errors(github_client):
    """Verify execute_graphql raises on GraphQL errors."""
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "errors": [{"message": "Field 'test' doesn't exist on type 'Query'"}]
        }
        mock_post.return_value = mock_response

        with pytest.raises(RuntimeError, match="GraphQL error"):
            await github_client.execute_graphql("query { test }")


def test_finding_key_generation():
    """Test that finding keys are generated consistently."""
    from main import finding_key

    key1 = finding_key("src/app.py", 42, "SQL Injection")
    key2 = finding_key("src/app.py", 42, "SQL injection")

    assert key1 == key2
    assert "src/app.py:42" in key1


def test_extract_thread_finding_key():
    """Test extraction of finding key from thread."""
    from main import extract_thread_finding_key

    thread = {
        "path": "src/app.py",
        "line": 42,
        "comments": {
            "nodes": [
                {
                    "body": "**HIGH — Security**\n\n**Possible SQL Injection**\n\nDescription here"
                }
            ]
        },
    }

    key = extract_thread_finding_key(thread)
    assert key is not None
    assert "sql injection" in key.lower()


def test_is_ai_review_thread():
    """Test identification of AI review threads."""
    from main import is_ai_review_thread

    ai_thread = {"comments": {"nodes": [{"body": "**Recommendation:** Fix this issue"}]}}

    non_ai_thread = {"comments": {"nodes": [{"body": "Just a regular comment"}]}}

    assert is_ai_review_thread(ai_thread) is True
    assert is_ai_review_thread(non_ai_thread) is False
