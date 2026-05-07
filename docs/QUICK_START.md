# Quick Start Guide

## Prerequisites

- Python 3.13+
- Node 20.9+
- `uv`
- `pnpm` for the frontend

## Install

```bash
uv sync
cd frontend && pnpm install
```

## Backend: Run the API

```bash
source .venv/bin/activate
uvicorn api:app --reload
```

Backend defaults:

- API base URL: `http://localhost:8000`
- WebSocket URL: `ws://localhost:8000/ws/chat`
- Swagger UI: `http://localhost:8000/docs`

## Frontend: Run the UI

```bash
cd frontend
pnpm dev
```

## MCP Server (optional)

An optional MCP server is provided at `mcp_server.py` to expose retrieval tools via MCP. Set these env vars to configure it:

- `MCP_HOST` (default `127.0.0.1`)
- `MCP_PORT` (default `8000`)
- `MCP_TRANSPORT` (`stdio` | `streamable-http` — default `stdio`)

Example:

```bash
MCP_TRANSPORT=streamable-http MCP_PORT=8001 python mcp_server.py
```

Frontend defaults:

- App URL: `http://localhost:3000`
- REST API env: `NEXT_PUBLIC_API_URL`
- WebSocket env: `NEXT_PUBLIC_WS_URL`

If no env vars are set, the frontend connects to `http://localhost:8000` and `ws://localhost:8000/ws/chat`.

## Library examples

Runnable demos live in `examples/`:

```bash
python examples/main_example.py
python examples/hybrid_rag_flow.py
```

## API Surface

HTTP routes:

- `GET /`
- `GET /health`
- `GET /config`
- `PUT /config`
- `POST /documents`
- `GET /documents/sources`
- `GET /collections`
- `GET /cache/stats`

- `WS /ws/chat`

Example health check:

```bash
curl http://localhost:8000/health
```

Example WebSocket query with `websocat`:

```bash
echo '{"query":"How do I use offline maps?"}' | websocat ws://localhost:8000/ws/chat
```

## Config Basics

Important `HybridRetrieverConfig` fields:

- `semantic_top_k`
- `keyword_top_k`
- `final_top_k`
- `semantic_weight`
- `keyword_weight`
- `enable_rerank`
- `pre_rerank_top_k`
- `collection_name`

`semantic_weight + keyword_weight` must equal `1.0`.

## Cache Basics

The platform uses layered caching:

- L1: full query-response cache
- L2: embedding LRU cache inside `HybridRetriever`
- L3: persistent ChromaDB storage

Useful env vars:

```bash
CACHE_BACKEND=memory
CACHE_TTL_SECONDS=3600
CACHE_MAX_SIZE=10000

# production-style option
CACHE_BACKEND=redis
REDIS_URL=redis://localhost:6379
CACHE_KEY_PREFIX=hybrid_rag_cache:
```

Check cache stats:

```bash
curl http://localhost:8000/cache/stats
```

## Ingest Content

Example text ingestion:

```bash
curl -X POST http://localhost:8000/documents \
  -H "Content-Type: application/json" \
  -d '{
    "ingest_type": "add",
    "source_type": "text",
    "content": "Your document content here...",
    "source_label": "example_text"
  }'
```

- `ingest_type="add"` preserves the warm cache.
- `ingest_type="update"` clears cached query responses after the write.

## Example Scripts

```bash
python examples/main_example.py
python examples/hybrid_rag_flow.py
```

## Validate Changes

```bash
uv run ruff check .
uv run pytest tests/ -v
cd frontend && pnpm lint && pnpm test:unit && pnpm build
```

## Common Issues

- Model download fails:
  Check network access and rerun after `uv sync`.
- Backend starts but queries fail:
  Confirm the retriever initialized and `GET /health` reports readiness.
- Frontend cannot connect:
  Check `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_WS_URL`.
- Retrieval is slow:
  Disable reranking or lower the top-k values.

## More Docs

- `README.md`
- `docs/HTTP_ENDPOINT_ALLOWLIST.md`
- `docs/PRODUCT_PRD.md`
- `CLAUDE.md`
