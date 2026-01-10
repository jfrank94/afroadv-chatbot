"""
Conversation memory and context handling for the PoC platforms chatbot.

Handles follow-up questions, intent tracking, and query reformulation.
Enables smart context-aware responses like:
  User: "What events are upcoming for Black tech professionals?"
  Bot: [lists events]
  User: "And Techqueria?"
  Bot: [understands to look for Techqueria events]
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class IntentType(Enum):
    """User intent types specific to PoC platforms chatbot."""
    DISCOVER_PLATFORMS = "discover"
    FIND_EVENTS = "events"
    LOCATION_SPECIFIC = "location"
    PROGRAM_DETAILS = "programs"
    DEMOGRAPHIC_FOCUS = "demographic"
    NONE = "none"


@dataclass
class ConversationState:
    """Tracks conversation context across turns."""
    current_intent: IntentType = IntentType.NONE
    entities: Dict = field(default_factory=dict)
    last_platforms: List[str] = field(default_factory=list)


class ConversationMemory:
    """Manages conversation history with sliding window."""

    def __init__(self, max_turns: int = 5):
        """
        Initialize conversation memory.

        Args:
            max_turns: Maximum conversation turns to retain
        """
        self.max_turns = max_turns
        self.history: List[Dict] = []
        self.state = ConversationState()

    def add_turn(self, user_msg: str, assistant_msg: str, platforms_returned: List[str] = None):
        """
        Add a conversation turn.

        Args:
            user_msg: User's query
            assistant_msg: Assistant's response
            platforms_returned: List of platform names returned in this turn
        """
        self.history.append({
            'user': user_msg,
            'assistant': assistant_msg,
            'timestamp': datetime.now(),
            'platforms': platforms_returned or []
        })

        # Maintain sliding window
        if len(self.history) > self.max_turns:
            self.history = self.history[-self.max_turns:]

        # Update state
        if platforms_returned:
            self.state.last_platforms = platforms_returned

        logger.debug(f"Added turn to memory. Total turns: {len(self.history)}")

    def get_recent_history(self, n_turns: int = 3) -> List[Dict]:
        """Get last N turns."""
        return self.history[-n_turns:] if self.history else []

    def format_for_llm(self) -> List[Dict]:
        """
        Format conversation history for LLM messages list.

        Returns:
            List of message dicts with 'role' and 'content'
        """
        messages = []
        for turn in self.history[-3:]:  # Last 3 turns
            messages.append({"role": "user", "content": turn['user']})
            messages.append({"role": "assistant", "content": turn['assistant']})
        return messages

    def clear(self):
        """Clear conversation history."""
        self.history = []
        self.state = ConversationState()
        logger.info("Conversation memory cleared")


class ContextDependencyDetector:
    """Detects if a query needs conversation context to be understood."""

    PRONOUNS = {'it', 'they', 'them', 'this', 'that', 'these', 'those', 'he', 'she'}
    CONNECTOR_WORDS = {'and', 'also', 'what about', 'how about', 'but', 'or'}
    COMPARATIVE = {'more', 'other', 'another', 'similar', 'different'}

    def needs_reformulation(self, query: str, has_history: bool) -> bool:
        """
        Determine if query is context-dependent and needs reformulation.

        Args:
            query: User's query
            has_history: Whether conversation history exists

        Returns:
            True if query needs reformulation with context
        """
        if not has_history:
            return False

        query_lower = query.lower().strip()
        words = set(query_lower.split())

        score = 0

        # Signal 1: Very short queries (< 5 words)
        if len(words) < 5:
            score += 1

        # Signal 2: Contains pronouns
        if words & self.PRONOUNS:
            score += 2

        # Signal 3: Starts with connector word
        first_word = query_lower.split()[0] if query_lower else ""
        if first_word in self.CONNECTOR_WORDS:
            score += 2

        # Signal 4: Contains comparatives
        if words & self.COMPARATIVE:
            score += 1

        # Threshold: Score >= 2 means likely context-dependent
        needs_context = score >= 2
        logger.debug(f"Context dependency check: '{query}' -> score={score}, needs_reformulation={needs_context}")
        return needs_context


class QueryReformulator:
    """Reformulates context-dependent queries into standalone questions."""

    def __init__(self, llm_client):
        """
        Initialize query reformulator.

        Args:
            llm_client: LLMProvider instance for reformulation
        """
        self.llm = llm_client
        self.detector = ContextDependencyDetector()

    def reformulate(self, query: str, memory: ConversationMemory) -> str:
        """
        Reformulate query if needed, otherwise return original.

        Args:
            query: User's query
            memory: ConversationMemory instance

        Returns:
            Reformulated standalone query or original query
        """
        # Check if reformulation is needed
        if not self.detector.needs_reformulation(query, bool(memory.history)):
            logger.debug(f"No reformulation needed for: '{query}'")
            return query

        # Build context from recent history
        history_messages = memory.format_for_llm()
        if not history_messages:
            return query

        # Create reformulation prompt
        history_text = "\n".join([
            f"{msg['role'].capitalize()}: {msg['content'][:200]}"
            for msg in history_messages[-4:]  # Last 2 turns (4 messages)
        ])

        reformulation_prompt = f"""Conversation history:
{history_text}

Follow-up question: {query}

Reformulate this as a clear, concise standalone question (10 words or less). Preserve the user's intent.

Standalone question:"""

        try:
            # Use LLM for reformulation (fast, low temperature)
            standalone = self.llm.generate(
                messages=[{"role": "user", "content": reformulation_prompt}],
                max_tokens=100,
                temperature=0.0
            )

            if standalone and len(standalone.strip()) > 0:
                logger.info(f"Reformulated query: '{query}' -> '{standalone}'")
                return standalone.strip()
            else:
                logger.warning("Empty reformulation result, using original query")
                return query

        except Exception as e:
            # Fallback to original query if reformulation fails
            logger.error(f"Query reformulation failed: {e}. Using original query.")
            return query


class IntentTracker:
    """Tracks user intent across conversation turns."""

    # Keywords that signal specific intents
    INTENT_KEYWORDS = {
        IntentType.FIND_EVENTS: [
            'event', 'events', 'upcoming', 'conference', 'meetup',
            'happening', 'schedule', 'calendar', 'gathering', 'summit'
        ],
        IntentType.PROGRAM_DETAILS: [
            'program', 'programs', 'offer', 'provide', 'services',
            'mentorship', 'training', 'course', 'workshop'
        ],
        IntentType.LOCATION_SPECIFIC: [
            ' in ', ' near ', ' at ', 'local', 'area', 'city',
            'bay area', 'nyc', 'atlanta', 'seattle', 'austin'
        ]
    }

    def detect_intent(self, query: str, current_state: ConversationState) -> IntentType:
        """
        Detect intent from query.

        Args:
            query: User's query
            current_state: Current conversation state

        Returns:
            Detected IntentType
        """
        query_lower = query.lower()

        # Check for explicit intent keywords
        for intent, keywords in self.INTENT_KEYWORDS.items():
            if any(kw in query_lower for kw in keywords):
                logger.debug(f"Detected intent: {intent.value} from query: '{query}'")
                return intent

        # Maintain current intent if no new intent detected (sticky intent)
        if current_state.current_intent != IntentType.NONE:
            logger.debug(f"Maintaining previous intent: {current_state.current_intent.value}")
            return current_state.current_intent

        logger.debug("No specific intent detected, defaulting to DISCOVER_PLATFORMS")
        return IntentType.DISCOVER_PLATFORMS

    def extract_entities(self, query: str) -> Dict:
        """
        Extract entities (demographics, platforms, locations) from query.

        Args:
            query: User's query

        Returns:
            Dictionary of extracted entities
        """
        entities = {}

        # Extract demographics
        demographics = {
            'black', 'african american', 'afro', 'latinx', 'latina', 'latino', 'hispanic',
            'asian', 'indigenous', 'native', 'women', 'lgbtq', 'queer', 'trans'
        }
        query_lower = query.lower()
        found_demographics = [d for d in demographics if d in query_lower]
        if found_demographics:
            entities['demographics'] = found_demographics

        # Extract platform names (capitalized words that aren't common words)
        common_words = {'I', 'In', 'At', 'On', 'The', 'A', 'An', 'For', 'To', 'Of'}
        platforms = [
            w for w in query.split()
            if w and w[0].isupper() and w not in common_words
        ]
        if platforms:
            entities['platforms'] = platforms

        logger.debug(f"Extracted entities: {entities}")
        return entities

    def update_state(self, query: str, state: ConversationState) -> ConversationState:
        """
        Update conversation state based on new query.

        Args:
            query: User's query
            state: Current conversation state

        Returns:
            Updated conversation state
        """
        # Detect new intent
        new_intent = self.detect_intent(query, state)
        state.current_intent = new_intent

        # Extract and merge entities
        new_entities = self.extract_entities(query)
        state.entities.update(new_entities)

        return state


# Convenience function for external usage
def create_conversation_memory(max_turns: int = 5) -> ConversationMemory:
    """
    Create a new ConversationMemory instance.

    Args:
        max_turns: Maximum conversation turns to retain

    Returns:
        ConversationMemory instance
    """
    return ConversationMemory(max_turns=max_turns)
