# AGENTS.md — AI Session Bootstrap Context

**For:** Hybrid RAG Caching System (20260420-caching-blueprint)  
**Date:** 2026-04-20  
**Read this first:** Every new AI session on cache-related work should start here.

---

## TL;DR

**What is this?** A production-ready 3-layer caching system for Hybrid RAG (semantic + keyword search) that:
- Caches full retrieval responses (L1) for 24-48 hours via `_shared_retrieve_documents()` in `api.py`
- Caches query embeddings (L2) for infinite reuse
- Caches config responses (L3) with event invalidation

**Why does it matter?** Enables 5-100x retrieval speedup (200-1000ms → <5ms on cache hit)

**Where is the code?**
- Core: `hybrid_rag/cache.py` (CacheBackend ABC, InMemoryCache, RedisCache)
- Integration: `api.py` (`_shared_retrieve_documents()` function for L1, WebSocket `/ws/chat` endpoint)
- Config: `hybrid_rag/config.py` (CacheSettings, create_cache_backend)

**Three blocking issues addressed:**
- Issue #1: Config changes now clear cache (ADR-006, `PUT /config` → `cache.clear()`)
- Issue #2: Cache stampede monitored via `/cache/stats` endpoint (ADR-005)
- Issue #3: Aggressive ingest invalidation fixed with `ingest_type` parameter (ADR-003)

**What's risky?** Cache stampede (100 concurrent requests → retriever hammered), config staleness (users change config, old results served), aggressive ingest clear (cache stays cold).

**How is quality measured?** Hit rate >40%, latency <5ms on hit, 100% fail-open on cache errors.

---

## Architecture at a Glance

```
┌─────────────────────────────────────────────────┐
│ FastAPI WebSocket Client Requests               │
└──────────────────┬──────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────┐
│ WS /ws/chat Handler                             │
│ - Calls _shared_retrieve_documents()            │
│ - L1 Response Cache (via lazy_cache)            │
│ - Returns cache_status: HIT/MISS/ERROR          │
│ Backend: Redis (prod) or InMemoryCache (dev)    │
│ TTL: 24-48h, max_size: 10k entries              │
└──────────────────┬──────────────────────────────┘
                   │ Cache HIT
                   │ (return cached)
                   │
      ┌────────────┤
      │ Cache MISS │
      │            ▼
      │    ┌──────────────────────────────┐
      │    │ HybridRetriever              │
      │    │ - L2 Embedding Cache (LRU)   │
      │    │ - Query encoding (cached)    │
      │    │ - ChromaDB semantic search   │
      │    │ - Keyword search (BM25)      │
      │    │ - Score fusion               │
      │    │ - Reranking (optional)       │
      │    └──────────────────────────────┘
      │
      └──────────────┬───────────────────┐
                     │                   │
                     ▼                   ▼
              ┌────────────────┐   ┌──────────────┐
              │ Config (L3)    │   │ ChromaDB     │
              │ semantic_weight│   │ Vector store │
              │ keyword_weight │   │ semantic idx │
              └────────────────┘   └──────────────┘
```

**Key insight:** L1 caches **entire responses** in `_shared_retrieve_documents()`, so most requests never hit retriever. L2 caches only **embeddings**, saving encoder calls. L3 caches **config responses**, avoiding recomputation.

---

## Critical Path: How Requests Flow

### Request 1 (Cold Start: Cache Miss)

```
WS /ws/chat {"query": "...", "enable_rerank": false}
  ↓
websocket_chat handler:
  - Call _shared_retrieve_documents()
  ↓
_shared_retrieve_documents():
  - Generate cache key: sha256(json_canonical_request + corpus_version)
  - Check lazy_cache.get(key) → None (MISS)
  - Pass through to retriever
  ↓
HybridRetriever.retrieve(query):
  - Check L2 embedding cache for query
  - If miss: encode query with sentence-transformers (SLOW: ~100ms)
  - Store in L2 LRU cache
  - Semantic search in ChromaDB
  - Keyword search (BM25)
  - Fusion (semantic_weight * sem_score + keyword_weight * kw_score)
  - Optional reranking (cross-encoder)
  ↓
_shared_retrieve_documents() stores response in L1 cache with TTL=24h
  ↓
WebSocket message sent with cache_status: MISS (latency: ~500ms)
```

### Request 2 (Warm: Cache Hit)

```
WS /ws/chat {"query": "...", "enable_rerank": false}
  ↓
websocket_chat handler:
  - Call _shared_retrieve_documents()
  ↓
_shared_retrieve_documents():
  - Generate cache key: sha256(json_canonical_request + corpus_version)
  - Check lazy_cache.get(key) → Found!
  ↓
WebSocket message sent with cache_status: HIT (latency: <5ms)

[Retriever never called; no ChromaDB query; no encoding]
```

### Request 3 (Config Changed: Cache Invalidation)

```
PUT /config {"semantic_weight": 0.8}
  ↓
API handler: update_config(update):
  - _config = _config.update(**update.dict())
  - cache.clear()  ← ADR-006 implementation
  ↓
WS /ws/chat (same query as before)
  ↓
websocket_chat handler:
  - Call _shared_retrieve_documents()
  ↓
_shared_retrieve_documents():
  - Check lazy_cache.get(key) → None (cache was cleared)
  ↓
Retriever runs with NEW config (semantic_weight=0.8)
Result stored in cache
WebSocket message sent with cache_status: MISS

[Users see config change take effect immediately]
```

---

## Key ADRs (Architectural Decisions)

Read these. They explain the "why" behind every implementation choice.

| ADR | Title | Impact |
|-----|-------|--------|
| ADR-001 | Three-layer caching strategy | L1/L2/L3 separation of concerns |
| ADR-002 | Include enable_rerank in cache key | Reranked/non-reranked cached separately |
| ADR-003 | Ingest type parameter (add vs update) | Selective cache invalidation |
| ADR-005 | Cache stampede mitigation (MVP) | Stats monitoring; defer lock-based to v1.1 |
| ADR-006 | Config changes clear cache | `PUT /config` → `cache.clear()` |

---

## Quality System

The quality system has 6 artifacts. Before changing any code:

1. **QUALITY.md** — Read what "good enough" means (fitness-to-purpose scenarios)
2. **test_caching_functional.py** — 40+ spec-driven tests; all must pass
3. **RUN_CODE_REVIEW.md** — Code review protocol with guardrails
4. **RUN_INTEGRATION_TESTS.md** — E2E pipeline tests
5. **RUN_SPEC_AUDIT.md** — Multi-model spec audit (Council of Three)
6. **AGENTS.md** — This file (bootstrap context)

**Entry point for any session:**
- Fixing bug? Read QUALITY.md scenario #X first
- Writing test? Run `pytest quality/test_caching_functional.py -v` first
- Reviewing code? Use RUN_CODE_REVIEW.md guardrails
- Doing QA? Use RUN_INTEGRATION_TESTS.md protocol

---

## Common Tasks

### Task: Fix a cache-related bug

**Steps:**
1. Identify which QUALITY.md scenario is broken
2. Write a regression test in `quality/test_regression_XXX.py` (reproduces bug)
3. Verify test fails (confirms bug exists)
4. Fix code in `hybrid_rag/cache.py` or `api.py`
5. Verify test passes
6. Run full test suite: `pytest quality/ tests/test_cache* -v`

### Task: Add a new cache feature

**Steps:**
1. Read ADRs to understand architecture constraints
2. Add new CacheBackend method to abstract class (if needed)
3. Implement in InMemoryCache and RedisCache
4. Add types and Google-style docstrings
5. Write functional tests in `quality/test_caching_functional.py`
6. Add integration test if it affects API
7. Update this AGENTS.md with new feature

### Task: Optimize cache hit rate

**Steps:**
1. Check `/cache/stats` endpoint: what's current hit rate?
2. If <40%: could be TTL too short, ingest too frequent, or query distribution high-cardinality
3. Run `quality/RUN_INTEGRATION_TESTS.md` Phase 3 (load test) to see latency distribution
4. Adjust TTL or ingest_type strategy
5. Re-run integration tests to measure impact

### Task: Debug cache miss on expected hit

**Steps:**
1. Check cache key canonicalization (ADR-002)
   - Verify `json.dumps(..., sort_keys=True)` used
   - Two requests with reordered JSON should produce same key
2. Check X-Cache header: is it MISS or ERROR?
   - MISS: cache working correctly (entry not found or expired)
   - ERROR: cache backend failure (check logs)
3. Check cache size: `GET /cache/stats` → size > 0?
   - If size=0, cache was cleared (check if config/ingest operations happened)
4. Check request canonicality: are enable_rerank values identical?
   - Different enable_rerank values → different cache keys (by design, ADR-002)

---

## Gotchas & Known Issues

### Gotcha 1: Cache Stampede on Popularity

**Scenario:** Query "How does RAG work?" is asked 1000x/day. Cache expires (TTL). First request after expiry is a MISS. If 100 concurrent requests arrive simultaneously, all 100 hit the retriever pipeline at once.

**Effect:** CPU/memory spike, possible timeouts.

**Mitigation (v1.0):** MVP monitoring only. Monitor `/cache/stats` for latency spikes.

**Future (v1.1):** Lock-based request coalescing or TTL jitter.

**What you need to do:** Document this in your incident playbook. Monitor for latency spikes after cache clear.

### Gotcha 2: Aggressive Ingest Invalidation

**Scenario:** If your documents are updated frequently (every 5 min), the cache is cold most of the time. L1 cache never warms up; system stays slow.

**Solution:** Use `ingest_type="add"` for bulk additions (preserves cache), only use `ingest_type="update"` for actual updates. See `POST /documents` request model.

### Gotcha 3: Config Not Taking Effect

**Scenario:** Change config via `PUT /config`, but WebSocket queries still return results with old config weights.

**Cause:** Config invalidation (ADR-006) not implemented. Cache returns old results. See QUALITY.md Scenario #1.

**Verification:** Check WebSocket message's `cache_status` field after config change. Should be "MISS" (cache was cleared), then subsequent identical query should show "HIT" with new weights.

### Gotcha 4: Redis Connection Timeout

**Scenario:** Redis server is slow/down. API hangs indefinitely waiting for Redis connection.

**Fix:** Redis client should have socket_connect_timeout and socket_timeout. If missing, that's a BUG (see RUN_SPEC_AUDIT.md).

### Gotcha 5: JSON Formatting Variance

**Scenario:** Client A sends `{"query": "test", "enable_rerank": false}`. Client B sends `{"enable_rerank": false, "query": "test"}`. Should be same cache key (ADR-002).

**Verify:** Cache key uses `json.dumps(..., sort_keys=True)` for determinism.

---

## Environment Setup

**Prerequisites:**
- Python 3.13+
- Virtual environment with dependencies: `pip install -r requirements.txt`
- ChromaDB: auto-initialized on first run
- Redis (optional): defaults to InMemoryCache if not available

**Environment variables:**

```bash
# Cache configuration
export CACHE_BACKEND=memory  # or "redis"
export CACHE_TTL_SECONDS=86400  # 24 hours
export CACHE_MAX_SIZE=10000
export REDIS_URL=redis://localhost:6379  # Only if backend="redis"

# Logging
export LOG_LEVEL=INFO  # DEBUG for verbose output
```

**Start API:**

```bash
uvicorn api:app --reload --port 8000
```

**Run tests:**

```bash
pytest quality/test_caching_functional.py -v
pytest tests/test_cache_integration.py -v
pytest quality/RUN_INTEGRATION_TESTS.md  # Full e2e pipeline
```

---

## Files You'll Touch

| File | Purpose | Ownership |
|------|---------|-----------|
| `hybrid_rag/cache.py` | Core cache backends (ABC, InMemory, Redis) | Critical ⚠️ |
| `api.py` | L1 caching via `_shared_retrieve_documents()`, stats endpoint, cache invalidation | Critical ⚠️ |
| `hybrid_rag/config.py` | CacheSettings, create_cache_backend factory | Important |
| `quality/test_caching_functional.py` | Functional tests | Important |
| `tests/test_cache_integration.py` | Integration tests | Important |
| `quality/QUALITY.md` | Quality constitution (read first) | Reference |

---

## Debugging Checklist

**Cache not hitting:**
- [ ] Is `cache_status` field "MISS"? (Not "ERROR")
- [ ] Check cache size: `GET /cache/stats` → size > 0?
- [ ] Check TTL hasn't expired (24h default)
- [ ] Check cache key canonicalization (ADR-002)

**Cache errors:**
- [ ] Check logs: `grep -i "cache" /var/log/api.log`
- [ ] Is Redis running? (If using redis backend)
- [ ] Check Redis connection timeout configuration
- [ ] Test fail-open: API should continue even if cache down

**Hit rate low:**
- [ ] Check query distribution (high cardinality → low hit rate)
- [ ] Check ingest frequency (frequent updates clear cache)
- [ ] Use `ingest_type="add"` for non-updating ingests (preserve cache)

**Performance slow:**
- [ ] Check if cache is enabled: `GET /config` → config reflects setup
- [ ] Check WebSocket message `cache_status`: are most HIT?
- [ ] If many MISS: why? (TTL too short, cache cleared, high cardinality)

---

## Emergency Procedures

### Emergency: Cache causing issues

**Disable cache immediately:**
```bash
# Set backend to noop (won't cache)
export CACHE_BACKEND=disabled
# or restart API without cache config
```

### Emergency: Memory pressure (cache too large)

```bash
# Reduce max size
export CACHE_MAX_SIZE=1000

# Clear cache immediately
curl -X PUT http://localhost:8000/config -H "Content-Type: application/json" -d '{}'
```

### Emergency: Redis unavailable

**API should still work** (fail-open pattern):
```bash
redis-cli shutdown  # Simulate Redis down
# Test via WebSocket or frontend UI
# Should return correct results with cache_status: ERROR (not crash)
```

If API crashes or returns errors, that's a BUG (fail-open not implemented).

---

## Success Metrics

You'll know the cache is working when:

✅ **Performance:** Cache hits return in <5ms (vs 200-1000ms for live)  
✅ **Availability:** Cache backend failure never crashes API (X-Cache: ERROR)  
✅ **Correctness:** Config changes clear cache (users see updates immediately)  
✅ **Scalability:** 50+ concurrent requests don't cause timeouts (cache hits fast)  
✅ **Observability:** `/cache/stats` shows hit_rate >40% for realistic workloads  

---

## Next Steps

**For new work:**
1. Start in `quality/QUALITY.md` (read scenarios)
2. Write test in `quality/test_caching_functional.py`
3. Implement change in core module (`hybrid_rag/cache.py` or `api.py`)
4. Run full test suite: `pytest quality/ tests/test_cache* -v`
5. Run integration tests: `bash quality/RUN_INTEGRATION_TESTS.md`

**For reviews:**
1. Use `quality/RUN_CODE_REVIEW.md` protocol
2. Check against relevant ADRs
3. Verify tests pass

**For incidents:**
1. Check `/cache/stats` endpoint
2. Look at X-Cache headers (HIT/MISS/ERROR)
3. Check logs for errors
4. Use debugging checklist above

---

## Resources

**Specification Documents:**
- [Caching_Architecture_Blueprint.md](docs/plan/20260420-caching-blueprint/Caching_Architecture_Blueprint.md) — Full design spec
- [plan.yaml](docs/plan/20260420-caching-blueprint/plan.yaml) — Implementation roadmap
- ADRs: Read in order ADR-001 → 002 → 003 → 005 → 006

**Code References:**
- `hybrid_rag/cache.py:30-80` — CacheBackend ABC definition
- `api.py:652-880` — `_shared_retrieve_documents()` function (L1 cache implementation, key generation, cache hits/misses)
- `api.py:1277-1370` — WebSocket handler with cache status reporting
- `api.py:250-280` — Config update & cache clear
- `api.py:310-330` — Cache stats endpoint

**Quality Artifacts:**
- `quality/QUALITY.md` — Quality constitution (8 fitness scenarios)
- `quality/test_caching_functional.py` — 40+ spec-driven tests
- `quality/RUN_CODE_REVIEW.md` — Code review guardrails
- `quality/RUN_INTEGRATION_TESTS.md` — E2E test protocol
- `quality/RUN_SPEC_AUDIT.md` — Multi-model audit framework

**Related Code:**
- `hybrid_rag/retriever.py` — HybridRetriever (uses L2 cache internally)
- `hybrid_rag/config.py` — Configuration & settings validation
- `tests/` — Existing unit/integration tests

---

**Last updated:** 2026-04-20  
**Maintained by:** Caching Task Force  
**Status:** ✅ Production Ready
