# Architecture

> **Evidence**: `api.py`, `hybrid_rag/retriever.py`, `hybrid_rag/reranker.py`, `hybrid_rag/vectordb.py`, `hybrid_rag/cache.py`, `hybrid_rag/config.py`, `hybrid_rag/constants.py`, `frontend/src/lib/ws.ts`, `frontend/src/lib/api.ts`, `frontend/src/stores/chatStore.ts`

## System Overview

This is a monorepo with three layers:
1. **Library** (`hybrid_rag/`) — a standalone importable Python package for hybrid RAG retrieval
2. **API** (`api.py`) — a FastAPI application that wraps the library and exposes it over HTTP/WebSocket
3. **Frontend** (`frontend/`) — a Next.js 16 single-page application that communicates with the API

## Hybrid RAG Pipeline (5 stages)

The core retrieval pipeline executes inside `HybridRetriever.retrieve()` in `hybrid_rag/retriever.py`:

```
Query
  |
  v
[1] Query cleaning (re.sub special chars)
  |
  v
[2] Semantic search (ChromaDB cosine similarity via SentenceTransformer embedding)
  |
  v
[3] Keyword search (stop-word filtered keyword extraction; ChromaDB $contains per keyword)
  |
  v
[4] Score fusion (weighted sum: semantic_weight * sem_score + keyword_weight * kw_score)
  |
  v
[5a] Cross-encoder reranking (CrossEncoderReranker with ms-marco-MiniLM-L-6-v2; optional)
  |
  v
[5b] Deduplication by source URL (one result per source, capped at final_top_k)
  |
  v
Results: list[dict] with id, text, metadata, score
```

**Embedding model**: `all-MiniLM-L6-v2` (sentence-transformers, local) — produces 384-dim vectors.
**Reranker model**: `cross-encoder/ms-marco-MiniLM-L-6-v2` (sentence-transformers, local) — logits normalized via sigmoid.

## Three-Layer Cache Architecture

```
WebSocket query
       |
       v
  [L1] Shared retrieval cache (_shared_retrieve_documents)
       Key: SHA-256({query, enable_rerank, config_fingerprint, corpus_version})
       Corpus version token: "gen{N}.n{count}" (generation counter + live collection count)
       Backend: InMemoryCache (TTLCache) or RedisCache (switchable via CACHE_BACKEND env var)
       |
       | cache miss
       v
  [L2] Embedding LRU cache (inside HybridRetriever._get_or_encode_embedding)
       Key: SHA-256(query_text)
       Backend: cachetools.LRUCache (maxsize=5000, session-scoped, in-process)
       |
       | embedding cache miss
       v
  [L3] ChromaDB vector storage (persistent, in ./knowledge_db)
       Backend: chromadb.PersistentClient
```

**Fail-open**: All cache operations are try/except-guarded. A Redis failure logs a warning and falls through to live retrieval. Cache failures never block a request.

**Cache invalidation**: `_corpus_version` token regenerates after any ingest (add or update). For `ingest_type='update'` the `_cache_generation` counter is bumped; for `ingest_type='add'` only the collection count changes, leaving the generation stable (cached results for unrelated queries remain valid).

## State Management (API layer)

Module-level globals in `api.py`:

| Global | Type | Purpose |
|---|---|---|
| `_retriever` | `Optional[HybridRetriever]` | Active retriever instance |
| `_config` | `Optional[HybridRetrieverConfig]` | Current config snapshot |
| `_cache` | `Optional[CacheBackend]` | Active cache backend |
| `_cache_generation` | `int` | Monotonic invalidation counter |
| `_corpus_version` | `str` | Composite token "gen{N}.n{count}" |
| `_last_fallback_state` | `Optional[bool]` | Edge-triggered fallback logging tracker |

`LazyCache` wraps the `_cache` global so CORS/other middleware can reference the cache object before `startup_event` runs.

## Frontend-Backend Communication

```
Next.js (port 3000)
    |
    +-- REST (fetch) ──────────────────► FastAPI (port 8000)
    |   Endpoints: /health, /config,      NEXT_PUBLIC_API_URL env var
    |   /config (PUT), /documents,
    |   /sources, /collections
    |
    +-- WebSocket ─────────────────────► FastAPI WS /ws/chat
        src/lib/ws.ts WebSocketClient     NEXT_PUBLIC_WS_URL env var
        Singleton with exponential        Default: ws://localhost:8000/ws/chat
        backoff reconnect
        (1s → 2s → 4s … capped 30s)
```

**WebSocket message flow**:
- Client sends: `{"query": str, "enable_rerank": bool?}`
- Server sends: `{"type": "status", "message": str}` then `{"type": "results", "query": str, "results": [...], "total_results": int, "cache_status": "HIT"|"MISS"|"ERROR"}`
- On error: `{"type": "error", "message": str}`

## Configuration Flow

`HybridRetrieverConfig` is a `@dataclass` validated in `__post_init__`. It is immutable — `config.update(**kwargs)` returns a new instance via `dataclasses.replace`. All defaults live in `constants.py` and `config.py`. Runtime updates via `PUT /config` call `_retriever.update_config(**kwargs)` which rebinds `_retriever.config` and bumps `_corpus_version`.

`CacheSettings` is also a `@dataclass` with `__post_init__` validation. Production mode (env `ENVIRONMENT=production`) enforces `rediss://` URL and a password for Redis. `CacheSettings.from_env()` reads all cache env vars.

## ChromaDB Collection Lifecycle

On startup (`initialize_retriever`):
1. `list_existing_collections(KNOWLEDGE_DB_DIRECTORY)` checks if `config.collection_name` (`"rag_collection"`) already exists.
2. If yes: `open_collection(...)` — preserves existing data.
3. If no: `initialize_vector_db(sample_documents, ...)` — seeds with Google Maps support docs.

Collection names are validated: 6–20 characters, `is_valid_collection_name` and `sanitize_collection_name` utilities are exported from the library.

## Document Ingestion

`POST /documents` accepts three source types:
- `"text"`: Raw text body
- `"url"`: Fetches HTML, strips tags, chunks
- `"file"`: Base64-encoded; PDF extraction via `pypdf` if installed, otherwise plain text

Ingest type:
- `"update"` (default): Deletes existing chunks for the source, re-ingests, bumps `_cache_generation`.
- `"add"`: Adds new chunks without deleting, no generation bump (only collection count changes).

## Frontend State

| Store | Persistence | Responsibility |
|---|---|---|
| `chatStore` (Zustand + persist) | localStorage (`"chat-history-v1"`) | Message history, capped at 200 messages; loading/done/error status per message |
| `settingsStore` (Zustand) | In-memory only | Known ChromaDB collections (merged, not replaced, to survive navigation) |

The root page (`src/app/page.tsx`) is a `"use client"` component managing active panel (`"query"` | `"data"` | `"settings"`) in local React state.

## CORS Configuration

Allowed origins are read from `CORS_ORIGINS` env var (comma-separated), defaulting to `http://localhost:3000,http://localhost:3001`. All methods and headers are allowed; credentials are enabled.
