"""URL utility functions used across the codebase."""


def normalize_url(url: str) -> str:
    """Normalize a URL for comparison by stripping protocol, www, and trailing slash.

    Args:
        url: URL string to normalize

    Returns:
        Lowercase URL with protocol, www prefix, and trailing slash removed.
        Returns empty string if url is falsy.

    Example:
        >>> normalize_url("https://www.outdoorafro.org/")
        'outdoorafro.org'
    """
    if not url:
        return ""
    normalized = url.lower()
    normalized = normalized.replace("https://", "").replace("http://", "")
    normalized = normalized.replace("www.", "")
    return normalized.rstrip("/")


def is_homepage_url(event_url: str, org_homepage: str) -> bool:
    """Return True if event_url is exactly the organization homepage (no sub-path).

    Used to avoid linking event entries directly to a base website when no
    specific event page was found.

    Args:
        event_url: URL of the event (may be a deep link or just the homepage)
        org_homepage: Known homepage URL of the organization

    Returns:
        True if event_url normalizes to the same value as org_homepage.
    """
    if not org_homepage:
        return False
    return normalize_url(event_url) == normalize_url(org_homepage)
