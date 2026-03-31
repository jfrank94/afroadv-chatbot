"""
Main chatbot logic integrating RAG pipeline.

Combines retrieval + generation with conversation memory.
Now includes event search capability and smart context handling!
"""

from typing import List, Dict, Optional
import logging
import threading
import config
from src.core.retriever import Retriever
from src.utils.url_utils import is_homepage_url
from src.infrastructure.llm import LLMProvider
from src.events.event_store import EventStore
from src.analytics import QueryLogger
from src.core.conversation import (
    ConversationMemory,
    QueryReformulator,
    IntentTracker,
    IntentType
)

logger = logging.getLogger(__name__)


# Common city nickname/abbreviation → full name(s) for event location matching
_CITY_ALIASES: dict[str, str] = {
    "nyc": "New York City New York NY",
    "new york city": "New York City New York NY",
    "la": "Los Angeles California CA",
    "los angeles": "Los Angeles California CA",
    "sf": "San Francisco California CA",
    "san francisco": "San Francisco California CA",
    "dc": "Washington DC District of Columbia",
    "washington dc": "Washington DC District of Columbia",
    "dmv": "Washington DC Maryland Virginia",
    "chi": "Chicago Illinois IL",
    "chicago": "Chicago Illinois IL",
    "atl": "Atlanta Georgia GA",
    "atlanta": "Atlanta Georgia GA",
    "miami": "Miami Florida FL",
    "seattle": "Seattle Washington WA",
    "denver": "Denver Colorado CO",
    "austin": "Austin Texas TX",
    "houston": "Houston Texas TX",
    "dallas": "Dallas Texas TX",
    "boston": "Boston Massachusetts MA",
    "philly": "Philadelphia Pennsylvania PA",
    "philadelphia": "Philadelphia Pennsylvania PA",
    "portland": "Portland Oregon OR",
}


def _expand_location_query(query: str) -> tuple[str, Optional[str]]:
    """Expand city nicknames in a query and extract a location hint for re-ranking.

    Returns:
        (expanded_query, location_hint) where location_hint is the expanded
        city string if a known city was found, else None.

    Example:
        'events in NYC' → ('events in NYC New York City New York NY', 'New York City New York NY')
    """
    query_lower = query.lower()
    expansions = []
    for alias, expansion in _CITY_ALIASES.items():
        if alias in query_lower:
            expansions.append(expansion)
    if expansions:
        combined = " ".join(expansions)
        return f"{query} {combined}", combined
    return query, None


# Event-related keywords for query detection
EVENT_KEYWORDS = [
    'event', 'conference', 'workshop', 'meetup', 'webinar',
    'happening', 'upcoming', 'schedule', 'calendar', 'when',
    'gathering', 'summit', 'bootcamp', 'hackathon', 'training'
]


class RAGChatbot:
    """RAG-powered chatbot for PoC platform discovery with event search."""

    def __init__(
        self,
        retriever: Optional[Retriever] = None,
        llm: Optional[LLMProvider] = None,
        n_results: int = 5,
        conversation_memory: int = 3,
        enable_events: bool = True,
        enable_analytics: bool = True
    ):
        """
        Initialize chatbot with retriever and LLM.

        Args:
            retriever: Retriever instance (creates new if None)
            llm: LLMProvider instance (creates new if None)
            n_results: Number of platforms to retrieve per query
            conversation_memory: Number of conversation turns to remember
            enable_events: Enable event search (default: True)
            enable_analytics: Enable query logging for analytics (default: True)
        """
        self.retriever = retriever or Retriever()
        self.llm = llm or LLMProvider()
        self.n_results = n_results
        self.conversation_memory = conversation_memory
        self.enable_events = enable_events

        # Initialize analytics logger
        self.analytics_logger = QueryLogger() if enable_analytics else None

        # Initialize event store if events are enabled
        if self.enable_events:
            try:
                # Share the Qdrant client but use separate "events" collection
                self.event_store = EventStore(
                    collection_name="events",
                    vector_db=self.retriever.vector_db  # Share the same client
                )
                logger.info("Event search enabled with shared client, separate collection")
            except Exception as e:
                logger.warning(f"Failed to initialize event store: {e}. Events disabled.")
                self.enable_events = False
                self.event_store = None
        else:
            self.event_store = None

        # Initialize conversation memory and context handling
        self.memory = ConversationMemory(max_turns=conversation_memory)
        self.query_reformulator = QueryReformulator(self.llm)
        self.intent_tracker = IntentTracker()

        # Legacy history for backward compatibility (deprecated)
        self.history: List[Dict[str, str]] = []
        self._history_lock = threading.Lock()

        # Initialize complex query agent (LangGraph ReAct) if Anthropic client is available
        self.query_classifier = None
        self.complex_agent = None
        if getattr(self.llm, 'anthropic_client', None):
            try:
                from src.agents.query_classifier import classify
                from src.agents.complex_agent import ComplexQueryAgent
                self.query_classifier = classify
                self.complex_agent = ComplexQueryAgent(
                    retriever=self.retriever,
                    event_store=self.event_store,
                    anthropic_client=self.llm.anthropic_client,
                )
                logger.info("Complex query agent enabled (LangGraph ReAct)")
            except Exception as e:
                logger.warning(f"Failed to initialize complex agent: {e}. All queries will use simple RAG.")

        logger.info(f"RAG Chatbot initialized (retrieve top-{n_results}, memory={conversation_memory} turns, events={'enabled' if self.enable_events else 'disabled'}, context_aware=True, agent={'enabled' if self.complex_agent else 'disabled'})")

    def chat(
        self,
        query: str,
        type_filter: Optional[str] = None,
        include_sources: bool = True
    ) -> Dict:
        """
        Process user query and generate response.

        Args:
            query: User's question
            type_filter: Optional filter ("Tech" or "Outdoor/Travel")
            include_sources: Include source platforms in response

        Returns:
            Dictionary with response, sources, events, and metadata
        """
        if not query.strip():
            result = {
                "response": "Please ask me a question about PoC platforms in tech or outdoor/travel!",
                "sources": [],
                "events": [],
                "retrieved": 0,
                "events_found": 0,
                "error": "empty_query",
                "query": query
            }
            # Log empty query error
            if self.analytics_logger:
                try:
                    self.analytics_logger.log_query(
                        query=query,
                        response=result["response"],
                        error="empty_query"
                    )
                except Exception as e:
                    logger.warning(f"Analytics logging failed: {e}")
            return result

        # Validate query length (prevent abuse and excessive token usage)
        if len(query) > config.MAX_QUERY_LENGTH:
            return {
                "response": f"Your question is too long ({len(query)} characters). Please keep it under {config.MAX_QUERY_LENGTH} characters.",
                "sources": [],
                "events": [],
                "retrieved": 0,
                "events_found": 0,
                "error": "query_too_long",
                "query": query[:100] + "..."  # Truncate for logging
            }

        # Route complex queries (comparative, superlative, multi-step) to LangGraph agent
        if self.query_classifier and self.complex_agent:
            if self.query_classifier(query) == "complex":
                return self._handle_complex_query(query)

        import time
        start_time = time.time()
        logger.info(f"Processing query: '{query}'")

        # Step 1: Reformulate query if context-dependent (e.g., "And Techqueria?")
        t1 = time.time()
        retrieval_query = self.query_reformulator.reformulate(query, self.memory)
        if retrieval_query != query:
            logger.info(f"Using reformulated query for retrieval: '{retrieval_query}'")
        logger.debug(f"⏱️  Query reformulation: {(time.time()-t1)*1000:.0f}ms")

        # Step 2: Update conversation state and detect intent
        t2 = time.time()
        self.memory.state = self.intent_tracker.update_state(retrieval_query, self.memory.state)
        logger.debug(f"⏱️  Intent tracking: {(time.time()-t2)*1000:.0f}ms")

        # Step 3 & 4: Run vector search and event search in parallel for speed
        t3 = time.time()

        # Use threading to run searches in parallel (I/O bound operations)
        from concurrent.futures import ThreadPoolExecutor, as_completed

        platforms = []
        events = []

        with ThreadPoolExecutor(max_workers=2) as executor:
            # Submit both searches simultaneously
            future_platforms = executor.submit(
                self.retriever.retrieve,
                query=retrieval_query,
                n_results=self.n_results,
                type_filter=type_filter
            )

            future_events = None
            if self.enable_events:
                event_query, location_hint = _expand_location_query(query)
                future_events = executor.submit(
                    self.event_store.search_events,
                    query=event_query,
                    n_results=config.EVENT_SEARCH_RESULTS,
                    location_hint=location_hint
                )

            # Wait for platforms first (required for response)
            platforms = future_platforms.result()

            # Get events if enabled
            if future_events:
                try:
                    events = future_events.result()
                except Exception as e:
                    logger.error(f"Error searching events: {e}")
                    events = []

        logger.info(f"⏱️  Parallel search: {(time.time()-t3)*1000:.0f}ms - {len(platforms)} platforms, {len(events)} events")

        # Step 4.5: If we found platforms but no/few events, do targeted event search by platform IDs
        if platforms and len(events) < 3 and self.enable_events:
            t4 = time.time()
            platform_events = []
            for platform in platforms[:2]:  # Check top 2 platforms
                try:
                    platform_id = platform.get('id')
                    if platform_id:
                        pf_events = self.event_store.get_platform_events(platform_id, limit=3)
                        platform_events.extend(pf_events)
                        if pf_events:
                            logger.info(f"Found {len(pf_events)} events for {platform['name']}")
                except Exception as e:
                    logger.error(f"Error getting events for platform {platform.get('name')}: {e}")

            # Merge with existing events (avoid duplicates)
            event_ids_seen = {(e.get('title'), e.get('date')) for e in events}
            for pe in platform_events:
                event_key = (pe.get('title'), pe.get('date'))
                if event_key not in event_ids_seen:
                    events.append(pe)
                    event_ids_seen.add(event_key)

            logger.info(f"⏱️  Targeted event search: {(time.time()-t4)*1000:.0f}ms - now {len(events)} total events")

        if not platforms:
            response_text = self._handle_no_results(query)

            # Add to conversation history even when no results
            with self._history_lock:
                self.history.append({"role": "user", "content": query})
                self.history.append({"role": "assistant", "content": response_text})
                if len(self.history) > self.conversation_memory * 2:
                    self.history = self.history[-(self.conversation_memory * 2):]

            return {
                "response": response_text,
                "sources": [],
                "events": [],
                "retrieved": 0,
                "events_found": 0,
                "query": query
            }

        # Step 5: Generate response with LLM (reduced max_tokens for speed)
        t5 = time.time()
        messages = self._create_prompt_with_events(query, platforms, events)
        response_text = self.llm.generate(messages, max_tokens=config.CHAT_MAX_TOKENS, temperature=config.TEMPERATURE)
        logger.info(f"⏱️  LLM generation: {(time.time()-t5)*1000:.0f}ms")
        logger.info(f"⏱️  TOTAL: {(time.time()-start_time)*1000:.0f}ms")

        if not response_text:
            # Fallback if LLM fails
            response_text = self._create_fallback_response(query, platforms, events)
            logger.warning("LLM failed, using fallback response")

        # Step 5: Add to conversation memory
        platform_names = [p['name'] for p in platforms]
        self.memory.add_turn(
            user_msg=query,
            assistant_msg=response_text,
            platforms_returned=platform_names
        )

        # Maintain legacy history for backward compatibility
        with self._history_lock:
            self.history.append({"role": "user", "content": query})
            self.history.append({"role": "assistant", "content": response_text})
            if len(self.history) > self.conversation_memory * 2:
                self.history = self.history[-(self.conversation_memory * 2):]

        # Step 6: Build response
        result = {
            "response": response_text,
            "sources": platforms if include_sources else [],
            "events": events if include_sources else [],
            "retrieved": len(platforms),
            "events_found": len(events),
            "query": query
        }

        # Log query for analytics (no PII)
        if self.analytics_logger:
            try:
                self.analytics_logger.log_query(
                    query=query,
                    response=response_text,
                    sources=platforms,
                    events=events
                )
            except Exception as e:
                logger.warning(f"Failed to log analytics: {e}")

        return result

    def _handle_complex_query(self, query: str) -> dict:
        """Run the LangGraph ReAct agent for multi-step queries.

        Falls back to simple RAG if the agent raises an exception.
        """
        logger.info(f"Routing to complex agent: '{query[:80]}'")
        try:
            result = self.complex_agent.run(
                query=query,
                conversation_history=self.memory.format_for_llm(),
            )
            # Update conversation memory so follow-up questions have context
            platform_names = [p['name'] for p in result.get('sources', [])]
            self.memory.add_turn(
                user_msg=query,
                assistant_msg=result['response'],
                platforms_returned=platform_names,
            )
            with self._history_lock:
                self.history.append({"role": "user", "content": query})
                self.history.append({"role": "assistant", "content": result['response']})
                if len(self.history) > self.conversation_memory * 2:
                    self.history = self.history[-(self.conversation_memory * 2):]
            # Log analytics
            if self.analytics_logger:
                try:
                    self.analytics_logger.log_query(
                        query=query,
                        response=result['response'],
                        sources=result.get('sources', []),
                        events=result.get('events', []),
                    )
                except Exception as e:
                    logger.warning(f"Analytics logging failed: {e}")
            return result
        except Exception as e:
            logger.error(f"Complex agent failed, falling back to simple RAG: {e}")
            # Fall through to simple RAG by calling chat() logic directly; avoid recursion
            # by temporarily disabling the classifier for this call
            saved = self.query_classifier
            self.query_classifier = None
            try:
                return self.chat(query)
            finally:
                self.query_classifier = saved

    def _is_event_query(self, query: str) -> bool:
        """
        Determine if query is asking about events.

        Args:
            query: User's query

        Returns:
            True if query appears to be event-related
        """
        query_lower = query.lower()
        return any(keyword in query_lower for keyword in EVENT_KEYWORDS)

    def _create_prompt_with_events(self, query: str, platforms: List[Dict], events: List[Dict]) -> List[Dict]:
        """
        Create LLM prompt that includes both platforms and events.

        Args:
            query: User's query
            platforms: Retrieved platforms
            events: Retrieved events

        Returns:
            Messages for LLM
        """
        # Build context from platforms
        platform_context = "Relevant Platforms:\n\n"
        for i, platform in enumerate(platforms, 1):
            # Build location info from geographic_focus and states
            location_info = ""
            geo = platform.get('geographic_focus', '')
            states = platform.get('states', '')
            if states:
                location_info = f"   Active in states: {states}\n"
            elif geo:
                location_info = f"   Geographic focus: {geo}\n"

            platform_context += (
                f"{i}. **{platform['name']}** ({platform['type']})\n"
                f"   Focus: {platform['focus_area']}\n"
                f"   Description: {platform['description']}\n"
                f"   Website: {platform['website']}\n"
            )
            if location_info:
                platform_context += location_info
            platform_context += "\n"

        # Build context from events if available
        event_context = ""
        if events:
            event_context = "\nUpcoming Events:\n\n"
            for i, event in enumerate(events, 1):
                event_url = event.get('url', '')

                # Find the org homepage to detect when an event URL is just the base website
                org_homepage = next(
                    (p['website'] for p in platforms if p['name'] == event.get('org_name')),
                    None
                )
                homepage = is_homepage_url(event_url, org_homepage)

                event_context += (
                    f"{i}. **{event['title']}**\n"
                    f"   Organization: {event.get('org_name', 'N/A')}\n"
                    f"   Date: {event.get('date', 'TBD')} {event.get('time', '')}\n"
                    f"   Location: {event.get('location', 'TBD')}\n"
                    f"   Description: {event.get('description', '')}\n"
                )

                # Add URL field - only include actual URL if it's not just the homepage
                if homepage:
                    event_context += f"   Event URL: [BASE WEBSITE ONLY - {org_homepage}]\n\n"
                else:
                    event_context += f"   Event URL: {event_url}\n\n"

        system_message = (
            "You are a warm, knowledgeable guide who helps people discover platforms and "
            "communities built by and for People of Color in tech and outdoor/travel spaces. "
            "You genuinely care about connecting people to the right communities.\n\n"

            "PERSONALITY & TONE:\n"
            "- Be conversational and approachable, like a well-connected friend giving advice\n"
            "- Show enthusiasm about the communities you're recommending\n"
            "- Ask follow-up questions naturally (e.g., 'Are you looking for something local or virtual?')\n"
            "- Share brief personal context about why a platform stands out\n"
            "- If someone's vague, help them narrow it down instead of dumping all results\n"
            "- Use natural flowing paragraphs, not robotic lists\n"
            "- It's okay to be concise - don't over-explain every platform\n\n"

            "CONVERSATION STYLE EXAMPLES:\n"
            "Good: 'Oh, you'd love Outdoor Afro! They have an incredible network of leaders in 60+ cities "
            "organizing hikes, camping trips, and nature walks. Check them out at [Outdoor Afro](https://outdoorafro.org).'\n"
            "Bad: '1. Outdoor Afro (Outdoor/Travel) - Focus: Black Outdoor Recreation - Website: outdoorafro.org'\n\n"

            "Good: 'There are a few great options depending on what you're looking for! "
            "Are you more interested in networking, job opportunities, or community events?'\n"
            "Bad: 'Here are 5 platforms that match your query:'\n\n"

            "FORMATTING RULES:\n"
            "- Write in natural paragraphs - avoid bullet point lists (•)\n"
            "- Use numbered lists (1., 2., 3.) only when listing 3+ specific recommendations\n"
            "- Format ALL links as clickable markdown: [Link Text](url)\n"
            "- Bold platform names with ** when first mentioning them\n"
            "- Add blank lines between paragraphs for readability\n\n"

            "EVENT URL RULES:\n"
            "- If an event's URL says '[BASE WEBSITE ONLY - url]': say 'Check the [Org Name](url) website for details' "
            "instead of creating a fake event link\n"
            "- If it's a real event URL: link it naturally like [Register here](url) or [Event details](url)\n"
            "- NEVER link to a base website URL as 'Event Details' - that's misleading\n\n"

            "IMPORTANT:\n"
            "- Only recommend platforms from the provided context - don't make things up\n"
            "- If no results match, say so honestly and suggest broadening the search\n"
            "- Remember conversation context - if someone asks 'tell me more', refer back to what was discussed"
        )

        # Build messages list with conversation history
        messages = [{"role": "system", "content": system_message}]

        # Add conversation history from memory (more structured)
        # Use new memory format if available, fallback to legacy history
        if self.memory and self.memory.history:
            messages.extend(self.memory.format_for_llm())
        else:
            messages.extend(self.history)

        # Add current query with context
        user_message = (
            f"User question: {query}\n\n"
            f"{platform_context}"
            f"{event_context}"
            f"Please provide a helpful answer to the user's question based on the above information.\n\n"
            f"REMINDER: When using bullet points, put each bullet on a NEW LINE like this:\n"
            f"Recommendations:\n\n"
            f"• First item\n"
            f"• Second item\n"
            f"• Third item\n\n"
            f"NOT like this: Recommendations: • First item • Second item • Third item"
        )
        messages.append({"role": "user", "content": user_message})

        return messages

    def _handle_no_results(self, query: str) -> str:
        """
        Generate response when no platforms are found.

        Args:
            query: User's query

        Returns:
            Helpful message suggesting next steps
        """
        return (
            f"I couldn't find platforms that match '{query}'. "
            "Try broadening your search or asking about different communities. "
            "For example, you could search for 'Black tech professionals' or 'Latinx hiking groups'.\n\n"
            "If you know of a platform that should be included, please let us know!"
        )

    def _create_fallback_response(self, query: str, platforms: List[Dict], events: Optional[List[Dict]] = None) -> str:
        """
        Create simple response without LLM (fallback).

        Args:
            query: User's query
            platforms: Retrieved platforms
            events: Retrieved events (optional)

        Returns:
            Basic formatted response
        """
        response_parts = [
            f"Here are {len(platforms)} platforms that might interest you:\n"
        ]

        for i, platform in enumerate(platforms[:3], 1):  # Show top 3
            response_parts.append(
                f"{i}. **{platform['name']}** - {platform['focus_area']}\n"
                f"   {platform['description']}\n"
                f"   Website: {platform['website']}\n"
            )

        if len(platforms) > 3:
            response_parts.append(f"\n...and {len(platforms) - 3} more platforms.")

        # Add events if available
        if events:
            response_parts.append(f"\n\n🎉 Upcoming Events ({len(events)}):\n")
            for i, event in enumerate(events[:3], 1):
                event_url = event.get('url', 'URL not available')
                response_parts.append(
                    f"{i}. **{event['title']}** - {event.get('org_name', 'N/A')}\n"
                    f"   📅 {event.get('date', 'TBD')} at {event.get('location', 'TBD')}\n"
                    f"   🔗 Register: {event_url}\n"
                )

        return "\n".join(response_parts)

    def clear_history(self):
        """Clear conversation history."""
        with self._history_lock:
            self.history = []
        self.memory.clear()
        logger.info("Conversation history cleared")

    def get_history(self) -> List[Dict[str, str]]:
        """Get conversation history."""
        return self.history.copy()

    def get_stats(self) -> Dict:
        """Get chatbot statistics."""
        return {
            "retriever": self.retriever.get_stats(),
            "conversation_turns": len(self.history) // 2,
            "n_results": self.n_results,
            "memory_turns": self.conversation_memory
        }


def format_response_for_display(result: Dict) -> str:
    """
    Format chatbot response for display.

    Args:
        result: Result dictionary from chatbot.chat()

    Returns:
        Formatted string for display
    """
    lines = [result["response"]]

    if result.get("sources"):
        lines.append("\n" + "=" * 60)
        lines.append("📚 Sources:")
        lines.append("=" * 60)

        for platform in result["sources"]:
            lines.append(
                f"\n• {platform['name']} ({platform['type']})\n"
                f"  {platform['website']}"
            )

    return "\n".join(lines)


if __name__ == "__main__":
    # Quick test
    logging.basicConfig(level=logging.INFO)

    chatbot = RAGChatbot()

    # Test query
    query = "What communities exist for Black women in tech?"
    result = chatbot.chat(query)

    print("\n" + "=" * 60)
    print("CHATBOT TEST")
    print("=" * 60)
    print(f"\nQuery: {query}")
    print(f"\n{format_response_for_display(result)}")

    print("\n" + "=" * 60)
    print("Stats:")
    print("=" * 60)
    stats = chatbot.get_stats()
    print(f"Retrieved: {result['retrieved']} platforms")
    print(f"Database: {stats['retriever']['database']['total_platforms']} total platforms")
