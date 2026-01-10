#!/bin/bash
# Production script: Update a single organization's events
# Quick way to refresh one org without processing all 48

set -e  # Exit on error

if [ $# -eq 0 ]; then
    echo "Usage: $0 \"Organization Name\" [--no-web-search]"
    echo ""
    echo "Examples:"
    echo "  $0 \"Outdoor Afro\""
    echo "  $0 \"POCIT (People of Color in Tech)\""
    echo "  $0 \"Techqueria\" --no-web-search"
    echo ""
    echo "Available organizations:"
    python3 -c "import json; data = json.load(open('data/platforms.json')); [print(f'  - {p[\"name\"]}') for p in data[:10]]; print(f'  ... and {len(data)-10} more')"
    exit 1
fi

ORG_NAME="$1"
NO_SEARCH_FLAG=""

if [ "$2" == "--no-web-search" ]; then
    NO_SEARCH_FLAG="--no-web-search"
fi

echo "========================================"
echo "UPDATING: $ORG_NAME"
echo "========================================"
echo ""

python3 scripts/update_single_org_events.py "$ORG_NAME" $NO_SEARCH_FLAG

echo ""
echo "========================================"
echo "✅ UPDATE COMPLETE"
echo "========================================"
