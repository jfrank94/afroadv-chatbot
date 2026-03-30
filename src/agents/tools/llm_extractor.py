"""Structured field extraction from search results using Claude Haiku + instructor."""

import logging
from typing import Optional, Literal
from pydantic import BaseModel, Field
import instructor
from anthropic import Anthropic
import config

logger = logging.getLogger(__name__)

# Lazy-initialized instructor client (shared across calls)
_client: Optional[instructor.Instructor] = None


def _get_client() -> instructor.Instructor:
    global _client
    if _client is None:
        _client = instructor.from_anthropic(Anthropic(api_key=config.ANTHROPIC_API_KEY))
    return _client


class PlatformUpdate(BaseModel):
    """Fields that the enrichment agent can update for a platform.

    Only fields where the agent found clear evidence are populated.
    Fields with no evidence are left as None so the merger can skip them.
    """
    community_size: Optional[str] = Field(
        None,
        description="Current member/follower count as a human-readable string, e.g. '40,000+ members'. Null if not found.",
    )
    states: list[str] = Field(
        default_factory=list,
        description=(
            "US state abbreviations (e.g. CA, TX) where the platform has confirmed "
            "chapters or active in-person presence. Empty list if none found or global/virtual only."
        ),
    )
    still_active: bool = Field(
        True,
        description="False only if search results clearly indicate the platform is defunct or inactive.",
    )
    confidence: Literal["high", "medium", "low"] = Field(
        "low",
        description="high = directly stated in results, medium = implied, low = guessed or no evidence.",
    )
    needs_review: bool = Field(
        False,
        description="True if any extracted data is uncertain, contradictory, or the agent is unsure.",
    )
    notes: Optional[str] = Field(
        None,
        description="Brief note for human reviewers about what was found or why needs_review is True.",
    )


_SYSTEM_PROMPT = (
    "You extract factual information about PoC community platforms from web search results. "
    "Rules:\n"
    "- Only extract what is clearly stated in the search results. Do NOT guess or infer.\n"
    "- For states: only include abbreviations (CA, TX, NY, etc.) where the platform has "
    "confirmed physical chapters or in-person events. Do not include states just because "
    "members live there.\n"
    "- For community_size: use the exact phrasing from the source (e.g. '19,000+ members').\n"
    "- Set confidence='high' only if the data is directly and clearly stated.\n"
    "- Set needs_review=True if results are contradictory, outdated, or you are uncertain.\n"
    "- Leave fields null/empty if you cannot find clear evidence — do not fill in blanks."
)


def extract_updates(platform_name: str, search_results: list[dict]) -> PlatformUpdate:
    """Extract structured platform field updates from web search results.

    Args:
        platform_name: Name of the platform being enriched
        search_results: List of Tavily result dicts (title, url, content)

    Returns:
        PlatformUpdate with fields populated only where evidence was found.
        Returns a low-confidence needs_review record if search_results is empty.
    """
    if not search_results:
        return PlatformUpdate(
            confidence="low",
            needs_review=True,
            notes="No search results returned — manual review required.",
        )

    # Concatenate top-3 results into a single context block
    context = "\n\n".join(
        f"[{r.get('title', 'No title')}]\n{r.get('content', '')}"
        for r in search_results[:3]
    )

    logger.debug(f"Extracting updates for '{platform_name}' from {len(search_results)} results")

    return _get_client().messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=512,
        max_retries=2,  # instructor auto-retries on schema validation failure
        system=_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": (
                f"Platform: {platform_name}\n\n"
                f"Search results:\n{context}\n\n"
                "Extract any updated information you can verify from the above."
            ),
        }],
        response_model=PlatformUpdate,
    )
