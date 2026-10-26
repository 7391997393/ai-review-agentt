import asyncio

from src.lifecycle import finding_key
from src.lifecycle_manager import LifecycleManager


class FakeGithub:
    def __init__(self):
        self.resolved = []
        self.reopened = []
        self.failed = False

    async def resolve_thread(self, owner: str, repo: str, thread_id: str) -> bool:
        if self.failed:
            raise RuntimeError("thread missing")
        self.resolved.append((owner, repo, thread_id))
        return True

    async def reopen_thread(self, owner: str, repo: str, thread_id: str) -> bool:
        if self.failed:
            raise RuntimeError("thread missing")
        self.reopened.append((owner, repo, thread_id))
        return True


def test_execute_lifecycle_action_resolved_updates_state():
    github = FakeGithub()
    manager = LifecycleManager(github)

    finding = {
        "file": "app.py",
        "line": 7,
        "title": "Hardcoded secret",
        "description": "token defined inline",
    }
    key = finding_key(finding)

    state = {
        "findings": {
            key: {
                "finding_key": key,
                "thread_id": "thread-123",
                "status": "open",
                "updated_at": "old",
            }
        },
        "thread_mappings": {
            key: {
                "finding_key": key,
                "thread_id": "thread-123",
                "status": "open",
                "updated_at": "old",
            }
        },
    }

    updated = asyncio.run(
        manager.execute_lifecycle_action("owner", "repo", state, "resolved", key, finding)
    )

    assert github.resolved == [("owner", "repo", "thread-123")]
    assert updated["findings"][key]["status"] == "resolved"
    assert updated["thread_mappings"][key]["status"] == "resolved"


def test_execute_lifecycle_action_reopen_updates_state():
    github = FakeGithub()
    manager = LifecycleManager(github)

    finding = {
        "file": "app.py",
        "line": 7,
        "title": "Hardcoded secret",
        "description": "token defined inline",
    }
    key = finding_key(finding)

    state = {
        "findings": {
            key: {
                "finding_key": key,
                "thread_id": "thread-456",
                "status": "resolved",
                "updated_at": "old",
            }
        },
        "thread_mappings": {
            key: {
                "finding_key": key,
                "thread_id": "thread-456",
                "status": "resolved",
                "updated_at": "old",
            }
        },
    }

    updated = asyncio.run(
        manager.execute_lifecycle_action("owner", "repo", state, "reopen", key, finding)
    )

    assert github.reopened == [("owner", "repo", "thread-456")]
    assert updated["findings"][key]["status"] == "reopened"
    assert updated["thread_mappings"][key]["status"] == "reopened"


def test_execute_lifecycle_action_missing_thread_id_is_safe():
    github = FakeGithub()
    manager = LifecycleManager(github)

    state = {
        "findings": {},
        "thread_mappings": {},
    }

    updated = asyncio.run(
        manager.execute_lifecycle_action("owner", "repo", state, "resolved", "missing-key", {})
    )

    assert updated == state
    assert github.resolved == []
    assert github.reopened == []


def test_execute_lifecycle_action_missing_thread_is_safe():
    github = FakeGithub()
    github.failed = True
    manager = LifecycleManager(github)

    finding = {
        "file": "app.py",
        "line": 7,
        "title": "Hardcoded secret",
        "description": "token defined inline",
    }
    key = finding_key(finding)

    state = {
        "findings": {
            key: {
                "finding_key": key,
                "thread_id": "thread-ghost",
                "status": "open",
                "updated_at": "old",
            }
        },
        "thread_mappings": {
            key: {
                "finding_key": key,
                "thread_id": "thread-ghost",
                "status": "open",
                "updated_at": "old",
            }
        },
    }

    updated = asyncio.run(
        manager.execute_lifecycle_action("owner", "repo", state, "resolved", key, finding)
    )

    assert github.resolved == []
    assert updated["findings"][key]["status"] == "open"
