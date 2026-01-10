# 🌿 PoC Platforms Discovery

> AI chatbot helping you discover communities and events for People of Color in tech and outdoor spaces.

Ask questions like *"What communities exist for Black women in hiking?"* or *"Find Latinx tech groups"* and get intelligent answers from our curated database of 48+ platforms.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Streamlit](https://img.shields.io/badge/streamlit-1.28+-red.svg)](https://streamlit.io)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**Features**: Hybrid semantic search • Event discovery • Multi-LLM fallback • $0/month deployment

---

## Quick Start

```bash
# Clone and setup
git clone https://github.com/yourusername/poc-platforms-chatbot.git
cd poc-platforms-chatbot
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Configure API keys
cp .env.example .env
# Edit .env: Add ANTHROPIC_API_KEY and TAVILY_API_KEY

# Build index and run
python scripts/build_index.py
streamlit run app.py
```

**Get free API keys**:
- [Claude](https://console.anthropic.com) - Primary LLM
- [Tavily](https://tavily.com) - Event discovery (1000 searches/month free)

---

## How It Works

**RAG Pipeline**: User query → Hybrid search (vector + keyword) → LLM generates answer with sources

**Tech Stack**:
- **Frontend**: Streamlit chat interface
- **Search**: Qdrant vector database + sentence-transformers embeddings
- **LLM**: Claude Haiku (primary) → Cerebras (backup) → DeepSeek (fallback)
- **Events**: Auto-discovered via Tavily web search + RSS parsing

**Example**:
```
You: "Black women in tech communities?"
Bot: Returns Black Women Talk Tech, /dev/color, BIT, etc. with descriptions
```

---

## Deploy to Production (Free)

**Stack**: Streamlit Community Cloud + Qdrant Cloud = $0/month

```bash
# 1. Sign up for Qdrant Cloud (free 1GB)
# Get URL and API key from https://cloud.qdrant.io

# 2. Upload data to cloud
export USE_QDRANT_CLOUD=true
export QDRANT_URL=https://your-cluster.cloud.qdrant.io:6333
export QDRANT_API_KEY=your_key
python scripts/build_index.py
python scripts/smart_populate_events.py --limit 20

# 3. Push to GitHub
git add .
git commit -m "Initial commit"
git push origin main

# 4. Deploy on Streamlit Cloud
# Go to https://streamlit.io/cloud
# Connect your GitHub repo
# Add secrets in dashboard (ANTHROPIC_API_KEY, TAVILY_API_KEY, etc.)
# Deploy!
```

---

## Project Structure

```
├── app.py                   # Streamlit UI
├── config.py                # Settings
├── requirements.txt         # Dependencies
├── data/platforms.json      # 48 platforms (source of truth)
├── src/
│   ├── chatbot.py          # RAG orchestration
│   ├── retriever.py        # Hybrid search
│   ├── llm.py              # Multi-provider LLM
│   ├── vectordb_qdrant.py  # Vector DB wrapper
│   └── events/             # Event discovery system
└── scripts/
    ├── build_index.py      # Index platforms
    └── smart_populate_events.py  # Discover events
```

---

## Configuration

**.env file**:
```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...
TAVILY_API_KEY=...

# Optional (backup LLMs)
CEREBRAS_API_KEY=...
DEEPSEEK_API_KEY=...

# For production deployment
USE_QDRANT_CLOUD=false
QDRANT_URL=https://your-cluster.cloud.qdrant.io:6333
QDRANT_API_KEY=...
```

**Key settings in [config.py](config.py)**:
- `DEFAULT_TOP_K = 5` - Results per query
- `CONVERSATION_MEMORY_TURNS = 5` - Chat history length
- `EVENT_EXPIRY_MONTHS = 12` - How far ahead to show events

---

## Contributing

**Add a platform**:
1. Edit [`data/platforms.json`](data/platforms.json)
2. Run `python scripts/build_index.py`
3. Submit PR

**Report issues**: [GitHub Issues](https://github.com/yourusername/poc-platforms-chatbot/issues)

---

## Architecture

```
┌─────────────┐
│  Streamlit  │  User asks question
└──────┬──────┘
       │
┌──────▼──────────────────┐
│  Chatbot (src/chatbot)  │  Routes to platform/event search
└──────┬──────────────────┘
       │
   ┌───┴────┐
   │        │
┌──▼────┐ ┌─▼──────┐
│Search │ │ Events │  Retrieves relevant data
└───┬───┘ └────┬───┘
    │          │
┌───▼──────────▼───┐
│  LLM Provider    │  Generates natural language response
│  (Claude/etc.)   │
└──────────────────┘
```

**Data flow**: Query → Embed → Hybrid Search (Qdrant) → LLM Generation → Response

**See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for detailed architecture and technical documentation**

---

## Cost

| Tier | Monthly Cost | Usage |
|------|-------------|--------|
| **Free** | $0 | Use Cerebras LLM + free tiers |
| **Prod** | $2-5 | Claude Haiku with 90% caching |

**Scaling**: $0 (100 users) → $2-5 (1K users) → $20-50 (10K users)

---

## License

MIT License - see [LICENSE](LICENSE)

---

## Acknowledgments

Built with care to uplift and connect communities of color in tech and outdoor spaces.

**Powered by**: [Streamlit](https://streamlit.io) • [Qdrant](https://qdrant.tech) • [Claude](https://anthropic.com) • [Cerebras](https://cerebras.ai) • [Tavily](https://tavily.com)

**Made with 💚 for communities of color**
