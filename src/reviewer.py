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
 """Run one structured AI request covering all review categories."""
 model = build_model(settings)
 structured_model = model.with_structured_output(ReviewResult)

 category_instructions = "\n\n".join(
 build_prompt(category, "").strip()
 for category in CATEGORIES
 )

 combined_prompt = f"""
{category_instructions}

Return one ReviewResult object with a root "findings" array.
Each finding must contain:
category, severity, file, line, title, description,
recommendation, and confidence.

Rules:
- severity must be critical, high, medium, low, or info.
- confidence must be a number from 0 to 1.
- Return structured data, not Markdown or code fences.
- Use actual changed file paths and relevant line numbers.
- If no issues are found, return an empty findings array.

Pull Request context:
{context}
"""

 try:
    result = await structured_model.ainvoke(combined_prompt)
 except Exception as exc:
    print(f"AI structured response failed: {exc!r}")
    raise

 return result.findings