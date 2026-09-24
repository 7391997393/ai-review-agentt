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
 
Return the result as ONE ReviewResult object.
 
The response MUST have this exact structure:
 
{{
    "findings": [
        {{
            "category": "security",
            "severity": "high",
            "file": "example.py",
            "line": 10,
            "title": "Short issue title",
            "description": "Explain the issue.",
            "recommendation": "Explain how to fix it.",
            "confidence": 0.90
        }}
    ]
}}
 
IMPORTANT:
- The root response MUST be an object containing "findings".
- Do NOT return a list directly.
- "severity" must be one of: critical, high, medium, low, info.
- "confidence" must be a number from 0 to 1.
- Every finding must contain category, severity, file, line, title,
  description, recommendation, and confidence.
- Do not use Markdown or code fences.
 
Pull Request context:
{context}
"""
 

    result = await structured_model.ainvoke(combined_prompt)
    return result.findings
