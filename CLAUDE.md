# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Full-stack monorepo: a **Python Hybrid RAG library** (`hybrid_rag/`) with a **FastAPI REST/WebSocket API** (`api.py`) and a **Next.js 16 frontend** (`frontend/`). The RAG pipeline combines semantic search (ChromaDB embeddings) + keyword search (BM25-style) with optional cross-encoder reranking.

## Commands

### Python Backend

```bash
# Install (uv preferred)
uv sync

# Run tests
pytest tests/ -v

# Run a single test file
pytest tests/test_cache.py -v

# Run with coverage
pytest tests/ -v --cov=hybrid_rag --cov=api

# Start FastAPI server
uvicorn api:app --reload
```

pytest is configured with `asyncio_mode = "auto"` in `pyproject.toml` — no per-test async decorators needed.

### Frontend

```bash
cd frontend
pnpm install
pnpm dev          # http://localhost:3000
pnpm build
pnpm lint
pnpm tsc --noEmit
pnpm test:unit
```

## Architecture

### Hybrid RAG Pipeline (`hybrid_rag/`)

Five-stage retrieval in `retriever.py`:
1. Semantic search via ChromaDB (`vectordb.py`)
2. Keyword search (stop-word filtered, `constants.py`)
3. Score fusion (weighted combination, configurable in `config.py`)
4. Cross-encoder reranking via ms-marco model (`reranker.py`)
5. Source deduplication

Public API is exported through `__init__.py` with `__all__`. Configuration uses validated dataclasses (`config.py` with `__post_init__` validation, defaults from `constants.py`).

### Caching (`cache.py`, `api_middleware.py`)

Three-layer design:
- **L1** — Full query response cache (FastAPI middleware in `api_middleware.py`); backend switchable via `CACHE_BACKEND=memory|redis`
- **L2** — LRU embedding cache inside `HybridRetriever` (session-scoped)
- **L3** — ChromaDB persistent vector storage

Cache failures are fail-open. Monitor at `GET /cache/stats`. Configure via `CACHE_BACKEND`, `REDIS_URL`, `CACHE_TTL_SECONDS`.

### API Layer (`api.py`)

FastAPI app (~1600 lines) with:
- `POST /retrieve` — synchronous retrieval
- `WS /ws/chat` — real-time streaming chat
- `GET /cache/stats` — cache observability
- `GET /health` — health check
- Configuration management endpoints
- CORS middleware enabled

### Frontend (`frontend/`)

Next.js 16.2.3 (App Router) + React 19 + Zustand + Tailwind v4. Components are feature-organized under `src/components/{chat,data,layout,settings,ui}/`. WebSocket client lives in `src/lib/ws.ts`. State management via Zustand stores in `src/stores/`.

**Next.js 16 has breaking changes from 13/14.** Before writing frontend code, check `frontend/AGENTS.md` for documented breaking changes and check current API patterns in `node_modules/next/dist/docs/`.

## Key Conventions

### Python
- All functions must have comprehensive type hints (`py.typed` marker present)
- Use custom exceptions from `hybrid_rag.exceptions` — never bare `Exception`
- Module-level loggers only: `logger = logging.getLogger(__name__)` — no `print()`
- Google-style docstrings with Args/Returns/Raises/Example on all public functions
- Config validated in `__post_init__`; defaults centralized in `constants.py`

### TypeScript/Frontend
- No implicit `any` types
- Zod validation at API boundaries
- No component-local state for server data — use Zustand stores
- Accessibility attributes required (`alt`, `aria-label`, etc.)

## Environment

Copy `.env.local.example` to `.env.local`. Python 3.13+ and Node 20.9+ required.
