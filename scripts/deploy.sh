#!/bin/bash
# Production script: Initial deployment setup
# Run this once when deploying to a new environment

set -e  # Exit on error

echo "========================================"
echo "PRODUCTION DEPLOYMENT SETUP"
echo "========================================"
echo ""

# Check for required environment variables
if [ ! -f .env ]; then
    echo "❌ Error: .env file not found!"
    echo ""
    echo "Please create .env with required API keys:"
    echo "  ANTHROPIC_API_KEY=your_key"
    echo "  TAVILY_API_KEY=your_key"
    echo "  (Optional) CEREBRAS_API_KEY, GOOGLE_API_KEY, DEEPSEEK_API_KEY"
    exit 1
fi

# Check required API keys
echo "Checking environment variables..."
python3 -c "
import os
from dotenv import load_dotenv
load_dotenv()

required_keys = ['ANTHROPIC_API_KEY', 'TAVILY_API_KEY']
missing = [key for key in required_keys if not os.getenv(key)]

if missing:
    print(f'❌ Missing required API keys: {', '.join(missing)}')
    exit(1)
else:
    print('✅ All required API keys found')
"

# Step 1: Install dependencies
echo ""
echo "Step 1/4: Installing dependencies..."
pip install -q -r requirements.txt

# Step 2: Build platform index
echo ""
echo "Step 2/4: Building platform vector index..."
python3 scripts/build_index.py

# Step 3: Populate events
echo ""
echo "Step 3/4: Populating events (this may take 5-10 minutes)..."
python3 scripts/smart_populate_events.py

echo ""
echo "========================================"
echo "✅ DEPLOYMENT COMPLETE"
echo "========================================"
echo ""
echo "To start the chatbot:"
echo "  streamlit run app.py"
echo ""
echo "To update data later:"
echo "  ./scripts/update_all.sh          - Full update (URLs + events)"
echo "  ./scripts/update_events.sh       - Events only (faster)"
echo "  ./scripts/update_org.sh \"Name\"   - Single org"
