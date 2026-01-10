#!/bin/bash
# Production script: Update events only (skip URL verification)
# Faster update when you know platform URLs haven't changed

set -e  # Exit on error

echo "========================================"
echo "EVENTS UPDATE"
echo "========================================"
echo ""

# Parse arguments
PRIORITY_FLAG=""
LIMIT_FLAG=""
NO_SEARCH_FLAG=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --priority-only)
      PRIORITY_FLAG="--priority-only"
      shift
      ;;
    --limit)
      LIMIT_FLAG="--limit $2"
      shift 2
      ;;
    --no-web-search)
      NO_SEARCH_FLAG="--no-web-search"
      shift
      ;;
    *)
      echo "Unknown option: $1"
      echo "Usage: $0 [--priority-only] [--limit N] [--no-web-search]"
      exit 1
      ;;
  esac
done

# Run event population
python3 scripts/smart_populate_events.py $PRIORITY_FLAG $LIMIT_FLAG $NO_SEARCH_FLAG

echo ""
echo "========================================"
echo "✅ EVENTS UPDATE COMPLETE"
echo "========================================"
echo ""
echo "To view results:"
echo "  - Run: streamlit run app.py"
