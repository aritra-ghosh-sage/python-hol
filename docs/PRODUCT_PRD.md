# Product PRD

Product: Python HOL Hybrid RAG Platform
Version: 1.0
Status: current-state PRD for this repository

## Summary

Python HOL is a hybrid retrieval platform with three surfaces:

- a reusable Python library in `hybrid_rag/`
- a FastAPI backend in `api.py`
- a Next.js frontend in `frontend/`

The system ingests knowledge, chunks and embeds it, retrieves with semantic and keyword search, optionally reranks results, and exposes that workflow through WebSocket and admin HTTP endpoints.

## Problem

Teams need a grounded retrieval layer they can run locally, integrate into Python applications, and operate through a simple UI without stitching together separate tools for ingestion, search, config, and observability.

## Goals

- Provide a reusable Python retrieval engine with stable defaults.
- Support grounded querying with source-aware results.
- Make ingestion and config changes available through an operator-friendly API.
- Keep repeated queries fast with layered caching.

## Non-goals

- General open-ended chatbot behavior.
- Multi-tenant billing or account management.
- Custom model training.
- Replacing upstream document management systems.

## Primary Users

- Developer: embeds the library or API into another app.
- Operator: ingests content and validates retrieval quality.
- Admin: changes config and monitors service health.
- End user: queries the knowledge base through the UI.

## Current Product Scope

### Backend

- `GET /`
- `GET /health`
- `GET /config`
- `PUT /config`
- `POST /documents`
- `GET /documents/sources`
- `GET /collections`
- `GET /cache/stats`
- `WS /ws/chat`

### Library

- Hybrid retrieval with semantic + keyword fusion
- Optional cross-encoder reranking
- ChromaDB persistence
- Config validation via dataclasses
- L2 embedding cache inside the retriever

### Frontend

- Query/chat workflow over WebSocket
- Settings workflow over REST
- Document ingestion workflow over REST
- Zustand-managed browser state

## Functional Requirements

### P0

- Ingest text, URL, and file sources.
- Return ranked retrieval results with source metadata.
- Support semantic and keyword retrieval in one pipeline.
- Allow config reads and updates at runtime.
- Expose a working query experience through `WS /ws/chat`.

### P1

- Expose cache metrics for debugging and tuning.
- Preserve source listings and collection visibility.
- Support Redis-backed L1 caching for shared deployments.
- Keep cache failures fail-open.
- Provide responsive frontend flows for query, data, and settings.

### P2

- Add production auth in front of admin and write routes.
- Add retrieval evaluation and quality dashboards.
- Add deployment runbooks and stronger operational safeguards.

## Success Metrics

- P95 warm-query latency under 2 seconds in the default setup.
- Cache hit rate above 60% on repeated-query workloads.
- 80%+ successful ingestion on supported source types.
- 85%+ judged relevance for top result in curated evaluation sets.
- Zero request failures caused only by cache backend outages.

## Technical Constraints

- Python backend uses ChromaDB and sentence-transformer embeddings.
- Query retrieval path is WebSocket-first, not `POST /retrieve`.
- Cache invalidation uses corpus-version tokens plus generation counters.
- Frontend defaults to `NEXT_PUBLIC_API_URL=http://localhost:8000` and `NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws/chat`.

## Risks

- Retrieval quality can degrade as source volume and heterogeneity grow.
- Source updates can produce stale results without correct invalidation.
- Production security is incomplete until auth is added externally or in-app.

## Out of Scope for This PRD

- Model training and feedback

## Verification

Use these checks when product-surface changes are made:

```bash
uv run ruff check .
uv run pytest tests/ -v
cd frontend && pnpm lint && pnpm test:unit && pnpm build
```
