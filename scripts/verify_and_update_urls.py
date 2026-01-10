"""
URL Verification and Update Agent

Verifies and updates platform URLs in platforms.json to ensure they're current.
Handles:
- Redirects (e.g., nomadnesstribe.com → nomadnesstraveltribe.com)
- Rebrands
- Domain changes
- Dead links

Preserves all other platform metadata (descriptions, focus areas, etc.).
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import json
import logging
import argparse
import requests
from urllib.parse import urlparse
from typing import Dict, List, Optional
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from src.infrastructure.llm import LLMProvider

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class URLVerifier:
    """Verifies and updates platform URLs."""

    def __init__(self, llm: Optional[LLMProvider] = None):
        """
        Initialize URL verifier.

        Args:
            llm: LLMProvider instance for intelligent URL discovery
        """
        self.llm = llm or LLMProvider()
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })

    def check_url(self, url: str, timeout: int = 10) -> Dict:
        """
        Check if URL is accessible and get final URL after redirects.

        Args:
            url: URL to check
            timeout: Request timeout in seconds

        Returns:
            Dictionary with status, final_url, and redirect info
        """
        try:
            # Ensure URL has scheme
            if not url.startswith(('http://', 'https://')):
                url = f"https://{url}"

            logger.debug(f"Checking URL: {url}")

            # Make request with redirects
            response = self.session.get(url, timeout=timeout, allow_redirects=True)

            final_url = response.url
            was_redirected = final_url != url

            result = {
                'status': 'success',
                'accessible': True,
                'status_code': response.status_code,
                'original_url': url,
                'final_url': final_url,
                'was_redirected': was_redirected,
                'redirect_chain': [r.url for r in response.history] if was_redirected else []
            }

            if response.status_code >= 400:
                result['accessible'] = False
                result['status'] = 'error'
                result['error'] = f"HTTP {response.status_code}"

            return result

        except requests.exceptions.SSLError as e:
            # Try HTTP if HTTPS fails
            if url.startswith('https://'):
                logger.warning(f"SSL error for {url}, trying HTTP...")
                return self.check_url(url.replace('https://', 'http://'), timeout)
            return {
                'status': 'error',
                'accessible': False,
                'original_url': url,
                'error': f"SSL Error: {str(e)}"
            }

        except requests.exceptions.Timeout:
            return {
                'status': 'error',
                'accessible': False,
                'original_url': url,
                'error': "Timeout"
            }

        except requests.exceptions.ConnectionError as e:
            return {
                'status': 'error',
                'accessible': False,
                'original_url': url,
                'error': f"Connection Error: {str(e)}"
            }

        except Exception as e:
            return {
                'status': 'error',
                'accessible': False,
                'original_url': url,
                'error': str(e)
            }

    def is_likely_official_site(self, url: str) -> bool:
        """
        Check if URL pattern suggests it's an official site (not a news article).

        Args:
            url: URL to check

        Returns:
            True if URL looks like an official site
        """
        url_lower = url.lower()
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        path = parsed.path.lower().strip('/')

        # Exclude news/article/product listing patterns
        exclude_patterns = [
            '/news/', '/blog/', '/article/', '/press/', '/story/', '/post/',
            '/20\d{2}/',  # Year patterns like /2024/
            '/featured/', '/spotlight/', '/interview/', '/profile/',
            '/product/', '/item/', '/collection/',  # E-commerce
            'medium.com', 'techcrunch.com', 'forbes.com', 'theverge.com',
            'businessinsider.com', 'cnbc.com', 'bloomberg.com',
            'kpopusaonline.com', 'etsy.com', 'amazon.com',  # E-commerce sites
        ]

        if any(pattern in url_lower for pattern in exclude_patterns):
            logger.debug(f"URL appears to be news/article/product: {url}")
            return False

        # E-commerce/marketplace domains are never official org sites
        ecommerce_domains = [
            'shop', 'store', 'market', 'buy', 'sell', 'cart', 'checkout',
            'kpop', 'merch', 'apparel', 'clothing'
        ]
        if any(keyword in domain for keyword in ecommerce_domains):
            logger.debug(f"URL appears to be e-commerce/marketplace: {url}")
            return False

        # Prefer root domain or standard organizational pages
        if not path or path in ['about', 'home', 'contact', 'index.html', 'index.php', 'about-us', 'who-we-are']:
            return True

        # If path contains words like "featured", "organization", it's likely ABOUT the org, not BY the org
        if any(word in path for word in ['featured', 'spotlight', 'organization', 'profile', 'directory']):
            logger.debug(f"URL appears to be about/featuring the org, not official site: {url}")
            return False

        # Short, simple paths are okay (e.g., /services, /programs)
        # But reject if path is too descriptive (article-like)
        if path.count('/') == 0:  # Single-level path only
            # Check if path is unusually long (articles have descriptive URLs)
            if len(path) > 50:  # e.g., "wild-diversity-featured-outdoor-diversity-organization"
                logger.debug(f"URL path too long/descriptive (article-like): {url}")
                return False
            return True

        logger.debug(f"URL has nested path (likely not official): {url}")
        return False

    def verify_page_content(self, url: str, platform_name: str, allow_partial: bool = False) -> bool:
        """
        Fetch and verify that the page content matches the organization.

        Args:
            url: URL to verify
            platform_name: Name of the platform to match
            allow_partial: If True, accept partial word matches (for rebranded orgs)

        Returns:
            True if page content confirms it's the right organization
        """
        try:
            # Fetch page content
            response = self.session.get(url, timeout=10)
            if response.status_code != 200:
                return False

            # Extract only visible text content (not CSS/JavaScript)
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(response.text, 'html.parser')

                # Remove script and style elements
                for script in soup(["script", "style", "noscript"]):
                    script.decompose()

                # Get text content
                page_text = soup.get_text(separator=' ', strip=True).lower()
            except Exception:
                # Fallback to raw text if BeautifulSoup fails
                page_text = response.text.lower()

            platform_lower = platform_name.lower()

            # Method 1: Check if the exact platform name appears on the page
            # (allows for minor variations like punctuation)
            import re
            # Escape special regex characters but allow word boundaries
            platform_pattern = re.escape(platform_lower)
            platform_pattern = platform_pattern.replace(r'\ ', r'\s+')  # Allow multiple spaces/whitespace

            if re.search(platform_pattern, page_text):
                logger.debug(f"Page content verified: Exact name '{platform_name}' found on page")
                return True

            # Method 2: Check for very close variations (e.g., with/without punctuation)
            # Remove common words and check if remaining distinctive words appear together
            common_words = {'the', 'a', 'an', 'of', 'for', 'and', 'in', 'to', 'with', 'on', 'at'}
            distinctive_words = [
                word for word in platform_lower.split()
                if len(word) > 3 and word not in common_words
            ]

            if len(distinctive_words) >= 2:
                if allow_partial:
                    # For partial matching (rebrands), check if most distinctive words appear anywhere
                    # This handles cases like "Color Outside" → "Color My Outdoors"
                    words_found = sum(1 for word in distinctive_words if word in page_text)
                    match_ratio = words_found / len(distinctive_words)

                    if match_ratio >= 0.5:  # At least 50% of distinctive words
                        logger.debug(f"Page content verified (partial): {words_found}/{len(distinctive_words)} distinctive words found")
                        return True
                else:
                    # For exact matching, require words to appear close together
                    for i, word1 in enumerate(distinctive_words[:-1]):
                        word2 = distinctive_words[i + 1]
                        # Find positions of both words
                        word1_positions = [m.start() for m in re.finditer(r'\b' + re.escape(word1) + r'\b', page_text)]
                        word2_positions = [m.start() for m in re.finditer(r'\b' + re.escape(word2) + r'\b', page_text)]

                        # Check if any pair is within 100 characters
                        for pos1 in word1_positions:
                            for pos2 in word2_positions:
                                if abs(pos1 - pos2) < 100:
                                    logger.debug(f"Page content verified: '{word1}' and '{word2}' found close together")
                                    return True

            # If neither method works, fail verification
            logger.debug(f"Page content mismatch: '{platform_name}' not found on page")
            return False

        except Exception as e:
            logger.debug(f"Page content verification failed: {e}")
            return False

    def find_correct_url_with_search(self, platform_name: str, old_url: str, error: str, platform_data: Optional[Dict] = None) -> Optional[str]:
        """
        Use Tavily web search to find the correct current URL for a platform.
        Handles organization rebrands by searching with broader context.

        Args:
            platform_name: Name of the platform
            old_url: Previous/broken URL
            error: Error message from URL check
            platform_data: Full platform data (for context like focus_area, description)

        Returns:
            Updated URL or None if not found
        """
        tavily_api_key = os.getenv("TAVILY_API_KEY")

        if not tavily_api_key:
            logger.warning("TAVILY_API_KEY not set, cannot search for new URL")
            return None

        try:
            # Extract old domain for validation
            from urllib.parse import urlparse
            old_domain = urlparse(old_url if '://' in old_url else f'https://{old_url}').netloc
            # Get core domain (remove www., remove subdomains for matching)
            old_core = old_domain.replace('www.', '').split('.')[0] if old_domain else ""

            # Strategy 1: Search for exact organization name
            search_query = f'"{platform_name}" official website'
            logger.info(f"Search strategy 1: Exact name - {search_query}")

            result, confidence, has_domain_match = self._search_and_verify(search_query, platform_name, old_core, return_confidence=True, return_domain_match=True)
            # Only accept results with actual domain similarity
            # (not just URL pattern/position bonuses)
            if result and has_domain_match:
                logger.info(f"Strategy 1 found result with domain match (score: {confidence})")
                return result
            elif result:
                logger.info(f"Strategy 1 found result WITHOUT domain match (score: {confidence}), trying broader search...")
                best_result = (result, confidence, has_domain_match)  # Save as fallback
            else:
                best_result = (None, 0, False)

            # Strategy 2: If exact name fails and we have platform context, search more broadly
            if platform_data:
                # Build broader search from platform focus and type
                focus = platform_data.get('focus_area', '')
                platform_type = platform_data.get('type', '')

                # Determine category context
                if 'tech' in focus.lower() or platform_type == 'Tech':
                    category_context = 'people of color tech community'
                elif 'outdoor' in focus.lower() or 'travel' in focus.lower() or platform_type == 'Outdoor/Travel':
                    category_context = 'people of color outdoor community'
                else:
                    category_context = 'people of color community'

                # Extract key distinctive words from platform name
                key_words = [word for word in platform_name.lower().split() if len(word) > 3]
                if key_words:
                    # Search with key words + category context
                    search_query = f'{" ".join(key_words[:3])} {category_context} official website'
                    logger.info(f"Search strategy 2: Broader context - {search_query}")

                    result, confidence, has_domain_match = self._search_and_verify(search_query, platform_name, old_core, allow_partial_match=True, return_confidence=True, return_domain_match=True)
                    if result and confidence > best_result[1]:
                        best_result = (result, confidence, has_domain_match)
                        # If we found domain match, return immediately
                        if has_domain_match:
                            logger.info(f"Strategy 2 found domain match (score: {confidence})")
                            return result

            # Strategy 3: Last resort - search with old domain keywords + category
            if old_core and platform_data:
                platform_type = platform_data.get('type', '')
                category = 'tech' if platform_type == 'Tech' else 'outdoor'
                search_query = f'{old_core} people of color {category} community official website'
                logger.info(f"Search strategy 3: Old domain + category - {search_query}")

                result, confidence, has_domain_match = self._search_and_verify(search_query, platform_name, old_core, allow_partial_match=True, return_confidence=True, return_domain_match=True)
                if result and confidence > best_result[1]:
                    best_result = (result, confidence, has_domain_match)

            # Return the best result found across all strategies
            if best_result[0]:
                logger.info(f"Returning best result across all strategies (confidence: {best_result[1]}, domain_match: {best_result[2]})")
                return best_result[0]

            return None

        except Exception as e:
            logger.error(f"Web search URL discovery failed: {e}")
            return None

    def _search_and_verify(self, search_query: str, platform_name: str, old_core: str, allow_partial_match: bool = False, return_confidence: bool = False, return_domain_match: bool = False):
        """
        Execute search query and verify results.

        Args:
            search_query: Search query to execute
            platform_name: Original platform name for verification
            old_core: Core of old domain for similarity scoring
            allow_partial_match: If True, accept partial name matches in content verification
            return_confidence: If True, return (url, confidence_score) tuple
            return_domain_match: If True, return (url, confidence, has_domain_match) tuple

        Returns:
            Verified URL or None (or tuple if return_confidence/return_domain_match=True)
        """
        tavily_api_key = os.getenv("TAVILY_API_KEY")

        try:

            response = requests.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": tavily_api_key,
                    "query": search_query,
                    "search_depth": "advanced",  # 2 credits but higher accuracy for URL verification
                    "max_results": 7,  # Increased from 5 for better coverage
                    "include_answer": "basic",  # LLM validation of results
                    "exclude_domains": [
                        # Exclude social media (we penalize these separately)
                        # "facebook.com", "twitter.com", "x.com", "instagram.com", "linkedin.com",
                        # Exclude news/article sites
                        "medium.com", "techcrunch.com", "forbes.com", "theverge.com",
                        "businessinsider.com", "cnbc.com", "bloomberg.com", "wired.com",
                        "crunchbase.com", "wikipedia.org"
                    ]
                },
                timeout=15
            )
            response.raise_for_status()

            results = response.json().get("results", [])

            # Try each result, prefer URLs with similar domain
            candidates = []
            for idx, result in enumerate(results):
                candidate_url = result.get("url", "")
                if not candidate_url:
                    continue

                # Check if it's a social media URL
                is_social_media = any(
                    social in candidate_url.lower()
                    for social in ['facebook.com', 'twitter.com', 'x.com', 'instagram.com', 'linkedin.com']
                )

                # Check if URL pattern looks like official site
                looks_official = self.is_likely_official_site(candidate_url)

                # Extract candidate domain
                candidate_domain = urlparse(candidate_url).netloc
                candidate_core = candidate_domain.replace('www.', '').split('.')[0] if candidate_domain else ""

                # Remove hyphens for comparison (e.g., "natives-outdoors" vs "nativesoutdoors")
                old_core_normalized = old_core.replace('-', '').replace('_', '').lower() if old_core else ""
                candidate_core_normalized = candidate_core.replace('-', '').replace('_', '').lower() if candidate_core else ""

                # Enhanced multi-signal scoring system
                score = 0
                domain_similarity_score = 0

                # Signal 1: Domain similarity (strongest signal)
                if old_core_normalized and candidate_core_normalized:
                    if old_core_normalized == candidate_core_normalized:
                        domain_similarity_score = 10  # Exact match
                        score += 10
                    elif old_core_normalized in candidate_core_normalized or candidate_core_normalized in old_core_normalized:
                        domain_similarity_score = 5  # Partial match
                        score += 5

                # Signal 2: URL pattern analysis
                if looks_official:
                    score += 5
                else:
                    score -= 5  # Strong penalty for article-like URLs

                # Signal 3: Search result position (earlier = more relevant)
                position_score = 5 - idx  # Top result gets +5, 5th gets +1
                score += max(0, position_score)

                # Signal 4: Title and content relevance
                title = result.get("title", "").lower()
                snippet = result.get("content", "").lower()
                platform_lower = platform_name.lower()

                if platform_lower in title:
                    score += 3
                if "official" in title or "official" in snippet:
                    score += 2

                # Signal 5: Social media penalty
                if is_social_media:
                    score -= 5  # Strong penalty for social media

                has_domain_match = domain_similarity_score > 0
                candidates.append((candidate_url, score, is_social_media, looks_official, has_domain_match))

            # Sort by score (highest first)
            candidates.sort(key=lambda x: x[1], reverse=True)

            # Log all candidates for debugging
            logger.debug(f"Found {len(candidates)} candidates, scores: {[(c[0], c[1], c[4]) for c in candidates[:3]]}")

            # Try candidates in order of score
            for candidate_url, score, is_social_media, looks_official, has_domain_match in candidates:
                # Strict minimum score threshold
                # Require score >= 5 if we have any candidates with score >= 5
                min_threshold = 5 if any(s >= 5 for _, s, _, _, _ in candidates) else 2

                if score < min_threshold:
                    logger.debug(f"Skipping low-score candidate: {candidate_url} (score: {score} < {min_threshold})")
                    continue

                # Verify the URL works
                check_result = self.check_url(candidate_url)
                if check_result['accessible']:
                    # CRITICAL: Verify page content matches the organization
                    logger.info(f"Verifying page content for: {candidate_url} (score: {score}, domain_match: {has_domain_match})")
                    content_verified = self.verify_page_content(
                        check_result['final_url'],
                        platform_name,
                        allow_partial=allow_partial_match
                    )

                    if not content_verified:
                        logger.warning(f"⚠️  Page content doesn't match '{platform_name}' - skipping")
                        continue

                    # Warn if no domain match
                    if not has_domain_match:
                        logger.warning(f"⚠️  No domain similarity (score: {score}): {candidate_url}")
                        logger.warning(f"⚠️  Please manually verify this is the correct organization!")

                    site_type = "social media" if is_social_media else "official site" if looks_official else "other"
                    logger.info(f"✓ Search found working URL: {candidate_url} (score: {score}, {site_type}, content verified)")

                    if return_confidence and return_domain_match:
                        return (check_result['final_url'], score, has_domain_match)
                    elif return_confidence:
                        return (check_result['final_url'], score)
                    return check_result['final_url']

            if return_confidence and return_domain_match:
                return (None, 0, False)
            elif return_confidence:
                return (None, 0)
            return None

        except Exception as e:
            logger.error(f"Web search URL discovery failed: {e}")
            if return_confidence and return_domain_match:
                return (None, 0, False)
            elif return_confidence:
                return (None, 0)
            return None

    def normalize_url(self, url: str) -> str:
        """
        Normalize URL to standard format.

        Args:
            url: URL to normalize

        Returns:
            Normalized URL
        """
        # Ensure scheme
        if not url.startswith(('http://', 'https://')):
            url = f"https://{url}"

        # Remove trailing slash
        url = url.rstrip('/')

        # Prefer https
        if url.startswith('http://'):
            url = url.replace('http://', 'https://')

        return url


def verify_and_update_platforms(
    platforms_file: Path,
    dry_run: bool = False,
    use_llm_fallback: bool = True
) -> Dict:
    """
    Verify and update all platform URLs.

    Args:
        platforms_file: Path to platforms.json
        dry_run: If True, don't write changes to file
        use_llm_fallback: Use LLM to find URLs for broken links

    Returns:
        Dictionary with verification results
    """
    logger.info(f"Loading platforms from {platforms_file}")

    # Load platforms
    with open(platforms_file, 'r', encoding='utf-8') as f:
        platforms = json.load(f)

    logger.info(f"Loaded {len(platforms)} platforms")

    # Initialize verifier
    verifier = URLVerifier()

    # Track results
    results = {
        'total': len(platforms),
        'accessible': 0,
        'redirected': 0,
        'broken': 0,
        'updated': 0,
        'removed': 0,
        'changes': [],
        'platforms_to_remove': []  # Track platforms with no valid URL found
    }

    # Verify each platform
    for i, platform in enumerate(platforms, 1):
        platform_name = platform.get('name', 'Unknown')
        original_url = platform.get('website', '')

        logger.info(f"\n[{i}/{len(platforms)}] Checking {platform_name}...")
        logger.info(f"  URL: {original_url}")

        if not original_url:
            logger.warning("  ⚠️  No URL found, skipping")
            results['broken'] += 1
            continue

        # Check URL
        check_result = verifier.check_url(original_url)

        if check_result['accessible']:
            results['accessible'] += 1

            # Check if redirected
            if check_result['was_redirected']:
                final_url = verifier.normalize_url(check_result['final_url'])
                normalized_original = verifier.normalize_url(original_url)

                # Only update if URLs are different after normalization
                if final_url != normalized_original:
                    results['redirected'] += 1
                    logger.info(f"  🔀 Redirected: {original_url} → {final_url}")

                    # Update URL
                    platform['website'] = final_url
                    results['updated'] += 1
                    results['changes'].append({
                        'platform': platform_name,
                        'old_url': original_url,
                        'new_url': final_url,
                        'reason': 'redirect'
                    })
                else:
                    logger.info(f"  ✓ Accessible (redirect but same domain)")
            else:
                logger.info(f"  ✓ Accessible")

        else:
            results['broken'] += 1
            logger.warning(f"  ❌ Not accessible: {check_result.get('error', 'Unknown error')}")

            # Try to find correct URL with web search
            if use_llm_fallback:
                logger.info("  🔍 Searching for correct URL with web search...")
                new_url = verifier.find_correct_url_with_search(
                    platform_name,
                    original_url,
                    check_result.get('error', 'Not accessible'),
                    platform_data=platform  # Pass full platform data for context
                )

                if new_url:
                    # Check if it's just a social media fallback (not a real website)
                    is_social_media = any(
                        social in new_url.lower()
                        for social in ['facebook.com', 'twitter.com', 'x.com', 'instagram.com', 'linkedin.com']
                    )

                    if is_social_media:
                        logger.warning(f"  ⚠️  Only social media found: {new_url}")
                        logger.warning(f"  🗑️  Marking for removal (no official website exists)")
                        results['platforms_to_remove'].append({
                            'platform': platform_name,
                            'reason': 'No official website, only social media',
                            'social_media': new_url
                        })
                        results['removed'] += 1
                    else:
                        logger.info(f"  ✓ Found new URL: {new_url}")
                        platform['website'] = new_url
                        results['updated'] += 1
                        results['changes'].append({
                            'platform': platform_name,
                            'old_url': original_url,
                            'new_url': new_url,
                            'reason': 'web_search_discovery'
                        })
                else:
                    logger.warning(f"  ⚠️  Could not find new URL")
                    logger.warning(f"  🗑️  Marking for removal (organization may no longer exist)")
                    results['platforms_to_remove'].append({
                        'platform': platform_name,
                        'reason': 'No URL found, organization may no longer exist',
                        'old_url': original_url
                    })
                    results['removed'] += 1

    # Remove platforms with no valid URL if not dry run
    if not dry_run and results['removed'] > 0:
        logger.info(f"\n🗑️  Removing {results['removed']} platforms with no valid URL...")
        platforms_to_keep = [
            p for p in platforms
            if p.get('name') not in [r['platform'] for r in results['platforms_to_remove']]
        ]
        platforms = platforms_to_keep
        logger.info(f"  ✓ {len(platforms)} platforms remaining")

    # Write updated platforms if not dry run
    if not dry_run and (results['updated'] > 0 or results['removed'] > 0):
        logger.info(f"\n💾 Writing changes to {platforms_file}")

        # Backup original file
        backup_file = platforms_file.with_suffix('.json.backup')
        with open(platforms_file, 'w', encoding='utf-8') as f:
            json.dump(platforms, f, indent=2, ensure_ascii=False)
        logger.info(f"  ✓ Backup saved to {backup_file}")

        # Write updated file
        with open(platforms_file, 'w', encoding='utf-8') as f:
            json.dump(platforms, f, indent=2, ensure_ascii=False)
        logger.info(f"  ✓ Updated platforms.json")

    elif dry_run and (results['updated'] > 0 or results['removed'] > 0):
        logger.info(f"\n🔍 DRY RUN: Would update {results['updated']} URLs and remove {results['removed']} platforms (not writing to file)")

    # Print summary
    print("\n" + "=" * 60)
    print("URL VERIFICATION SUMMARY")
    print("=" * 60)
    print(f"Total platforms: {results['total']}")
    print(f"✓ Accessible: {results['accessible']}")
    print(f"🔀 Redirected: {results['redirected']}")
    print(f"❌ Broken: {results['broken']}")
    print(f"📝 Updated: {results['updated']}")
    print(f"🗑️  Removed: {results['removed']}")

    if results['changes']:
        print("\n" + "─" * 60)
        print("URL CHANGES:")
        print("─" * 60)
        for change in results['changes']:
            print(f"\n{change['platform']}")
            print(f"  Old: {change['old_url']}")
            print(f"  New: {change['new_url']}")
            print(f"  Reason: {change['reason']}")

    if results['platforms_to_remove']:
        print("\n" + "─" * 60)
        print("PLATFORMS TO REMOVE:")
        print("─" * 60)
        for removal in results['platforms_to_remove']:
            print(f"\n{removal['platform']}")
            print(f"  Reason: {removal['reason']}")
            if 'old_url' in removal:
                print(f"  Old URL: {removal['old_url']}")
            if 'social_media' in removal:
                print(f"  Social Media: {removal['social_media']}")

    print("\n" + "=" * 60)

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Verify and update platform URLs")
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help="Don't write changes, just show what would be updated"
    )
    parser.add_argument(
        '--no-search',
        action='store_true',
        help="Don't use web search (Tavily) to find URLs for broken links"
    )
    parser.add_argument(
        '--file',
        type=str,
        default='data/platforms.json',
        help="Path to platforms.json file (default: data/platforms.json)"
    )

    args = parser.parse_args()

    platforms_file = Path(args.file)

    if not platforms_file.exists():
        logger.error(f"❌ File not found: {platforms_file}")
        sys.exit(1)

    try:
        results = verify_and_update_platforms(
            platforms_file=platforms_file,
            dry_run=args.dry_run,
            use_llm_fallback=not args.no_search
        )

        if results['updated'] > 0 and not args.dry_run:
            logger.info("\n✅ URLs updated! Rebuild the vector index with:")
            logger.info("   python scripts/build_index.py")

    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
    except Exception as e:
        logger.error(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
