# Structure

> **Evidence**: `find` output (repo tree), `hybrid_rag/__init__.py`, `api.py`, `frontend/src/app/page.tsx`, `frontend/src/lib/ws.ts`, `frontend/src/lib/api.ts`, `tests/conftest.py`

## Repository Root

```
python-hol/
├── api.py                    # FastAPI application (~1909 lines) — the backend entry point
├── main.py                   # Minimal standalone launcher (thin wrapper)
├── main_example.py           # Standalone library usage demo (not production code)
├── hybrid_rag_flow.py        # Simplified demo/refactored flow (not production code)
├── pyproject.toml            # Python project config, dependencies, tool config
├── uv.lock                   # Locked dependency tree for uv
├── CLAUDE.md                 # Project guidance for Claude Code agents
├── README.md                 # Project overview and metrics
├── .env.local.example        # Template for environment variables
├── .env                      # Actual env vars (git-ignored)
├── .python-version           # Pin file (Python version for uv)
├── hybrid_rag/               # Core library package (importable)
├── tests/                    # All backend test files
├── frontend/                 # Next.js frontend application
├── docs/                     # Documentation (architecture, caching, etc.)
├── knowledge_db/             # ChromaDB persistent storage (git-ignored)
├── ai_support_kb/            # Source documents for ingestion (~1972 entries)
├── quality/                  # Code review artifacts, spec audits (partially git-ignored)
├── jupyter-playground.ipynb  # Exploration notebook
└── .github/agents/           # Custom AI agent definitions
```

## Python Library: `hybrid_rag/`

```
hybrid_rag/
├── __init__.py       # Public API: 26 exports via __all__; version "1.0.0"
├── config.py         # HybridRetrieverConfig, CacheSettings, create_cache_backend
├── constants.py      # KNOWLEDGE_DB_DIRECTORY, DEFAULT_EMBEDDING_MODEL, MIN_RELEVANCE_SCORE,
│                     # STOP_WORDS, CACHE_TELEMETRY_LABELS
├── exceptions.py     # HybridRAGException, RetrieverNotInitializedError, RetrievalError, VectorDBError
├── reranker.py       # CrossEncoderReranker (ms-marco-MiniLM-L-6-v2 model)
├── retriever.py      # HybridRetriever — 5-stage pipeline, L2 embedding LRU cache
├── vectordb.py       # chunk_text, initialize_vector_db, open_collection,
│                     # get_sample_documents, is_valid_collection_name,
│                     # sanitize_collection_name, list_existing_collections
├── cache.py          # CacheBackend (ABC), InMemoryCache, RedisCache
└── py.typed          # PEP 561 marker for mypy/pyright
```

## API Layer: `api.py`

Single-file FastAPI application with:
- Global state: `_retriever`, `_config`, `_cache`, `_cache_generation`, `_corpus_version`, `_last_fallback_state`
- Lifespan startup/shutdown via `@asynccontextmanager startup_event`
- Pydantic request/response models defined inline
- `LazyCache` wrapper class deferring to global `_cache` (allows middleware to register before init)
- Route handlers:

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | API info |
| GET | `/health` | Health check |
| GET | `/config` | Get retriever config |
| PUT | `/config` | Update retriever config |
| GET | `/cache/stats` | Layered cache stats (L1 + L2 + health) |
| WS | `/ws/chat` | Primary retrieval path (streaming results) |
| POST | `/documents` | Ingest text, URL, or file (base64 encoded) |
| GET | `/sources` | List document sources in active collection |
| GET | `/collections` | List all ChromaDB collections |

## Tests: `tests/`

```
tests/
├── conftest.py                         # Session + function fixtures; fake retriever stub
├── test_api_shared_retrieval.py        # Shared retrieval path, cache key behavior
├── test_cache.py                       # Unit tests for InMemoryCache and RedisCache
├── test_cache_integration.py          # Integration: cache invalidation, corpus versioning
├── test_cache_stats_layered.py        # Layered /cache/stats endpoint schema
├── test_collection_utilities.py       # Collection name validation utilities
├── test_collection_utils.py           # Additional collection utility tests
├── test_config.py                     # HybridRetrieverConfig validation
├── test_embedding_cache.py            # L2 LRU embedding cache behavior
├── test_initialize_retriever_startup.py # Startup: existing vs new collection logic
├── test_observability_logs.py         # Telemetry label emission (CACHE_TELEMETRY_LABELS)
├── test_optb013_docs_closeout.py      # OPTB-013 acceptance tests
├── test_retrieval_quality_benchmark.py # End-to-end retrieval quality benchmarks
├── test_system_e2e.py                 # Full system E2E (cache + retrieval + ingest)
├── test_system_resilience.py          # Failure mode and fallback behavior
├── test_ws_http_middleware_tradeoffs_e2e.py # WS vs HTTP cache path comparison
└── test_ws_retrieval_critical_path.py # WebSocket retrieval critical path
```

## Frontend: `frontend/`

```
frontend/
├── src/
│   ├── app/
│   │   ├── page.tsx          # Root page — panel switcher (query/data/settings)
│   │   ├── layout.tsx        # Root layout with global CSS
│   │   └── globals.css       # Tailwind base styles
│   ├── components/
│   │   ├── chat/
│   │   │   ├── ChatInput.tsx, ChatWindow.tsx, MessageBubble.tsx, QueryPanel.tsx
│   │   ├── data/
│   │   │   ├── AddDataPanel.tsx, FileUpload.tsx, SourceList.tsx, TextInput.tsx, UrlInput.tsx
│   │   ├── layout/
│   │   │   ├── MainPanel.tsx, Sidebar.tsx
│   │   ├── settings/
│   │   │   ├── SettingsPanel.tsx
│   │   └── ui/
│   ├── lib/
│   │   ├── types.ts          # TypeScript interfaces matching FastAPI Pydantic models
│   │   ├── ws.ts             # WebSocketClient singleton with exponential backoff reconnect
│   │   ├── api.ts            # REST ApiClient (fetch-based, non-WebSocket endpoints)
│   │   └── url-utils.ts      # URL normalization helpers
│   └── stores/
│       ├── chatStore.ts      # Zustand store: message history, persisted to localStorage
│       └── settingsStore.ts  # Zustand store: known ChromaDB collections
├── package.json
├── tsconfig.json             # strict: true, paths alias @/ → src/
├── tailwind.config.ts
├── vitest.config.ts
└── eslint.config.mjs
```

## Key Configuration Files

| File | Purpose |
|---|---|
| `pyproject.toml` | Dependencies, pytest config (`asyncio_mode = "auto"`), ruff config |
| `.env.local.example` | Template for all cache env vars |
| `frontend/tsconfig.json` | `strict: true`, `@/` path alias to `src/` |
| `CLAUDE.md` | Agent instructions, coding conventions, commands |
| `frontend/AGENTS.md` | Frontend-specific Next.js 16 breaking-changes warnings |
| `.github/AGENTS.md` | AI agent catalog and usage guidance |
