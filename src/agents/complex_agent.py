"""Complex query agent using LangGraph + Anthropic native tool use.

Handles multi-step queries that the single-pass RAG path can't answer well:
- Comparative ("compare X and Y")
- Superlative ("most active community in DC")
- Multi-step ("find outdoor communities in NYC with upcoming events")

Graph structure (ReAct loop):
    START → call_model → [tool_use?] → execute_tools → call_model → ... → END

The agent shares the Retriever and EventStore instances from RAGChatbot so no
duplicate Qdrant connections are opened.
"""

import json
import logging
from typing import TypedDict, Annotated, Any

from langgraph.graph import StateGraph, END, START
import config
from src.agents.agent_tools import TOOL_SCHEMAS, make_tool_executor

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 5  # Safety cap on tool-call loops


# ── State ─────────────────────────────────────────────────────────────────────

def _append(existing: list, new: list) -> list:
    """Simple list-append reducer for LangGraph state fields."""
    return existing + new


class AgentState(TypedDict):
    query: str
    messages: Annotated[list, _append]   # Anthropic message dicts (plain, serialisable)
    platforms: Annotated[list, _append]  # Accumulated platform results from tool calls
    events: Annotated[list, _append]     # Accumulated event results from tool calls
    iteration_count: int


# ── Node helpers ──────────────────────────────────────────────────────────────

def _content_to_dicts(content: Any) -> list[dict]:
    """Convert Anthropic SDK content blocks to plain dicts for state storage."""
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    result = []
    for block in content:
        if hasattr(block, "type"):
            if block.type == "text":
                result.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                result.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
        elif isinstance(block, dict):
            result.append(block)
    return result


# ── Graph nodes ───────────────────────────────────────────────────────────────

def _make_call_model(anthropic_client):
    """Return a call_model node bound to the provided Anthropic client."""

    def call_model(state: AgentState) -> dict:
        response = anthropic_client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=config.CHAT_MAX_TOKENS,
            tools=TOOL_SCHEMAS,
            tool_choice={"type": "auto"},
            messages=state["messages"],
        )
        assistant_msg = {
            "role": "assistant",
            "content": _content_to_dicts(response.content),
            "stop_reason": response.stop_reason,
        }
        return {
            "messages": [assistant_msg],
            "iteration_count": state["iteration_count"] + 1,
        }

    return call_model


def _make_execute_tools(tool_executor: dict):
    """Return an execute_tools node bound to the provided tool executor."""

    def execute_tools(state: AgentState) -> dict:
        last_msg = state["messages"][-1]
        tool_use_blocks = [
            b for b in last_msg.get("content", [])
            if isinstance(b, dict) and b.get("type") == "tool_use"
        ]

        tool_result_blocks = []
        new_platforms: list = []
        new_events: list = []

        for block in tool_use_blocks:
            tool_name = block["name"]
            tool_input = block["input"]
            tool_fn = tool_executor.get(tool_name)

            if tool_fn is None:
                result_str = json.dumps({"error": f"Unknown tool: {tool_name}"})
            else:
                result_str = tool_fn(tool_input)

            tool_result_blocks.append({
                "type": "tool_result",
                "tool_use_id": block["id"],
                "content": result_str,
            })

            # Accumulate results for the final response dict
            try:
                parsed = json.loads(result_str)
                if "platforms" in parsed:
                    new_platforms.extend(parsed["platforms"])
                if "events" in parsed:
                    new_events.extend(parsed["events"])
            except json.JSONDecodeError:
                pass

        user_msg = {"role": "user", "content": tool_result_blocks}
        return {
            "messages": [user_msg],
            "platforms": new_platforms,
            "events": new_events,
        }

    return execute_tools


def _should_continue(state: AgentState) -> str:
    """Route to tool execution or end based on last model response."""
    last_msg = state["messages"][-1]
    if (
        last_msg.get("stop_reason") == "tool_use"
        and state["iteration_count"] < MAX_ITERATIONS
    ):
        return "execute_tools"
    return "end"


# ── Agent class ───────────────────────────────────────────────────────────────

class ComplexQueryAgent:
    """LangGraph agent for multi-step platform discovery queries."""

    def __init__(self, retriever, event_store, anthropic_client) -> None:
        tool_executor = make_tool_executor(retriever, event_store)
        self._graph = self._build_graph(anthropic_client, tool_executor)

    def _build_graph(self, anthropic_client, tool_executor) -> Any:
        call_model = _make_call_model(anthropic_client)
        execute_tools = _make_execute_tools(tool_executor)

        graph = StateGraph(AgentState)
        graph.add_node("call_model", call_model)
        graph.add_node("execute_tools", execute_tools)

        graph.add_edge(START, "call_model")
        graph.add_conditional_edges(
            "call_model",
            _should_continue,
            {"execute_tools": "execute_tools", "end": END},
        )
        graph.add_edge("execute_tools", "call_model")

        return graph.compile()

    def run(self, query: str, conversation_history: list) -> dict:
        """Run the agent on a complex query.

        Args:
            query: User's query string
            conversation_history: Prior turns from ConversationMemory.format_for_llm()

        Returns:
            Standard response dict: {response, sources, events, retrieved, events_found, query}
        """
        system_prompt = (
            "You are a warm, knowledgeable guide helping people discover platforms and "
            "communities built by and for People of Color in tech and outdoor/travel spaces. "
            "Use the available tools to find relevant information, then synthesize a clear, "
            "conversational answer. Be specific — name platforms, cite locations, mention events. "
            "Format links as markdown: [Link Text](url). "
            "Only recommend platforms and events you found through the tools."
        )

        # Build initial messages: conversation history + current query
        messages = list(conversation_history)
        messages.append({"role": "user", "content": f"[System: {system_prompt}]\n\n{query}"})

        initial_state: AgentState = {
            "query": query,
            "messages": messages,
            "platforms": [],
            "events": [],
            "iteration_count": 0,
        }

        try:
            final_state = self._graph.invoke(
                initial_state,
                config={"recursion_limit": MAX_ITERATIONS * 2 + 2},
            )
        except Exception as e:
            logger.error(f"ComplexQueryAgent graph failed: {e}")
            raise

        # Extract the final text response
        response_text = ""
        for msg in reversed(final_state["messages"]):
            if msg.get("role") == "assistant":
                for block in msg.get("content", []):
                    if isinstance(block, dict) and block.get("type") == "text":
                        response_text = block["text"]
                        break
                if response_text:
                    break

        platforms = final_state.get("platforms", [])
        events = final_state.get("events", [])

        return {
            "response": response_text or "I wasn't able to find a good answer. Try rephrasing your question.",
            "sources": platforms,
            "events": events,
            "retrieved": len(platforms),
            "events_found": len(events),
            "query": query,
        }
