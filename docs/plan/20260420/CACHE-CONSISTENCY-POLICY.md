# CACHE-CONSISTENCY-POLICY (Wave 1)

Date: 2026-04-21  
Plan ID: 20260420-cache-gap  
Task ID: CACHE-CONSISTENCY-POLICY  
Status: Approved for implementation

## Purpose

Define one concrete cross-channel cache consistency contract for REST and WebSocket retrieval so Wave 2 (`CACHE-PARITY-IMPLEMENT`) and Wave 3 (`CACHE-PARITY-TESTS`) can proceed without ambiguity.

## Scope

- In scope:
  - WS cache participation policy
  - `ingest_type` invalidation semantics (`add` vs `update`)
  - Cache key identity inputs and parity test acceptance criteria
- Out of scope:
  - Product code changes
  - Cache backend implementation redesign

## Decision Matrix

| Decision Area | Options Considered | Final Decision | Rationale | Implementation Contract |
|---|---|---|---|---|
| WS cache participation | A) Keep WS uncached permanently. B) WS shares same L1 response cache contract as REST `/retrieve`. C) Separate WS cache. | **B: WS participates in the same logical L1 response-cache policy as REST.** | Current gap is channel divergence (REST cached through middleware; WS uncached direct retrieval). Shared policy eliminates behavior drift risk and enables one parity test matrix. | Introduce shared retrieval/cache facade used by both transports. Middleware remains HTTP entrypoint, but WS must apply equivalent key/lookup/invalidation contract through shared service. |
| `ingest_type=add` invalidation | A) Clear all L1 entries. B) Preserve cache entries (eventual consistency). | **B: Preserve existing L1 entries for `add`.** | Existing behavior and comments already define `add` as cache-preserving for bulk ingestion. This keeps cost/latency predictable and avoids unnecessary full invalidation during incremental ingest. | Both REST and WS must exhibit same post-`add` cache behavior: previously cached equivalent queries may return pre-add results until TTL expiry or explicit invalidation event. |
| `ingest_type=update` invalidation | A) Preserve cache. B) Clear all L1 entries immediately. C) Selective invalidation only. | **B: Clear all L1 entries immediately on successful `update`.** | Existing behavior in `/documents` already clears cache on `update`. Keeping full clear is practical with current architecture and avoids stale-answer uncertainty. | On successful `update`, shared cache layer clears entries once. Subsequent equivalent REST and WS requests must behave as MISS/recompute. |
| Config update invalidation (`PUT /config`) | A) No invalidation. B) Clear all L1 entries. C) Namespace version bump only. | **B: Clear all L1 entries on successful config update.** | Existing code already clears cache after config update. This aligns retrieval behavior with new config immediately and reduces mixed-policy risk. | After successful config update, both transports observe invalidation before next retrieval response. |
| Cache key identity inputs for parity | A) Query only. B) Query + rerank mode. C) Query + rerank + retrieval config/corpus identity. | **C: identity includes `query`, effective rerank mode, retrieval-config fingerprint, and corpus version token.** | Query + rerank alone is insufficient for strict cross-channel parity after config or corpus mutations. Explicit config/corpus identity enables deterministic parity assertions. | Canonical identity contract for shared retrieval cache key: `identity = {query_normalized, effective_enable_rerank, config_fingerprint, corpus_version}`. Transport is not an identity dimension under parity policy. |
| Transport in key identity | A) Include `transport` (`rest`/`ws`) in key. B) Exclude transport. | **B: Exclude transport from key identity.** | Including transport forces divergence by construction and blocks cache sharing/parity. | Equivalent requests from REST and WS map to same logical key when identity inputs match. |

## Normative Policy Rules

1. Cross-channel parity rule:
   - For equivalent retrieval identity inputs, REST and WS must return semantically equivalent retrieval payloads and identical cache state transitions (HIT/MISS expectation), subject to response-envelope differences.

2. Invalidation rules:
   - `ingest_type=add`: no immediate L1 clear.
   - `ingest_type=update`: immediate full L1 clear after successful ingest.
   - `PUT /config` success: immediate full L1 clear.

3. Key identity rules:
   - Required identity inputs: normalized query string, effective rerank mode, config fingerprint, corpus version.
   - Transport is excluded from key identity.

4. Fail-open rule:
   - Cache operation failures must not fail retrieval requests for either channel.

## Acceptance Criteria for Parity Tests (Implementation-Ready)

### AC1: Baseline parity for repeated equivalent query

- Given identical query and rerank mode with unchanged config/corpus,
- When request 1 is sent via REST and equivalent request 2 via WS,
- Then request 2 must observe shared-cache behavior consistent with request 1 (expected HIT after first MISS under healthy cache).

### AC2: `ingest_type=add` preserves cache across channels

- Given an equivalent query is already cached,
- When `/documents` is called with `ingest_type=add`,
- Then equivalent REST and WS queries continue to use existing cache entry behavior (no forced clear), unless TTL expiration occurs.

### AC3: `ingest_type=update` invalidates cache across channels

- Given an equivalent query is already cached,
- When `/documents` is called with `ingest_type=update` and succeeds,
- Then next equivalent retrieval via REST and via WS must both be MISS/recompute before re-populating cache.

### AC4: config update invalidates cache across channels

- Given an equivalent query is already cached,
- When `PUT /config` succeeds,
- Then next equivalent retrieval via REST and via WS must both be MISS/recompute using updated config behavior.

### AC5: key identity parity contract

- Given two requests that differ only by transport,
- When query text normalization, effective rerank, config fingerprint, and corpus version are equal,
- Then both transports must resolve to the same logical cache identity.

- Given any one identity input changes (effective rerank OR config fingerprint OR corpus version OR normalized query),
- Then cache identity must change and prior entry must not be reused.

### AC6: fail-open parity

- Given cache backend get/set/clear errors,
- When equivalent requests are sent via REST and WS,
- Then both requests still return successful retrieval responses (no 5xx caused by cache failure), with cache status surfaced as best-effort telemetry only.

## Notes for Wave 2/3 Implementers

- Current architecture uses HTTP middleware for `/retrieve`; WS currently bypasses middleware and retrieves directly.
- Implementation should centralize retrieval and cache-policy logic into one shared service/facade so policy is enforced once.
- Existing response envelopes differ (REST `RetrievalResponse`; WS status/results messages). Parity assertions should target retrieval semantics and cache behavior, not envelope shape.

## Sources

- `docs/plan/20260420/cache-gap-plan.yaml`
- `docs/plan/20260420/plan.yaml`
- `docs/plan/20260420/notes.md`
- `api.py`
- `api_middleware.py`
