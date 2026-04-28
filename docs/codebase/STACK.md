# Stack

> **Evidence**: `pyproject.toml`, `frontend/package.json`, `frontend/tsconfig.json`, `hybrid_rag/retriever.py`, `hybrid_rag/reranker.py`, `hybrid_rag/vectordb.py`, `hybrid_rag/cache.py`

## Python Runtime

- **Version**: 3.13+ (enforced by `pyproject.toml` `requires-python = ">=3.13"`)
- **Package manager**: `uv` (lock file `uv.lock`; `uv sync` installs all deps)
- **Virtual environment**: `.venv/` (managed by uv)

## Backend Production Dependencies

| Package | Version constraint | Role |
|---|---|---|
| `fastapi` | >=0.135.3 | HTTP/WebSocket API framework |
| `uvicorn` | >=0.44.0 | ASGI server |
| `pydantic` | >=2.12.5 | Request/response validation, Pydantic v2 |
| `chromadb` | >=1.5.7 | Vector database (persistent, local) |
| `sentence-transformers` | >=5.3.0 | Embedding model (`all-MiniLM-L6-v2`) and cross-encoder (`cross-encoder/ms-marco-MiniLM-L-6-v2`) |
| `langchain-text-splitters` | >=1.1.1 | `RecursiveCharacterTextSplitter` for chunking |
| `langchain` / `langchain-*` | various >=1.x | LangChain ecosystem (core, chroma, huggingface, openai, community) |
| `langgraph` | >=1.1.6 | Graph-based agent workflows (present, not yet exercised in main pipeline) |
| `numpy` | >=2.4.4 | Embedding array arithmetic |
| `cachetools` | >=5.3.0 | `TTLCache` (L1 in-memory) and `LRUCache` (L2 embedding) |
| `redis` | >=5.0.0 | Optional distributed cache backend |
| `requests` | >=2.33.1 | HTTP fetching for URL-based document ingestion |
| `pypdf` | >=4.0.0 | PDF text extraction (optional at runtime; import guarded in `api.py`) |
| `python-dotenv` | >=1.0.0 | `.env` loading |
| `huggingface-hub` | >=1.9.2 | Model download from HuggingFace |
| `boto3` | >=1.42.86 | AWS SDK (present in deps; not used in core pipeline) |
| `deepagents` | >=0.5.1 | [TODO: usage not found in core pipeline] |
| `ipykernel`, `ipywidgets` | >=7.x/8.x | Jupyter notebook support |

## Backend Dev Dependencies

| Package | Role |
|---|---|
| `pytest` >=9.0.3 | Test runner |
| `pytest-asyncio` >=0.24.0 | Async test support (`asyncio_mode = "auto"`) |
| `pytest-cov` >=7.1.0 | Coverage reporting |
| `ruff` >=0.15.12 | Linter and formatter |
| `websockets` >=13.0 | WebSocket testing utilities |
| `ipykernel` | (also in dev group, Jupyter) |

## Frontend Runtime

- **Framework**: Next.js 16.2.3 (App Router)
- **Language**: TypeScript 5.9.3 (`strict: true`)
- **React**: 19.2.4
- **Node requirement**: 20.9+ (per CLAUDE.md)
- **Package manager**: `pnpm` (lock file `pnpm-lock.yaml`)

## Frontend Production Dependencies

| Package | Version | Role |
|---|---|---|
| `next` | 16.2.3 | React framework with App Router |
| `react` / `react-dom` | 19.2.4 | UI library |
| `zustand` | ^5.0.12 | Client-side state management |
| `zod` | ^4.3.6 | Runtime schema validation at API boundaries |
| `lucide-react` | ^1.11.0 | Icon library |
| `@tailwindcss/typography` | ^0.5.19 | Prose typography styles |

## Frontend Dev Dependencies

| Package | Role |
|---|---|
| `tailwindcss` ^4.2.4 | Utility-first CSS |
| `vitest` ^3.2.4 | Unit test runner |
| `@testing-library/react` ^16.3.2 | Component testing utilities |
| `@playwright/test` ^1.59.1 | E2E testing (browser automation) |
| `eslint` ^9.39.4 + `eslint-config-next` | Linting |
| `typescript` ^5.9.3 | Type checking |
| `jsdom` ^26.1.0 | DOM simulation for Vitest |

## Key Framework Notes

- **Next.js 16 has breaking changes** from 13/14; consult `frontend/AGENTS.md` and `node_modules/next/dist/docs/` before writing frontend code.
- **Pydantic v2** is in use; v1 migration patterns (`.dict()`) are invalid.
- `asyncio_mode = "auto"` in `pyproject.toml` means no `@pytest.mark.asyncio` needed on test functions.
- Ruff excludes `jupyter-playground.ipynb` (`[tool.ruff] exclude = [...]` in `pyproject.toml`).
