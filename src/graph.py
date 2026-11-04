from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from src.config import Settings
from src.reviewer import review_all_categories
from src.schemas import Finding


class ReviewState(TypedDict, total=False):
    context: str
    findings: list[Finding]


def build_graph(settings: Settings):
    """Build the LangGraph review workflow: START -> review -> END.

    A single node reviews all four categories (security, standards, tests,
    performance) with one model call. This keeps LLM cost and latency low; the
    graph is the extension point for adding more stages later (for example
    separate category nodes or a static-analysis node).
    """

    async def review_node(state: ReviewState) -> ReviewState:
        findings = await review_all_categories(settings=settings, context=state["context"])
        return {"findings": findings}

    builder = StateGraph(ReviewState)
    builder.add_node("review", review_node)
    builder.add_edge(START, "review")
    builder.add_edge("review", END)
    return builder.compile()
