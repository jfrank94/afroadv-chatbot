"""
Smart Event Finder - LLM-powered agent for finding and verifying event URLs.

This agent uses Claude Haiku to:
1. Verify organization URLs are current
2. Search for event pages intelligently
3. Extract real event URLs from web content
4. Validate that URLs are accessible
"""

import logging
from typing import List, Dict, Optional
from datetime import datetime
import json
import time

import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load environment variables
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / '.env')

from src.infrastructure.llm import LLMProvider
from src.events.base_extractor import BaseLLMExtractor
from config import LLMTokenLimits, ContentLimits

logger = logging.getLogger(__name__)


class SmartEventFinder(BaseLLMExtractor):
    """LLM-powered agent that intelligently finds and verifies event URLs."""

    def __init__(self, use_web_search: bool = True):
        """
        Initialize the smart event finder.

        Args:
            use_web_search: If True, use Tavily web search for URL verification.
                           If False, use traditional URL verification only (free, but can't find rebrands).
        """
        llm_provider = LLMProvider()
        super().__init__(llm_provider)
        self.use_web_search = use_web_search

        # Initialize Tavily client if web search is enabled
        if self.use_web_search:
            try:
                from tavily import TavilyClient
                import os
                tavily_api_key = os.getenv('TAVILY_API_KEY')
                if tavily_api_key:
                    self.tavily_client = TavilyClient(api_key=tavily_api_key)
                    logger.info("Tavily client initialized for web search")
                else:
                    logger.warning("TAVILY_API_KEY not found, web search disabled")
                    self.use_web_search = False
                    self.tavily_client = None
            except ImportError:
                logger.warning("Tavily not installed, web search disabled")
                self.use_web_search = False
                self.tavily_client = None
        else:
            self.tavily_client = None

    def find_organization_url(self, org_name: str, old_url: Optional[str] = None, skip_search_if_valid: bool = True) -> str:
        """
        Use Tavily to find the current, correct URL for an organization.

        Args:
            org_name: Organization name
            old_url: Previously known URL (might be outdated)
            skip_search_if_valid: If True, skip web search if old URL is accessible (saves 2 credits)

        Returns:
            Current organization URL
        """
        # Cost optimization: If old URL is accessible, return it without web search
        if skip_search_if_valid and old_url:
            if self.verify_url(old_url):
                logger.info(f"URL verified for {org_name}: {old_url} (skipped web search)")
                return old_url
            else:
                logger.info(f"URL broken for {org_name}, using web search to find current URL")

        try:
            # Use Tavily for web search if enabled
            search_context = ""
            if self.use_web_search and self.tavily_client:
                try:
                    # Optimized search query with more context
                    search_query = f"{org_name} official website homepage"

                    # Optimized Tavily API call for maximum accuracy
                    search_results = self.tavily_client.search(
                        query=search_query,
                        max_results=5,  # Increased from 3 for better coverage
                        search_depth="advanced",  # 2 credits but higher accuracy
                        include_answer="basic",  # LLM validation of results
                        exclude_domains=[
                            # Exclude social media and aggregators
                            "facebook.com", "twitter.com", "linkedin.com",
                            "instagram.com", "youtube.com", "tiktok.com",
                            "medium.com", "substack.com",
                            # Exclude news/press coverage
                            "techcrunch.com", "forbes.com", "businessinsider.com",
                            "crunchbase.com", "wikipedia.org"
                        ]
                    )

                    # Build context from search results
                    if search_results.get('results'):
                        search_context = "\n\nWeb Search Results:\n"
                        for i, result in enumerate(search_results['results'][:5], 1):
                            search_context += f"{i}. {result['title']}\n"
                            search_context += f"   URL: {result['url']}\n"
                            search_context += f"   Content: {result['content'][:200]}...\n\n"

                        # Include Tavily's LLM answer if available
                        if search_results.get('answer'):
                            search_context += f"Tavily Analysis: {search_results['answer']}\n\n"

                        logger.info(f"Tavily advanced search found {len(search_results['results'])} results for {org_name}")
                except Exception as e:
                    logger.warning(f"Tavily search failed: {e}")
                    search_context = ""

            # Cacheable system instructions
            system_prompt = """You are a web research assistant specializing in finding current, official website URLs for organizations.

TASK: Return the current, official website URL for the organization provided.

IMPORTANT RULES:
- Organizations sometimes rebrand or change domains (e.g., blackgirlscode.com → wearebgc.org)
- Return ONLY the base URL (e.g., https://example.org)
- The URL must be the official, current website
- If you're not certain, acknowledge uncertainty

OUTPUT FORMAT (JSON only):
{
    "url": "https://example.org",
    "confidence": "high" or "medium" or "low",
    "notes": "Any relevant context about the URL"
}"""

            # Variable user content
            user_prompt = f"""Find the current official website URL for this organization:

Organization: {org_name}
{f'Previously known URL: {old_url}' if old_url else ''}
{search_context}

Return the result as JSON following the format specified."""

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]

            response = self.llm.generate(
                messages,
                max_tokens=LLMTokenLimits.URL_FINDER_MAX_TOKENS,
                temperature=0.1
            )

            # Parse response
            import re

            if not response:
                logger.warning(f"Empty response from LLM for {org_name}")
                return old_url or ''

            # Remove Claude's inline citation markers before extracting JSON
            # This includes: [1], [2], and emoji citations like 🔍1️⃣, 🔍2️⃣, etc.
            response = re.sub(r'\s*\[\d+\]', '', response)  # Remove [1], [2]
            response = re.sub(r'🔍\d+️⃣', '', response)  # Remove 🔍1️⃣, 🔍2️⃣
            response = re.sub(r'[🔍\d️⃣]+', '', response)  # Remove any remaining emoji citations
            logger.debug(f"After removing citations: {response}")

            # Extract JSON from markdown if present
            if '```' in response:
                # Find JSON block
                parts = response.split('```')
                for part in parts:
                    part = part.strip()
                    if part.startswith('json'):
                        part = part[4:].strip()
                    if part.startswith('{'):
                        response = part
                        break

            # Find JSON object in response
            json_start = response.find('{')
            if json_start == -1:
                logger.warning(f"No JSON object found in response for {org_name}")
                return old_url or ''

            # Find matching closing brace
            brace_count = 0
            json_end = -1
            for i in range(json_start, len(response)):
                if response[i] == '{':
                    brace_count += 1
                elif response[i] == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        json_end = i
                        break

            if json_end == -1:
                logger.warning(f"No complete JSON object found in response for {org_name}")
                return old_url or ''

            json_str = response[json_start:json_end+1]

            # Fix common JSON malformations from Claude's citations
            # Pattern: "key":  text without quotes
            # Fix: "key": "text"
            json_str = re.sub(r'("notes"\s*:\s*)([^"{].*?)(\s*[,}])', r'\1"\2"\3', json_str)

            logger.debug(f"Extracted JSON: {json_str}")

            data = json.loads(json_str)
            url = data.get('url', old_url or '')
            confidence = data.get('confidence', 'low')

            logger.info(f"Found URL for {org_name}: {url} (confidence: {confidence})")

            # Verify URL is accessible
            if url and self.verify_url(url):
                return url
            else:
                logger.warning(f"URL {url} is not accessible, falling back to old URL")
                return old_url or url or ''

        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Error parsing LLM response for {org_name}: {e}")
            return old_url or ''
        except Exception as e:
            logger.error(f"Unexpected error finding URL for {org_name}: {e}", exc_info=True)
            return old_url or ''

    def find_event_page_url(self, org_name: str, base_url: str) -> List[str]:
        """
        Use Tavily search to find where events are actually listed on the website.

        Args:
            org_name: Organization name
            base_url: Organization's base URL

        Returns:
            List of potential event page URLs
        """
        event_page_urls = []

        # Use Tavily to search for actual event pages if enabled
        if self.use_web_search and self.tavily_client:
            try:
                # Search for the organization's event/calendar pages
                search_query = f"{org_name} events calendar upcoming programs"

                logger.info(f"Searching for event pages: {search_query}")

                search_results = self.tavily_client.search(
                    query=search_query,
                    max_results=5,
                    search_depth="advanced",  # 2 credits but finds actual event pages
                    include_answer="basic",  # LLM helps identify best pages
                    exclude_domains=[
                        # Exclude social media event pages
                        "facebook.com", "twitter.com", "linkedin.com",
                        "instagram.com", "youtube.com", "tiktok.com",
                        # Exclude generic event aggregators (we want org's own page)
                        "eventbrite.com", "meetup.com", "lu.ma",
                        # Exclude news/press coverage of events
                        "medium.com", "techcrunch.com", "forbes.com",
                        "businessinsider.com", "crunchbase.com", "wikipedia.org"
                    ]
                )

                # Extract URLs from search results
                if search_results.get('results'):
                    for result in search_results['results']:
                        url = result.get('url', '')
                        if url and base_url in url:  # Only use URLs from the org's domain
                            event_page_urls.append(url)
                            logger.info(f"  Found event page: {url}")

                logger.info(f"Tavily found {len(event_page_urls)} event page(s) for {org_name}")

            except Exception as e:
                logger.warning(f"Tavily search for event pages failed: {e}")

        # Fallback: Add common URL patterns if Tavily didn't find anything
        if not event_page_urls:
            logger.info(f"No event pages found via search, trying common patterns...")
            common_patterns = [
                f"{base_url}/events",
                f"{base_url}/calendar",
                f"{base_url}/programs",
                f"{base_url}/get-involved",
                f"{base_url}/community/events",
            ]
            event_page_urls = common_patterns

        return event_page_urls[:5]  # Limit to 5 URLs

    def extract_events_from_page(self, page_url: str, org_name: str, org_id: str) -> List[Dict]:
        """
        Fetch page content and use LLM to extract event information with URLs.

        Args:
            page_url: URL of the page to extract events from
            org_name: Organization name
            org_id: Organization ID

        Returns:
            List of events with verified URLs
        """
        result = self.fetch_and_parse_page(page_url)
        if not result:
            return []

        text_content, soup = result

        # Extract all links from the page for event URLs
        all_links = self.extract_links_from_soup(soup, page_url)

        # Use LLM to extract events
        events = self._llm_extract_events(text_content, all_links, org_name, org_id, page_url)

        return events

    def _llm_extract_events(
        self,
        content: str,
        links: List[str],
        org_name: str,
        org_id: str,
        source_url: str
    ) -> List[Dict]:
        """
        Use LLM to intelligently extract event information and match to URLs.

        Args:
            content: Page text content
            links: All links found on the page
            org_name: Organization name
            org_id: Organization ID
            source_url: URL of the source page

        Returns:
            List of extracted events
        """
        # Create a truncated links list for the prompt
        links_text = "\n".join(f"- {link}" for link in links[:ContentLimits.MAX_LINKS_TO_PROCESS])

        # Cacheable system instructions (NO dynamic content - reused across all calls)
        system_prompt = """You are an event extraction expert. Your task is to extract upcoming events from web page content and match them to specific event URLs.

EXTRACTION RULES:
1. Find all upcoming events mentioned in the content
2. For each event, try to identify the specific event URL from the provided links list
3. Look for links that contain event-related paths like /event/, /events/, /calendar/, etc.
4. Match event titles/dates to corresponding URLs when possible
5. Only extract events from the FUTURE or past 12 months (current date will be provided)

OUTPUT FORMAT (JSON array only):
[
  {
    "title": "Event Title",
    "date": "YYYY-MM-DD",
    "time": "HH:MM AM/PM" or "TBD",
    "location": "City, State" or "Virtual" or "TBD",
    "description": "Brief description",
    "event_type": "conference" or "workshop" or "meetup" or "webinar" or "other",
    "url": "https://specific-event-url.com" or ""
  }
]

KEY GUIDELINES:
- Match events to specific URLs when possible
- If no specific URL found, leave url as empty string
- Only include future events or events from past 12 months
- Return [] if no events found
- Return valid JSON only (no markdown, no explanations)"""

        # Variable user content (changes for each page)
        user_prompt = f"""Extract events from the following page:

Organization: {org_name}
Source Page: {source_url}
Current Date: {datetime.now().strftime('%Y-%m-%d')}

PAGE CONTENT:
{content}

AVAILABLE LINKS ON PAGE:
{links_text}

Return events as JSON array following the specified format."""

        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
            response = self.llm.generate(messages, max_tokens=LLMTokenLimits.EVENT_EXTRACTOR_MAX_TOKENS, temperature=0.2)

            events_data = self.parse_llm_json_response(response)
            if not events_data:
                return []

            # Normalize and filter events
            events = []
            for event_data in events_data:
                event = self.normalize_event_data(event_data, org_name, org_id, source_url, 'smart_finder')
                if event:
                    events.append(event)

            # Filter old events
            events = self.filter_fresh_events(events)

            logger.info(f"Extracted {len(events)} events from {source_url}")
            return events

        except Exception as e:
            logger.error(f"Error in LLM extraction: {e}")
            return []

    def find_events_for_organization(
        self,
        org_name: str,
        org_id: str,
        current_url: Optional[str] = None
    ) -> Dict:
        """
        Complete pipeline: Find organization URL, find event pages, extract events.

        Args:
            org_name: Organization name
            org_id: Organization ID
            current_url: Currently known URL (might be outdated)

        Returns:
            Dictionary with updated URL and list of events
        """
        logger.info(f"\n{'='*70}")
        logger.info(f"SMART EVENT FINDER: {org_name}")
        logger.info(f"{'='*70}")

        # Step 1: Verify/find current organization URL
        logger.info("Step 1: Finding current organization URL...")
        base_url = self.find_organization_url(org_name, current_url)

        if not base_url:
            logger.warning(f"Could not find URL for {org_name}")
            return {'url': current_url or '', 'events': []}

        # Step 2: Find potential event page URLs
        logger.info("Step 2: Finding event page URLs...")
        event_page_urls = self.find_event_page_url(org_name, base_url)

        # Step 3: Try each event page URL and extract events
        logger.info("Step 3: Extracting events from event pages...")
        all_events = []

        for event_url in event_page_urls:
            # Verify URL is accessible before trying to extract
            if not self.verify_url(event_url):
                logger.debug(f"Skipping inaccessible URL: {event_url}")
                continue

            logger.info(f"Trying: {event_url}")
            events = self.extract_events_from_page(event_url, org_name, org_id)

            if events:
                all_events.extend(events)
                logger.info(f"✓ Found {len(events)} events from {event_url}")

            # Rate limiting
            time.sleep(1)

        # Deduplicate events by title and date
        unique_events = self.deduplicate_events(all_events)

        logger.info(f"\n{'='*70}")
        logger.info(f"RESULTS: {org_name}")
        logger.info(f"  Updated URL: {base_url}")
        logger.info(f"  Total events found: {len(unique_events)}")
        logger.info(f"{'='*70}\n")

        return {
            'url': base_url,
            'events': unique_events
        }



if __name__ == '__main__':
    # Test the smart event finder
    logging.basicConfig(level=logging.INFO)

    finder = SmartEventFinder()

    # Test with Black Girls CODE (old URL vs new URL)
    result = finder.find_events_for_organization(
        org_name="Black Girls CODE",
        org_id="test_bgc",
        current_url="https://www.blackgirlscode.com"
    )

    print("\n" + "="*70)
    print("TEST RESULTS")
    print("="*70)
    print(f"Updated URL: {result['url']}")
    print(f"Events found: {len(result['events'])}")
    for i, event in enumerate(result['events'][:3], 1):
        print(f"\n{i}. {event['title']}")
        print(f"   Date: {event.get('date', 'TBD')}")
        print(f"   URL: {event['url']}")
