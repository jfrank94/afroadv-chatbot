"""Tool definitions and executor for the complex query agent.

Wraps the existing Retriever, EventStore, and web searcher as callable tools
with Anthropic tool schemas. The executor is created via a factory so the
agent shares the same Retriever/EventStore instances as the RAG path.
"""

import json
import logging
from typing import Callable

logger = logging.getLogger(__name__)

# ── Anthropic tool schemas ────────────────────────────────────────────────────

TOOL_SCHEMAS = [
    {
        "name": "search_platforms",
        "description": (
            "Search the PoC platforms database for communities matching a query. "
            "Use for finding tech or outdoor/travel platforms serving People of Color. "
            "Call this first for any platform discovery question."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query, e.g. 'Black women in tech' or 'Latinx hiking groups'",
                },
                "type_filter": {
                    "type": "string",
                    "enum": ["Tech", "Outdoor/Travel"],
                    "description": "Restrict to one platform type. Omit to search both.",
                },
                "n_results": {
                    "type": "integer",
                    "description": "Number of results (default 5, max 10)",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_events",
        "description": (
            "Search upcoming events from PoC platforms. "
            "Use when the query asks about events, conferences, meetups, or things happening."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Event search query",
                },
                "location": {
                    "type": "string",
                    "description": "City or state to prioritize, e.g. 'New York NY'",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "web_search",
        "description": (
            "Search the web for current information about a specific platform. "
            "Use only when the database results are sparse or you need very recent data."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "platform_name": {
                    "type": "string",
                    "description": "Exact name of the platform to search for",
                },
                "platform_type": {
                    "type": "string",
                    "enum": ["Tech", "Outdoor/Travel"],
                },
            },
            "required": ["platform_name", "platform_type"],
        },
    },
]


# ── Tool executor factory ─────────────────────────────────────────────────────

def make_tool_executor(retriever, event_store) -> dict[str, Callable]:
    """Create a tool dispatch dict bound to the caller's retriever and event_store.

    Returns a dict mapping tool name → callable(inputs: dict) → str.
    Each callable returns a JSON string so it can be passed directly as a
    tool_result content block to the Anthropic API.
    """

    def _search_platforms(inputs: dict) -> str:
        query = inputs["query"]
        type_filter = inputs.get("type_filter")
        n_results = min(int(inputs.get("n_results", 5)), 10)
        try:
            results = retriever.retrieve(
                query=query,
                n_results=n_results,
                type_filter=type_filter,
            )
            if not results:
                return json.dumps({"platforms": [], "message": "No platforms found."})
            platforms = [
                {
                    "name": p["name"],
                    "type": p["type"],
                    "focus_area": p["focus_area"],
                    "description": p["description"],
                    "website": p["website"],
                    "community_size": p.get("community_size", ""),
                    "states": p.get("states", ""),
                }
                for p in results
            ]
            return json.dumps({"platforms": platforms})
        except Exception as e:
            logger.error(f"search_platforms tool failed: {e}")
            return json.dumps({"error": str(e), "platforms": []})

    def _search_events(inputs: dict) -> str:
        from src.core.chatbot import _expand_location_query
        query = inputs["query"]
        location = inputs.get("location", "")
        expanded_query, location_hint = _expand_location_query(
            f"{query} {location}".strip()
        )
        try:
            results = event_store.search_events(
                query=expanded_query,
                n_results=5,
                location_hint=location_hint,
            )
            if not results:
                return json.dumps({"events": [], "message": "No upcoming events found."})
            events = [
                {
                    "title": e["title"],
                    "org_name": e.get("org_name", ""),
                    "date": e.get("date", "TBD"),
                    "location": e.get("location", "TBD"),
                    "url": e.get("url", ""),
                }
                for e in results
            ]
            return json.dumps({"events": events})
        except Exception as e:
            logger.error(f"search_events tool failed: {e}")
            return json.dumps({"error": str(e), "events": []})

    def _web_search(inputs: dict) -> str:
        from src.agents.tools.web_searcher import search_platform_info
        try:
            results = search_platform_info(
                platform_name=inputs["platform_name"],
                platform_type=inputs["platform_type"],
            )
            if not results:
                return json.dumps({"results": [], "message": "No web results found."})
            snippets = [
                {"title": r.get("title", ""), "content": r.get("content", "")[:400]}
                for r in results[:3]
            ]
            return json.dumps({"results": snippets})
        except Exception as e:
            logger.error(f"web_search tool failed: {e}")
            return json.dumps({"error": str(e), "results": []})

    return {
        "search_platforms": _search_platforms,
        "search_events": _search_events,
        "web_search": _web_search,
    }
