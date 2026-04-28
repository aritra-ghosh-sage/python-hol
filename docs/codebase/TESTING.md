# Testing

> **Evidence**: `tests/conftest.py`, `pyproject.toml`, `tests/test_cache.py`, `tests/test_system_e2e.py`, `tests/test_ws_retrieval_critical_path.py`, `CLAUDE.md`

## Test Runner Configuration

- **Tool**: `pytest` >=9.0.3 with `pytest-asyncio` >=0.24.0
- **Async mode**: `asyncio_mode = "auto"` in `pyproject.toml` — no `@pytest.mark.asyncio` needed on individual tests
- **Coverage tool**: `pytest-cov` >=7.1.0
- **Coverage target**: >=80% overall (enforcement manual — CI must be green)
- **Pass requirement**: 100% of executed tests must pass; no allowed failure rate

## Running Tests

```bash
# All tests
pytest tests/ -v

# Single file
pytest tests/test_cache.py -v

# With coverage
pytest tests/ -v --cov=hybrid_rag --cov=api
```

## Fixture Hierarchy (`tests/conftest.py`)

Three primary fixtures plus one derived fixture:

### `setup_test_environment` (session scope, autouse)
Sets env vars once per session:
- `CACHE_BACKEND=memory`
- `CACHE_TTL_SECONDS=3600`
- `CACHE_MAX_SIZE=10000`

### `initialized_app` (function scope)
- Initializes a real `HybridRetriever` with `get_sample_documents()` and `initialize_vector_db()`
- Downloads sentence-transformer and cross-encoder models if not cached
- Setup time: 10–18 seconds
- Uses `pytest.skip()` if model or network is unavailable
- Initializes `InMemoryCache` from env vars
- Resets `api._cache_generation = 0`
- Clears cache in `finally` block
- **Use when**: the test exercises the actual retrieval pipeline

### `fake_initialized_app` (function scope)
- Bypasses `HybridRetriever.__init__` using `object.__new__`
- Injects stub `collection` (MagicMock, `.count()` returns 5), `encoder` (MagicMock, `.encode()` returns zeros array), empty LRU cache
- Initializes `InMemoryCache` directly
- Setup time: <10 ms
- **Use when**: the test only checks HTTP response shapes, status codes, JSON field names, or admin endpoints

### `client_with_fresh_cache` (function scope)
- Delegates to `fake_initialized_app`, then calls `api._cache.clear()`
- Returns the same `TestClient` with a zeroed cache
- **Use when**: the test needs deterministic hit/miss counters

## HTTP Testing

All tests use `fastapi.testclient.TestClient` (synchronous), which handles both HTTP and WebSocket connections. WebSocket tests use `TestClient` context manager:

```python
with client.websocket_connect("/ws/chat") as ws:
    ws.send_json({"query": "..."})
    response = ws.receive_json()
```

## Test File Naming and Organization

- One test class per module/class under test
- Method names follow `test_<method>_<condition>_<expected_outcome>` pattern
- Files mirror source structure (e.g. `test_cache.py` tests `hybrid_rag/cache.py`)
- Each test class has a docstring describing what is under test

## Key Test Files and What They Cover

| File | Coverage area |
|---|---|
| `test_cache.py` | `CacheBackend` ABC, `InMemoryCache`, `RedisCache` (mocked Redis) |
| `test_cache_integration.py` | Cache invalidation after ingest, corpus version token, add vs update |
| `test_cache_stats_layered.py` | `GET /cache/stats` layered schema (L1, L2, health sections) |
| `test_api_shared_retrieval.py` | `_shared_retrieve_documents` cache key composition, HIT/MISS/ERROR paths |
| `test_embedding_cache.py` | L2 LRU embedding cache hit/miss counting in `HybridRetriever` |
| `test_config.py` | `HybridRetrieverConfig` validation, `update()` immutability |
| `test_collection_utilities.py` / `test_collection_utils.py` | `is_valid_collection_name`, `sanitize_collection_name` |
| `test_initialize_retriever_startup.py` | Startup with existing vs missing collection (preserves data) |
| `test_observability_logs.py` | `CACHE_TELEMETRY_LABELS` constants emitted in log records |
| `test_system_e2e.py` | Admin endpoints, concurrent requests, error scenarios, perf benchmarks |
| `test_system_resilience.py` | Cache failure modes, fallback behavior |
| `test_ws_retrieval_critical_path.py` | WebSocket query end-to-end, `cache_status` field in results |
| `test_retrieval_quality_benchmark.py` | Retrieval precision/recall benchmarks against sample data |
| `test_optb013_docs_closeout.py` | OPTB-013 acceptance tests (observability + corpus versioning) |

## Async Test Notes

- No `@pytest.mark.asyncio` decorators needed anywhere
- `asyncio_mode = "auto"` in `pyproject.toml` covers all tests
- `TestClient` is synchronous even for `async def` FastAPI routes

## Mock Strategy

- **Redis**: `unittest.mock.patch` or `MagicMock` on `redis.Redis` to avoid requiring a live Redis server
- **Retriever**: `_make_fake_retriever()` in `conftest.py` uses `object.__new__` to bypass `__init__` and inject stubs; avoids model downloads
- **Collection health**: Tests that hold `initialized_app` always call `collection.count()` before retrieval to surface stale handles

## Frontend Tests

- **Tool**: Vitest with `@testing-library/react` and jsdom
- **Command**: `pnpm test:unit` (runs `vitest run --environment jsdom`)
- **Test files**: Colocated with components (e.g. `SettingsPanel.test.tsx`, `chatStore.test.ts`, `url-utils.test.ts`, `SourceList.test.tsx`)
- **E2E**: Playwright (`@playwright/test`) — scripts in `frontend/tmp-e2e/` (git-tracked but in `.eslint ignore` list); screenshots git-ignored
- **Coverage target**: >80% on critical paths (per `frontend/AGENTS.md`)
