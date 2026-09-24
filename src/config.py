from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    """Application configuration loaded from environment variables."""

    openai_api_key: str
    openai_model: str
    openai_base_url: str | None
    github_token: str
    github_owner: str
    github_repo: str

    @classmethod
    def from_env(cls) -> "Settings":
        """
        Load configuration for Capgemini Generative Engine
        using its OpenAI-compatible API.
        """

        required = {
            "CG_API_KEY": os.getenv("CG_API_KEY"),
            "CG_MODEL": os.getenv("CG_MODEL"),
            "GITHUB_TOKEN": os.getenv("GITHUB_TOKEN"),
        }

        missing = [name for name, value in required.items() if not value]

        if missing:
            raise RuntimeError(
                f"Missing environment variables: {', '.join(missing)}"
            )

        return cls(
            openai_api_key=required["CG_API_KEY"],
            openai_model=required["CG_MODEL"],
            openai_base_url=os.getenv(
                "CG_BASE_URL",
                "https://openai.generative.engine.capgemini.com/v1",
            ),
            github_token=required["GITHUB_TOKEN"],
            github_owner=os.getenv("GITHUB_OWNER", ""),
            github_repo=os.getenv("GITHUB_REPO", ""),
        )