"""
Base LLM extractor class with shared functionality for event extraction.

This module provides a common base class for all LLM-powered extractors,
consolidating duplicate code for HTML parsing, JSON handling, deduplication,
and date filtering.
"""

import json
import logging
import requests
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

from config import ContentLimits, EventConfig

logger = logging.getLogger(__name__)


class BaseLLMExtractor:
    """Base class for LLM-powered event extractors with shared utilities.

    Provides consolidated functionality for HTML parsing, JSON handling,
    deduplication, and date filtering across all event extractors.

    Attributes:
        llm: LLMProvider instance for making LLM calls
        session: Requests session with user-agent header for HTTP calls
    """

    def __init__(self, llm_provider):
        """
        Initialize the base extractor.

        Args:
            llm_provider: LLMProvider instance for making LLM calls
        """
        self.llm = llm_provider
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (compatible; PoC-Platforms-Bot/1.0; Educational/Research)'
        })

    def fetch_and_parse_page(self, url: str, timeout: int = 15) -> Optional[tuple[str, BeautifulSoup]]:
        """
        Fetch a URL and parse HTML content with cleanup.

        Fetches the URL, removes script/style/nav/footer elements, and
        extracts clean text. Automatically truncates content to ContentLimits.MAX_CONTENT_LENGTH.

        Args:
            url: URL to fetch
            timeout: Request timeout in seconds (default: 15)

        Returns:
            Tuple of (text_content, soup) where text_content is cleaned text
            and soup is the BeautifulSoup object, or None if error occurs.

        Raises:
            Logged but not raised: Requests exceptions and parsing errors
        """
        try:
            logger.info(f"Fetching {url}...")
            response = self.session.get(url, timeout=timeout)
            response.raise_for_status()

            # Parse HTML
            soup = BeautifulSoup(response.text, 'html.parser')

            # Remove script and style elements
            for script in soup(['script', 'style', 'nav', 'footer', 'header']):
                script.decompose()

            # Get text content
            text_content = soup.get_text(separator='\n', strip=True)

            # Limit content length for LLM
            if len(text_content) > ContentLimits.MAX_CONTENT_LENGTH:
                text_content = text_content[:ContentLimits.MAX_CONTENT_LENGTH] + "\n...[content truncated]"

            return text_content, soup

        except requests.RequestException as e:
            logger.error(f"Error fetching {url}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error parsing {url}: {e}")
            return None

    def extract_links_from_soup(self, soup: BeautifulSoup, base_url: str) -> List[str]:
        """
        Extract all links from parsed HTML and resolve relative URLs.

        Finds all anchor tags and converts relative URLs to absolute URLs.
        Limits results to ContentLimits.MAX_LINKS_TO_PROCESS.

        Args:
            soup: BeautifulSoup parsed HTML object
            base_url: Base URL for resolving relative links

        Returns:
            List of absolute URLs (up to MAX_LINKS_TO_PROCESS items)
        """
        from urllib.parse import urljoin

        all_links: List[str] = []
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            if isinstance(href, str):
                if href.startswith('http'):
                    all_links.append(href)
                elif href.startswith('/'):
                    all_links.append(urljoin(base_url, href))

        return all_links[:ContentLimits.MAX_LINKS_TO_PROCESS]

    def parse_llm_json_response(self, response: str) -> Optional[List[Dict]]:
        """
        Parse LLM response and extract JSON array.

        Handles markdown code blocks (```json/```), extracts JSON arrays from
        mixed text responses, and validates the output is a list.

        Args:
            response: Raw LLM response text (may contain markdown, extra text, etc.)

        Returns:
            Parsed JSON list if successful, None if parsing fails or response is empty

        Example:
            >>> response = "Here is the JSON:\\n```json\\n[{\"key\": \"value\"}]\\n```"
            >>> result = extractor.parse_llm_json_response(response)
            >>> result == [{"key": "value"}]
            True
        """
        if not response or not response.strip():
            logger.warning("Empty response from LLM")
            return None

        response = response.strip()

        # Handle markdown code blocks
        if '```json' in response:
            response = response.split('```json')[1].split('```')[0].strip()
        elif '```' in response:
            response = response.split('```')[1].split('```')[0].strip()

        # Extract JSON array if response contains extra text
        if '[' in response and ']' in response:
            start = response.index('[')
            end = response.rindex(']') + 1
            response = response[start:end]

        try:
            data = json.loads(response)
            return data if isinstance(data, list) else None
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            logger.debug(f"Response was: {response[:200]}...")
            return None

    def deduplicate_events(self, events: List[Dict]) -> List[Dict]:
        """
        Remove duplicate events based on title and date.

        Deduplication is case-insensitive for titles. Events are considered
        duplicates if they have the same title (ignoring case) and date.

        Args:
            events: List of event dictionaries

        Returns:
            Deduplicated list of events maintaining original order
        """
        seen = set()
        unique_events = []

        for event in events:
            # Create key from title + date (case-insensitive)
            title = event.get('title', '').lower().strip()
            date = event.get('date', '')
            key = (title, date)

            if key not in seen:
                seen.add(key)
                unique_events.append(event)
            else:
                logger.debug(f"Skipping duplicate: {event.get('title', 'Unknown')}")

        return unique_events

    def filter_fresh_events(self, events: List[Dict]) -> List[Dict]:
        """
        Filter events to only include those within the configured time window.

        Removes events older than EventConfig.EVENT_EXPIRY_MONTHS. Events with
        invalid or missing dates are kept (assumed to be upcoming events).

        Args:
            events: List of event dictionaries with optional 'date' field in YYYY-MM-DD format

        Returns:
            Filtered list of fresh events (kept original order)

        Note:
            - Events without a date are kept (assumed upcoming)
            - Invalid dates trigger a warning but event is kept
        """
        cutoff_date = datetime.now() - timedelta(days=EventConfig.EVENT_EXPIRY_MONTHS * 30)
        fresh_events = []

        for event in events:
            try:
                date_str = event.get('date', '')
                if not date_str:
                    # No date = assume upcoming, keep it
                    fresh_events.append(event)
                    continue

                # Parse date
                event_date = datetime.strptime(date_str, '%Y-%m-%d')

                # Check if within time window
                if event_date >= cutoff_date:
                    fresh_events.append(event)
                else:
                    logger.debug(
                        f"Filtering old event (>{EventConfig.EVENT_EXPIRY_MONTHS} months): "
                        f"{event.get('title', 'Unknown')} ({date_str})"
                    )

            except ValueError:
                # Invalid date format, keep event
                logger.warning(f"Invalid date format for event '{event.get('title', 'Unknown')}': {date_str}")
                fresh_events.append(event)
            except Exception as e:
                logger.error(f"Error filtering event: {e}")
                fresh_events.append(event)

        return fresh_events

    def normalize_event_data(
        self,
        event_data: Dict,
        org_name: str,
        org_id: str,
        source_url: str,
        extractor_name: str
    ) -> Optional[Dict]:
        """
        Normalize event data to standard format.

        Converts raw event data from LLM into a standardized schema with
        fallbacks. If event URL is missing or invalid, uses source_url.

        Args:
            event_data: Raw event data dictionary from LLM with keys like 'title', 'url', 'date', etc.
            org_name: Human-readable organization/platform name
            org_id: Unique identifier for the organization/platform
            source_url: URL where the event was discovered
            extractor_name: Name of the extractor used (e.g., 'smart_finder', 'llm_extractor')

        Returns:
            Normalized event dictionary with standard schema or None if error occurs

        Example:
            >>> event = {"title": "Tech Talk", "date": "2025-01-15", "location": "NYC"}
            >>> norm = extractor.normalize_event_data(event, "Techqueria", "techqueria_001", "https://example.com", "llm_extractor")
            >>> norm['title'] == "Tech Talk"
            >>> norm['platform_id'] == "techqueria_001"
        """
        try:
            # Get event URL, fallback to source page
            event_url = event_data.get('url', '').strip()
            if not event_url or not event_url.startswith('http'):
                event_url = source_url

            return {
                'title': event_data.get('title', 'Untitled Event'),
                'url': event_url,
                'date': event_data.get('date', ''),
                'time': event_data.get('time', 'TBD'),
                'location': event_data.get('location', 'TBD'),
                'description': event_data.get('description', ''),
                'event_type': event_data.get('event_type', 'other'),
                'source': extractor_name,
                'org_name': org_name,
                'platform_id': org_id
            }
        except Exception as e:
            logger.warning(f"Error normalizing event data: {e}")
            return None

    def verify_url(self, url: str, timeout: int = 10) -> bool:
        """
        Verify that a URL is accessible.

        Attempts a HEAD request first, then falls back to GET if the server
        doesn't support HEAD requests. Returns True only if response status is 200.

        Args:
            url: URL to verify
            timeout: Request timeout in seconds (default: 10)

        Returns:
            True if HTTP 200 received, False for any errors or other status codes
        """
        try:
            response = self.session.head(url, timeout=timeout, allow_redirects=True)
            return response.status_code == 200
        except Exception:
            # Try GET if HEAD fails (some servers don't support HEAD)
            try:
                response = self.session.get(url, timeout=timeout, allow_redirects=True)
                return response.status_code == 200
            except Exception as e:
                logger.debug(f"URL verification failed for {url}: {e}")
                return False
