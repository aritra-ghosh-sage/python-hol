# Quality Constitution: Hybrid RAG Caching System

**Plan ID:** `20260420-caching-blueprint`  
**Module:** `hybrid_rag/cache.py`, `api.py` (cache integration)  
**Date:** 2026-04-20  
**Owned by:** Caching Task Force  
**Last Updated:** 2026-04-24

---

## Table of Contents

1. [Purpose & Fitness for Use](#1-purpose--fitness-for-use)
2. [Coverage Targets](#2-coverage-targets)
3. [Coverage Theater Prevention](#3-coverage-theater-prevention)
4. [Fitness-to-Purpose Scenarios](#4-fitness-to-purpose-scenarios)
5. [AI Session Quality Discipline](#5-ai-session-quality-discipline)
6. [The Human Gate](#6-the-human-gate)

---

## 1. Purpose & Fitness for Use

### What Does "Good Enough" Mean?

For a caching system, fitness for use means:

- **Correctness**: The cache never returns stale or incorrect results. If a value in cache is returned, it is guaranteed to match what the live API would produce **at that moment**. If the system is in doubt (cache miss, backend failure), it fails open (returns live) rather than returning potentially stale data.

- **Performance**: Cache hits occur in <5ms. With a well-configured cache, >40% of retrieval requests hit L1 (response cache), reducing latency from 200–1000ms (live retrieval) to <5ms (cache hit). L2 (embedding cache) reduces encoder calls by 10-30%, and L3 (config cache) is 100% effective.

- **Resilience**: Cache backend failure never crashes the API. If Redis is down or connection pools exhausted, the system falls back to uncached live retrieval. This is the **fail-open principle**: availability > performance.

- **Security**: No sensitive data leaks through cache keys or stored values. Cache keys are canonical (deterministic) so identical requests always map to the same key, even with JSON formatting variance. No unencrypted PII or API keys stored in Redis.

- **Observability**: The cache emits statistics every request (hits/misses/latency) via `/cache/stats` endpoint. Cache operations are logged at INFO level for ingest/config changes (cache invalidation events) and WARNING level for errors. This enables ops teams to detect cache anomalies (stampede, thrashing, backend failures).

---

## 2. Coverage Targets

| Subsystem | Target | Rationale |
|-----------|--------|-----------|
| `cache.py` (core module) | ≥85% | Defensive code (error handling, TTL logic, thread safety) must be tested. Miss TTL expiration or locking edge cases → production cache corruption. |
| `api.py` (L1 caching via shared retrieval) | ≥90% | L1 cache is integrated into `_shared_retrieve_documents()` function. Must handle HIT/MISS/ERROR paths, key canonicalization, and cache invalidation on config/ingest changes. |
| `api.py` (cache integration) | ≥80% | Cache initialization, invalidation on config/ingest, and stats endpoint. Integration tests cover the full lifecycle (startup → requests → cache clear → shutdown). |
| `config.py` (cache config) | ≥90% | Schema validation + backend factory. Invalid backend selection or missing Redis URL must fail loudly at startup, not silently at runtime. |
| E2E (end-to-end cache pipeline) | 100% | Real workflow: ingest docs → WebSocket /ws/chat query → cache hit on repeat. Verify that the cache is actually populated and hit on subsequent requests. |

---

## 3. Coverage Theater Prevention

Common fake tests that pad coverage without catching real bugs:

### ❌ Theater Pattern 1: Asserting Return Type, Not Return Value

```python
# ❌ FAKE TEST
def test_cache_get():
    cache = InMemoryCache()
    cache.set("key", "value")
    result = cache.get("key")
    assert isinstance(result, str)  # ← Type check, not correctness check
    # Missing: assert result == "value"

# ✅ REAL TEST
def test_cache_get():
    cache = InMemoryCache()
    cache.set("key", "value")
    assert cache.get("key") == "value"
    assert cache.get("nonexistent") is None
```

**Fix:** Every test must assert the actual value, not just its type.

### ❌ Theater Pattern 2: Mocking All Dependencies

```python
# ❌ FAKE TEST
def test_retriever_cache_hit():
    mock_cache = MagicMock()
    mock_cache.get.return_value = {"results": [...]}
    # Test passes because mock_cache is configured to return results
    # But real cache might never store that shape, or store differently
    assert retriever_with_cache(mock_cache).results == [...]

# ✅ REAL TEST
def test_retriever_cache_hit():
    cache = InMemoryCache()  # Real cache
    # Retrieve → cache miss → store in cache
    first_call = retriever.retrieve("query", cache=cache)
    # Retrieve again → cache hit
    second_call = retriever.retrieve("query", cache=cache)
    assert first_call == second_call  # Verify exact match
```

**Fix:** Use real caches in tests, not mocks. Mocks should only be used for external services (Redis connections, HTTP calls).

### ❌ Theater Pattern 3: Testing Import, Not Functionality

```python
# ❌ FAKE TEST
def test_cache_module_imports():
    from hybrid_rag.cache import InMemoryCache, RedisCache
    assert InMemoryCache is not None  # ← Import succeeded, that's all
    assert RedisCache is not None

# ✅ REAL TEST
def test_in_memory_cache_basic_operations():
    cache = InMemoryCache()
    cache.set("key", "value")
    assert cache.get("key") == "value"
    cache.delete("key")
    assert cache.get("key") is None
```

**Fix:** Test behavior, not imports.

### ❌ Theater Pattern 4: Verifying Mock Configuration Instead of Calling Code

```python
# ❌ FAKE TEST
def test_cache_check():
    mock_cache = MagicMock()
    # Assertion checks if mock is configured, not if it's called
    assert mock_cache.get is not None  # ← Useless

# ✅ REAL TEST
def test_shared_retrieve_cache_hit():
    cache = InMemoryCache()
    global _cache
    _cache = cache
    
    # First call: cache miss
    results1 = _shared_retrieve_documents("test query")
    assert len(results1) > 0
    
    # Second call with same query: cache hit
    results2 = _shared_retrieve_documents("test query")
    assert results1 == results2  # Verify exact match
    
    # Check cache was actually used
    stats = cache.stats()
    assert stats["hits"] > 0
```

**Fix:** Call actual code. Verify cache behavior with real cache backends, not mocks.

### ❌ Theater Pattern 5: Happy Path Only

```python
# ❌ FAKE TEST
def test_cache_set():
    cache = InMemoryCache()
    cache.set("key", "value")  # ← Success case only
    # Missing: OOM, permission errors, concurrent writes

# ✅ REAL TEST
def test_cache_set():
    cache = InMemoryCache()
    # Happy path
    cache.set("key", "value")
    assert cache.get("key") == "value"
    
    # Boundary: None values
    cache.set("key2", None)
    assert cache.get("key2") is None
    
    # Boundary: Large values (near max_size)
    large_value = "x" * (10 * 1024 * 1024)  # 10 MB
    cache.set("large", large_value)
    # Cache should either store or evict, never corrupt
    
    # Concurrent access (threading)
    import threading
    errors = []
    def writer():
        try:
            for i in range(100):
                cache.set(f"thread_{threading.current_thread().name}_{i}", "val")
        except Exception as e:
            errors.append(e)
    
    threads = [threading.Thread(target=writer, name=f"t{i}") for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    
    assert len(errors) == 0, f"Threading errors: {errors}"
```

**Fix:** Test boundaries, error paths, and concurrent scenarios.

---

## 4. Fitness-to-Purpose Scenarios

### Scenario 1: Cache Never Returns Stale Config Results
**[Req: formal — Caching_Architecture_Blueprint.md § 3-Layer Strategy, ADR-006]**

**What happens:** A user calls `PUT /config` to change `semantic_weight` from 0.65 to 0.8. This changes how retrieval scores are fused. If L1 (response cache) still contains results computed with the old weight, subsequent retrieval requests get incorrect scores.

**Why it matters:** Users rely on config changes to take effect immediately. Returning cached results with old weights silently produces wrong rankings — users see results in the wrong order without any indication that the system is stale. This is silent correctness loss.

**How to verify:**
1. Make a WebSocket `/ws/chat` query with default config (semantic_weight=0.65)
2. Verify response is cached and `cache_status` field shows "HIT" on repeat query
3. Call `PUT /config` with semantic_weight=0.8
4. Verify cache is cleared: `cache_status` field shows "MISS" on next request
5. Verify new request produces different (reweighted) scores

**Edge cases:**
- Config update with invalid values (should reject before clearing cache)
- Concurrent requests during config update (TOCTOU: time-of-check to time-of-use)
- Config update with only some fields (partial update)

**See tests:** `test_config_invalidates_cache`, `test_concurrent_config_update_and_retrieve`

---

### Scenario 2: Cache Stampede Detection & Monitoring
**[Req: formal — Caching_Architecture_Blueprint.md § Cross-Cutting Concerns, ADR-005]**

**What happens:** A popular query (e.g., "How does RAG work?") is queried frequently. When L1 cache expires or is manually cleared (e.g., after ingest), the first request after expiry is a cache miss. If 100 concurrent requests arrive simultaneously, all 100 hit the retriever pipeline at once — each calling embedding encoder, ChromaDB, keyword search, fusion, and possibly reranking. This "thundering herd" can spike CPU/memory to 5-10x normal levels, causing timeouts.

**Why it matters:** Cache stampede turns a 10-second slow request into a 60-second hang (or crash if resources exhaust). In production, this can cascade to other services or databases if rate limits are exceeded.

**How to verify:** (MVP approach — defer lock-based fix to v1.1)
1. Make a WebSocket `/ws/chat` query and verify it caches (`cache_status: MISS` → `HIT`)
2. Clear cache via `PUT /config` or `POST /ingest`
3. Simulate 50+ concurrent WebSocket queries for the same query
4. Check `/cache/stats` endpoint: latency spike should be visible (first request takes 200–1000ms, subsequent get <5ms after the first completes)
5. Verify no errors occur; all 50 requests eventually return correct results

**Expected behavior:** First request slow (cache miss, retriever runs), subsequent 49 requests get cache hits and complete quickly.

**Monitoring red flag:** If response times don't improve after the first request, the cache is not working (HIT rate should be high after first miss).

**See tests:** `test_cache_stampede_monitoring`, `test_concurrent_retrieve_latency`

---

### Scenario 3: Aggressive Cache Invalidation Causes Cold Starts
**[Req: formal — Caching_Architecture_Blueprint.md § Cache Invalidation, ADR-003]**

**What happens:** Document ingestion via `POST /ingest` clears the entire L1 cache. If documents are ingested frequently (e.g., every 5 minutes), the cache is cold most of the time, and retrieval requests always miss. The cache becomes useless, and system performance degrades to live-retrieval speeds (200–1000ms per query).

**Why it matters:** The cache is supposed to improve performance. If ingestion invalidation is too aggressive, it defeats the purpose. Users see slow queries after every ingest.

**How to verify:**
1. Ingest documents (default behavior: `ingest_type="update"`)
2. Verify cache is cleared: `/cache/stats` shows size=0
3. Make retrieval requests: all show X-Cache: MISS (cache is cold)
4. Continue retrieving same query: should hit cache on repeat (size increases)
5. Now ingest with `ingest_type="add"` (preserve cache)
6. Make retrieval request: should still hit cache (size unchanged or increased)
7. Compare performance: `ingest_type="add"` preserves cache and keeps fast retrieval speeds

**See tests:** `test_ingest_type_add_preserves_cache`, `test_ingest_type_update_clears_cache`, `test_cache_recovery_time`

---

### Scenario 4: Fail-Open: Cache Backend Failure Never Breaks API
**[Req: formal — Caching_Architecture_Blueprint.md § Guiding Principles, § Fail-Open]**

**What happens:** Redis connection pool is exhausted, or Redis server is down. A WebSocket query via `/ws/chat` arrives. If cache fails ungracefully (raises exception), the entire request fails, and users get an error message.

**Why it matters:** Availability > performance. A slow response (live retrieval, no cache) is better than no response (error). Users would rather wait 500ms for results than get an error.

**How to verify:**
1. Simulate Redis connection failure (mock `redis.Redis` to raise `ConnectionError`)
2. Make a retrieval request via WebSocket `/ws/chat`
3. Verify: request completes successfully, returns correct results (via live retriever)
4. Verify: WebSocket message includes cache_status field showing "ERROR" (not "HIT" or "MISS")
5. Verify: error is logged at WARNING level, not ERROR or CRITICAL
6. Verify: `/cache/stats` reflects the error (error_count incremented)

**See tests:** `test_redis_connection_failure`, `test_cache_backend_failure_fail_open`, `test_api_continues_on_cache_error`

---

### Scenario 5: Thread-Safe Cache Under Concurrent Load
**[Req: inferred — from defensive pattern: threading.Lock in InMemoryCache]**

**What happens:** Concurrent requests to the same cache key (e.g., 50 threads calling cache.set("key", value) simultaneously). Without synchronization, one thread might read a partially-written key, or two threads might corrupt internal cache state (dict, TTLCache). Result: cache returns corrupted data or crashes.

**Why it matters:** Production systems always have concurrent requests. If the cache is not thread-safe, it will fail under any real load.

**How to verify:**
1. Create 20 threads, each setting/getting/deleting random cache keys 100 times
2. Verify no exceptions are raised
3. Verify cache size is consistent (no state corruption)
4. Verify all values retrieved match what was set
5. Verify no deadlocks (test completes within 10 seconds)

**See tests:** `test_in_memory_cache_thread_safety`, `test_concurrent_cache_operations`

---

### Scenario 6: Cache Key Canonicalization (No JSON Formatting Variance)
**[Req: formal — Caching_Architecture_Blueprint.md § Data Architecture, ADR-002]**

**What happens:** Client A sends `{"query": "test", "enable_rerank": true}`. Client B sends `{"enable_rerank": true, "query": "test"}` (different key order). Without canonicalization, these map to different cache keys and miss each other. Same query, different request formatting → cache miss, redundant retriever calls.

**Why it matters:** Users/clients might format requests differently. Naive JSON serialization (e.g., `json.dumps(dict)`) preserves key order (Python 3.7+), but the order is not guaranteed across clients. Canonicalization ensures identical queries always map to the same cache key, maximizing hit rate.

**How to verify:**
1. Make request A: `{"query": "test", "enable_rerank": false}`
2. Verify cache hit on repeat (X-Cache: HIT)
3. Make request B: `{"enable_rerank": false, "query": "test"}` (reordered keys)
4. Verify cache hit (not miss) because canonicalization ensures same key
5. Make request C: `{"query": "test"}` (enable_rerank omitted, default=false)
6. Verify cache hit (not miss) because canonical form treats omitted fields same as explicit defaults

**See tests:** `test_cache_key_canonicalization`, `test_cache_key_independence_of_json_order`

---

### Scenario 7: Cache Hit Rate Degrades Under Adversarial Query Distribution
**[Req: inferred — from domain knowledge: cache hit rate depends on query distribution]**

**What happens:** If queries have high cardinality (users ask many different questions), cache hit rate is low. If L1 TTL is too short (e.g., 1 hour), frequently-asked questions fall out of cache before repeat queries arrive. Conversely, if TTL is too long, ingested documents don't get fresh rankings fast enough.

**Why it matters:** Cache tuning requires understanding query patterns. A cache configured for 24-hour TTL might be wrong for a system with 5-minute ingest cycles.

**How to verify:**
1. Simulate realistic query distribution (e.g., 80% Zipf: 20% of queries account for 80% of traffic)
2. Run for simulated 24 hours, check hit rate at each hour
3. Verify hit rate stabilizes (typically 40-60% for realistic distributions)
4. Verify L1 size doesn't grow unbounded (LRU eviction working)
5. Compare against baseline (live retriever, no cache): cache should be 5-10x faster on average

**See tests:** `test_cache_hit_rate_distribution`, `test_cache_lru_eviction`

---

### Scenario 8: Cache Status Field Accuracy
**[Req: inferred — from code inspection: cache_status field in WebSocket messages]**

**What happens:** WebSocket `/ws/chat` messages include a `cache_status` field to indicate cache state (HIT, MISS, ERROR). If this field is wrong (e.g., returns HIT when it should be MISS), monitoring systems and clients will be confused.

**Why it matters:** Clients and ops teams rely on cache_status field to diagnose cache health. Wrong status → wrong diagnosis → wasted troubleshooting time.

**How to verify:**
1. Make WebSocket query (cache miss): verify `cache_status: "MISS"` in first response message
2. Repeat same query (cache hit): verify `cache_status: "HIT"` in response
3. Corrupt cache (delete the key externally): make query, verify `cache_status: "MISS"` (not HIT)
4. Simulate cache error: verify `cache_status: "ERROR"` (not HIT or MISS)

**See tests:** `test_cache_status_miss`, `test_cache_status_hit`, `test_cache_status_error`

---

## 5. AI Session Quality Discipline

Every AI session working on this codebase must follow these rules:

### 5.1 Before Writing Code
- [ ] Read `quality/QUALITY.md` (this file) completely
- [ ] Read `Caching_Architecture_Blueprint.md` to understand 3-layer strategy
- [ ] Read `plan.yaml` to understand implementation plan and ADRs
- [ ] Identify which scenario(s) your change affects (reference by number)

### 5.2 Type Safety
- [ ] All functions have complete type hints (no implicit `Any`)
- [ ] Return types specified
- [ ] Complex types annotated (Dict, List, Literal, Optional)
- [ ] Run `mypy --strict` on changed files before commit

### 5.3 Docstrings
- [ ] Every public function has a Google-style docstring
- [ ] Docstring includes Args, Returns, Raises, and Example sections
- [ ] Example shows actual usage (not pseudocode)

### 5.4 Error Handling
- [ ] Catch specific exceptions (never bare `except:`)
- [ ] Log at appropriate level: DEBUG (dev info), INFO (events), WARNING (issues), ERROR (failures)
- [ ] Cache failures logged as WARNING, never CRITICAL (fail-open principle)

### 5.5 Testing
- [ ] Write at least one test per scenario that your change affects
- [ ] Test happy path AND error paths (scenario boundaries)
- [ ] Use real objects, not mocks (except external services: Redis, HTTP)
- [ ] Run full test suite before commit: `pytest tests/ quality/ -v`

### 5.6 Commit Messages
- [ ] Use conventional commits: `feat|fix|refactor|test|docs(cache): ...`
- [ ] Reference ADR in commit: `fix(cache): implement stampede monitoring (ADR-005)`
- [ ] Reference scenario in commit: `test(cache): add Scenario #7 test (cache hit rate distribution)`

---

## 6. The Human Gate

These decisions require human judgment and cannot be automated:

1. **Tuning cache TTLs** — Does your query distribution support 24-hour TTL, or should it be shorter? This requires analyzing real query logs.

2. **Stampede mitigation strategy** — Should you use request coalescing (lock-based), probabilistic early expiration (xfetch), or something else? This is an architectural decision.

3. **Backend selection** — Should you use Redis (distributed) or in-memory (single-instance)? Depends on deployment topology.

4. **Monitoring alerting thresholds** — What's a "bad" hit rate for your workload? 30%? 50%? 70%? Set thresholds based on observed baselines.

5. **Incident response** — When cache is down, should you retry, fail open, or fail fast? Depends on SLA and system criticality.

---

## Summary

A caching system is **fit for use** when:

✅ It returns correct results (never stale/corrupted)  
✅ It improves performance (hit rate >40%, latency <5ms)  
✅ It fails gracefully (backend failure → fallback to live, never error)  
✅ It's observable (stats endpoint, logging, X-Cache headers)  
✅ It's safe (thread-safe, no data leaks, canonical keys)  

This constitution defines what "correct" means for this project. Every test, protocol, and scenario is grounded in this definition. When you're unsure whether something is important, ask: "Does this affect correctness, performance, resilience, security, or observability?" If yes, it belongs in the quality system.
