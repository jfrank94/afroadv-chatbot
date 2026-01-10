"""
Main chatbot logic integrating RAG pipeline.

Combines retrieval + generation with conversation memory.
Now includes event search capability and smart context handling!
"""

from typing import List, Dict, Optional
import logging
from src.core.retriever import Retriever
from src.infrastructure.llm import LLMProvider, create_rag_prompt
from src.events.event_store import EventStore
from src.core.conversation import (
    ConversationMemory,
    QueryReformulator,
    IntentTracker,
    IntentType
)

logger = logging.getLogger(__name__)


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
        enable_events: bool = True
    ):
        """
        Initialize chatbot with retriever and LLM.

        Args:
            retriever: Retriever instance (creates new if None)
            llm: LLMProvider instance (creates new if None)
            n_results: Number of platforms to retrieve per query
            conversation_memory: Number of conversation turns to remember
            enable_events: Enable event search (default: True)
        """
        self.retriever = retriever or Retriever()
        self.llm = llm or LLMProvider()
        self.n_results = n_results
        self.conversation_memory = conversation_memory
        self.enable_events = enable_events

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

        logger.info(f"RAG Chatbot initialized (retrieve top-{n_results}, memory={conversation_memory} turns, events={'enabled' if self.enable_events else 'disabled'}, context_aware=True)")

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
            return {
                "response": "Please ask me a question about PoC platforms in tech or outdoor/travel!",
                "sources": [],
                "events": [],
                "retrieved": 0,
                "events_found": 0,
                "error": "empty_query",
                "query": query
            }

        # Validate query length (prevent abuse and excessive token usage)
        MAX_QUERY_LENGTH = 1000
        if len(query) > MAX_QUERY_LENGTH:
            return {
                "response": f"Your question is too long ({len(query)} characters). Please keep it under {MAX_QUERY_LENGTH} characters.",
                "sources": [],
                "events": [],
                "retrieved": 0,
                "events_found": 0,
                "error": "query_too_long",
                "query": query[:100] + "..."  # Truncate for logging
            }

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
                future_events = executor.submit(
                    self.event_store.search_events,
                    query=query,
                    n_results=5
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
            self.history.append({"role": "user", "content": query})
            self.history.append({"role": "assistant", "content": response_text})

            # Trim history to conversation_memory turns
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
        response_text = self.llm.generate(messages, max_tokens=512, temperature=0.7)
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

        return result

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
            platform_context += (
                f"{i}. **{platform['name']}** ({platform['type']})\n"
                f"   Focus: {platform['focus_area']}\n"
                f"   Description: {platform['description']}\n"
                f"   Website: {platform['website']}\n\n"
            )

        # Build context from events if available
        event_context = ""
        if events:
            event_context = "\nUpcoming Events:\n\n"
            for i, event in enumerate(events, 1):
                event_url = event.get('url', '')

                # Check if event URL is just the org homepage (no specific event page found)
                # Look for platform with matching org name to get their website
                org_homepage = None
                for p in platforms:
                    if p['name'] == event.get('org_name'):
                        org_homepage = p['website']
                        break

                # Normalize URLs for comparison (remove protocol, www, trailing slashes)
                def normalize_url(url):
                    if not url:
                        return ""
                    normalized = url.lower()
                    normalized = normalized.replace('https://', '').replace('http://', '')
                    normalized = normalized.replace('www.', '')
                    normalized = normalized.rstrip('/')
                    return normalized

                # Check if event URL is just the org homepage (no specific event page path)
                event_url_normalized = normalize_url(event_url)
                org_homepage_normalized = normalize_url(org_homepage) if org_homepage else ""

                # URL is considered homepage if it's exactly the same as org homepage
                # (not just same domain - we want to allow /events, /programs, etc.)
                is_homepage = (
                    org_homepage_normalized and
                    event_url_normalized == org_homepage_normalized
                )

                event_context += (
                    f"{i}. **{event['title']}**\n"
                    f"   Organization: {event.get('org_name', 'N/A')}\n"
                    f"   Date: {event.get('date', 'TBD')} {event.get('time', '')}\n"
                    f"   Location: {event.get('location', 'TBD')}\n"
                    f"   Description: {event.get('description', '')}\n"
                )

                # Add URL field - only include actual URL if it's not just the homepage
                if is_homepage:
                    event_context += f"   Event URL: [BASE WEBSITE ONLY - {org_homepage}]\n\n"
                else:
                    event_context += f"   Event URL: {event_url}\n\n"

        system_message = (
            "You are a helpful assistant for discovering platforms and communities "
            "serving People of Color in tech and outdoor/travel spaces. "
            "Answer questions based on the provided platform and event information. "
            "Be friendly, concise, and helpful.\n\n"
            "CRITICAL FORMATTING RULES:\n"
            "1. Use natural paragraph format - DO NOT use bullet points (•) in your responses\n"
            "2. Write recommendations as numbered lists (1., 2., 3.) or as flowing sentences\n"
            "3. Format ALL links as markdown: [Link Text](full-url-here)\n"
            "4. Add blank lines between sections for readability\n\n"
            "EVENT URL RULES (CRITICAL - FOLLOW EXACTLY):\n"
            "- Check each event's 'Event URL' field carefully\n"
            "- If it says '[BASE WEBSITE ONLY - url]': Do NOT show a clickable event link. Instead say 'Visit [Org Name](url) for upcoming event details' or 'Check the [Org Name](url) website regularly for updates'\n"
            "- If it's a normal https:// URL (not marked BASE WEBSITE ONLY): Create a clickable link like [Event Details](url) or [Register Here](url)\n"
            "- NEVER link to base website URLs as 'Event Details' - that's misleading\n"
            "- Treat each event independently - some have specific URLs, some don't\n\n"
            "CORRECT RECOMMENDATION FORMAT:\n"
            "To stay updated on events, I recommend checking the Outdoor Afro website regularly, "
            "following their social media channels, and signing up for their newsletter.\n\n"
            "OR use numbered lists:\n\n"
            "1. Visit the Outdoor Afro website regularly\n"
            "2. Follow their social media channels\n"
            "3. Sign up for their newsletter\n\n"
            "WRONG (don't use bullet points like this):\n"
            "Recommendations: • First • Second • Third\n\n"
            "EXAMPLE EVENT FORMATS:\n\n"
            "WITH SPECIFIC EVENT URL:\n"
            "**Black History Month Hike Series**\n"
            "📅 January 12, 2026 | 📍 Oakland, CA\n"
            "🔗 [Event Details](https://outdoorafro.org/events/bhm-hike-2026)\n"
            "Community hike celebrating Black history.\n\n"
            "WITHOUT SPECIFIC EVENT URL (when Event URL says '[BASE WEBSITE ONLY - url]'):\n"
            "**Black History Month Hike Series**\n"
            "📅 January 12, 2026 | 📍 Multiple Cities\n"
            "Check the [Outdoor Afro](https://outdoorafro.org) website regularly for upcoming event details.\n"
            "A month-long hiking series celebrating Black history.\n\n"
            "CRITICAL: When you see [BASE WEBSITE ONLY], NEVER create a '🔗 Event Details' link!"
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
