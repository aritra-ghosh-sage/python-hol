# QA Validation Report - Wave 2 (CACHE-PARITY-IMPLEMENT, CACHE-MW-HARDEN)

Date: 2026-04-21  
Scope: Validate Wave 2 acceptance criteria in current workspace state for:
1. Shared REST/WS retrieval path
2. No global `_config.enable_rerank` mutation per request
3. Middleware JSON-only eligibility hardening
4. Fail-open behavior preserved

## Overall Result

Wave 2 acceptance criteria are **met in implementation** in current workspace state.

- Blocking: 0
- Warning: 1
- Passed: 4 criteria

## Acceptance Criteria Validation

| Criterion | Status | Severity | Evidence | Notes |
|---|---|---|---|---|
| Shared REST/WS retrieval path | **PASS** | n/a | [api.py](api.py#L461), [api.py](api.py#L570), [api.py](api.py#L912), [api.py](api.py#L950), [tests/test_api_shared_retrieval.py](tests/test_api_shared_retrieval.py#L44), [tests/test_api_shared_retrieval.py](tests/test_api_shared_retrieval.py#L74), [docs/plan/20260420/cache-gap-plan.yaml](docs/plan/20260420/cache-gap-plan.yaml#L160) | REST and WS both route through `_shared_retrieve_documents(...)`. |
| No global `_config` rerank mutation per request | **PASS** | n/a | [api.py](api.py#L461), [api.py](api.py#L467), [api.py](api.py#L570), [api.py](api.py#L643), [api.py](api.py#L950), [tests/test_api_shared_retrieval.py](tests/test_api_shared_retrieval.py#L11) | Rerank override is passed as request-local parameter to retriever; no request-time `_config.enable_rerank = ...` mutation in handlers. |
| Middleware JSON-only eligibility hardening | **PASS** | n/a | [api_middleware.py](api_middleware.py#L117), [api_middleware.py](api_middleware.py#L123), [api_middleware.py](api_middleware.py#L138), [api_middleware.py](api_middleware.py#L139), [api_middleware.py](api_middleware.py#L142), [tests/test_query_cache_middleware.py](tests/test_query_cache_middleware.py#L463), [tests/test_query_cache_middleware.py](tests/test_query_cache_middleware.py#L492), [tests/test_query_cache_middleware.py](tests/test_query_cache_middleware.py#L507) | Middleware now gates cache eligibility to JSON media types (`application/json` and `application/*+json`). |
| Fail-open behavior preserved | **PASS** | n/a | [api_middleware.py](api_middleware.py#L10), [api_middleware.py](api_middleware.py#L277), [api_middleware.py](api_middleware.py#L307), [tests/test_query_cache_middleware.py](tests/test_query_cache_middleware.py#L562), [tests/test_query_cache_middleware.py](tests/test_query_cache_middleware.py#L592), [api.py](api.py#L826), [api.py](api.py#L897) | Middleware and cache stats endpoint preserve fail-open behavior (cache errors logged; retrieval path continues). |

## Test Execution Evidence

### Confirmed from workspace context

- Command (previously run in terminal context):
  - `source .venv/bin/activate && pytest -q tests/test_caching_functional.py -k "config_update_clears_l1_cache or cache_key_independent_of_json_order or cache_key_handles_defaults"`
  - Result: exit code `0`

### Additional execution attempts during this QA pass

- Multiple targeted pytest runs were attempted for Wave 2 coverage.
- Result: interrupted at collection/import stage (`KeyboardInterrupt`) while loading heavy import chain from `tests/conftest.py -> api.py -> sentence_transformers/torch`.
- Representative evidence path (captured terminal resource):
  - `/home/aritraghosh/.vscode-server/data/User/workspaceStorage/23fad270fd3e3c3d4f7571c1784725ee/GitHub.copilot-chat/chat-session-resources/804442b1-76bc-41e8-8440-34c83a11cc1c/call_uSOaiA9ZFYu79eg6nq4znpy4__vscode-1776741845194/content.txt`

## Blockers

- **WARNING**: Full targeted pytest execution for Wave 2 validation is partially blocked by test collection/import-time interruption in this environment.

## QA Conclusion

Wave 2 acceptance criteria are satisfied by current code state. Remaining risk is execution-evidence depth due local pytest collection/import interruptions in this environment.
