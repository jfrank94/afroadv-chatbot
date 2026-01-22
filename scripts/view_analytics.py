"""
View chatbot analytics from query logs.

Usage:
    python scripts/view_analytics.py              # Show summary stats
    python scripts/view_analytics.py --detailed   # Show detailed breakdown
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.analytics import QueryLogger


def display_summary():
    """Display summary analytics."""
    logger = QueryLogger()
    stats = logger.get_stats()

    print("\n" + "="*70)
    print("📊 CHATBOT ANALYTICS SUMMARY")
    print("="*70)

    print(f"\n📈 Overall Stats:")
    print(f"  Total Queries: {stats['total_queries']}")
    print(f"  Total Errors: {stats['total_errors']}")
    print(f"  Error Rate: {stats['error_rate']}")

    print(f"\n🎯 Retrieval Performance:")
    print(f"  Avg Platforms per Query: {stats['avg_sources_per_query']}")
    print(f"  Avg Events per Query: {stats['avg_events_per_query']}")

    print(f"\n🔥 Top Keywords (by frequency):")
    if stats['top_keywords']:
        for i, (keyword, count) in enumerate(stats['top_keywords'][:15], 1):
            bar = "█" * min(int(count / 2), 50)
            print(f"  {i:2d}. {keyword:<20} {bar} ({count})")
    else:
        print("  No data yet")

    print("\n" + "="*70)


def display_detailed():
    """Display detailed analytics with recent queries."""
    import json

    logger = QueryLogger()

    if not logger.log_file.exists():
        print("No analytics data found yet.")
        return

    print("\n" + "="*70)
    print("📊 DETAILED ANALYTICS")
    print("="*70)

    # Read all entries
    entries = []
    with open(logger.log_file) as f:
        for line in f:
            entries.append(json.loads(line.strip()))

    if not entries:
        print("No analytics data found yet.")
        return

    # Show summary first
    stats = logger.get_stats()
    print(f"\n📈 Total Queries: {stats['total_queries']}")
    print(f"📉 Error Rate: {stats['error_rate']}")

    # Show recent queries (last 20)
    print(f"\n📝 Recent Queries (last 20):")
    print("-" * 70)

    for entry in entries[-20:]:
        timestamp = entry['timestamp'][:19]  # Remove milliseconds
        keywords = ', '.join(entry.get('query_keywords', []))
        num_sources = entry.get('num_sources', 0)
        num_events = entry.get('num_events', 0)
        had_error = entry.get('had_error', False)

        status = "❌ ERROR" if had_error else f"✅ {num_sources}P {num_events}E"

        print(f"{timestamp} | {status:<12} | {keywords[:50]}")

    print("-" * 70)

    # Keyword analysis
    print(f"\n🔥 Top 20 Keywords:")
    for i, (keyword, count) in enumerate(stats['top_keywords'][:20], 1):
        print(f"  {i:2d}. {keyword:<20} ({count} queries)")

    print("\n" + "="*70)


def main():
    """Main entry point."""
    if len(sys.argv) > 1 and sys.argv[1] == "--detailed":
        display_detailed()
    else:
        display_summary()


if __name__ == "__main__":
    main()
