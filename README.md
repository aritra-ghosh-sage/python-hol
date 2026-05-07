# Python HOL

Python HOL is a hybrid retrieval platform with three shipped surfaces:

- `hybrid_rag/`: reusable Python library
- `api.py`: FastAPI backend
- `frontend/`: Next.js 16 web app

It combines semantic search, keyword search, optional cross-encoder reranking, layered caching, and source-aware ingestion. Eliminates the need to use a LLM for inference. Keeps data safe and local, eliminates LLM costs.
Use ChromaDB as the local vector store. Can be replaced with a managed one, e.g. ChromaDB managed, Pinecone managed.

## Repository Layout

```text
hybrid_rag/   core retrieval library
routers/      FastAPI route modules
frontend/     Next.js UI
examples/     runnable library examples
docs/         operator and product docs
tests/        backend test suite
```

## Core Capabilities

- Hybrid retrieval with semantic + keyword fusion
- Optional reranking via `cross-encoder/ms-marco-MiniLM-L-6-v2`
- ChromaDB persistence and collection management
- Text, URL, and file ingestion
- L1 response caching and L2 embedding caching
- WebSocket query workflow for the UI

## Requirements

- Python 3.13+
- Node 20.9+
- `uv`
- `pnpm`

## Quick Start

### 1. Install

```bash
uv sync
cd frontend && pnpm install
```

### 2. Start the backend

```bash
source .venv/bin/activate
uvicorn api:app --reload
```

### 3. Start the frontend

```bash
cd frontend
pnpm dev
```

### 4. Try the examples

```bash
python examples/main_example.py
python examples/hybrid_rag_flow.py
```

### 5. Manage ChromaDB collections

```bash
uv run rag-collections -h
```

`status` reports document counts and whether a collection looks corrupted based on
its persisted SQLite metadata and vector-segment files inside `knowledge_db/`.
`backup` archives the active configured Chroma persistence state into `backup/`
using the format `mm_dd_yy_HH_MM_SS.bak`.

## MCP Server (optional)

The repository includes an MCP server entrypoint at `mcp_server.py` that exposes the hybrid RAG tools over an MCP transport. It supports these environment variables:

- `MCP_HOST` — host address for the MCP HTTP transport (default: `127.0.0.1`).
- `MCP_PORT` — port the MCP server listens on (default: `8000`).
- `MCP_TRANSPORT` — transport mode: `stdio` (default) or `streamable-http` / `http`.

```bash
export MCP_TRANSPORT=streamable-http 
export MCP_PORT=8001 
export MCP_HOST=localhost

uv run python mcp_server.py
```

When `MCP_TRANSPORT=stdio` the server uses stdio for tool requests and responses.

## Backend Surface

HTTP routes:

- `GET /`
- `GET /health`
- `GET /config`
- `PUT /config`
- `POST /documents`
- `GET /documents/sources`
- `GET /collections`
- `GET /cache/stats`

Query route:

- `WS /ws/chat`

Docs:

- Swagger: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Frontend Defaults

- App: `http://localhost:3000`
- API env: `NEXT_PUBLIC_API_URL`
- WebSocket env: `NEXT_PUBLIC_WS_URL`

If unset, the frontend defaults to:

- `http://localhost:8000`
- `ws://localhost:8000/ws/chat`

## Library Example

```python
from hybrid_rag import (
    HybridRetriever,
    HybridRetrieverConfig,
    get_sample_documents,
    initialize_vector_db,
)

collection = initialize_vector_db(get_sample_documents())
retriever = HybridRetriever(collection, HybridRetrieverConfig())
results = retriever.retrieve("How do I use offline maps?")
```

## Caching

The platform uses three layers:

- L1: shared query-response cache
- L2: embedding LRU cache inside the retriever
- L3: persistent ChromaDB storage

Useful env vars:

```bash
CACHE_BACKEND=memory
CACHE_TTL_SECONDS=3600
CACHE_MAX_SIZE=10000

CACHE_BACKEND=redis
REDIS_URL=redis://localhost:6379
CACHE_KEY_PREFIX=hybrid_rag_cache:
```

Check cache state:

```bash
curl http://localhost:8000/cache/stats
```

## Development Commands

Backend:

```bash
uv run ruff check .
uv run pytest tests/ -v
mypy hybrid_rag/ api.py api_models.py routers/
```

Frontend:

```bash
cd frontend
pnpm lint
pnpm test:unit
pnpm build
```

## Documentation

- `docs/QUICK_START.md`
- `docs/HTTP_ENDPOINT_ALLOWLIST.md`
- `docs/PRODUCT_PRD.md`
- `CLAUDE.md`
