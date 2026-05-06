# PR #92 Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Address all unresolved PR #92 review threads plus align canonical default weights to 0.65/0.35.

**Architecture:** Targeted edits across 7 files — no new modules, no restructuring. Each task is independently verifiable. Single commit at the end.

**Tech Stack:** Python 3.13, FastAPI, asyncio, pytest, uv (run tests with `uv run pytest`)

---

## File Map

| File | Changes |
|------|---------|
| `hybrid_rag/config.py` | Remove explicit weights from `DEFAULT_CONFIG` |
| `api.py` | Update hardcoded 0.7/0.3 weights |
| `tests/conftest.py` | Update hardcoded 0.7/0.3 weights |
| `routers/documents.py` | SSRF: unspecified IPs, userinfo rejection, safe_url metadata, ingest_type log |
| `mcp_server.py` | Surface mcp_task exceptions; DEFAULT_CONFIG fallback |
| `tests/test_mcp_server.py` | Fix instance-level monkeypatch on event loop |
| `routers/__init__.py` | Fix stale line-number reference in docstring |

---

## Task 1: Canonical default weights — `hybrid_rag/config.py`

**Files:**
- Modify: `hybrid_rag/config.py:173-178`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py` inside the existing test class (or at module level if the file has no class):

```python
def test_default_config_weights_match_dataclass_field_defaults() -> None:
    from hybrid_rag import DEFAULT_CONFIG, HybridRetrieverConfig
    bare = HybridRetrieverConfig()
    assert DEFAULT_CONFIG.semantic_weight == bare.semantic_weight
    assert DEFAULT_CONFIG.keyword_weight == bare.keyword_weight
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/test_config.py::test_default_config_weights_match_dataclass_field_defaults -v
```

Expected: FAIL — `assert 0.7 == 0.65`

- [ ] **Step 3: Remove explicit weights from DEFAULT_CONFIG**

In `hybrid_rag/config.py`, change lines 173-178 from:

```python
DEFAULT_CONFIG = HybridRetrieverConfig(
    semantic_weight=0.7,
    keyword_weight=0.3,
    enable_rerank=True,
    collection_name="rag_collection",
)
```

To:

```python
DEFAULT_CONFIG = HybridRetrieverConfig(
    enable_rerank=True,
    collection_name="rag_collection",
)
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
uv run pytest tests/test_config.py::test_default_config_weights_match_dataclass_field_defaults -v
```

Expected: PASS

---

## Task 2: Canonical default weights — `api.py` and `tests/conftest.py`

**Files:**
- Modify: `api.py:211-212`
- Modify: `tests/conftest.py:58-59`, `tests/conftest.py:98-101`

- [ ] **Step 1: Update hardcoded weights in `api.py`**

In `api.py`, change lines 211-212 from:

```python
            _config = HybridRetrieverConfig(
                semantic_weight=0.7, keyword_weight=0.3, enable_rerank=True
            )
```

To:

```python
            _config = HybridRetrieverConfig(
                semantic_weight=0.65, keyword_weight=0.35, enable_rerank=True
            )
```

- [ ] **Step 2: Update hardcoded weights in `tests/conftest.py` (fake retriever fixture)**

In `tests/conftest.py`, change lines 58-59 from:

```python
    obj.config = HybridRetrieverConfig(
        semantic_weight=0.7, keyword_weight=0.3, enable_rerank=False
    )
```

To:

```python
    obj.config = HybridRetrieverConfig(
        semantic_weight=0.65, keyword_weight=0.35, enable_rerank=False
    )
```

- [ ] **Step 3: Update hardcoded weights in `tests/conftest.py` (initialized_app fixture)**

In `tests/conftest.py`, change lines 98-101 from:

```python
        config = HybridRetrieverConfig(
            semantic_weight=0.7,
            keyword_weight=0.3,
            enable_rerank=True
        )
```

To:

```python
        config = HybridRetrieverConfig(
            semantic_weight=0.65,
            keyword_weight=0.35,
            enable_rerank=True
        )
```

- [ ] **Step 4: Run full test suite to verify no regressions**

```bash
uv run pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: same pass/fail count as baseline (327 passed)

---

## Task 3: SSRF — unspecified IP addresses and userinfo rejection

**Files:**
- Modify: `routers/documents.py:53-140` (`_validate_url_for_ssrf`)
- Test: `tests/test_ingestion_paths.py`

- [ ] **Step 1: Write failing tests for unspecified IPs and userinfo**

Add a new test class to `tests/test_ingestion_paths.py`:

```python
class TestValidateUrlForSsrf:
    """Unit tests for _validate_url_for_ssrf."""

    def test_unspecified_ipv4_raises_400(self) -> None:
        from routers.documents import _validate_url_for_ssrf
        from fastapi import HTTPException
        import pytest
        with pytest.raises(HTTPException) as exc_info:
            _validate_url_for_ssrf("http://0.0.0.0/evil")
        assert exc_info.value.status_code == 400

    def test_userinfo_in_url_raises_400(self) -> None:
        from routers.documents import _validate_url_for_ssrf
        from fastapi import HTTPException
        import pytest
        with pytest.raises(HTTPException) as exc_info:
            _validate_url_for_ssrf("http://user:pass@example.com/path")
        assert exc_info.value.status_code == 400

    def test_userinfo_username_only_raises_400(self) -> None:
        from routers.documents import _validate_url_for_ssrf
        from fastapi import HTTPException
        import pytest
        with pytest.raises(HTTPException) as exc_info:
            _validate_url_for_ssrf("http://user@example.com/path")
        assert exc_info.value.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_ingestion_paths.py::TestValidateUrlForSsrf -v
```

Expected: 3 FAILs (unspecified IP passes through; userinfo passes through)

- [ ] **Step 3: Add userinfo rejection and unspecified IP check**

In `routers/documents.py`, update `_validate_url_for_ssrf`:

**After** the `if not parsed.netloc:` block (line 88-92), add the userinfo check:

```python
    if parsed.username or parsed.password:
        raise HTTPException(
            status_code=400,
            detail="URLs with embedded credentials (userinfo) are not permitted.",
        )
```

**In** the IP check condition (lines 112-119), add `addr.is_unspecified`:

```python
        if (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_reserved
            or addr.is_multicast
            or addr.is_unspecified
            or addr in _CGNAT
        ):
```

**Also** update the docstring to reflect these additions. Replace the `Raises:` section:

```python
    Raises:
        HTTPException: 400 if scheme/host is invalid, URL contains userinfo,
            or any resolved IP is private/reserved/unspecified.
        HTTPException: 502 if DNS resolution fails.
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/test_ingestion_paths.py::TestValidateUrlForSsrf -v
```

Expected: 3 PASSes

---

## Task 4: SSRF — strip userinfo from reconstructed safe_url netloc

**Files:**
- Modify: `routers/documents.py:128-140` (the `urlunparse` block)

Note: userinfo is now *rejected* in Task 3, so no real URL will reach this code with credentials. This task makes the reconstruction explicitly safe regardless, so static analysis tools and future audits see no data-flow path from `parsed.netloc` (which could theoretically include userinfo) to the outbound request.

- [ ] **Step 1: Reconstruct netloc from hostname + port only**

In `routers/documents.py`, replace the `safe_url = urlunparse(...)` block (lines 132-139):

From:

```python
    safe_url = urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        parsed.query,
        "",  # strip fragment — not sent to server
    ))
    return safe_url
```

To:

```python
    safe_netloc = (
        f"{parsed.hostname}:{parsed.port}" if parsed.port else parsed.hostname
    )
    safe_url = urlunparse((
        parsed.scheme,
        safe_netloc,
        parsed.path,
        parsed.params,
        parsed.query,
        "",  # strip fragment — not sent to server
    ))
    return safe_url
```

- [ ] **Step 2: Run existing SSRF tests to verify no regression**

```bash
uv run pytest tests/test_ingestion_paths.py -v
```

Expected: all pass

---

## Task 5: Metadata — use safe_url for source_label and source_url

**Files:**
- Modify: `routers/documents.py` — URL branch and metadata block

- [ ] **Step 1: Initialize safe_url before the source_type branches**

In `routers/documents.py`, add `safe_url: Optional[str] = None` immediately before the `if request.source_type == "text":` line (~line 224). It is already `Optional` imported from `typing`.

```python
        safe_url: Optional[str] = None

        if request.source_type == "text":
```

- [ ] **Step 2: Fix source_label for URL ingestion (line ~254)**

Change:

```python
            source_label = request.source_label or request.content
```

To:

```python
            source_label = request.source_label or safe_url
```

- [ ] **Step 3: Fix source_url metadata derivation (lines ~315-317)**

Change:

```python
            parsed = urlparse(request.content)
            is_http_url = parsed.scheme in ("http", "https") and bool(parsed.netloc)
            source_url = request.content if is_http_url else None
```

To:

```python
            source_url = safe_url  # None for text/file; validated URL for url type
```

- [ ] **Step 4: Run ingestion tests**

```bash
uv run pytest tests/test_ingestion_paths.py tests/test_vectordb_metadata.py -v
```

Expected: all pass

---

## Task 6: Log — fix misleading ingest_type log

**Files:**
- Modify: `routers/documents.py:218-222`

- [ ] **Step 1: Replace the early ingest_type log**

Change lines 218-222 from:

```python
        api.logger.info(
            "Ingest type: %s; cache %s",
            request.ingest_type,
            "will be cleared" if request.ingest_type == "update" else "will be preserved",
        )
```

To:

```python
        if "ingest_type" in request.model_fields_set:
            api.logger.info("Ingest type: %s", request.ingest_type)
        else:
            api.logger.info("Ingest type: auto (will be resolved from collection)")
```

- [ ] **Step 2: Run observability log tests**

```bash
uv run pytest tests/test_observability_logs.py tests/test_optb013_docs_closeout.py -v
```

Expected: all pass

---

## Task 7: mcp_server.py — surface mcp_task exceptions

**Files:**
- Modify: `mcp_server.py:368-370` (after the `finally` block)
- Test: `tests/test_mcp_server.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_mcp_server.py`:

```python
@pytest.mark.asyncio
async def test_main_surfaces_mcp_task_exception(monkeypatch):
    """main() should propagate exceptions from the MCP transport task."""
    monkeypatch.setattr(mcp_server, "_initialize_retriever", AsyncMock())
    monkeypatch.setattr(mcp_server, "_resolve_transport", lambda: "stdio")

    loop = asyncio.get_running_loop()
    monkeypatch.setattr(
        type(loop), "add_signal_handler", lambda self, sig, handler: None
    )

    async def raise_error():
        raise RuntimeError("transport crashed")

    monkeypatch.setattr(mcp_server.mcp, "run_stdio_async", raise_error)

    with pytest.raises(RuntimeError, match="transport crashed"):
        await mcp_server.main()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/test_mcp_server.py::test_main_surfaces_mcp_task_exception -v
```

Expected: FAIL — no exception raised, test assertion fails

- [ ] **Step 3: Add exception surfacing after asyncio.wait**

In `mcp_server.py`, after the `finally` block that cleans up `shutdown_wait_task` (after line 367), insert:

```python
    # Surface transport exception if task exited before a shutdown signal
    if mcp_task in done and not shutdown_event.is_set():
        mcp_task.result()  # re-raises any stored exception
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
uv run pytest tests/test_mcp_server.py::test_main_surfaces_mcp_task_exception -v
```

Expected: PASS

---

## Task 8: mcp_server.py — DEFAULT_CONFIG fallback

**Files:**
- Modify: `mcp_server.py:62-85` (`_load_initial_config`)

- [ ] **Step 1: Replace both HybridRetrieverConfig() fallbacks with DEFAULT_CONFIG**

In `mcp_server.py`, in `_load_initial_config`, change line 82:

```python
            config = HybridRetrieverConfig()
```

To:

```python
            config = DEFAULT_CONFIG
```

And line 85:

```python
        config = HybridRetrieverConfig()
```

To:

```python
        config = DEFAULT_CONFIG
```

- [ ] **Step 2: Verify docstring is accurate**

The existing docstring at line 66 already says "uses DEFAULT_CONFIG" — it is now correct. No change needed.

- [ ] **Step 3: Run mcp_server tests**

```bash
uv run pytest tests/test_mcp_server.py -v
```

Expected: all pass

---

## Task 9: tests/test_mcp_server.py — fix instance-level monkeypatch

**Files:**
- Modify: `tests/test_mcp_server.py:352`, `tests/test_mcp_server.py:385`

- [ ] **Step 1: Fix the monkeypatch in test_main_graceful_shutdown_calls_mcp_shutdown**

In `tests/test_mcp_server.py`, at line 352, change:

```python
    monkeypatch.setattr(loop, "add_signal_handler", lambda sig, handler: handler())
```

To:

```python
    monkeypatch.setattr(type(loop), "add_signal_handler", lambda self, sig, handler: handler())
```

- [ ] **Step 2: Fix the same pattern in test_main_graceful_shutdown_uses_stop_when_shutdown_missing**

At line 385, change:

```python
    monkeypatch.setattr(loop, "add_signal_handler", lambda sig, handler: handler())
```

To:

```python
    monkeypatch.setattr(type(loop), "add_signal_handler", lambda self, sig, handler: handler())
```

- [ ] **Step 3: Also update the new test added in Task 7** to use the same class-level pattern (it already does — confirm the lambda is `lambda self, sig, handler: None`)

- [ ] **Step 4: Run all mcp_server tests**

```bash
uv run pytest tests/test_mcp_server.py -v
```

Expected: all pass

---

## Task 10: routers/__init__.py — fix stale line-number reference

**Files:**
- Modify: `routers/__init__.py:18`

- [ ] **Step 1: Update the docstring**

Change line 18 from:

```python
     See api.py lines 635-640 for how the routers are imported.
```

To:

```python
     See _register_routers_on_app() in api.py for how routers are registered.
```

- [ ] **Step 2: Run lint**

```bash
uv run ruff check routers/__init__.py
```

Expected: no errors

---

## Task 11: Final verification and commit

- [ ] **Step 1: Run full lint**

```bash
uv run ruff check .
```

Expected: no errors

- [ ] **Step 2: Run full test suite**

```bash
uv run pytest tests/ -v 2>&1 | tail -20
```

Expected: ≥327 passed (new tests from Tasks 1, 3, 7 add at least 5 more), same skip/error counts as baseline

- [ ] **Step 3: Commit**

```bash
git add \
  hybrid_rag/config.py \
  api.py \
  tests/conftest.py \
  routers/documents.py \
  mcp_server.py \
  tests/test_mcp_server.py \
  tests/test_ingestion_paths.py \
  tests/test_config.py \
  routers/__init__.py \
  docs/superpowers/specs/2026-05-05-pr92-review-fixes-design.md \
  docs/superpowers/plans/2026-05-05-pr92-review-fixes.md
git commit -m "fix(api): address remaining PR #92 review comments"
```
