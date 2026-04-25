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

Public API (17 exports) is defined in `__init__.py` with `__all__`. Configuration uses validated dataclasses (`config.py` with `__post_init__` validation, defaults from `constants.py`). See `main_example.py` and `hybrid_rag_flow.py` for library usage patterns.

### Caching (`cache.py`)

Three-layer design:
- **L1** — Full query response cache (shared retrieval layer in `api.py`); backend switchable via `CACHE_BACKEND=memory|redis`
- **L2** — LRU embedding cache inside `HybridRetriever` (session-scoped)
- **L3** — ChromaDB persistent vector storage

Cache failures are fail-open. Monitor at `GET /cache/stats`. Configure via `CACHE_BACKEND`, `REDIS_URL`, `CACHE_TTL_SECONDS`.

Cache invalidation is tied to corpus version (`_corpus_version` in `api.py`) — incrementing it busts the L1 cache. When adding new cache event types, register them in `CACHE_TELEMETRY_LABELS` in `constants.py`.

### API Layer (`api.py`)

FastAPI app (~1600 lines) with:
- `WS /ws/chat` — real-time streaming chat (primary retrieval path)
- `GET /cache/stats` — cache observability
- `GET /health` — health check
- Configuration management endpoints
- CORS middleware enabled

### Frontend (`frontend/`)

Next.js 16.2.3 (App Router) + React 19 + Zustand + Tailwind v4. Components are feature-organized under `src/components/{chat,data,layout,settings,ui}/`. WebSocket client lives in `src/lib/ws.ts`. State management via Zustand stores in `src/stores/`.

**Next.js 16 has breaking changes from 13/14.** Before writing frontend code, check `frontend/AGENTS.md` for documented breaking changes and check current API patterns in `node_modules/next/dist/docs/`.

## Testing

Integration tests use `fastapi.testclient.TestClient` with fixtures from `tests/conftest.py`:
- `setup_test_environment` (session scope) — sets env vars
- `initialized_app` (function scope) — fresh retriever + cache per test
- `client_with_fresh_cache` — cleared-cache variant

Always check collection health before retrieval in integration tests. Mock Redis/external deps where needed; async tests work without decorators due to `asyncio_mode = "auto"`.

## Agent Infrastructure

Custom AI development agents live in `.github/agents/` (planner, orchestrator, implementer, debugger, reviewer, designer, researcher). The catalog and usage guidance is in `.github/AGENTS.md`. For complex multi-step tasks, consult that file before starting.

## Key Conventions

### Python Coding Standards

#### Code Quality & Formatting
- **RUFF**: Project uses RUFF for code formatting and linting. Run `ruff check .` before committing.
- **Line Length**: Maximum 88 characters (Black-compatible)
- **Imports**: Organize in three groups (standard library, third-party, local) separated by blank lines
  ```python
  # Standard library
  import logging
  from typing import Any, Dict, List, Optional

  # Third-party
  import numpy as np
  from fastapi import FastAPI

  # Local
  from hybrid_rag.config import HybridRetrieverConfig
  from .exceptions import RetrievalError
  ```

#### Type Hints
- **Required on ALL functions**: Parameters, return types, and class attributes
- **Use modern syntax**: `list[str]`, `dict[str, Any]` (not `List[str]`, `Dict[str, Any]`)
- **Optional types**: Use `Optional[T]` or `T | None` for nullable values
- **TYPE_CHECKING**: Use for circular imports
- **py.typed marker**: Library includes `py.typed` marker for PEP 561 compliance
  ```python
  from __future__ import annotations
  from typing import TYPE_CHECKING, Optional

  if TYPE_CHECKING:
      from .cache import CacheBackend

  def process_data(data: list[str], cache: Optional[CacheBackend] = None) -> dict[str, Any]:
      ...
  ```

#### Naming Conventions
- **Functions**: `snake_case` — descriptive verb phrases (`retrieve_documents`, `validate_config`, `create_cache_backend`)
- **Classes**: `PascalCase` — nouns (`HybridRetriever`, `CacheBackend`, `DocumentResult`)
- **Constants**: `UPPER_SNAKE_CASE` — descriptive names (`DEFAULT_CONFIG`, `STOP_WORDS`, `MIN_RELEVANCE_SCORE`)
- **Private members**: Single underscore prefix (`_retriever`, `_cache_generation`, `_embedding_cache`)
- **Module exports**: Define `__all__` list at top of module for public API
- **Test names**: `test_<action>_<expected_outcome>` (e.g., `test_cache_returns_none_for_missing_key`)

#### Docstrings (Google Style)
Required on all public functions, classes, and modules:

```python
def retrieve_documents(
    query: str,
    config: HybridRetrieverConfig,
    enable_cache: bool = True
) -> list[dict[str, Any]]:
    """Retrieve relevant documents using hybrid search.

    Combines semantic and keyword search with optional cross-encoder reranking
    to find the most relevant documents for the given query.

    Args:
        query: Search query string from the user.
        config: Configuration parameters controlling retrieval behavior.
        enable_cache: Whether to use cached results. Defaults to True.

    Returns:
        List of document dictionaries, each containing:
            - id (str): Document identifier
            - text (str): Document content
            - score (float): Relevance score (0-1)
            - source (str): Document source label

    Raises:
        RetrievalError: If retrieval fails due to database or model errors.
        ValueError: If query is empty or config is invalid.

    Example:
        >>> config = HybridRetrieverConfig(semantic_weight=0.7)
        >>> results = retrieve_documents("How do I reset password?", config)
        >>> for doc in results:
        ...     print(f"Score: {doc['score']:.3f} - {doc['text'][:50]}")
    """
```

#### Error Handling
- **Use custom exceptions**: Import from `hybrid_rag.exceptions` — never bare `Exception`
- **Exception hierarchy**: All inherit from `HybridRAGException`
  - `RetrieverNotInitializedError`: Retriever accessed before initialization
  - `RetrievalError`: Document retrieval failures
  - `VectorDBError`: Vector database operation failures
- **Logging**: Module-level loggers only — `logger = logging.getLogger(__name__)`, NO `print()`
- **Fail-open caching**: Cache failures should never break requests

#### Configuration & Validation
- **Dataclasses**: Use `@dataclass` for configuration models
- **Validation**: Implement `__post_init__` for parameter validation (all config validated in `__post_init__`)
- **Defaults**: Centralize in `constants.py`, reference in config classes (defaults centralized in `constants.py`)
- **Immutability**: Use `replace()` for config updates (returns new instance)
  ```python
  @dataclass
  class HybridRetrieverConfig:
      semantic_weight: float = 0.65
      keyword_weight: float = 0.35

      def __post_init__(self) -> None:
          weight_sum = self.semantic_weight + self.keyword_weight
          if not (0.99 <= weight_sum <= 1.01):
              raise ValueError(f"Weights must sum to 1.0, got {weight_sum}")
  ```

#### Testing Standards
- **Test Coverage**: Minimum **80%** overall coverage (check with `pytest --cov`)
- **Test Pass Rate**: Minimum **85%** tests must pass before check-in
- **Test Organization**:
  - One test class per module/class being tested
  - Descriptive test names: `test_<method>_<condition>_<expected_outcome>`
  - Use fixtures from `tests/conftest.py` for setup
- **Async Tests**: No decorators needed — `asyncio_mode = "auto"` in `pyproject.toml`
- **Test Structure**:
  ```python
  class TestHybridRetriever:
      """Test the HybridRetriever class."""

      def test_retrieve_returns_results_for_valid_query(self, initialized_app):
          """retrieve() returns non-empty results for valid queries."""
          results = retriever.retrieve("test query")
          assert len(results) > 0
          assert all("score" in r for r in results)
  ```

#### File Organization
- **Module structure**: One class per file (exceptions: small related classes)
- **Public API**: Define in `__init__.py` with `__all__` list
- **Constants**: Centralize in `constants.py`
- **Config**: All configuration in `config.py`
- **Tests**: Mirror source structure in `tests/` directory

#### Common Patterns
- **Context managers**: Use for resource management (files, connections)
- **LRU Cache**: Use `cachetools.LRUCache` for in-memory caching
- **Type guards**: Validate inputs at public API boundaries
- **Logging levels**: DEBUG for detailed traces, INFO for significant events, WARNING for issues, ERROR for failures
- **Async/await**: Use for I/O operations (database, network, file operations)

### TypeScript/Frontend
- No implicit `any` types
- Zod validation at API boundaries
- No component-local state for server data — use Zustand stores
- Accessibility attributes required (`alt`, `aria-label`, etc.)

## Git Workflow

### Branch Naming Convention
```
<type>/<descriptive-name>

Types:
  feature/   - New features or enhancements
  epic/      - Large multi-feature initiatives
  bugfix/    - Bug fixes
  hotfix/    - Critical production fixes (branch from main)
  patch/     - Small fixes or improvements
  docs/      - Documentation updates
  refactor/  - Code refactoring
  test/      - Test additions or updates

Examples:
  feature/add-redis-caching
  epic/multi-agent-retrieval
  bugfix/fix-embedding-cache-key
  hotfix/critical-memory-leak
  patch/update-dependencies
  docs/update-api-documentation
```

### Commit Message Convention
```
<type>(<scope>): <subject>

<body>

<footer>

Types:
  feat     - New feature
  fix      - Bug fix
  docs     - Documentation changes
  style    - Code style/formatting (no logic change)
  refactor - Code refactoring
  test     - Test additions/changes
  chore    - Build/tooling changes
  perf     - Performance improvements

Examples:
  feat(cache): add Redis backend support with TLS
  fix(retriever): correct embedding cache key generation
  docs(readme): update installation instructions
  test(cache): add integration tests for Redis failover
  refactor(api): extract WebSocket handler to separate module
  perf(embedding): optimize batch embedding computation

Breaking Changes:
  feat(config)!: change cache TTL parameter name

  BREAKING CHANGE: Renamed CacheSettings.ttl to ttl_seconds
  Migration: Update all CacheSettings(ttl=...) to CacheSettings(ttl_seconds=...)
```

## Pre-Commit Checklist
- [ ] All tests pass (`pytest tests/ -v`)
- [ ] Test coverage ≥80% (`pytest --cov=hybrid_rag --cov=api`)
- [ ] Test pass rate ≥85%
- [ ] RUFF checks pass (`ruff check .`)
- [ ] Type hints on all new functions
- [ ] Google-style docstrings on public functions
- [ ] No `print()` statements (use `logger`)
- [ ] Custom exceptions (no bare `Exception`)
- [ ] Updated `__all__` if adding public APIs

## Environment

Copy `.env.local.example` to `.env.local`. Python 3.13+ and Node 20.9+ required.
