import json
import re
 
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
        "max_tokens": 1500,
    }
 
    if settings.openai_base_url:
        kwargs["base_url"] = settings.openai_base_url
 
    return ChatOpenAI(**kwargs)
 
 
def extract_json(text: str) -> str:
    """Extract JSON from raw output or Markdown fenced JSON."""
    text = text.strip()
 
    fenced = re.search(
        r"```(?:json)?\s*(\{.*?\})\s*```",
        text,
        re.DOTALL,
    )
 
    if fenced:
        return fenced.group(1)
 
    start = text.find("{")
    end = text.rfind("}")
 
    if start != -1 and end != -1 and end > start:
        return text[start:end + 1]
 
    return text
 
 
async def review_all_categories(
    settings: Settings,
    context: str,
) -> list:
    model = build_model(settings)
 
    category_instructions = "\n\n".join(
        build_prompt(category, "").strip()
        for category in CATEGORIES
    )
 
    combined_prompt = f"""
{category_instructions}
 
Return ONLY valid JSON.
Do not use Markdown.
Do not wrap the JSON in ```json```.
 
The JSON must follow this structure:
 
{{
  "findings": []
}}
 
Pull Request context:
{context}
"""
 
    response = await model.ainvoke(combined_prompt)
 
    content = response.content
 
    if isinstance(content, list):
        content = "".join(
            item.get("text", "") if isinstance(item, dict) else str(item)
            for item in content
        )
 
    json_text = extract_json(str(content))
 
    data = json.loads(json_text)
    result = ReviewResult.model_validate(data)
 
    return result.findings
 