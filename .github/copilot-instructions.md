---
description: "Workspace instructions for Hybrid RAG full-stack project (Python backend + Next.js frontend)"
applyTo: ["**/*.py", "**/*.ts", "**/*.tsx"]
---

# Python HOL - Hybrid RAG Full-Stack Project

A full-stack workspace combining a **Python-based Hybrid RAG library** with a **Next.js 16 frontend**. This document guides AI assistants on project structure, conventions, and development practices.

## 🏗️ Project Architecture

```
python-hol/                          # Monorepo root
├── .github/
│   ├── agents/                      # Custom AI agents for development
│   ├── instructions/                # Project-wide guidelines
│   ├── prompts/                     # Prompt templates
│   └── skills/                      # Reusable skill modules
├── hybrid_rag/                      # Core production library (Python)
│   ├── __init__.py                  # Public API exports
│   ├── cache.py                     # Cache backends and interfaces
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
│   ├── src/stores/                  # Zustand stores
│   ├── public/                      # Static assets
│   ├── AGENTS.md                    # Next.js 16 breaking changes guide
│   ├── CLAUDE.md                    # Claude-specific guidance
│   ├── SETUP.md                     # Frontend setup guide
│   └── [config files]               # TypeScript, Tailwind, ESLint
├── docs/                            # Documentation
│   ├── API_INTEGRATION.md           # API integration guide
│   ├── CACHE_DEPLOYMENT.md          # Cache deployment guidance
│   ├── CACHE_PERF_REPORT.md         # Cache performance report
│   ├── LIBRARY_DESIGN.md            # Hybrid RAG architecture docs
│   └── QUICK_START.md               # Getting started guide
├── implementation_docs/             # Implementation details
├── quality/                         # Quality playbook and integration guides
├── ai_support_kb/                   # Chroma vector database (dev)
├── support_kb/                      # Additional support knowledge base data
├── tests/                           # Python test suite
├── api.py                           # FastAPI REST wrapper
├── api_middleware.py                # Query cache middleware
├── main.py                          # Minimal entry script
├── main_example.py                  # Standalone library example
├── hybrid_rag_flow.py               # Simplified usage demo
├── jupyter-playground.ipynb         # Interactive Jupyter notebook
├── pyproject.toml                   # Python project configuration
├── uv.lock                          # uv lock file
└── README.md                        # Project overview
```

## 🔑 Key Conventions & Patterns

### Backend (Python - `hybrid_rag/`, `api.py`)

**Module Organization**
- Each module has a single, well-defined responsibility
- Public API exported through `__init__.py` with `__all__`
- Separation of core logic from API layer

**Type Safety (Strong Emphasis)**
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
- This codebase explicitly treats this version as having breaking changes
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

**Realtime Support**
- Real-time WebSocket connections available for chat
- See `src/lib/ws.ts` for WebSocket utilities

## ⚙️ Build & Development Commands

### Backend (Python)

```bash
# Activate virtual environment
source .venv/bin/activate

# Install dependencies (recommended: use uv lockfile)
uv sync
# Alternative editable install
pip install -e .

# Run tests
pytest tests/ -v

# Run the FastAPI server
uvicorn api:app --reload
# or
python api.py

# Run library example
python main_example.py
```

**Key Dependencies:**
- `chromadb>=1.5.7` (vector database)
- `sentence-transformers>=5.3.0` (local embeddings)
- `fastapi>=0.135.3`, `uvicorn>=0.44.0` (REST API)
- `pydantic>=2.12.5` (data validation)
- `langchain>=1.2.15`, `langchain-core>=1.2.28`, `langchain-text-splitters>=1.1.1` (text processing and orchestration)
- `langchain-chroma>=1.1.0`, `langchain-community>=0.4.1`, `langchain-huggingface>=1.2.1`, `langchain-openai>=1.1.12` (LangChain integrations)
- `langgraph>=1.1.6` (agentic orchestration)
- `deepagents>=0.5.1` (deep agent framework)
- `boto3>=1.42.86` (AWS integration)
- `pypdf>=4.0.0` (PDF processing)
- `python-dotenv>=1.0.0` (environment management)
- `cachetools>=5.3.0`, `redis>=5.0.0` (caching support)
- `requests>=2.33.1` (URL ingestion support)

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

# Unit tests
pnpm test:unit
```

**Key Dependencies:**
- `next@16.2.3` (with breaking changes)
- `react@19.2.4`, `react-dom@19.2.4`
- `typescript@5.9.3`
- `tailwindcss@4.2.3` (with `@tailwindcss/postcss@4.2.3`)
- `@tailwindcss/typography@0.5.19` (typography plugin)
- `zustand@5.0.12` (state management)
- `zod@4.3.6` (schema validation)
- `lucide-react@1.8.0` (icons)

## ⚠️ Known Issues & Workarounds

### 1. Next.js 16 Breaking Changes
**Issue:** Code patterns from Next.js 13/14 may not work

**Solution:** 
- Read [frontend/AGENTS.md](./frontend/AGENTS.md) for breaking changes documentation
- Check `node_modules/next/dist/docs/` for current API patterns
- Heed all deprecation notices before writing code

### 2. Cache Backend Selection
**Issue:** Cache behavior differs between local and distributed setups

**Solution:**
- Default backend is in-memory cache for local development
- For distributed environments, set `CACHE_BACKEND=redis` and `REDIS_URL`
- Use `/cache/stats` for runtime cache observability

### 3. AI Agent Infrastructure
**Note:** Project includes custom AI agents in `.github/agents/` for development assistance. See `.github/agents/` for available agents and `.github/skills/` for reusable skill modules.

## 📚 Documentation Links

**Backend & Library**
- [LIBRARY_DESIGN.md](./docs/LIBRARY_DESIGN.md) - Architecture and module descriptions
- [API_INTEGRATION.md](./docs/API_INTEGRATION.md) - REST API integration guide
- [QUICK_START.md](./docs/QUICK_START.md) - Fast-track usage examples
- [CACHE_DEPLOYMENT.md](./docs/CACHE_DEPLOYMENT.md) - Cache deployment details
- [README.md](./README.md) - Project overview

**Frontend**
- [frontend/AGENTS.md](./frontend/AGENTS.md) - Next.js 16 breaking changes guide
- [frontend/CLAUDE.md](./frontend/CLAUDE.md) - Claude-specific development notes
- [frontend/SETUP.md](./frontend/SETUP.md) - Frontend setup and configuration
- [frontend/README.md](./frontend/README.md) - Frontend project details

**Implementation & Reference**
- [implementation_docs/](./implementation_docs/) - Detailed implementation guides
- [.github/agents/](./.github/agents/) - Custom AI agents for development
- [.github/instructions/](./.github/instructions/) - Development guidelines and standards

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

### Using Custom AI Agents
The project includes custom AI agents in `.github/agents/` for development assistance:
- **planning and orchestration**: `gem-planner.agent.md`, `gem-orchestrator.agent.md`
- **implementation and debugging**: `gem-implementer.agent.md`, `gem-debugger.agent.md`
- **review and quality**: `gem-reviewer.agent.md`, `qa-subagent.agent.md`
- **documentation and architecture**: `gem-documentation-writer.agent.md`, `adr-generator.agent.md`, `arch.agent.md`
- **discovery and research**: `explore-hybrid-rag.agent.md`, `gem-researcher.agent.md`

See `.github/agents/` for the current full list.

### Debugging
- **Python:** Enable DEBUG logging: `logging.basicConfig(level=logging.DEBUG)`
- **Frontend:** Check browser console and Network tab for API calls; use `frontend/AGENTS.md` for Next.js 16 debugging
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
- [ ] Accessibility attributes present (alt, aria-labels)

## 📝 Notes for Contributors

- **Python version:** 3.13+ required
- **Node version:** 20.9+ required by installed Next.js 16.2.3
- **Package manager preference:** uv (Python), pnpm (Node)
- **Type checking:** Type hints for Python modules, TypeScript for frontend
- **Testing:** pytest/pytest-asyncio for Python backend, Vitest and Playwright in frontend tooling
- **Documentation:** Always include examples in docstrings
- **Version:** Project v0.1.0 (see `pyproject.toml` and `frontend/package.json`)
- **Environment:** Use `.env.local.example` as the reference template and configure required variables for your environment
- **Jupyter Support:** Interactive notebook available at `jupyter-playground.ipynb`
- **Custom Agents:** Use agents in `.github/agents/` for AI-assisted development
