import pytest

from src.config import DEFAULT_CG_BASE_URL, DEFAULT_MCP_IMAGE, Settings

ENV = ("CG_API_KEY", "CG_MODEL", "CG_BASE_URL", "GITHUB_TOKEN", "GH_PAT", "GITHUB_PAT",
       "MAX_REVIEW_CONTEXT_CHARS", "CG_MAX_OUTPUT_TOKENS", "REOPEN_RESOLVED_THREADS",
       "GITHUB_MCP_IMAGE", "GITHUB_OWNER", "GITHUB_REPO")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ENV:
        monkeypatch.delenv(name, raising=False)


def set_required(monkeypatch):
    monkeypatch.setenv("CG_API_KEY", "k")
    monkeypatch.setenv("CG_MODEL", "m")
    monkeypatch.setenv("GITHUB_TOKEN", "t")


def test_missing_required_variables_are_reported(monkeypatch):
    with pytest.raises(RuntimeError, match="CG_API_KEY, CG_MODEL, GITHUB_TOKEN"):
        Settings.from_env()


def test_defaults(monkeypatch):
    set_required(monkeypatch)
    monkeypatch.setenv("CG_BASE_URL", "")  # empty workflow input -> default URL

    settings = Settings.from_env()

    assert settings.openai_base_url == DEFAULT_CG_BASE_URL
    assert settings.max_review_context_chars == 120000
    assert settings.max_output_tokens == 8192
    assert settings.reopen_resolved_threads is False
    assert settings.mcp_image == DEFAULT_MCP_IMAGE
    assert ":" in DEFAULT_MCP_IMAGE and not DEFAULT_MCP_IMAGE.endswith(":latest")


def test_token_fallback_and_overrides(monkeypatch):
    set_required(monkeypatch)
    monkeypatch.delenv("GITHUB_TOKEN")
    monkeypatch.setenv("GH_PAT", " pat \n")
    monkeypatch.setenv("CG_MAX_OUTPUT_TOKENS", "4000")
    monkeypatch.setenv("REOPEN_RESOLVED_THREADS", "Yes")

    settings = Settings.from_env()

    assert settings.github_token == "pat"
    assert settings.max_output_tokens == 4000
    assert settings.reopen_resolved_threads is True


@pytest.mark.parametrize("value", ["abc", "0", "-5"])
def test_invalid_integers_are_rejected_clearly(monkeypatch, value):
    set_required(monkeypatch)
    monkeypatch.setenv("MAX_REVIEW_CONTEXT_CHARS", value)
    with pytest.raises(RuntimeError, match="MAX_REVIEW_CONTEXT_CHARS"):
        Settings.from_env()
