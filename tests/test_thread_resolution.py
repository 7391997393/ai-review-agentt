import asyncio
from unittest.mock import AsyncMock
 
import pytest
 
from main import resolve_outdated_threads
 

def test_resolves_outdated_unresolved_thread():
    github = AsyncMock()
    settings = AsyncMock()
    settings.github_owner = "test-owner"
    settings.github_repo = "test-repo"
 
    response = {
        "review_threads": [
            {
                "id": "thread-1",
                "is_resolved": False,
                "is_outdated": True,
            }
        ]
    }
 
    asyncio.run(
    resolve_outdated_threads(
        github, settings, 12, response
    )
)
 
    github.resolve_thread.assert_awaited_once_with(
        owner="test-owner",
        repo="test-repo",
        pull_number=12,
        thread_id="thread-1",
    )
 
def test_skips_already_resolved_thread():
    github = AsyncMock()
    settings = AsyncMock()
 
    response = {
        "review_threads": [
            {
                "id": "thread-1",
                "is_resolved": True,
                "is_outdated": True,
            }
        ]
    }
 
    asyncio.run(
    resolve_outdated_threads(
        github, settings, 12, response
    )
)
 
    github.resolve_thread.assert_not_awaited()
 

def test_skips_non_outdated_thread():
    github = AsyncMock()
    settings = AsyncMock()
 
    response = {
        "review_threads": [
            {
                "id": "thread-1",
                "is_resolved": False,
                "is_outdated": False,
            }
        ]
    }
 
    asyncio.run(
    resolve_outdated_threads(
        github, settings, 12, response
    )
)
 
    github.resolve_thread.assert_not_awaited()
 
def test_skips_thread_without_id():
    github = AsyncMock()
    settings = AsyncMock()
 
    response = {
        "review_threads": [
            {
                "is_resolved": False,
                "is_outdated": True,
            }
        ]
    }
 
    asyncio.run(
    resolve_outdated_threads(
        github, settings, 12, response
    )
)
 
    github.resolve_thread.assert_not_awaited()
 
 
def test_resolution_failure_does_not_raise():
    github = AsyncMock()
    github.resolve_thread.side_effect = RuntimeError(
        "MCP resolution failed"
    )
    settings = AsyncMock()
    settings.github_owner = "test-owner"
    settings.github_repo = "test-repo"
 
    response = {
        "review_threads": [
            {
                "id": "thread-1",
                "is_resolved": False,
                "is_outdated": True,
            }
        ]
    }
 
    asyncio.run(
    resolve_outdated_threads(
        github, settings, 12, response
    )
)

def test_handles_invalid_response():
    github = AsyncMock()
    settings = AsyncMock()
 
    asyncio.run(
    resolve_outdated_threads(
        github, settings, 12, None
    )
)

    github.resolve_thread.assert_not_awaited()