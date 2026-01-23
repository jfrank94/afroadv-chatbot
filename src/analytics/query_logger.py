"""
Simple analytics logging for chatbot queries and responses.

Logs queries to JSONL file for later analysis without any PII.
"""

import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional


class QueryLogger:
    """Logs chatbot queries and responses for analytics."""

    def __init__(self, log_file: Path = None):
        """Initialize the query logger.

        Args:
            log_file: Path to JSONL log file (default: data/analytics.jsonl)
        """
        if log_file is None:
            log_file = Path("data/analytics.jsonl")

        self.log_file = log_file
        self.log_file.parent.mkdir(exist_ok=True)

    def log_query(
        self,
        query: str,
        response: str,
        sources: List[Dict[str, Any]] = None,
        events: List[Dict[str, Any]] = None,
        error: Optional[str] = None
    ):
        """Log a query and response.

        Args:
            query: User's question
            response: Chatbot's response
            sources: List of platform sources returned
            events: List of events returned
            error: Error message if query failed
        """
        # Extract just the platform names/IDs from sources (no PII)
        platform_ids = []
        if sources:
            platform_ids = [s.get('id', s.get('name', 'unknown')) for s in sources]

        # Extract event IDs
        event_ids = []
        if events:
            event_ids = [e.get('id', 'unknown') for e in events]

        # Create log entry
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "query_length": len(query),
            "query_keywords": self._extract_keywords(query),
            "response_length": len(response) if response else 0,
            "num_sources": len(sources) if sources else 0,
            "platform_ids": platform_ids,
            "num_events": len(events) if events else 0,
            "event_ids": event_ids,
            "had_error": error is not None,
            "error_type": type(error).__name__ if error else None
        }

        # Append to JSONL file
        with open(self.log_file, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')

    def _extract_keywords(self, query: str) -> List[str]:
        """Extract simple keywords from query (lowercased, common words removed)."""
        # Common stop words to filter out
        stop_words = {
            'a', 'an', 'and', 'are', 'as', 'at', 'be', 'by', 'for', 'from',
            'has', 'he', 'in', 'is', 'it', 'its', 'of', 'on', 'that', 'the',
            'to', 'was', 'will', 'with', 'what', 'where', 'who', 'how', 'when',
            'me', 'my', 'i', 'you', 'can', 'find', 'show', 'tell', 'give', 'get'
        }

        # Extract words, lowercase, filter stop words
        words = query.lower().split()
        keywords = [w.strip('?.,!') for w in words if w.strip('?.,!') not in stop_words]

        # Return unique keywords (first 10 max)
        return list(dict.fromkeys(keywords))[:10]

    def get_stats(self) -> Dict[str, Any]:
        """Get basic analytics stats from the log file.

        Returns:
            Dictionary with analytics metrics
        """
        if not self.log_file.exists():
            return {
                "total_queries": 0,
                "total_errors": 0,
                "avg_sources_per_query": 0,
                "avg_events_per_query": 0,
                "top_keywords": []
            }

        # Read all log entries
        entries = []
        with open(self.log_file) as f:
            for line in f:
                entries.append(json.loads(line.strip()))

        if not entries:
            return {
                "total_queries": 0,
                "total_errors": 0,
                "avg_sources_per_query": 0,
                "avg_events_per_query": 0,
                "top_keywords": []
            }

        # Calculate metrics
        total_queries = len(entries)
        total_errors = sum(1 for e in entries if e.get('had_error'))

        total_sources = sum(e.get('num_sources', 0) for e in entries)
        avg_sources = total_sources / total_queries if total_queries > 0 else 0

        total_events = sum(e.get('num_events', 0) for e in entries)
        avg_events = total_events / total_queries if total_queries > 0 else 0

        # Count keyword frequencies
        keyword_counts = {}
        for entry in entries:
            for keyword in entry.get('query_keywords', []):
                keyword_counts[keyword] = keyword_counts.get(keyword, 0) + 1

        # Get top 20 keywords
        top_keywords = sorted(
            keyword_counts.items(),
            key=lambda x: x[1],
            reverse=True
        )[:20]

        return {
            "total_queries": total_queries,
            "total_errors": total_errors,
            "error_rate": f"{(total_errors/total_queries*100):.1f}%" if total_queries > 0 else "0%",
            "avg_sources_per_query": f"{avg_sources:.1f}",
            "avg_events_per_query": f"{avg_events:.1f}",
            "top_keywords": top_keywords
        }
