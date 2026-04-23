"""Hybrid RAG Library - Combining semantic and keyword search for document retrieval.

A production-ready library for hybrid retrieval-augmented generation (RAG) that combines
semantic search using embeddings with keyword-based search for robust document retrieval.

Features:
    - Hybrid search combining semantic and keyword retrieval
    - Cross-encoder reranking for improved ranking accuracy
    - Source-based deduplication to avoid redundant results
    - Configurable weights and thresholds
    - Comprehensive logging and error handling
    - ChromaDB integration for vector storage
    - Local sentence-transformer embeddings (no external APIs)

Modules:
    config: Configuration classes for retrieval parameters
    constants: Constants and default values used throughout the library
    exceptions: Custom exception classes
    reranker: Cross-encoder based document reranking
    retriever: Core hybrid retrieval engine
    vectordb: Vector database initialization and document chunking

Quick Start:
    >>> from hybrid_rag import HybridRetriever, HybridRetrieverConfig
    >>> from hybrid_rag.vectordb import initialize_vector_db, get_sample_documents
    >>>
    >>> # Initialize vector database
    >>> documents = get_sample_documents()
    >>> collection = initialize_vector_db(documents)
    >>>
    >>> # Create retriever with custom configuration
    >>> config = HybridRetrieverConfig(
    ...     semantic_weight=0.7,
    ...     keyword_weight=0.3,
    ...     enable_rerank=True
    ... )
    >>> retriever = HybridRetriever(collection, config)
    >>>
    >>> # Retrieve documents
    >>> results = retriever.retrieve("Your search query here")
    >>> for result in results:
    ...     print(f"Score: {result['score']:.3f}")
    ...     print(f"Text: {result['text'][:100]}")
"""

__version__ = "1.0.0"
__author__ = "Aritra Ghosh"
__all__ = [
    "HybridRetriever",
    "HybridRetrieverConfig",
    "CrossEncoderReranker",
    "HybridRAGException",
    "RetrieverNotInitializedError",
    "RetrievalError",
    "VectorDBError",
    "CacheBackend",
    "InMemoryCache",
    "RedisCache",
    "CacheSettings",
    "create_cache_backend",
    "chunk_text",
    "initialize_vector_db",
    "get_sample_documents",
    "DEFAULT_CONFIG",
    "STOP_WORDS",
    "MIN_RELEVANCE_SCORE",
    "DEFAULT_PERSIST_DIRECTORY",
    "CACHE_TELEMETRY_LABELS",
]

# Public API imports
from .cache import CacheBackend, InMemoryCache, RedisCache
from .config import (
    DEFAULT_CONFIG,
    CacheSettings,
    HybridRetrieverConfig,
    create_cache_backend,
)
from .constants import (
    DEFAULT_PERSIST_DIRECTORY,
    MIN_RELEVANCE_SCORE,
    STOP_WORDS,
    CACHE_TELEMETRY_LABELS,
)
from .exceptions import (
    HybridRAGException,
    RetrievalError,
    RetrieverNotInitializedError,
    VectorDBError,
)
from .reranker import CrossEncoderReranker
from .retriever import HybridRetriever
from .vectordb import chunk_text, get_sample_documents, initialize_vector_db
