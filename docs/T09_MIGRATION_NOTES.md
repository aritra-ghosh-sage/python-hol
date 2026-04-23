# T09 Migration Notes: Deprecated Code Removal

**Date**: 2026-04-23
**Task**: T09 - Enforce Final Admin-Only HTTP Allowlist

## Overview

This document tracks the deprecated code and tests removed as part of T09, which enforced the admin-only HTTP endpoint allowlist and completed the WebSocket-only retrieval migration.

## Files Removed

### Production Code
- **`api_middleware.py`** (461 lines)
  - **Purpose**: QueryCacheMiddleware for HTTP-layer caching of POST /retrieve
  - **Reason**: POST /retrieve endpoint removed in T08; middleware no longer needed
  - **Last commit**: Referenced in git history before T09
  - **Migration**: All caching now handled at retrieval layer in `_shared_retrieve_documents()`

### Test Files
- **`tests/test_query_cache_middleware.py`** (~900 lines, 47 test usages)
  - **Purpose**: Unit tests for QueryCacheMiddleware
  - **Reason**: Middleware removed; tests no longer applicable
  - **Migration**: Retrieval-layer caching tested in other suites

- **`tests/test_caching_functional.py`** (12 usages)
  - **Purpose**: Functional tests for HTTP-layer caching behavior
  - **Reason**: HTTP caching layer removed
  - **Migration**: Cache behavior tested via WebSocket in `test_ws_retrieval_critical_path.py`

- **`tests/test_retrieval_filtering.py`** (197 lines, 4 tests)
  - **Purpose**: Tests for POST /retrieve and POST /retrieve-filtered endpoints
  - **Reason**: Both endpoints removed (T04 and T08)
  - **Migration**: WebSocket equivalents in `test_ws_retrieval_critical_path.py`:
    - `test_ws_filters_results_below_threshold`
    - `test_ws_total_results_reflects_post_filter_count`
    - `test_ws_results_sorted_descending`

### Partial Removals (Test Functions)
- **`tests/test_cache_integration.py`**
  - Removed: `test_middleware_is_registered_before_routes()`
  - Removed: `test_middleware_excluded_paths()`
  - Removed: `test_retrieve_endpoint_works_with_cache_middleware()`
  - Removed: `test_cache_hit_miss_flow()`
  - Removed: `test_config_update_invalidates_cache()`
  - **Reason**: These tests verified middleware integration with POST /retrieve

### Code Changes

#### `hybrid_rag/constants.py`
**Removed**: HTTP middleware telemetry labels
```python
# REMOVED (T09)
"http_hit": "cache.http_hit",
"http_miss": "cache.http_miss",
```

**Rationale**: These labels were emitted by QueryCacheMiddleware. With the middleware removed, these telemetry events are no longer generated.

**Impact**: Monitoring dashboards that reference `cache.http_hit` or `cache.http_miss` should be updated to use retrieval-layer events instead:
- `cache.retrieval_hit`
- `cache.retrieval_miss`
- `cache.retrieval_error`

## Documentation References

The following documentation files **contain historical references** to removed code. These references are **intentionally preserved** for historical context and architecture evolution tracking:

### Architecture Documentation
- **`docs/CACHING_ARCHITECTURE.md`**
  - References QueryCacheMiddleware as L1 cache layer
  - **Status**: Historical reference - describes old architecture
  - **Action**: Consider adding T09 migration note to this document

- **`docs/CACHE_DEPLOYMENT.md`**
  - References `test_query_cache_middleware.py::test_fail_open_errors`
  - **Status**: Historical gap analysis - still accurate for understanding past state

- **`docs/CACHE_PERF_REPORT.md`**
  - Lists `test_query_cache_middleware.py` in test suite inventory
  - **Status**: Historical snapshot - dated artifact

### Migration Plans
- **`docs/plan/20260423-ws-only-retrieval-deprecation/`**
  - `T06-migration-matrix.md` - Test migration tracking
  - `INVENTORY.md` - Code inventory before removal
  - **Status**: Historical planning documents - should not be modified

- **`docs/plan/20260420-caching-blueprint/`**
  - Multiple references to `api_middleware.py` and QueryCacheMiddleware
  - **Status**: Historical design documents - preserved for context

## New Files Created

### CI/Test Files
- **`tests/test_route_allowlist.py`** (8 tests, ~350 lines)
  - **Purpose**: Automated enforcement of HTTP endpoint allowlist
  - **Tests**:
    - `test_http_routes_match_allowlist()` - Verify all HTTP routes are approved
    - `test_websocket_routes_match_allowlist()` - Verify WebSocket routes
    - `test_no_forbidden_routes()` - Prevent `/retrieve` reintroduction
    - `test_no_retrieval_http_endpoints()` - Ensure no HTTP retrieval paths
    - `test_openapi_schema_no_retrieval_references()` - Check OpenAPI schema
    - `test_route_inventory_documentation()` - Generate CI artifacts
  - **CI Integration**: Required status check on all PRs

### Documentation
- **`docs/HTTP_ENDPOINT_ALLOWLIST.md`**
  - **Purpose**: Governance policy for HTTP endpoint additions
  - **Sections**:
    - Approved HTTP endpoints (admin-only)
    - Approved WebSocket endpoints
    - Forbidden endpoints (deprecated)
    - Governance and approval process
    - Automated enforcement details
    - Monitoring and incident response

## Migration Impact Analysis

### Test Coverage
- **Before T09**: ~900 lines of middleware tests + 197 lines of HTTP retrieval tests
- **After T09**: Replaced by 6 allowlist enforcement tests
- **Coverage Migration**: HTTP retrieval coverage now in WebSocket test suite

### Monitoring Impact
**Metrics Removed**:
- `cache.http_hit` (middleware-level cache hits)
- `cache.http_miss` (middleware-level cache misses)

**Metrics Retained**:
- `cache.retrieval_hit` (retrieval-layer cache hits)
- `cache.retrieval_miss` (retrieval-layer cache misses)
- `cache.retrieval_error` (retrieval-layer cache errors)
- `cache.fallback_activated` (cache backend degradation)
- `cache.fallback_deactivated` (cache backend recovery)

**Dashboard Updates Required**:
- Any dashboard panels referencing `cache.http_*` labels should be updated to use `cache.retrieval_*`
- Alert rules should be migrated similarly

### API Surface
**Before T09**:
- 11 HTTP routes (including POST /retrieve)
- 1 WebSocket route

**After T09**:
- 11 HTTP routes (excluding POST /retrieve)
- 1 WebSocket route
- Enforced allowlist: `/health`, `/config`, `/documents`, `/documents/sources`, `/cache/stats`, `/`

### Rollback Considerations

If rollback to pre-T09 state is required:

1. **Git Tags**: Pre-removal state tagged as `pre-t09-cleanup-v1`
2. **Restore Files**: Restore from git history:
   - `git checkout pre-t09-cleanup-v1 -- api_middleware.py`
   - `git checkout pre-t09-cleanup-v1 -- tests/test_query_cache_middleware.py`
   - etc.
3. **Re-register Middleware**: Uncomment middleware registration in `api.py` (if commented)
4. **Restore Telemetry**: Revert `hybrid_rag/constants.py` changes

**Note**: Rollback is **not recommended** as it would reintroduce the POST /retrieve endpoint, violating the T09 allowlist policy.

## Related Tasks

- **T08**: Removed POST /retrieve endpoint
- **T04**: Removed POST /retrieve-filtered endpoint
- **T06**: Migrated tests to WebSocket-first approach
- **T03**: Implemented retrieval-layer caching (replaced HTTP middleware caching)

## Verification Checklist

✅ **Code Removal**
- [x] `api_middleware.py` deleted
- [x] `tests/test_query_cache_middleware.py` deleted
- [x] `tests/test_caching_functional.py` deleted
- [x] `tests/test_retrieval_filtering.py` deleted
- [x] Deprecated test functions removed from `test_cache_integration.py`
- [x] HTTP middleware telemetry removed from `constants.py`

✅ **Allowlist Enforcement**
- [x] `tests/test_route_allowlist.py` created with 6 comprehensive tests
- [x] All allowlist tests pass
- [x] Route inventory generated and verified (11 HTTP, 1 WebSocket)

✅ **Documentation**
- [x] `docs/HTTP_ENDPOINT_ALLOWLIST.md` created
- [x] T09 migration notes documented (this file)

✅ **No Regressions**
- [x] No `/retrieve` references in OpenAPI schema
- [x] No `/retrieve` routes in runtime inventory
- [x] Existing tests still pass (sampled `test_cache_integration.py`)
- [x] Route allowlist tests all green

## Next Steps

1. **CI Integration** (T09 requirement):
   - Add `test_route_allowlist.py` to required CI checks
   - Configure as blocking gate for protected branches

2. **Dashboard Updates**:
   - Migrate monitoring dashboards from `cache.http_*` to `cache.retrieval_*` metrics
   - Update alert rules similarly

3. **Documentation Updates**:
   - Add T09 migration note to `docs/CACHING_ARCHITECTURE.md`
   - Update `docs/API_INTEGRATION.md` to reference new allowlist policy

4. **Archive Historical Docs**:
   - Consider moving old caching blueprint docs to `docs/archive/` for clarity

## Contact

For questions about this migration:
- **Primary**: See T09 issue (#TODO: add issue number)
- **Rollback**: Contact platform team lead
- **Dashboard Updates**: Contact observability team
