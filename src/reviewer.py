from langchain_openai import ChatOpenAI

from src.config import Settings
from src.prompts import build_prompt
from src.schemas import ReviewResult


CATEGORIES = ["security", "standards", "tests", "performance"]


def build_model(settings: Settings) -> ChatOpenAI:
    kwargs = {
        "model": settings.openai_model,
        "temperature": 0,
        "api_key": settings.openai_api_key,
    }

    if settings.openai_base_url:
        kwargs["base_url"] = settings.openai_base_url

    return ChatOpenAI(**kwargs)


async def review_all_categories(
    settings: Settings,
    context: str,
) -> list:
    """Run one structured Gemini request covering all review categories."""
    model = build_model(settings)
    structured_model = model.with_structured_output(ReviewResult)

    category_instructions = "\n\n".join(
        build_prompt(category, "").strip() for category in CATEGORIES
    )

    combined_prompt = f"""
{category_instructions}

Return only the structured ReviewResult requested by the application.

Pull Request context:
{context}
"""

    result = await structured_model.ainvoke(combined_prompt)
    return result.findings
