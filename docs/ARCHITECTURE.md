# Technical Architecture

## System Overview

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
│                      (src/core/chatbot.py)                           │
│  • Routes queries to platform or event search                        │
│  • Manages conversation context                                      │
│  • Formats responses with sources                                    │
└─────────┬────────────────────────────────────────────────────────────┘
          │
          ├─────────────────────────┬────────────────────────────────┐
          ▼                         ▼                                ▼
┌──────────────────────┐  ┌──────────────────────┐  ┌─────────────────────┐
│   PLATFORM SEARCH    │  │    EVENT SEARCH      │  │   EVENT DISCOVERY   │
│ (src/core/retriever) │  │(src/events/event_    │  │(src/events/smart_   │
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
           │       LLM PROVIDER (src/infrastructure/llm.py)       │
           │   Multi-provider fallback with retry logic:          │
           │                                                      │
           │   1️⃣ Claude Haiku 4.5 (primary)                      │
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

---

## Data Flow

### Platform Query
```
User Query → Embed → Hybrid Search → Retrieve Top-K → LLM → Response
```

### Event Query
```
User Query → Embed → Vector Search → Filter by Date → LLM → Event Cards
```

### Event Discovery
```
Platform URL → Web Search → RSS/LLM Extraction → Validate → Store in Qdrant
```

---

## Key Components

| Component | Purpose | Technology |
|-----------|---------|------------|
| **app.py** | Streamlit chat UI | Streamlit 1.28+ |
| **src/core/chatbot.py** | RAG orchestration | Python |
| **src/core/retriever.py** | Hybrid search | Qdrant + sentence-transformers |
| **src/core/conversation.py** | Memory management | Python |
| **src/infrastructure/llm.py** | Multi-provider LLM | Claude, Cerebras, DeepSeek |
| **src/infrastructure/vectordb.py** | Vector DB wrapper | qdrant-client |
| **src/infrastructure/embeddings.py** | Text embeddings | sentence-transformers |
| **src/events/event_store.py** | Event storage | Qdrant (separate collection) |
| **src/events/smart_event_finder.py** | Event discovery | Tavily API, RSS, LLM |

---

## Technical Highlights

### 1. Hybrid Search
**Problem**: Pure vector search misses exact brand names  
**Solution**: Combine semantic + keyword matching  
- Vector: `similarity(query_embedding, platform_embedding)`
- Keyword: Exact match on platform names (1.5x boost)
- Result: Better for both "hiking groups" and "Outdoor Afro"

### 2. Prompt Caching (Claude)
- Cache platform context (rarely changes)
- Cache conversation history (5 turns)
- **90% cache hit rate** → $0.10 vs $1.00/M tokens
- **Saves ~$20-30/month** for 10K queries

### 3. Multi-LLM Fallback
- Claude fails → Cerebras → DeepSeek
- Exponential backoff (1s, 2s, 4s)
- **99.9% uptime** via redundancy

### 4. Future-Only Events
- Filter: `event.date >= today`
- Auto-cleanup of expired events
- Better UX (only actionable events)

---

## Performance

| Operation | Latency |
|-----------|---------|
| Embedding | ~50ms |
| Vector search | ~100ms |
| LLM generation | ~2-5s |
| **Total** | **~3-6s** |

**Bottleneck**: LLM generation  
**Optimization**: Use Cerebras for faster inference

---

## Cost

### Free Tier
- Streamlit Cloud: $0 (1 app)
- Qdrant Cloud: $0 (1GB)
- Cerebras: $0 (30M tokens/month)
- Tavily: $0 (1000 searches/month)
- **Total: $0/month**

### Production (Claude)
- Claude Haiku: $2-5/month (10K queries with caching)
- Everything else: $0/month
- **Total: $2-5/month**

**Scaling**:  
100 users → $0 | 1K users → $2-5 | 10K users → $20-50

---

## Data Schema

### Platform
```json
{
  "id": "outdoor_afro_001",
  "name": "Outdoor Afro",
  "type": "Outdoor/Travel",
  "focus_area": "Black Outdoor Recreation",
  "description": "...",
  "website": "https://outdoorafro.org",
  "tags": ["black", "outdoors", "hiking"]
}
```

### Event
```json
{
  "id": "event_001",
  "platform_id": "outdoor_afro_001",
  "title": "Summer Hiking Series",
  "date": "2025-07-15",
  "location": "Oakland, CA",
  "url": "https://..."
}
```

---

## Deployment

```
GitHub → Streamlit Community Cloud (free hosting)
       └→ Qdrant Cloud (free 1GB vector storage)
       
External APIs: Claude, Cerebras, Tavily
```

**Dev vs Prod**:
- Dev: Local Qdrant
- Prod: Qdrant Cloud (set `USE_QDRANT_CLOUD=true`)

---

## Configuration

```bash
# Required
ANTHROPIC_API_KEY=...
TAVILY_API_KEY=...

# Optional backups
CEREBRAS_API_KEY=...
DEEPSEEK_API_KEY=...

# Vector DB
USE_QDRANT_CLOUD=false
QDRANT_URL=https://...
QDRANT_API_KEY=...
```

---

## References

- [Qdrant Docs](https://qdrant.tech/documentation)
- [Sentence Transformers](https://www.sbert.net)
- [Claude API](https://docs.anthropic.com)
- [Streamlit Docs](https://docs.streamlit.io)
