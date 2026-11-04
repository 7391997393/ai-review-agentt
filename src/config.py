import os
from dataclasses import dataclass

DEFAULT_CG_BASE_URL = "https://openai.generative.engine.capgemini.com/v1"
# Pinned, tested GitHub MCP Server release. Override with GITHUB_MCP_IMAGE.
DEFAULT_MCP_IMAGE = "ghcr.io/github/github-mcp-server:v2.0.3"


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer, got {raw!r}") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be a positive integer, got {value}")
    return value


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Application configuration loaded from environment variables."""

    openai_api_key: str
    openai_model: str
    openai_base_url: str | None
    github_token: str
    github_owner: str
    github_repo: str
    max_review_context_chars: int
    max_output_tokens: int = 8192
    reopen_resolved_threads: bool = False
    mcp_image: str = DEFAULT_MCP_IMAGE

    @classmethod
    def from_env(cls) -> "Settings":
        """Load configuration for the Capgemini Generative Engine.

        The engine is used through its OpenAI-compatible API.
        """
        github_token = (
            os.getenv("GITHUB_TOKEN") or os.getenv("GH_PAT") or os.getenv("GITHUB_PAT") or ""
        ).strip()

        required = {
            "CG_API_KEY": (os.getenv("CG_API_KEY") or "").strip(),
            "CG_MODEL": (os.getenv("CG_MODEL") or "").strip(),
            "GITHUB_TOKEN": github_token,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise RuntimeError(f"Missing environment variables: {', '.join(missing)}")

        return cls(
            openai_api_key=required["CG_API_KEY"],
            openai_model=required["CG_MODEL"],
            openai_base_url=os.getenv("CG_BASE_URL") or DEFAULT_CG_BASE_URL,
            github_token=github_token,
            github_owner=os.getenv("GITHUB_OWNER", "").strip(),
            github_repo=os.getenv("GITHUB_REPO", "").strip(),
            max_review_context_chars=_int_env("MAX_REVIEW_CONTEXT_CHARS", 120000),
            max_output_tokens=_int_env("CG_MAX_OUTPUT_TOKENS", 8192),
            reopen_resolved_threads=_bool_env("REOPEN_RESOLVED_THREADS", False),
            mcp_image=os.getenv("GITHUB_MCP_IMAGE", "").strip() or DEFAULT_MCP_IMAGE,
        )
