"""How the GitHub MCP server is started: Docker image or a local binary."""

import pytest

from src.mcp_github import MCP_TOOLSETS, GitHubError, GitHubMCPClient, resolve_mcp_launch

IMAGE = "ghcr.io/github/github-mcp-server:v2.0.3"
BINARY = r"C:\tools\github-mcp-server\github-mcp-server.exe"


@pytest.fixture
def which(monkeypatch):
    """Control which executables exist: `which({"docker": "/usr/bin/docker"})`."""

    def install(found: dict[str, str]):
        monkeypatch.setattr("src.mcp_github.shutil.which", lambda name: found.get(name))

    return install


def test_explicit_binary_path_uses_stdio_with_limited_toolsets(monkeypatch, which):
    monkeypatch.setenv("GITHUB_MCP_COMMAND", BINARY)
    which({BINARY: BINARY})

    command, args = resolve_mcp_launch(IMAGE)

    assert command == BINARY
    assert args == ["stdio", f"--toolsets={MCP_TOOLSETS}"]
    assert "docker" not in command.lower()


def test_quoted_path_from_env_file_is_accepted(monkeypatch, which):
    monkeypatch.setenv("GITHUB_MCP_COMMAND", f'"{BINARY}"')
    which({BINARY: BINARY})

    assert resolve_mcp_launch(IMAGE)[0] == BINARY


def test_missing_binary_fails_with_actionable_message(monkeypatch, which):
    monkeypatch.setenv("GITHUB_MCP_COMMAND", BINARY)
    which({})

    with pytest.raises(GitHubError, match="binary not found"):
        resolve_mcp_launch(IMAGE)


def test_docker_still_works_when_selected(monkeypatch, which):
    monkeypatch.setenv("GITHUB_MCP_COMMAND", "docker")
    which({"docker": "/usr/bin/docker"})

    command, args = resolve_mcp_launch(IMAGE)

    assert command == "/usr/bin/docker"
    assert args[:3] == ["run", "--rm", "-i"]
    assert args[-1] == IMAGE


def test_docker_selected_but_not_installed_explains_the_fix(monkeypatch, which):
    monkeypatch.setenv("GITHUB_MCP_COMMAND", "docker")
    which({})

    with pytest.raises(GitHubError, match="Docker is not installed"):
        resolve_mcp_launch(IMAGE)


def test_unset_command_defaults_to_docker_when_available(monkeypatch, which):
    monkeypatch.delenv("GITHUB_MCP_COMMAND", raising=False)
    which({"docker": "/usr/bin/docker", "github-mcp-server": "/usr/bin/github-mcp-server"})

    assert resolve_mcp_launch(IMAGE)[0] == "/usr/bin/docker"


def test_unset_command_falls_back_to_binary_on_path_without_docker(monkeypatch, which):
    monkeypatch.delenv("GITHUB_MCP_COMMAND", raising=False)
    which({"github-mcp-server": BINARY})

    command, args = resolve_mcp_launch(IMAGE)

    assert command == BINARY
    assert args[0] == "stdio"


def test_server_parameters_pass_token_by_environment_only(monkeypatch, which, settings):
    monkeypatch.setenv("GITHUB_MCP_COMMAND", BINARY)
    which({BINARY: BINARY})

    server = GitHubMCPClient(settings).server_parameters()

    assert server.env["GITHUB_PERSONAL_ACCESS_TOKEN"] == settings.github_token
    assert server.env["GITHUB_TOOLSETS"] == MCP_TOOLSETS
    assert settings.github_token not in " ".join(server.args)
