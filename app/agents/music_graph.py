from __future__ import annotations

from typing import Any, Literal, TypedDict

from app.integrations.ai_extractor import (
    SourceItemClassification,
    classify_source_item,
    extract_music_event,
    openai_configured,
)


GraphItemType = Literal["notice", "release", "live_event", "ticket", "merch", "irrelevant"]


class MusicItemState(TypedDict, total=False):
    """State passed through the per-post classification/extraction workflow."""

    source: dict[str, Any]
    post: dict[str, Any]
    page_context: str | None
    raw_text: str

    item_type: GraphItemType
    classification_confidence: float
    classification_reason: str | None
    event_extraction: dict[str, Any] | None
    error: str


async def classify_item_node(state: MusicItemState) -> MusicItemState:
    """Classify one collected post into the routing item types."""
    
    source = state["source"]
    post = state["post"]
    classification = await classify_source_item(
        artist_name=source["artist_name"],
        raw_text=post["text"],
        page_context=state.get("page_context"),
    )
    return _classification_to_state(classification)


async def extract_event_node(state: MusicItemState) -> MusicItemState:
    """Extract calendar-ready event fields for live and ticket posts."""
    if state.get("item_type") not in {"live_event", "ticket"} or not openai_configured():
        return {"event_extraction": None}

    source = state["source"]
    post = state["post"]
    extracted = await extract_music_event(
        source["artist_name"],
        post["text"],
        state.get("page_context"),
    )
    return {"event_extraction": extracted}


def route_after_classification(state: MusicItemState) -> str:
    """Choose the next node after classification."""
    if state.get("item_type") in {"live_event", "ticket"}:
        return "extract_event"
    return "end"


async def run_music_item_graph(
    *,
    source: dict[str, Any],
    post: dict[str, Any],
    page_context: str | None,
    raw_text: str,
) -> MusicItemState:
    """Run the per-post workflow.

    If LangGraph is installed, the actual graph is used. In local/dev
    environments without the dependency, the same node functions run in the
    equivalent sequential order so the bot still works.
    """
    initial_state: MusicItemState = {
        "source": source,
        "post": post,
        "page_context": page_context,
        "raw_text": raw_text,
    }

    graph = _build_langgraph_or_none()
    if graph is not None:
        return await graph.ainvoke(initial_state)

    state: MusicItemState = {**initial_state, **await classify_item_node(initial_state)}
    if route_after_classification(state) == "extract_event":
        state.update(await extract_event_node(state))
    return state


def _classification_to_state(classification: SourceItemClassification) -> MusicItemState:
    """Convert the Pydantic classifier result into graph state updates."""
    return {
        "item_type": classification.item_type,
        "classification_confidence": classification.confidence,
        "classification_reason": classification.reason_ko,
    }


def _build_langgraph_or_none():
    """Build the LangGraph workflow when the optional dependency is available."""
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError:
        return None

    builder = StateGraph(MusicItemState)
    builder.add_node("classify_item", classify_item_node)
    builder.add_node("extract_event", extract_event_node)
    builder.add_edge(START, "classify_item")
    builder.add_conditional_edges(
        "classify_item",
        route_after_classification,
        {
            "extract_event": "extract_event",
            "end": END,
        },
    )
    builder.add_edge("extract_event", END)
    return builder.compile()
