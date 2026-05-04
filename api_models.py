"""Pydantic request/response models for the Hybrid RAG REST API.

All public data shapes used across API endpoints are defined here so
that they can be imported by both the core ``api`` module and each
``routers/`` sub-module without introducing circular dependencies.
"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class DocumentResult(BaseModel):
    """Model representing a single retrieved document."""

    id: str = Field(..., description="Document identifier")
    text: str = Field(..., description="Document text content")
    source: str = Field(..., description="Document source label or URL")
    source_url: Optional[str] = Field(
        None, description="Original URL when source has a custom label"
    )
    score: float = Field(
        ...,
        description="Relevance score (may be negative due to fusion/reranking)",
    )


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

    All fields are optional — only provided fields will be updated.
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
        None,
        min_length=6,
        max_length=20,
        description=(
            "ChromaDB collection name (6-20 chars, "
            "alphanumeric/underscore/hyphen)"
        ),
    )


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
        "update",
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


class CollectionInfo(BaseModel):
    """Model representing a ChromaDB collection."""

    name: str = Field(..., description="Collection name")
    count: int = Field(..., description="Number of documents in the collection")


class CollectionsResponse(BaseModel):
    """Response model for listing ChromaDB collections."""

    collections: list[CollectionInfo] = Field(
        ..., description="List of available ChromaDB collections"
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
        None,
        description="Ping round-trip latency in ms (None for in-memory backends)",
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
