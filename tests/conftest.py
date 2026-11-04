"""Shared fixtures and fakes. No test talks to GitHub, Docker or an LLM."""

from __future__ import annotations

from typing import Any

import pytest

from src.config import Settings
from src.schemas import Finding

AI_BODY = (
    "**HIGH — Security**\n\n"
    "**Hard-coded password**\n\n"
    "A password is stored in code.\n\n"
    "**Recommendation:** Use an environment variable."
)

PATCH = "\n".join(
    [
        "@@ -1,3 +1,4 @@",
        " import os",
        "-password = 'x'",
        "+password = os.environ['PASSWORD']",
        "+token = 'abc'",
        " print('ok')",
    ]
)  # new-file lines: 1 context, 2 added, 3 added, 4 context


@pytest.fixture
def settings() -> Settings:
    return Settings(
        openai_api_key="test-key",
        openai_model="test-model",
        openai_base_url="https://test.url",
        github_token="test-pat-token",
        github_owner="test-owner",
        github_repo="test-repo",
        max_review_context_chars=120000,
    )


def make_finding(**overrides: Any) -> Finding:
    data = {
        "category": "security",
        "severity": "high",
        "file": "app.py",
        "line": 3,
        "title": "Hard-coded token",
        "description": "A token is stored in code.",
        "recommendation": "Load it from a secret store.",
        "confidence": 0.9,
    }
    data.update(overrides)
    return Finding(**data)


def make_thread(
    thread_id: str | None = "T1",
    *,
    resolved: bool = False,
    outdated: bool = False,
    body: str = AI_BODY,
    path: str = "src/app.py",
    line: int | None = 25,
    original_line: int | None = None,
    author: str | None = None,
    extra_comments: list[dict] | None = None,
) -> dict[str, Any]:
    first: dict[str, Any] = {"body": body}
    if author:
        first["author"] = {"login": author}
    return {
        "id": thread_id,
        "isResolved": resolved,
        "isOutdated": outdated,
        "path": path,
        "line": line,
        "originalLine": original_line,
        "comments": {"nodes": [first, *(extra_comments or [])]},
    }


def graphql_mutation_response(field: str, thread_id: str, is_resolved: bool) -> dict:
    return {"data": {field: {"thread": {"id": thread_id, "isResolved": is_resolved}}}}
