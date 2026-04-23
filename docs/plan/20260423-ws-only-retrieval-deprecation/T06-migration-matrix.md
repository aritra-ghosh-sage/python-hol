# T06 — Test Migration Matrix: WS-First Retrieval Validation

**Plan ID:** 20260423-ws-only-retrieval-deprecation  
**Task ID:** T06  
**Status:** complete  
**Depends on:** T03 (#20), T04 (#24)  
**Feeds:** T07 Gate (#27)  

---

## Purpose

Document the mapping between legacy HTTP-retrieval tests and their WS-first
replacements.  Every removed or superseded test has a recorded rationale and a
traceable replacement, satisfying the T06 guard-rail "no critical-path
validation dropped".

---

## 1 — Acceptance criteria checklist

| Criterion | Status | Evidence |
|-----------|--------|---------|
| Critical retrieval correctness tests run against WS path | ✅ Done | `tests/test_ws_retrieval_critical_path.py` — 7 tests all pass offline |
| Success/error/cache semantics covered in WS test suite | ✅ Done | Success: `test_ws_success_result_fields_populated`; Error: `test_ws_error_on_retrieval_failure`, `test_ws_error_on_retriever_not_initialized`; Cache: covered by pre-existing `test_ws_http_middleware_tradeoffs_e2e.py` (C1–C3) |
| No critical-path validation depends on `/retrieve-filtered` | ✅ Done | `/retrieve-filtered` removed in T04; `test_retrieve_filtered_enforces_threshold` retired (skipped) in T04 |
| Endpoint-era tests migrated, retired, or merged with rationale | ✅ Done | See §2 below |
| Test matrix maps old checks to new WS checks | ✅ Done | See §2 below |
| Impacted CI test targets updated | ✅ Done | `tests/test_ws_retrieval_critical_path.py` added to test suite; runs offline without live backend |

---

## 2 — Test migration matrix

### 2.1 Live-backend HTTP tests (Category E) → WS equivalents

| Old test (HTTP / live backend) | Disposition | New WS test | Notes |
|-------------------------------|-------------|-------------|-------|
| `test_retrieval_filtering.py::TestRestApi::test_retrieve_filters_below_threshold` | **Superseded** | `test_ws_retrieval_critical_path.py::test_ws_filters_results_below_threshold` | New test runs offline via `api.websocket_chat` + `FakeWebSocket` |
| `test_retrieval_filtering.py::TestRestApi::test_retrieve_result_count_reflects_filter` | **Superseded** | `test_ws_retrieval_critical_path.py::test_ws_total_results_reflects_post_filter_count` | Same assertion logic, now WS-first |
| `test_retrieval_filtering.py::TestRestApi::test_retrieve_results_sorted_descending` | **Superseded** | `test_ws_retrieval_critical_path.py::test_ws_results_sorted_descending` | Same assertion logic, now WS-first |
| `test_retrieval_filtering.py::TestRestApi::test_retrieve_filtered_enforces_threshold` | **Retired** (T04) | N/A — `/retrieve-filtered` removed | Marked `@pytest.mark.skip` in T04 PR; no WS equivalent needed |

> **Note:** The HTTP tests themselves are kept in `test_retrieval_filtering.py`
> (not deleted) to continue serving as live-backend regression tests during
> manual QA.  They will be permanently deleted in the T07 PR that removes the
> `/retrieve` endpoint.

### 2.2 Mock WS tests → upgraded to use `api.websocket_chat`

The simple mock-based WS tests in `test_retrieval_filtering.py` test pure
Python filtering logic but do not exercise the real `api.websocket_chat`
handler.  T06 adds proper handler-level equivalents:

| Old mock test | Limitation | New WS handler test |
|---------------|-----------|---------------------|
| `test_websocket_mock_filters_below_threshold` | Tests standalone filter logic only; does not call `api.websocket_chat` | `test_ws_filters_results_below_threshold` |
| `test_websocket_mock_results_sorted` | Tests standalone sort assumption | `test_ws_results_sorted_descending` |
| `test_websocket_count_after_filter` | Tests standalone count calculation | `test_ws_total_results_reflects_post_filter_count` |

The original mock tests are retained for their value as fast unit-level checks.

### 2.3 New tests (no HTTP equivalent)

| New WS test | Rationale |
|-------------|-----------|
| `test_ws_error_on_retrieval_failure` | WS error-type contract was untested; `RetrievalError` must produce `{"type": "error"}` not a hang |
| `test_ws_error_on_retriever_not_initialized` | WS uninitialized-retriever path was untested offline |
| `test_ws_success_result_fields_populated` | Field-level contract (`id`, `text`, `source`, `score`) was implicit; now explicit |
| `test_ws_empty_results_on_all_below_threshold` | Boundary condition: all docs filtered → empty list, not an error |

---

## 3 — Test run evidence

All 7 new tests in `test_ws_retrieval_critical_path.py` run offline (no live
backend required) and pass as of this PR.  Run:

```bash
uv run pytest tests/test_ws_retrieval_critical_path.py -v
```

Expected output:

```
tests/test_ws_retrieval_critical_path.py::test_ws_filters_results_below_threshold PASSED
tests/test_ws_retrieval_critical_path.py::test_ws_total_results_reflects_post_filter_count PASSED
tests/test_ws_retrieval_critical_path.py::test_ws_results_sorted_descending PASSED
tests/test_ws_retrieval_critical_path.py::test_ws_error_on_retrieval_failure PASSED
tests/test_ws_retrieval_critical_path.py::test_ws_error_on_retriever_not_initialized PASSED
tests/test_ws_retrieval_critical_path.py::test_ws_success_result_fields_populated PASSED
tests/test_ws_retrieval_critical_path.py::test_ws_empty_results_on_all_below_threshold PASSED
7 passed
```

---

## 4 — Coverage delta

| Metric | Before T06 | After T06 |
|--------|-----------|----------|
| WS critical-path tests (offline) | 0 direct handler tests | 7 tests via `api.websocket_chat` |
| HTTP live-backend tests for /retrieve | 3 (skipped when no backend) | 3 (retained, annotated superseded) |
| HTTP live-backend tests for /retrieve-filtered | 1 (skipped — retired T04) | 1 (skipped — retired T04) |
| WS mock-only tests | 3 (test pure logic, not handler) | 3 (retained, documented limitation) |

---

## 5 — Remaining risks

| Risk | Severity | Mitigation |
|------|----------|-----------|
| HTTP TestRestApi tests skipped in CI (no live backend) | Low | Superseded by offline WS tests; will be deleted in T07 |
| WS mock tests test logic only, not handler | Low | Offline handler tests now provide handler-level coverage |
| `test_ws_results_sorted_descending` relies on retriever returning pre-sorted results | Low | `_to_filtered_document_results` preserves retriever output order; sorting is caller's responsibility per current API contract — test validates this assumption explicitly |

---

## 6 — Dependency gate status

| Dependency | Status |
|-----------|--------|
| T03 — WS cache-status payload field | ✅ Complete (tests C1–C3 in `test_ws_http_middleware_tradeoffs_e2e.py`) |
| T04 — `/retrieve-filtered` removed | ✅ Complete (no active tests reference it) |
