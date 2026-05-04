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
    vectordb: Vector database initialization and chunking (chunk_document, chunk_text)

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
    "chunk_document",
    "initialize_vector_db",
    "open_collection",
    "get_sample_documents",
    "list_existing_collections",
    "is_valid_collection_name",
    "sanitize_collection_name",
    "DEFAULT_CONFIG",
    "STOP_WORDS",
    "MIN_RELEVANCE_SCORE",
    "KNOWLEDGE_DB_DIRECTORY",
    "CACHE_TELEMETRY_LABELS",
    "DEFAULT_EMBEDDING_MODEL",
    "save_config_to_disk",
    "load_config_from_disk",
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
    CACHE_TELEMETRY_LABELS,
    DEFAULT_EMBEDDING_MODEL,
    KNOWLEDGE_DB_DIRECTORY,
    MIN_RELEVANCE_SCORE,
    STOP_WORDS,
)
from .exceptions import (
    HybridRAGException,
    RetrievalError,
    RetrieverNotInitializedError,
    VectorDBError,
)
from .persistence import load_config_from_disk, save_config_to_disk
from .reranker import CrossEncoderReranker
from .retriever import HybridRetriever
from .vectordb import (
    chunk_document,
    chunk_text,
    get_sample_documents,
    initialize_vector_db,
    is_valid_collection_name,
    list_existing_collections,
    open_collection,
    sanitize_collection_name,
)
