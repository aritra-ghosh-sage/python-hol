# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

- `hybrid_rag/`: Python hybrid retrieval library
- `api.py` + `routers/`: FastAPI backend
- `frontend/`: Next.js 16 frontend

## Ignore
`ai_support_kb` folder and any underlying files during code scan

## Commands

### Python Backend

```bash
uv sync
uv run ruff check .
pytest tests/ -v
pytest tests/ -v --cov=hybrid_rag --cov=api
mypy hybrid_rag/ api.py api_models.py routers/
uvicorn api:app --reload
```

A Python change is only complete when:

- `uv run ruff check .` passes
- `pytest tests/ -v` passes

### Frontend

```bash
cd frontend
pnpm install
pnpm lint && pnpm build
pnpm test:unit
pnpm dev
```

A frontend change is only complete when `pnpm lint`, `pnpm test:unit`, and `pnpm build` all pass.

## Architecture

### Retrieval pipeline

Five stages in `hybrid_rag/retriever.py`:

1. semantic search via ChromaDB
2. keyword search with stop-word filtering
3. score fusion
4. optional reranking
5. source deduplication

### Public API

Exported from `hybrid_rag/__init__.py`:

- core: `HybridRetriever`, `HybridRetrieverConfig`, `CrossEncoderReranker`, `DEFAULT_CONFIG`
- cache: `CacheBackend`, `InMemoryCache`, `RedisCache`, `CacheSettings`, `create_cache_backend`
- exceptions: `HybridRAGException`, `RetrieverNotInitializedError`, `RetrievalError`, `VectorDBError`
- utilities: `chunk_text`, `chunk_document`, `initialize_vector_db`, `open_collection`, `get_sample_documents`, `is_valid_collection_name`, `sanitize_collection_name`, `list_existing_collections`, `save_config_to_disk`, `load_config_from_disk`, `resolve_startup_config`
- constants: `STOP_WORDS`, `MIN_SCORE_RETRIEVAL`, `KNOWLEDGE_DB_DIRECTORY`, `CACHE_TELEMETRY_LABELS`, `DEFAULT_EMBEDDING_MODEL`, `DEFAULT_QUERY_PREFIX`

### API surface

- `GET /`
- `GET /health`
- `GET /config`
- `PUT /config`
- `POST /documents`
- `GET /documents/sources`
- `GET /collections`
- `GET /cache/stats`
- `WS /ws/chat`

`POST /retrieve` is removed.

### Caching

- L1: query-response cache shared by the API layer
- L2: embedding LRU cache inside `HybridRetriever`
- L3: ChromaDB persistence

Cache failures must fail open.

## Testing Guidance

Important fixtures in `tests/conftest.py`:

- `initialized_app`: real retriever, slower
- `fake_initialized_app`: stub retriever, preferred for HTTP-shape tests
- `client_with_fresh_cache`: fake app with cleared cache

Use `fake_initialized_app` unless the test truly needs the retrieval pipeline.

Slow tests are skipped by default. Use `pytest tests/ --run-slow` to include them.

## Editing Rules

- Use `grep` before opening files.
- Prefer small range reads over full-file reads.
- Do not re-read files already in context unless needed.
- Use `apply_patch` for text edits.
- Preserve existing patterns and keep changes narrow.

## Python Conventions

- Ruff/Black-compatible formatting, max line length 88
- Type hints on all functions
- Google-style docstrings on public APIs
- Dataclass config with validation in `__post_init__`
- Use module loggers, not `print()`
- Use custom exceptions from `hybrid_rag.exceptions`

## Repo-Specific Rules

- Default collection name is `rag_collection`.
- `HybridRetrieverConfig.update(**kwargs)` returns a new instance.
- Router modules must access shared state through the `api` module.
- Do not add direct `requests` or `chromadb` imports in routers.
- `examples/` contains demo code and is not production code.

## Known Test Failures

Do not fix these as part of unrelated work:

- `test_all_acceptance_criteria_implemented`
- `test_url_html_ingestion_stores_heading_metadata`
- `test_ingest_update_clears_cache`
- `test_ingest_add_preserves_cache`

## Environment

 - Copy `.env.local.example` to `.env.local` when needed.
 - Python 3.13+ and Node 20.9+ are required.
 - GitHub MCP is not required; `gh` CLI is sufficient for PR inspection.
