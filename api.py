"""FastAPI REST API for Hybrid RAG Retrieval Service.

This module provides a production-ready REST API for the hybrid RAG library,
including health checks, retrieval endpoints, configuration management,
document ingestion, and WebSocket-based chat.

CACHING ARCHITECTURE:
    L1 WebSocket Cache: The /ws/chat endpoint is the sole retrieval path; results
        are cached by the shared retrieval handler (_shared_retrieve_documents).
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
import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional
from html.parser import HTMLParser
from urllib.parse import urlparse
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
    CACHE_TELEMETRY_LABELS,
    KNOWLEDGE_DB_DIRECTORY,
    list_existing_collections,
    is_valid_collection_name,
)
from hybrid_rag.cache import CacheBackend
from hybrid_rag.config import CacheSettings, create_cache_backend

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
# Authoritative corpus version token for cache keying.
# Derived from _cache_generation (explicit invalidation events) combined with the
# live collection count (DB-grounded document count). This replaces the old approach
# of using str(_cache_generation) directly, which was process-local and lost its
# meaning after a restart.  See OPTB-007 for full rationale.
_corpus_version: str = "0"

# OPTB-012: Track the last known fallback state so we can log transitions
# (False → True = activation, True → False = deactivation) without flooding
# the log stream with repeated messages while the state is stable.
_last_fallback_state: Optional[bool] = None

# Pydantic models for request/response validation
class DocumentResult(BaseModel):
    """Model representing a single retrieved document."""

    id: str = Field(..., description="Document identifier")
    text: str = Field(..., description="Document text content")
    source: str = Field(..., description="Document source label or URL")
    source_url: Optional[str] = Field(None, description="Original URL when source has a custom label")
    score: float = Field(..., description="Relevance score (may be negative due to fusion/reranking)")


class ConfigResponse(BaseModel):
    """Response model for configuration endpoint."""

    semantic_top_k: int
    keyword_top_k: int
    final_top_k: int
    semantic_weight: float
    keyword_weight: float
    enable_rerank: bool
    pre_rerank_top_k: int
    collection_name: str


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
    collection_name: Optional[str] = Field(
        None, min_length=6, max_length=20, description="ChromaDB collection name (6-20 chars, alphanumeric/underscore/hyphen)"
    )


class CollectionsResponse(BaseModel):
    """Response model for listing ChromaDB collections."""

    collections: List[str] = Field(..., description="List of existing collection names")


class DocumentIngestionRequest(BaseModel):
    """Request model for adding custom documents.

    Attributes:
        source_type: Type of data source: 'text', 'url', or 'file'.
        content: Text content, URL, or base64-encoded file.
        filename: Original filename for file uploads.
        source_label: User-friendly label for the data source.
        ingest_type: Optional override for the ingest operation type.
            When omitted (the default), the backend derives whether this is an
            'add' (new source) or 'update' (existing source) by querying the
            vector collection.  Providing this field explicitly bypasses the
            derivation and honours the caller's intent:
            - 'add': treat as new source, preserve existing cache entries.
            - 'update': treat as a re-ingest, delete stale chunks and clear cache.
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
        description=(
            "Ingest type override.  Omit to let the backend derive add/update from "
            "the collection state.  Provide explicitly to force a specific path."
        ),
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

    sources: list[DocumentSource] = Field(
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


# ---------------------------------------------------------------------------
# OPTB-008: Layered cache stats schema
# WHY: The flat CacheStatsResponse mixes L1 counters, L2 embedding stats,
# and backend health into a single level, making it hard for operators to
# distinguish which cache layer is healthy/unhealthy.  The layered schema
# separates concerns into three named sections so monitoring dashboards and
# alerting rules can target the exact section that matters.
# ---------------------------------------------------------------------------

class L1QueryCacheStats(BaseModel):
    """Statistics for the L1 query-response cache (ASGI middleware layer).

    WHY 'corpus_version': The corpus version token controls cache key
    namespacing.  Exposing it here lets operators quickly verify that
    invalidation events (add/update ingest, config changes) have propagated
    and that stale entries cannot be served under the new version.

    Attributes:
        backend: Backend identifier ('memory' or 'redis').
        hits: Total cache hits since last reset.
        misses: Total cache misses since last reset.
        hit_rate: Fraction of accesses that were hits (0.0–1.0).
        size: Current number of entries in the L1 cache.
        max_size: Configured maximum capacity of the L1 cache.
        ttl_seconds: Configured TTL for L1 entries.
        corpus_version: The active corpus version token used in cache keys.

    Example:
        >>> l1 = L1QueryCacheStats(
        ...     backend="memory", hits=500, misses=100, hit_rate=0.833,
        ...     size=50, max_size=1000, ttl_seconds=600,
        ...     corpus_version="gen2.n108"
        ... )
    """

    backend: str = Field(..., description="Cache backend ('memory' or 'redis')")
    hits: int = Field(..., ge=0, description="Total L1 cache hits")
    misses: int = Field(..., ge=0, description="Total L1 cache misses")
    hit_rate: float = Field(..., ge=0.0, le=1.0, description="L1 hit rate (0.0–1.0)")
    size: int = Field(..., ge=0, description="Current L1 cache size in entries")
    max_size: int = Field(..., ge=0, description="L1 maximum capacity")
    ttl_seconds: int = Field(..., ge=0, description="L1 configured TTL in seconds")
    corpus_version: str = Field(
        ..., description="Active corpus version token controlling cache key namespace"
    )


class L2EmbeddingCacheStats(BaseModel):
    """Statistics for the L2 embedding LRU cache (inside HybridRetriever).

    WHY: L2 caches sentence-transformer embeddings to avoid redundant model
    inference on repeated or similar queries.  Monitoring capacity vs. size
    reveals when the LRU is evicting aggressively (cache too small).

    Attributes:
        hits: Total embedding cache hits since retriever init.
        misses: Total embedding cache misses since retriever init.
        hit_rate: Fraction of embedding lookups served from cache (0.0–1.0).
        size: Number of embeddings currently held in the LRU.
        capacity: Maximum number of embeddings the LRU can hold.

    Example:
        >>> l2 = L2EmbeddingCacheStats(
        ...     hits=1200, misses=200, hit_rate=0.857, size=300, capacity=5000
        ... )
    """

    hits: int = Field(..., ge=0, description="Total L2 embedding cache hits")
    misses: int = Field(..., ge=0, description="Total L2 embedding cache misses")
    hit_rate: float = Field(..., ge=0.0, le=1.0, description="L2 hit rate (0.0–1.0)")
    size: int = Field(..., ge=0, description="Number of embeddings currently cached")
    capacity: int = Field(..., ge=0, description="Maximum L2 LRU cache capacity")


class BackendHealthStats(BaseModel):
    """Connectivity and health report for the cache backend.

    WHY: For Redis deployments, monitoring dashboards need to distinguish
    between 'cache miss' (normal) and 'Redis unreachable, serving without
    cache' (incident).  'fallback_active' provides this binary signal.
    'latency_ms' lets SLO dashboards alert on degraded-but-connected Redis.

    Attributes:
        connected: True when the backend is currently reachable.
        latency_ms: Round-trip ping latency in ms, or None for in-memory.
        fallback_active: True when operating without the intended backend.
        error: Last error string if unhealthy, else None.

    Example:
        >>> healthy = BackendHealthStats(
        ...     connected=True, latency_ms=0.8, fallback_active=False, error=None
        ... )
        >>> degraded = BackendHealthStats(
        ...     connected=False, latency_ms=None, fallback_active=True,
        ...     error="Connection refused"
        ... )
    """

    connected: bool = Field(..., description="True when backend is reachable")
    latency_ms: Optional[float] = Field(
        None, description="Ping round-trip latency in ms (None for in-memory backends)"
    )
    fallback_active: bool = Field(
        ..., description="True when operating without the intended backend"
    )
    error: Optional[str] = Field(
        None, description="Last error message if unhealthy, else None"
    )


class LayeredCacheStatsResponse(BaseModel):
    """Layered cache statistics response with three distinct sections.

    WHY (OPTB-008): The flat CacheStatsResponse collapses L1, L2, and health
    info into one level, making it impossible to route specific alerts (e.g.
    'L2 hit rate < 40%') without knowing which keys belong to which layer.
    The layered schema gives consumers an unambiguous contract.

    All L1 metrics (hits, misses, hit_rate, size, backend, etc.) are accessed
    via l1_query_cache.  The deprecated top-level mirrors were removed; clients
    must use the nested paths.

    Attributes:
        l1_query_cache: L1 query-response cache metrics + corpus_version.
        l2_embedding_cache: L2 embedding LRU cache metrics from HybridRetriever.
        backend_health: Redis/memory backend connectivity and latency.
        timestamp: When these statistics were captured (UTC).

    Example:
        >>> response = LayeredCacheStatsResponse(
        ...     l1_query_cache=L1QueryCacheStats(...),
        ...     l2_embedding_cache=L2EmbeddingCacheStats(...),
        ...     backend_health=BackendHealthStats(...),
        ...     timestamp=datetime.now(timezone.utc),
        ... )
    """

    l1_query_cache: L1QueryCacheStats = Field(
        ..., description="L1 query-response cache statistics"
    )
    l2_embedding_cache: L2EmbeddingCacheStats = Field(
        ..., description="L2 embedding LRU cache statistics from HybridRetriever"
    )
    backend_health: BackendHealthStats = Field(
        ..., description="Cache backend connectivity and health"
    )
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
    """WebSocket results message sent by server.

    T03 WS cache-status contract: the ``cache_status`` field carries
    the retrieval-layer cache outcome (HIT / MISS / ERROR).  The field uses
    the retrieval-layer signal (``cache.retrieval_*``) rather than the
    HTTP-middleware signal (``cache.http_*``) because WebSocket traffic
    bypasses the middleware.
    """

    type: Literal["results"] = "results"
    query: str = Field(..., description="Original query")
    results: list[DocumentResult] = Field(..., description="Retrieved documents")
    total_results: int = Field(..., description="Total number of results")
    cache_status: Literal["HIT", "MISS", "ERROR"] = Field(
        "MISS",
        description=(
            "T03 WS cache-status contract: retrieval-layer cache outcome. "
            "HIT = served from cache; MISS = cache bypassed; ERROR = cache fault."
        ),
    )


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
    global _retriever, _config, _corpus_version

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
        collection = initialize_vector_db(
            documents,
            persist_dir=KNOWLEDGE_DB_DIRECTORY,
            collection_name=_config.collection_name,
        )

        # Create retriever
        _retriever = HybridRetriever(collection, _config)
        logger.info("✓ Hybrid retriever initialized successfully")

        # Build the authoritative corpus_version token now that _retriever is live.
        # This grounds the token in the actual collection count (DB-grounded)
        # so it stays meaningful after process restarts with the same data.
        _corpus_version = _build_corpus_version_token()
        logger.info("Corpus version token initialized: %s", _corpus_version)

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

    def stats(self) -> dict[str, Any]:
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

    def health(self) -> dict[str, Any]:
        """Proxy health() to the underlying cache backend.

        WHY (OPTB-008): The get_cache_stats endpoint calls lazy_cache.health()
        rather than _cache.health() directly so it benefits from the same
        lazy-initialisation pattern already used for get/set/stats.  When no
        backend is available this returns a degraded sentinel rather than
        raising AttributeError.
        """
        if _cache is None:
            # No backend — signal degraded state without raising.
            return {
                "connected": False,
                "latency_ms": None,
                "fallback_active": True,
                "error": None,
            }
        try:
            return _cache.health()
        except Exception as exc:
            logger.warning("Cache health check failed: %s", exc)
            return {
                "connected": False,
                "latency_ms": None,
                "fallback_active": True,
                "error": str(exc),
            }


# Create lazy cache wrapper for middleware
lazy_cache = LazyCache()


def _build_corpus_version_token() -> str:
    """Build an authoritative corpus version token combining generation counter with live collection count.

    This replaces the direct process-local _cache_generation usage in cache key
    composition. The token is sourced from the retriever's collection count (DB-grounded)
    combined with the monotonic generation counter (explicit invalidation events).

    By grounding the token in the actual collection count we get two desirable
    properties:
      1. Stability across equivalent states — two processes that load the same corpus
         produce the same token, so a warm-restart does not flush a usable cache.
      2. Automatic invalidation on ingest — every document addition changes the count,
         so the token changes even without an explicit _cache_generation bump.

    Returns:
        A string token like "gen0.n42" that encodes both generation and corpus size.
        Falls back to "gen{N}.n0" if the retriever/collection is unavailable, preserving
        the consistent token format for reliable log parsing and key-space analysis.
    """
    if _retriever is not None:
        try:
            count = _retriever.collection.count()
            return f"gen{_cache_generation}.n{count}"
        except Exception as exc:
            # Warning (not debug): failure to read collection count is a degraded state
            # that may indicate a connectivity or attribute problem with the retriever.
            logger.warning("Could not read collection count for corpus_version: %s", exc)
    # Keep the same "gen{N}.n{count}" format even in the fallback so that log
    # parsers and cache key analysis tooling never encounter an unexpected shape.
    return f"gen{_cache_generation}.n0"


def _log_fallback_transition(current_fallback_active: bool) -> None:
    """Emit a structured log on fallback state transitions and update the tracker.

    OPTB-012: The module-level ``_last_fallback_state`` is compared against
    ``current_fallback_active`` on every health-check poll.  A log is emitted
    only when the state flips, preventing alert fatigue from repeated events
    while the backend remains degraded (or healthy).

    The pattern implemented here is "edge-triggered logging" (log on state
    change only) rather than "level-triggered logging" (log on every poll
    while degraded).  Edge-triggered logs are far less noisy in production
    and make alert rules simpler to write.

    Multi-process note: ``_last_fallback_state`` is process-local.  Under a
    multi-worker uvicorn deployment each process tracks its own state
    independently, so a backend status change will produce one transition log
    per worker on the first health-check poll after the change.  This is
    acceptable: operators will see N logs (N = worker count) per transition,
    not one global log.  Single-worker deployments (the default) are unaffected.

    Args:
        current_fallback_active: The fallback_active value from the latest
            backend health check result.
    """
    # The `global` declaration is required to rebind the module-level name
    # rather than creating a local variable with the same name.  Without it,
    # the assignment `_last_fallback_state = ...` below would create a new
    # local variable and the module-level value would remain unchanged.
    global _last_fallback_state

    if _last_fallback_state == current_fallback_active:
        # State unchanged — no transition to log.
        # On the very first call _last_fallback_state is None; None != True and
        # None != False, so the first poll always produces a transition log.
        return

    if current_fallback_active:
        # Transition False → True (or first poll, degraded): backend just failed.
        # WARNING level is appropriate because this signals a degraded mode that
        # operators should investigate, even if requests still succeed (fail-open).
        logger.warning(
            "%s: cache backend is unreachable;"
            " serving requests without L1 cache",
            CACHE_TELEMETRY_LABELS["fallback_activated"],
        )
    else:
        # Transition True → False: backend recovered.
        # INFO level is appropriate for a recovery event — it is noteworthy
        # but not an actionable problem.
        logger.info(
            "%s: cache backend is reachable again;"
            " L1 cache is active",
            CACHE_TELEMETRY_LABELS["fallback_deactivated"],
        )

    # Persist the new state so the next poll can detect the NEXT transition.
    _last_fallback_state = current_fallback_active


def _shared_retrieve_documents(
    query: str,
    enable_rerank: Optional[bool] = None,
    correlation_id: Optional[str] = None,
    _out_cache_status: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    """Execute retrieval through one shared path for REST and WebSocket handlers.

    Args:
        query: The search query string.
        enable_rerank: Override for reranking; None means use config default.
        correlation_id: Per-request tracing identifier used in cache hit/miss
            log records (OPTB-012).  Auto-generated as a UUID if None.
        _out_cache_status: Optional mutable list.  When provided, the function
            appends the retrieval-layer cache outcome as its first element:
            ``"HIT"``, ``"MISS"``, or ``"ERROR"``.  Exactly one element is
            always appended (including the ``_cache is None`` case, which
            produces ``"MISS"`` because the retriever is always invoked).
            Callers that need the cache status (e.g. the WS handler
            implementing the T03 payload-field contract) pass an **empty**
            ``[]`` here and read ``_out_cache_status[0]`` after the call.
            The list must be empty when passed.  REST callers that do not
            need the status omit this argument; their behaviour is unchanged.
    """
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
        # Use the authoritative corpus_version token instead of the raw
        # process-local _cache_generation integer.  _corpus_version encodes both
        # the explicit invalidation generation counter AND the live collection count,
        # so the key changes on both config updates and corpus mutations.
        # Note: for ingest_type='add' only the count dimension changes (generation
        # is not bumped), making existing cached queries for untouched topics still
        # valid while new queries see the grown corpus.
        "corpus_version": _corpus_version,
    }
    cache_key = "shared-retrieve:" + hashlib.sha256(
        json.dumps(
            shared_identity,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    # OPTB-012: Resolve correlation ID — use the caller-supplied value or
    # auto-generate a UUID so every log record is traceable even when the
    # caller does not supply a correlation header.
    effective_correlation_id = correlation_id or str(uuid.uuid4())

    if _cache is not None:
        try:
            cached_results = lazy_cache.get(cache_key)
            if isinstance(cached_results, list):
                # OPTB-012: Structured hit telemetry — `cache.retrieval_hit` identifies
                # this as the retrieval-layer cache, distinct from the HTTP-layer
                # `cache.http_hit` emitted by the middleware, so each layer can be
                # alerted and counted independently.
                logger.info(
                    "%s correlation_id=%s corpus_version=%s",
                    CACHE_TELEMETRY_LABELS["retrieval_hit"],
                    effective_correlation_id,
                    _corpus_version,
                )
                if _out_cache_status is not None:
                    _out_cache_status.append("HIT")
                return cached_results
            if cached_results is None:
                # OPTB-012: Structured miss telemetry — `cache.retrieval_miss` identifies the
                # retrieval layer and records corpus_version so operators can distinguish
                # expected post-invalidation misses from unexpected misses on a stable corpus.
                # Guard: only emitted when the cache read succeeds and returns no value;
                # cache read failures are tracked separately via `cache.retrieval_error`.
                logger.info(
                    "%s correlation_id=%s corpus_version=%s",
                    CACHE_TELEMETRY_LABELS["retrieval_miss"],
                    effective_correlation_id,
                    _corpus_version,
                )
                if _out_cache_status is not None:
                    _out_cache_status.append("MISS")
        except Exception as e:
            logger.warning("Shared retrieval cache read failed: %s", e)
            logger.info(
                "%s correlation_id=%s corpus_version=%s",
                CACHE_TELEMETRY_LABELS["retrieval_error"],
                effective_correlation_id,
                _corpus_version,
            )
            if _out_cache_status is not None:
                _out_cache_status.append("ERROR")
    else:
        # No cache backend available — retriever will always be invoked.
        # Emit MISS so callers always receive exactly one status element.
        if _out_cache_status is not None:
            _out_cache_status.append("MISS")
    results = _retriever.retrieve(query, enable_rerank=effective_enable_rerank)

    if _cache is not None:
        try:
            lazy_cache.set(cache_key, results)
        except Exception as e:
            logger.warning("Shared retrieval cache write failed: %s", e)

    return results


def _to_filtered_document_results(
    results: list[dict[str, Any]], min_score_threshold: float
) -> list[DocumentResult]:
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
            source_url=r["metadata"].get("source_url"),
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
        collection_name=_config.collection_name,
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
    global _config, _cache_generation, _corpus_version, _retriever

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
                collection_name=_config.collection_name,
            )

        logger.info(f"Updating configuration with: {update_dict}")

        # If collection_name is changing, validate it before applying
        new_collection_name = update_dict.get("collection_name")
        collection_changed = (
            new_collection_name is not None
            and new_collection_name != _config.collection_name
        )
        if new_collection_name is not None and not is_valid_collection_name(new_collection_name):
            raise ValueError(
                f"Invalid collection name '{new_collection_name}': must be 6-20 chars, "
                "alphanumeric/underscore/hyphen only"
            )

        # Create updated configuration (validates automatically in __post_init__)
        _config = _config.update(**update_dict)

        # Re-initialize vector database when collection_name changes
        if collection_changed:
            logger.info(f"Collection name changed to '{_config.collection_name}', re-initializing vector DB")
            documents = get_sample_documents()
            new_collection = initialize_vector_db(
                documents,
                persist_dir=KNOWLEDGE_DB_DIRECTORY,
                collection_name=_config.collection_name,
            )
            _retriever = HybridRetriever(new_collection, _config)
            logger.info("✓ Retriever re-initialized with new collection")

        # Clear cache to invalidate all L1 entries (ADR-006 - Fix for blocking issue #1)
        # This ensures the new configuration is used for subsequent queries
        prev_version = _corpus_version
        _cache_generation += 1
        # Rebuild the authoritative corpus_version token now that the generation
        # counter has been bumped.  This propagates the config-change invalidation
        # into every future cache key without needing to clear the store.
        _corpus_version = _build_corpus_version_token()
        # OPTB-012: Structured invalidation log — records the version transition
        # so operators can correlate config changes with cache miss spikes.
        logger.info(
            "cache.invalidation event=config_change prev_version=%s new_version=%s",
            prev_version,
            _corpus_version,
        )
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
            collection_name=_config.collection_name,
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
    "/collections",
    response_model=CollectionsResponse,
    tags=["Configuration"],
    summary="List existing ChromaDB collections",
)
async def get_collections() -> CollectionsResponse:
    """List all ChromaDB collections in the knowledge database directory.

    Returns:
        CollectionsResponse containing a list of collection name strings.

    Raises:
        HTTPException: 503 if the knowledge database cannot be accessed.

    Example:
        GET /collections
        Response: {"collections": ["hybrid_rag_collection", "my_docs"]}
    """
    try:
        names = list_existing_collections(KNOWLEDGE_DB_DIRECTORY)
        return CollectionsResponse(collections=names)
    except VectorDBError as e:
        logger.error(f"Failed to list collections: {e}")
        raise HTTPException(
            status_code=503,
            detail=f"Failed to list collections: {str(e)}",
        )


@app.get(
    "/cache/stats",
    response_model=LayeredCacheStatsResponse,
    tags=["Cache"],
    summary="Get layered cache statistics",
)
async def get_cache_stats() -> LayeredCacheStatsResponse:
    """Get layered cache statistics for monitoring and debugging.

    Returns a three-section response covering L1 query-response cache metrics,
    L2 embedding LRU cache metrics, and backend connectivity health.

    WHY layered schema (OPTB-008): The previous flat schema mixed L1 counters
    with backend health, making it impossible to route specific alerts (e.g.
    'only L2 is degraded').  The three-section layout gives consumers an
    unambiguous contract and allows section-level alerting rules.

    Implements fail-open principle: always returns HTTP 200, even when the
    cache backend is unavailable, the retriever is not initialized, or an
    unexpected exception is raised.  Degraded sections return zeroed values
    and backend_health.fallback_active=True to signal the degraded state.

    Returns:
        LayeredCacheStatsResponse with l1_query_cache, l2_embedding_cache,
        backend_health, and timestamp sections.

    Example:
        GET /cache/stats
        Response: {
            "l1_query_cache": {
                "backend": "memory",
                "hits": 1500, "misses": 350, "hit_rate": 0.811,
                "size": 125, "max_size": 10000, "ttl_seconds": 3600,
                "corpus_version": "gen2.n108"
            },
            "l2_embedding_cache": {
                "hits": 800, "misses": 200, "hit_rate": 0.800,
                "size": 300, "capacity": 5000
            },
            "backend_health": {
                "connected": true, "latency_ms": 0.8,
                "fallback_active": false, "error": null
            },
            "timestamp": "2026-04-22T10:30:45.123456Z"
        }
    """
    # -----------------------------------------------------------------------
    # Zero-value sentinels used when a section cannot be populated.
    # Returning zeroes (not None) guarantees the schema shape is always valid
    # and consumers never need null-checks on numeric fields.
    # -----------------------------------------------------------------------
    _zeroed_l1 = L1QueryCacheStats(
        backend="none",
        hits=0,
        misses=0,
        hit_rate=0.0,
        size=0,
        max_size=0,
        ttl_seconds=0,
        corpus_version=_corpus_version,
    )
    _zeroed_l2 = L2EmbeddingCacheStats(
        hits=0, misses=0, hit_rate=0.0, size=0, capacity=0
    )
    _degraded_health = BackendHealthStats(
        connected=False,
        latency_ms=None,
        fallback_active=True,
        error=None,
    )

    try:
        # ------------------------------------------------------------------
        # L1 section — sourced from the active cache backend.
        # ------------------------------------------------------------------
        if _cache is None:
            # Cache not yet initialised or was torn down after a backend error.
            l1 = _zeroed_l1
            backend_health = _degraded_health
        else:
            try:
                raw = lazy_cache.stats()
                hits = int(raw.get("hits", 0))
                misses = int(raw.get("misses", 0))
                total = hits + misses
                hit_rate = (hits / total) if total > 0 else 0.0

                l1 = L1QueryCacheStats(
                    backend=str(raw.get("backend", "unknown")),
                    hits=hits,
                    misses=misses,
                    hit_rate=hit_rate,
                    size=int(raw.get("size", 0) or 0),
                    max_size=int(raw.get("max_size", 0) or 0),
                    ttl_seconds=int(raw.get("ttl_seconds", 0) or 0),
                    # corpus_version surfaces the active key-namespace token so
                    # operators can verify invalidation events took effect.
                    corpus_version=_corpus_version,
                )
                logger.debug(
                    "L1 stats: backend=%s hits=%d misses=%d hit_rate=%.2f corpus_version=%s",
                    l1.backend,
                    l1.hits,
                    l1.misses,
                    l1.hit_rate,
                    l1.corpus_version,
                )
            except Exception as l1_err:
                # Fail-open for L1: return zeroes rather than propagating.
                logger.warning("Failed to read L1 cache stats: %s", l1_err)
                l1 = _zeroed_l1

            # ----------------------------------------------------------------
            # Backend health — uses the CacheBackend.health() method which
            # performs a live Redis PING for RedisCache or returns an always-
            # connected response for InMemoryCache.
            # ----------------------------------------------------------------
            try:
                raw_health = lazy_cache.health()
                backend_health = BackendHealthStats(
                    connected=bool(raw_health.get("connected", False)),
                    latency_ms=raw_health.get("latency_ms"),
                    fallback_active=bool(raw_health.get("fallback_active", False)),
                    error=raw_health.get("error"),
                )
            except Exception as health_err:
                logger.warning("Failed to read backend health: %s", health_err)
                backend_health = _degraded_health

            # OPTB-012: Emit structured log on fallback state transitions.
            # _log_fallback_transition() is idempotent for stable states so it
            # is safe to call on every /cache/stats poll.
            _log_fallback_transition(backend_health.fallback_active)

        # ------------------------------------------------------------------
        # L2 section — sourced from the retriever's public embedding cache
        # accessor.  Returns zeroes if the retriever is not yet initialised.
        # ------------------------------------------------------------------
        if _retriever is None:
            l2 = _zeroed_l2
        else:
            try:
                raw_l2 = _retriever.get_embedding_cache_stats()
                l2_hits = int(raw_l2.get("hits", 0))
                l2_misses = int(raw_l2.get("misses", 0))
                l2_total = l2_hits + l2_misses
                l2_hit_rate = (l2_hits / l2_total) if l2_total > 0 else 0.0
                l2 = L2EmbeddingCacheStats(
                    hits=l2_hits,
                    misses=l2_misses,
                    hit_rate=l2_hit_rate,
                    size=int(raw_l2.get("size", 0)),
                    capacity=int(raw_l2.get("capacity", 0)),
                )
                logger.debug(
                    "L2 stats: hits=%d misses=%d hit_rate=%.2f size=%d/%d",
                    l2.hits,
                    l2.misses,
                    l2.hit_rate,
                    l2.size,
                    l2.capacity,
                )
            except Exception as l2_err:
                logger.warning("Failed to read L2 embedding cache stats: %s", l2_err)
                l2 = _zeroed_l2

        return LayeredCacheStatsResponse(
            l1_query_cache=l1,
            l2_embedding_cache=l2,
            backend_health=backend_health,
            timestamp=datetime.now(timezone.utc),
        )

    except Exception as outer_err:
        # Outer fail-open guard: an unexpected error in the orchestration
        # logic itself must never produce a 5xx response.
        logger.warning("Unexpected error building cache stats response: %s", outer_err)
        return LayeredCacheStatsResponse(
            l1_query_cache=_zeroed_l1,
            l2_embedding_cache=_zeroed_l2,
            backend_health=_degraded_health,
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

                # OPTB-012: Generate a per-message correlation ID for WebSocket
                # requests.  WebSocket frames do not carry HTTP headers, so we
                # always auto-generate a UUID.  This links cache hit/miss logs
                # to the specific WebSocket message.
                ws_correlation_id = str(uuid.uuid4())
                ws_cache_status_out: list[str] = []
                results = _shared_retrieve_documents(
                    query,
                    enable_rerank=enable_rerank,
                    correlation_id=ws_correlation_id,
                    _out_cache_status=ws_cache_status_out,
                )
                doc_results = _to_filtered_document_results(
                    results, min_score_threshold=0.80
                )

                # T03 WS cache-status contract: include retrieval-layer cache
                # outcome in the results payload so WS clients have direct
                # cache visibility via the cache_status field in the message.
                # _shared_retrieve_documents always appends exactly one element;
                # the fallback handles any unexpected empty-list edge case.
                _raw_status = ws_cache_status_out[0] if ws_cache_status_out else "MISS"
                ws_cache_status: Literal["HIT", "MISS", "ERROR"] = (
                    _raw_status if _raw_status in ("HIT", "MISS", "ERROR") else "MISS"
                )

                # Send results (total_results reflects post-filter count)
                results_msg = WsResultsMessage(
                    query=query,
                    results=doc_results,
                    total_results=len(doc_results),
                    cache_status=ws_cache_status,
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
    global _cache_generation, _corpus_version

    if _retriever is None or _config is None:
        logger.error("Retriever not initialized")
        raise HTTPException(
            status_code=503,
            detail="Retriever service not initialized. Try again later.",
        )

    try:
        text_content = ""
        # source_label is resolved per source_type branch below when not explicitly provided.
        source_label = request.source_label

        # Log ingest type (ADR-003 - Fix for blocking issue #3)
        logger.info(f"Ingest type: {request.ingest_type}; cache {'will be cleared' if request.ingest_type == 'update' else 'will be preserved'}")

        if request.source_type == "text":
            text_content = request.content
            # When no explicit label is provided, derive a deterministic one from the
            # content so that different unlabelled text uploads are treated as distinct
            # sources.  The generic fallback ("text") would map everything to the same
            # source and cause the update path to delete unrelated prior ingests.
            if not source_label:
                content_hash = hashlib.sha256(request.content.encode()).hexdigest()[:12]
                source_label = f"text_{content_hash}"
            logger.info(f"Ingesting text document: {source_label}")

        elif request.source_type == "url":
            logger.info(f"Fetching content from URL: {request.content}")
            try:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.5",
                }
                response = requests.get(request.content, headers=headers, timeout=15)
                response.raise_for_status()
            except requests.RequestException as e:
                logger.error(f"Failed to fetch URL: {e}")
                raise HTTPException(
                    status_code=502, detail=f"Failed to fetch URL: {str(e)}"
                )

            class _TextExtractor(HTMLParser):
                def __init__(self):
                    super().__init__()
                    self._parts: list[str] = []
                    self._skip = False
                def handle_starttag(self, tag, attrs):
                    if tag in {"script", "style", "nav", "footer", "header"}:
                        self._skip = True
                def handle_endtag(self, tag):
                    if tag in {"script", "style", "nav", "footer", "header"}:
                        self._skip = False
                def handle_data(self, data):
                    if not self._skip:
                        s = data.strip()
                        if s:
                            self._parts.append(s)
                def get_text(self) -> str:
                    return " ".join(self._parts)

            extractor = _TextExtractor()
            extractor.feed(response.text)
            text_content = extractor.get_text()
            if not text_content:
                logger.error(f"No extractable text from URL: {request.content}")
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"No readable text could be extracted from {request.content}. "
                        "The page may require JavaScript, a login, or bot verification."
                    ),
                )
            source_label = request.source_label or request.content

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

            # Use the filename as the stable identifier so repeated uploads of the
            # same file are treated as updates rather than independent new sources.
            source_label = request.source_label or request.filename

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
            parsed = urlparse(request.content)
            is_http_url = parsed.scheme in ("http", "https") and bool(parsed.netloc)
            source_url = request.content if is_http_url else None
            url_meta: dict[str, str] = {"source_url": source_url} if source_url else {}
            metadatas = [
                {"source": source_label, "chunk_index": i, **url_meta}
                for i in range(len(chunks))
            ]

            # Determine effective ingest type.
            # When the client explicitly sets ingest_type (present in model_fields_set)
            # we honour that contract.  When omitted (the default), we derive the type
            # from the collection so the backend can self-heal without client cooperation.
            #
            # Derivation: primary check by source label, secondary by source_url to handle
            # the case where the same URL was previously ingested under a different label.
            if "ingest_type" in request.model_fields_set:
                effective_ingest_type = request.ingest_type
                source_is_new = (effective_ingest_type == "add")
                matched_by_url = False
            else:
                # Pass include=[] so ChromaDB returns only ids, not full documents.
                existing_by_label = collection.get(
                    where={"source": source_label}, limit=1, include=[]
                )
                matched_by_url = False
                if not existing_by_label["ids"] and source_url:
                    existing_by_url = collection.get(
                        where={"source_url": source_url}, limit=1, include=[]
                    )
                    matched_by_url = bool(existing_by_url["ids"])

                source_is_new = not existing_by_label["ids"] and not matched_by_url
                effective_ingest_type = "add" if source_is_new else "update"

            logger.info(
                "Ingest source_is_new=%s effective_ingest_type=%s source=%s",
                source_is_new,
                effective_ingest_type,
                source_label,
            )

            # For updates, remove stale chunks before adding new ones so the corpus
            # never holds duplicate content for the same source.
            # When the match was by source_url (label changed), delete by URL to reach
            # the old chunks that are indexed under the previous label.
            if effective_ingest_type == "update":
                old_ids_by_label = collection.get(
                    where={"source": source_label}, include=[]
                )["ids"]
                if old_ids_by_label:
                    collection.delete(ids=old_ids_by_label)
                    logger.info(
                        "Deleted %d stale chunks for source=%s",
                        len(old_ids_by_label),
                        source_label,
                    )
                if matched_by_url and source_url:
                    old_ids_by_url = collection.get(
                        where={"source_url": source_url}, include=[]
                    )["ids"]
                    remaining = [id_ for id_ in old_ids_by_url if id_ not in set(old_ids_by_label)]
                    if remaining:
                        collection.delete(ids=remaining)
                        logger.info(
                            "Deleted %d stale chunks for source_url=%s (label changed)",
                            len(remaining),
                            source_url,
                        )

            # Add to collection
            collection.add(
                ids=doc_ids,
                documents=chunks,
                metadatas=metadatas,
            )
            logger.info(
                f"Added {len(chunks)} chunks to collection from source: {source_label}"
            )

            if effective_ingest_type == "update":
                prev_version = _corpus_version
                _cache_generation += 1
                _corpus_version = _build_corpus_version_token()
                logger.info(
                    "cache.invalidation event=ingest_update prev_version=%s new_version=%s",
                    prev_version,
                    _corpus_version,
                )
                if _cache is not None:
                    try:
                        lazy_cache.clear()
                        logger.info("Ingest complete (type='update'); cache cleared")
                    except Exception as e:
                        logger.warning(f"Failed to clear cache after ingest: {e}")
                else:
                    logger.debug("Ingest complete (type='update'); cache not initialized")
            else:
                # New source: don't bump the generation counter — cached results for
                # existing queries are still valid.  Rebuild the token on the count
                # dimension so queries issued after this add see the grown corpus.
                prev_version = _corpus_version
                _corpus_version = _build_corpus_version_token()
                logger.info(
                    "cache.invalidation event=ingest_add prev_version=%s new_version=%s",
                    prev_version,
                    _corpus_version,
                )
                logger.info("Ingest complete (type='add'); cache preserved")

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
