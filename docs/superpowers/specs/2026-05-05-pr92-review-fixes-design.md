# Design: Address PR #92 Remaining Review Comments

**Date:** 2026-05-05  
**Branch:** `copilot/cleanup-api-file-structure`  
**Commit strategy:** Single commit — `fix(api): address remaining PR review comments`

---

## Scope

Nine targeted fixes across four files. No architectural changes. Test audit (owner review) is tracked separately as a follow-up.

---

## Changes

### `routers/documents.py` — SSRF hardening + metadata fixes

**Thread 12 — Unspecified addresses (0.0.0.0 / ::)**  
Add `addr.is_unspecified` to the IP rejection condition alongside the existing `is_private`, `is_loopback`, `is_link_local`, `is_reserved`, `is_multicast`, and `in _CGNAT` checks.

**Thread 13 — Userinfo in netloc**  
After scheme/netloc checks, reject any URL where `parsed.username` or `parsed.password` is set (HTTP Basic Auth in URL). Reconstruct `safe_url` netloc from `parsed.hostname` + optional `parsed.port` rather than reusing `parsed.netloc` verbatim, so credentials can never leak into logs or be forwarded to the remote server.

**Thread 14 — Metadata uses raw request content**  
For URL ingestion, `source_label` defaults to `request.source_label or safe_url` (not `request.content`), and `source_url` is set from `safe_url` (not `request.content`). The validated URL, not the raw user string, propagates to ChromaDB metadata and dedup lookups.

**Thread 15 — Misleading ingest_type log**  
At the early log (line ~220), check `"ingest_type" in request.model_fields_set`. If not explicitly set, log `ingest_type="auto"` and omit the "will be cleared/preserved" prediction (it's unknown until auto-detection completes). The resolved `effective_ingest_type` is already logged at line ~352; that log is sufficient and unchanged.

### `mcp_server.py` — Error surfacing + DEFAULT_CONFIG alignment

**Thread 9/21 — mcp_task exceptions swallowed**  
After `asyncio.wait` returns, if `mcp_task` is in `done` (transport exited before shutdown signal), call `mcp_task.result()` to re-raise any stored exception. This surfaces transport failures deterministically rather than swallowing them as `'Task exception was never retrieved'` warnings.

**Thread 10/20 — DEFAULT_CONFIG fallback**  
Replace both `HybridRetrieverConfig()` fallback constructions in `_load_initial_config()` with `DEFAULT_CONFIG`. Update docstring to accurately describe the fallback. This keeps MCP and REST API startup defaults aligned.

### `tests/test_mcp_server.py` — Monkeypatch signal handler fix

**Thread 17/18 — Instance-level attribute on event loop**  
Change `monkeypatch.setattr(loop, "add_signal_handler", ...)` to `monkeypatch.setattr(type(loop), "add_signal_handler", ...)` with `lambda self, sig, handler: handler()` (adds `self` parameter). Patching the class rather than the instance works on slot-based asyncio loop implementations.

### `routers/__init__.py` — Stale docstring reference

**Thread 19 — Line-number reference**  
Replace `See api.py lines 635-640` with a reference to the `_register_routers_on_app` symbol name, which is stable across refactors.

---

### `hybrid_rag/config.py` + `api.py` + `tests/conftest.py` — Canonical default weights

**Weight alignment across all flows**  
`DEFAULT_CONFIG` explicitly sets `semantic_weight=0.7, keyword_weight=0.3`, diverging from the dataclass field defaults of 0.65/0.35. Three changes make 0.65/0.35 the single source of truth:

- `hybrid_rag/config.py:173` — Remove explicit `semantic_weight` and `keyword_weight` from `DEFAULT_CONFIG` so it inherits the dataclass field defaults
- `api.py:212` — Update hardcoded `semantic_weight=0.7, keyword_weight=0.3` to 0.65/0.35
- `tests/conftest.py:59, 99` — Update hardcoded 0.7/0.3 to 0.65/0.35

`main_example.py` and `hybrid_rag_flow.py` are illustrative examples — left unchanged.

---

## Out of Scope

- Test audit / redundant test removal (owner review) — separate follow-up
- Any changes to `api_models.py`, `routers/health.py`, `routers/cache.py`, `routers/websocket.py`

---

## Verification

```bash
uv run ruff check .
uv run pytest tests/ -v
```

All 327 tests must pass (baseline from last commit).
