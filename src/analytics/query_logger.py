"""
Analytics logging for chatbot queries.

Writes to Google Sheets (primary) with a local JSONL fallback if Sheets
is unavailable or not configured.
"""

import json
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

import config

logger = logging.getLogger(__name__)

# Header row for the queries sheet
_QUERIES_HEADERS = [
    "timestamp", "query_length", "query_keywords",
    "num_sources", "platform_ids", "num_events",
    "had_error", "error_type"
]


def _get_sheets_client():
    """Return a gspread client using the service account credentials, or None."""
    if not config.GOOGLE_SERVICE_ACCOUNT_JSON:
        return None
    try:
        import gspread
        creds = json.loads(config.GOOGLE_SERVICE_ACCOUNT_JSON)
        return gspread.service_account_from_dict(creds)
    except Exception as e:
        logger.warning(f"Could not initialize Google Sheets client: {e}")
        return None


def _get_or_create_sheet(client, sheet_name: str):
    """Open the analytics spreadsheet and return the named worksheet.

    Creates the header row if the sheet is empty.
    """
    spreadsheet = client.open(config.ANALYTICS_SPREADSHEET_NAME)
    worksheet = spreadsheet.worksheet(sheet_name)

    # Add headers if the sheet is empty
    if worksheet.row_count == 0 or not worksheet.row_values(1):
        if sheet_name == config.ANALYTICS_QUERIES_SHEET:
            worksheet.append_row(_QUERIES_HEADERS)
    return worksheet


class QueryLogger:
    """Logs chatbot queries to Google Sheets with local JSONL fallback."""

    def __init__(self, log_file: Path = None):
        self.log_file = log_file or Path("data/analytics.jsonl")
        self.log_file.parent.mkdir(exist_ok=True)
        self._sheets_client = _get_sheets_client()

    def log_query(
        self,
        query: str,
        response: str,
        sources: List[Dict[str, Any]] = None,
        events: List[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ):
        """Log a query and response (no PII stored)."""
        platform_ids = [s.get("id", s.get("name", "unknown")) for s in (sources or [])]
        event_ids = [e.get("id", "unknown") for e in (events or [])]

        row = {
            "timestamp": datetime.now().isoformat(),
            "query_length": len(query),
            "query_keywords": self._extract_keywords(query),
            "response_length": len(response) if response else 0,
            "num_sources": len(sources) if sources else 0,
            "platform_ids": platform_ids,
            "num_events": len(events) if events else 0,
            "event_ids": event_ids,
            "had_error": error is not None,
            "error_type": type(error).__name__ if error else None,
        }

        self._write(row)

    def _write(self, row: dict):
        """Write a row to Google Sheets; fall back to JSONL on failure."""
        if self._sheets_client:
            try:
                ws = _get_or_create_sheet(self._sheets_client, config.ANALYTICS_QUERIES_SHEET)
                ws.append_row([
                    row["timestamp"],
                    row["query_length"],
                    ", ".join(row["query_keywords"]),
                    row["num_sources"],
                    ", ".join(row["platform_ids"]),
                    row["num_events"],
                    str(row["had_error"]),
                    row["error_type"] or "",
                ])
                return
            except Exception as e:
                logger.warning(f"Google Sheets write failed, falling back to JSONL: {e}")

        # Local fallback
        with open(self.log_file, "a") as f:
            f.write(json.dumps(row) + "\n")

    def _extract_keywords(self, query: str) -> List[str]:
        stop_words = {
            "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
            "has", "he", "in", "is", "it", "its", "of", "on", "that", "the",
            "to", "was", "will", "with", "what", "where", "who", "how", "when",
            "me", "my", "i", "you", "can", "find", "show", "tell", "give", "get",
        }
        words = query.lower().split()
        keywords = [w.strip("?.,!") for w in words if w.strip("?.,!") not in stop_words]
        return list(dict.fromkeys(keywords))[:10]
