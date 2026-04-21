"""FastAPI REST API for Hybrid RAG Retrieval Service.

This module provides a production-ready REST API for the hybrid RAG library,
including health checks, retrieval endpoints, configuration management,
document ingestion, and WebSocket-based chat.

CACHING ARCHITECTURE:
    L1 Response Cache: FastAPI middleware intercepts POST /retrieve requests and
        caches full responses for identical queries. Reduces embedding computations.
    L2 Embedding Cache: Integrated into HybridRetriever as an LRU cache for
        embedding computations. Hits on semantically similar queries reduce model
        inference latency.
    L3 Vector Storage: Persistent ChromaDB vector store serves as the base layer.

Configuration:
    Cache behavior is configured via environment variables (see .env.local.example):
    - CACHE_BACKEND: 'memory' (development) or 'redis' (production)
    - REDIS_URL: Connection string for Redis backend (required if CACHE_BACKEND=redis)
    - CACHE_TTL_SECONDS: Time-to-live for cache entries (default: 3600)
    - CACHE_KEY_PREFIX: Prefix for cache keys (default: 'hybrid_rag_cache:')
    - CACHE_MAX_SIZE: Max entries in memory cache (default: 10000)

Monitoring:
    - GET /cache/stats: Returns cache hit rate, current size, and backend info
    - All cache failures are non-blocking (fail-open): cache issues never break requests

For detailed caching documentation, see docs/CACHE_DEPLOYMENT.md and docs/CACHE_PERF_REPORT.md
"""

import base64
import io
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from contextlib import asynccontextmanager

import requests
from fastapi import FastAPI, HTTPException, WebSocketDisconnect, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from hybrid_rag import (
    HybridRetriever,
    HybridRetrieverConfig,
    RetrievalError,
    RetrieverNotInitializedError,
    VectorDBError,
    initialize_vector_db,
    get_sample_documents,
    chunk_text,
)
from hybrid_rag.cache import CacheBackend
from hybrid_rag.config import CacheSettings, create_cache_backend
from api_middleware import QueryCacheMiddleware

with_pdf_support = True
try:
    import pypdf
except ImportError:
    with_pdf_support = False

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

__all__ = ["app", "initialize_retriever"]

# Global retriever and cache instances
_retriever: Optional[HybridRetriever] = None
_config: Optional[HybridRetrieverConfig] = None
_cache: Optional[CacheBackend] = None
_cache_generation: int = 0


# Pydantic models for request/response validation
class RetrievalRequest(BaseModel):
    """Request model for document retrieval."""

    query: str = Field(
        ..., min_length=1, max_length=500, description="Search query"
    )
    enable_rerank: Optional[bool] = Field(
        None, description="Override reranking setting"
    )


class DocumentResult(BaseModel):
    """Model representing a single retrieved document."""

    id: str = Field(..., description="Document identifier")
    text: str = Field(..., description="Document text content")
    source: str = Field(..., description="Document source URL")
    score: float = Field(..., description="Relevance score (may be negative due to fusion/reranking)")


class RetrievalResponse(BaseModel):
    """Response model for retrieval requests."""

    query: str = Field(..., description="Original search query")
    results: List[DocumentResult] = Field(
        ..., description="List of retrieved documents"
    )
    total_results: int = Field(..., ge=0, description="Total number of results")


class ConfigResponse(BaseModel):
    """Response model for configuration endpoint."""

    semantic_top_k: int
    keyword_top_k: int
    final_top_k: int
    semantic_weight: float
    keyword_weight: float
    enable_rerank: bool
    pre_rerank_top_k: int


class HealthResponse(BaseModel):
    """Response model for health check endpoint."""

    status: str = Field(..., description="Service status")
    retriever_ready: str = Field(..., description="Retriever readiness status")


class ConfigUpdateRequest(BaseModel):
    """Request model for configuration updates.

    All fields are optional - only provided fields will be updated.
    """

    semantic_top_k: Optional[int] = Field(
        None, gt=0, description="Number of semantic search results"
    )
    keyword_top_k: Optional[int] = Field(
        None, gt=0, description="Number of keyword search results"
    )
    final_top_k: Optional[int] = Field(
        None, gt=0, description="Maximum final results to return"
    )
    semantic_weight: Optional[float] = Field(
        None, ge=0.0, le=1.0, description="Weight for semantic search (0-1)"
    )
    keyword_weight: Optional[float] = Field(
        None, ge=0.0, le=1.0, description="Weight for keyword search (0-1)"
    )
    enable_rerank: Optional[bool] = Field(
        None, description="Enable cross-encoder reranking"
    )
    pre_rerank_top_k: Optional[int] = Field(
        None, gt=0, description="Candidates to rerank before selection"
    )


class DocumentIngestionRequest(BaseModel):
    """Request model for adding custom documents.
    
    Attributes:
        source_type: Type of data source: 'text', 'url', or 'file'.
        content: Text content, URL, or base64-encoded file.
        filename: Original filename for file uploads.
        source_label: User-friendly label for the data source.
        ingest_type: Type of ingest operation: 'add' or 'update'.
            - 'add': Preserve existing cache (for bulk additions)
            - 'update': Clear cache after ingestion (default for backwards compatibility)
    """

    source_type: Literal["text", "url", "file"] = Field(
        ..., description="Type of data source: 'text', 'url', or 'file'"
    )
    content: str = Field(
        ..., min_length=1, description="Text content, URL, or base64-encoded file"
    )
    filename: Optional[str] = Field(
        None, description="Original filename (for file uploads)"
    )
    source_label: Optional[str] = Field(
        None, description="User-friendly label for the data source"
    )
    ingest_type: Literal["add", "update"] = Field(
        default="update",
        description="Ingest type: 'add' preserves cache, 'update' clears cache"
    )


class DocumentIngestionResponse(BaseModel):
    """Response model for document ingestion."""

    status: str = Field(..., description="Operation status ('success' or 'error')")
    documents_added: int = Field(..., description="Number of documents added")
    chunks_created: int = Field(..., description="Number of chunks created")
    message: Optional[str] = Field(None, description="Additional message")


class DocumentSource(BaseModel):
    """Model representing a document source."""

    source: str = Field(..., description="Source identifier")
    count: int = Field(..., description="Number of chunks from this source")


class SourcesResponse(BaseModel):
    """Response model for listing document sources."""

    sources: List[DocumentSource] = Field(
        ..., description="List of available document sources"
    )


class CacheStatsResponse(BaseModel):
    """Response model for cache statistics.
    
    Contains detailed cache performance metrics for monitoring and debugging.
    Implements fail-open principle: never raises errors, always provides best-effort stats.
    
    Attributes:
        backend: Cache backend identifier ('memory' or 'redis').
        hits: Total number of cache hits since initialization.
        misses: Total number of cache misses since initialization.
        hit_rate: Cache hit rate as a float (0.0-1.0).
            Calculated as: hits / (hits + misses), or 0.0 if no activity.
        size: Current number of entries in the cache.
        max_size: Maximum capacity of the cache in entries.
        ttl_seconds: Configured time-to-live for cache entries in seconds.
        timestamp: When these statistics were captured (UTC datetime).
    
    Example:
        >>> response = CacheStatsResponse(
        ...     backend="memory",
        ...     hits=1500,
        ...     misses=350,
        ...     hit_rate=0.811,
        ...     size=125,
        ...     max_size=10000,
        ...     ttl_seconds=3600,
        ...     timestamp=datetime.now(timezone.utc)
        ... )
        >>> print(f"Hit rate: {response.hit_rate:.1%}")  # 81.1%
    """

    backend: str = Field(..., description="Cache backend ('memory' or 'redis')")
    hits: int = Field(..., ge=0, description="Total cache hits")
    misses: int = Field(..., ge=0, description="Total cache misses")
    hit_rate: float = Field(..., ge=0.0, le=1.0, description="Cache hit rate (0.0-1.0)")
    size: int = Field(..., ge=0, description="Current cache size in entries")
    max_size: int = Field(..., ge=0, description="Maximum cache capacity")
    ttl_seconds: int = Field(..., ge=0, description="Configured TTL in seconds")
    timestamp: datetime = Field(..., description="When stats were captured (UTC)")


class WsMessageBase(BaseModel):
    """Base model for WebSocket messages."""

    type: str = Field(..., description="Message type")


class WsQueryMessage(BaseModel):
    """WebSocket message sent by client (query request)."""

    query: str = Field(
        ..., min_length=1, max_length=500, description="Search query"
    )
    enable_rerank: Optional[bool] = Field(
        None, description="Override reranking setting"
    )


class WsStatusMessage(BaseModel):
    """WebSocket status message sent by server."""

    type: Literal["status"] = "status"
    message: str = Field(..., description="Status message")


class WsResultsMessage(BaseModel):
    """WebSocket results message sent by server."""

    type: Literal["results"] = "results"
    query: str = Field(..., description="Original query")
    results: List[DocumentResult] = Field(..., description="Retrieved documents")
    total_results: int = Field(..., description="Total number of results")


class WsErrorMessage(BaseModel):
    """WebSocket error message sent by server."""

    type: Literal["error"] = "error"
    message: str = Field(..., description="Error message")


def initialize_retriever() -> None:
    """Initialize the global hybrid retriever instance.

    Sets up the vector database and creates a HybridRetriever with default
    configuration. Called during application startup.

    Raises:
        VectorDBError: If vector database initialization fails.
        Exception: If any other initialization step fails.
    """
    global _retriever, _config

    try:
        logger.info("Initializing hybrid retriever...")

        # Initialize configuration
        _config = HybridRetrieverConfig(
            semantic_weight=0.7, keyword_weight=0.3, enable_rerank=True
        )

        # Initialize vector database
        logger.debug("Loading sample documents...")
        documents = get_sample_documents()

        logger.debug("Initializing vector database...")
        collection = initialize_vector_db(documents)

        # Create retriever
        _retriever = HybridRetriever(collection, _config)
        logger.info("✓ Hybrid retriever initialized successfully")

    except VectorDBError as e:
        logger.error(f"Vector DB initialization failed: {e}")
        raise
    except Exception as e:
        logger.error(f"Retriever initialization failed: {e}")
        raise


# @app.on_event("startup")
@asynccontextmanager
async def startup_event(app: FastAPI):
    """Application startup event handler.
    
    Initializes both the hybrid retriever and the cache backend from environment settings.
    Both are stored as globals and cleaned up on shutdown.
    
    Raises:
        Exception: If initialization fails, critical exception is logged.
    """
    global _retriever, _config, _cache
    try:
        # Initialize retriever
        initialize_retriever()
        
        # Initialize cache from environment settings
        try:
            cache_settings = CacheSettings.from_env()
            _cache = create_cache_backend(cache_settings)
            logger.info(f"✓ Cache initialized: backend={cache_settings.backend}, ttl={cache_settings.ttl_seconds}s")
        except Exception as e:
            logger.error(f"Cache initialization failed: {e}. Continuing without cache.")
            _cache = None
        
        yield
    except Exception as e:
        logger.critical(f"Failed to start application: {e}")
        raise
    finally:
        # Cleanup on shutdown
        if _cache is not None:
            try:
                _cache.clear()
                logger.info("Cache cleared on shutdown")
            except Exception as e:
                logger.warning(f"Error clearing cache on shutdown: {e}")
        
        _retriever = None
        _config = None
        _cache = None
        logger.info("Application shutdown complete")


# FastAPI application
app = FastAPI(
    title="Hybrid RAG Retriever API",
    description="REST API for hybrid semantic and keyword-based document retrieval with WebSocket chat",
    version="1.0.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
    lifespan=startup_event
)

class LazyCache(CacheBackend):
    """Lazy cache wrapper that defers to the global _cache variable.
    
    This allows middleware registration before _cache is initialized,
    with the middleware using the actual cache once it's available at startup.
    
    If _cache is None, this implementation is a no-op (fail-open principle).
    """

    def get(self, key: str) -> Optional[Any]:
        """Retrieve from cache if available."""
        if _cache is None:
            return None
        try:
            return _cache.get(key)
        except Exception as e:
            logger.warning(f"Cache get failed: {e}")
            return None

    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        """Store in cache if available."""
        if _cache is None:
            return
        try:
            _cache.set(key, value, ttl_seconds)
        except Exception as e:
            logger.warning(f"Cache set failed: {e}")

    def delete(self, key: str) -> None:
        """Delete from cache if available."""
        if _cache is None:
            return
        try:
            _cache.delete(key)
        except Exception as e:
            logger.warning(f"Cache delete failed: {e}")

    def clear(self) -> None:
        """Clear cache if available."""
        if _cache is None:
            return
        try:
            _cache.clear()
        except Exception as e:
            logger.warning(f"Cache clear failed: {e}")

    def stats(self) -> Dict[str, Any]:
        """Get stats from cache if available."""
        if _cache is None:
            return {
                "backend": "none",
                "hits": 0,
                "misses": 0,
                "size": 0,
                "max_size": 0,
                "ttl_seconds": 0,
            }
        try:
            return _cache.stats()
        except Exception as e:
            logger.warning(f"Cache stats failed: {e}")
            return {
                "backend": "error",
                "hits": 0,
                "misses": 0,
                "size": 0,
                "max_size": 0,
                "ttl_seconds": 0,
            }


# Create lazy cache wrapper for middleware
lazy_cache = LazyCache()


def _shared_retrieve_documents(
    query: str, enable_rerank: Optional[bool] = None
) -> List[Dict[str, Any]]:
    """Execute retrieval through one shared path for REST and WebSocket handlers."""
    if _retriever is None or _config is None:
        raise RetrieverNotInitializedError("Retriever not initialized")

    effective_enable_rerank = (
        _config.enable_rerank if enable_rerank is None else bool(enable_rerank)
    )
    normalized_query = " ".join(query.split())

    config_fingerprint_payload = {
        "semantic_top_k": _config.semantic_top_k,
        "keyword_top_k": _config.keyword_top_k,
        "final_top_k": _config.final_top_k,
        "semantic_weight": _config.semantic_weight,
        "keyword_weight": _config.keyword_weight,
        "enable_rerank": _config.enable_rerank,
        "pre_rerank_top_k": _config.pre_rerank_top_k,
    }
    config_fingerprint = hashlib.sha256(
        json.dumps(
            config_fingerprint_payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    shared_identity = {
        "query": normalized_query,
        "effective_enable_rerank": effective_enable_rerank,
        "config_fingerprint": config_fingerprint,
        "corpus_version": str(_cache_generation),
    }
    cache_key = "shared-retrieve:" + hashlib.sha256(
        json.dumps(
            shared_identity,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    if _cache is not None:
        try:
            cached_results = lazy_cache.get(cache_key)
            if isinstance(cached_results, list):
                return cached_results
        except Exception as e:
            logger.warning("Shared retrieval cache read failed: %s", e)

    results = _retriever.retrieve(query, enable_rerank=effective_enable_rerank)

    if _cache is not None:
        try:
            lazy_cache.set(cache_key, results)
        except Exception as e:
            logger.warning("Shared retrieval cache write failed: %s", e)

    return results


def _to_filtered_document_results(
    results: List[Dict[str, Any]], min_score_threshold: float
) -> List[DocumentResult]:
    """Filter retrieval results and convert them to API response models."""
    filtered_results = [r for r in results if float(r.get("score", 0.0)) >= min_score_threshold]
    logger.debug(
        "Filtered from %s to %s results (min_score=%s)",
        len(results),
        len(filtered_results),
        min_score_threshold,
    )
    return [
        DocumentResult(
            id=r["id"],
            text=r["text"],
            source=r["metadata"]["source"],
            score=float(r["score"]),
        )
        for r in filtered_results
    ]

# Add CORS middleware
allow_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:3001").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
logger.info(f"CORS enabled for origins: {allow_origins}")

# Register cache middleware BEFORE routes (important for ASGI chain order)
app.add_middleware(
    QueryCacheMiddleware,
    cache_backend=lazy_cache,
    excluded_paths=["/health", "/config", "/documents", "/cache/stats"],
)
logger.info("QueryCacheMiddleware registered with lazy cache wrapper")

@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["Health"],
    summary="Health check endpoint",
)
async def health_check() -> HealthResponse:
    """Check the health status of the retrieval service.

    Returns:
        HealthResponse with service status and retriever readiness.

    Example:
        GET /health
        Response: {"status": "healthy", "retriever_ready": "yes"}
    """
    is_ready = _retriever is not None
    return HealthResponse(
        status="healthy", retriever_ready="yes" if is_ready else "no"
    )


@app.post(
    "/retrieve",
    response_model=RetrievalResponse,
    tags=["Retrieval"],
    summary="Retrieve relevant documents",
)
async def retrieve(request: RetrievalRequest) -> RetrievalResponse:
    """Retrieve documents relevant to the provided query.

    Performs hybrid retrieval combining semantic and keyword search,
    with optional cross-encoder reranking.

    Args:
        request: RetrievalRequest with query and optional reranking setting.

    Returns:
        RetrievalResponse with relevant documents and scores.

    Raises:
        HTTPException: 503 if retriever not initialized, 500 if retrieval fails.

    Example:
        POST /retrieve
        {
            "query": "How do I use offline maps?",
            "enable_rerank": true
        }
    """
    if _retriever is None or _config is None:
        logger.error("Retriever not initialized")
        raise HTTPException(
            status_code=503,
            detail="Retriever service not initialized. Try again later.",
        )

    try:
        logger.info(f"Retrieval request: {request.query[:50]}...")

        results = _shared_retrieve_documents(
            request.query, enable_rerank=request.enable_rerank
        )
        doc_results = _to_filtered_document_results(
            results, min_score_threshold=0.80
        )

        logger.info(f"Retrieval complete: {len(doc_results)} results after filtering")
        return RetrievalResponse(
            query=request.query, results=doc_results, total_results=len(doc_results)
        )

    except RetrievalError as e:
        logger.error(f"Retrieval error: {e}")
        raise HTTPException(status_code=500, detail=f"Retrieval failed: {str(e)}")
    except RetrieverNotInitializedError as e:
        logger.error(f"Retriever not initialized: {e}")
        raise HTTPException(
            status_code=503,
            detail="Retriever service not initialized. Try again later.",
        )
    except Exception as e:
        logger.error(f"Unexpected error during retrieval: {e}")
        raise HTTPException(status_code=500, detail=f"Retrieval failed: {str(e)}")


@app.post(
    "/retrieve-filtered",
    response_model=RetrievalResponse,
    tags=["Retrieval"],
    summary="Retrieve documents with score filtering",
)
async def retrieve_filtered(
    request: RetrievalRequest, min_score: float = 0.5
) -> RetrievalResponse:
    """Retrieve documents with optional minimum score filtering.

    Similar to /retrieve but filters results by minimum relevance score.

    Args:
        request: RetrievalRequest with query and optional reranking setting.
        min_score: Minimum relevance score (0.0-1.0) for results. Defaults to 0.5.

    Returns:
        RetrievalResponse with filtered documents.

    Raises:
        HTTPException: 400 if min_score invalid, 503 if not initialized, 500 if fails.

    Example:
        POST /retrieve-filtered?min_score=0.8
        {
            "query": "How do I update maps?"
        }
    """
    if not 0.0 <= min_score <= 1.0:
        logger.warning(f"Invalid min_score: {min_score}")
        raise HTTPException(
            status_code=400, detail="min_score must be in range [0.0, 1.0]"
        )

    if _retriever is None or _config is None:
        logger.error("Retriever not initialized")
        raise HTTPException(
            status_code=503,
            detail="Retriever service not initialized. Try again later.",
        )

    try:
        logger.info(
            f"Filtered retrieval request: {request.query[:50]}... (min_score={min_score})"
        )

        results = _shared_retrieve_documents(
            request.query, enable_rerank=request.enable_rerank
        )

        # Filter results by minimum score, enforcing floor of 0.80 for chat quality
        effective_min_score = max(0.80, min_score)
        doc_results = _to_filtered_document_results(
            results, min_score_threshold=effective_min_score
        )

        logger.info(f"Filtered retrieval complete: {len(doc_results)} results after filtering")
        return RetrievalResponse(
            query=request.query, results=doc_results, total_results=len(doc_results)
        )

    except RetrievalError as e:
        logger.error(f"Retrieval error: {e}")
        raise HTTPException(status_code=500, detail=f"Retrieval failed: {str(e)}")
    except RetrieverNotInitializedError as e:
        logger.error(f"Retriever not initialized: {e}")
        raise HTTPException(
            status_code=503,
            detail="Retriever service not initialized. Try again later.",
        )
    except Exception as e:
        logger.error(f"Unexpected error during filtered retrieval: {e}")
        raise HTTPException(status_code=500, detail=f"Retrieval failed: {str(e)}")


@app.get(
    "/config",
    response_model=ConfigResponse,
    tags=["Configuration"],
    summary="Get retriever configuration",
)
async def get_config() -> ConfigResponse:
    """Get the current retriever configuration.

    Returns:
        ConfigResponse with all configuration parameters.

    Raises:
        HTTPException: 503 if retriever not initialized.

    Example:
        GET /config
        Response: {
            "semantic_top_k": 10,
            "keyword_top_k": 10,
            ...
        }
    """
    if _config is None:
        logger.error("Retriever not initialized")
        raise HTTPException(
            status_code=503,
            detail="Retriever not initialized. Try again later.",
        )

    return ConfigResponse(
        semantic_top_k=_config.semantic_top_k,
        keyword_top_k=_config.keyword_top_k,
        final_top_k=_config.final_top_k,
        semantic_weight=_config.semantic_weight,
        keyword_weight=_config.keyword_weight,
        enable_rerank=_config.enable_rerank,
        pre_rerank_top_k=_config.pre_rerank_top_k,
    )


@app.put(
    "/config",
    response_model=ConfigResponse,
    tags=["Configuration"],
    summary="Update retriever configuration",
)
async def update_config(request: ConfigUpdateRequest) -> ConfigResponse:
    """Update the retriever configuration with new values.

    Only provided fields are updated. Configuration updates are validated
    before being applied, ensuring semantic_weight + keyword_weight = 1.0
    and all parameters are within valid ranges.

    Args:
        request: ConfigUpdateRequest with fields to update (all optional).

    Returns:
        ConfigResponse with the updated configuration.

    Raises:
        HTTPException: 400 if validation fails, 503 if not initialized.

    Example:
        PUT /config
        {
            "semantic_weight": 0.8,
            "keyword_weight": 0.2
        }
        Response: {
            "semantic_top_k": 10,
            "semantic_weight": 0.8,
            "keyword_weight": 0.2,
            ...
        }
    """
    global _config, _cache_generation

    if _config is None:
        logger.error("Retriever not initialized")
        raise HTTPException(
            status_code=503,
            detail="Retriever not initialized. Try again later.",
        )

    try:
        # Extract only provided fields
        update_dict = request.model_dump(exclude_unset=True)

        if not update_dict:
            logger.debug("No configuration updates provided")
            return ConfigResponse(
                semantic_top_k=_config.semantic_top_k,
                keyword_top_k=_config.keyword_top_k,
                final_top_k=_config.final_top_k,
                semantic_weight=_config.semantic_weight,
                keyword_weight=_config.keyword_weight,
                enable_rerank=_config.enable_rerank,
                pre_rerank_top_k=_config.pre_rerank_top_k,
            )

        logger.info(f"Updating configuration with: {update_dict}")

        # Create updated configuration (validates automatically in __post_init__)
        _config = _config.update(**update_dict)

        # Clear cache to invalidate all L1 entries (ADR-006 - Fix for blocking issue #1)
        # This ensures the new configuration is used for subsequent queries
        _cache_generation += 1
        if _cache is not None:
            try:
                lazy_cache.clear()  # Use lazy_cache to defer to global _cache
                logger.info("Config updated; cache cleared")
            except Exception as e:
                logger.warning(f"Failed to clear cache after config update: {e}")
        else:
            logger.debug("Config updated; cache not initialized")

        logger.info("Configuration updated successfully")
        return ConfigResponse(
            semantic_top_k=_config.semantic_top_k,
            keyword_top_k=_config.keyword_top_k,
            final_top_k=_config.final_top_k,
            semantic_weight=_config.semantic_weight,
            keyword_weight=_config.keyword_weight,
            enable_rerank=_config.enable_rerank,
            pre_rerank_top_k=_config.pre_rerank_top_k,
        )

    except ValueError as e:
        logger.warning(f"Configuration validation failed: {e}")
        raise HTTPException(
            status_code=400,
            detail=f"Configuration validation failed: {str(e)}",
        )
    except TypeError as e:
        logger.warning(f"Invalid configuration parameter: {e}")
        raise HTTPException(
            status_code=400,
            detail=f"Invalid configuration parameter: {str(e)}",
        )
    except Exception as e:
        logger.error(f"Configuration update failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Configuration update failed: {str(e)}",
        )


@app.get(
    "/cache/stats",
    response_model=CacheStatsResponse,
    tags=["Cache"],
    summary="Get cache statistics",
)
async def get_cache_stats() -> CacheStatsResponse:
    """Get cache statistics for monitoring and debugging.

    Returns detailed statistics about the cache backend including hit rate,
    current size, and configuration. Implements fail-open principle: never fails,
    always returns 200 with best-effort stats.

    The endpoint is useful for:
    - Monitoring cache performance (hit rate, hit/miss counts)
    - Debugging cache behavior
    - Verifying cache configuration (backend type, TTL, capacity)
    - Tracking cache usage patterns

    Returns:
        CacheStatsResponse with complete cache statistics.
        If cache is not initialized or errors occur, returns zero stats.

    Example:
        GET /cache/stats
        Response: {
            "backend": "memory",
            "hits": 1500,
            "misses": 350,
            "hit_rate": 0.811,
            "size": 125,
            "max_size": 10000,
            "ttl_seconds": 3600,
            "timestamp": "2026-04-20T14:30:45.123456"
        }
    """
    # Fix for blocking issue #2: Always return 200 with stats (fail-open principle)
    try:
        if _cache is None:
            # Cache not initialized, return zero stats
            return CacheStatsResponse(
                backend="none",
                hits=0,
                misses=0,
                hit_rate=0.0,
                size=0,
                max_size=0,
                ttl_seconds=0,
                timestamp=datetime.now(timezone.utc),
            )

        # Get stats from cache
        stats = lazy_cache.stats()

        # Calculate hit rate
        hits = stats.get("hits", 0)
        misses = stats.get("misses", 0)
        total = hits + misses
        hit_rate = (hits / total) if total > 0 else 0.0

        logger.debug(
            f"Cache stats retrieved: backend={stats.get('backend')}, "
            f"hits={hits}, misses={misses}, hit_rate={hit_rate:.2%}"
        )

        return CacheStatsResponse(
            backend=stats.get("backend", "unknown"),
            hits=hits,
            misses=misses,
            hit_rate=hit_rate,
            size=stats.get("size", 0),
            max_size=stats.get("max_size", 0),
            ttl_seconds=stats.get("ttl_seconds", 0),
            timestamp=datetime.now(timezone.utc),
        )

    except Exception as e:
        # Fail-open: always return 200 even on error
        logger.warning(f"Error retrieving cache stats: {e}")
        return CacheStatsResponse(
            backend="error",
            hits=0,
            misses=0,
            hit_rate=0.0,
            size=0,
            max_size=0,
            ttl_seconds=0,
            timestamp=datetime.now(timezone.utc),
        )


# WebSocket endpoint for real-time chat
@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time document queries.

    Client sends: {"query": str, "enable_rerank": bool?}
    Server sends (in sequence):
      - {"type": "status", "message": str}
      - {"type": "results", "query": str, "results": [...], "total_results": int}
      - {"type": "error", "message": str} (on failure)
    """
    await websocket.accept()
    logger.info("WebSocket client connected")

    try:
        while True:
            # Receive query from client
            data = await websocket.receive_json()
            query = data.get("query", "").strip()
            enable_rerank = data.get("enable_rerank")

            # Validate query
            if not query or len(query) < 1 or len(query) > 500:
                error_msg = WsErrorMessage(
                    message="Query must be between 1 and 500 characters"
                )
                await websocket.send_json(error_msg.model_dump())
                continue

            if _retriever is None or _config is None:
                error_msg = WsErrorMessage(message="Retriever not initialized")
                await websocket.send_json(error_msg.model_dump())
                continue

            try:
                # Send initial status
                status_msg = WsStatusMessage(message="Retrieving documents...")
                await websocket.send_json(status_msg.model_dump())

                results = _shared_retrieve_documents(
                    query, enable_rerank=enable_rerank
                )
                doc_results = _to_filtered_document_results(
                    results, min_score_threshold=0.80
                )

                # Send results (total_results reflects post-filter count)
                results_msg = WsResultsMessage(
                    query=query, results=doc_results, total_results=len(doc_results)
                )
                await websocket.send_json(results_msg.model_dump())
                logger.info(f"WebSocket query succeeded: {query[:50]}... ({len(doc_results)} results after filtering)")

            except RetrievalError as e:
                logger.error(f"WebSocket retrieval error: {e}")
                error_msg = WsErrorMessage(message=f"Retrieval failed: {str(e)}")
                await websocket.send_json(error_msg.model_dump())
            except Exception as e:
                logger.error(f"WebSocket unexpected error: {e}")
                error_msg = WsErrorMessage(message="An unexpected error occurred")
                await websocket.send_json(error_msg.model_dump())

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            error_msg = WsErrorMessage(message="Connection error")
            await websocket.send_json(error_msg.model_dump())
        except Exception:
            pass


def _extract_text_from_file(filename: str, content_bytes: bytes) -> str:
    """Extract text from various file formats."""
    filename_lower = filename.lower()

    if filename_lower.endswith(".txt"):
        return content_bytes.decode("utf-8", errors="ignore")
    elif filename_lower.endswith(".md"):
        return content_bytes.decode("utf-8", errors="ignore")
    elif filename_lower.endswith(".pdf"):
        if not with_pdf_support:
            raise ValueError(
                "PDF support not available. Install pypdf: pip install pypdf"
            )
        try:
            pdf_file = io.BytesIO(content_bytes)
            reader = pypdf.PdfReader(pdf_file)
            text_parts = []
            for page in reader.pages:
                text_parts.append(page.extract_text())
            return "\n".join(text_parts)
        except Exception as e:
            raise ValueError(f"Failed to extract PDF text: {str(e)}")
    else:
        raise ValueError(
            f"Unsupported file format: {filename}. Supported: .txt, .md, .pdf"
        )


@app.post(
    "/documents",
    response_model=DocumentIngestionResponse,
    tags=["Documents"],
    summary="Add custom documents",
)
async def add_documents(request: DocumentIngestionRequest) -> DocumentIngestionResponse:
    """Add custom documents to the retrieval system.

    Supports three types of document sources:
    - text: Raw text content (paste directly)
    - url: URL to fetch content from
    - file: Base64-encoded file (txt, md, pdf)

    Args:
        request: DocumentIngestionRequest with source type, content, and optional label.

    Returns:
        DocumentIngestionResponse with status and document/chunk counts.

    Raises:
        HTTPException: 400 on validation error, 503 if retriever not initialized, 500 on failure.
    """
    global _cache_generation

    if _retriever is None or _config is None:
        logger.error("Retriever not initialized")
        raise HTTPException(
            status_code=503,
            detail="Retriever service not initialized. Try again later.",
        )

    try:
        text_content = ""
        source_label = request.source_label or request.source_type

        # Log ingest type (ADR-003 - Fix for blocking issue #3)
        logger.info(f"Ingest type: {request.ingest_type}; cache {'will be cleared' if request.ingest_type == 'update' else 'will be preserved'}")

        if request.source_type == "text":
            text_content = request.content
            logger.info(f"Ingesting text document: {source_label}")

        elif request.source_type == "url":
            logger.info(f"Fetching content from URL: {request.content}")
            try:
                response = requests.get(request.content, timeout=10)
                response.raise_for_status()
                text_content = response.text
                source_label = request.source_label or request.content
            except requests.RequestException as e:
                logger.error(f"Failed to fetch URL: {e}")
                raise HTTPException(
                    status_code=400, detail=f"Failed to fetch URL: {str(e)}"
                )

        elif request.source_type == "file":
            # Decode base64
            try:
                file_bytes = base64.b64decode(request.content)
            except Exception as e:
                logger.error(f"Failed to decode base64: {e}")
                raise HTTPException(
                    status_code=400, detail="Invalid base64 encoding"
                )

            if not request.filename:
                raise HTTPException(
                    status_code=400, detail="filename required for file uploads"
                )

            # Extract text from file
            try:
                text_content = _extract_text_from_file(request.filename, file_bytes)
                logger.info(f"Extracted text from file: {request.filename}")
            except ValueError as e:
                logger.error(f"Failed to extract file content: {e}")
                raise HTTPException(status_code=400, detail=str(e))

        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported source_type: {request.source_type}",
            )

        # Chunk the text content
        chunks = chunk_text(text_content, chunk_size=500, chunk_overlap=50)
        if not chunks:
            raise HTTPException(
                status_code=400, detail="No content to chunk from source"
            )

        logger.info(f"Created {len(chunks)} chunks from source: {source_label}")

        # Add chunks to vector database collection
        try:
            # Use the collection from the global retriever
            collection = _retriever._collection if hasattr(_retriever, "_collection") else _retriever.collection
            if not collection:
                raise HTTPException(
                    status_code=500, detail="Vector database collection not accessible"
                )

            # Prepare documents for ChromaDB
            doc_ids = [f"{source_label}_{i}" for i in range(len(chunks))]
            metadatas = [
                {"source": source_label, "chunk_index": i} for i in range(len(chunks))
            ]

            # Add to collection
            collection.add(
                ids=doc_ids,
                documents=chunks,
                metadatas=metadatas,
            )
            logger.info(
                f"Added {len(chunks)} chunks to collection from source: {source_label}"
            )

            # Conditional cache clear based on ingest_type (ADR-003 - Fix for blocking issue #3)
            # - 'update': Clear cache to ensure new documents are retrieved
            # - 'add': Preserve cache for bulk additions
            if request.ingest_type == "update":
                _cache_generation += 1
                if _cache is not None:
                    try:
                        lazy_cache.clear()
                        logger.info(f"Ingest complete (type='update'); cache cleared")
                    except Exception as e:
                        logger.warning(f"Failed to clear cache after ingest: {e}")
                else:
                    logger.debug("Ingest complete (type='update'); cache not initialized")
            else:  # ingest_type == 'add'
                logger.info(f"Ingest complete (type='add'); cache preserved")

            return DocumentIngestionResponse(
                status="success",
                documents_added=1,
                chunks_created=len(chunks),
                message=f"Successfully ingested {len(chunks)} chunks from {source_label}",
            )

        except Exception as e:
            logger.error(f"Failed to add documents to collection: {e}")
            raise HTTPException(
                status_code=500, detail=f"Failed to add documents: {str(e)}"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error during document ingestion: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Document ingestion failed: {str(e)}",
        )


@app.get(
    "/documents/sources",
    response_model=SourcesResponse,
    tags=["Documents"],
    summary="List document sources",
)
async def get_document_sources() -> SourcesResponse:
    """Get list of all document sources in the retrieval system.

    Returns:
        SourcesResponse with list of sources and chunk counts.

    Raises:
        HTTPException: 503 if retriever not initialized, 500 on failure.
    """
    if _retriever is None:
        logger.error("Retriever not initialized")
        raise HTTPException(
            status_code=503,
            detail="Retriever service not initialized. Try again later.",
        )

    try:
        collection = _retriever._collection if hasattr(_retriever, "_collection") else _retriever.collection
        if not collection:
            raise HTTPException(
                status_code=500, detail="Vector database collection not accessible"
            )

        # Get all documents and count by source
        all_docs = collection.get()
        source_counts: dict[str, int] = {}

        if all_docs and all_docs["metadatas"]:
            for metadata in all_docs["metadatas"]:
                source = metadata.get("source", "unknown")
                source_counts[source] = source_counts.get(source, 0) + 1

        sources = [
            DocumentSource(source=src, count=count)
            for src, count in sorted(source_counts.items())
        ]

        logger.info(f"Retrieved {len(sources)} document sources")
        return SourcesResponse(sources=sources)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to retrieve document sources: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve sources: {str(e)}",
        )


# Application info endpoints
@app.get("/", tags=["Info"], summary="API information")
async def root() -> dict:
    """Root endpoint with API information."""
    return {
        "name": "Hybrid RAG Retriever API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
        "websocket": "/ws/chat",
    }


if __name__ == "__main__":
    import uvicorn

    logger.info("🚀 Starting Hybrid RAG Retriever API...")
    logger.info("📖 Swagger UI: http://localhost:8000/docs")
    logger.info("📋 ReDoc: http://localhost:8000/redoc")
    logger.info("🔧 Health Check: http://localhost:8000/health")
    logger.info("💬 WebSocket Chat: ws://localhost:8000/ws/chat")

    uvicorn.run(app, host="0.0.0.0", port=8000)
