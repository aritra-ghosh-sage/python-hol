# T07 — Gate Record: Go/No-Go Decision for `/retrieve` Removal

**Plan ID:** 20260423-ws-only-retrieval-deprecation  
**Task ID:** T07  
**Status:** complete — **GO**  
**Decision date:** 2026-04-23  
**Rollback tag:** `pre-retrieve-removal-v1` → commit `a8e3ec7`  
**Feeds:** T08 — Remove `/retrieve` and eliminate HTTP retrieval-specific cache path  

---

## Decision

> ### ✅ GO — Proceed with T08 (`/retrieve` removal)

All evidence criteria are satisfied. No unresolved blockers prevent safe removal.
T08 may proceed subject to the T08 execution checklist linked in §6.

---

## 1 — Dependency Readiness

| Criterion | Status | Evidence |
|-----------|--------|---------|
| No unresolved internal dependency on `/retrieve` | ✅ Confirmed | T01 inventory (`INVENTORY.md` §1.7): zero GitHub Actions workflows; zero shell scripts reference `/retrieve`. All remaining test consumers are TestClient-based (no live-backend requirement). |
| T05 middleware scope evidence complete | ✅ Confirmed | Issue #25 closed as `completed` (2026-04-23T11:17:44Z). PR #33 merged: `QueryCacheMiddleware` scope locked to `POST /retrieve` explicitly; positive-path `method == POST and path == /retrieve` allowlist confirmed; negative tests for admin endpoints added. |
| T06 WS-first test migration evidence complete | ✅ Confirmed | Issue #26 closed as `completed` (2026-04-23T11:04:47Z). `T06-migration-matrix.md` documents 7 new WS critical-path tests, full migration matrix, and coverage delta. |

---

## 2 — Operational Readiness

| Criterion | Status | Evidence |
|-----------|--------|---------|
| Observability readiness for WS-only traffic validated | ✅ Confirmed | `tests/test_ws_http_middleware_tradeoffs_e2e.py`: Tests B3, C1, C2, C3 assert that WS messages carry `cache_status` ∈ `{"HIT", "MISS", "ERROR"}` (T03 decision: payload-field contract). WS clients have equivalent cache-status visibility to the `X-Cache` header on the REST path. No external alerting config is checked into the repo; ops team is advised to audit any out-of-repo dashboards before T08 deployment (see §5 residual risks). |
| Rollback tag captured and verified for pre-removal state | ✅ Captured | Tag `pre-retrieve-removal-v1` → `a8e3ec7` (T05 merge: "T05: Align HTTP middleware scope for transition period"). To restore: `git checkout pre-retrieve-removal-v1`. This state includes the functioning `/retrieve` route and `QueryCacheMiddleware` intact. |
| Approver sign-off recorded | ✅ Required — see §7 | Sign-off must be recorded in issue #27 comments before T08 starts. @copilot has assembled the evidence package; @aritra-ghosh-sage is the designated approver. |

---

## 3 — Blockers Assessment

The following blockers from `INVENTORY.md §3.2` were open at T01. All are
assessed here against current evidence. **None block the GO decision**; they are
all within-scope work for the T08 PR itself.

| Blocker | Original status | T07 assessment | T08 action |
|---------|----------------|----------------|-----------|
| B-R-1: `api_middleware.py` hard-codes `/retrieve`; middleware becomes a no-op after removal | Open | **Within-scope for T08** — middleware must be removed alongside the route | Remove `QueryCacheMiddleware` registration in T08 PR |
| B-R-2: 47 tests in `test_query_cache_middleware.py` test middleware against `/retrieve` | Open | **Within-scope for T08** — tests become moot after route removal | Retire or migrate to WS cache-parity checks in T08 PR |
| B-R-3: 35 tests in `test_system_e2e.py` use L1/L2 cache via `/retrieve` | Was "Blocked on T06" | **Resolved** — T06 landed WS `cache_status` payload field | Migrate to WS harness in T08 PR |
| B-R-4: 12 tests in `test_system_resilience.py` use `/retrieve` | Open | **Within-scope for T08** | Migrate to WS resilience harness in T08 PR |
| B-R-5: `test_api_shared_retrieval.py` REST leg of shared-facade parity tests | Open | **Within-scope for T08** | Convert REST leg to WS parity test in T08 PR |
| B-R-6: `test_ws_http_middleware_tradeoffs_e2e.py::test_b4_*` tests double-write behavior | Open | **Within-scope for T08** — double-write is intentionally eliminated | Retire with documented rationale in T08 PR |
| B-R-7: 3 live-backend tests in `test_retrieval_filtering.py::TestRestApi` | Open | **Within-scope for T08** — T06 superseded these with offline WS tests | Retire in T08 PR per T06 migration matrix |
| B-R-8: Docs updates across 8+ files | Open | **Within-scope for T08/T09/T10** | Update docs in T08 PR or parallel docs PR |
| B-R-9: WS cache-status contract decision | Was "Decision pending" | **Resolved in T03/T06** — payload-field approach implemented and tested | No further action needed before T08 |

**No blocker is outstanding that would prevent T08 from starting.**

---

## 4 — Evidence Summary

### 4.1 WS critical-path test pass evidence (T06)

File: `tests/test_ws_retrieval_critical_path.py` — 7 tests, all passing offline:

```
test_ws_filters_results_below_threshold              PASSED
test_ws_total_results_reflects_post_filter_count     PASSED
test_ws_results_sorted_descending                    PASSED
test_ws_error_on_retrieval_failure                   PASSED
test_ws_error_on_retriever_not_initialized           PASSED
test_ws_success_result_fields_populated              PASSED
test_ws_empty_results_on_all_below_threshold         PASSED
7 passed
```

Run command: `uv run pytest tests/test_ws_retrieval_critical_path.py -v`

### 4.2 Middleware scope evidence (T05)

- `api_middleware.py` line 178: `if request.method != "POST" or request.url.path != "/retrieve": return False`
- Scope is deterministic and explicit. No admin endpoint (`/config`, `/health`, `/cache/stats`, `/documents`) is intercepted.
- PR #33 added negative tests confirming admin endpoints bypass the cache.

### 4.3 WS observability evidence (T03/T06)

`tests/test_ws_http_middleware_tradeoffs_e2e.py` coverage:

| Test | Assertion |
|------|-----------|
| `test_b3_http_and_ws_both_expose_cache_status_in_their_respective_contracts` | WS `cache_status` field present; REST `X-Cache` header present |
| `test_c1_ws_cache_hit_payload_field_and_log_event_signal_hit` | WS `cache_status == "HIT"` on second request |
| `test_c2_ws_cache_miss_payload_field_and_log_event_signal_miss` | WS `cache_status == "MISS"` on first request |
| `test_c3_ws_cache_invalidation_post_invalidation_ws_query_shows_miss` | WS `cache_status == "MISS"` after invalidation |

### 4.4 Internal consumer scan (T01)

From `INVENTORY.md §1.7`:
- **No `.github/workflows/` directory** — no CI pipeline depends on `/retrieve`
- **No shell scripts (`.sh`)** — no automation scripts reference the endpoint
- All test consumers use `TestClient` (offline); live-backend tests are gated behind `skip_if_no_backend`

---

## 5 — Residual Risks

| Risk | Severity | Owner | Mitigation |
|------|----------|-------|-----------|
| Out-of-repo production dashboards/alerts may reference `/retrieve` | Medium | Ops team | Audit any external Prometheus/Grafana/CloudWatch configs before deploying T08 to production |
| `test_query_cache_middleware.py` (47 tests) becomes moot post-removal — must not be silently skipped | Low | QA | T08 PR checklist item: explicitly retire or rewrite all 47 tests |
| `test_system_e2e.py` (35 tests) needs WS migration — large surface | Medium | QA / backend | T08 is the designated execution slot for this migration; risk is captured in T08 acceptance criteria |
| WS mock tests in `test_retrieval_filtering.py` test logic only, not handler | Low | QA | Offline handler tests in `test_ws_retrieval_critical_path.py` provide handler-level coverage |

---

## 6 — T08 Execution Checklist

T08 may begin immediately after approver sign-off (§7). The following checklist
is the minimal required scope for the T08 PR:

- [ ] Remove `@app.post("/retrieve", ...)` handler from `api.py`
- [ ] Remove `QueryCacheMiddleware` registration from `api.py`
- [ ] Remove or archive `api_middleware.py` (no other routes consume it)
- [ ] Retire / migrate `tests/test_query_cache_middleware.py` (47 tests, B-R-2)
- [ ] Migrate `tests/test_system_e2e.py` to WS harness (35 tests, B-R-3)
- [ ] Migrate `tests/test_system_resilience.py` to WS resilience harness (12 tests, B-R-4)
- [ ] Convert REST leg of `tests/test_api_shared_retrieval.py` to WS parity test (B-R-5)
- [ ] Retire `test_b4_rest_miss_causes_two_cache_writes_*` with rationale comment (B-R-6)
- [ ] Retire 3 live-backend `/retrieve` tests in `tests/test_retrieval_filtering.py::TestRestApi` (B-R-7)
- [ ] Update `docs/API_INTEGRATION.md` to mark `/retrieve` as removed (B-R-8)
- [ ] Update `docs/QUICK_START.md` curl example (B-R-8)
- [ ] Update `docs/CACHING_ARCHITECTURE.md` architecture diagrams (B-R-8)
- [ ] Update `README.md` feature bullet and curl example (B-R-8)
- [ ] Update `frontend/SETUP.md` endpoint table and ASCII diagram (B-R-8)
- [ ] Update `quality/AGENTS.md`, `quality/QUALITY.md`, `quality/RUN_INTEGRATION_TESTS.md` (B-R-8)
- [ ] Confirm single cache write-path via `cache/stats` assertion after removal
- [ ] Verify no regression in `/config`, `/health`, `/cache/stats`, `/documents` endpoints

**Rollback procedure for T08:**
```bash
git checkout pre-retrieve-removal-v1
```
Tag `pre-retrieve-removal-v1` points to commit `a8e3ec7` — the T05-complete,
pre-removal state with `/retrieve` fully functional.

---

## 7 — Approver Sign-Off

| Role | Person | Sign-off |
|------|--------|---------|
| Evidence assembler (Copilot) | @copilot | ✅ Evidence package complete — GO recommended |
| Decision authority | @aritra-ghosh-sage | ⬜ **Pending** — record sign-off in issue #27 comments |

> **Fail-closed guard-rail:** If approver sign-off is not recorded in issue #27
> before T08 begins, the default decision is **NO-GO**.

---

## 8 — Dependency Gate Status

| Dependency | Status |
|-----------|--------|
| T03 — WS cache-status payload field | ✅ Complete |
| T04 — `/retrieve-filtered` removed | ✅ Complete |
| T05 — Middleware scope aligned | ✅ Complete (issue #25 closed) |
| T06 — WS-first test migration | ✅ Complete (issue #26 closed) |
| T07 sign-off | ⬜ Pending approver confirmation in issue #27 |
