import asyncio

from src.lifecycle import finding_key
from src.lifecycle_manager import LifecycleManager


class FakeGithub:
    def __init__(self):
        self.calls = []

    async def resolve_thread(self, owner: str, repo: str, thread_id: str):
        self.calls.append(("resolve", owner, repo, thread_id))
        return True

    async def reopen_thread(self, owner: str, repo: str, thread_id: str):
        self.calls.append(("reopen", owner, repo, thread_id))
        return True


def test_e2e_resolved_flow_executes_and_updates_state():
    github = FakeGithub()
    manager = LifecycleManager(github)

    finding = {
        "file": "app.py",
        "line": 10,
        "title": "Potential SQL injection",
        "description": "User input concatenated into SQL",
    }
    key = finding_key(finding)

    state = {
        "findings": {
            key: {"finding_key": key, "thread_id": "t-1", "status": "open"}
        },
        "thread_mappings": {
            key: {"finding_key": key, "thread_id": "t-1", "status": "open"}
        },
    }

    updated = asyncio.run(
        manager.execute_lifecycle_actions("owner", "repo", state, [("resolved", key, finding)])
    )

    assert github.calls == [("resolve", "owner", "repo", "t-1")]
    assert updated["findings"][key]["status"] == "resolved"
    assert updated["thread_mappings"][key]["status"] == "resolved"


def test_e2e_reopen_flow_executes_and_updates_state():
    github = FakeGithub()
    manager = LifecycleManager(github)

    finding = {
        "file": "app.py",
        "line": 10,
        "title": "Potential SQL injection",
        "description": "User input concatenated into SQL",
    }
    key = finding_key(finding)

    state = {
        "findings": {
            key: {"finding_key": key, "thread_id": "t-2", "status": "resolved"}
        },
        "thread_mappings": {
            key: {"finding_key": key, "thread_id": "t-2", "status": "resolved"}
        },
    }

    updated = asyncio.run(
        manager.execute_lifecycle_actions("owner", "repo", state, [("reopen", key, finding)])
    )

    assert github.calls == [("reopen", "owner", "repo", "t-2")]
    assert updated["findings"][key]["status"] == "reopened"
    assert updated["thread_mappings"][key]["status"] == "reopened"
