#!/bin/bash
# Production script: Full system update (platforms + events)
# Updates platform URLs, rebuilds index, and refreshes all events

set -e  # Exit on error

echo "========================================"
echo "FULL SYSTEM UPDATE"
echo "========================================"
echo ""

# Step 1: Update platform URLs
echo "Step 1/3: Verifying and updating platform URLs..."
python3 scripts/verify_and_update_urls.py

# Step 2: Rebuild platform index
echo ""
echo "Step 2/3: Rebuilding platform vector index..."
python3 scripts/build_index.py

# Step 3: Update all events
echo ""
echo "Step 3/3: Updating events for all organizations..."
python3 scripts/smart_populate_events.py

echo ""
echo "========================================"
echo "✅ FULL SYSTEM UPDATE COMPLETE"
echo "========================================"
echo ""
echo "Next steps:"
echo "  - Run: streamlit run app.py"
