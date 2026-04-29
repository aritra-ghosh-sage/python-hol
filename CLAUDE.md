# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Full-stack monorepo: a **Python Hybrid RAG library** (`hybrid_rag/`) with a **FastAPI REST/WebSocket API** (`api.py`) and a **Next.js 16 frontend** (`frontend/`). The RAG pipeline combines semantic search (ChromaDB embeddings) + keyword search (BM25-style) with optional cross-encoder reranking.

## Commands

### Python Backend

```bash
uv sync                                          # install
pytest tests/ -v                                 # run tests
pytest tests/ -v --cov=hybrid_rag --cov=api      # with coverage
mypy hybrid_rag/ api.py                          # type check
uv run ruff check .                              # lint
uvicorn api:app --reload                         # start server
```

pytest is configured with `asyncio_mode = "auto"` in `pyproject.toml` — no per-test async decorators needed.

A **Python change is only complete** when `uv run ruff check .` and `pytest tests/ -v` (100% pass) both succeed.

### Frontend

```bash
cd frontend && pnpm install
pnpm dev          # http://localhost:3000
pnpm build && pnpm lint && pnpm test:unit
```

A **frontend change is only complete** when `pnpm lint`, `pnpm test:unit`, and `pnpm build` all pass.

## Architecture

### Hybrid RAG Pipeline (`hybrid_rag/`)

Five-stage retrieval in `retriever.py`:
1. Semantic search via ChromaDB (`vectordb.py`)
2. Keyword search (stop-word filtered, `constants.py`)
3. Score fusion (weighted combination, configurable in `config.py`)
4. Cross-encoder reranking — model `cross-encoder/ms-marco-MiniLM-L-6-v2` (`reranker.py`)
5. Source deduplication

Public API (18 exports) in `__init__.py` with `__all__`:
- **Core**: `HybridRetriever`, `HybridRetrieverConfig`, `CrossEncoderReranker`, `DEFAULT_CONFIG`
- **Cache**: `CacheBackend`, `InMemoryCache`, `RedisCache`, `CacheSettings`, `create_cache_backend`
- **Exceptions**: `HybridRAGException`, `RetrieverNotInitializedError`, `RetrievalError`, `VectorDBError`
- **Utilities**: `chunk_text`, `chunk_document`, `initialize_vector_db`, `get_sample_documents`, `is_valid_collection_name`, `sanitize_collection_name`, `list_existing_collections`
- **Constants**: `STOP_WORDS`, `MIN_RELEVANCE_SCORE`, `KNOWLEDGE_DB_DIRECTORY`, `CACHE_TELEMETRY_LABELS`

Config uses validated dataclasses (`config.py`, `__post_init__` validation, defaults from `constants.py`). `HybridRetrieverConfig.update(**kwargs)` returns a new instance via `dataclasses.replace` — never mutates. Default collection name is `"rag_collection"` (ChromaDB enforces 6–20 chars; `is_valid_collection_name` / `sanitize_collection_name` validate/coerce).

### Caching (`cache.py`)

Three-layer design:
- **L1** — Full query response cache (shared retrieval layer in `api.py`); backend switchable via `CACHE_BACKEND=memory|redis`
- **L2** — LRU embedding cache inside `HybridRetriever` (session-scoped)
- **L3** — ChromaDB persistent vector storage

Cache failures are fail-open. Monitor at `GET /cache/stats`. Configure via env vars:
- `CACHE_BACKEND` — `memory` (default) or `redis`
- `REDIS_URL` — e.g. `redis://localhost:6379`; production requires `rediss://` (TLS) with password
- `CACHE_TTL_SECONDS` — entry lifespan (default: 3600)
- `CACHE_KEY_PREFIX` — prefix for shared Redis instances (default: `hybrid_rag_cache:`)
- `CACHE_MAX_SIZE` — max in-memory LRU entries (default: 10000)

**Cache invalidation**: L1 cache keys embed a `corpus_version` token built from `_cache_generation` + live `collection.count()` (format: `gen{N}.n{count}`). Increment the global `_cache_generation` int in `api.py` to bust the L1 cache after ingestion or config changes. Register new cache event types in `CACHE_TELEMETRY_LABELS` in `constants.py`.

### API Layer (`api.py`)

FastAPI app (~1600 lines). Routes:
- `WS /ws/chat` — real-time streaming chat (primary retrieval path; `POST /retrieve` was removed)
- `GET /health`, `GET /config`, `PUT /config` (also invalidates L1 cache)
- `GET /cache/stats`, `POST /documents`, `GET /documents/sources`
- CORS middleware enabled

### Frontend (`frontend/`)

Next.js 16.2.3 (App Router) + React 19 + Zustand + Tailwind v4. Components under `src/components/{chat,data,layout,settings,ui}/`. WebSocket client in `src/lib/ws.ts`. State in `src/stores/`.

**Next.js 16 has breaking changes from 13/14.** Before writing frontend code, check `frontend/AGENTS.md` and current API patterns in `node_modules/next/dist/docs/`.

## Testing

Fixtures from `tests/conftest.py`:
- `initialized_app` — real retriever + ChromaDB, ~10–18 s; skip if model unavailable
- `fake_initialized_app` — stub retriever, no model download, <10 ms; use for HTTP shape tests
- `client_with_fresh_cache` — cleared-cache variant (delegates to `fake_initialized_app`)

Prefer `fake_initialized_app` for tests that don't exercise the retrieval pipeline. Always check `collection.count()` before retrieval in integration tests. Async tests work without decorators (`asyncio_mode = "auto"`).

## Agent Infrastructure

Custom AI agents in `.github/agents/` (planner, orchestrator, implementer, debugger, reviewer, designer, researcher). Catalog and usage in `.github/AGENTS.md`. **For complex multi-step tasks, consult that file before starting.**

## Planning Discipline

**Use `/plan` before implementing any non-trivial feature or refactor.** The 3:1 fix-to-feature commit ratio in this repo comes from implementing before the approach is aligned. Plan first — it costs ~1k tokens; rework costs 5–10x that.

## File Read Discipline

High file-read token cost degrades every session. Required sequence for any symbol lookup:

1. **`grep` first** — locate exact line numbers before opening any file
2. **Explore subagent for broad questions** — `subagent_type: "Explore"` rather than reading files directly
3. **Range reads only** — always pass `offset` + `limit` to `Read` (±20 lines around grep result)
4. **No re-reads** — if a file is already in context, reference it; don't read again
5. Full-file reads only for files under ~80 lines

## Key Conventions

### Python

- **Formatting/lint**: RUFF, max 88 chars (Black-compatible). Run `uv run ruff check .` before committing.
- **Imports**: Three groups — stdlib, third-party, local — separated by blank lines
- **Type hints**: Required on all functions. Modern syntax: `list[str]`, `dict[str, Any]`. Use `Optional[T]` or `T | None`. `py.typed` marker present (PEP 561).
- **Naming**: `snake_case` functions, `PascalCase` classes, `UPPER_SNAKE_CASE` constants, `_single_underscore` private members
- **Docstrings**: Google style on all public functions, classes, modules
- **Errors**: Custom exceptions from `hybrid_rag.exceptions`. No bare `except Exception` except at fail-open boundaries. Module-level loggers only — no `print()`.
- **Config**: `@dataclass` with `__post_init__` validation. `replace()` for updates (immutable).
- **Tests**: 80% coverage minimum, 100% pass rate. `test_<method>_<condition>_<outcome>` naming. One test class per module.

### Git

Branch: `<type>/<name>` (types: `feature/`, `epic/`, `bugfix/`, `hotfix/`, `patch/`, `docs/`, `refactor/`, `test/`)

Commit: `<type>(<scope>): <subject>` (types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `perf`). Breaking changes: `feat(scope)!:` + `BREAKING CHANGE:` footer.

## Pre-Commit Checklist
- [ ] `pytest tests/ -v` — 100% pass
- [ ] `pytest --cov=hybrid_rag --cov=api` — ≥80% coverage
- [ ] `uv run ruff check .` — zero errors
- [ ] Type hints on all new functions
- [ ] Google-style docstrings on public functions
- [ ] No `print()` (use `logger`)
- [ ] Custom exceptions (no bare `Exception`)
- [ ] Updated `__all__` if adding public APIs

## Environment

Copy `.env.local.example` to `.env.local`. Python 3.13+ and Node 20.9+ required.
