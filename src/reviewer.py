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
    "max_tokens": 4096,
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

Return only valid JSON matching the ReviewResult schema.
 
Every finding MUST contain these fields:
category, severity, file, line, title, description, recommendation, confidence.
 
Do not omit any field.
If a field is not applicable, provide a short value instead of omitting it.
 
Do not use Markdown.
Do not wrap the JSON in ```json or ``` code fences.

Pull Request context:
{context}
"""

    result = await structured_model.ainvoke(combined_prompt)
    return result.findings
