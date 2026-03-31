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
│  • Manages conversation context and memory                           │
│  • Classifies query complexity and routes accordingly                │
└──────────────────┬──────────────────────────┬────────────────────────┘
                   │                          │
         simple query                   complex query
         (RAG path)                     (agent path)
                   │                          │
                   ▼                          ▼
┌──────────────────────────┐  ┌───────────────────────────────────────┐
│     SIMPLE RAG PATH      │  │         COMPLEX AGENT PATH            │
│                          │  │   (src/agents/complex_agent.py)       │
│  Parallel search:        │  │                                       │
│  • Platform retrieval    │  │  LangGraph ReAct loop:                │
│  • Event search          │  │  • call_model → tool_use?             │
│  • LLM generates answer  │  │    → execute_tools → call_model → ... │
│                          │  │  • Tools: search_platforms,           │
│                          │  │    search_events, web_search          │
│                          │  │  • MAX_ITERATIONS=5 safety cap        │
└──────────┬───────────────┘  └──────────────────┬────────────────────┘
           │                                     │
           └─────────────────┬───────────────────┘
                             ▼
          ┌──────────────────────────────────────────────────┐
          ├─────────────────────────┬────────────────────────┤
          ▼                         ▼                        ▼
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

### Simple Query (RAG path)
```
User Query → Classify (simple) → Embed → Hybrid Search → Retrieve Top-K → LLM → Response
```

### Complex Query (agent path)
```
User Query → Classify (complex) → LangGraph ReAct Loop:
  call_model → tool_use → execute_tools → call_model → ... → end
  Tools: search_platforms | search_events | web_search
→ Synthesized Response
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
| **src/core/chatbot.py** | RAG orchestration + query routing | Python |
| **src/core/retriever.py** | Hybrid search | Qdrant + sentence-transformers |
| **src/core/conversation.py** | Memory management | Python |
| **src/agents/query_classifier.py** | Classify simple vs. complex queries | Python (regex) |
| **src/agents/complex_agent.py** | LangGraph ReAct agent | LangGraph + Anthropic tool use |
| **src/agents/agent_tools.py** | Tool schemas + executor factory | Anthropic tool use |
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

### 4. LangGraph ReAct Agent
**Problem**: Single-pass RAG can't handle comparative, superlative, or multi-step queries well
**Solution**: A regex classifier routes complex queries to a LangGraph ReAct loop
- Classifier fires on patterns: `compare`, `vs`, `most active`, `top 3`, `in NYC... events`, etc.
- Agent calls `search_platforms`, `search_events`, and `web_search` tools iteratively
- Anthropic native tool use (not LangChain): `tool_use` stop_reason → tool results in `user` role
- Custom `_append` reducer (not `add_messages`) keeps state as plain JSON-serializable dicts
- MAX_ITERATIONS=5 cap prevents runaway loops
- Falls back to simple RAG if agent raises an exception

### 5. Future-Only Events
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

## Community Submission System

The platform includes a community-driven submission system for users to suggest new platforms.

### User Flow

1. **Submission Form** (`pages/01_Suggest_Platform.py`)
   - Accessible via "📝 Suggest a Platform" button in app footer
   - Collects: Name, Type, Website, Category, Focus Area, Description, Optional metadata
   - Validates required fields and provides real-time feedback
   - Stores submissions in `data/pending_submissions.json`

2. **Submission Data Structure**
```json
{
  "id": "uuid",
  "submitted_at": "ISO timestamp",
  "status": "pending|approved|rejected",
  "platform": {
    "name": "Platform Name",
    "type": "Tech|Outdoor/Travel",
    "category": "Nonprofit|Community|Company|...",
    "focus_area": "Specific demographic",
    "description": "Brief description",
    "website": "example.com",
    "founded": "2020",
    "community_size": "10K+ members",
    "key_programs": "Programs offered",
    "geographic_focus": "United States",
    "tags": ["tag1", "tag2"]
  },
  "submitter": {
    "name": "Optional name",
    "email": "Optional email"
  }
}
```

### Admin Review Workflow

**Review Tool** (`scripts/review_submissions.py`):

```bash
# List all submissions with status
python scripts/review_submissions.py --list

# Interactive review session
python scripts/review_submissions.py
```

**Review Actions**:
- **[a] Approve** → Adds platform to `data/platforms.json` with auto-generated ID
- **[r] Reject** → Moves to `data/rejected_submissions.json` with reason
- **[s] Skip** → Review later
- **[q] Quit** → End session

**Platform ID Generation**:
Format: `{type}_{name_slug}_{counter:03d}`
Examples: `tech_pocit_001`, `outdoor_outdoor_afro_001`

**Post-Approval Workflow**:
1. Approve submission(s) via review tool
2. Rebuild index: `python scripts/build_index.py`
3. Optionally discover events: `python scripts/smart_populate_events.py`
4. Commit and push: `git add data/platforms.json data/approved_submissions.json`
5. Streamlit Cloud auto-deploys updates

### Data Files

| File | Purpose | Git Tracked |
|------|---------|-------------|
| `data/platforms.json` | Main platform database | ✅ Yes |
| `data/pending_submissions.json` | Awaiting review | ❌ No |
| `data/approved_submissions.json` | Approval history | ✅ Yes |
| `data/rejected_submissions.json` | Rejection history | ❌ No |

### Review Guidelines

**Approve if**:
- Active platform serving PoC communities
- Verifiable website and legitimate organization
- Aligned with tech or outdoor/travel focus
- Not a duplicate

**Reject if**:
- Inactive/defunct organization
- Not focused on PoC communities
- Duplicate submission
- Spam or invalid information

---

## References

- [Qdrant Docs](https://qdrant.tech/documentation)
- [Sentence Transformers](https://www.sbert.net)
- [Claude API](https://docs.anthropic.com)
- [Streamlit Docs](https://docs.streamlit.io)
