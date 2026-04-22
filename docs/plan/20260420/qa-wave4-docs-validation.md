# QA Wave 4 Documentation Validation Report (Rerun)

**Scope:** Wave 4 documentation re-validation after fixes  
**Validator:** QA (senior quality assurance engineer)  
**Date:** 2026-04-21

## Artifacts Re-validated

### Documentation in scope
- `docs/CACHE_DEPLOYMENT.md`
- `docs/DOCUMENTATION_INDEX.md`
- `docs/plan/20260420/notes.md`
- `docs/plan/20260420/cache-gap-plan.yaml`

### Code/tests cross-checked
- `api.py`
- `api_middleware.py`
- `hybrid_rag/cache.py`
- `tests/test_api_shared_retrieval.py`

### Runtime evidence
- `PYTHONPATH=. pytest -q tests/test_api_shared_retrieval.py` -> **6 passed, 0 failed**

---

## Verdict

**Conditional PASS** for Wave 4 documentation accuracy.

Previously blocking findings **F-1, F-2, F-3 are resolved**. One new/remaining documentation inconsistency is still present (high severity) and should be corrected in a follow-up docs patch.

---

## Blocking Findings Status (Previous)

| Finding | Previous Status | Current Status | Evidence |
|---|---|---|---|
| F-1: `/cache/stats` documented as HTTP-only | BLOCKING | **RESOLVED** | `docs/CACHE_DEPLOYMENT.md` now states backend-aggregated counters include HTTP middleware and WS/shared-facade lookups ("Cache stats aggregate backend activity" row). Code alignment: `api.py` `_shared_retrieve_documents` uses `lazy_cache.get` and `api.py` `get_cache_stats` returns backend stats; `hybrid_rag/cache.py` `InMemoryCache.get` increments hits/misses for all callers. |
| F-2: Production env examples used plaintext `redis://` | BLOCKING | **RESOLVED** | `docs/CACHE_DEPLOYMENT.md` Environment Variables examples now use `rediss://...` with credentials for production examples. Code alignment: `hybrid_rag/cache.py` `RedisCache.__init__` enforces `rediss://` + password in production. |
| F-3: Production checklist used plaintext `redis://` | BLOCKING | **RESOLVED** | `docs/CACHE_DEPLOYMENT.md` Production Checklist now uses `rediss://...` and includes explicit TLS requirement item. Code alignment: same production guardrail enforcement in `hybrid_rag/cache.py`. |

---

## Additional Cross-check Results

| Item | Status | Evidence |
|---|---|---|
| Shared retrieval facade used by REST + WS | PASS | `api.py` defines `_shared_retrieve_documents`; both `retrieve` and `websocket_chat` call it. |
| Request-local rerank override (no global mutation) | PASS | `api.py` computes `effective_enable_rerank` without mutating global config; parity tests in `tests/test_api_shared_retrieval.py` validate isolation. |
| `PUT /config` invalidation semantics documented with generation bump | PASS | `docs/plan/20260420/notes.md` includes `_cache_generation` increment; `api.py` increments `_cache_generation` and clears cache in `update_config`. |
| Plan completion status consistency | PASS | `docs/plan/20260420/cache-gap-plan.yaml` marks parity tasks and overall plan status as completed. |
| Duplicate appendix block in perf report | RESOLVED | Former performance-report content was superseded and consolidated into active docs. |

---

## Remaining Issues

### R-1 — Production Docker Compose snippet contradicts SEC-004 transport policy

**Severity:** High  
**Location:** `docs/CACHE_DEPLOYMENT.md`, Production Setup Docker Compose example (`api` service env)  
**Observed:**
- Example still sets `REDIS_URL=redis://redis:6379` under production setup context.

**Expected:**
- Production-facing examples should use `rediss://` + authentication to match runtime production guardrails.

**Why this matters:**
- With `ENVIRONMENT=production`, this config will be rejected by `RedisCache.__init__` (startup failure).
- Without `ENVIRONMENT=production`, operators may unintentionally deploy plaintext Redis transport.

**Recommended fix:**
- Update Compose production snippet to `REDIS_URL=rediss://:strong-password@redis:6379/0` (or equivalent), and include TLS/auth note inline for that snippet.

---

## Final QA Decision

1. F-1: **Resolved**
2. F-2: **Resolved**
3. F-3: **Resolved**
4. Remaining issues: **1 (High)**

**Decision:** Documentation re-validation passes for the originally blocking set, with one high-severity follow-up documentation correction required.

---

## Final Sanity Check (SEC-004) — 2026-04-21

Re-checked `docs/CACHE_DEPLOYMENT.md` specifically for production-context `redis://` examples against the SEC-004 production guardrails enforced in `hybrid_rag/cache.py` (`ENVIRONMENT=production` requires `rediss://` and password authentication).

Result: **Clean for production context**.

- No remaining production-context `redis://` examples were found.
- Production examples use `rediss://` with credentials and are aligned with runtime enforcement.
- One `redis://` example remains under **Long-Lived Cache (12 hours)**, which is not labeled as production context.

Final status: **All blocking/high-severity findings are resolved.**
