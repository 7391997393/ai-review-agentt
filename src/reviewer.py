import json
import re
from typing import Any
 
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
        "max_tokens": 3000,
    }
 
    if settings.openai_base_url:
        kwargs["base_url"] = settings.openai_base_url
 
    return ChatOpenAI(**kwargs)
 
 
def extract_json(text: str) -> str:
    """
    Extract a JSON object from the model response.
 
    Handles:
    - plain JSON
    - ```json ... ```
    - responses containing text before/after the JSON
    """
 
    text = text.strip()
 
    text = re.sub(
        r"^```(?:json)?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
 
    text = re.sub(
        r"\s*```$",
        "",
        text,
    )
 
    start = text.find("{")
    end = text.rfind("}")
 
    if start == -1 or end == -1 or end <= start:
        raise ValueError(
            "AI response did not contain a valid JSON object."
        )
 
    return text[start : end + 1]
 
 
def normalize_finding(finding: Any) -> dict:
    if not isinstance(finding, dict):
        return {
            "category": "standards",
            "severity": "medium",
            "file": "",
            "line": None,
            "title": "Code review finding",
            "description": str(finding),
            "recommendation": "Review and correct the identified issue.",
            "confidence": 0.5,
        }
 
    category = finding.get("category", "standards")
 
    if category not in CATEGORIES:
        category = "standards"
 
    severity = finding.get("severity", "medium")
 
    if severity not in {
        "critical",
        "high",
        "medium",
        "low",
        "info",
    }:
        severity = "medium"
 
    line = finding.get("line")
 
    if isinstance(line, str):
        line = line.strip()
 
        if line.isdigit():
            line = int(line)
        else:
            line = None
 
    if isinstance(line, float):
        line = int(line)
 
    if isinstance(line, int) and line < 1:
        line = None
 
    confidence = finding.get("confidence", 0.5)
 
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0.5
 
    confidence = max(0.0, min(1.0, confidence))
 
    return {
        "category": category,
        "severity": severity,
        "file": str(finding.get("file", "")),
        "line": line,
        "title": str(
            finding.get(
                "title",
                "Code review finding",
            )
        ),
        "description": str(
            finding.get(
                "description",
                "Potential issue identified in the changed code.",
            )
        ),
        "recommendation": str(
            finding.get(
                "recommendation",
                "Review and correct the identified issue.",
            )
        ),
        "confidence": confidence,
    }
 
 
async def review_all_categories(
    settings: Settings,
    context: str,
) -> list:
 
    model = build_model(settings)
 
    category_instructions = "\n\n".join(
        build_prompt(category).strip()
        for category in CATEGORIES
    )
 
    combined_prompt = f"""
{category_instructions}
 
You are producing the final structured result for an automated
GitHub Pull Request code review.
 
Return ONLY a JSON object.
 
The JSON MUST have exactly this top-level structure:
 
{{
  "findings": [
    {{
      "category": "security",
      "severity": "medium",
      "file": "path/to/file",
      "line": 10,
      "title": "Short issue title",
      "description": "Explain the concrete problem.",
      "recommendation": "Explain the specific fix.",
      "confidence": 0.95
    }}
  ]
}}
 
Every finding MUST contain all of these fields:
category
severity
file
line
title
description
recommendation
confidence
 
Allowed category values:
security, standards, tests, performance
 
Allowed severity values:
critical, high, medium, low, info
 
confidence MUST be a number from 0 to 1.
 
line MUST be the changed source-code line number when the finding
can be associated with a changed line. Otherwise use null.
 
Only report concrete findings supported by the supplied Pull Request
context. Do not invent issues.
 
If there are no concrete findings, return:
{{ "findings": [] }}
 
Do NOT return Markdown.
Do NOT use ```json.
Do NOT add explanations before or after the JSON.
 
Pull Request context:
{context}
"""
 
    response = await model.ainvoke(combined_prompt)
 
    content = response.content
 
    if isinstance(content, list):
        parts = []
 
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text", "")))
            else:
                parts.append(str(item))
 
        content = "".join(parts)
 
    try:
        json_text = extract_json(str(content))
        data = json.loads(json_text)
 
    except (ValueError, json.JSONDecodeError):
        repair_prompt = f"""
The following AI-generated response was supposed to be a JSON object
for a GitHub Pull Request code review, but it is malformed.
 
Repair it into valid JSON.
 
Return ONLY valid JSON.
Do not add Markdown.
Do not add explanations.
Do not remove valid findings.
 
The required structure is:
 
{{
  "findings": [
    {{
      "category": "security",
      "severity": "medium",
      "file": "path/to/file",
      "line": 10,
      "title": "Short issue title",
      "description": "Explain the concrete problem.",
      "recommendation": "Explain the specific fix.",
      "confidence": 0.95
    }}
  ]
}}
 
Allowed categories:
security, standards, tests, performance
 
Allowed severities:
critical, high, medium, low, info
 
The original malformed response is:
 
{content}
"""
 
        repair_response = await model.ainvoke(repair_prompt)
        repair_content = repair_response.content
 
        if isinstance(repair_content, list):
            parts = []
 
            for item in repair_content:
                if isinstance(item, dict):
                    parts.append(str(item.get("text", "")))
                else:
                    parts.append(str(item))
 
            repair_content = "".join(parts)
 
        try:
            json_text = extract_json(str(repair_content))
            data = json.loads(json_text)
        except (ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                "AI returned an invalid response. "
                "The response could not be repaired safely, "
                "so the review was stopped instead of posting incomplete findings."
            ) from exc
 
    if not isinstance(data, dict):
        raise RuntimeError(
            "AI response must be a JSON object."
        )
 
    raw_findings = data.get("findings", [])
 
    if raw_findings is None:
        raw_findings = []
 
    if not isinstance(raw_findings, list):
        raise RuntimeError(
            "AI response 'findings' must be a list."
        )
 
    normalized_findings = [
        normalize_finding(finding)
        for finding in raw_findings
    ]
 
    result = ReviewResult.model_validate(
        {
            "findings": normalized_findings
        }
    )
 
    return result.findings
 
 