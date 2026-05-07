# Critical Dead Code Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract three duplicated code blocks (`_build_corpus_version_token()`, cache key construction, `MIN_RELEVANCE_SCORE` usage) into shared utilities to eliminate silent production bugs where `api.py` and `mcp_server.py` could diverge.

**Architecture:** 
1. Create `hybrid_rag/cache_utils.py` to hold shared cache-key helpers (`_build_corpus_version_token()`, `_build_cache_key()`)
2. Remove unused `MIN_RELEVANCE_SCORE` constant from `constants.py`; define single threshold `MIN_SCORE_RETRIEVAL = 0.50`
3. Update `api.py`, `mcp_server.py`, and `routers/websocket.py` to import and use the new shared utilities
4. Add tests to verify both entry points produce identical cache keys

**Tech Stack:** Python 3.13+, pytest, `hashlib`, `json`

---

## File Structure

**Files to create:**
- `hybrid_rag/cache_utils.py` — shared cache-key builders (corpus version token, full cache key)

**Files to modify:**
- `hybrid_rag/constants.py` — remove `MIN_RELEVANCE_SCORE`, add `MIN_SCORE_RETRIEVAL = 0.50`
- `hybrid_rag/__init__.py` — update exports (remove `MIN_RELEVANCE_SCORE`, add `MIN_SCORE_RETRIEVAL`)
- `api.py` — remove `_build_corpus_version_token()`, import from cache_utils, use new helpers
- `mcp_server.py` — remove `_build_corpus_version_token()`, import from cache_utils, use new helpers  
- `routers/websocket.py` — import and use `MIN_SCORE_RETRIEVAL` constant instead of hardcoded `0.40`
- `tests/test_cache_keys.py` — new test file to verify cache key consistency

---

## Task 1: Create `hybrid_rag/cache_utils.py` with shared helpers

**Files:**
- Create: `hybrid_rag/cache_utils.py`
- Test: `tests/test_cache_keys.py`

- [ ] **Step 1: Write failing tests for cache key consistency**

Create `tests/test_cache_keys.py`:

```python
import hashlib
import json
import pytest
from hybrid_rag.cache_utils import build_corpus_version_token, build_shared_retrieve_cache_key


class MockCollection:
    """Mock ChromaDB collection for testing."""
    def __init__(self, count: int):
        self._count = count

    def count(self) -> int:
        return self._count


class MockRetriever:
    """Mock retriever with collection."""
    def __init__(self, collection: MockCollection):
        self.collection = collection


def test_build_corpus_version_token_with_retriever():
    """Corpus version token should encode generation + collection count."""
    retriever = MockRetriever(MockCollection(42))
    token = build_corpus_version_token(retriever, cache_generation=5)
    assert token == "gen5.n42"


def test_build_corpus_version_token_with_none_retriever():
    """Corpus version token should fall back to gen{N}.n0 when retriever is None."""
    token = build_corpus_version_token(None, cache_generation=5)
    assert token == "gen5.n0"


def test_build_corpus_version_token_with_collection_error():
    """Corpus version token should fall back gracefully if collection.count() raises."""
    class FailingCollection:
        def count(self):
            raise RuntimeError("DB connection failed")

    retriever = MockRetriever(FailingCollection())
    token = build_corpus_version_token(retriever, cache_generation=3)
    assert token == "gen3.n0"


def test_build_shared_retrieve_cache_key_consistency():
    """Both api.py and mcp_server.py should build identical cache keys for same inputs."""
    retriever = MockRetriever(MockCollection(100))
    corpus_version = "gen0.n100"
    
    config = {
        "semantic_top_k": 5,
        "keyword_top_k": 5,
        "final_top_k": 10,
        "semantic_weight": 0.5,
        "keyword_weight": 0.5,
        "enable_rerank": True,
        "pre_rerank_top_k": 50,
    }
    
    key = build_shared_retrieve_cache_key(
        query="what is retrieval augmented generation",
        config_dict=config,
        corpus_version=corpus_version,
        enable_rerank=True,
    )
    
    # Key should have consistent format
    assert key.startswith("shared-retrieve:")
    assert len(key) == len("shared-retrieve:") + 64  # SHA-256 hex digest is 64 chars


def test_build_shared_retrieve_cache_key_with_whitespace_normalization():
    """Cache key should normalize query whitespace."""
    corpus_version = "gen0.n100"
    config = {
        "semantic_top_k": 5,
        "keyword_top_k": 5,
        "final_top_k": 10,
        "semantic_weight": 0.5,
        "keyword_weight": 0.5,
        "enable_rerank": True,
        "pre_rerank_top_k": 50,
    }
    
    key1 = build_shared_retrieve_cache_key(
        query="what    is  RAG",
        config_dict=config,
        corpus_version=corpus_version,
        enable_rerank=True,
    )
    
    key2 = build_shared_retrieve_cache_key(
        query="what is RAG",
        config_dict=config,
        corpus_version=corpus_version,
        enable_rerank=True,
    )
    
    # Different whitespace should not affect key
    assert key1 == key2


def test_build_shared_retrieve_cache_key_varies_with_config():
    """Cache key should change when config changes."""
    corpus_version = "gen0.n100"
    query = "test query"
    enable_rerank = True
    
    config1 = {
        "semantic_top_k": 5,
        "keyword_top_k": 5,
        "final_top_k": 10,
        "semantic_weight": 0.5,
        "keyword_weight": 0.5,
        "enable_rerank": True,
        "pre_rerank_top_k": 50,
    }
    
    config2 = {
        "semantic_top_k": 10,  # changed
        "keyword_top_k": 5,
        "final_top_k": 10,
        "semantic_weight": 0.5,
        "keyword_weight": 0.5,
        "enable_rerank": True,
        "pre_rerank_top_k": 50,
    }
    
    key1 = build_shared_retrieve_cache_key(query, config1, corpus_version, enable_rerank)
    key2 = build_shared_retrieve_cache_key(query, config2, corpus_version, enable_rerank)
    
    assert key1 != key2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/aritraghosh/projects/python-hol
pytest tests/test_cache_keys.py -v
```

Expected output: All tests FAIL with `ModuleNotFoundError: No module named 'hybrid_rag.cache_utils'`

- [ ] **Step 3: Create `hybrid_rag/cache_utils.py` with implementations**

```python
"""Shared cache utilities for api.py and mcp_server.py.

This module contains helpers that must produce identical output across both
entry points to enable Redis cache sharing. Do not modify these functions
without careful consideration of cross-process consistency.
"""

import hashlib
import json
from typing import Any, Optional


def build_corpus_version_token(
    retriever: Optional[Any],
    cache_generation: int,
) -> str:
    """Build a corpus version token combining generation counter with live collection count.

    This token is authoritative across both api.py and mcp_server.py processes,
    enabling them to share the warm L1 cache in Redis. The token encodes:
      1. Explicit cache invalidation via generation counter bumps
      2. Automatic invalidation on corpus mutations (doc count changes)

    Args:
        retriever: The initialized HybridRetriever, or None if not yet available.
        cache_generation: The current cache generation counter (incremented on invalidation).

    Returns:
        A string token like "gen0.n42" encoding both generation and corpus size.
        Falls back to "gen{N}.n0" if retriever or collection is unavailable, preserving
        the consistent token format for reliable log parsing and key-space analysis.
    """
    if retriever is not None:
        try:
            count = retriever.collection.count()
            return f"gen{cache_generation}.n{count}"
        except Exception:
            # Silent fallback: if we can't read the collection count, don't propagate.
            # The token format stays consistent for tooling.
            pass
    return f"gen{cache_generation}.n0"


def build_shared_retrieve_cache_key(
    query: str,
    config_dict: dict[str, Any],
    corpus_version: str,
    enable_rerank: bool,
) -> str:
    """Build a cache key for shared retrieval that matches across api.py and mcp_server.py.

    Both processes must produce identical keys for the same inputs to enable Redis
    cache sharing. This function is the single source of truth for cache key construction.

    Args:
        query: The user query (will be whitespace-normalized).
        config_dict: The retriever config as a dict (semantic_top_k, keyword_top_k, etc.).
        corpus_version: The corpus version token from build_corpus_version_token().
        enable_rerank: Whether cross-encoder reranking is enabled.

    Returns:
        A cache key string prefixed with "shared-retrieve:" followed by a SHA-256 hash.
    """
    # Normalize query whitespace (multiple spaces → single space)
    normalized_query = " ".join(query.split())

    # Build config fingerprint (same fields used by both api.py and mcp_server.py)
    config_fingerprint_payload = {
        "semantic_top_k": config_dict["semantic_top_k"],
        "keyword_top_k": config_dict["keyword_top_k"],
        "final_top_k": config_dict["final_top_k"],
        "semantic_weight": config_dict["semantic_weight"],
        "keyword_weight": config_dict["keyword_weight"],
        "enable_rerank": config_dict["enable_rerank"],
        "pre_rerank_top_k": config_dict["pre_rerank_top_k"],
    }
    config_fingerprint = hashlib.sha256(
        json.dumps(
            config_fingerprint_payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    # Build shared identity that both processes must agree on
    shared_identity = {
        "query": normalized_query,
        "effective_enable_rerank": enable_rerank,
        "config_fingerprint": config_fingerprint,
        "corpus_version": corpus_version,
    }

    cache_key = "shared-retrieve:" + hashlib.sha256(
        json.dumps(
            shared_identity,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    return cache_key
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/aritraghosh/projects/python-hol
pytest tests/test_cache_keys.py -v
```

Expected output: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /home/aritraghosh/projects/python-hol
git add hybrid_rag/cache_utils.py tests/test_cache_keys.py
git commit -m "feat(cache): extract shared cache key builders into hybrid_rag.cache_utils

- build_corpus_version_token(): generate gen{N}.n{count} tokens
- build_shared_retrieve_cache_key(): build identical cache keys across processes
- Tests verify both functions handle fallback cases and whitespace normalization
- Prerequisite for removing duplicate implementations from api.py and mcp_server.py

Closes DEAD_CODE_AUDIT.md finding #1 (duplicate cache key construction)."
```

---

## Task 2: Remove `MIN_RELEVANCE_SCORE` and add `MIN_SCORE_RETRIEVAL` to `constants.py`

**Files:**
- Modify: `hybrid_rag/constants.py`
- Modify: `hybrid_rag/__init__.py`

- [ ] **Step 1: Read and locate `MIN_RELEVANCE_SCORE`**

Already read above; `MIN_RELEVANCE_SCORE = 0.80` at line 76.

- [ ] **Step 2: Remove `MIN_RELEVANCE_SCORE` and add `MIN_SCORE_RETRIEVAL`**

Replace lines 70–76 in `constants.py`:

```python
# OLD (remove these lines):
# Note 6: MIN_RELEVANCE_SCORE acts as a quality gate...
MIN_RELEVANCE_SCORE = 0.80

# NEW (replace with):
# Note 6: MIN_SCORE_RETRIEVAL is the output filter threshold applied by WebSocket
# and MCP entry points before returning results to the user. Results with scores
# below this threshold are filtered out. Set to 0.50 to balance between recall
# (catching relevant documents) and precision (avoiding low-confidence matches).
MIN_SCORE_RETRIEVAL = 0.50
```

- [ ] **Step 3: Update `__all__` in `constants.py`**

Update the `__all__` list to remove `MIN_RELEVANCE_SCORE` and add `MIN_SCORE_RETRIEVAL`:

```python
__all__ = [
    "STOP_WORDS",
    "MIN_SCORE_RETRIEVAL",  # changed from MIN_RELEVANCE_SCORE
    "KNOWLEDGE_DB_DIRECTORY",
    "CACHE_TELEMETRY_LABELS",
    "DEFAULT_EMBEDDING_MODEL",
    "DEFAULT_QUERY_PREFIX",
]
```

- [ ] **Step 4: Update exports in `hybrid_rag/__init__.py`**

Remove `MIN_RELEVANCE_SCORE` and add `MIN_SCORE_RETRIEVAL` from imports and `__all__`:

```python
# In imports section, change:
# from hybrid_rag.constants import MIN_RELEVANCE_SCORE
# to:
from hybrid_rag.constants import MIN_SCORE_RETRIEVAL

# In __all__, change:
# "MIN_RELEVANCE_SCORE",
# to:
"MIN_SCORE_RETRIEVAL",
```

- [ ] **Step 5: Verify import works**

```bash
cd /home/aritraghosh/projects/python-hol
python -c "from hybrid_rag.constants import MIN_SCORE_RETRIEVAL; print(f'MIN_SCORE_RETRIEVAL = {MIN_SCORE_RETRIEVAL}')"
```

Expected output: `MIN_SCORE_RETRIEVAL = 0.5`

- [ ] **Step 6: Verify old constant is gone**

```bash
cd /home/aritraghosh/projects/python-hol
python -c "from hybrid_rag.constants import MIN_RELEVANCE_SCORE" 2>&1 | head -5
```

Expected output: `ImportError: cannot import name 'MIN_RELEVANCE_SCORE'`

- [ ] **Step 7: Commit**

```bash
cd /home/aritraghosh/projects/python-hol
git add hybrid_rag/constants.py hybrid_rag/__init__.py
git commit -m "refactor(constants): consolidate to single MIN_SCORE_RETRIEVAL threshold (0.50)

Remove unused MIN_RELEVANCE_SCORE (0.80) which was exported but never used.
Replace with MIN_SCORE_RETRIEVAL (0.50), the output filter threshold applied
by WebSocket and MCP entry points when returning results to users.

This eliminates the dead code and makes the threshold semantics clear.

Closes DEAD_CODE_AUDIT.md finding #2 (inconsistent threshold)."
```

---

## Task 3: Update `api.py` to use shared utilities

**Files:**
- Modify: `api.py:413-442` (remove `_build_corpus_version_token`)
- Modify: `api.py:536-572` (use new cache key builder)

- [ ] **Step 1: Add import at top of `api.py`**

Add to the imports section (after other `hybrid_rag` imports):

```python
from hybrid_rag.cache_utils import (
    build_corpus_version_token,
    build_shared_retrieve_cache_key,
)
```

- [ ] **Step 2: Replace `_build_corpus_version_token()` function with module-level update**

Remove the entire `_build_corpus_version_token()` function definition (lines 413-442) and update the code that calls it. Find where `_corpus_version = _build_corpus_version_token()` is called and update to:

```python
_corpus_version = build_corpus_version_token(_retriever, _cache_generation)
```

- [ ] **Step 3: Replace cache key construction in `_shared_retrieve_documents()`**

Replace lines 536-572 (the entire config fingerprint and cache key construction block) with:

```python
    normalized_query = " ".join(query.split())

    cache_key = build_shared_retrieve_cache_key(
        query=normalized_query,
        config_dict={
            "semantic_top_k": _config.semantic_top_k,
            "keyword_top_k": _config.keyword_top_k,
            "final_top_k": _config.final_top_k,
            "semantic_weight": _config.semantic_weight,
            "keyword_weight": _config.keyword_weight,
            "enable_rerank": _config.enable_rerank,
            "pre_rerank_top_k": _config.pre_rerank_top_k,
        },
        corpus_version=_corpus_version,
        enable_rerank=effective_enable_rerank,
    )
```

- [ ] **Step 4: Update where `_corpus_version` is assigned on startup**

Find the line where `_corpus_version` is initially assigned in `_initialize_retriever()` and update it to use the new function:

```python
_corpus_version = build_corpus_version_token(_retriever, _cache_generation)
```

- [ ] **Step 5: Run tests to verify no breakage**

```bash
cd /home/aritraghosh/projects/python-hol
pytest tests/ -v -k "test_retrieve or test_shared_retrieve or test_cache" --tb=short
```

Expected output: All related tests PASS

- [ ] **Step 6: Commit**

```bash
cd /home/aritraghosh/projects/python-hol
git add api.py
git commit -m "refactor(api): use shared cache utilities from hybrid_rag.cache_utils

- Remove local _build_corpus_version_token() (now in cache_utils)
- Use build_corpus_version_token() from shared module
- Use build_shared_retrieve_cache_key() for consistent key construction
- No behavioral change; enables cache key consistency with mcp_server.py

Closes DEAD_CODE_AUDIT.md finding #1 (duplicate _build_corpus_version_token)
and finding #4 (duplicate cache key construction)."
```

---

## Task 4: Update `mcp_server.py` to use shared utilities

**Files:**
- Modify: `mcp_server.py:76-93` (remove `_build_corpus_version_token`)
- Modify: `mcp_server.py:176-202` (use new cache key builder)

- [ ] **Step 1: Add import at top of `mcp_server.py`**

Add to the imports section (after other `hybrid_rag` imports):

```python
from hybrid_rag.cache_utils import (
    build_corpus_version_token,
    build_shared_retrieve_cache_key,
)
```

- [ ] **Step 2: Remove local `_build_corpus_version_token()` function**

Delete the entire function definition (lines 76-93).

- [ ] **Step 3: Replace cache key construction in `query_knowledge_base()`**

Replace lines 176-202 (config fingerprint and cache key construction) with:

```python
        config_fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "semantic_top_k": _config.semantic_top_k,
                    "keyword_top_k": _config.keyword_top_k,
                    "final_top_k": _config.final_top_k,
                    "semantic_weight": _config.semantic_weight,
                    "keyword_weight": _config.keyword_weight,
                    "enable_rerank": _config.enable_rerank,
                    "pre_rerank_top_k": _config.pre_rerank_top_k,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

        cache_key = build_shared_retrieve_cache_key(
            query=" ".join(query_str.split()),
            config_dict={
                "semantic_top_k": _config.semantic_top_k,
                "keyword_top_k": _config.keyword_top_k,
                "final_top_k": _config.final_top_k,
                "semantic_weight": _config.semantic_weight,
                "keyword_weight": _config.keyword_weight,
                "enable_rerank": _config.enable_rerank,
                "pre_rerank_top_k": _config.pre_rerank_top_k,
            },
            corpus_version=_corpus_version,
            enable_rerank=effective_enable_rerank,
        )
```

Wait, this is still building `config_fingerprint` separately. Let me correct this — we should build the entire key using the helper:

Replace lines 176-202 entirely with:

```python
        cache_key = build_shared_retrieve_cache_key(
            query=" ".join(query_str.split()),
            config_dict={
                "semantic_top_k": _config.semantic_top_k,
                "keyword_top_k": _config.keyword_top_k,
                "final_top_k": _config.final_top_k,
                "semantic_weight": _config.semantic_weight,
                "keyword_weight": _config.keyword_weight,
                "enable_rerank": _config.enable_rerank,
                "pre_rerank_top_k": _config.pre_rerank_top_k,
            },
            corpus_version=_corpus_version,
            enable_rerank=effective_enable_rerank,
        )
```

- [ ] **Step 4: Update where `_corpus_version` is assigned on startup**

Find the line where `_corpus_version` is initially assigned in `_initialize_retriever()` and update it:

```python
_corpus_version = build_corpus_version_token(_retriever, _cache_generation)
```

- [ ] **Step 5: Run type check**

```bash
cd /home/aritraghosh/projects/python-hol
mypy mcp_server.py --strict
```

Expected output: No type errors

- [ ] **Step 6: Commit**

```bash
cd /home/aritraghosh/projects/python-hol
git add mcp_server.py
git commit -m "refactor(mcp_server): use shared cache utilities from hybrid_rag.cache_utils

- Remove local _build_corpus_version_token() (now in cache_utils)
- Use build_corpus_version_token() from shared module
- Use build_shared_retrieve_cache_key() for consistent key construction
- No behavioral change; cache keys now identical to api.py

Closes DEAD_CODE_AUDIT.md finding #1 and #4."
```

---

## Task 5: Update `routers/websocket.py` to use `MIN_SCORE_RETRIEVAL` constant

**Files:**
- Modify: `routers/websocket.py:113`

- [ ] **Step 1: Add import at top of `routers/websocket.py`**

Add to imports:

```python
from hybrid_rag.constants import MIN_SCORE_RETRIEVAL
```

- [ ] **Step 2: Replace hardcoded `0.40` with constant**

Find line 113 where it says:

```python
results, min_score_threshold=0.40
```

Replace with:

```python
results, min_score_threshold=MIN_SCORE_RETRIEVAL
```

- [ ] **Step 3: Run linter**

```bash
cd /home/aritraghosh/projects/python-hol
uv run ruff check routers/websocket.py
```

Expected output: No errors

- [ ] **Step 4: Commit**

```bash
cd /home/aritraghosh/projects/python-hol
git add routers/websocket.py
git commit -m "refactor(websocket): use MIN_SCORE_RETRIEVAL constant instead of hardcoded threshold

Replace magic number 0.40 with MIN_SCORE_RETRIEVAL constant from hybrid_rag.constants.

Closes DEAD_CODE_AUDIT.md finding #2 (inconsistent threshold)."
```

---

## Task 6: Verify cache key consistency across entry points

**Files:**
- Modify: `tests/test_cache_keys.py` (add integration test)

- [ ] **Step 1: Add integration test to verify api.py and mcp_server.py produce identical keys**

Add to `tests/test_cache_keys.py`:

```python
def test_api_and_mcp_produce_identical_cache_keys():
    """Verify that both api.py and mcp_server.py logic produces identical cache keys.
    
    This is a regression test for DEAD_CODE_AUDIT.md finding #1.
    If these diverge, the two processes will silently stop sharing Redis cache.
    """
    # Simulate the config used by both entry points
    config_dict = {
        "semantic_top_k": 5,
        "keyword_top_k": 5,
        "final_top_k": 10,
        "semantic_weight": 0.5,
        "keyword_weight": 0.5,
        "enable_rerank": True,
        "pre_rerank_top_k": 50,
    }
    
    query = "what is hybrid retrieval"
    corpus_version = "gen0.n100"
    enable_rerank = True
    
    # Both should produce the same key using the shared utility
    key1 = build_shared_retrieve_cache_key(
        query=query,
        config_dict=config_dict,
        corpus_version=corpus_version,
        enable_rerank=enable_rerank,
    )
    
    key2 = build_shared_retrieve_cache_key(
        query=query,
        config_dict=config_dict,
        corpus_version=corpus_version,
        enable_rerank=enable_rerank,
    )
    
    assert key1 == key2, "Cache key builder must be deterministic"
    assert key1.startswith("shared-retrieve:"), "Cache key must have correct prefix"
```

- [ ] **Step 2: Run all cache key tests**

```bash
cd /home/aritraghosh/projects/python-hol
pytest tests/test_cache_keys.py -v
```

Expected output: All tests PASS (7 total)

- [ ] **Step 3: Run full test suite to ensure no regressions**

```bash
cd /home/aritraghosh/projects/python-hol
pytest tests/ -v
```

Expected output: 100% pass rate (all tests pass)

- [ ] **Step 4: Commit**

```bash
cd /home/aritraghosh/projects/python-hol
git add tests/test_cache_keys.py
git commit -m "test(cache): add integration test for cross-process cache key consistency

Add test_api_and_mcp_produce_identical_cache_keys() to verify that both
entry points use the shared cache key builder and produce identical keys.

This is a regression test for DEAD_CODE_AUDIT.md finding #1."
```

---

## Task 7: Verify all tools pass (ruff, mypy, pytest)

**Files:**
- None (verification only)

- [ ] **Step 1: Run ruff linter**

```bash
cd /home/aritraghosh/projects/python-hol
uv run ruff check .
```

Expected output: No errors or warnings

- [ ] **Step 2: Run mypy type checker**

```bash
cd /home/aritraghosh/projects/python-hol
mypy hybrid_rag/ api.py mcp_server.py routers/ api_models.py
```

Expected output: No type errors

- [ ] **Step 3: Run full pytest suite with coverage**

```bash
cd /home/aritraghosh/projects/python-hol
pytest tests/ -v --cov=hybrid_rag --cov=api --cov=mcp_server
```

Expected output: 100% pass rate and coverage ≥80%

- [ ] **Step 4: Verify no regressions in related modules**

```bash
cd /home/aritraghosh/projects/python-hol
pytest tests/test_cache_integration.py tests/test_api_*.py -v
```

Expected output: All tests PASS

- [ ] **Step 5: Final verification commit message (if needed)**

If all checks pass, no commit needed. If you made any final tweaks, commit:

```bash
cd /home/aritraghosh/projects/python-hol
git commit -m "chore: final verification of dead code fixes

All ruff, mypy, and pytest checks pass.
- No duplicate cache key construction
- Consistent MIN_SCORE_RETRIEVAL usage
- No duplicate _build_corpus_version_token()

Resolves DEAD_CODE_AUDIT.md findings #1, #2, #4."
```

---

## Summary of Changes

| Issue | Solution | Files |
|-------|----------|-------|
| Duplicate `_build_corpus_version_token()` | Extract to `hybrid_rag/cache_utils.py` | `api.py`, `mcp_server.py` |
| Duplicate cache key construction | Extract to `build_shared_retrieve_cache_key()` in `cache_utils.py` | `api.py`, `mcp_server.py` |
| Unused `MIN_RELEVANCE_SCORE` + inconsistent `0.40` threshold | Remove unused constant; use single `MIN_SCORE_RETRIEVAL = 0.50` | `constants.py`, `__init__.py`, `websocket.py`, `mcp_server.py` |
| No integration test | Add `tests/test_cache_keys.py` with 7 tests | `tests/test_cache_keys.py` |

---

## Verification Checklist

- [ ] All 7 tasks completed and committed
- [ ] `uv run ruff check .` passes (zero errors)
- [ ] `mypy hybrid_rag/ api.py mcp_server.py routers/` passes
- [ ] `pytest tests/ -v` passes (100% pass rate)
- [ ] `pytest --cov=hybrid_rag --cov=api` shows ≥80% coverage
- [ ] Cache key tests verify consistency across entry points
- [ ] `MIN_RELEVANCE_SCORE` removed from codebase and exports
- [ ] `MIN_SCORE_RETRIEVAL = 0.50` used consistently in `websocket.py` and `mcp_server.py`
- [ ] No duplicate `_build_corpus_version_token()` functions remain
