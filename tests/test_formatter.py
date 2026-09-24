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
