# Plan 20260420 Clarifications

## Objective
Stabilize and secure the caching rollout for Hybrid RAG by closing production-blocking security gaps identified in researcher outputs while preserving current architecture behavior (fail-open cache usage and deterministic keying).

## Clarified Critical Scope (Blocking Set)
The following items are blocking for the clarified critical scope and must be completed before production gating:

- SEC-001: Canonicalize JSON before cache-key hashing to prevent equivalent payloads producing different keys.
- SEC-002: Exclude multipart/file-upload endpoints from cache middleware body replay to avoid memory amplification and upload-path DoS.
- SEC-004: Enforce secure Redis transport/auth expectations for production (TLS-first Redis URL policy and validation).

## Deferred Item
- SEC-003 is deferred from the immediate blocking set and scheduled for the next implementation wave:
  - Add encryption-at-rest for cached payloads (for example, Fernet-backed value encryption with key from environment configuration).

## Architectural Decisions (Clarified)
1. Keep fail-open behavior: cache failures must not fail request handling.
2. Treat canonical request identity as a correctness invariant for cache keys (stable, normalized serialization before hashing).
3. Keep binary and large multipart traffic out of cache middleware replay/caching paths.
4. Apply environment-sensitive Redis security gates: strict transport requirements in production.
5. Stage encryption-at-rest as a planned hardening milestone (deferred SEC-003), not as a prerequisite to close current critical set.

## Staging vs Production Gate Notes
- Staging gate:
  - SEC-001, SEC-002, and SEC-004 implemented and validated.
  - Regression tests for canonical keys and excluded upload endpoints pass.
  - Cache behavior remains fail-open under backend fault simulation.

- Production gate:
  - Complete staging gate criteria first.
  - Complete deferred SEC-003 (cache payload encryption at rest).
  - Confirm operational security posture (Redis transport policy, credentials handling, and deployment-time validation checks).

## Risk List
- Risk: Cache fragmentation or poisoning via non-canonical payload serialization.
  - Mitigation: SEC-001 canonical JSON normalization.
- Risk: Memory pressure and DoS from multipart body replay/caching.
  - Mitigation: SEC-002 endpoint exclusion for upload routes.
- Risk: Confidentiality exposure in Redis transit if non-TLS configuration is allowed in production.
  - Mitigation: SEC-004 strict production validation.
- Risk: Confidentiality exposure at rest for cached retrieval payloads.
  - Mitigation: Deferred SEC-003 encryption-at-rest milestone before production sign-off.
- Risk: Operational regression if strict security checks disrupt existing deployments.
  - Mitigation: Environment-aware gates and staging verification before production rollout.

## Sources
- docs/plan/20260420-caching-blueprint/ANALYSIS_REPORT_DOUBLECHECK_QUALITY_PLAYBOOK.md
- docs/plan/20260420-caching-blueprint/AUDIT_REPORT_20260420.json

---

## SEC-004 Closure Evidence — 2026-04-21

**Status: CLOSED**

### Root Cause
`RedisCache.__init__` accepted any URL including `redis://` (plaintext, no auth) even when
`ENVIRONMENT=production`. The config-layer guardrail in `CacheSettings.__post_init__` was
bypassed entirely by direct constructor calls.

### Fix Applied
**`hybrid_rag/cache.py`** — Added imports (`os`, `urlparse`) and production guardrail block
inside `RedisCache.__init__` (after `ttl_seconds` validation, before `_redis_url` assignment):
- `ENVIRONMENT=production` + `redis://` scheme → `ValueError` (TLS required)
- `ENVIRONMENT=production` + `rediss://` without password → `ValueError` (auth required)
- All other environments → no change (backward compatible)

Policy mirrors `CacheSettings.__post_init__` exactly, closing the bypass gap.

**`tests/test_cache.py`** — Added `TestRedisCacheProductionGuardrails` class (10 tests):
| Test | Outcome |
|------|---------|
| production rejects `redis://` | ✅ PASS |
| production rejects `redis://` with explicit host | ✅ PASS |
| production rejects `rediss://` without password | ✅ PASS |
| production rejects `rediss://` with username only | ✅ PASS |
| production accepts `rediss://:password@host` | ✅ PASS |
| production accepts `rediss://user:pass@host` | ✅ PASS |
| development allows `redis://` | ✅ PASS |
| absent ENVIRONMENT allows `redis://` | ✅ PASS |
| staging allows `redis://` | ✅ PASS |
| fail-open runtime behavior unchanged in production | ✅ PASS |

### Regression Verification
- `TestRedisCache`: 12/12 passed (no regressions in existing Redis tests)
- `TestCacheSettings` production tests: 3/3 passed (config-layer parity confirmed)
- Full `test_cache.py`: 57/57 passed

### Acceptance Criteria Map
| Criterion | Evidence |
|-----------|----------|
| Direct constructor rejects non-TLS URL in production | `test_production_rejects_non_tls_url` ✅ |
| Direct constructor rejects TLS URL without password in production | `test_production_rejects_tls_url_without_password` ✅ |
| Direct constructor accepts prior valid non-production local URL | `test_non_production_accepts_non_tls_url` ✅ |
| Fail-open runtime behavior unchanged | `test_fail_open_runtime_behavior_unchanged_in_production` ✅ |

## Addendum (2026-04-21): CACHE-CONSISTENCY-POLICY

Wave 1 cache-gap decision contract is documented in:

- `docs/plan/20260420/CACHE-CONSISTENCY-POLICY.md`

Approved decisions captured there unblock Wave 2 and Wave 3 planning for:

- WS participation in the same logical L1 cache policy as REST `/retrieve`
- `ingest_type` invalidation semantics (`add` preserves, `update` clears)
- Cache identity inputs for parity tests (query normalization, effective rerank mode, config fingerprint, corpus version; transport excluded)

## Addendum (2026-04-21): Wave 2–3 Implementation Complete

Tasks CACHE-PARITY-IMPLEMENT (Wave 2) and CACHE-PARITY-TESTS (Wave 3) are complete.

### What was implemented

**Shared retrieval facade** (`_shared_retrieve_documents` in `api.py`):
- Both `POST /retrieve` and `/ws/chat` route all retrieval through this one function.
- Cache key identity: `{normalized_query, effective_enable_rerank, config_fingerprint, corpus_version}`. Transport is excluded.
- Fail-open: all cache `get`/`set` calls are wrapped in try/except; errors are logged at WARNING and retrieval proceeds.

**Request-local rerank override** (no global mutation):
- `enable_rerank` from request is resolved to `effective_enable_rerank` locally; `_config.enable_rerank` is never written at request time.
- Verified by `GuardConfig` test double in `tests/test_api_shared_retrieval.py`.

**Invalidation semantics** (consistent with CACHE-CONSISTENCY-POLICY):
- `ingest_type=update` → full L1 clear (increments `_cache_generation`).
- `ingest_type=add` → cache preserved; corpus_version unchanged.
- `PUT /config` success → increments `_cache_generation` and performs full L1 clear via `lazy_cache.clear()`.

**Parity tests added** (`tests/test_api_shared_retrieval.py`):
- `test_retrieve_uses_shared_facade_with_request_local_rerank`
- `test_websocket_uses_shared_facade_and_preserves_message_contract`
- `test_parity_repeated_equivalent_query_rest_then_ws_hits_shared_cache`
- `test_parity_config_update_invalidates_shared_cache_for_rest_and_ws`
- `test_parity_ingest_add_preserves_cache_and_update_invalidates`
- `test_rerank_override_isolation_no_global_config_bleed_under_mixed_calls`

### Residual risk / open item

**AC6 (fail-open parity for WS):** No dedicated test asserts that the WS handler returns a successful `results` message under a faulting cache backend. The production code path is structurally covered (all cache calls in `_shared_retrieve_documents` are wrapped in try/except), and REST fail-open is independently tested in `test_query_cache_middleware.py::test_fail_open_errors`. This is a test coverage gap, not a production risk. Recommended follow-up: add one test in `test_api_shared_retrieval.py` that injects a cache backend raising on `get`/`set` and verifies the WS handler still sends a `type=results` message.

### Documentation updates (CACHE-REVIEW-DOCS)

- `docs/CACHE_DEPLOYMENT.md` — added section "Cross-Channel Cache Architecture (REST/WS Parity)" covering the shared facade, key identity contract, invalidation semantics, request-local rerank, and observability limitations. Updated FAQ cache-clear entry. Bumped document version to 1.1.
- `docs/CACHE_DEPLOYMENT.md` — current cache operations guide; supersedes former performance-report references.
- `docs/plan/20260420/notes.md` — this addendum.

