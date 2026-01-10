"""
Update events for a single organization by name.

Quick script to refresh events for one org without processing all 49.
"""

import sys
from pathlib import Path
import logging
import json
import argparse

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


def update_org_events(org_name: str, use_web_search: bool = True):
    """
    Update events for a single organization.

    Args:
        org_name: Exact name of organization (case-sensitive)
        use_web_search: Enable Tavily web search for URL verification
    """
    print("\n" + "=" * 70)
    print(f"UPDATING EVENTS FOR: {org_name}")
    print("=" * 70)

    # Load organizations from platforms.json
    platforms_file = PROJECT_ROOT / 'data' / 'platforms.json'
    with open(platforms_file) as f:
        platforms = json.load(f)

    # Find the organization
    target_org = None
    for platform in platforms:
        if platform['name'] == org_name:
            target_org = platform
            break

    if not target_org:
        print(f"\n❌ Organization '{org_name}' not found in database!")
        print("\nAvailable organizations:")
        for p in platforms[:10]:
            print(f"  - {p['name']}")
        print(f"  ... and {len(platforms) - 10} more")
        return

    print(f"\nFound: {target_org['name']}")
    print(f"Type: {target_org['type']}")
    print(f"URL: {target_org['website']}")

    # Initialize finder and event store
    finder = SmartEventFinder(use_web_search=use_web_search)
    event_store = EventStore()

    # Process the organization
    org_id = target_org['id']
    current_url = f"https://{target_org['website'].replace('http://', '').replace('https://', '')}"

    try:
        # Find events
        result = finder.find_events_for_organization(
            org_name=org_name,
            org_id=org_id,
            current_url=current_url
        )

        updated_url = result['url']
        events = result['events']

        # Show URL update if changed
        if updated_url != current_url:
            print(f"\n📍 URL UPDATED:")
            print(f"   Old: {current_url}")
            print(f"   New: {updated_url}")
            print(f"\n⚠️  Manual action needed: Update platforms.json with new URL")

        # Clear old events and add new ones
        if events:
            print(f"\n🗑️  Clearing old events for {org_name}...")
            event_store.clear_platform_events(org_id)

            print(f"✅ Adding {len(events)} new event(s)...")
            added = event_store.add_events(events, org_id)

            print(f"\n" + "=" * 70)
            print("EVENTS FOUND:")
            print("=" * 70)
            for i, event in enumerate(events, 1):
                print(f"\n{i}. {event['title']}")
                print(f"   📅 {event.get('date', 'TBD')} | 📍 {event.get('location', 'TBD')}")
                print(f"   🔗 {event['url']}")
                if event.get('description'):
                    desc = event['description'][:100]
                    print(f"   📝 {desc}{'...' if len(event.get('description', '')) > 100 else ''}")
        else:
            print(f"\nℹ️  No upcoming events found for {org_name}")

        # Show token usage
        llm_stats = finder.llm.get_usage_stats()
        print("\n" + "=" * 70)
        print("📊 COST SUMMARY")
        print("=" * 70)
        print(f"  Web searches:    {llm_stats['web_searches']}")
        print(f"  Input tokens:    {llm_stats['input_tokens']:,}")
        print(f"  Output tokens:   {llm_stats['output_tokens']:,}")
        print(f"  Cached tokens:   {llm_stats['cached_tokens']:,}")
        print(f"  Estimated cost:  {llm_stats['estimated_cost']}")
        print("=" * 70)

        print(f"\n✅ Successfully updated events for {org_name}!")

    except Exception as e:
        logger.error(f"Error processing {org_name}: {e}", exc_info=True)
        print(f"\n❌ Error: {e}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Update events for a single organization',
        epilog='Example: python scripts/update_single_org_events.py "Outdoor Afro"'
    )
    parser.add_argument('org_name', help='Exact organization name (use quotes if spaces)')
    parser.add_argument('--no-web-search', action='store_true',
                       help='Disable web search to save costs')
    args = parser.parse_args()

    update_org_events(args.org_name, use_web_search=not args.no_web_search)
