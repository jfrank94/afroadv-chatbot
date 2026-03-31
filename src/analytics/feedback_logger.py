"""
User feedback logging.

Writes thumbs up/down ratings and optional text to Google Sheets
(primary) with a local JSONL fallback.
"""

import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

import config
from src.analytics.query_logger import _get_sheets_client, _get_or_create_sheet

logger = logging.getLogger(__name__)

_FEEDBACK_HEADERS = [
    "timestamp", "rating", "comment", "query_keywords"
]


class FeedbackLogger:
    """Logs user feedback to Google Sheets with local JSONL fallback."""

    def __init__(self, log_file: Path = None):
        self.log_file = log_file or Path("data/feedback.jsonl")
        self.log_file.parent.mkdir(exist_ok=True)
        self._sheets_client = _get_sheets_client()

    def log_feedback(
        self,
        rating: str,           # "👍" or "👎"
        query: str,            # The query that was rated
        comment: Optional[str] = None,
    ):
        """Log a user feedback submission."""
        keywords = self._extract_keywords(query)
        row = {
            "timestamp": datetime.now().isoformat(),
            "rating": rating,
            "comment": (comment or "").strip(),
            "query_keywords": keywords,
        }
        self._write(row)

    def _write(self, row: dict):
        """Write a row to Google Sheets; fall back to JSONL on failure."""
        if self._sheets_client:
            try:
                ws = _get_or_create_sheet(self._sheets_client, config.ANALYTICS_FEEDBACK_SHEET)
                # Add headers if empty
                if ws.row_count == 0 or not ws.row_values(1):
                    ws.append_row(_FEEDBACK_HEADERS)
                ws.append_row([
                    row["timestamp"],
                    row["rating"],
                    row["comment"],
                    ", ".join(row["query_keywords"]),
                ])
                return
            except Exception as e:
                logger.warning(f"Google Sheets feedback write failed, falling back to JSONL: {e}")

        with open(self.log_file, "a") as f:
            f.write(json.dumps(row) + "\n")

    def _extract_keywords(self, query: str) -> list:
        stop_words = {
            "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
            "has", "in", "is", "it", "of", "on", "that", "the", "to", "was",
            "will", "with", "what", "where", "who", "how", "when", "me", "my",
            "i", "you", "can", "find", "show", "tell", "give", "get",
        }
        words = query.lower().split()
        keywords = [w.strip("?.,!") for w in words if w.strip("?.,!") not in stop_words]
        return list(dict.fromkeys(keywords))[:10]
