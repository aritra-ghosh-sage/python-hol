# Dead Code Audit Report

**Date:** 2026-05-06  
**Scope:** `api.py`, `mcp_server.py`, `hybrid_rag/retriever.py`, `hybrid_rag/vectordb.py`, `hybrid_rag/reranker.py`, `hybrid_rag/persistence.py`, `hybrid_rag/config.py`, `hybrid_rag/cache.py`, `api_models.py`

---

## Severity Legend

| Symbol | Meaning |
|--------|---------|
| 🔴 | Critical — correctness or silent-failure risk |
| 🟠 | Important — maintainability or consistency risk |
| 🟡 | Minor — cleanup / hygiene |

---

## Category 1: Unused Code Artifacts

### 1.1 Unused Functions

| Category | File Path | Line(s) | Name / Description | Context | Confidence | Risk | Suggested Action |
|----------|-----------|---------|-------------------|---------|------------|------|-----------------|
| Unused Function | `tests/conftest.py` | 53–65 | `_is_retriever_collection_healthy()` | Private helper defined at module level; never called by any test or fixture in the test suite | High | Low | **Remove** |
| Unused Function | `mcp_server.py` | 61–73 | `_load_initial_config()` | One-line wrapper that only calls `resolve_startup_config(KNOWLEDGE_DB_DIRECTORY)`; called exactly once — easier to inline | High | Low | **Remove** (inline the call) |

### 1.2 Superseded / Backward-Compat-Only Classes

| Category | File Path | Line(s) | Name / Description | Context | Confidence | Risk | Suggested Action |
|----------|-----------|---------|-------------------|---------|------------|------|-----------------|
| Unused Class | `api_models.py` | 172–218 | `CacheStatsResponse` | Docstring explicitly states it is superseded by `LayeredCacheStatsResponse` (OPTB-008). Re-exported from `api.py` for backward compat but never instantiated in any production code path. | High | Medium | **Review** — keep for API compat, or schedule formal deprecation with removal milestone |
| Unused Class | `api_models.py` | 372–383 | `WsMessageBase` | Docstring says "retained for backward compatibility only"; all active WS message types (`WsStatusMessage`, `WsResultsMessage`, `WsErrorMessage`) inherit directly from `pydantic.BaseModel`, not from this class | High | Low | **Review** — schedule removal once no external callers confirmed |
| Unused Class | `api_models.py` | 386–395 | `WsQueryMessage` | The WebSocket handler (`routers/websocket.py`) reads `data.get("query")` from raw JSON directly — this model is never used for parsing incoming WS messages | High | Low | **Review** — either wire it into the handler for validated parsing, or schedule removal |

### 1.3 Intentional-but-Flagged Imports

| Category | File Path | Line(s) | Name / Description | Context | Confidence | Risk | Suggested Action |
|----------|-----------|---------|-------------------|---------|------------|------|-----------------|
| Unused Import | `api.py` | 64 | `chunk_text` (noqa F401) | Retained per ADR-0001 T4 for future callers; currently unused in production | High | Low | **Keep** — annotate comment with the expected first-caller or target ticket |
| Unused Import | `api.py` | 52–53 | `requests`, `chromadb` (noqa F401) | Imported only so tests can `monkeypatch("api.requests.get")` and `monkeypatch(api.chromadb, "PersistentClient")` | Medium | Low | **Keep** — comment is already clear; no action required |

### 1.4 Unused Constants

| Category | File Path | Line(s) | Name / Description | Context | Confidence | Risk | Suggested Action |
|----------|-----------|---------|-------------------|---------|------------|------|-----------------|
| Unused Constant | `hybrid_rag/constants.py` | 71 | `MIN_RELEVANCE_SCORE = 0.80` | Exported in `__all__`, referenced in `hybrid_rag_flow.py` example only. Neither `api.py`, `routers/websocket.py`, nor `mcp_server.py` use it — both hardcode `0.40` as the threshold instead | High | Medium | **Refactor** — use the constant in both places, or define separate named constants to make the threshold divergence intentional and visible |

### 1.5 Pass-Through-Only Methods (Code Smell)

| Category | File Path | Line(s) | Name / Description | Context | Confidence | Risk | Suggested Action |
|----------|-----------|---------|-------------------|---------|------------|------|-----------------|
| Passthrough Method | `hybrid_rag/retriever.py` | 219–238 | `get_embedding_cache_stats()` | Delegates entirely to `_get_embedding_cache_stats()` with no added logic. Documented as intentional public-API boundary (OPTB-008) | High | Low | **Keep** — the boundary is intentional; no action required |

---

## Category 2: Dead Code Blocks

### 2.1 Commented-Out Code

| Category | File Path | Line(s) | Name / Description | Context | Confidence | Risk | Suggested Action |
|----------|-----------|---------|-------------------|---------|------------|------|-----------------|
| Dead Block | `hybrid_rag/retriever.py` | 522–534 | Large debug logging block | Multi-line commented-out block inside `retrieve()` that would print reranked results with section metadata | High | Low | **Remove** — if debug visibility is needed, convert to `logger.debug()` calls controlled by log level |

```python
# debug_lines = []
# for r in reranked:
#     metadata = r.get("metadata", {})
#     ...
# logger.info("Reranked results:\n" + "\n".join(debug_lines))
```

### 2.2 Functionally Dead Branches

| Category | File Path | Line(s) | Name / Description | Context | Confidence | Risk | Suggested Action |
|----------|-----------|---------|-------------------|---------|------------|------|-----------------|
| Dead Branch | `mcp_server.py` | 280–281 | `if _config is None: raise ValueError(...)` in `get_config()` | `_config` is assigned `DEFAULT_CONFIG` at module level (line 55) and is never reset to `None`, making this guard unreachable under normal operation | Medium | Low | **Review** — add a comment explaining the defensive intent, or replace with an assertion |

---

## Category 3: Test Code Issues

### 3.1 Unused Fixtures

| Category | File Path | Line(s) | Name / Description | Context | Confidence | Risk | Suggested Action |
|----------|-----------|---------|-------------------|---------|------------|------|-----------------|
| Unused Fixture | `tests/test_cache_integration.py` | 23–26 | `mock_cache` fixture | Defined with `@pytest.fixture` returning a real `InMemoryCache`, but no test function signature accepts it as a parameter. All tests create their own `mock_cache = MagicMock(spec=CacheBackend)` locally. | High | Low | **Remove** |

### 3.2 Tests Skipped by Default

| Category | File Path | Line(s) | Name / Description | Context | Confidence | Risk | Suggested Action |
|----------|-----------|---------|-------------------|---------|------------|------|-----------------|
| Skipped Tests | `tests/test_api_config_persistence.py` | (entire file) | Whole module marked `@pytest.mark.slow` | Skipped in all normal CI runs; requires model download | High | Low | **Review** — ensure adequate coverage exists for config-persistence paths in non-slow tests |
| Skipped Tests | `tests/test_embedding_cache.py` | multiple | 4 test methods marked `@pytest.mark.slow` | `test_cache_hit_reuses_embedding`, `test_cache_miss_calls_encoder`, `test_cache_preserves_accuracy`, `test_embedding_cache_isolated` | High | Low | **Keep** — skip is intentional, requires HuggingFace model download |

### 3.3 conftest Helper Never Called

| Category | File Path | Line(s) | Name / Description | Context | Confidence | Risk | Suggested Action |
|----------|-----------|---------|-------------------|---------|------------|------|-----------------|
| Unused Helper | `tests/conftest.py` | 53–65 | `_is_retriever_collection_healthy()` | Checks `api._retriever.collection.count()` but is not used as a skip guard, assertion helper, or fixture dependency anywhere in the test suite | High | Low | **Remove** |

---

## Category 4: Advanced Patterns

### 4.1 Duplicate Function Implementations

| Category | Files | Names | Description | Confidence | Risk | Suggested Action |
|----------|-------|-------|-------------|------------|------|-----------------|
| Duplicate | `api.py:413–442` and `mcp_server.py:76–93` | `_build_corpus_version_token()` | Near-identical implementations. Both read `_cache_generation`, call `_retriever.collection.count()`, and return `f"gen{N}.n{count}"`. The `mcp_server.py` docstring even says "Mirrors the same helper in api.py." | High | Medium | **Refactor** — extract to a shared utility in `hybrid_rag` (e.g., `hybrid_rag.cache` or a new `hybrid_rag.utils`) |
| Duplicate | `api.py:536–572` and `mcp_server.py:176–202` | Cache key construction in `_shared_retrieve_documents()` vs `query_knowledge_base()` | Identical SHA-256 JSON fingerprint logic (config dict → hash → `"shared-retrieve:"` prefix) manually duplicated. | High | **High** | **Refactor** — extract to a shared helper immediately; divergence would silently break Redis cache sharing between the two processes |

### 4.2 Magic Numbers Inconsistent With Named Constants

| Category | File Path | Line(s) | Value | Description | Confidence | Risk | Suggested Action |
|----------|-----------|---------|-------|-------------|------------|------|-----------------|
| Magic Number | `routers/websocket.py` | 113 | `0.40` | Min-score threshold hardcoded; `MIN_RELEVANCE_SCORE = 0.80` exists in `constants.py` but is not used here | High | Medium | **Refactor** — either use `MIN_RELEVANCE_SCORE` or define a second explicit constant (e.g., `MIN_SCORE_RETRIEVAL = 0.40`) and document the intent |
| Magic Number | `mcp_server.py` | 258 | `0.40` | Same hardcoded threshold as the WS handler; inconsistent with the `MIN_RELEVANCE_SCORE` constant | High | Medium | **Refactor** — apply the same fix; ensure both entry points agree or the difference is intentionally named |

### 4.3 Orphaned / Unguarded Scripts

| Category | File Path | Line(s) | Name / Description | Context | Confidence | Risk | Suggested Action |
|----------|-----------|---------|-------------------|---------|------------|------|-----------------|
| Orphaned Script | `main.py` | 1–6 | Trivial `def main(): print("Hello from python-hol!")` | Placeholder with no actual logic; the real entry points are `api.py` and `mcp_server.py` | High | Low | **Remove** or promote to a real CLI entry point |
| Orphaned Script | `hybrid_rag_flow.py` | 1–40 | Example demo script with no `if __name__ == "__main__"` guard | Executes vector DB initialization at import time — importing it in a test or tool would trigger a side-effect | High | Low | **Review** — add `if __name__ == "__main__":` guard or move to `examples/` directory |
| Orphaned Script | `main_example.py` | 1–111 | Well-structured example demonstrating the library | Has a proper `__main__` guard but is referenced nowhere in the codebase or docs | High | Low | **Review** — move to `examples/` or reference in README |

### 4.4 Private Function Not Reflected in `__all__`

| Category | File Path | Line(s) | Name / Description | Context | Confidence | Risk | Suggested Action |
|----------|-----------|---------|-------------------|---------|------------|------|-----------------|
| API Surface | `hybrid_rag/persistence.py` | 23–32 | `get_config_file_path()` | Used internally by `save_config_to_disk` and `load_config_from_disk` but **not** listed in `__all__`. May be useful for tooling but is invisible to external consumers. | Medium | Low | **Review** — add to `__all__` if intended as public API, or rename to `_get_config_file_path` to signal it is internal |

---

## Summary

| Category | Findings | High Confidence | Recommended Action |
|----------|----------|----------------|--------------------|
| Unused functions | 2 | 2 | Remove / Inline |
| Superseded classes | 3 | 3 | Review / Schedule deprecation |
| Intentional-but-flagged imports | 2 | 1 | Keep (document) |
| Unused constants | 1 | 1 | Refactor |
| Commented-out blocks | 1 | 1 | Remove |
| Dead branches | 1 | 1 | Review |
| Unused test fixtures | 2 | 2 | Remove |
| Skipped tests | 5 | 5 | Keep / Review coverage |
| Duplicate implementations | 2 | 2 | Refactor |
| Magic-number inconsistencies | 2 | 2 | Refactor |
| Orphaned scripts | 3 | 3 | Move / Remove |
| API surface gaps | 1 | 1 | Review |
| **Total** | **25** | **24** | |

---

## Top Priority Findings

| # | 🔴/🟠/🟡 | Finding | Why It Matters |
|---|-----------|---------|----------------|
| 1 | 🔴 | **Duplicate cache key construction** (`api.py` vs `mcp_server.py`) | If these implementations drift, the two processes silently build different cache keys and lose Redis sharing — a non-obvious production bug |
| 2 | 🟠 | **`MIN_RELEVANCE_SCORE` constant ignored** — both retrieval paths use `0.40`; the constant is `0.80` | The named constant gives false confidence; either the constant value or the hardcoded values are wrong |
| 3 | 🟠 | **Duplicate `_build_corpus_version_token()`** | Same logic in two files; future changes must be applied twice or the processes diverge silently |
| 4 | 🟡 | **`WsQueryMessage` defined but never used** | The WS handler bypasses this model entirely, providing no input validation benefit and misleading readers |
| 5 | 🟡 | **`hybrid_rag_flow.py` runs at import time** | No `if __name__ == "__main__"` guard means any import-time load triggers vector DB initialization as a side effect |
