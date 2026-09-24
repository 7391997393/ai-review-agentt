from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from src.config import Settings
from src.reviewer import review_all_categories
from src.schemas import Finding


class ReviewState(TypedDict, total=False):
    context: str
    findings: list[Finding]


def build_graph(settings: Settings):
    """Build a simple LangGraph with one AI review node.

    One model call reviews all four categories. This keeps the demo simple and
    reduces Gemini quota usage compared with four separate model calls.
    """
    async def review_node(state: ReviewState):
        findings = await review_all_categories(
            settings=settings,
            context=state["context"],
        )
        return {"findings": findings}

    builder = StateGraph(ReviewState)
    builder.add_node("review", review_node)
    builder.add_edge(START, "review")
    builder.add_edge("review", END)

    return builder.compile()
