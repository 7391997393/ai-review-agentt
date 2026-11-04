"""LLM review call, JSON extraction and normalisation of model output."""

from __future__ import annotations

import json
import logging
import math
import re
from typing import Any

from langchain_openai import ChatOpenAI

from src.config import Settings
from src.diff_utils import normalize_path
from src.prompts import (
    CATEGORIES,
    MAX_FINDINGS,
    SEVERITIES,
    build_repair_prompt,
    build_review_prompt,
)
from src.schemas import Finding, ReviewResult

logger = logging.getLogger(__name__)

MAX_TITLE_CHARS = 200
MAX_TEXT_CHARS = 4000
DEFAULT_TITLE = "Code review finding"
DEFAULT_DESCRIPTION = "Potential issue identified in the changed code."
DEFAULT_RECOMMENDATION = "Review and correct the identified issue."


class ReviewError(RuntimeError):
    """The LLM review could not produce a trustworthy result."""


def build_model(settings: Settings) -> ChatOpenAI:
    kwargs: dict[str, Any] = {
        "model": settings.openai_model,
        "temperature": 0,
        "api_key": settings.openai_api_key,
        "max_tokens": settings.max_output_tokens,
    }
    if settings.openai_base_url:
        kwargs["base_url"] = settings.openai_base_url
    return ChatOpenAI(**kwargs)


def response_text(response: Any) -> str:
    """Flatten a LangChain message's content (str or list of parts) to text."""
    content = getattr(response, "content", response)
    if isinstance(content, list):
        return "".join(
            str(part.get("text", "")) if isinstance(part, dict) else str(part) for part in content
        )
    return str(content or "")


def was_truncated(response: Any) -> bool:
    metadata = getattr(response, "response_metadata", None) or {}
    return metadata.get("finish_reason") == "length"


def extract_json(text: str) -> str:
    """Extract the outermost JSON object from a model response.

    Handles plain JSON, ```json fences and text before/after the object.
    """
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("AI response did not contain a JSON object.")
    return text[start : end + 1]


def _parse(text: str) -> Any:
    return json.loads(extract_json(text))


def _clip(value: Any, default: str, limit: int) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        return default
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _line(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        value = value.strip()
        return int(value) if value.isdigit() and int(value) >= 1 else None
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            return None
        value = int(value)
    if isinstance(value, int) and value >= 1:
        return value
    return None


def _confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.5
    if not math.isfinite(number):
        return 0.5
    return max(0.0, min(1.0, number))


def normalize_finding(finding: Any) -> dict[str, Any]:
    """Coerce one untrusted model finding into the `Finding` schema."""
    if not isinstance(finding, dict):
        return {
            "category": "standards",
            "severity": "medium",
            "file": "",
            "line": None,
            "title": DEFAULT_TITLE,
            "description": _clip(finding, DEFAULT_DESCRIPTION, MAX_TEXT_CHARS),
            "recommendation": DEFAULT_RECOMMENDATION,
            "confidence": 0.5,
        }

    category = str(finding.get("category", "standards")).strip().lower()
    severity = str(finding.get("severity", "medium")).strip().lower()
    return {
        "category": category if category in CATEGORIES else "standards",
        "severity": severity if severity in SEVERITIES else "medium",
        "file": normalize_path(str(finding.get("file") or "")),
        "line": _line(finding.get("line")),
        "title": _clip(finding.get("title"), DEFAULT_TITLE, MAX_TITLE_CHARS),
        "description": _clip(finding.get("description"), DEFAULT_DESCRIPTION, MAX_TEXT_CHARS),
        "recommendation": _clip(
            finding.get("recommendation"), DEFAULT_RECOMMENDATION, MAX_TEXT_CHARS
        ),
        "confidence": _confidence(finding.get("confidence", 0.5)),
    }


def findings_from_data(data: Any) -> list[Finding]:
    """Validate the parsed JSON object and return Pydantic findings."""
    if not isinstance(data, dict):
        raise ReviewError("AI response must be a JSON object.")
    raw = data.get("findings")
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        raise ReviewError("AI response 'findings' must be a list.")
    if len(raw) > MAX_FINDINGS:
        logger.warning("Model returned %d findings; keeping the first %d", len(raw), MAX_FINDINGS)
        raw = raw[:MAX_FINDINGS]
    return ReviewResult.model_validate({"findings": [normalize_finding(f) for f in raw]}).findings


async def review_all_categories(settings: Settings, context: str) -> list[Finding]:
    """Review the PR context for all four categories in one model call.

    One repair attempt is made when the answer is not valid JSON. If that also
    fails, ReviewError is raised so no incomplete review is posted.
    """
    model = build_model(settings)
    response = await model.ainvoke(build_review_prompt(context))
    content = response_text(response)
    truncated = was_truncated(response)
    if truncated:
        logger.warning(
            "Model output hit the max_tokens limit (%d); attempting repair",
            settings.max_output_tokens if settings else -1,
        )

    try:
        data = _parse(content)
    except (ValueError, json.JSONDecodeError) as first_error:
        logger.warning("AI response was not valid JSON (%s); trying one repair", first_error)
        repair = await model.ainvoke(build_repair_prompt(content, truncated=truncated))
        try:
            data = _parse(response_text(repair))
        except (ValueError, json.JSONDecodeError) as exc:
            raise ReviewError(
                "AI returned an invalid response. The response could not be repaired safely, "
                "so the review was stopped instead of posting incomplete findings."
            ) from exc

    findings = findings_from_data(data)
    logger.info("Model reported %d finding(s)", len(findings))
    return findings


__all__ = [
    "ReviewError",
    "build_model",
    "extract_json",
    "findings_from_data",
    "normalize_finding",
    "response_text",
    "review_all_categories",
]
