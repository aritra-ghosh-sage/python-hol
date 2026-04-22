---
description: "Workspace instructions for Hybrid RAG full-stack project (Python backend + Next.js frontend)"
applyTo: ["**/*.py", "**/*.ts", "**/*.tsx"]
---

# Python HOL - Hybrid RAG Full-Stack Project

A production-ready full-stack application combining a **Python-based Hybrid RAG library** with a **Next.js 16 frontend**. This document guides AI assistants on project structure, conventions, and development practices.

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
│   ├── public/                      # Static assets
│   ├── AGENTS.md                    # Next.js 16 breaking changes guide
│   ├── CLAUDE.md                    # Claude-specific guidance
│   ├── SETUP.md                     # Frontend setup guide
│   └── [config files]               # TypeScript, Tailwind, ESLint
├── docs/                            # Documentation
│   ├── API_INTEGRATION.md           # API integration guide
│   ├── LIBRARY_DESIGN.md            # Hybrid RAG architecture docs
│   └── QUICK_START.md               # Getting started guide
├── implementation_docs/             # Implementation details
├── ai_support_kb/                   # Chroma vector database (dev)
├── tests/                           # Python test suite
├── api.py                           # FastAPI REST wrapper
├── main_example.py                  # Standalone library example
├── hybrid_rag_flow.py               # Simplified usage demo
├── jupyter-playground.ipynb         # Interactive Jupyter notebook
├── pyproject.toml                   # Python project configuration
└── README.md                        # Project overview
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

**Frontend Runtime**
- Real-time WebSocket connections available for chat
- See `src/lib/ws.ts` for WebSocket utilities
- Static assets are served through standard Next.js handling

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
- `chromadb>=1.5.7` (vector database)
- `sentence-transformers>=5.3.0` (local embeddings)
- `fastapi>=0.135.3`, `uvicorn>=0.44.0` (REST API)
- `pydantic>=2.12.5` (data validation)
- `langchain>=1.2.15` (text splitting & utilities)
- `langchain-chroma>=1.1.0`, `langchain-community>=0.4.1`, `langchain-huggingface>=1.2.1` (LangChain integrations)
- `langgraph>=1.1.6` (agentic orchestration)
- `deepagents>=0.5.1` (deep agent framework)
- `boto3>=1.42.86` (AWS integration)
- `pypdf>=4.0.0` (PDF processing)
- `python-dotenv>=1.0.0` (environment management)

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
- `next@16.2.3` (with breaking changes)
- `react@19.2.4`, `react-dom@19.2.4`
- `typescript@5.9.3`
- `tailwindcss@4.2.2` (with @tailwindcss/postcss@4.2.2)
- `@tailwindcss/typography@0.5.19` (typography plugin)
- `zustand@5.0.12` (state management)
- `zod@4.3.6` (schema validation)
- `lucide-react@1.8.0` (icons)

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

**Solution:** 
- Read [frontend/AGENTS.md](./frontend/AGENTS.md) for breaking changes documentation
- Check `node_modules/next/dist/docs/` for current API patterns
- Heed all deprecation notices before writing code

### 3. Frontend Runtime Notes
**Note:** The frontend uses standard Next.js runtime behavior with no offline-install subsystem enabled. Do not add that subsystem back unless explicitly scoped.

### 4. AI Agent Infrastructure
**Note:** Project includes custom AI agents in `.github/agents/` for development assistance. See `.github/agents/` for available agents and `.github/skills/` for reusable skill modules.

## 📚 Documentation Links

**Backend & Library**
- [LIBRARY_DESIGN.md](./docs/LIBRARY_DESIGN.md) - Architecture and module descriptions
- [API_INTEGRATION.md](./docs/API_INTEGRATION.md) - REST API integration guide
- [QUICK_START.md](./docs/QUICK_START.md) - Fast-track usage examples
- [README.md](./README.md) - Project overview and refactoring summary

**Frontend**
- [frontend/AGENTS.md](./frontend/AGENTS.md) - Next.js 16 breaking changes guide
- [frontend/CLAUDE.md](./frontend/CLAUDE.md) - Claude-specific development notes
- [frontend/SETUP.md](./frontend/SETUP.md) - Frontend setup and configuration
- [frontend/README.md](./frontend/README.md) - Frontend project details

**Implementation & Reference**
- [implementation_docs/](./implementation_docs/) - Detailed implementation guides
- [.github/agents/](./github/agents/) - Custom AI agents for development
- [.github/instructions/](./github/instructions/) - Development guidelines and standards

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
- **explore-hybrid-rag.agent.md** - Understand library architecture and design patterns
- **gem-planner.agent.md** - DAG-based task planning and decomposition
- **gem-implementer.agent.md** - TDD-focused code implementation
- **gem-critic.agent.md** - Challenge assumptions and find edge cases
- **gem-reviewer.agent.md** - Security auditing and OWASP compliance
- **principal-software-engineer.agent.md** - Principal-level guidance
- **qa-subagent.agent.md** - Meticulous QA and edge-case analysis
- **adr-generator.agent.md** - Create Architecture Decision Records
- **se-system-architecture-reviewer.agent.md** - Architecture review & design validation

See `.github/agents/` for full agent specifications.

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
- [ ] Taiga tasks linked in comments
- [ ] Accessibility attributes present (alt, aria-labels)

## 📝 Notes for Contributors

- **Python version:** 3.13+ required
- **Node version:** 18+ recommended (for Next.js 16)
- **Package manager preference:** uv (Python), pnpm (Node)
- **Type checking:** `mypy` for Python, TypeScript for frontend
- **Testing:** pytest for Python backend, Playwright for e2e tests
- **Documentation:** Always include examples in docstrings
- **Version:** Project v0.1.0 (see `pyproject.toml` and `frontend/package.json`)
- **Environment:** Copy `.env.local.example` to `.env.local` and configure (frontend)
- **Jupyter Support:** Interactive notebook available at `jupyter-playground.ipynb`
- **Custom Agents:** Use agents in `.github/agents/` for AI-assisted development
