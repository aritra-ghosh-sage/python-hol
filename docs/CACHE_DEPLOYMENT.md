# Hybrid RAG Cache Deployment Guide

**Applicable to:** Hybrid RAG v0.1.x

## Overview

The live system has **two implemented cache layers**:

- **L1 query cache** backed by `hybrid_rag.cache.CacheBackend`
- **L2 embedding cache** inside `HybridRetriever`

ChromaDB is persistent storage, not a cache layer.

## Runtime Design

### L1 Query Cache

The L1 cache stores full retrieval results and is shared across the API layer.

- `api_middleware.py` caches `POST /retrieve` HTTP responses
- `api.py` caches retrieval results in `_shared_retrieve_documents()` so REST and WebSocket retrieval use the same cache identity

The cache key is derived from:

1. normalized query
2. effective rerank mode
3. config fingerprint
4. corpus version

### L2 Embedding Cache

`HybridRetriever` stores query embeddings in an in-process LRU cache. This avoids repeated encoder work for repeated queries, but it does not store retrieval responses.

## Backends

The configurable backend is for **L1 only**.

| Backend | Recommended use |
|---|---|
| `memory` | local development, tests, single-instance deployments |
| `redis` | multi-instance or persistent deployments |

## Environment Variables

```bash
# Common
CACHE_BACKEND=memory
CACHE_TTL_SECONDS=3600
CACHE_KEY_PREFIX=hybrid_rag_cache:

# In-memory only
CACHE_MAX_SIZE=10000

# Redis only
REDIS_URL=redis://localhost:6379/0
```

Production Redis notes:

- use `rediss://` in production
- require Redis authentication
- prefer a dedicated Redis DB or key prefix

## Local Verification

```bash
# Health
curl -s http://localhost:8000/health | jq .

# Layered cache stats
curl -s http://localhost:8000/cache/stats | jq .

# Repeated query to trigger L1 activity
for i in 1 2 3; do
  curl -s -X POST http://localhost:8000/retrieve \
    -H "Content-Type: application/json" \
    -d '{"query":"offline maps"}' > /dev/null
done

curl -s http://localhost:8000/cache/stats | jq '.l1_query_cache'
curl -s http://localhost:8000/cache/stats | jq '.l2_embedding_cache'
```

Expected checks:

- `/health` returns `{"status":"healthy","retriever_ready":"yes"}` once the retriever is initialized
- `/cache/stats` returns `l1_query_cache`, `l2_embedding_cache`, `backend_health`, and `timestamp`
- repeated identical queries should increase L1 hits and usually L2 hits

## Invalidation Rules

| Event | Behavior |
|---|---|
| `PUT /config` success | clear L1 query cache |
| `POST /documents` with `ingest_type="update"` | clear L1 query cache |
| `POST /documents` with `ingest_type="add"` | preserve existing L1 entries |
| backend failure | fail open and continue retrieval without cache |

L2 embedding cache is process-local and not explicitly cleared on config changes.

## Reading `/cache/stats`

Example response shape:

```json
{
  "l1_query_cache": {
    "backend": "memory",
    "hits": 2,
    "misses": 1,
    "hit_rate": 0.667,
    "size": 1,
    "max_size": 10000,
    "ttl_seconds": 3600,
    "corpus_version": "gen0.n1"
  },
  "l2_embedding_cache": {
    "hits": 2,
    "misses": 1,
    "hit_rate": 0.667,
    "size": 1,
    "capacity": 5000
  },
  "backend_health": {
    "connected": true,
    "latency_ms": null,
    "fallback_active": false,
    "error": null
  },
  "timestamp": "2026-04-22T10:30:45.123456Z"
}
```

Operational focus:

- inspect `.l1_query_cache.hit_rate` for shared query-cache effectiveness
- inspect `.l2_embedding_cache.hit_rate` for encoder reuse
- inspect `.backend_health` for Redis connectivity or fail-open fallback

## Troubleshooting

### L1 hit rate stays at 0

Check that:

- you are sending identical query payloads
- the backend is healthy
- the workload is repeating requests rather than all unique queries

```bash
curl -s http://localhost:8000/cache/stats | jq '.backend_health'
curl -s http://localhost:8000/cache/stats | jq '.l1_query_cache'
```

### Redis configured but cache falls back

Check:

```bash
echo "$REDIS_URL"
redis-cli -u "$REDIS_URL" PING
curl -s http://localhost:8000/cache/stats | jq '.backend_health'
```

If production uses Redis, ensure the URL uses `rediss://` and includes credentials.

### Results look stale after data changes

Use `ingest_type="update"` for bulk replacements and `PUT /config` for config changes. Both clear L1.

## Related Docs

- [LIBRARY_DESIGN.md](./LIBRARY_DESIGN.md) — architecture and cache design
- [API_INTEGRATION.md](./API_INTEGRATION.md) — endpoint contracts and WebSocket message shapes
- [DEPLOYMENT_PRODUCTION.md](./DEPLOYMENT_PRODUCTION.md) — broader deployment checklist
