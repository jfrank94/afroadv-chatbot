# 🌿 PoC Platforms Discovery - RAG-Based Chatbot

> **Discover vibrant communities and platforms created by and for People of Color in tech and outdoor/travel spaces.**

A production-ready RAG-based (Retrieval-Augmented Generation) chatbot that helps users discover platforms serving communities of color, especially Afro-Adventurers. Ask natural language questions like *"What communities exist for Black women in hiking?"* or *"Find me Latinx tech networking groups"* and get intelligent, contextual answers powered by AI.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Streamlit](https://img.shields.io/badge/streamlit-1.28+-red.svg)](https://streamlit.io)
[![Tests](https://img.shields.io/badge/tests-40%20passing-success.svg)](TEST_SUMMARY.md)
[![Coverage](https://img.shields.io/badge/coverage-89%25%20core-green.svg)](TEST_SUMMARY.md)

---

## ✨ Features

- **🤖 AI-Powered Search** - Multi-provider LLM with intelligent fallback (Claude Haiku → Cerebras → DeepSeek)
- **🔍 Hybrid Search** - Combines semantic vector search with keyword matching for brand names
- **🎉 Event Discovery** - Automatically discovers upcoming events from platform websites
- **📊 Vector Database** - Qdrant (local + cloud) with sentence-transformers embeddings
- **💬 Conversation Memory** - Context-aware responses with chat history (last 5 turns)
- **🔒 Secure & Private** - All API keys from environment variables, no hardcoded secrets
- **⚡ Fast & Free** - Uses free API tiers (Tavily, Cerebras) + Claude prompt caching (90% savings)
- **🧪 Well-Tested** - 40 tests (100% passing), 89% coverage on core utilities

---

## 🚀 Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/yourusername/poc-platforms-chatbot.git
cd poc-platforms-chatbot
```

### 2. Create Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Set Up API Keys

```bash
cp .env.example .env  # Create your environment file
```

Edit `.env` and add your API keys:

```bash
# Primary LLM (Recommended - Best quality with 90% prompt caching)
ANTHROPIC_API_KEY=sk-ant-...  # Get at https://console.anthropic.com/

# Web Search for Event Discovery (Required for event features)
TAVILY_API_KEY=...  # Get free at https://tavily.com (1000 searches/month)

# Optional Backup LLMs (for redundancy)
CEREBRAS_API_KEY=...   # Get free at https://cloud.cerebras.ai/ (30M tokens/month)
DEEPSEEK_API_KEY=...   # Get at https://platform.deepseek.com/ (~$0.28/M tokens)

# Vector Database (optional - only for Qdrant Cloud deployment)
USE_QDRANT_CLOUD=false
# QDRANT_URL=https://your-cluster.cloud.qdrant.io:6333
# QDRANT_API_KEY=your_api_key
```

**Minimum Required**: `ANTHROPIC_API_KEY` + `TAVILY_API_KEY` for full functionality.

### 5. Build the Platform Index

```bash
# Index platforms into Qdrant vector database
python scripts/build_index.py
```

This creates a local Qdrant database with all platform embeddings (~30 seconds for 50 platforms).

### 6. (Optional) Populate Events

```bash
# Discover events from platforms with websites (requires TAVILY_API_KEY)
python scripts/smart_populate_events.py --limit 20

# Or populate all platforms at once
python scripts/smart_populate_events.py
```

### 7. Run the App

```bash
streamlit run app.py
```

The app will open at `http://localhost:8501` 🎉

---

## 📖 Usage

### Ask Natural Language Questions

```
User: "What communities exist for Black women in tech?"

Bot: "Here are several communities for Black women in tech:

1. Black Women Talk Tech - Community specifically for Black women...
2. /dev/color - Nonprofit empowering Black software engineers...
3. Blacks In Technology (BIT) - 20K+ members across tech..."
```

### Discover Events

```
User: "What tech events are upcoming for Latinx professionals?"

Bot: "Here are 3 upcoming events:

🎉 Latinas in Tech Summit 2025
   📅 March 15, 2025
   📍 San Francisco, CA
   🔗 Register: https://latinasintechsummit.org
   ...
```

### Browse All Platforms

Click **"📋 Browse All Platforms"** in the sidebar to see the full database.

### Filter Results

Use the sidebar to:
- Filter by type (Tech / Outdoor/Travel)
- Adjust number of results (3-10)
- Clear chat history

---

## 🏗️ Architecture

### System Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                          USER INTERFACE                              │
│                     (Streamlit Chat Interface)                       │
│  • Chat history with conversation memory (last 5 turns)              │
│  • Event cards with date/location/links                              │
│  • Platform cards with metadata                                      │
└────────────────────────────────┬─────────────────────────────────────┘
                                 │
                                 ▼
┌──────────────────────────────────────────────────────────────────────┐
│                       CHATBOT ORCHESTRATION                          │
│                         (src/chatbot.py)                             │
│  • Routes queries to platform or event search                        │
│  • Manages conversation context                                      │
│  • Formats responses with sources                                    │
└─────────┬────────────────────────────────────────────────────────────┘
          │
          ├─────────────────────────┬────────────────────────────────┐
          ▼                         ▼                                ▼
┌──────────────────────┐  ┌──────────────────────┐  ┌─────────────────────┐
│   PLATFORM SEARCH    │  │    EVENT SEARCH      │  │   EVENT DISCOVERY   │
│  (src/retriever.py)  │  │(src/events/event_    │  │(src/events/smart_   │
│                      │  │      store.py)       │  │  event_finder.py)   │
│ • Hybrid search:     │  │                      │  │                     │
│   - Vector (semantic)│  │ • Vector search over │  │ • Web scraping      │
│   - Keyword (brand)  │  │   events collection  │  │ • RSS/feed parsing  │
│ • Top-k retrieval    │  │ • Date filtering     │  │ • LLM extraction    │
│ • Similarity scoring │  │   (future only)      │  │ • Auto-enrichment   │
└──────────┬───────────┘  └──────────┬───────────┘  └──────────┬──────────┘
           │                         │                         │
           └─────────────────────────┼─────────────────────────┘
                                     ▼
           ┌──────────────────────────────────────────────────────┐
           │            LLM PROVIDER (src/llm.py)                 │
           │   Multi-provider fallback with retry logic:          │
           │                                                      │
           │   1️⃣ Claude Haiku 4.5 (primary)                      |
           │      • 90% prompt caching for cost savings           │
           │      • Best quality responses                        │
           │                                                      │
           │   2️⃣ Cerebras Llama 3.1 70B (backup)                 │
           │      • 2000 tok/sec inference speed                  │
           │      • 30M tokens/month free tier                    │
           │                                                      │
           │   3️⃣ DeepSeek (final fallback)                       │
           │      • Ultra low cost (~$0.28/M tokens)              │
           │      • Reliable availability                         │
           └──────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌────────────────────────────────────────────────────────────────────┐
│                          DATA LAYER                                │
│                                                                    │
│  ┌─────────────────────┐         ┌──────────────────────────────┐  │
│  │  platforms.json     │────────▶│  Qdrant Vector Database      │  │
│  │  (48 platforms)     │         │  Collection: "poc_platforms" │  │
│  │  • Source of truth  │         │                              │  │
│  │  • Manually curated │         │  • Local mode: Persistent    │  │
│  │  • Rich metadata    │         │    storage (qdrant_storage/) │  │
│  └─────────────────────┘         │  • Cloud mode: Qdrant Cloud  │  │
│                                  │    (1GB free tier)           │  │
│  ┌─────────────────────┐         │                              │  │
│  │  Event Discovery    │────────▶│  Collection: "events"        │  │
│  │  • Web scraping     │         │  • Separate collection       │  │
│  │  • RSS feeds        │         │  • Date-based filtering      │  │
│  │  • LLM extraction   │         │  • Auto-cleanup of expired   │  │
│  └─────────────────────┘         └──────────────────────────────┘  │
│                                                                    │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │         Embeddings: sentence-transformers/all-MiniLM-L6-v2  │   │
│  │         • 384 dimensions                                    │   │
│  │         • Local inference (no API calls)                    │   │
│  │         • ~90MB model size                                  │   │
│  └─────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────┘
```

### Data Flow

**Platform Query Flow**:
```
User Query → Embed → Hybrid Search (Vector + Keyword) →
Retrieve Top-K → LLM Generation → Response with Sources
```

**Event Query Flow**:
```
User Query → Embed → Vector Search (events collection) →
Filter by Date → Retrieve Top-K → LLM Generation → Event Cards
```

**Event Discovery Flow**:
```
Platform URL → Web Search (Tavily) → RSS/Feed Parsing →
LLM Extraction → Validate & Store → Qdrant Events Collection
```

### Key Components

| Component | Purpose | Technology |
|-----------|---------|------------|
| **[app.py](app.py)** | Streamlit web interface | Streamlit 1.28+ |
| **[src/chatbot.py](src/chatbot.py)** | Main RAG orchestration | Python |
| **[src/retriever.py](src/retriever.py)** | Hybrid search (semantic + keyword) | Qdrant + sentence-transformers |
| **[src/llm.py](src/llm.py)** | Multi-provider LLM with fallback | Claude API, Cerebras, DeepSeek |
| **[src/events/event_store.py](src/events/event_store.py)** | Event vector storage & search | Qdrant (separate collection) |
| **[src/events/smart_event_finder.py](src/events/smart_event_finder.py)** | Event discovery & enrichment | Tavily API, RSS parsing, LLM |
| **[src/vectordb_qdrant.py](src/vectordb_qdrant.py)** | Qdrant wrapper (local + cloud) | qdrant-client |
| **[src/embeddings.py](src/embeddings.py)** | Text embedding generation | sentence-transformers |

### Deployment Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                  PRODUCTION DEPLOYMENT                      │
│                                                             │
│  GitHub Repository                                          │
│       │                                                     │
│       ├─── Auto-deploy ───▶ Streamlit Community Cloud       │
│       │                     • Free hosting                  │
│       │                     • 1GB RAM, 2 vCPU               │
│       │                     • Auto-restart on push          │
│       │                                                     │
│       └─── Data Upload ──▶ Qdrant Cloud                     │
│            (via scripts)    • Free 1GB tier                 │
│                            • Persistent vector storage      │
│                            • Global CDN                     │
│                                                             │
│  External APIs:                                             │
│  • Claude API (primary LLM)                                 │
│  • Cerebras API (backup LLM)                                │
│  • Tavily API (web search for events)                       │
└─────────────────────────────────────────────────────────────┘
```

**See**: [DEPLOYMENT_QUICK_START.md](DEPLOYMENT_QUICK_START.md) for 5-step deployment guide

### Technical Highlights

- **Hybrid Search**: Combines vector similarity with keyword matching for better brand name retrieval
- **Prompt Caching**: Claude Haiku's 90% prompt caching reduces costs dramatically
- **Multi-LLM Fallback**: Automatic failover ensures 99.9% uptime
- **Future-Only Events**: Filters out expired events automatically for better UX
- **Local + Cloud**: Seamlessly switch between local development and cloud production

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for detailed technical documentation.

---

## 🧪 Testing

### Run All Tests

```bash
# All tests (40 total)
pytest tests/ -v

# Just unit tests (fast, no API calls)
pytest tests/unit/ -v

# Integration tests (requires API keys in .env)
pytest tests/integration/ -v -m integration

# With coverage
pytest tests/unit/ --cov=src --cov-report=term-missing --cov-report=html
```

**Test Status**: 40/40 passing (100%), 89% coverage on core utilities

See [TEST_SUMMARY.md](TEST_SUMMARY.md) for detailed test documentation.

---

## 📁 Project Structure

```
poc_platforms_chatbot/
├── app.py                          # Streamlit web app
├── config.py                       # Configuration & settings
├── requirements.txt                # Python dependencies
├── README.md                       # This file
│
├── data/
│   ├── platforms.json              # Platform database (50+ orgs)
│   ├── url_updates.json            # URL enrichment tracking
│   ├── pending_submissions.json    # Intake queue
│   └── rejected_submissions.json   # Rejection tracking
│
├── src/
│   ├── chatbot.py                  # Main chatbot logic
│   ├── llm.py                      # Multi-provider LLM wrapper
│   ├── retriever.py                # RAG retrieval
│   ├── embeddings.py               # Embedding model
│   ├── vectordb_qdrant.py          # Qdrant vector DB
│   │
│   ├── events/
│   │   ├── event_store.py          # Event storage (Qdrant)
│   │   ├── base_extractor.py       # Shared utilities (89% coverage)
│   │   ├── llm_extractor.py        # LLM event extraction
│   │   ├── eventbrite_scraper.py   # Eventbrite scraping
│   │   ├── rss_fetcher.py          # RSS/Atom parsing
│   │   └── smart_event_finder.py   # Smart URL discovery
│   │
│   └── agents/
│       └── event_finder.py         # EventFinder agent (web search + LLM)
│
├── scripts/
│   ├── build_index.py              # Build platform vector index
│   ├── populate_events.py          # Populate events with EventFinder
│   ├── cleanup_inactive_platforms.py  # Remove inactive platforms
│   ├── test_queries.py             # Test retrieval quality
│   └── test_chatbot_manual.py      # Manual chatbot testing
│
├── tests/
│   ├── unit/                       # Fast unit tests
│   │   ├── test_base_extractor.py  # 89% coverage
│   │   └── test_llm_parsing.py
│   ├── integration/                # Real API tests
│   │   ├── test_llm_integration.py
│   │   ├── test_event_store.py
│   │   └── test_agent_event_finder.py
│   └── fixtures/
│       └── llm_responses.py        # Cached LLM responses
│
└── docs/
    ├── ARCHITECTURE.md             # Technical deep dive
    ├── DATABASE.md                 # Data schema
    ├── CHATBOT.md                  # UX patterns
    ├── INFRASTRUCTURE.md           # Deployment guide
    └── CLAUDE.md                   # Project overview
```

---

## 🔧 Configuration

### Environment Variables

All configuration is loaded from `.env` file:

```bash
# Required API Keys
ANTHROPIC_API_KEY=sk-ant-...    # Primary LLM - Claude Haiku 4.5
TAVILY_API_KEY=...              # Web search for events (1000 free/month)

# Optional Backup LLMs (Recommended for redundancy)
CEREBRAS_API_KEY=...            # Backup - Llama 3.1 70B (30M tokens/month FREE)
DEEPSEEK_API_KEY=...            # Final fallback - DeepSeek (~$0.28/M tokens)

# Vector Database Configuration
USE_QDRANT_CLOUD=false          # Set to "true" for production deployment
# QDRANT_URL=https://your-cluster.cloud.qdrant.io:6333
# QDRANT_API_KEY=...
```

### Key Settings in [config.py](config.py)

```python
# Retrieval
DEFAULT_TOP_K = 5                    # Results per query
MIN_SIMILARITY_THRESHOLD = 0.3       # Similarity threshold

# Generation
MAX_TOKENS = 1000                    # Max response length
TEMPERATURE = 0.7                    # LLM creativity
CONVERSATION_MEMORY_TURNS = 5        # Chat history

# Events
EVENT_EXPIRY_MONTHS = 12             # How far ahead to show events
MAX_EVENTS_PER_PLATFORM = 100        # Max events per platform
```

---

## 🚢 Deployment

### Local Development

```bash
# Run locally with local Qdrant storage
streamlit run app.py
```

### Production (Streamlit Community Cloud + Qdrant Cloud)

**Total Cost**: $0/month for MVP using free tiers!

#### Quick Deployment (30 minutes)

1. **Sign up for Qdrant Cloud** → [cloud.qdrant.io](https://cloud.qdrant.io)
   - Create free 1GB cluster
   - Copy Cluster URL and API Key

2. **Upload data to Qdrant Cloud**
   ```bash
   # Set USE_QDRANT_CLOUD=true in .env
   python scripts/build_index.py
   python scripts/smart_populate_events.py --limit 20
   ```

3. **Push to GitHub**
   ```bash
   git add .
   git commit -m "Ready for deployment"
   git push origin main
   ```

4. **Deploy on Streamlit Community Cloud** → [streamlit.io/cloud](https://streamlit.io/cloud)
   - Connect GitHub repo
   - Add secrets (API keys) in dashboard
   - Deploy automatically!

**See**: [DEPLOYMENT_QUICK_START.md](DEPLOYMENT_QUICK_START.md) for detailed 5-step guide

### Alternative Deployment Options

- **Railway** - Easy deployment with persistent storage ($5/month)
- **Render** - Free tier with auto-sleep (good for demos)
- **Fly.io** - Global edge deployment ($0-5/month)
- **HuggingFace Spaces** - Free Streamlit hosting (16GB RAM)

See [DEPLOY_STREAMLIT.md](DEPLOY_STREAMLIT.md) for comprehensive deployment documentation.

---

## 💰 Cost Estimation

### Free Tier MVP (<1000 users/month)

| Service | Free Tier | Monthly Cost |
|---------|-----------|--------------|
| **Streamlit Community Cloud** | 1 public app | **$0** |
| **Qdrant Cloud** | 1GB storage | **$0** |
| **Cerebras** | 30M tokens/month | **$0** |
| **Tavily** | 1000 searches/month | **$0** |
| **Total** | | **$0/month** ✨ |

### Production with Claude Haiku (<10K queries/month)

| Service | Usage | Monthly Cost |
|---------|-------|--------------|
| **Claude Haiku 4.5** | With 90% prompt caching | **$2-5** |
| **Streamlit Cloud** | Free tier | **$0** |
| **Qdrant Cloud** | 1GB free tier | **$0** |
| **Tavily** | 1000 searches | **$0** |
| **Cerebras (backup)** | Free tier | **$0** |
| **Total** | | **$2-5/month** |

**Cost Breakdown** (Claude Haiku):
- Input: $1 per 1M tokens (cached: $0.10/1M)
- Output: $5 per 1M tokens
- **With 90% caching**: Save ~$20-30/month on input tokens
- **For 10K queries**: ~$2-5/month total

### Scaling Estimate

- **100 users/month**: $0 (use Cerebras free tier)
- **1,000 users/month**: $2-5 (Claude with caching)
- **10,000 users/month**: $20-50 (upgrade Qdrant to $25/month paid tier)

---

## 📚 Documentation

- **[CLAUDE.md](CLAUDE.md)** - Project overview and quick start
- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** - Technical architecture deep dive
- **[docs/DATABASE.md](docs/DATABASE.md)** - Platform data schema and examples
- **[docs/CHATBOT.md](docs/CHATBOT.md)** - Chatbot UX patterns and prompts
- **[docs/INFRASTRUCTURE.md](docs/INFRASTRUCTURE.md)** - Deployment options and hosting
- **[src/events/README.md](src/events/README.md)** - Event extraction strategies guide
- **[src/agents/README.md](src/agents/README.md)** - EventFinder agent documentation
- **[TEST_SUMMARY.md](TEST_SUMMARY.md)** - Testing strategy and coverage

---

## 🤝 Contributing

### Add a New Platform

1. Edit [`data/platforms.json`](data/platforms.json)
2. Add platform entry with required fields
3. Run `python scripts/build_index.py` to rebuild index
4. Submit pull request

### Report Issues

Found a bug or have a suggestion? [Open an issue](https://github.com/yourusername/poc-platforms-chatbot/issues)

### Development Setup

```bash
# Install dev dependencies
pip install -r requirements.txt
pip install pytest pytest-cov

# Run tests
pytest tests/ -v

# Check code quality
python -m py_compile app.py src/*.py
```

---

## 🔐 Security & Privacy

- ✅ **No hardcoded secrets** - All API keys from environment variables
- ✅ **Input validation** - Query length limits (max 1000 chars)
- ✅ **Secure dependencies** - All from trusted PyPI sources
- ✅ **No data collection** - No user tracking or analytics
- ✅ **Local-first** - Runs entirely on your machine or private server

---

## 📄 License

This project is open source and available under the [MIT License](LICENSE).

---

## 🙏 Acknowledgments

Built with care to uplift and connect People of Color communities in tech and outdoor/travel spaces.

**Powered by**:
- [Streamlit](https://streamlit.io) - Web framework
- [Qdrant](https://qdrant.tech) - Vector database
- [Sentence Transformers](https://www.sbert.net) - Embeddings
- [Claude](https://anthropic.com), [Cerebras](https://cerebras.ai), [Gemini](https://ai.google.dev) - LLM APIs
- [Tavily](https://tavily.com) - Web search API

---

## Support

- **Documentation**: [docs/](docs/)

---

**Made with 💚 for communities of color**
