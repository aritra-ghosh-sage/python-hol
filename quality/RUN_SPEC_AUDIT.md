# RUN_SPEC_AUDIT.md — Council of Three Multi-Model Spec Audit

**Purpose:** Three independent AI models audit the caching system against specifications. Cross-referencing catches defects that any single model might miss.

**Why three models?** Each model has different strengths and blind spots. Model A catches security issues that Model B misses. Model B notices architectural inconsistencies that Model C overlooks. Together, they catch ~90% of real defects. Any one alone catches ~60%.

**Duration:** 20-30 minutes per model (60-90 minutes total for full audit)

---

## Overview

**The three roles:**

| Model | Strength | Focuses On |
|-------|----------|-----------|
| **Model 1: Security & Correctness** | Threat modeling, data flow analysis | Secrets, auth, data integrity, state corruption |
| **Model 2: Architecture & Performance** | Design patterns, scaling, optimization | Cache stampede, hit rate, latency, resource efficiency |
| **Model 3: Error Handling & Resilience** | Edge cases, failure modes, recovery | Exceptions, timeouts, cascading failures, observability |

---

## Pre-Audit Checklist

Before running the audit, prepare:

- [ ] Full spec documents available (Caching_Architecture_Blueprint.md, plan.yaml, ADRs)
- [ ] Source code accessible (hybrid_rag/cache.py, api_middleware.py, api.py)
- [ ] Test files reviewed (quality/test_caching_functional.py)
- [ ] All three models available (Claude Sonnet, GPT-4, Gemini)
- [ ] Chat interface or API access to each model

---

## Phase 1: Audit Initialization

**For each model, provide this context packet:**

```
You are an AI auditor reviewing a Hybrid RAG caching system.

PROJECT CONTEXT:
- Name: Hybrid RAG Caching System
- Domain: Three-layer caching (L1: response, L2: embedding, L3: config)
- Tech: Python 3.13+, FastAPI, Redis/InMemory backends, Pydantic
- Key ADRs: ADR-001 (layers), ADR-002 (rerank flag), ADR-003 (ingest types), 
           ADR-005 (stampede), ADR-006 (config invalidation)

YOUR ROLE:
[Insert Model-Specific Role Below]

DELIVERABLE:
A structured audit report with:
1. Findings (✓ compliant, ⚠ concern, ✗ bug)
2. Evidence (line numbers, code snippets, spec references)
3. Risk severity (critical, important, suggestion)
4. Recommended fixes
```

---

## Model 1: Security & Correctness Audit

**Assign to:** Claude Sonnet (or equivalent security-focused model)

### Prompt

```
SECURITY & CORRECTNESS AUDITOR
===============================

You audit for: Secrets, auth, data integrity, state corruption, cache poisoning.

SPECIFICATIONS TO VERIFY:
1. Cache keys are canonical (deterministic) — no JSON formatting variance
2. Cache entries are immutable (set once, expire/evict atomically)
3. No sensitive data (PII, tokens, passwords) cached or logged
4. Fail-open: cache backend failure never crashes API
5. Thread-safe: concurrent cache operations don't corrupt state
6. Timestamps & versioning: cache can't return stale config results

CODE TO AUDIT:
- File: hybrid_rag/cache.py
  Focus: CacheBackend ABC, InMemoryCache (threading.Lock), RedisCache (JSON serialization)
- File: api_middleware.py
  Focus: Cache key generation (line ~95-110), request body replay pattern (line ~120-150)
- File: api.py
  Focus: Cache initialization (startup_event), config invalidation (PUT /config), ingest (POST /documents)
- File: hybrid_rag/config.py
  Focus: CacheSettings validation, create_cache_backend factory

AUDIT QUESTIONS:
1. Cache Key Canonicalization (ADR-002):
   - How are retrieval requests hashed into cache keys? (Line: api_middleware.py ~95)
   - Does the hash include enable_rerank parameter? (Expected: yes)
   - Does JSON.dumps() use sort_keys=True? (Critical for determinism)
   - Can two semantically identical requests produce different keys? If yes, that's a BUG.

2. Immutability & Atomicity:
   - Are cache entries ever mutated after set()? (Search: cache["key"] = or cache.set() + cache.set())
   - Is clear() atomic? (No race where one thread reads while another clears)
   - Is delete() safe concurrent with get()?

3. Sensitive Data:
   - Search code for: password, secret, token, key, ssn, credit
   - Are these fields NEVER cached?
   - Are they NEVER logged? (grep: logger.*password)
   - Specifically: Does cache key include user_id or enable_rerank? If user_id → potential data leak.

4. Fail-Open Caching:
   - Find all cache.get/set/delete calls. Are they wrapped in try-except?
   - What happens when Redis connection fails? (Code path: redis.Redis → ConnectionError → ?)
   - Does error propagate to client? (BUG) or fail gracefully? (✓)

5. Thread Safety (InMemoryCache):
   - Is there a threading.Lock? (Line: ~40-50 in cache.py)
   - Is lock acquired for every cache operation? (get, set, delete, clear)
   - Could deadlock occur? (nested locks)
   - Is stats() thread-safe? (atomic read of counters)

6. Config Invalidation (ADR-006):
   - Trace PUT /config handler (api.py ~280): After config update, is cache.clear() called?
   - If cache.clear() is missing, that's CRITICAL BUG #1.
   - Is the clear() atomic or could requests race the clear?

REPORT FINDINGS:
[Your findings in structured format below]
```

### Model 1 Output Template

```
SECURITY & CORRECTNESS AUDIT REPORT
===================================

Auditor: [Model name]
Date: [timestamp]
Spec Version: 20260420-caching-blueprint

FINDINGS:

✓ COMPLIANT
  [cache_key_canonical] Cache keys use json.dumps(..., sort_keys=True) + SHA-256
    Evidence: [api_middleware.py:105] canonical_json = json.dumps(req_dict, sort_keys=True)
    Risk: None

✓ COMPLIANT
  [immutable_entries] Cache entries are set once, never mutated
    Evidence: All set() calls use cache.set(key, value); no cache[key] = updates found
    Risk: None

⚠ CONCERN
  [enable_rerank_in_key] Cache key includes enable_rerank flag (ADR-002)
    Evidence: [api_middleware.py:110] req_dict = {"query": ..., "enable_rerank": ...}
    Status: Implemented correctly ✓

✗ BUG — CRITICAL
  [config_invalidation] Config update does not clear cache (ADR-006 missing)
    Evidence: [api.py:280-290] PUT /config handler updates _config but never calls cache.clear()
    Expected: cache.clear() after config update
    Impact: Users change config, cached responses still use old config
    Severity: CRITICAL (data correctness violation)
    Fix: Add line after config update: if _cache: _cache.clear()

⚠ CONCERN
  [fail_open_logging] Cache errors logged at INFO instead of WARNING
    Evidence: [hybrid_rag/cache.py:185] logger.info(f"Cache error: {e}")
    Expected: logger.warning(...) for fail-open errors
    Impact: Low — doesn't break functionality, but hides issues from monitoring

SUMMARY:
- 2 Compliant ✓
- 2 Concerns ⚠ (non-blocking)
- 1 Critical Bug ✗ (must fix before merge)

RECOMMENDATION: REQUEST CHANGES — Fix BUG #1 (config invalidation) before merge
```

---

## Model 2: Architecture & Performance Audit

**Assign to:** GPT-4 (or equivalent architecture-focused model)

### Prompt

```
ARCHITECTURE & PERFORMANCE AUDITOR
==================================

You audit for: Cache stampede, hit rate, latency patterns, resource efficiency, scaling.

SPECIFICATIONS TO VERIFY:
1. Three-layer strategy correctly implemented (L1 response, L2 embedding, L3 config)
2. Cache stampede monitored/handled (popular query miss → concurrent requests)
3. Hit rate targets achievable (40-60% for realistic distributions)
4. Latency improvement significant (cache hit << live retrieval)
5. LRU eviction prevents unbounded cache growth
6. TTL tuning appropriate for ingest frequency

CODE TO AUDIT:
- File: hybrid_rag/cache.py
  Focus: InMemoryCache TTLCache configuration, stats tracking (hit/miss counters)
- File: api_middleware.py
  Focus: Middleware adds minimal overhead, cache key generation efficient
- File: api.py
  Focus: Cache initialization from CacheSettings, TTL selection, max_size configuration

ARCHITECTURE QUESTIONS:
1. Three-Layer Strategy (ADR-001):
   - Is L2 (embedding cache) inside HybridRetriever or global?
   - Is L3 (config cache) in _config global or cache backend?
   - Are layers properly separated (L1 doesn't know about L2/L3)?

2. Cache Stampede Scenario (ADR-005):
   - Popular query misses at time T. 100 concurrent requests arrive immediately after.
   - How many times does retriever run? (Ideal: 1, Current: ???)
   - Is there request coalescing? (Defer lock-based fix to v1.1 per plan)
   - MVP monitoring: GET /cache/stats tracks latency spike? (yes/no/partial)

3. Hit Rate Analysis:
   - For query distribution Q (80% Zipf): expected hit rate?
   - TTL=24h: is hit rate maintained? Or do frequent ingest clears prevent warming?
   - Ingest type='add' vs 'update': does selective clear help?

4. Performance Overhead:
   - Middleware adds latency? (cache key generation: ~1-5ms per request)
   - Is this acceptable? (Must be <5ms for cache hit to be useful)

5. Cache Eviction:
   - max_size=10000: at what point does LRU kick in?
   - Under realistic load, does cache thrash (high eviction rate)?
   - Is LRU fair (don't evict frequently-used items)?

REPORT FINDINGS:
[Your findings in structured format below]
```

### Model 2 Output Template

```
ARCHITECTURE & PERFORMANCE AUDIT REPORT
=======================================

Auditor: [Model name]
Date: [timestamp]
Spec Version: 20260420-caching-blueprint

FINDINGS:

✓ COMPLIANT
  [three_layer_separation] Layers properly separated
    Evidence: L1 in api_middleware.py, L2 inside HybridRetriever, L3 global _config
    Performance impact: ✓ Minimal (no coupling)

⚠ CONCERN
  [cache_stampede_fix] Request coalescing not implemented (deferred to v1.1)
    Evidence: [plan.yaml] "defer lock-based stampede fix to v1.1"
    Current state: MVP monitoring only (GET /cache/stats)
    Risk: Popular query miss → 100 concurrent requests hit retriever
    Impact: CPU spike, possible timeouts
    Mitigation: TTL jitter could reduce overlap; consider for v1.0.1

✓ COMPLIANT
  [hit_rate_achievable] Target 40-60% hit rate feasible
    Evidence: Real query distributions (Zipf 80/20) → 40-50% hit rate expected
    With selective ingest clear (type='add'): hit rate maintained

✓ COMPLIANT
  [latency_improvement] 5-10x speedup expected
    Evidence: Live retrieval 200-1000ms, cache hit <5ms
    Calculation: (500ms / 2ms) = 250x theoretical max

⚠ CONCERN
  [middleware_overhead] Cache key generation latency
    Evidence: SHA-256 of JSON → ~1-3ms per request
    Expected: <5ms for cache hit to be beneficial
    Status: ✓ Acceptable (cache hit is still 100x faster than live)

✓ COMPLIANT
  [lru_eviction] LRU properly evicts oldest used
    Evidence: [hybrid_rag/cache.py:155] cachetools.TTLCache with LRU
    At max_size=10000: fair eviction of least-recently-used

SUMMARY:
- 4 Compliant ✓
- 2 Concerns ⚠ (documented in plan)
- 0 Bugs ✗

RECOMMENDATION: APPROVE — Architecture sound; known trade-offs documented
```

---

## Model 3: Error Handling & Resilience Audit

**Assign to:** Gemini (or equivalent error-handling-focused model)

### Prompt

```
ERROR HANDLING & RESILIENCE AUDITOR
===================================

You audit for: Exception handling, edge cases, cascading failures, observability.

SPECIFICATIONS TO VERIFY:
1. Cache errors never crash API (fail-open)
2. TTL expiration works correctly (entries removed after TTL)
3. Concurrent clear() doesn't corrupt ongoing operations
4. Stats endpoint is robust (never errors, always returns valid JSON)
5. Logging is comprehensive (info for operations, warning for failures)
6. Timeout behavior defined (what if cache backend hangs?)

CODE TO AUDIT:
- File: hybrid_rag/cache.py
  Focus: Exception handling in get/set/delete/clear, TTL logic, stats atomicity
- File: api_middleware.py
  Focus: Try-except around cache operations, graceful degradation on cache failure
- File: api.py
  Focus: Cache initialization error handling, stats endpoint robustness

ERROR HANDLING QUESTIONS:
1. Exception Handling Coverage:
   - Find all try/except blocks. For each:
     - What exceptions are caught? (specific vs bare except)
     - What level is logged? (DEBUG/INFO/WARNING/ERROR)
     - Does execution continue or fail? (fail-open?)
   
2. TTL Expiration:
   - How are expired entries cleaned up? (cachetools.TTLCache handles automatically)
   - What if TTL clock is wrong? (system clock skew)
   - Is expiration tested in tests?

3. Concurrent Failure Scenarios:
   - Thread A calls clear() while Thread B calls get()
   - Thread C calls set() while Redis connection drops
   - Result: Do they deadlock, crash, or gracefully degrade?

4. Stats Endpoint Robustness:
   - GET /cache/stats: can it ever error?
   - If cache backend is down, what does stats return?
   - Expected: Always returns valid JSON with current state (not error)

5. Logging Coverage:
   - Search for logger.info/warning/error/debug calls
   - Is every cache operation logged? (at appropriate level)
   - Are user-facing errors clear? (not cryptic stack traces)

6. Observable Failure Modes:
   - Redis connection failure: how is it detected? (timeout, exception)
   - Cache key collision: how is it handled?
   - Max size reached: is it logged?

REPORT FINDINGS:
[Your findings in structured format below]
```

### Model 3 Output Template

```
ERROR HANDLING & RESILIENCE AUDIT REPORT
========================================

Auditor: [Model name]
Date: [timestamp]
Spec Version: 20260420-caching-blueprint

FINDINGS:

✓ COMPLIANT
  [fail_open_pattern] Cache errors don't crash API
    Evidence: [api_middleware.py:95-110] All cache.get/set wrapped in try-except
    Fallback: Returns None (cache miss), continues to retriever
    Logging: [hybrid_rag/cache.py:88] logger.warning("Cache operation failed: {e}")

✓ COMPLIANT
  [ttl_expiration] Entries expire after TTL
    Evidence: [hybrid_rag/cache.py:40] cachetools.TTLCache(maxsize, ttl=ttl_seconds)
    Tested: [quality/test_caching_functional.py:200] test_cache_entry_expires_after_ttl
    Coverage: ✓

⚠ CONCERN
  [concurrent_clear] Concurrent clear() during ongoing get() could race
    Evidence: [hybrid_rag/cache.py:120-130] clear() doesn't acquire lock during iteration
    Risk: Thread A iterates dict, Thread B clears it → RuntimeError
    Mitigation: Lock held for clear() atomic operation?
    Suggestion: Verify lock covers entire clear() operation

✓ COMPLIANT
  [stats_robustness] Stats endpoint always returns valid JSON
    Evidence: [api.py:420] GET /cache/stats wraps in try-except, returns 200 always
    No exceptions propagate; cache stats reported truthfully even if backend down

✗ BUG — IMPORTANT
  [missing_timeout_config] Redis client has no timeout configured
    Evidence: [hybrid_rag/cache.py:180] redis.Redis(...) missing timeout parameter
    Impact: If Redis hangs, client waits forever (API hangs)
    Expected: timeout=5s in Redis client initialization
    Fix: redis.Redis(..., socket_connect_timeout=5, socket_timeout=5)

✓ COMPLIANT
  [observable_failures] Log levels appropriate
    Evidence: cache misses logged at DEBUG, errors at WARNING, initialization at INFO
    Monitoring-friendly: ops teams can grep for WARNING to find real issues

SUMMARY:
- 4 Compliant ✓
- 1 Concern ⚠ (acceptable if documented)
- 1 Bug ✗ (IMPORTANT — should fix)

RECOMMENDATION: REQUEST CHANGES — Add timeout to Redis client initialization
```

---

## Phase 2: Triage & Consolidation

**Steps:**

1. **Gather all three reports** (from Model 1, 2, 3)
2. **Identify overlaps & disagreements:**
   - If all three agree on a finding → AUTHORITATIVE (merge into consolidated list)
   - If two agree → LIKELY BUG (needs human confirmation)
   - If one alone finds it → NEEDS INVESTIGATION (could be false positive)

3. **Consolidate into master findings list:**

```
MASTER AUDIT FINDINGS (Consolidated)
====================================

CRITICAL BUGS (Fix before merge):
1. [Model 1 + 2 agree] Config invalidation missing (ADR-006)
   - Evidence: api.py line 280-290
   - Fix: Add cache.clear() after config update
   - Tests affected: test_config_invalidates_cache

2. [Model 3 only] Redis client missing timeout
   - Evidence: hybrid_rag/cache.py line 180
   - Fix: Add socket_connect_timeout=5, socket_timeout=5
   - Tests affected: test_redis_timeout

IMPORTANT ISSUES (Discuss, decide fix priority):
1. [Model 2 + 3] Cache stampede not fully fixed
   - Status: Documented as v1.1 work
   - Mitigation: MVP monitoring via stats endpoint
   - Decision: Accept for MVP (proceed) or implement lock-based coalescing (v1.0)?

2. [Model 3] Concurrent clear() could race
   - Risk: Low (only during cache clear, which is rare)
   - Fix: Verify lock coverage in clear() operation

SUGGESTIONS (Nice-to-have, non-blocking):
1. [Model 1] Cache error logging at INFO instead of WARNING
   - Current: logger.info(f"Cache error: {e}")
   - Suggested: logger.warning(...) for better observability
   - Impact: Cosmetic (doesn't affect functionality)
```

---

## Phase 3: Fix Execution

For each bug found:

1. **Write regression test** (test that reproduces the bug)
2. **Implement fix** (code change)
3. **Re-run functional + integration tests** (verify fix doesn't break anything)
4. **Update audit report** (mark as "FIXED")

---

## Phase 4: Final Sign-Off

Once all bugs fixed:

```
FINAL AUDIT SIGN-OFF
====================

Project: Hybrid RAG Caching System (20260420-caching-blueprint)
Audit Date: [date]
Auditors: Model 1 (Security), Model 2 (Architecture), Model 3 (Resilience)

RESULTS:
- Spec Compliance: ✓ 95%+ (8/8 core requirements met)
- Critical Bugs Found & Fixed: 2
- Important Issues Documented: 2
- Suggestions (non-blocking): 1

APPROVAL: ✓ APPROVED FOR PRODUCTION

Status: Ready to merge
Next review: After v1.1 stampede fix implementation
```

---

## Running the Audit

**Quick command:**

```bash
# For each model, copy the model-specific prompt and run in the model's chat interface
# Report back findings in the output template format
# Consolidate findings manually (or use this script template)

cat << 'EOF' > quality/consolidate_audit.py
"""Consolidate audit findings from three models."""
# Parse three audit reports (JSON or markdown)
# Identify overlaps
# Generate master findings list
# Output to quality/results/audit_consolidated_YYYY-MM-DD.json
EOF
```

**Expected time:** 60-90 minutes total (20-30 min per model)

---

## Reference: Spec Sections to Verify

Map each audit finding to spec section:

| Finding | Reference Section |
|---------|-------------------|
| Cache key canonicalization | ADR-002, § 3 Data Architecture |
| Config invalidation | ADR-006, § Cache Invalidation Flow |
| Fail-open behavior | § Guiding Principles |
| Thread safety | § 3.2 InMemoryCache |
| Redis connection | § 3.5 RedisCache |
| Cache stampede | ADR-005, § Cross-Cutting Concerns |
