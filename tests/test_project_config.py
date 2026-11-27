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


def test_apm_manifest_matches_project_and_uses_no_docker():
    manifest = (ROOT / "apm.yml").read_text(encoding="utf-8")
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert f'version: "{project["version"]}"' in manifest
    assert f"name: {project['name']}" in manifest
    assert "docker" not in manifest.lower()
    assert "${env:GITHUB_TOKEN}" in manifest  # the token is referenced, never written down


def test_apm_agent_is_in_a_folder_apm_recognises():
    # APM only scans .apm/agents/ (plural) for files named <name>.agent.md.
    agents = sorted((ROOT / ".apm" / "agents").glob("*.agent.md"))
    assert agents, "no .apm/agents/*.agent.md found"
    text = agents[0].read_text(encoding="utf-8")
    assert text.startswith("---\n") and "\nname: " in text and "\ndescription: " in text
    assert not (ROOT / ".apm" / "agent").exists()  # the singular folder is ignored by APM
