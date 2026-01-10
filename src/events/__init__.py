"""
Events module for managing organization events.

Uses SmartEventFinder for intelligent event discovery via:
- Web search (Tavily API)
- LLM-powered extraction
- URL verification
"""

from .event_store import EventStore
from .smart_event_finder import SmartEventFinder

__all__ = ['EventStore', 'SmartEventFinder']
