"""Web search tool using Tavily API with retry logic."""

import logging
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import config

logger = logging.getLogger(__name__)

# Domains that rarely contain useful platform info
_EXCLUDED_DOMAINS = [
    "medium.com", "wikipedia.org", "crunchbase.com",
    "bloomberg.com", "forbes.com", "techcrunch.com",
]


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type(httpx.HTTPStatusError),
    reraise=True,
)
def search(query: str, max_results: int = 3) -> list[dict]:
    """Search for information using Tavily API.

    Args:
        query: Search query string
        max_results: Number of results to return (uses basic depth to conserve credits)

    Returns:
        List of result dicts with 'title', 'url', and 'content' keys.
        Returns empty list if TAVILY_API_KEY is not set.
    """
    if not config.TAVILY_API_KEY:
        logger.warning("TAVILY_API_KEY not configured — skipping web search")
        return []

    with httpx.Client(timeout=15.0) as client:
        response = client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": config.TAVILY_API_KEY,
                "query": query,
                "search_depth": "basic",  # 1 credit vs 2 for advanced
                "max_results": max_results,
                "exclude_domains": _EXCLUDED_DOMAINS,
            },
        )
        response.raise_for_status()
        return response.json().get("results", [])


def search_platform_info(platform_name: str, platform_type: str) -> list[dict]:
    """Search for current info about a specific platform.

    Args:
        platform_name: Name of the platform (e.g. "Outdoor Afro")
        platform_type: "Tech" or "Outdoor/Travel" — used to sharpen the query

    Returns:
        List of search result dicts
    """
    category = "tech community" if platform_type == "Tech" else "outdoor travel community"
    query = f'"{platform_name}" {category} 2026 members chapters'
    logger.info(f"Searching: {query}")
    return search(query, max_results=3)
