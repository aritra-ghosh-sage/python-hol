# Concerns

> **Evidence**: `api.py`, `hybrid_rag/retriever.py`, `hybrid_rag/config.py`, `hybrid_rag/cache.py`, `hybrid_rag/vectordb.py`, `tests/conftest.py`, `pyproject.toml`, `git log --name-only` output

## High-Churn Files (Maintenance Risk)

Based on `git log --name-only --since=2025-01-01 | sort | uniq -c | sort -rn`:

| File | Change count | Concern |
|---|---|---|
| `api.py` | 47 | Heaviest churn; single 1909-line file accumulating all concerns |
| `tests/test_api_shared_retrieval.py` | 18 | Tests co-evolve tightly with api.py; breakage risk when api.py is refactored |
| `hybrid_rag/vectordb.py` | 11 | Multiple fixes to collection name handling, `open_collection` behavior |
| `hybrid_rag/config.py` | 10 | `CacheSettings`, `HybridRetrieverConfig`, `create_cache_backend` co-located — coupling risk |
| `hybrid_rag/__init__.py` | 10 | Public API surface changed frequently as exports are added/removed |
| `tests/test_cache_integration.py` | 11 | Integration tests require living ChromaDB state; fragile to fixture order |

## Technical Debt

### `api.py` is a God Module
`api.py` is a single ~1900-line file containing: global state, all Pydantic request/response models, business logic for URL fetching, HTML parsing, PDF extraction, cache management, all route handlers, and a `LazyCache` wrapper class. The `CLAUDE.md` itself notes it is ~1600 lines but the current file is already 1909 lines and growing. Extracting WebSocket handlers, ingestion logic, and Pydantic models into sub-modules would reduce maintenance friction.

### `except Exception` in Library Code
`hybrid_rag/cache.py` and `hybrid_rag/vectordb.py` use broad `except Exception` catches at several non-boundary points. While intentional for fail-open cache semantics, the same pattern in `vectordb.py` (e.g. `chunk_text`, `initialize_vector_db`) could suppress unexpected bugs silently. CLAUDE.md allows `except Exception` only at "clear boundary layers" but some of these are below that threshold.

### `assert` in Production Code
`hybrid_rag/config.py:353` uses `assert settings.redis_url is not None` to narrow types before constructing `RedisCache`. Python's `-O` flag removes `assert` statements. This should be replaced with an explicit `if ... raise ValueError(...)` guard.

### `InMemoryCache` Per-Key TTL Override is Silently Ignored
`InMemoryCache.set()` accepts `ttl_seconds` as a parameter but ignores it — `cachetools.TTLCache` does not support per-key TTL. The comment in the code acknowledges this. If per-key TTL behavior is ever expected by callers, results will differ silently between `InMemoryCache` and `RedisCache`.

### `_corpus_version` is Process-Local
`_last_fallback_state` and `_corpus_version` are module-level globals. Under multi-worker uvicorn deployments each worker maintains independent state. `_cache_generation` would not be synchronized across workers, so cache invalidation events in one worker are invisible to others (documented in a comment in `api.py:750`). There is no distributed lock or shared counter.

### Score Filtering Threshold Unified
**RESOLVED (PR#100):** Consolidated score filtering threshold to single `MIN_SCORE_RETRIEVAL = 0.50` constant. Both WebSocket handler and MCP server now use shared utility from `hybrid_rag/cache_utils.py`, eliminating hardcoded divergence risk.

## Security Concerns

### Redis URL Logged at INFO Level
`api.py:567` logs `f"✓ Cache initialized: backend={cache_settings.backend}, ttl={cache_settings.ttl_seconds}s"` at INFO. The URL itself is not logged here, but `RedisCache.stats()` returns `redis_url` in its stats dict, which is serialized and returned from `GET /cache/stats`. If the Redis URL contains credentials (username/password), they would be exposed in the `/cache/stats` response. **Action required**: Redact credentials from `redis_url` before serialization in the stats response.

### No Authentication on API Endpoints
The API has no authentication or authorization layer. All endpoints (`/config` PUT, `/documents` POST, `/cache/stats`, etc.) are publicly accessible on the configured port. This is acceptable for local development but must be addressed before production exposure.

### CORS Defaults Allow localhost:3001
The default `CORS_ORIGINS` includes `http://localhost:3001` in addition to `3000`. This is permissive for dev convenience but should be restricted in production deployments.

### HTML/URL Ingestion Without Content Validation
`POST /documents` with `source_type="url"` fetches arbitrary URLs using `requests.get()` without a timeout, without IP allowlisting, and without SSRF protection. A malicious input could cause the server to make requests to internal network addresses.

## Performance Concerns

### Keyword Search O(keywords × ChromaDB queries)
`_keyword_search` issues one `collection.query()` call per keyword after stop-word filtering. For a 10-word query with 7 non-stop-words, that is 7 sequential ChromaDB queries. Under heavy load this compounds latency. A single full-text search pass would be more efficient but requires ChromaDB schema changes.

### `_fusion` Uses List Linear Scans
`_fusion()` in `retriever.py` searches for existing documents by `id` using `next((item for item in results if item[0] == id_), None)`. For large candidate sets (up to `semantic_top_k + keyword_top_k = 20` by default) this is acceptable, but would become O(n²) for very large top-k values.

### `RedisCache.clear()` Uses SCAN with Unbounded Iteration
`RedisCache.clear()` accumulates all matching keys into a list before batch-deleting. For a large cache with many entries, this could consume significant memory. [TODO: switch to pipelined SCAN + DELETE for large key sets]

### Model Initialization Blocks Startup
Both `SentenceTransformer` and `CrossEncoderReranker` are initialized synchronously in `HybridRetriever.__init__()`, which is called synchronously from `initialize_retriever()` in `startup_event`. On first run, model download can take minutes. The server does not respond to requests until this completes.

## Known Flakiness Risk

### ChromaDB Stale Handles in Tests
`tests/conftest.py` notes that stale `Collection` handles cause `collection.count()` to fail silently. The `_is_retriever_collection_healthy()` helper probes for this. Tests using `initialized_app` always reinitialize the retriever per function, but if tests share a collection name that is deleted mid-suite, the handle can become stale. This has historically required `try/except` guards in the test suite.

### `initialized_app` Depends on Network/Model Availability
Tests using `initialized_app` call `pytest.skip()` rather than failing when the model cannot be downloaded. This means CI environments without internet access will silently skip these tests rather than fail them, potentially hiding retrieval regressions. **Action required**: Mark model-dependent tests with `@pytest.mark.requires_models` and conditionally run in CI vs local environments.
