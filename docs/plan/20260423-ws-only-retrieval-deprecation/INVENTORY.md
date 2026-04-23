# T01 — Baseline Dependency and Route Inventory

**Plan ID:** 20260423-ws-only-retrieval-deprecation  
**Task ID:** T01  
**Status:** complete  
**Created:** 2026-04-23  
**Baseline commit:** `295d232`  
**Owner:** copilot  

> **Line-number note:** All line numbers in this document reflect the state of
> the codebase at baseline commit `295d232`.  Line numbers are provided for
> navigation convenience and will become stale as the code evolves; treat them
> as approximate pointers, not stable anchors.

---

## Purpose

Machine-verifiable inventory of every reference to `POST /retrieve` and
`POST /retrieve-filtered` across the codebase.  No removal stage (T04, T06,
T07, T08) proceeds until every entry in this document has an explicit migration
path or a recorded rationale for deferral.

---

## 1 — Grep Evidence (structured)

### 1.1 Production / runtime references

| File | Line(s) | Pattern | Category |
|------|---------|---------|----------|
| `api.py` | 965 | `@app.post("/retrieve", …)` | **Route definition** |
| `api.py` | 1052 | `@app.post("/retrieve-filtered", …)` | **Route definition** |
| `api.py` | 988, 1077 | docstring examples `POST /retrieve`, `POST /retrieve-filtered` | Doc-comment |
| `api.py` | 1062, 1095 | prose references inside `/retrieve-filtered` docstring | Doc-comment |
| `api_middleware.py` | 29 | docstring example `@app.post("/retrieve")` | Doc-comment |
| `api_middleware.py` | 160 | `request.url.path != "/retrieve"` (guard condition) | **Middleware hard-code** |

### 1.2 Test references — `/retrieve`

| File | Reference count | Invocation style | Requires live backend? |
|------|----------------|-----------------|----------------------|
| `tests/test_system_e2e.py` | 35 | `client.post("/retrieve", …)` via `TestClient` | No (TestClient) |
| `tests/test_query_cache_middleware.py` | 47 | `client.post("/retrieve", …)` via `TestClient` | No (TestClient) |
| `tests/test_system_resilience.py` | 12 | `client.post("/retrieve", …)` via `TestClient` | No (TestClient) |
| `tests/test_caching_functional.py` | 12 | `client.post("/retrieve", …)` via `TestClient` | No (TestClient) |
| `tests/test_retrieval_quality_benchmark.py` | 6 | `client.post("/retrieve", …)` via `TestClient` | No (TestClient) |
| `tests/test_observability_logs.py` | 8 | `client.post("/retrieve", …)` via `TestClient` | No (TestClient) |
| `tests/test_optb013_docs_closeout.py` | 6 | `client.post("/retrieve", …)` via `TestClient` | No (TestClient) |
| `tests/test_ws_http_middleware_tradeoffs_e2e.py` | 5 | `client.post("/retrieve", …)` via `TestClient` | No (TestClient) |
| `tests/test_api_shared_retrieval.py` | indirect (facade tests) | calls via `TestClient`, no hard-coded path string | No (TestClient) |
| `tests/test_retrieval_filtering.py` | 3 | `requests.post("http://localhost:8000/retrieve", …)` | **Yes — live backend** |

### 1.3 Test references — `/retrieve-filtered`

| File | Line(s) | Pattern | Requires live backend? |
|------|---------|---------|----------------------|
| `tests/test_retrieval_filtering.py` | 198 | `requests.post("http://localhost:8000/retrieve-filtered?min_score=0.5", …)` | **Yes — live backend** |

### 1.4 Documentation references

| File | Line(s) | Pattern | Stakeholder |
|------|---------|---------|------------|
| `docs/API_INTEGRATION.md` | 74, 108, 150, 165, 175, 666, 798, 828 | curl examples, TypeScript fetch example, notes | API consumers / integrators |
| `docs/QUICK_START.md` | 104, 114, 368 | curl examples | Developers / onboarding |
| `docs/CACHING_ARCHITECTURE.md` | 40, 50, 57, 77, 88, 99, 115, 329, 346, 353, 366, 533, 534, 544, 576 | architecture diagrams, notes, curl examples | Platform / infra team |
| `docs/CACHE_PERF_REPORT.md` | 186, 264 | test result tables | Platform / infra team |
| `docs/PRODUCT_PRD.md` | (indirect) | feature table | Product |
| `frontend/SETUP.md` | 81, 82, 327 | endpoint table, ASCII diagram | Frontend / full-stack team |
| `README.md` | 89, 256 | feature bullet, curl example | All contributors |

### 1.5 Quality / runbook references

| File | Line(s) | Pattern | Stakeholder |
|------|---------|---------|------------|
| `quality/AGENTS.md` | 45, 86, 112, 132, 373 | runbook steps, curl examples | QA / on-call |
| `quality/QUALITY.md` | 136, 143, 147, 271 | test snippets, failure mode description | QA team |
| `quality/RUN_INTEGRATION_TESTS.md` | 164, 183, 236, 299, 389, 474, 478, 492 | integration test script snippets | QA / CI |

### 1.6 AI-agent / prompt references

| File | Line(s) | Pattern | Notes |
|------|---------|---------|-------|
| `.github/AGENTS.md` | 89 | `↓ Intercepts POST /retrieve` | Agent instruction doc |
| `.github/prompts/backend-python.prompt.md` | 301 | `@app.post("/retrieve", …)` | Prompt example |
| `.github/copilot-instructions.md` | 190 | `api.post<APIResponse>("/retrieve", query)` | Copilot system prompt |

### 1.7 CI / automation

| File | Pattern | Notes |
|------|---------|-------|
| No `.github/workflows/` directory found | — | No GitHub Actions CI pipeline exists in this repo at inventory time. |
| No shell scripts (`.sh`) found | — | No standalone automation scripts reference either endpoint. |

> **Finding:** There are no hidden CI pipeline or shell-script consumers of
> `/retrieve` or `/retrieve-filtered`.  All runtime calls originate from test
> fixtures (TestClient) or live-backend integration tests gated behind
> `skip_if_no_backend`.

---

## 2 — Test Categorisation and Migration Paths

### 2.1 `/retrieve` — test-by-test categorisation

#### Category A: Cache / middleware behaviour tests (TestClient — no live backend)

These tests exercise the `QueryCacheMiddleware` and caching pipeline via
`TestClient`.  They call `/retrieve` because it is the **only HTTP path that
flows through the middleware**.  After `/retrieve` is removed the cache
middleware must be removed or re-targeted; these tests must either migrate to
the WebSocket path or be retired with documented rationale.

| Test file | Function(s) | Migration path |
|-----------|-------------|----------------|
| `test_query_cache_middleware.py` | All 47 usages (various `test_*` functions) | Migrate to a stub `/retrieve` shim in the middleware test fixture, or retire and replace with WS cache-parity tests. |
| `test_caching_functional.py` | All 12 usages | Same as above — stub shim or retire. |
| `test_system_e2e.py` | All 35 usages | Migrate to WS test harness once WS cache-status signal is available (T06/T08 gate). |
| `test_system_resilience.py` | All 12 usages | Migrate to WS resilience tests. |

#### Category B: Observability / logging tests (TestClient)

| Test file | Function(s) | Migration path |
|-----------|-------------|----------------|
| `test_observability_logs.py` | 8 usages — correlation-ID and log-event assertions | Migrate correlation-ID assertions to WS path after T06. |
| `test_optb013_docs_closeout.py` | 6 usages — X-Cache header and fail-open assertions | Retire after T04/T07 gate; open a follow-up to verify WS equivalents. |

#### Category C: Retrieval quality / benchmark tests (TestClient)

| Test file | Function(s) | Migration path |
|-----------|-------------|----------------|
| `test_retrieval_quality_benchmark.py` | 6 usages — latency, hit-rate, result-consistency | Migrate to WS benchmark harness; verify same quality guarantees hold. |

#### Category D: WS ↔ HTTP parity tests (TestClient, mixed HTTP + WS)

| Test file | Function(s) | Migration path |
|-----------|-------------|----------------|
| `test_api_shared_retrieval.py` | `test_retrieve_uses_shared_facade_*` and parity tests | Keep until `/retrieve` is removed; at removal, convert REST leg to WS and retain as pure WS parity tests. |
| `test_ws_http_middleware_tradeoffs_e2e.py` | `test_b1_*` through `test_b4_*` | These tests explicitly document tradeoffs; retire or convert to WS-only equivalents as part of T07/T08. |

#### Category E: Live-backend integration tests (require running backend)

| Test file | Function(s) | Requires backend? | Migration path |
|-----------|-------------|-------------------|----------------|
| `tests/test_retrieval_filtering.py` | `TestRestApi.test_retrieve_filters_below_threshold` | Yes | Migrate to WS or retire after T07. |
| `tests/test_retrieval_filtering.py` | `TestRestApi.test_retrieve_result_count_reflects_filter` | Yes | Migrate to WS or retire after T07. |
| `tests/test_retrieval_filtering.py` | `TestRestApi.test_retrieve_results_sorted_descending` | Yes | Migrate to WS or retire after T07. |
| `tests/test_retrieval_filtering.py` | `TestIntegration.test_backend_health_check` | Yes | Keep — tests `/health`, not `/retrieve`. No migration needed. |

### 2.2 `/retrieve-filtered` — test-by-test categorisation

| Test file | Function | Requires backend? | Migration path |
|-----------|----------|-------------------|----------------|
| `tests/test_retrieval_filtering.py` | `TestRestApi.test_retrieve_filtered_enforces_threshold` | Yes | **Retire** — `/retrieve-filtered` has no WS equivalent; score filtering is already enforced by the shared facade's `min_score_threshold=0.80` floor applied to both transports. Retire with explicit rationale comment in the test file. |

---

## 3 — Blockers

### 3.1 Blockers for `/retrieve-filtered` removal (T04)

| # | Blocker | Owner | Mitigation | Status |
|---|---------|-------|-----------|--------|
| B-RF-1 | `test_retrieval_filtering.py::TestRestApi::test_retrieve_filtered_enforces_threshold` calls live `http://localhost:8000/retrieve-filtered`. Must be retired or replaced before removal. | QA / test owner | Mark test as `@pytest.mark.skip(reason="Retired: /retrieve-filtered removed, see T04")` in T04 PR. | Open |
| B-RF-2 | `docs/API_INTEGRATION.md` lines 150, 165, 175, 798 document `/retrieve-filtered` as a public API contract. Removing without updating docs breaks external consumers. | Docs / API team | Update `API_INTEGRATION.md` to mark `/retrieve-filtered` as removed.  Consumers should migrate to WebSocket (`/ws/chat`) as the preferred retrieval path.  Those that must use HTTP can use `POST /retrieve`, noting that the shared facade already applies a `min_score_threshold=0.80` floor automatically — callers need not specify filtering separately. Done as part of T04 PR. | Open |
| B-RF-3 | `docs/QUICK_START.md` line 114 has a curl example for `/retrieve-filtered`. | Docs team | Remove curl example in T04 PR. | Open |
| B-RF-4 | `frontend/SETUP.md` lines 81-82 list `/retrieve-filtered` in the endpoint table. | Frontend team | Remove row from endpoint table in T04 PR. | Open |
| B-RF-5 | `quality/AGENTS.md` and `quality/RUN_INTEGRATION_TESTS.md` do not reference `/retrieve-filtered` — no blocker here. | — | No action needed. | Cleared |

### 3.2 Blockers for `/retrieve` removal (T07)

| # | Blocker | Owner | Mitigation | Status |
|---|---------|-------|-----------|--------|
| B-R-1 | `api_middleware.py` line 160 contains the guard `if request.method != "POST" or request.url.path != "/retrieve": return False`, which means the middleware **only** caches `POST /retrieve` requests and is a no-op for every other path.  Removing the `/retrieve` route makes the middleware permanently skip all requests; it should be removed from `api.py` (or re-targeted) in the same PR that removes the route. | Backend / infra team | Remove `QueryCacheMiddleware` registration from `api.py` in the same PR that removes the route, or re-target to a new path if needed (see T07 spec). | Open |
| B-R-2 | 47 usages in `test_query_cache_middleware.py` test the middleware against `/retrieve`. These tests become meaningless after removal. | QA | Migrate or retire all middleware tests in T04–T07. Must be complete before T07 gate. | Open |
| B-R-3 | 35 usages in `test_system_e2e.py` validate L1/L2 cache behaviour via `/retrieve`. WS cache-status signal (T06) must land before these tests can be migrated to WS. | QA / backend | Depends on T06 (WS cache-status payload field decision). | Blocked on T06 |
| B-R-4 | 12 usages in `test_system_resilience.py` test resilience scenarios (degraded state, recovery) via `/retrieve`. | QA | Migrate to WS resilience harness as part of T07. | Open |
| B-R-5 | `test_api_shared_retrieval.py` — `test_retrieve_uses_shared_facade_*` tests the REST leg of the shared facade. These tests document the parity contract and must be replaced with WS-only equivalents before `/retrieve` is removed. | QA / backend | Convert REST leg to WS in T07 PR; keep as WS parity tests thereafter. | Open |
| B-R-6 | `test_ws_http_middleware_tradeoffs_e2e.py` — `test_b4_rest_miss_causes_two_cache_writes_*` tests a two-write behaviour that disappears when `/retrieve` is removed. The test will become vacuously true or fail. | QA | Retire with documented rationale (the double-write is intentionally eliminated). | Open |
| B-R-7 | 3 live-backend tests in `test_retrieval_filtering.py::TestRestApi` call `http://localhost:8000/retrieve`. Must be migrated or retired. | QA | Migrate to WS or retire after T07. | Open |
| B-R-8 | All documentation (`docs/API_INTEGRATION.md`, `docs/QUICK_START.md`, `docs/CACHING_ARCHITECTURE.md`, `README.md`, `frontend/SETUP.md`, `quality/AGENTS.md`, `quality/QUALITY.md`, `quality/RUN_INTEGRATION_TESTS.md`) references `/retrieve` and must be updated. | Docs / platform team | Update all docs in T07 or a parallel docs PR. | Open |
| B-R-9 | Open decision: WS cache-status contract (payload field vs status-event vs logs-only). This blocks T06 and therefore blocks cache-behaviour test migration (B-R-3). | Architect | Decision must be made and implemented before T06 gate; see `plan.yaml` open_questions. | Blocked — decision pending |

---

## 4 — Dependency Matrix

```
Decision: WS cache-status contract (B-R-9)
  ↓
T04 (remove /retrieve-filtered)
  requires: B-RF-1 (retire test), B-RF-2 (API docs), B-RF-3 (QUICK_START), B-RF-4 (SETUP.md)
  unblocks: T06 (simpler middleware surface)
  ↓
T06 (WS cache-status signal / observability unification)
  requires: B-R-9 decision (WS cache-status contract)
  resolves: B-R-3 (unblocks cache-behaviour test migration to WS)
  unblocks: T07 test migration, T08 dashboard/alert migration

Critical path for T07:
  B-R-9 decision → T06 implementation → B-R-3 resolved → T07 execution

T07 (remove /retrieve)
  requires: T04, T06, and ALL of B-R-1 through B-R-8 resolved
  unblocks: T08, T09, T10
  ↓
T08 (alert / dashboard migration)
  requires: T06, T07
```

---

## 5 — Baseline Telemetry Assumptions

> **Note:** No production telemetry system (Prometheus, Datadog, CloudWatch,
> etc.) is configured in this repository.  The following assumptions are based
> on code analysis and the existing `CACHE_PERF_REPORT.md`.

### 5.1 Call volumes

| Endpoint | Observed call source | Estimated production volume |
|----------|--------------------|-----------------------------|
| `POST /retrieve` | All test suites (TestClient), plus direct developer curl | Unknown — no production traffic instrumentation present |
| `POST /retrieve-filtered` | One live-backend test; no frontend consumer observed | Unknown — likely near-zero; not referenced in frontend code |
| `WS /ws/chat` | Frontend chat UI | Primary retrieval path for all end-user queries |

> **Action required:** Before T04 gate, confirm with product/ops whether
> `/retrieve-filtered` has ever received external traffic.  If log analysis is
> available, capture a 30-day request count.

### 5.2 Cache hit/miss rates (from CACHE_PERF_REPORT.md, dated 2026-04-20)

| Metric | Value | Source |
|--------|-------|--------|
| L2 embedding cache hit rate (repeated queries) | 60% | `CACHE_PERF_REPORT.md` |
| Mean latency, uncached | 979.2 ms | `CACHE_PERF_REPORT.md` |
| Mean latency, cached | 946.8 ms | `CACHE_PERF_REPORT.md` |
| L1 middleware cache (X-Cache: HIT) | Not measured at report time | TestClient tests assert header presence only |

> **Action required:** Add structured log counters for `X-Cache: HIT` and
> `X-Cache: MISS` on `/retrieve` before removal so the hit-rate baseline is
> captured in production logs, not just test assertions.

### 5.3 Alert / dashboard dependencies

| Alert / dashboard | Endpoint dependency | Owner | Notes |
|-------------------|---------------------|-------|-------|
| No production alerting config found in repo | — | — | No Prometheus rules, Grafana dashboards, or CloudWatch alarms checked in. |
| `quality/QUALITY.md` §Redis failure mode | `POST /retrieve` | QA | Documents expected fail-open behaviour; update after T07. |

> **Finding:** No external alert or dashboard system is committed to the
> repository.  Any production monitoring configured outside the repo must be
> audited manually by the ops team before T04 and T07 gates.

---

## 6 — Summary: Unknowns Resolved

| Unknown (from `plan.yaml` gaps) | Status | Evidence |
|---------------------------------|--------|----------|
| Hidden CI/CD consumers of `/retrieve` or `/retrieve-filtered` | **No hidden consumers found** | No `.github/workflows/` directory; no shell scripts reference either endpoint. |
| Internal tooling calling `/retrieve` in runbooks/scripts | **No such scripts exist** | Grep across all `.sh`, `.yml`, `.yaml` files — only doc references found. |
| External production traffic to `/retrieve-filtered` | **Cannot confirm from code alone** | No production access logs in repo; ops team must verify. |

---

## 7 — Machine-Verifiable Checklist

```yaml
inventory_checks:
  - id: grep_retrieve
    description: "All /retrieve references in codebase"
    status: complete
    evidence: "Section 1 tables above"

  - id: grep_retrieve_filtered
    description: "All /retrieve-filtered references in codebase"
    status: complete
    evidence: "Section 1 tables above"

  - id: tests_categorized
    description: "tests/test_*.py references categorized with migration path"
    status: complete
    evidence: "Section 2"

  - id: docs_mapped
    description: "docs/ and implementation_docs/ references mapped to stakeholders"
    status: complete
    evidence: "Section 1.4"

  - id: ci_audited
    description: "CI/CD and automation scripts audited"
    status: complete
    evidence: "Section 1.7 — no CI pipeline or scripts found"

  - id: blockers_retrieve_filtered
    description: "Blockers for /retrieve-filtered removal documented with owner and mitigation"
    status: complete
    evidence: "Section 3.1 — 5 blockers (B-RF-1 through B-RF-5)"

  - id: blockers_retrieve
    description: "Blockers for /retrieve removal documented with owner and mitigation"
    status: complete
    evidence: "Section 3.2 — 9 blockers (B-R-1 through B-R-9)"

  - id: dependency_matrix
    description: "Dependency matrix shows required migrations before each removal"
    status: complete
    evidence: "Section 4"

  - id: call_volume
    description: "Current /retrieve and /retrieve-filtered call volume documented"
    status: partial
    evidence: "Section 5.1 — no production telemetry in repo; ops confirmation needed"

  - id: cache_rates
    description: "Cache hit/miss rates per endpoint recorded"
    status: partial
    evidence: "Section 5.2 — L2 rate from CACHE_PERF_REPORT.md; L1 rate needs structured logging"

  - id: alert_dependencies
    description: "Alert/dashboard dependencies identified"
    status: complete
    evidence: "Section 5.3 — no monitoring config in repo; external systems must be audited manually"
```
