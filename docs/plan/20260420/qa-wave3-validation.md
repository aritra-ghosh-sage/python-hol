# QA Validation Report - Wave 3 (CACHE-PARITY-TESTS)

Date: 2026-04-21  
Plan: 20260420-cache-gap  
Task: CACHE-PARITY-TESTS

## Overall Verdict

Conditional pass.

- Passed contract areas: REST/WS parity baseline, config and ingest invalidation semantics, request-local rerank override behavior
- Remaining gaps: fail-open parity is not asserted cross-transport, and concurrency isolation is tested with mixed calls but not true concurrent execution

## Scope Validated

Policy source:
- [docs/plan/20260420/CACHE-CONSISTENCY-POLICY.md](docs/plan/20260420/CACHE-CONSISTENCY-POLICY.md#L52)
- [docs/plan/20260420/CACHE-CONSISTENCY-POLICY.md](docs/plan/20260420/CACHE-CONSISTENCY-POLICY.md#L58)
- [docs/plan/20260420/CACHE-CONSISTENCY-POLICY.md](docs/plan/20260420/CACHE-CONSISTENCY-POLICY.md#L64)
- [docs/plan/20260420/CACHE-CONSISTENCY-POLICY.md](docs/plan/20260420/CACHE-CONSISTENCY-POLICY.md#L70)
- [docs/plan/20260420/CACHE-CONSISTENCY-POLICY.md](docs/plan/20260420/CACHE-CONSISTENCY-POLICY.md#L76)
- [docs/plan/20260420/CACHE-CONSISTENCY-POLICY.md](docs/plan/20260420/CACHE-CONSISTENCY-POLICY.md#L85)

Wave 3 task definition:
- [docs/plan/20260420/cache-gap-plan.yaml](docs/plan/20260420/cache-gap-plan.yaml#L295)

Primary test artifacts reviewed:
- [tests/test_api_shared_retrieval.py](tests/test_api_shared_retrieval.py)
- [tests/test_query_cache_middleware.py](tests/test_query_cache_middleware.py)
- [tests/test_system_e2e.py](tests/test_system_e2e.py)
- [tests/test_ws.py](tests/test_ws.py)

## Execution Evidence

Executed targeted suites:

1. PYTHONPATH=. pytest -q --noconftest tests/test_query_cache_middleware.py tests/test_api_shared_retrieval.py  
   Result: 53 passed

2. PYTHONPATH=. pytest -q --noconftest tests/test_cache_integration.py -k config_update_invalidates_cache  
   Result: 1 passed, 28 deselected

3. PYTHONPATH=. pytest -q tests/test_system_e2e.py -k "ingest_add_preserves_cache or ingest_update_clears_cache or l1_cache_invalidation_on_config_change"  
   Result: 3 passed, 21 deselected

Note: The same e2e subset fails under --noconftest due to missing fixture wiring, but passes with normal fixture loading.

## Findings (Ordered by Severity)

### High

1. AC6 fail-open parity is not fully enforced across both transports.

- Requirement: [docs/plan/20260420/CACHE-CONSISTENCY-POLICY.md](docs/plan/20260420/CACHE-CONSISTENCY-POLICY.md#L85)
- Observed coverage:
  - REST/middleware fail-open is covered in [tests/test_query_cache_middleware.py](tests/test_query_cache_middleware.py#L592)
  - No WS+REST parity test injects cache backend failures and asserts both transports remain successful under equivalent requests in [tests/test_api_shared_retrieval.py](tests/test_api_shared_retrieval.py)
- Impact: A regression could preserve REST fail-open while breaking WS parity under cache errors without failing Wave 3 tests.

2. Rerank isolation check is mixed-call, not true concurrent isolation.

- Requirement focus: rerank concurrency-isolation checks from [docs/plan/20260420/cache-gap-plan.yaml](docs/plan/20260420/cache-gap-plan.yaml#L304)
- Current test: [tests/test_api_shared_retrieval.py](tests/test_api_shared_retrieval.py#L270)
- Observation: test validates request-local rerank behavior and no global bleed, but executes sequential mixed calls rather than concurrent calls.
- Impact: Race-condition regressions in concurrent REST/WS traffic may escape detection.

### Medium

1. Baseline parity assertion is one-directional (REST then WS) and does not include WS-first symmetric path.

- Current parity test: [tests/test_api_shared_retrieval.py](tests/test_api_shared_retrieval.py#L184)
- Observation: Covers equivalent query parity and shared-cache reuse for REST-first path only.
- Impact: Lower risk, but symmetric-path coverage would reduce transport-order blind spots.

### Warning

1. e2e invalidation tests in system suite validate success status but do not strictly assert MISS/HIT transitions.

- Tests: [tests/test_system_e2e.py](tests/test_system_e2e.py#L213), [tests/test_system_e2e.py](tests/test_system_e2e.py#L332), [tests/test_system_e2e.py](tests/test_system_e2e.py#L369)
- Observation: Useful regression smoke tests, but strict parity transition enforcement is primarily in shared facade tests.
- Impact: Low, because stronger contract checks exist elsewhere.

## Pass Matrix for Requested Focus Checks

1. REST/WS parity assertions
- Status: Pass with gap
- Strong evidence:
  - [tests/test_api_shared_retrieval.py](tests/test_api_shared_retrieval.py#L184)
  - [tests/test_api_shared_retrieval.py](tests/test_api_shared_retrieval.py#L142)
- Gap: Missing explicit fail-open parity and WS-first symmetric parity path

2. Config and ingest invalidation semantics
- Status: Pass
- Evidence:
  - Config invalidation parity: [tests/test_api_shared_retrieval.py](tests/test_api_shared_retrieval.py#L207)
  - Ingest add/update parity: [tests/test_api_shared_retrieval.py](tests/test_api_shared_retrieval.py#L228)
  - Additional integration evidence: [tests/test_system_e2e.py](tests/test_system_e2e.py#L213), [tests/test_system_e2e.py](tests/test_system_e2e.py#L332), [tests/test_system_e2e.py](tests/test_system_e2e.py#L369)

3. Rerank concurrency-isolation checks
- Status: Partial pass
- Evidence:
  - Request-local rerank/no global mutation: [tests/test_api_shared_retrieval.py](tests/test_api_shared_retrieval.py#L112), [tests/test_api_shared_retrieval.py](tests/test_api_shared_retrieval.py#L270)
- Gap: No true concurrent mixed REST/WS rerank stress assertion

## Blockers

- No hard blocker for running targeted suites with standard fixture loading.
- Operational note: Running selected e2e tests with --noconftest causes fixture-resolution errors and can produce false blocker signals.

## QA Recommendation

Wave 3 is acceptable to merge only if the team accepts the residual risk around AC6 and concurrency race coverage. For strict policy closure, add two targeted contract tests:

1. Cross-transport fail-open parity test with injected cache get/set/clear errors
2. True concurrent mixed REST/WS rerank isolation test that validates no global config bleed under parallel traffic
