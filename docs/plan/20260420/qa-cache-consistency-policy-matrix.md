# QA Validation Matrix - CACHE-CONSISTENCY-POLICY (Wave 1)

Date: 2026-04-21
Plan: 20260420-cache-gap
Scope: Define testable, observable contract assertions before Wave 2 implementation.
Constraint: No product code edits in this wave.

## 1) Contract Under Test

This matrix defines externally observable behavior for retrieval consistency across:
- REST: `POST /retrieve`
- WS: `GET /ws/chat` message exchange (`status` then final `response`/payload)

Current-state evidence indicates transport divergence (REST goes through L1 middleware; WS bypasses middleware). This artifact defines required assertions to validate the policy chosen for Wave 2+.

## 2) Decision Gate (Blocking)

Policy Decision D1 must be approved before Wave 2 implementation:
- D1-A (recommended): WS participates in the same L1 response cache policy as REST (strict parity)
- D1-B (allowed only with explicit sign-off): WS remains uncached; divergence is documented as intentional non-parity

Quality Gate:
- If D1 is not explicitly approved, `CACHE-PARITY-IMPLEMENT` is blocked.

## 3) Observable Contract Assertions (REST vs WS)

### 3.1 Baseline parity assertions (apply to both D1-A and D1-B)

| ID | Scenario | Assertion (Observable) | Pass Criteria | Severity if Violated |
|---|---|---|---|---|
| CP-01 | Same query + same rerank value across transports | Top-k result identity/order parity is consistent with approved policy | Result IDs and ordering equivalent, or documented allowed delta with reason | High |
| CP-02 | Response contract compatibility | WS terminal retrieval payload maps to same semantic fields as REST (`query`, `results[*].id/text/source/score`) | Field-level semantic parity, no missing required retrieval fields | High |
| CP-03 | Deterministic behavior | Repeated equivalent requests/messages produce stable outputs (excluding documented non-deterministic fields) | No unexplained drift in IDs/scores/order | Medium |
| CP-04 | Error parity | Equivalent retriever failure states surface equivalent error class to client | Same failure class (service unavailable vs retrieval failure), transport-specific wrapper allowed | High |
| CP-05 | Rerank isolation | `enable_rerank=true` and `false` remain behaviorally isolated (no cross-bleed) | Different-mode calls do not reuse wrong-mode result set | High |

### 3.2 Cache behavior assertions for D1-A (strict parity)

| ID | Scenario | Assertion (Observable) | Pass Criteria | Severity if Violated |
|---|---|---|---|---|
| CP-A1 | First equivalent REST and WS retrieval after cold start | Both are cache MISS equivalents | Both paths show miss-equivalent behavior on first request | Medium |
| CP-A2 | Second identical request/message | Both are HIT equivalents | Both paths return cached response equivalent; latency and headers/events indicate hit-equivalent behavior | High |
| CP-A3 | Cache key identity | Query + rerank + config fingerprint + corpus version + transport policy generate equivalent parity behavior | No false HIT across mismatched rerank/config/corpus dimensions | Critical |
| CP-A4 | Fail-open cache errors | Cache backend failure does not break retrieval | Both transports still return retrieval result/error independent of cache subsystem | High |

### 3.3 Cache behavior assertions for D1-B (intentional non-parity)

| ID | Scenario | Assertion (Observable) | Pass Criteria | Severity if Violated |
|---|---|---|---|---|
| CP-B1 | Repeated REST request | REST shows HIT/MISS semantics via middleware behavior | `X-Cache` semantics remain valid on REST | Medium |
| CP-B2 | Repeated WS message | WS remains uncached by design | WS always computes fresh retrieval; docs/tests explicitly assert this | Medium |
| CP-B3 | Divergence disclosure | Non-parity is explicit in docs and tests | Acceptance tests and docs clearly state divergence and rationale | High |

## 4) Invalidation Matrix (Required)

### 4.1 Ingest invalidation scenarios

| ID | Trigger | Expected Cache Effect (D1-A) | Expected Cache Effect (D1-B) | Observable Assertions |
|---|---|---|---|---|
| INV-ADD-01 | Ingest with `ingest_type=add` | No global clear; existing entries preserved (eventual consistency allowed by policy) | REST cache preserved; WS unaffected (already uncached) | Repeated pre-ingest query remains HIT-equivalent on cached path; result freshness expectation documented as eventual for add |
| INV-ADD-02 | Ingest with `ingest_type=add` then query for newly added content | Existing cached answers may remain; new query should discover added corpus when key not already cached | Same, with WS expected fresh computation | Behavior matches declared consistency model; no silent contract contradiction |
| INV-UPD-01 | Ingest with `ingest_type=update` | Full L1 clear required | REST full clear required; WS unaffected by cache clear but reflects updated corpus on fresh compute | Query sequence miss->hit->update->miss must hold on cached path |
| INV-UPD-02 | Concurrent update during active retrieval traffic | No stale cache entry survives as HIT after clear boundary | Same for REST; WS fresh compute | Post-update repeated query cannot return pre-update cache HIT-equivalent |

### 4.2 Config update invalidation scenarios

| ID | Trigger | Expected Cache Effect (D1-A) | Expected Cache Effect (D1-B) | Observable Assertions |
|---|---|---|---|---|
| CFG-01 | Successful config update (`PUT /config`) | Full L1 clear across relevant cache scope | REST full clear; WS unaffected by cache clear but must reflect updated config behavior | Query sequence miss->hit->config-update->miss on cached path |
| CFG-02 | No-op config update payload | No clear if config unchanged OR clear always if policy says so (must be explicit) | Same | Behavior deterministic and documented; tests assert chosen branch |
| CFG-03 | Config update failure (4xx/5xx) | No cache clear on failed update | Same | Cache state unchanged when update not committed |

## 5) Non-Goals (Wave 1)

- No implementation refactor in this artifact (no shared retrieval facade changes yet).
- No benchmark/SLO commitments beyond observable hit/miss equivalence checks.
- No distributed-cache topology validation (single-node vs multi-node coherence not certified here).
- No schema redesign of WS protocol beyond parity mapping assertions.
- No lock-based stampede prevention certification in Wave 1.

## 6) Edge Cases to Carry into Wave 3 Tests

- EC-01: JSON media type variants (`application/json`, `application/json; charset=utf-8`, `application/*+json`) must not create accidental cache bypass where policy expects caching.
- EC-02: Equivalent JSON payloads with key-order/whitespace differences must map to same cache identity.
- EC-03: `enable_rerank` override isolation under concurrent mixed requests/messages (no global config bleed).
- EC-04: Cache backend transient errors preserve fail-open retrieval behavior.
- EC-05: WS connection interruption mid-retrieval does not corrupt cache state for subsequent requests.
- EC-06: Empty/short query inputs treated consistently across transports (same validation class).

## 7) QA Acceptance Checklist for CACHE-CONSISTENCY-POLICY

- [ ] A single policy decision (D1-A or D1-B) is explicitly approved.
- [ ] All CP-* assertions are mapped to executable tests for Wave 3.
- [ ] Invalidation behavior for `ingest_type=add` and `ingest_type=update` is unambiguous.
- [ ] Config update invalidation behavior (success/failure/no-op) is explicit.
- [ ] Non-goals are accepted to avoid scope creep in Wave 1.
- [ ] Edge cases are tracked for implementation/testing waves.

## 8) QA Recommendation

Recommend D1-A (strict REST/WS cache parity) to eliminate current correctness and observability ambiguity. If D1-B is chosen, require explicit product sign-off and permanent divergence tests/docs to prevent accidental drift.
