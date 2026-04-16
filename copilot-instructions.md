---
description: "Workspace instructions for Hybrid RAG full-stack project (Python backend + Next.js frontend)"
applyTo: ["**/*.py", "**/*.ts", "**/*.tsx"]
---

# Python HOL - Hybrid RAG Full-Stack Project

A production-ready full-stack application combining a **Python-based Hybrid RAG library** with a **Next.js 16 frontend**. This document guides AI assistants on project structure, conventions, and development practices.

## 🏗️ Project Architecture

```
python-hol/                          # Monorepo root
├── hybrid_rag/                      # Core production library (Python)
│   ├── __init__.py                  # Public API exports
│   ├── config.py                    # Configuration with validation
│   ├── constants.py                 # Centralized constants
│   ├── exceptions.py                # Custom exception hierarchy
│   ├── reranker.py                  # Cross-encoder reranking
│   ├── retriever.py                 # Core hybrid retrieval engine
│   ├── vectordb.py                  # Vector DB utilities
│   └── py.typed                     # PEP 561 type marker
├── frontend/                        # Next.js 16 web application
│   ├── src/app/                     # App router pages
│   ├── src/components/              # Feature-based components
│   ├── src/hooks/                   # Custom React hooks
│   ├── src/lib/                     # Utilities & API integrations
│   ├── public/                      # Static assets & service worker
│   └── [config files]               # TypeScript, Tailwind, ESLint
├── api.py                           # FastAPI REST wrapper
├── main_example.py                  # Standalone library example
├── hybrid_rag_flow.py               # Simplified usage demo
├── pyproject.toml                   # Python project configuration
├── LIBRARY_DESIGN.md                # Hybrid RAG architecture docs
└── QUICK_START.md                   # Getting started guide
```

## 🔑 Key Conventions & Patterns

### Backend (Python - `hybrid_rag/`, `api.py`)

**Module Organization**
- Each module has a single, well-defined responsibility
- Public API exported through `__init__.py` with `__all__`
- Separation of core logic from API layer

**Type Safety (100% coverage - emphasis)**
- Comprehensive type hints on all functions and variables
- Generic types and Union types properly annotated
- Pydantic models for request/response validation
- `py.typed` marker enables IDE support
- **Always provide type hints when working on Python code**

**Error Handling (Custom Exception Hierarchy)**
```python
from hybrid_rag import (
    HybridRAGException,           # Base class
    RetrieverNotInitializedError, # Not ready
    RetrievalError,               # Retrieval failed
    VectorDBError,                # DB operation failed
)
```
- Catch specific exceptions, not base `Exception`
- Provide meaningful error context in messages

**Logging (Not Print Statements)**
```python
import logging
logger = logging.getLogger(__name__)
logger.info("Operation started")
logger.warning("Deprecated parameter used")
logger.error("Retrieval failed", exc_info=True)
```
- Use module-level loggers: `logging.getLogger(__name__)`
- Log levels: DEBUG (dev info), INFO (events), WARNING (issues), ERROR (failures)
- Never use print() for operational output

**Documentation (Google Style)**
```python
def retrieve(self, query: str, top_k: int = 5) -> List[Dict]:
    """Retrieve documents using hybrid search.
    
    Args:
        query: Search query string
        top_k: Number of results to return (default: 5)
        
    Returns:
        List of documents with scores, sorted by relevance
        
    Raises:
        RetrievalError: If retrieval operation fails
        
    Example:
        >>> results = retriever.retrieve("What is RAG?", top_k=3)
        >>> for result in results:
        ...     print(f"Score: {result['score']:.2f}")
    """
```
- Comprehensive docstrings on all public functions
- Include Args, Returns, Raises, and Examples sections
- Type hints serve as inline documentation

**Configuration Management**
```python
from dataclasses import dataclass, field

@dataclass
class HybridRetrieverConfig:
    semantic_weight: float = 0.7
    keyword_weight: float = 0.3
    
    def __post_init__(self):
        # Validation happens here
        total = self.semantic_weight + self.keyword_weight
        if not (0.99 <= total <= 1.01):  # Float tolerance
            raise ValueError(f"Weights must sum to 1.0, got {total}")
```
- Use dataclasses with `__post_init__` validation
- Centralize defaults in `constants.py`
- Keep configuration type-safe

### Frontend (Next.js 16 - `frontend/`)

**⚠️ CRITICAL: Next.js 16.2.3 Has Breaking Changes**
- This is NOT standard Next.js—many APIs and conventions differ
- **Before writing any code, check the Next.js 16 documentation**
- Read relevant guides in `node_modules/next/dist/docs/`
- Look for deprecation notices: patterns may have changed

**Component Organization (Feature-Based)**
```
components/
├── chat/              # Chat UI components
│   ├── ChatInput.tsx
│   ├── ChatWindow.tsx
│   └── MessageBubble.tsx
├── data/              # Data management components
├── layout/            # Page structure
├── settings/          # Configuration UI
└── ui/                # Reusable UI elements
```
- Components organized by feature, not by type
- Each component file has single responsibility
- Use `<PascalCase>` for component files

**State Management (Zustand)**
- Store queries in Zustand stores, not component state
- Keep stores focused and composable
- Type stores with TypeScript interfaces

**Styling (Tailwind v4)**
- Use Tailwind utility classes
- Custom CSS via `globals.css`
- Typography plugin available: `@tailwindcss/typography`

**API Integration (type-safe)**
```typescript
// src/lib/types.ts - Define all API contracts
export interface Message {
  id: string;
  content: string;
  role: "user" | "assistant";
}

// src/hooks/useApi.ts - Typed API calls
const response = await api.post<APIResponse>("/retrieve", query);
```
- Keep types in dedicated files
- Use TypeScript generics for API responses
- Validate responses at API boundary

**WebSocket Support**
- Service worker enables offline capability
- WebSocket connections available for real-time chat
- See `src/lib/ws.ts` for connection utilities

## ⚙️ Build & Development Commands

### Backend (Python)

```bash
# Activate virtual environment
source .venv/bin/activate

# Install dependencies (recommended: use uv)
uv pip install -r requirements.txt
# or
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Run the FastAPI server
uvicorn api:app --reload

# Run library example
python main_example.py
```

**Key Dependencies:**
- `chromadb` (vector database)
- `sentence-transformers` (local embeddings)
- `fastapi`, `uvicorn` (REST API)
- `pydantic` (data validation)
- `langchain` (text splitting & utilities)

### Frontend (Next.js)

```bash
cd frontend

# Install dependencies (pnpm recommended)
pnpm install

# Development mode (auto-reload)
pnpm dev              # Runs on http://localhost:3000

# Production build
pnpm build
pnpm start

# Type checking
pnpm tsc --noEmit

# Linting
pnpm lint
```

**Key Dependencies:**
- `next` 16.2.3 (with breaking changes)
- `react` 19.2.4
- `typescript` 5.9.3
- `tailwindcss` 4.2.2 (with PostCSS 4)
- `zustand` (state management)
- `zod` (schema validation)

## ⚠️ Known Issues & Workarounds

### 1. ChromaDB HuggingFace Embeddings Error
**Issue:** `ValueError: could not convert string to float: 'error'` from `HuggingFaceEmbeddingFunction`

**Cause:** Intermittent API errors returned as JSON instead of embeddings

**Solution:** Use local sentence-transformer embeddings (already configured in codebase)
```python
from chromadb.utils import embedding_functions
ef = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="all-MiniLM-L6-v2"  # Local inference, no API calls
)
```

### 2. Next.js 16 Breaking Changes
**Issue:** Code patterns from Next.js 13/14 may not work

**Solution:** Check `node_modules/next/dist/docs/` for current API patterns before making changes

### 3. Service Worker Caching
**Note:** Frontend has PWA support with offline capability. Be mindful of cache invalidation when updating APIs.

## 📚 Documentation Links

- **Backend Design:** [LIBRARY_DESIGN.md](./LIBRARY_DESIGN.md) - Architecture and module descriptions
- **Quick Start:** [QUICK_START.md](./QUICK_START.md) - Fast-track usage examples
- **Main Readme:** [README.md](./README.md) - Project overview and refactoring summary
- **Frontend Setup:** [frontend/SETUP.md](./frontend/SETUP.md) - Next.js 16 specific notes
- **Frontend AGENTS.md:** [frontend/AGENTS.md](./frontend/AGENTS.md) - Next.js warnings and breaking changes

## 🎯 Common Tasks

### Adding a New Hybrid RAG Feature
1. Create module in `hybrid_rag/` with single responsibility
2. Add comprehensive type hints and docstrings
3. Define custom exceptions if needed
4. Add module-level logger
5. Export from `__init__.py` in `__all__`
6. Add example usage to docstring
7. Update `LIBRARY_DESIGN.md` with module description

### Adding an API Endpoint
1. Define Pydantic models for request/response in `api.py`
2. Use custom exceptions from `hybrid_rag.exceptions`
3. Set appropriate status codes and error responses
4. Add logging at key points
5. Document endpoint behavior in endpoint docstring

### Adding a Frontend Component
1. Create in appropriate feature folder under `components/`
2. Use TypeScript with explicit types (no implicit `any`)
3. Import icons from `lucide-react`
4. Style with Tailwind utilities
5. Export from component's index if in a subfolder
6. Integrate state via Zustand if needed

### Debugging
- **Python:** Enable DEBUG logging: `logging.basicConfig(level=logging.DEBUG)`
- **Frontend:** Check browser console and Network tab for API calls
- **API Connection:** Verify FastAPI running and CORS configured in `api.py`

## 🔐 Code Review Checklist

**Python:**
- [ ] 100% type hints present
- [ ] Custom exceptions used appropriately
- [ ] Logging instead of print()
- [ ] Docstrings follow Google style
- [ ] Configuration validated in `__post_init__`
- [ ] Error context is meaningful

**TypeScript/Frontend:**
- [ ] No implicit `any` types
- [ ] API responses validated with Zod
- [ ] Component logic extracted to hooks
- [ ] Taiga tasks linked in comments
- [ ] Accessibility attributes present (alt, aria-labels)

## 📝 Notes for Contributors

- **Python version:** 3.13+ required
- **Package manager preference:** uv (Python), pnpm (Node)
- **Type checking:** `mypy` for Python, TypeScript for frontend
- **Testing:** pytest for Python backend
- **Documentation:** Always include examples in docstrings
- **Version:** Project v0.1.0 (see `pyproject.toml` and `frontend/package.json`)
