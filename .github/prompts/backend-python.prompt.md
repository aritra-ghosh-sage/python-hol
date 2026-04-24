---
description: "Use when: developing Python backend features (hybrid_rag/ library, api.py), implementing new modules, adding API endpoints, or writing production-quality Python code with type safety and proper error handling"
applyTo: ["**/*.py"]
---

# Python Backend Development Guide

You are developing the **Hybrid RAG production library** and FastAPI REST API backend. This prompt enforces best practices for production-quality Python code.

## 🎯 Your Task

When writing or modifying Python code:
1. **Implement** the feature/fix described in the request
2. **Ensure** 100% type hints throughout all code
3. **Follow** the architecture and module patterns defined below
4. **Use** appropriate error handling with custom exceptions
5. **Include** comprehensive docstrings with examples
6. **Apply** logging instead of print statements
7. **Validate** configuration and inputs properly

---

## 📋 Code Quality Standards

### 1. Type Hints (100% Coverage - NO EXCEPTIONS)

**✅ Required:**
```python
from typing import Optional, List, Dict, Union

def retrieve(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    """Retrieve documents."""
    pass

async def process_async(items: List[str]) -> None:
    """Process items asynchronously."""
    pass

config: Optional[HybridRetrieverConfig] = None
```

**❌ Never:**
```python
def retrieve(self, query, top_k=5):  # Missing types
    pass

results = some_function(query)  # No return type
```

**Guidelines:**
- Type hints on function parameters and return values
- Hint on class attributes and module-level variables
- Use `Optional[T]` instead of just `T | None` (for Python 3.10+ compat)
- Use `Any` sparingly—only when truly dynamic
- Use generics: `List[str]`, `Dict[str, int]`, not bare `list`, `dict`

### 2. Error Handling (Custom Exceptions)

**Import from `hybrid_rag.exceptions`:**
```python
from hybrid_rag import (
    HybridRAGException,           # Base - use for library-wide errors
    RetrieverNotInitializedError, # Retriever not ready
    RetrievalError,               # Operation failed
    VectorDBError,                # DB operation failed
)
```

**Usage Patterns:**
```python
# Check state and raise appropriate exception
if not self.initialized:
    raise RetrieverNotInitializedError("Retriever not initialized")

# Catch and re-raise with context
try:
    collection.query(query_vector)
except Exception as e:
    raise VectorDBError(f"Vector query failed: {str(e)}") from e

# In async code
try:
    results = await database.fetch()
except Exception as e:
    logger.error(f"Async operation failed", exc_info=True)
    raise RetrievalError(f"Failed to fetch results: {str(e)}")
```

**Never:**
```python
raise Exception("Something went wrong")  # Too generic
raise RuntimeError(...)                  # Not specific
if condition:
    pass  # Silent failures
```

### 3. Logging (Not Print Statements)

**Module-level logger:**
```python
import logging

logger = logging.getLogger(__name__)

def my_function(query: str) -> str:
    logger.debug(f"Starting retrieval for: {query}")
    logger.info("Retrieval complete")
    logger.warning("Low relevance score: 0.4")
    logger.error("Retrieval failed", exc_info=True)
    return result
```

**Log Levels:**
- `DEBUG`: Development/diagnostic info (low-level details)
- `INFO`: Normal operation events (startup, completion)
- `WARNING`: Unexpected but handled situations
- `ERROR`: Errors with full exception context

**Never:**
```python
print("Result:", result)  # Use logger.info instead
print(f"Query: {query}")  # Use logger.debug instead
```

### 4. Documentation (Google-Style Docstrings)

**Function docstring template:**
```python
def retrieve(
    self,
    query: str,
    top_k: int = 5,
    enable_rerank: bool = True
) -> List[Dict[str, Any]]:
    """Retrieve documents using hybrid search.
    
    Combines semantic search (vector similarity) with keyword search,
    fuses results, and optionally reranks using cross-encoder.
    
    Args:
        query: Search query as string (must be non-empty)
        top_k: Maximum documents to return (default: 5). Must be > 0.
        enable_rerank: Whether to apply cross-encoder reranking (default: True)
        
    Returns:
        List of documents sorted by relevance score. Each dict contains:
        - id: Document identifier
        - text: Document content
        - score: Relevance score (higher = more relevant)
        - metadata: Dict with source, page, etc.
        
    Raises:
        ValueError: If query is empty or top_k <= 0
        RetrievalError: If retrieval operation fails
        VectorDBError: If vector database operation fails
        
    Example:
        >>> retriever = HybridRetriever(collection, config)
        >>> results = retriever.retrieve("How to use offline maps?", top_k=3)
        >>> for doc in results:
        ...     print(f"{doc['score']:.2f}: {doc['text'][:100]}")
    """
    pass
```

**Class docstring template:**
```python
class HybridRetriever:
    """Hybrid retrieval system combining semantic and keyword search.
    
    This class encapsulates the core hybrid RAG logic, performing:
    1. Semantic search using vector embeddings
    2. Keyword-based search using BM25
    3. Result fusion with configurable weights
    4. Optional cross-encoder reranking
    
    Attributes:
        collection: ChromaDB collection for vector storage
        config: HybridRetrieverConfig with retrieval parameters
        
    Example:
        >>> config = HybridRetrieverConfig(semantic_weight=0.7)
        >>> retriever = HybridRetriever(collection, config)
        >>> results = retriever.retrieve("Query text")
    """
    pass
```

**Module docstring:**
```python
"""Hybrid RAG Retriever - Core retrieval engine combining semantic and keyword search.

This module provides the main HybridRetriever class which orchestrates:
- Vector-based semantic search using sentence embeddings
- Keyword-based search using term frequency
- Configurable weight-based fusion of results
- Cross-encoder based reranking (optional)

Type hints: All functions and classes are fully typed (PEP 561 compliant).

See Also:
    - config.HybridRetrieverConfig: Configuration parameters
    - reranker.CrossEncoderReranker: Reranking engine
    - vectordb: Vector database utilities
"""
```

### 5. Configuration Management

**Pattern: Dataclass with validation**
```python
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

@dataclass
class MyConfig:
    """Configuration for MyFeature.
    
    Attributes:
        param1: Description (type: str, default: "default")
        param2: Description (type: float, valid range: 0.0-1.0)
    """
    
    param1: str = "default"
    param2: float = 0.5
    
    def __post_init__(self) -> None:
        """Validate configuration parameters after initialization."""
        if not isinstance(self.param1, str):
            raise TypeError(f"param1 must be str, got {type(self.param1)}")
        
        if not 0.0 <= self.param2 <= 1.0:
            raise ValueError(f"param2 must be in [0.0, 1.0], got {self.param2}")
        
        logger.debug(f"MyConfig validated: param1={self.param1}, param2={self.param2}")
    
    def update(self, **kwargs: Any) -> "MyConfig":
        """Create updated copy of config with new values."""
        current = dataclasses.asdict(self)
        current.update(**kwargs)
        return MyConfig(**current)
```

### 6. Module Organization

**Where to put code:**

- **`config.py`** - Dataclass configurations, validation logic
- **`constants.py`** - Default values, enums, magic numbers
- **`exceptions.py`** - Custom exception classes (hierarchy)
- **`vectordb.py`** - Vector DB initialization, chunking, utilities
- **`retriever.py`** - Core retrieval logic (main class)
- **`reranker.py`** - Reranking engine
- **`api.py`** - FastAPI REST wrapper at root level
- **`__init__.py`** - Public API exports with `__all__`

**Imports pattern:**
```python
# In hybrid_rag/__init__.py
from .config import HybridRetrieverConfig
from .exceptions import HybridRAGException, RetrieverNotInitializedError
from .retriever import HybridRetriever
from .vectordb import initialize_vector_db

__all__ = [
    "HybridRetrieverConfig",
    "HybridRAGException",
    "RetrieverNotInitializedError",
    "HybridRetriever",
    "initialize_vector_db",
]
```

### 7. FastAPI Endpoints

**Pattern: Request/Response models + proper error handling**

```python
from fastapi import FastAPI, HTTPException, WebSocket
from pydantic import BaseModel, Field

class DocumentResult(BaseModel):
    """Response model for a single document."""
    id: str = Field(..., description="Document ID")
    text: str = Field(..., description="Document content")
    score: float = Field(..., description="Relevance score")

class HealthResponse(BaseModel):
    """Response model for health check endpoint."""
    status: str = Field(..., description="Service status")

@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Health check endpoint.
    
    Returns:
        HealthResponse with status
    """
    return HealthResponse(status="ok")

@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time chat and retrieval.
    
    Client sends: {"query": "...", "enable_rerank": false}
    
    Server responds with:
    1. Status message: {"type": "status", "message": "..."}
    2. Results message: {"type": "results", "cache_status": "HIT|MISS|ERROR", "results": [...]}
    3. Error message: {"type": "error", "message": "..."}
    
    Raises:
        WebSocketException on connection errors
    """
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            query = data.get("query")
            
            if not query:
                await websocket.send_json(
                    {"type": "error", "message": "Query is required"}
                )
                continue
            
            enable_rerank: bool = data.get("enable_rerank", True)
            
            try:
                # Retrieve documents using HybridRetriever
                results: List[Dict[str, Any]] = retriever.retrieve(
                    query=query,
                    enable_rerank=enable_rerank
                )
                
                await websocket.send_json({
                    "type": "results",
                    "query": query,
                    "cache_status": "HIT",
                    "results": [
                        {
                            "id": r["id"],
                            "text": r["text"],
                            "score": r["score"],
                            "source": r.get("source", "")
                        }
                        for r in results
                    ]
                })
            except RetrievalError as e:
                logger.error(f"Retrieval failed: {e}")
                await websocket.send_json(
                    {"type": "error", "message": f"Retrieval failed: {str(e)}"}
                )
            except VectorDBError as e:
                logger.error(f"Vector DB error: {e}")
                await websocket.send_json(
                    {"type": "error", "message": f"Database error: {str(e)}"}
                )
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
        try:
            await websocket.send_json(
                {"type": "error", "message": f"Error: {str(e)}"}
            )
        except Exception as send_error:
            logger.error(f"Failed to send error message: {send_error}")
        await websocket.close()
```

---

## ✅ Pre-Commit Checklist

Before marking code as ready:

- [ ] **Types:** 100% type hints present (no `Any` without reason)
- [ ] **Errors:** Using custom exceptions, not generic `Exception`
- [ ] **Logging:** No `print()` statements; appropriate log levels
- [ ] **Docs:** Comprehensive docstring with Args, Returns, Raises, Examples
- [ ] **Config:** Validation happens in `__post_init__` or explicit validate method
- [ ] **Tests:** Code is testable (dependencies injected, pure functions preferred)
- [ ] **Imports:** Only necessary imports; avoided circular dependencies
- [ ] **Naming:** Clear, descriptive names (`retriever` not `r`, `config` not `c`)
- [ ] **Edge Cases:** Handles empty inputs, None values, boundary conditions

---

## 🔍 Common Patterns

### Async Functions
```python
from typing import Coroutine

async def process_async(query: str) -> str:
    """Process query asynchronously."""
    logger.debug(f"Processing: {query}")
    result = await some_async_operation()
    logger.info(f"Processing complete")
    return result
```

### Type Aliases for Clarity
```python
from typing import TypeAlias

DocumentDict: TypeAlias = Dict[str, Any]
ScoreFloat: TypeAlias = float

def process(doc: DocumentDict, score: ScoreFloat) -> bool:
    """Process document with score."""
    pass
```

### Optional Returns with Validation
```python
def get_or_none(key: str) -> Optional[str]:
    """Get value or return None if not found."""
    if key in self.cache:
        return self.cache[key]
    return None
```

### Iteration with Type Hints
```python
def process_documents(docs: List[Dict[str, str]]) -> List[str]:
    """Extract text from documents."""
    return [doc["text"] for doc in docs if "text" in doc]
```

---

## 🚫 Anti-Patterns to Avoid

| ❌ Don't | ✅ Do |
|---------|------|
| `def func(x):` | `def func(x: str) -> str:` |
| `raise Exception(msg)` | `raise RetrievalError(msg)` |
| `print(result)` | `logger.info(f"Result: {result}")` |
| Docstring missing examples | Docstring with runnable Example section |
| Config validation elsewhere | Config validation in `__post_init__` |
| Mutable default args `[]`, `{}` | Use `None` and initialize in code |
| Bare `except:` | Catch specific exceptions |
| Magic numbers scattered | Define in `constants.py` |
| No module docstring | Always include module-level docstring |

---

## 📚 See Also

- [Workspace Instructions](../copilot-instructions.md) - Project-wide conventions
- [Library Design](../LIBRARY_DESIGN.md) - Architecture overview
- [API Integration Guide](../API_INTEGRATION.md) - REST endpoint contracts
- [Quick Start](../QUICK_START.md) - Usage examples
