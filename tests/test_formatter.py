import asyncio
 
import pytest
 
from src.formatter import format_review
from src.schemas import Finding
 
 
def test_format_review_with_finding():
    finding = Finding(
        category="security",
        severity="high",
        file="app.py",
        line=10,
        title="Possible SQL injection",
        description="User input is concatenated into SQL.",
        recommendation="Use parameterized queries.",
        confidence=0.95,
    )
 
    output = format_review("demo", "repo", 1, [finding])
 
    assert "AI Code Review" in output
    assert "HIGH" in output
    assert "app.py:10" in output
    assert "parameterized queries" in output
 
 
def test_format_review_without_findings():
    output = format_review("demo", "repo", 1, [])
 
    assert "No actionable findings" in output
 
 
def test_invalid_ai_response_is_handled(monkeypatch):
    from src import reviewer
 
    class FakeResponse:
        content = "This is not valid JSON."
 
    class FakeModel:
        async def ainvoke(self, prompt):
            return FakeResponse()
 
    monkeypatch.setattr(
        reviewer,
        "build_model",
        lambda settings: FakeModel(),
    )
 
    with pytest.raises(
        RuntimeError,
        match="AI returned an invalid response",
    ):
        asyncio.run(
            reviewer.review_all_categories(
                settings=None,
                context="Test Pull Request context",
            )
        )