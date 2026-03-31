"""Query classifier — routes queries to simple RAG or complex agent path.

Uses fast regex pattern matching (zero LLM calls, zero latency). Conservative
by design: only promotes to complex when a pattern fires clearly. A false-
negative (complex query treated as simple) is acceptable — the RAG path handles
most queries well. A false-positive (simple query sent to agent) wastes latency
and tokens, which is worse.
"""

import re
import logging
from typing import Literal

logger = logging.getLogger(__name__)

QueryType = Literal["simple", "complex"]

# Each pattern targets a specific class of query that benefits from multi-step
# agent reasoning rather than single-pass RAG retrieval.
_COMPLEX_PATTERNS: list[tuple[str, re.Pattern]] = [
    (
        "comparative",
        re.compile(
            r'\bcompare\b|\bvs\.?\b|\bversus\b|\bdifference between\b|\bwhich is better\b',
            re.I,
        ),
    ),
    (
        "superlative",
        re.compile(
            r'\bmost (active|popular|well.known|established)\b'
            r'|\bbiggest\b|\blargest\b|\bbest\b|\btop \d\b',
            re.I,
        ),
    ),
    (
        "multi_entity",
        re.compile(
            r'\b(both|all of|each of)\b.{3,60}\b(and|or)\b',
            re.I,
        ),
    ),
    (
        "location_plus_category",
        re.compile(
            r'\bin\s+(nyc|new york|la|los angeles|sf|san francisco|'
            r'chicago|atl|atlanta|dc|miami|boston|seattle|denver|'
            r'austin|houston|dallas|philly|philadelphia)\b'
            r'.{0,40}\b(tech|outdoor|hiking|coding|climbing|events?|conference)\b',
            re.I,
        ),
    ),
    (
        "events_plus_platform",
        re.compile(
            r'\b\w[\w\s]{2,30}\b\s+(and|with)\s+(upcoming\s+)?events?\b',
            re.I,
        ),
    ),
]


def classify(query: str) -> QueryType:
    """Classify a query as 'simple' or 'complex'.

    Args:
        query: Raw user query string

    Returns:
        'complex' if any pattern matches, 'simple' otherwise.
    """
    for label, pattern in _COMPLEX_PATTERNS:
        if pattern.search(query):
            logger.debug(f"Query classified as complex ({label}): '{query[:80]}'")
            return "complex"
    logger.debug(f"Query classified as simple: '{query[:80]}'")
    return "simple"
