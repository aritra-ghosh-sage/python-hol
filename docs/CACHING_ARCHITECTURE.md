# Hybrid RAG — Caching Architecture Reference

**Document Version:** 1.0  
**Last Updated:** 2026-05-01  
**Task:** OPTB-013 Wave 7 documentation closeout  
**Audience:** Operators, backend developers  
**Applicable to:** Hybrid RAG v0.1.0+ (post-OPTB-008 layered stats schema)

> **Purpose.** This document is the single authoritative reference for the Hybrid RAG two-layer caching architecture. It supersedes the caching narrative sections in `CACHE_DEPLOYMENT.md` and `LIBRARY_DESIGN.md`, which remain in place for deployment procedures and library design rationale respectively.

---

## Table of Contents

1. [Architecture Overview — Two-Layer, Two-Owner Model](#1-architecture-overview--two-layer-two-owner-model)
2. [L1 Query Cache (Middleware Layer)](#2-l1-query-cache-middleware-layer)
3. [L2 Embedding Cache (Retriever Layer)](#3-l2-embedding-cache-retriever-layer)
4. [Cache Stats Schema — `GET /cache/stats`](#4-cache-stats-schema--get-cachestats)
   - 4.1 [`l1_query_cache`](#41-l1_query_cache-section)
   - 4.2 [`l2_embedding_cache`](#42-l2_embedding_cache-section)
   - 4.3 [`backend_health`](#43-backend_health-section)
   - 4.4 [`timestamp`](#44-timestamp-field)
5. [corpus_version — Redis-Backed Behavior and Fallback Semantics](#5-corpus_version--redis-backed-behavior-and-fallback-semantics)
6. [Node-Local L2 Scope and Thread-Safety Caveats](#6-node-local-l2-scope-and-thread-safety-caveats)
7. [X-Cache Response Header Contract](#7-x-cache-response-header-contract)
8. [Fail-Open and Fallback Behavior](#8-fail-open-and-fallback-behavior)
9. [Cache Invalidation Rules](#9-cache-invalidation-rules)
10. [Migration Notes — Flat → Layered Stats Schema (OPTB-008)](#10-migration-notes--flat--layered-stats-schema-optb-008)
11. [Cross-Issue Decisions (Resolved)](#11-cross-issue-decisions-resolved)
12. [Quick Reference](#12-quick-reference)

---

## 1. Architecture Overview — Two-Layer, Two-Owner Model

Hybrid RAG implements a **two-layer caching system with distinct ownership boundaries**. Each layer is owned and operated by a different component, and neither layer has shared cache entries with the other.

```
┌─────────────────────────────────────────────────────────┐
│  HTTP Request  POST /retrieve                           │
│                                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │  L1: QueryCacheMiddleware  (api_middleware.py)  │   │
│  │                                                 │   │
│  │  • Owner:   HTTP middleware layer               │   │
│  │  • Caches:  Full HTTP response bodies           │   │
│  │  • Backends: InMemoryCache or RedisCache        │   │
│  │  • Key:     Request JSON-derived cache key      │   │
│  │              + enable_rerank                    │   │
│  │  • Scope:   HTTP /retrieve only                 │   │
│  │  • Note:    WebSocket bypasses this middleware; │   │
│  │              shared retrieval caching happens   │   │
│  │              via _shared_retrieve_documents     │   │
│  └──────────────────┬──────────────────────────────┘   │
│                     │ L1 MISS only                      │
│  ┌──────────────────▼──────────────────────────────┐   │
│  │  L2: HybridRetriever   (hybrid_rag/retriever.py)│   │
│  │                                                 │   │
│  │  • Owner:   Retriever layer                     │   │
│  │  • Caches:  Sentence-transformer embeddings     │   │
│  │  • Backend: cachetools.LRUCache (always local)  │   │
│  │  • Key:     SHA-256(query_text)                 │   │
│  │  • Scope:   In-process only, never distributed  │   │
│  └──────────────────┬──────────────────────────────┘   │
│                     │ L2 MISS only                      │
│  ┌──────────────────▼──────────────────────────────┐   │
│  │  L3: ChromaDB Vector Store (persistent)         │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

### Ownership summary

| Layer | Name | Owner | Configurable Backend | Distributed? |
|-------|------|-------|---------------------|--------------|
| L1 | Query Cache | `QueryCacheMiddleware` in `api_middleware.py` | Yes (`memory` or `redis`) | Yes (via Redis) |
| L2 | Embedding Cache | `HybridRetriever` in `hybrid_rag/retriever.py` | No | **Never** |
| L3 | Vector Store | ChromaDB | N/A | Out of scope |

> **Ownership note.** L1 and L2 are fully decoupled. A cache miss at L1 triggers retrieval at the application layer; L2 is consulted by the retriever regardless of L1 status. L2 is **not** a fallback for L1 — the two layers cache different things (responses vs. embeddings).

---

## 2. L1 Query Cache (Middleware Layer)

**Owner:** `QueryCacheMiddleware` (`api_middleware.py`)

L1 caches **complete HTTP response bodies** for `POST /retrieve` requests. A cache hit short-circuits the entire retrieval pipeline — the retriever, reranker, and ChromaDB are never touched.

### Cache key identity

The L1 cache key is a SHA-256 hash of four inputs:

| Input | Source | Notes |
|-------|--------|-------|
| `query` | Request body, whitespace-normalised | Equivalent queries (same normalised form) share a key |
| `enable_rerank` | Request param → `_config.enable_rerank` default | Requests with different rerank values are cached separately (ADR-002) |
| `config_fingerprint` | SHA-256 of serialised `_config` retrieval fields | Changes on every `PUT /config` success |
| `corpus_version` | `_corpus_version` module variable | Changes on explicit invalidation events (see §5) |

**Transport is excluded.** REST `POST /retrieve` and WebSocket `/ws/chat` calls that produce identical key inputs share the same L1 cache entry (see `CACHE_DEPLOYMENT.md` §Cross-Channel Cache Architecture for the shared facade details).

### Configurable backends

| Backend | Class | Use case |
|---------|-------|----------|
| `InMemoryCache` | `hybrid_rag.cache.InMemoryCache` | Development, single-process deployments |
| `RedisCache` | `hybrid_rag.cache.RedisCache` | Multi-instance production |

Backend is selected at startup via `CACHE_BACKEND` environment variable. For deployment procedures and env-var reference see `CACHE_DEPLOYMENT.md`.

### Eligibility gate

The middleware only attempts to cache a request when all of the following are true:

- HTTP method is `POST`
- Path is exactly `/retrieve`
- `Content-Type` is `application/json` or `application/*+json` (RFC 6839)
- Path is **not** in `excluded_paths` (default: `/health`, `/config`, `/ingest`, `/documents`, `/documents/sources`, `/cache/stats`)

All eligibility checks are header-only and occur before any request body I/O.

---

## 3. L2 Embedding Cache (Retriever Layer)

**Owner:** `HybridRetriever` (`hybrid_rag/retriever.py`)

L2 caches **sentence-transformer embedding vectors** keyed by `SHA-256(query_text)`. An L2 hit avoids a model inference call.

### Backend

L2 always uses `cachetools.LRUCache` — an in-process, node-local LRU store. There is no option to configure a distributed L2 backend. This is an intentional design decision (ADR-005): embedding vectors are cheap to recompute relative to the operational complexity of a distributed embedding cache.

### Scope

| Property | Value |
|----------|-------|
| Storage | In-process heap memory |
| Distribution | **None** — node-local only |
| Persistence | Lost on process restart |
| Key | `SHA-256(query_text)` |
| Eviction | LRU (Least Recently Used) |
| Capacity | Configurable; reported as `l2_embedding_cache.capacity` in stats |

> See §6 for thread-safety and multi-worker caveats.

---

## 4. Cache Stats Schema — `GET /cache/stats`

**This is the post-OPTB-008 layered schema.** The pre-OPTB-008 flat schema is no longer served. See §10 for migration guidance.

### Full response example

```json
{
  "l1_query_cache": {
    "backend":        "redis",
    "hits":           1042,
    "misses":         317,
    "hit_rate":       0.767,
    "size":           284,
    "max_size":       100000,
    "ttl_seconds":    86400,
    "corpus_version": "gen2.n108"
  },
  "l2_embedding_cache": {
    "hits":     891,
    "misses":   204,
    "hit_rate": 0.814,
    "size":     198,
    "capacity": 512
  },
  "backend_health": {
    "connected":       true,
    "latency_ms":      1.3,
    "fallback_active": false,
    "error":           null
  },
  "timestamp": "2026-05-01T14:22:05.341Z"
}
```

---

### 4.1 `l1_query_cache` section

Reports the state of the middleware-owned L1 query cache.

| Field | Type | Description |
|-------|------|-------------|
| `backend` | `"memory"` \| `"redis"` | Active cache backend. Set at startup from `CACHE_BACKEND` env var; does not change at runtime. |
| `hits` | integer ≥ 0 | Cumulative L1 cache hits since process start. Incremented whenever a request is served from the L1 cache without calling the retriever. |
| `misses` | integer ≥ 0 | Cumulative L1 cache misses since process start. Incremented for every cacheable request that was not found in L1. |
| `hit_rate` | float 0.0–1.0 | `hits / (hits + misses)`. Returns `0.0` when no requests have been processed yet (avoids division-by-zero). |
| `size` | integer ≥ 0 | Current number of entries stored in the L1 cache. For `redis` backend this reflects the count of keys with the configured prefix. |
| `max_size` | integer | Configured maximum entry capacity. For `memory` backend this is `CACHE_MAX_SIZE`. For `redis` backend this reflects the configured limit; Redis itself enforces memory via `maxmemory-policy`. |
| `ttl_seconds` | integer | Entry TTL in seconds. Entries older than this are considered stale and will not be served. `0` means indefinite. |
| `corpus_version` | string | Active corpus version token (e.g. `"gen2.n108"`). This token is embedded in every L1 cache key; when it changes, previously cached entries are effectively orphaned and will be ignored (see §5). |

**Counter scope.** `hits` and `misses` are process-local. Under a multi-worker deployment each worker reports its own counters. When using Redis, cache lookups from all workers update the same Redis keys, but the in-process hit/miss counters in each worker only reflect that worker's requests.

---

### 4.2 `l2_embedding_cache` section

Reports the state of the retriever-owned L2 embedding cache.

| Field | Type | Description |
|-------|------|-------------|
| `hits` | integer ≥ 0 | Cumulative L2 cache hits since process start. Incremented when a query's embedding vector is found in the LRU cache, avoiding a model inference call. |
| `misses` | integer ≥ 0 | Cumulative L2 cache misses since process start. |
| `hit_rate` | float 0.0–1.0 | `hits / (hits + misses)`. Returns `0.0` before any retrieval has been attempted. |
| `size` | integer ≥ 0 | Current number of embedding vectors held in the LRU cache. |
| `capacity` | integer | Maximum number of embedding vectors the LRU cache can hold. When `size` reaches `capacity`, the least-recently-used entry is evicted. |

**Scope note.** All L2 fields reflect **only the current worker's** L2 cache state. Under multi-worker deployments, L2 caches are not shared — see §6.

---

### 4.3 `backend_health` section

Reports whether the L1 cache backend is reachable and whether the system is operating in fallback mode.

| Field | Type | Description |
|-------|------|-------------|
| `connected` | boolean | `true` when the backend responded successfully to the most recent health check ping. For `memory` backend this is always `true`. For `redis` this reflects the result of a live PING to the Redis server. |
| `latency_ms` | float \| null | Round-trip time in milliseconds for the health check operation. `null` when the health check could not be completed (e.g. connection refused) or when backend is `memory`. |
| `fallback_active` | boolean | `true` when the system is operating without its intended cache backend — either because the `_cache` object is `None` (initialization failed) or because the backend raised an exception during a recent operation. See §8 for fallback semantics. |
| `error` | string \| null | Human-readable error message from the most recent failed health check. `null` when `connected=true`. This field is informational; do not parse its format programmatically. |

> **Alerting recommendation.** Monitor `fallback_active` transitions via structured logs (event name `cache.fallback_activated` / `cache.fallback_deactivated`). The field itself is sampled at request time, so polling `/cache/stats` is a valid but higher-latency signal. See §8.

---

### 4.4 `timestamp` field

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | ISO-8601 string (UTC) | UTC timestamp at which these statistics were captured. Format: ISO-8601 UTC, for example `YYYY-MM-DDTHH:MM:SS.sssZ` or `YYYY-MM-DDTHH:MM:SS.sss+00:00`. Use this to detect stale dashboards or caching of the `/cache/stats` response itself. |

---

## 5. corpus_version — Redis-Backed Behavior and Fallback Semantics

### Token format

```
gen{N}.n{count}
```

| Component | Meaning |
|-----------|---------|
| `N` | Monotonic generation counter. Incremented on each explicit invalidation event. Starts at `0` on process start. |
| `count` | Live document count read from ChromaDB at token-build time. Reflects corpus size at the moment the token was last built. |

**Examples:** `gen0.n1` (initial load, 1 document), `gen1.n42` (after first `PUT /config`, 42 documents), `gen2.n108` (after second explicit invalidation, 108 documents).

### When the token changes

| Event | N | count | Effect on L1 cache |
|-------|---|-------|-------------------|
| `PUT /config` succeeds | **Incremented** | Rebuilt | All previous L1 entries are orphaned (stale key suffix) |
| `POST /documents` with `ingest_type=update` | **Incremented** | Rebuilt | Full L1 clear + orphaned by new token |
| `POST /documents` with `ingest_type=add` | Stable | Rebuilt on next request | L1 cache preserved; previously cached results remain valid until TTL |
| TTL expiry | No change | No change | Individual entries evicted by backend |
| Process restart | Reset to `0` | Rebuilt at startup | In-process `_cache_generation` is reset; new token built from ChromaDB |

> **Eventual consistency on `ingest_type=add`.** After an incremental document addition, queries that were cached before the addition may return pre-add results until their TTL expires. This is intentional and documented in the approved cache-consistency policy (`docs/plan/20260420/CACHE-CONSISTENCY-POLICY.md`).

### Fallback: ChromaDB count unavailable

If `_build_corpus_version_token()` cannot read the collection document count from ChromaDB (e.g. ChromaDB is temporarily unavailable at startup), the token falls back to:

```
gen{N}.n0
```

The `n0` suffix is stable and unambiguous — it is never produced by a healthy collection with at least one document. Operators can use `n0` in `corpus_version` as a signal that the document count could not be read at token-build time.

### Multi-process note

`_cache_generation` is a **process-local** integer in `api.py`. Under multi-worker deployments (e.g. `uvicorn --workers 4`):

- Each worker starts at `_cache_generation = 0` on spawn.
- Invalidation events (config update, document update) increment only the counter of the worker that handled the request.
- **Workers do not synchronise their generation counters.** A `PUT /config` call handled by worker A increments A's counter and clears A's in-memory cache (if backend is `memory`). Workers B, C, D are unaffected until they receive their own invalidation event.

**With a Redis L1 backend**, the L1 cache itself is shared, so the explicit `cache.clear()` call performed by the handling worker flushes entries for all workers. However, `corpus_version` tokens across workers may still diverge for a brief window until each worker handles a request that rebuilds its token. In practice the window is bounded by the rate of incoming requests.

> **Recommendation for multi-worker production.** Use `CACHE_BACKEND=redis` so that explicit L1 clears are effective across all workers. Do not rely on `corpus_version` token equality across workers as an operational invariant.

---

## 6. Node-Local L2 Scope and Thread-Safety Caveats

### Thread safety

`cachetools.LRUCache` is **not thread-safe on its own**. `HybridRetriever` wraps every L2 cache read and write with `threading.Lock`, making the embedding cache safe for concurrent use within a single process.

> **Do not bypass the `HybridRetriever` methods to access the L2 cache directly** — doing so circumvents the lock and may produce silent data races or corrupted LRU state.

### Multi-worker scope

Because L2 is always in-process, each uvicorn worker has an independent L2 cache instance:

```
Worker 1: L2 cache (512 entries max) ──┐
Worker 2: L2 cache (512 entries max) ──┼──  NOT shared
Worker 3: L2 cache (512 entries max) ──┤
Worker 4: L2 cache (512 entries max) ──┘
```

Consequences:

- **No L2 warm-up sharing.** Embeddings computed by worker A are not available to worker B.
- **Hit rates in `/cache/stats` are per-worker.** A `hit_rate` of `0.81` reported by one worker does not imply that other workers have a similar rate.
- **Cold starts cause repeated model inference.** After a rolling restart, each worker's L2 cache starts empty. Expect a temporary increase in model inference latency until caches warm up.

### Why L2 is intentionally not distributed (ADR-005)

Distributing embedding vectors would require serialising and deserialising numpy arrays over the network. The operational overhead (serialisation format, network latency, cache invalidation for model upgrades) outweighs the benefit, given that embedding inference on MiniLM models is sub-10 ms on CPU. L2 is designed as a within-process hot-path optimisation, not a distributed shared store.

---

## 7. X-Cache Response Header Contract

**Header name:** `X-Cache`  
**Set by:** `QueryCacheMiddleware`  
**Applicable to:** `POST /retrieve` responses only  

| Value | Meaning |
|-------|---------|
| `HIT` | Response was served directly from L1 cache. Retriever was not called. |
| `MISS` | Response was computed fresh (retriever was called) and has been stored in L1 cache. |
| `ERROR` | Response status is non-200 (not cached), or a cache access error occurred during the request. |

**Paths where `X-Cache` is NOT set:** `GET` requests and all excluded paths (`/health`, `/config`, `/ingest`, `/documents`, `/documents/sources`, `/cache/stats`).

**WebSocket (`/ws/chat`):** Cache activity is reflected in `GET /cache/stats` counters (both transports share the same cache backend), but the WebSocket message schema does not include a cache-status field. `X-Cache` is an HTTP-only header.

### Usage example

```bash
# First request — MISS (response computed and cached)
curl -i -X POST http://localhost:8000/retrieve \
  -H "Content-Type: application/json" \
  -d '{"query": "How do I enable offline maps?"}' \
  | grep X-Cache
# X-Cache: MISS

# Second request — HIT (served from cache)
curl -i -X POST http://localhost:8000/retrieve \
  -H "Content-Type: application/json" \
  -d '{"query": "How do I enable offline maps?"}' \
  | grep X-Cache
# X-Cache: HIT
```

---

## 8. Fail-Open and Fallback Behavior

### Principle

**Cache failures never propagate to API consumers.** `POST /retrieve` always returns `HTTP 200` even when the cache backend is unreachable or faulting. The cache is a performance optimisation; it is never on the critical path for correctness.

### What "fallback" means

The system enters fallback mode when either:

1. `_cache` is `None` — cache initialization failed at startup (e.g. Redis unreachable on first connect).
2. The cache backend raises an exception during a `get` or `set` operation at request time.

In both cases:

- The retriever is called as normal (no `HIT` served).
- The response is not cached (no `set` attempted, or the `set` is silently swallowed).
- `backend_health.fallback_active` is set to `true` in the next `/cache/stats` response.

### Transition logging

`_log_fallback_transition()` emits a structured log entry **only when fallback state changes**, not on every poll or request. This avoids log flooding under sustained backend unavailability.

| Event | Log event name | Log level |
|-------|---------------|-----------|
| Backend becomes unreachable | `cache.fallback_activated` | `WARNING` |
| Backend becomes reachable again | `cache.fallback_deactivated` | `INFO` |

**Cold-start spurious log.** On process restart, `_last_fallback_state` is reset to `None`. The first health-check poll after restart always emits one transition log (from `None` to whatever the current state is). This is expected and harmless.

**Multi-process note.** `_last_fallback_state` is process-local. Under a 4-worker deployment a Redis backend failure produces 4 `cache.fallback_activated` log lines — one per worker. Operators should correlate by worker PID, not by event count.

### Multi-instance degraded-fallback decision (resolved)

Redis degraded fallback in multi-instance production is **acceptable and does not block rollout**. Each instance degrades independently with no impact on API availability (fail-open). The recommended mitigation is alerting on `cache.fallback_activated` structured log events. See §11 for the full cross-issue decision record.

---

## 9. Cache Invalidation Rules

| Trigger | L1 action | L2 action | `corpus_version` |
|---------|-----------|-----------|-----------------|
| `PUT /config` succeeds | **Full clear** | No change | N incremented; token rebuilt |
| `POST /documents` with `ingest_type=update` | **Full clear** | No change | N incremented; token rebuilt |
| `POST /documents` with `ingest_type=add` | **Preserve** | No change | N stable; count rebuilt on next request |
| TTL expiry | Evict expired entries (backend-managed) | N/A (LRU only) | No change |
| Process restart | Lost (memory) / Preserved (redis) | Lost (always) | Reset to `gen0.n{count}` |
| Redis connection failure | Fail-open; entries inaccessible | No change | No change |

> **L2 is never explicitly invalidated.** L2 keys are based on query text only and are evicted by LRU capacity pressure. Since embeddings are model-deterministic (same query + same model = same vector), there is no correctness reason to invalidate L2 on corpus or config changes.

---

## 10. Migration Notes — Flat → Layered Stats Schema (OPTB-008)

**Introduced in:** OPTB-008  
**Breaking change:** Yes — the previous flat top-level fields no longer exist.

### Before OPTB-008 (flat schema)

```json
{
  "backend":     "memory",
  "hits":        42,
  "misses":      11,
  "hit_rate":    0.79,
  "size":        38,
  "max_size":    10000,
  "ttl_seconds": 3600,
  "timestamp":   "2026-04-01T10:00:00.000Z"
}
```

### After OPTB-008 (layered schema)

```json
{
  "l1_query_cache":     { ... },
  "l2_embedding_cache": { ... },
  "backend_health":     { ... },
  "timestamp":          "..."
}
```

### Field mapping

| Old path (flat) | New path (layered) | Notes |
|----------------|--------------------|-------|
| `response.backend` | `response.l1_query_cache.backend` | |
| `response.hits` | `response.l1_query_cache.hits` | |
| `response.misses` | `response.l1_query_cache.misses` | |
| `response.hit_rate` | `response.l1_query_cache.hit_rate` | |
| `response.size` | `response.l1_query_cache.size` | |
| `response.max_size` | `response.l1_query_cache.max_size` | |
| `response.ttl_seconds` | `response.l1_query_cache.ttl_seconds` | |
| `response.timestamp` | `response.timestamp` | Promoted to top level |
| *(no equivalent)* | `response.l1_query_cache.corpus_version` | New in OPTB-008 |
| *(no equivalent)* | `response.l2_embedding_cache.*` | New in OPTB-008 |
| *(no equivalent)* | `response.backend_health.*` | New in OPTB-008 |

### Confirmed consumers

| Consumer | Calls `GET /cache/stats`? | Migration required? |
|----------|--------------------------|---------------------|
| Operator shell scripts / dashboards | Possibly — audit your own scripts | Yes — update field paths per table above |
| `frontend/src/lib/api.ts` | **No** — confirmed non-consumer | None |
| Test suite (`tests/`) | Yes — updated as part of OPTB-008 | Already migrated |

> **Frontend note.** The Hybrid RAG frontend (`frontend/src/lib/api.ts`) does **not** call `GET /cache/stats`. No frontend TypeScript type changes are required for the schema migration.

### Migration example

```python
# Before OPTB-008
stats = requests.get("/cache/stats").json()
hit_rate = stats["hit_rate"]          # KeyError in post-OPTB-008 API
backend  = stats["backend"]           # KeyError in post-OPTB-008 API

# After OPTB-008
stats = requests.get("/cache/stats").json()
hit_rate        = stats["l1_query_cache"]["hit_rate"]
backend         = stats["l1_query_cache"]["backend"]
corpus_version  = stats["l1_query_cache"]["corpus_version"]  # new
l2_hit_rate     = stats["l2_embedding_cache"]["hit_rate"]     # new
fallback_active = stats["backend_health"]["fallback_active"]  # new
```

---

## 11. Cross-Issue Decisions (Resolved)

The following decisions were deferred during implementation sprints and are now resolved. They are embedded here as the authoritative record.

### Decision 1: Response header name for cache status

**Question:** Should the cache-status response header be `X-Cache`, `X-Cache-Status`, or another name?

**Resolution:** **`X-Cache`** — already implemented and confirmed as the standard. No change required. Resolves the naming ambiguity tracked in prior review comments.

**Rationale:** `X-Cache` is the established convention used by CDNs (Varnish, Fastly, CloudFront) and is the least surprising choice for operators familiar with HTTP caching infrastructure.

---

### Decision 2: External monitors depending on flat stats schema

**Question:** Are there confirmed external monitors or dashboards that parse the pre-OPTB-008 flat `GET /cache/stats` schema and would break on the layered schema?

**Resolution:** **No confirmed external consumers.** The frontend does not call this endpoint. No external migration is required beyond operator-owned scripts. Operators should audit any scripts written before OPTB-008 using the field mapping table in §10.

---

### Decision 3: Redis degraded fallback in multi-instance production

**Question:** Does Redis fallback mode in a multi-instance deployment constitute a production blocker?

**Resolution:** **Not a blocker.** Fail-open semantics ensure no HTTP 5xx errors are surfaced to callers. Each instance degrades independently — a Redis outage causes cache misses, not request failures. The recommended operational mitigation is:

1. Alert on `cache.fallback_activated` structured log events (emitted only on state transition, not on every request).
2. Expect N log lines per worker count during a backend status change — this is normal.
3. Monitor `backend_health.fallback_active` via `/cache/stats` for dashboard visibility.

This decision **does not block rollout**.

---

## 12. Quick Reference

### Endpoint summary

| Endpoint | Cache interaction |
|----------|------------------|
| `POST /retrieve` | L1 checked (middleware). On miss, L2 checked (retriever). `X-Cache` header set. |
| `GET /ws/chat` (WebSocket) | Shares L1 cache entries with `POST /retrieve`. No `X-Cache` header on WS messages. |
| `GET /cache/stats` | Returns current L1 + L2 stats and backend health. Not cached. |
| `PUT /config` | Triggers full L1 clear + `corpus_version` increment on success. |
| `POST /documents?ingest_type=update` | Triggers full L1 clear + `corpus_version` increment. |
| `POST /documents?ingest_type=add` | Preserves L1 cache (eventual consistency until TTL). |

### Key behavioural guarantees

| Guarantee | Detail |
|-----------|--------|
| **Fail-open** | Cache errors never produce HTTP 5xx. `POST /retrieve` always returns 200. |
| **Transport parity** | REST and WebSocket share L1 cache entries. |
| **L2 always local** | L2 is in-process, never distributed, regardless of `CACHE_BACKEND`. |
| **Thread safety** | L2 LRU access is guarded by `threading.Lock` within `HybridRetriever`. |
| **Request-local rerank** | `enable_rerank` per-request override never mutates `_config` globally. |

### Environment variables (cache-related)

| Variable | Default | Purpose |
|----------|---------|---------|
| `CACHE_BACKEND` | `memory` | `memory` (InMemoryCache) or `redis` (RedisCache) |
| `REDIS_URL` | *(none)* | Required when `CACHE_BACKEND=redis` |
| `CACHE_TTL_SECONDS` | `3600` | L1 entry TTL in seconds |
| `CACHE_KEY_PREFIX` | `hybrid_rag_cache:` | Key namespace for Redis backend |
| `CACHE_MAX_SIZE` | `10000` | L1 max entry count (InMemoryCache only) |

### Diagnostic checklist

```bash
# 1. Check current cache stats (layered schema)
curl -s http://localhost:8000/cache/stats | jq .

# 2. Check L1 hit rate
curl -s http://localhost:8000/cache/stats | jq '.l1_query_cache.hit_rate'

# 3. Check corpus_version token
curl -s http://localhost:8000/cache/stats | jq '.l1_query_cache.corpus_version'

# 4. Check if fallback mode is active
curl -s http://localhost:8000/cache/stats | jq '.backend_health.fallback_active'

# 5. Inspect X-Cache header on a retrieve request
curl -si -X POST http://localhost:8000/retrieve \
  -H "Content-Type: application/json" \
  -d '{"query": "test query"}' \
  | grep -i x-cache

# 6. Force L1 invalidation (requires config change)
curl -X PUT http://localhost:8000/config \
  -H "Content-Type: application/json" \
  -d '{"enable_rerank": true}'
curl -s http://localhost:8000/cache/stats | jq '.l1_query_cache | {size, corpus_version}'
```

---

*For deployment procedures, Redis setup, and environment variable reference see [`CACHE_DEPLOYMENT.md`](./CACHE_DEPLOYMENT.md).*  
*For library design decisions and module structure see [`LIBRARY_DESIGN.md`](./LIBRARY_DESIGN.md).*  
*For observed cache performance metrics see [`CACHE_PERF_REPORT.md`](./CACHE_PERF_REPORT.md).*
