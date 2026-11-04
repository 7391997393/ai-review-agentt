"""Runs the real LangGraph graph; only the LLM client is replaced."""

from src import reviewer
from src.graph import build_graph


class FakeModel:
    def __init__(self):
        self.prompts = []

    async def ainvoke(self, prompt):
        self.prompts.append(prompt)
        content = (
            '{"findings": [{"category": "performance", "severity": "low", "file": "a.py", '
            '"line": 2, "title": "Loop", "description": "d", "recommendation": "r", '
            '"confidence": 0.7}]}'
        )
        return type("Response", (), {"content": content, "response_metadata": {}})()


async def test_graph_runs_review_node_and_returns_validated_findings(monkeypatch, settings):
    model = FakeModel()
    monkeypatch.setattr(reviewer, "build_model", lambda s: model)

    result = await build_graph(settings).ainvoke({"context": "PR-CONTEXT-123"})

    assert [(f.category, f.file, f.line) for f in result["findings"]] == [
        ("performance", "a.py", 2)
    ]
    assert result["context"] == "PR-CONTEXT-123"
    assert "PR-CONTEXT-123" in model.prompts[0]
