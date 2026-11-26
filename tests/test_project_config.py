"""Guards against the dependency lists drifting apart."""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def requirement_lines(name: str) -> set[str]:
    lines = (ROOT / name).read_text(encoding="utf-8").splitlines()
    return {line.strip() for line in lines if line.strip() and not line.startswith(("#", "-r"))}


def test_runtime_requirements_match_pyproject():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert requirement_lines("requirements.txt") == set(project["dependencies"])


def test_dev_requirements_match_pyproject():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert requirement_lines("requirements-dev.txt") == set(project["optional-dependencies"]["dev"])


def test_workflow_installs_only_runtime_requirements():
    workflow = (ROOT / ".github/workflows/reusable-ai-review.yml").read_text(encoding="utf-8")
    assert "pip install -r requirements.txt" in workflow
    assert "requirements-dev" not in workflow


def test_workflow_uses_standalone_mcp_binary_matching_pinned_version():
    from src.config import DEFAULT_MCP_IMAGE

    workflow = (ROOT / ".github/workflows/reusable-ai-review.yml").read_text(encoding="utf-8")
    pinned = DEFAULT_MCP_IMAGE.rsplit(":", 1)[1]
    assert f"MCP_VERSION: {pinned}" in workflow
    assert "GITHUB_MCP_COMMAND=" in workflow
    assert "sha256sum -c" in workflow  # the download is verified
    assert "docker" not in workflow.lower()
