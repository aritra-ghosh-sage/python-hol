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
- `DEFAULT_PERSIST_DIRECTORY`: ChromaDB persistence location (default: `./ai_support_kb`)
  - Controls where ChromaDB stores vector collections on disk
  - Can be overridden by passing `persist_dir` parameter to `initialize_vector_db()`
  - Provides a persistent on-disk storage directory, but the current `initialize_vector_db()` flow recreates the collection during initialization, so embeddings are recomputed rather than reused across application restarts
- `MIN_RELEVANCE_SCORE`: Score threshold for relevant documents
- `STOP_WORDS`: Filtered keywords for keyword search
- `CACHE_TELEMETRY_LABELS`: Structured event labels for cache observability

### `exceptions.py` - Exception Hierarchy
Custom exceptions for better error handling:
- `HybridRAGException`: Base class for all library exceptions
- `RetrieverNotInitializedError`: Retriever not ready
- `RetrievalError`: Retrieval operation failed
- `VectorDBError`: Vector database operation failed

### `vectordb.py` - Vector Database Management
Core functions:
- `chunk_text()`: Split text into overlapping chunks using recursive character splitting
- `initialize_vector_db()`: Set up ChromaDB collection with embeddings
  - Accepts `documents`, `persist_dir` (defaults to `DEFAULT_PERSIST_DIRECTORY`), and `collection_name` parameters
  - Creates persistent ChromaDB client at specified directory
  - Deletes and recreates collection to ensure clean state
  - Uses SentenceTransformer embeddings (all-MiniLM-L6-v2)
- `get_sample_documents()`: Load sample Google Maps documentation

Collection Management:
- **Persistent Storage**: Collections are stored on disk at `persist_dir` location
- **Collection Naming**: Default collection name is `"hybrid_rag_collection"`
- **Embedding Function**: Uses local sentence-transformers (no external API calls)
- **Distance Metric**: Cosine similarity for normalized embeddings
- **Document Chunking**: Automatic text splitting for optimal embedding performance
- **Metadata**: Each chunk stores source URL for traceability

Features:
- Local sentence-transformer embeddings (no external APIs)
- Cosine distance metric for similarity
- On-disk storage directory (collection is recreated on each initialization)
- Comprehensive error handling with `VectorDBError` exceptions

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
```bash
# Run the FastAPI server
python api.py

# Connect via WebSocket (the primary retrieval path)
websocat ws://localhost:8000/ws/chat

# Send a query
{"query": "How do I use offline maps?"}
```

> The API includes an L1 query cache (in `_shared_retrieve_documents`) and L2 embedding cache (retriever-internal). See [CACHING_ARCHITECTURE.md](./CACHING_ARCHITECTURE.md) for details.

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

## Configuration Management

### Environment-based Configuration

The following snippet illustrates **consumer-side** configuration. The `api.py`
entrypoint does not currently read `PERSIST_DIRECTORY` from the environment (it
calls `initialize_vector_db(documents)` with the library default); the pattern
below is intended for library consumers who want to build their own entry point
with environment-driven persistence paths.

```python
import os
from hybrid_rag.constants import DEFAULT_PERSIST_DIRECTORY

# Consumer-controlled: override default persist directory via environment variable
persist_dir = os.getenv("PERSIST_DIRECTORY", DEFAULT_PERSIST_DIRECTORY)

batch_size = int(os.getenv("BATCH_SIZE", 32))
config = HybridRetrieverConfig(
    semantic_weight=float(os.getenv("SEMANTIC_WEIGHT", 0.7)),
    enable_rerank=os.getenv("ENABLE_RERANK", "true").lower() == "true"
)

# Initialize with custom persist directory
collection = initialize_vector_db(
    documents=get_sample_documents(),
    persist_dir=persist_dir,
    collection_name="my_custom_collection"
)
```

### Collection Persistence
The vector database uses ChromaDB's persistent storage to keep its files on disk between application restarts, but the current initialization flow recreates the collection each time:

- **Default Location**: `./ai_support_kb` (configurable via `persist_dir` parameter)
- **Collection Lifecycle**:
  - `initialize_vector_db()` creates or recreates the collection
  - Existing collections at the same path are deleted before recreation
  - This ensures a clean state for each initialization, so previously stored embeddings are not reused by this flow
- **Storage Format**: ChromaDB internal format (SQLite + HNSW index)
- **Access Pattern**: Collections are accessed via the retriever's `collection` property

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
2. Implemented in v0.1.0 — see [CACHING_ARCHITECTURE.md](./CACHING_ARCHITECTURE.md)
3. `GET /cache/stats` metrics endpoint implemented in v0.1.0
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
