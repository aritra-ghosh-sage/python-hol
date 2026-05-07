# Conventions

> **Evidence**: `CLAUDE.md`, `frontend/AGENTS.md`, `hybrid_rag/retriever.py`, `hybrid_rag/cache.py`, `hybrid_rag/config.py`, `hybrid_rag/exceptions.py`, `api.py`, `frontend/src/lib/ws.ts`, `frontend/src/stores/chatStore.ts`, `frontend/src/lib/types.ts`

## Python Conventions

### Naming

| Element | Convention | Example |
|---|---|---|
| Functions | `snake_case`, verb phrases | `retrieve_documents`, `create_cache_backend` |
| Classes | `PascalCase`, nouns | `HybridRetriever`, `CacheBackend` |
| Constants | `UPPER_SNAKE_CASE` | `DEFAULT_CONFIG`, `STOP_WORDS`, `MIN_SCORE_RETRIEVAL` |
| Private attributes | Single underscore | `_retriever`, `_cache_generation`, `_embedding_cache` |
| Test methods | `test_<action>_<condition>_<expected_outcome>` | `test_cache_returns_none_for_missing_key` |
| Module exports | `__all__` list at top of each module | Verified in every `hybrid_rag/*.py` file |

### Imports

Three groups separated by blank lines: standard library, third-party, local. Relative imports used within `hybrid_rag/`. `TYPE_CHECKING` guard used in `config.py` to break circular import with `cache.py`.

```python
# Standard library
import logging
from typing import Any, Optional

# Third-party
from fastapi import FastAPI

# Local
from hybrid_rag.config import HybridRetrieverConfig
from .exceptions import RetrievalError
```

### Type Hints

- **Required on all functions**: parameters, return types, and class attributes.
- Modern syntax: `list[str]`, `dict[str, Any]` (not `List`/`Dict`).
- `Optional[T]` or `T | None` for nullable values.
- `py.typed` marker in `hybrid_rag/` for PEP 561 compliance.
- Two `# type: ignore[assignment]` annotations exist in `hybrid_rag/config.py` and `hybrid_rag/retriever.py` where type narrowing is impractical.

### Docstrings

Google-style docstrings required on all public functions, classes, and modules. Must include `Args:`, `Returns:`, `Raises:` (where applicable), and `Example:`. Short private helpers may omit the full structure.

### Error Handling

- **Never raise bare `Exception`**; use `ValueError`, `TypeError`, or custom exceptions from `hybrid_rag/exceptions.py`.
- Custom hierarchy: `HybridRAGException` → `RetrieverNotInitializedError`, `RetrievalError`, `VectorDBError`.
- **Broad `except Exception`** is used only at boundary layers (cache backends) where fail-open semantics are intentional — log the error and return a safe default.
- One `assert` in production code: `hybrid_rag/config.py:353` (`assert settings.redis_url is not None`) is post-validation narrowing, not application logic.
- `RetrieverNotInitializedError` is raised (not HTTP 503) when `_retriever` is `None`; the API layer catches it and converts to 503.

### Logging

- Module-level logger only: `logger = logging.getLogger(__name__)`.
- No `print()` statements in library or API code.
- Log levels: DEBUG for detail, INFO for significant events (startup, cache hit/miss), WARNING for recoverable issues (cache failures, stale handles), ERROR for non-recoverable failures.
- Structured telemetry labels use constants from `CACHE_TELEMETRY_LABELS` in `constants.py` — never inline string literals for event names.

### Configuration

- `@dataclass` with `__post_init__` validation for all config objects.
- Immutable updates: `config.update(**kwargs)` returns a new instance via `dataclasses.replace`.
- Defaults centralized in `constants.py`; referenced by `config.py`.
- No global mutable config objects — each config update returns a fresh instance.

### Line Length and Formatting

- Max 88 characters (Black-compatible, Ruff enforced).
- Ruff is the sole formatter/linter: `uv run ruff check .`.
- `jupyter-playground.ipynb` is excluded from ruff.

## Frontend Conventions

### Naming

| Element | Convention | Example |
|---|---|---|
| Components | `PascalCase` nouns | `ChatWindow`, `MessageBubble`, `QueryPanel` |
| Functions/variables | `camelCase` | `sendMessage`, `isConnected` |
| Constants | `UPPER_SNAKE_CASE` | `WS_URL`, `MAX_RETRIES`, `INITIAL_BACKOFF_MS` |
| Types/interfaces | `PascalCase` with suffix | `ChatWindowProps`, `ConnectionState`, `WebSocketConfig` |
| Event handlers | `handle` or `on` prefix | `handleSubmit`, `onMessageReceived` |
| Boolean variables | `is`/`has`/`should` prefix | `isLoading`, `hasError`, `shouldRetry` |

### TypeScript Strictness

- `tsconfig.json` has `"strict": true` — no implicit `any` permitted.
- All exported/public function signatures must be explicitly typed.
- Zod schemas are used for runtime validation at API response boundaries.
- `@/` path alias maps to `src/`.

### Component Structure

1. `"use client"` directive (only for client components)
2. Type definitions (interfaces/types)
3. Component function with destructured props
4. Hooks (`useState`, `useEffect`, custom)
5. Event handlers
6. Effects
7. Return/JSX

Server Components are the default; `"use client"` added only when needed (event handlers, browser APIs, hooks).

### State Management

- **Zustand**: for shared app/client state, persisted or cross-component state.
- **`useState`**: local UI state (toggles, modals).
- `chatStore` uses `zustand/persist` middleware with localStorage, capped at 200 messages.
- `settingsStore` uses plain Zustand with `mergeCollections` (never replaces, only adds).
- Direct imports (e.g. `@/components/layout/Sidebar`) preferred over barrel `index.ts` files.

### Accessibility

Required: `alt` text on images, `aria-label` on icon-only buttons, `htmlFor`/`id` on form pairs, keyboard navigation on interactive elements.

## Git Conventions

### Branch Naming

`<type>/<descriptive-name>` — types: `feature/`, `epic/`, `bugfix/`, `hotfix/`, `patch/`, `docs/`, `refactor/`, `test/`.

### Commit Messages

```
<type>(<scope>): <subject>
```

Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `perf`. Breaking changes: append `!` and add `BREAKING CHANGE:` footer.

## Pre-Commit Checklist

**Python**: `uv run ruff check .` and `pytest tests/ -v` (100% pass, >=80% coverage).
**Frontend**: `pnpm lint` + `pnpm test:unit` + `pnpm build` must all pass.
