"""
Use the Smart Event Finder to populate real events with verified URLs.

This script:
1. Loads organizations from the database
2. Uses LLM to verify current URLs
3. Intelligently finds event pages
4. Extracts real events with real URLs
5. Stores them in EventStore (Qdrant)
"""

import sys
from pathlib import Path
import logging
import json

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load environment variables
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / '.env')

from src.events.smart_event_finder import SmartEventFinder
from src.events.event_store import EventStore

logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s:%(name)s:%(message)s'
)
logger = logging.getLogger(__name__)


def smart_populate_events(limit: int = None, priority_only: bool = False, enable_web_search: bool = True):
    """
    Use smart event finder to populate real events.

    Args:
        limit: Maximum number of organizations to process (None = all)
        priority_only: If True, only process priority organizations
        enable_web_search: If True, use Tavily web search for URL discovery.
                          If False, only verify existing URLs (free, but can't find rebrands)
    """
    print("\n" + "=" * 70)
    print("SMART EVENT POPULATION")
    if not enable_web_search:
        print("⚠️  Web search DISABLED - will only verify existing URLs")
    print("=" * 70)

    # Load organizations from platforms.json
    platforms_file = PROJECT_ROOT / 'data' / 'platforms.json'
    with open(platforms_file) as f:
        platforms = json.load(f)

    # Initialize smart finder and event store
    finder = SmartEventFinder(use_web_search=enable_web_search)
    event_store = EventStore()

    # Select organizations to process
    if priority_only:
        # Focus on orgs known to have events
        priority_orgs = [
            "Black Girls CODE",
            "AfroTech",
            "Techqueria",
            "Outdoor Afro",
            "Latinas in Tech",
            "Melanin Base Camp",
            "Code2040",
            "Blacks In Technology (BIT)",
            "POCIT (People of Color in Tech)",
            "ColorStack"
        ]

        # Filter platforms to priority orgs
        selected_platforms = []
        for platform in platforms:
            if platform['name'] in priority_orgs:
                selected_platforms.append(platform)
    else:
        # Process all platforms
        selected_platforms = platforms

    # Apply limit if specified
    if limit:
        selected_platforms = selected_platforms[:limit]

    print(f"\nProcessing {len(selected_platforms)} organizations...")
    print("=" * 70)

    total_events = 0
    successful_orgs = 0
    updated_urls = []

    for i, platform in enumerate(selected_platforms, 1):
        org_name = platform['name']
        org_id = platform['id']
        current_url = f"https://{platform['website'].replace('http://', '').replace('https://', '')}"

        print(f"\n[{i}/{len(selected_platforms)}] {org_name}")
        print("-" * 70)

        try:
            # Use smart finder to get updated URL and events
            result = finder.find_events_for_organization(
                org_name=org_name,
                org_id=org_id,
                current_url=current_url
            )

            updated_url = result['url']
            events = result['events']

            # Check if URL was updated
            if updated_url != current_url:
                print(f"  📍 URL UPDATED:")
                print(f"     Old: {current_url}")
                print(f"     New: {updated_url}")
                updated_urls.append({
                    'org_name': org_name,
                    'org_id': org_id,
                    'old_url': current_url,
                    'new_url': updated_url
                })

            # Store events
            if events:
                # Clear old events for this org first
                event_store.clear_platform_events(org_id)

                # Add new events
                added = event_store.add_events(events, org_id)
                total_events += added
                successful_orgs += 1

                print(f"  ✅ Added {added} event(s)")
                for event in events[:2]:  # Show first 2 events
                    print(f"     • {event['title']}")
                    print(f"       {event.get('date', 'TBD')} | {event['url']}")
            else:
                print(f"  ℹ️  No upcoming events found")

        except Exception as e:
            logger.error(f"Error processing {org_name}: {e}")
            print(f"  ❌ Error: {e}")

        # Rate limiting
        import time
        time.sleep(2)  # Be nice to websites

    # Final summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Organizations processed: {len(selected_platforms)}")
    print(f"Organizations with events: {successful_orgs}")
    print(f"Total events added: {total_events}")
    print(f"URLs updated: {len(updated_urls)}")

    if updated_urls:
        print("\n📍 Updated Organization URLs:")
        print("-" * 70)
        for update in updated_urls:
            print(f"  • {update['org_name']}")
            print(f"    Old: {update['old_url']}")
            print(f"    New: {update['new_url']}")
            print()

    # Get final event store stats
    stats = event_store.get_collection_stats()
    print(f"\nEvent Store Stats:")
    print(f"  Total events: {stats['total_events']}")
    print(f"  Event types: {stats['event_types']}")

    print("\n" + "=" * 70)
    print("✅ SMART EVENT POPULATION COMPLETE!")
    print("=" * 70)

    # Display LLM token usage statistics
    llm_stats = finder.llm.get_usage_stats()
    print("\n" + "=" * 70)
    print("📊 LLM TOKEN USAGE REPORT")
    print("=" * 70)
    print(f"  Input tokens:    {llm_stats['input_tokens']:,}")
    print(f"  Output tokens:   {llm_stats['output_tokens']:,}")
    print(f"  Cached tokens:   {llm_stats['cached_tokens']:,}")
    print(f"  Web searches:    {llm_stats['web_searches']:,}")
    print(f"  Cache hit rate:  {llm_stats['cache_hit_rate']}")
    print(f"  Estimated cost:  {llm_stats['estimated_cost']}")
    print(f"  Cache savings:   {llm_stats['cache_savings']}")
    print("=" * 70)

    # Save updated URLs to file for manual review
    if updated_urls:
        updates_file = PROJECT_ROOT / 'data' / 'url_updates.json'
        with open(updates_file, 'w') as f:
            json.dump(updated_urls, f, indent=2)
        print(f"\n💾 URL updates saved to: {updates_file}")
        print("   Please review and update platforms.json accordingly")


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Smart event population with LLM-powered URL verification')
    parser.add_argument('--limit', type=int, default=None, help='Max organizations to process (default: all)')
    parser.add_argument('--priority-only', action='store_true', help='Only process priority organizations')
    parser.add_argument('--no-web-search', action='store_true',
                       help='Disable web search to save costs (will only verify existing URLs, cannot find rebrands)')
    args = parser.parse_args()

    smart_populate_events(
        limit=args.limit,
        priority_only=args.priority_only,
        enable_web_search=not args.no_web_search
    )
