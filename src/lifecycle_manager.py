"""Review lifecycle management helpers."""
from __future__ import annotations

import datetime
from typing import Any, Iterable

from src.lifecycle import decode_state, encode_state, finding_key, is_line_in_patch


class LifecycleManager:
    """Track review lifecycle state across review runs."""

    def __init__(self, github_client: Any):
        self.github = github_client

    async def load_state(self, owner: str, repo: str, pull_number: int) -> dict[str, Any]:
        try:
            comments = await self.github.get_review_comments(owner, repo, pull_number)
        except Exception:
            return {}

        if not comments:
            return {}

        for comment in comments:
            body = None
            if isinstance(comment, dict):
                body = comment.get("body")
            elif hasattr(comment, "body"):
                body = getattr(comment, "body")
            state = decode_state(body)
            if state:
                return state
        return {}

    async def save_state(self, owner: str, repo: str, pull_number: int, state: dict[str, Any]) -> None:
        payload = encode_state(state)
        try:
            await self.github.create_review(owner, repo, pull_number, payload)
            await self.github.submit_review(owner, repo, pull_number, payload)
        except Exception:
            # Save is best-effort; do not fail the whole review when state persistence is unavailable.
            return

    def reconcile_state(
        self,
        current_findings: Iterable[dict[str, Any] | Any],
        stored_state: dict[str, Any] | None,
        changed_files: Iterable[dict[str, Any]] | None = None,
    ) -> tuple[dict[str, Any], list[tuple[str, str, dict[str, Any] | None]]]:
        """Return updated state and lifecycle actions.

        Actions are tuples of (action, finding_key, finding). Supported actions:
        new, existing, resolved, reopen.
        """
        state = stored_state or {}
        findings_state = state.get("findings", {}) if isinstance(state, dict) else {}
        now = datetime.datetime.utcnow().isoformat() + "Z"
        new_state: dict[str, Any] = {"findings": {}, "meta": {"last_run_iso": now}}
        actions: list[tuple[str, str, dict[str, Any] | None]] = []

        current_map: dict[str, dict[str, Any]] = {}
        for finding in current_findings:
            if hasattr(finding, "model_dump"):
                data = finding.model_dump()
            elif isinstance(finding, dict):
                data = finding
            else:
                data = {"file": "", "line": None, "title": str(finding), "description": ""}
            key = finding_key(data)
            current_map[key] = data

        for key, finding in current_map.items():
            entry = findings_state.get(key, {}) if isinstance(findings_state, dict) else {}
            if not entry:
                new_state["findings"][key] = {
                    "finding_key": key,
                    "thread_id": None,
                    "status": "open",
                    "reviewed_lines": {finding.get("file", ""): [finding.get("line")] if finding.get("line") else []},
                    "diagnostics": {},
                }
                actions.append(("new", key, finding))
                continue

            next_entry = dict(entry)
            if next_entry.get("status") == "resolved":
                next_entry["status"] = "open"
                actions.append(("reopen", key, finding))
            else:
                actions.append(("existing", key, finding))

            reviewed = next_entry.get("reviewed_lines", {}) or {}
            file_name = finding.get("file") or ""
            lines = list(reviewed.get(file_name, []))
            line = finding.get("line")
            if line is not None and line not in lines:
                lines.append(line)
            if file_name:
                reviewed[file_name] = lines
            next_entry["reviewed_lines"] = reviewed
            next_entry.setdefault("diagnostics", {})
            new_state["findings"][key] = next_entry

        for key, entry in (findings_state or {}).items():
            if key not in current_map:
                next_entry = dict(entry)
                next_entry["status"] = "resolved"
                next_entry.setdefault("diagnostics", {})
                new_state["findings"][key] = next_entry
                actions.append(("resolved", key, None))

        return new_state, actions

    def validate_finding_against_changed_files(
        self,
        finding: dict[str, Any] | Any,
        changed_files: Iterable[dict[str, Any]] | None,
    ) -> bool:
        """Return False if the file or line is not part of the PR diff."""
        if hasattr(finding, "model_dump"):
            finding = finding.model_dump()
        if not isinstance(finding, dict):
            return True

        file_name = finding.get("file")
        line = finding.get("line")
        if not file_name:
            return True

        if not changed_files:
            return True

        for changed in changed_files:
            if not isinstance(changed, dict):
                continue
            candidate = (
                changed.get("filename")
                or changed.get("fileName")
                or changed.get("path")
                or changed.get("name")
            )
            if candidate != file_name:
                continue
            patch = changed.get("patch") or changed.get("diff") or changed.get("patch_text")
            if line is None:
                return True
            return is_line_in_patch(patch, int(line))
        return False


__all__ = ["LifecycleManager"]
