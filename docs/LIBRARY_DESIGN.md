"""Hybrid RAG Library - Developer Guide

This document provides an overview of the refactored hybrid RAG library
structure, design decisions, and best practices followed.
"""

# Hybrid RAG Library - Refactoring Documentation

## Overview

The hybrid RAG library has been refactored to follow Python best practices for production-ready libraries. The code is now modular, well-documented, properly typed, and includes comprehensive error handling and logging.

## Directory Structure

```
hybrid_rag/             # Main library package
├── __init__.py         # Package initialization and public API
├── config.py           # Configuration classes with validation
├── constants.py        # Constants and default values
├── exceptions.py       # Custom exception classes
├── reranker.py         # Cross-encoder based reranking
├── retriever.py        # Core hybrid retrieval engine
└── vectordb.py         # Vector database initialization and utilities

# Example and API files at root
├── main_example.py     # Example usage of the library
├── api.py              # FastAPI REST API wrapper
└── hybrid_rag_flow.py  # Simplified example script
```

## Design Principles

### 1. **Modularity**
   - Each module has a single, well-defined responsibility
   - Core logic separated from API layer
   - Easy to test and extend

### 2. **Type Safety**
   - Comprehensive type hints throughout
   - Pydantic models for request/response validation
   - Better IDE support and error detection

### 3. **Error Handling**
   - Custom exception hierarchy for different error types
   - Proper exception propagation with context
   - Graceful degradation where appropriate

### 4. **Logging**
   - Module-level loggers instead of print statements
   - Structured logging with appropriate levels
   - Easy to configure and filter logs

### 5. **Configuration**
   - Dataclass-based configuration with validation
   - Type-safe configuration parameters
   - Post-init validation to catch invalid configs early

### 6. **Documentation**
   - Comprehensive docstrings (Google style)
   - Type hints as documentation
   - Usage examples in docstrings
   - Module-level documentation

## Module Descriptions

### `config.py` - Configuration Management
Defines `HybridRetrieverConfig` dataclass with:
- **Semantic search parameters**: `semantic_top_k`, `semantic_weight`
- **Keyword search parameters**: `keyword_top_k`, `keyword_weight`
- **Fusion parameters**: `final_top_k`, `pre_rerank_top_k`
- **Reranking**: `enable_rerank` toggle
- **Validation**: Post-init validation of weights and ranges

```python
config = HybridRetrieverConfig(
    semantic_weight=0.7,
    keyword_weight=0.3,
    enable_rerank=True
)
```

### `constants.py` - Constants and Defaults
Centralized default values:
- `DEFAULT_PERSIST_DIRECTORY`: ChromaDB persistence location
- `MIN_RELEVANCE_SCORE`: Score threshold for relevant documents
- `STOP_WORDS`: Filtered keywords for keyword search

### `exceptions.py` - Exception Hierarchy
Custom exceptions for better error handling:
- `HybridRAGException`: Base class for all library exceptions
- `RetrieverNotInitializedError`: Retriever not ready
- `RetrievalError`: Retrieval operation failed
- `VectorDBError`: Vector database operation failed

### `vectordb.py` - Vector Database Management
Core functions:
- `chunk_text()`: Split text into overlapping chunks
- `initialize_vector_db()`: Set up ChromaDB collection with embeddings
- `get_sample_documents()`: Load sample Google Maps documentation

Features:
- Local sentence-transformer embeddings (no external APIs)
- Cosine distance metric for similarity
- Persistent storage
- Comprehensive error handling

### `reranker.py` - Cross-Encoder Reranking
`CrossEncoderReranker` class:
- Loads pre-trained ms-marco cross-encoder model
- Scores query-document pairs directly
- Applies sigmoid normalization to logits
- Returns sorted results by relevance

### `retriever.py` - Core Hybrid Retrieval
`HybridRetriever` class implements:
- **Semantic search**: Embedding-based similarity search
- **Keyword search**: Stop-word filtered keyword matching
- **Score fusion**: Weighted combination of scores
- **Reranking**: Optional cross-encoder reranking
- **Deduplication**: Source-based result deduplication

Pipeline stages:
1. Query cleaning (remove special characters)
2. Parallel semantic and keyword search
3. Score fusion with configurable weights
4. Optional cross-encoder reranking
5. Deduplication and top-k selection

### `cache.py` - Cache Backends and Runtime Cache Design

The current implementation uses **two runtime cache layers** plus persistent vector storage:

| Layer | Implemented In | Purpose |
|---|---|---|
| **L1 Query Cache** | `api.py`, `api_middleware.py`, `hybrid_rag/cache.py` | Reuse full retrieval results for identical request identity |
| **L2 Embedding Cache** | `hybrid_rag/retriever.py` | Reuse computed query embeddings inside `HybridRetriever` |
| **Vector Storage** | ChromaDB collection | Persistent document storage, not a cache |

There is **no separate L3 config cache** in the current codebase. The live implementation stores configuration directly in `_config` and includes a config fingerprint in the shared L1 cache key.

#### CacheBackend Interface

`hybrid_rag/cache.py` defines a **synchronous** backend interface used by the API layer:

```python
class CacheBackend(ABC):
    @abstractmethod
    def get(self, key: str) -> Optional[Any]:
        ...

    @abstractmethod
    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        ...

    @abstractmethod
    def delete(self, key: str) -> None:
        ...

    @abstractmethod
    def clear(self) -> None:
        ...

    @abstractmethod
    def stats(self) -> Dict[str, Any]:
        ...
```

Built-in backends:

- **InMemoryCache**: thread-safe TTL/LRU cache for development and tests
- **RedisCache**: distributed cache backend for shared deployments

#### L1 Query Cache

The L1 cache is a **shared query-result cache** backed by `CacheBackend`.

It is exercised through two code paths that use the same backend instance:

- `QueryCacheMiddleware` in `api_middleware.py` caches `POST /retrieve` HTTP responses
- `_shared_retrieve_documents()` in `api.py` caches retrieval results for REST/WebSocket parity

These are two access paths to one logical L1 cache, not separate layers.

The shared retrieval cache key is derived from:

1. normalized query text
2. effective rerank mode
3. configuration fingerprint
4. corpus version token

Transport is intentionally excluded, so REST and WebSocket requests share the same L1 entries when their retrieval identity matches.

#### L2 Embedding Cache

`HybridRetriever` maintains an in-process embedding cache:

```python
self._embedding_cache = cachetools.LRUCache(maxsize=5000)
```

`_get_or_encode_embedding()` hashes the query text, returns cached embeddings on hit, and records hit/miss counters exposed through `get_embedding_cache_stats()`.

This cache speeds up repeated or normalized queries by avoiding repeat encoder calls. It does **not** cache final retrieval results.

#### CacheSettings

The current `CacheSettings` model in `hybrid_rag/config.py` is:

```python
@dataclass
class CacheSettings:
    backend: Literal["memory", "redis"] = "memory"
    ttl_seconds: int = 3600
    redis_url: Optional[str] = None
    key_prefix: str = "hybrid_rag_cache:"
    max_size: int = 10000
```

Production validation enforces:

- `redis_url` must be present for `backend="redis"`
- `rediss://` is required in production
- Redis authentication credentials are required in production
- `ttl_seconds > 0`
- `max_size > 0`

#### Invalidation and Consistency

The current behavior is:

| Event | L1 Behavior |
|---|---|
| `PUT /config` success | clear L1 cache and advance the retrieval identity token |
| `POST /documents` with `ingest_type="update"` | clear L1 cache |
| `POST /documents` with `ingest_type="add"` | preserve existing L1 entries; future shared keys observe the new corpus count |
| cache backend failure | fail open; retrieval still succeeds without cache |

L2 embeddings are process-local and are not explicitly invalidated by config changes because they cache encoder output, not fused retrieval results.

#### Cache Stats

`GET /cache/stats` returns a **layered** response with four top-level keys:

```json
{
  "l1_query_cache": {
    "backend": "memory",
    "hits": 10,
    "misses": 5,
    "hit_rate": 0.667,
    "size": 3,
    "max_size": 100,
    "ttl_seconds": 3600,
    "corpus_version": "gen0.n1"
  },
  "l2_embedding_cache": {
    "hits": 20,
    "misses": 8,
    "hit_rate": 0.714,
    "size": 12,
    "capacity": 5000
  },
  "backend_health": {
    "connected": true,
    "latency_ms": null,
    "fallback_active": false,
    "error": null
  },
  "timestamp": "2026-04-22T10:30:45.123456Z"
}
```

For deployment and troubleshooting details, see [CACHE_DEPLOYMENT.md](./CACHE_DEPLOYMENT.md).

### `__init__.py` - Public API
Exports all public classes and functions:
- `HybridRetriever`, `HybridRetrieverConfig`
- `CrossEncoderReranker`
- Exception classes
- Utility functions

## Best Practices Implemented

### 1. **Type Hints**
```python
def retrieve(self, query: str) -> List[Dict[str, Any]]:
    """Execute hybrid retrieval pipeline..."""
```

### 2. **Docstrings (Google Style)**
```python
def chunk_text(text: str, chunk_size: int = 500) -> List[str]:
    """Split text into overlapping chunks.

    Args:
        text: The text string to split.
        chunk_size: Target size of each chunk.

    Returns:
        List of text chunks.

    Raises:
        ValueError: If parameters are invalid.
    """
```

### 3. **Logging Instead of Print**
```python
logger = logging.getLogger(__name__)
logger.info("Vector DB initialized successfully")
logger.debug("Detailed operation information")
logger.error("Error occurred", exc_info=True)
```

### 4. **Configuration Validation**
```python
@dataclass
class HybridRetrieverConfig:
    def __post_init__(self) -> None:
        """Validate parameters after initialization."""
        if not (0 < self.semantic_top_k):
            raise ValueError("semantic_top_k must be > 0")
```

### 5. **Error Handling**
```python
try:
    results = retriever.retrieve(query)
except RetrievalError as e:
    logger.error(f"Retrieval failed: {e}")
    raise
```

### 6. **`__all__` Exports**
```python
__all__ = [
    "HybridRetriever",
    "HybridRetrieverConfig",
    # ... other public items
]
```

## Usage Examples

### Basic Usage
```python
from hybrid_rag import (
    HybridRetriever,
    HybridRetrieverConfig,
    initialize_vector_db,
    get_sample_documents,
)

# Initialize
documents = get_sample_documents()
collection = initialize_vector_db(documents)

# Configure
config = HybridRetrieverConfig(
    semantic_weight=0.7,
    keyword_weight=0.3,
    enable_rerank=True,
)

# Create retriever
retriever = HybridRetriever(collection, config)

# Retrieve
results = retriever.retrieve("Your query here")
```

### API Usage
```python
# Run the FastAPI server
python api.py

# Make requests
curl -X POST http://localhost:8000/retrieve \
  -H "Content-Type: application/json" \
  -d '{"query": "How do I use offline maps?"}'
```

## Testing Considerations

The refactored code is designed for easier testing:

1. **Dependency Injection**: Configuration and collection passed to retriever
2. **Logging**: Uses standard logging module for easy mocking
3. **Exception Hierarchy**: Specific exceptions for better testing
4. **Type Safety**: Type hints catch errors early

Example test:
```python
def test_hybrid_retriever():
    config = HybridRetrieverConfig()
    collection = initialize_vector_db(get_sample_documents())
    retriever = HybridRetriever(collection, config)
    
    results = retriever.retrieve("test query")
    assert len(results) > 0
    assert all("score" in r for r in results)
```

## Plan Document Consolidation

This section documents where findings from the caching blueprint and design phase (see [plan/README.md](./plan/README.md)) have been consolidated into production documentation:

| Plan Document | Key Findings | Main Doc Location | Status |
|---|---|---|---|
| **CACHE-CONSISTENCY-POLICY.md** | REST vs WS parity contract, invalidation rules, cache key identity | [Cache Consistency Policy](#cache-consistency-policy-rest-vs-websocket) (above) | ✅ Consolidated |
| **Caching_Architecture_Blueprint.md** | Earlier caching blueprint and design rationale | [cache.py section](#cachepy---cache-backends-and-runtime-cache-design) (above) | ✅ Consolidated |
| **ANALYSIS_REPORT_DOUBLECHECK_QUALITY_PLAYBOOK.md** | 3 critical security issues (CRIT-001, CRIT-002, CRIT-003) | [SECURITY_COMPLIANCE.md](./SECURITY_COMPLIANCE.md) | ✅ Consolidated |
| **qa-cache-consistency-policy-matrix.md** | Cache parity test assertions, observable contract | Test planning (future testing guide) | 📋 Reference for QA |
| **CACHE-001-summary.md** | CacheBackend ABC, InMemoryCache, RedisCache implementations | [cache.py section](#cachepy---multi-backend-caching-layer) (above) | ✅ Consolidated |
| **CACHE-003-completion.md** | QueryCacheMiddleware implementation, X-Cache headers | [Middleware patterns in API_INTEGRATION.md](./API_INTEGRATION.md) | ✅ Referenced |
| **IMPLEMENTATION_SUMMARY.md** | 169 passing tests, production readiness, implementation waves | [Deployment checklist](./DEPLOYMENT_PRODUCTION.md#pre-production-checklist) | ✅ Referenced |

**Summary:** All critical findings from the planning and design phase have been consolidated into main documentation (SECURITY_COMPLIANCE.md, LIBRARY_DESIGN.md, API_INTEGRATION.md, DEPLOYMENT_PRODUCTION.md). Plan documents remain in `docs/plan/` as historical reference for detailed analysis and decision rationale.

**For detailed analysis and decision matrices**, use the plan archive index at [plan/README.md](./plan/README.md).

---

## Configuration Management

### Environment-based Configuration
```python
import os

batch_size = int(os.getenv("BATCH_SIZE", 32))
config = HybridRetrieverConfig(
    semantic_weight=float(os.getenv("SEMANTIC_WEIGHT", 0.7)),
    enable_rerank=os.getenv("ENABLE_RERANK", "true").lower() == "true"
)
```

### Logging Configuration
```python
import logging.config

logging.config.dictConfig({
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        }
    },
})
```

## Performance Considerations

1. **Caching**: ChromaDB handles internal caching of embeddings
2. **Batching**: Process multiple queries in batch if needed
3. **Reranking**: Optional for performance-critical scenarios
4. **Model Size**: Using MiniLM models for efficiency

## Future Enhancements

1. Add async retrieval support
2. Implement caching layer for frequent queries
3. Add metrics/monitoring endpoints
4. Support for custom embedding models
5. Batch retrieval operations
6. Configuration file support (YAML/JSON)

## Migration from Old Code

Changes from original `hybrid_rag_flow.py`:

1. **Split into modules**: Organized code by responsibility
2. **Removed print statements**: Use logging instead
3. **Added type hints**: Comprehensive type annotations
4. **Added error handling**: Custom exceptions and try-catch blocks
5. **Added logging**: Module-level loggers with different levels
6. **Configuration validation**: Validate parameters on initialization
7. **Better docstrings**: Google-style with examples
8. **API layer**: Separate FastAPI wrapper for REST interface

## Compatibility

- Python 3.9+
- chromadb 0.3.24+
- sentence-transformers 2.2.0+
- fastapi 0.100.0+
- pydantic 2.0.0+
- uvicorn 0.23.0+
