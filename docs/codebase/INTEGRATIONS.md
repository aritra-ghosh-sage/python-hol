# Integrations

> **Evidence**: `api.py`, `hybrid_rag/vectordb.py`, `hybrid_rag/reranker.py`, `hybrid_rag/retriever.py`, `hybrid_rag/cache.py`, `hybrid_rag/config.py`, `frontend/src/lib/ws.ts`, `frontend/src/lib/api.ts`, `.env.local.example`

## ChromaDB (Vector Store)

- **Package**: `chromadb` >=1.5.7
- **Mode**: `PersistentClient` — data is stored to disk at `./knowledge_db` (configurable via `KNOWLEDGE_DB_DIRECTORY` constant, default `"./knowledge_db"`).
- **Collection name**: `"rag_collection"` (6–20 character constraint enforced by ChromaDB; validated by `is_valid_collection_name`/`sanitize_collection_name` in `vectordb.py`).
- **Embedding function**: `chromadb.utils.embedding_functions.SentenceTransformerEmbeddingFunction` using `all-MiniLM-L6-v2` model.
- **Startup behavior**: `initialize_retriever()` in `api.py` checks if the collection exists before creating it — this prevents data loss on restart (fixed in commit `3dad77e`).
- **Query interface**: `collection.query(query_embeddings=[...], n_results=k, include=[...])` for semantic; `collection.query(query_texts=[kw], where_document={"$contains": kw})` for keyword.
- **Known concern**: Stale `Collection` handles (after test teardowns) can cause `collection.count()` to fail. The test fixture always checks `collection.count()` before using a collection handle.

## Sentence-Transformer Models (Local, HuggingFace)

Two models are downloaded from HuggingFace Hub on first use:

| Model | Class | Purpose |
|---|---|---|
| `all-MiniLM-L6-v2` | `SentenceTransformer` | Query embedding (384-dim vectors) |
| `cross-encoder/ms-marco-MiniLM-L-6-v2` | `CrossEncoder` | Reranker (ms-marco passage relevance) |

Both models are instantiated in `hybrid_rag/retriever.py` (`__init__`) and `hybrid_rag/reranker.py` (`__init__`) respectively. If `HF_TOKEN` env var is set, it is passed to the `CrossEncoder` constructor for private model access.

**Model download**: Models are cached by HuggingFace Hub to `~/.cache/huggingface/`. Tests that require the models take 10–18 seconds on first run. Tests that do not need models should use the `fake_initialized_app` fixture.

## Redis (Optional Distributed Cache)

- **Package**: `redis` >=5.0.0
- **Backend**: `RedisCache` in `hybrid_rag/cache.py`
- **Connection**: `redis.ConnectionPool.from_url(redis_url, decode_responses=False)` — connection pool is created at `__init__`; failures are caught and the pool is set to `None`.
- **Serialization**: JSON (`json.dumps`/`json.loads`). Values must be JSON-serializable.
- **Key prefix**: configurable via `CACHE_KEY_PREFIX` env var (default `"hybrid_rag_cache:"`).
- **Clear**: uses `SCAN` iterator (non-blocking) then batch `DELETE` — safe for large key spaces.
- **Production requirement**: `ENVIRONMENT=production` enforces `rediss://` (TLS) and a password in the URL — validated at both `CacheSettings.__post_init__` and `RedisCache.__init__`.
- **Activation**: set `CACHE_BACKEND=redis` and `REDIS_URL=redis://...` env vars.

## WebSocket (FastAPI / Browser)

- **Backend**: FastAPI `WebSocket` class, endpoint at `WS /ws/chat`, `api.py:1374`.
- **Protocol**: JSON text frames. Client always sends first; server responds with `status` then `results` (or `error`).
- **Frontend client**: `WebSocketClient` class in `frontend/src/lib/ws.ts` — a singleton (`getWSClient()`), never recreated.
- **Reconnection**: Exponential backoff (1s → 2s → 4s, capped at 30s), infinite retries.
- **Config**: `NEXT_PUBLIC_WS_URL` env var (default `ws://localhost:8000/ws/chat`).
- **Cache status field**: `cache_status: "HIT"|"MISS"|"ERROR"` in results messages — T03 WS contract.

## REST API (Frontend → Backend)

- **Client**: `ApiClient` class in `frontend/src/lib/api.ts` — thin fetch wrapper.
- **Config**: `NEXT_PUBLIC_API_URL` env var (default `http://localhost:8000`).
- **Error handling**: Parses FastAPI `{"detail": ...}` error format; converts Pydantic validation error arrays to readable strings.
- **Endpoints consumed by frontend**: `/health`, `/config`, `/config` (PUT), `/documents` (POST), `/sources`, `/collections`.

## CORS Middleware

- **Package**: `fastapi.middleware.cors.CORSMiddleware`
- **Allowed origins**: `CORS_ORIGINS` env var (comma-separated), defaults to `"http://localhost:3000,http://localhost:3001"`.
- All methods and headers allowed; credentials enabled.

## LangChain Text Splitters

- **Package**: `langchain-text-splitters` >=1.1.1
- **Usage**: `RecursiveCharacterTextSplitter` used in `hybrid_rag/vectordb.py:chunk_text()`.
- **Default params**: `chunk_size=500`, `chunk_overlap=50` characters.

## pypdf (Optional PDF Extraction)

- **Package**: `pypdf` >=4.0.0
- **Import guard**: `with_pdf_support = True; try: import pypdf except ImportError: with_pdf_support = False` in `api.py`.
- **Usage**: Called by `_extract_text_from_file()` for `.pdf` filenames in `POST /documents`.

## HTTP Fetching (URL Ingestion)

- **Package**: `requests` >=2.33.1
- **Usage**: `requests.get(url)` in `api.py` for `source_type="url"` ingestion; HTML is stripped via Python stdlib `html.parser.HTMLParser`.

## Environment Variables Summary

| Variable | Default | Scope |
|---|---|---|
| `CACHE_BACKEND` | `memory` | Python backend |
| `REDIS_URL` | (none) | Python backend |
| `CACHE_TTL_SECONDS` | `3600` | Python backend |
| `CACHE_KEY_PREFIX` | `hybrid_rag_cache:` | Python backend |
| `CACHE_MAX_SIZE` | `10000` | Python backend |
| `CORS_ORIGINS` | `http://localhost:3000,...` | Python backend |
| `ENVIRONMENT` | (empty) | Python backend (production mode triggers Redis TLS enforcement) |
| `HF_TOKEN` | (none) | Python backend (HuggingFace private model auth) |
| `NEXT_PUBLIC_WS_URL` | `ws://localhost:8000/ws/chat` | Frontend |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Frontend |
