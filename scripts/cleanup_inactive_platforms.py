#!/usr/bin/env python3
"""
Clean up inactive platforms - Remove organizations with no events in the past year.

This script:
1. Checks all platforms in the database
2. Queries EventStore for recent events (past year)
3. Removes platforms that haven't had any events in the past 12 months
4. Updates the platform database

Run: python scripts/cleanup_inactive_platforms.py
"""

import sys
import json
import logging
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.events.event_store import EventStore
from src.infrastructure.vectordb import QdrantVectorDB

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def check_platform_activity(event_store: EventStore, platform_id: str) -> dict:
    """
    Check if a platform is active based on events.

    A platform is active if:
    1. It held an event in the past year, OR
    2. It has future events scheduled

    Args:
        event_store: EventStore instance
        platform_id: Platform ID to check

    Returns:
        Dictionary with activity status and details
    """
    # Get all events for this platform
    events = event_store.get_platform_events(platform_id, limit=100)

    if not events:
        return {
            'is_active': False,
            'reason': 'no_events',
            'last_event_date': None,
            'has_future_events': False
        }

    today = datetime.now().date()
    most_recent_past = None
    has_future_events = False

    for event in events:
        date_str = event.get('date')
        if date_str:
            try:
                event_date = datetime.strptime(date_str, '%Y-%m-%d').date()

                if event_date >= today:
                    # Future event found
                    has_future_events = True
                else:
                    # Track most recent past event
                    if most_recent_past is None or event_date > most_recent_past:
                        most_recent_past = event_date
            except ValueError:
                continue

    # Determine if active
    is_active = has_future_events or (most_recent_past is not None)

    return {
        'is_active': is_active,
        'reason': 'has_future_events' if has_future_events and most_recent_past is None else 'has_past_events',
        'last_event_date': most_recent_past,
        'has_future_events': has_future_events
    }


def main(auto_confirm: bool = True, dry_run: bool = False):
    """
    Clean up inactive platforms.

    Args:
        auto_confirm: If True, skip confirmation prompt (default: True)
        dry_run: If True, analyze but don't delete anything (default: False)
    """
    print("=" * 70)
    print("🧹 CLEANING UP INACTIVE PLATFORMS")
    print("=" * 70)

    if dry_run:
        print("\n⚠️  DRY RUN MODE - No changes will be made\n")

    # Configuration
    INACTIVITY_THRESHOLD_DAYS = 365  # 1 year
    cutoff_date = datetime.now().date() - timedelta(days=INACTIVITY_THRESHOLD_DAYS)

    print(f"\n⚙️  Configuration:")
    print(f"   - Inactivity threshold: {INACTIVITY_THRESHOLD_DAYS} days (1 year)")
    print(f"   - Cutoff date: {cutoff_date}")
    print(f"   - Active if: past event since {cutoff_date} OR has future events scheduled")
    print(f"   - Inactive: no events OR last event >1 year ago with no future events")

    # Load platforms
    data_path = Path(__file__).parent.parent / "data" / "platforms.json"
    logger.info(f"Loading platforms from {data_path}")

    with open(data_path) as f:
        platforms = json.load(f)

    logger.info(f"Loaded {len(platforms)} platforms")

    # Initialize EventStore (creates Qdrant client)
    logger.info("Initializing EventStore...")
    event_store = EventStore(collection_name="events", local_mode=True)

    # Get reference to the shared Qdrant client (not the vector_db wrapper)
    logger.info("Setting up platform database access...")
    qdrant_client = event_store.vector_db.client  # Get the underlying Qdrant client
    platform_collection = "poc_platforms"

    print(f"\n📊 Analyzing {len(platforms)} platforms...\n")

    # Track results
    active_platforms = []
    inactive_platforms = []
    no_event_data = []

    for i, platform in enumerate(platforms, 1):
        platform_id = platform['id']
        platform_name = platform['name']

        # Check platform activity
        activity = check_platform_activity(event_store, platform_id)

        if activity['is_active']:
            # Platform is active
            if activity['has_future_events']:
                # Has future events scheduled
                if activity['last_event_date']:
                    days_since = (datetime.now().date() - activity['last_event_date']).days
                    logger.info(f"[{i}/{len(platforms)}] {platform_name}: Active (future events scheduled, last event {days_since} days ago)")
                else:
                    logger.info(f"[{i}/{len(platforms)}] {platform_name}: Active (future events scheduled)")
            else:
                # Had recent past event
                days_since = (datetime.now().date() - activity['last_event_date']).days
                logger.info(f"[{i}/{len(platforms)}] {platform_name}: Active (last event {days_since} days ago)")

            active_platforms.append({
                'platform': platform,
                'last_event_date': activity['last_event_date'],
                'has_future_events': activity['has_future_events'],
                'days_since': (datetime.now().date() - activity['last_event_date']).days if activity['last_event_date'] else None
            })
        else:
            # Platform is inactive
            if activity['last_event_date']:
                # Had events but too old
                days_since = (datetime.now().date() - activity['last_event_date']).days
                if days_since > 365:
                    inactive_platforms.append({
                        'platform': platform,
                        'last_event_date': activity['last_event_date'],
                        'days_since': days_since
                    })
                    logger.info(f"[{i}/{len(platforms)}] {platform_name}: Inactive (last event {days_since} days ago on {activity['last_event_date']})")
                else:
                    # Within past year, should be active
                    active_platforms.append({
                        'platform': platform,
                        'last_event_date': activity['last_event_date'],
                        'has_future_events': False,
                        'days_since': days_since
                    })
                    logger.info(f"[{i}/{len(platforms)}] {platform_name}: Active (last event {days_since} days ago)")
            else:
                # No events at all
                no_event_data.append({
                    'platform': platform,
                    'reason': 'no_events'
                })
                logger.info(f"[{i}/{len(platforms)}] {platform_name}: No events found")

    # Summary
    print("\n" + "=" * 70)
    print("📊 ANALYSIS SUMMARY")
    print("=" * 70)
    print(f"\nTotal platforms analyzed: {len(platforms)}")
    print(f"Active platforms (recent events OR future events): {len(active_platforms)}")
    print(f"Inactive platforms (last event >1 year ago, no future events): {len(inactive_platforms)}")
    print(f"Platforms with no events: {len(no_event_data)}")

    platforms_to_remove = inactive_platforms + no_event_data

    if not platforms_to_remove:
        print("\n✅ All platforms are active! No cleanup needed.")
        return

    # Show platforms to be removed
    print("\n" + "=" * 70)
    print(f"🗑️  PLATFORMS TO REMOVE ({len(platforms_to_remove)})")
    print("=" * 70)

    for item in platforms_to_remove:
        platform = item['platform']
        reason = item.get('reason', 'inactive')

        if reason == 'no_events':
            print(f"\n• {platform['name']}")
            print(f"  Reason: No events found in database")
        else:
            print(f"\n• {platform['name']}")
            print(f"  Last event: {item['last_event_date']} ({item['days_since']} days ago)")
            print(f"  Status: Inactive for {item['days_since'] - 365} days beyond threshold")
            print(f"  Note: No future events scheduled")

    # Confirmation (if not auto-confirm)
    if not auto_confirm:
        print("\n" + "=" * 70)
        response = input(f"\nRemove {len(platforms_to_remove)} inactive platform(s)? (yes/no): ")
        if response.lower() not in ['yes', 'y']:
            print("\n❌ Cleanup cancelled. No changes made.")
            return

    # Check if dry run
    if dry_run:
        print("\n" + "=" * 70)
        print("✅ DRY RUN COMPLETE - No changes made")
        print("=" * 70)
        print(f"\nWould have removed {len(platforms_to_remove)} platform(s)")
        print("Run without --dry-run to actually remove them")
        return

    print("\n" + "=" * 70)
    print(f"🗑️  Removing {len(platforms_to_remove)} inactive platform(s)...")
    print("=" * 70)

    # Remove from platform database (vector DB)
    removed_from_db = 0
    for item in platforms_to_remove:
        platform_id = item['platform']['id']
        try:
            # Delete from Qdrant using direct client access
            from qdrant_client.models import FieldCondition, Filter, MatchValue

            qdrant_client.delete(
                collection_name=platform_collection,
                points_selector=Filter(
                    must=[FieldCondition(key="id", match=MatchValue(value=platform_id))]
                )
            )
            removed_from_db += 1
            logger.info(f"Removed {item['platform']['name']} from vector DB")
        except Exception as e:
            logger.error(f"Failed to remove {item['platform']['name']} from vector DB: {e}")

    # Remove from platforms.json
    platform_ids_to_remove = {item['platform']['id'] for item in platforms_to_remove}
    updated_platforms = [p for p in platforms if p['id'] not in platform_ids_to_remove]

    # Backup original file
    backup_path = data_path.with_suffix('.json.backup')
    with open(backup_path, 'w') as f:
        json.dump(platforms, f, indent=2)
    logger.info(f"Backed up original platforms.json to {backup_path}")

    # Write updated platforms
    with open(data_path, 'w') as f:
        json.dump(updated_platforms, f, indent=2)
    logger.info(f"Updated platforms.json with {len(updated_platforms)} platforms")

    # Final summary
    print("\n" + "=" * 70)
    print("✅ CLEANUP COMPLETE")
    print("=" * 70)
    print(f"\n📊 Results:")
    print(f"   - Platforms removed from vector DB: {removed_from_db}")
    print(f"   - Platforms removed from platforms.json: {len(platforms_to_remove)}")
    print(f"   - Remaining platforms: {len(updated_platforms)}")
    print(f"   - Backup saved to: {backup_path.name}")

    print("\n💡 Next Steps:")
    print("   1. Review the changes")
    print("   2. Restart the Streamlit app to see updated platform list")
    print("   3. If needed, restore from backup: mv platforms.json.backup platforms.json")
    print("=" * 70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Clean up inactive platforms (no events in past year)"
    )
    parser.add_argument(
        '--confirm',
        action='store_true',
        help='Require manual confirmation before deleting (default: auto-confirm)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Analyze platforms but don\'t delete anything'
    )

    args = parser.parse_args()

    # Run with arguments
    main(
        auto_confirm=not args.confirm,  # If --confirm flag, disable auto-confirm
        dry_run=args.dry_run
    )
