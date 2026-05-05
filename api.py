
"""FastAPI REST API for Hybrid RAG Retrieval Service.

This module is the application entry point.  It owns all shared mutable
state (retriever, config, cache), exposes the public helpers used by the
route sub-modules in ``routers/``, and wires everything together via
``app.include_router()``.

Module layout
-------------
api.py          -- Global state, initialization, core utilities, app factory.
api_models.py   -- All Pydantic request/response models (zero state imports).
routers/
  health.py     -- GET /health, GET /
  config.py     -- GET /config, PUT /config
  cache.py      -- GET /cache/stats
  documents.py  -- POST /documents, GET /documents/sources, GET /collections
  websocket.py  -- WS /ws/chat

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

import hashlib
import json
import logging
import os
import sys
import uuid
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, Optional

import requests  # noqa: F401 — tests patch api.requests.get; import kept here for backward compat
import chromadb  # noqa: F401 — tests patch api.chromadb.PersistentClient; import kept here for backward compat
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from hybrid_rag import (
    CACHE_TELEMETRY_LABELS,
    KNOWLEDGE_DB_DIRECTORY,
    HybridRetriever,
    HybridRetrieverConfig,
    RetrieverNotInitializedError,
    VectorDBError,
    chunk_text,  # noqa: F401 - retained for future callers (ADR-0001 T4)
    get_sample_documents,
    initialize_vector_db,
    list_existing_collections,
    load_config_from_disk,
    open_collection,
)
from hybrid_rag.cache import CacheBackend
from hybrid_rag.config import CacheSettings, create_cache_backend

# Re-export all Pydantic models so existing callers (tests, client code) that
# do ``from api import WsResultsMessage`` or ``import api; api.DocumentResult``
# continue to work without modification.
from api_models import (
    BackendHealthStats,
    CacheStatsResponse,
    CollectionInfo,
    CollectionsResponse,
    ConfigResponse,
    ConfigUpdateRequest,
    DocumentIngestionRequest,
    DocumentIngestionResponse,
    DocumentResult,
    DocumentSource,
    HealthResponse,
    L1QueryCacheStats,
    L2EmbeddingCacheStats,
    LayeredCacheStatsResponse,
    SourcesResponse,
    WsErrorMessage,
    WsMessageBase,
    WsQueryMessage,
    WsResultsMessage,
    WsStatusMessage,
)

# TYPE_CHECKING imports — make route functions visible to static analyzers (Ruff, mypy, etc.)
# These imports are only executed during type-checking, not at runtime.
# At runtime, __getattr__() (defined below) provides the functions lazily to avoid circular imports.
if TYPE_CHECKING:
    from routers.cache import get_cache_stats
    from routers.config import get_config, update_config
    from routers.documents import add_documents, get_collections, get_document_sources
    from routers.health import health_check, root
    from routers.websocket import websocket_chat

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# CRITICAL FIX FOR PR #92 ROUTER IMPORT ISSUE:
# When api.py runs as a script (python api.py), Python creates a __main__ module.
# When routers later do "import api", Python looks for the api module in sys.modules.
# Without this fix, "import api" creates a SECOND module instance, causing global
# variables set in __main__ to be invisible to the routers.
# Solution: Explicitly register __main__ as "api" in sys.modules so all imports
# reference the same module and share the same globals.
if __name__ == "__main__" and "api" not in sys.modules:
    sys.modules["api"] = sys.modules["__main__"]
    logger.info("✓ Registered __main__ as 'api' in sys.modules to fix router import issue (PR #92)")
elif __name__ != "__main__" and __name__ not in sys.modules:
    sys.modules[__name__] = sys.modules["__main__"]
    logger.info(f"✓ Registered {__name__} in sys.modules")

__all__ = [
    # Application
    "app",
    "initialize_retriever",
    # Route handler functions — re-exported so tests can call them directly
    # (e.g. ``await api.websocket_chat(ws)``) without modification.
    "websocket_chat",
    "health_check",
    "root",
    "get_config",
    "update_config",
    "get_cache_stats",
    "add_documents",
    "get_document_sources",
    "get_collections",
    # Models — re-exported so ``from api import X`` and ``api.X`` continue to
    # work for existing tests and client code after the models moved to api_models.py.
    "BackendHealthStats",
    "CacheStatsResponse",
    "CollectionInfo",
    "CollectionsResponse",
    "ConfigResponse",
    "ConfigUpdateRequest",
    "DocumentIngestionRequest",
    "DocumentIngestionResponse",
    "DocumentResult",
    "DocumentSource",
    "HealthResponse",
    "L1QueryCacheStats",
    "L2EmbeddingCacheStats",
    "LayeredCacheStatsResponse",
    "SourcesResponse",
    "WsErrorMessage",
    "WsMessageBase",
    "WsQueryMessage",
    "WsResultsMessage",
    "WsStatusMessage",
]

# ---------------------------------------------------------------------------
# Global mutable state
# Tests access these directly (e.g. ``api._retriever = mock``), so they must
# remain at module level in this file.
# ---------------------------------------------------------------------------

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

        # Try to load persisted configuration first
        _config = load_config_from_disk(KNOWLEDGE_DB_DIRECTORY)
        if _config is not None:
            logger.info("Loaded persisted configuration from disk")
        else:
            # Initialize with default configuration if no persisted config
            logger.info("No persisted configuration found, using defaults")
            _config = HybridRetrieverConfig(
                semantic_weight=0.7, keyword_weight=0.3, enable_rerank=True
            )

        # Initialize vector database
        existing = list_existing_collections(KNOWLEDGE_DB_DIRECTORY)
        if _config.collection_name in existing:
            collection = open_collection(
                persist_dir=KNOWLEDGE_DB_DIRECTORY,
                collection_name=_config.collection_name,
            )
            logger.info("Loaded existing collection '%s'", _config.collection_name)
        else:
            documents = get_sample_documents()
            collection = initialize_vector_db(
                documents,
                persist_dir=KNOWLEDGE_DB_DIRECTORY,
                collection_name=_config.collection_name,
            )
            logger.info(
                "Created new collection '%s' with %d sample documents",
                _config.collection_name,
                len(documents),
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
    
    Initializes the hybrid retriever and cache backend from environment settings.
    Ensures routers are registered (failsafe in case of deferred import issues).
    Both are stored as globals and cleaned up on shutdown.
    
    Raises:
        Exception: If initialization fails, critical exception is logged.
    """
    global _retriever, _config, _cache
    logger.info("🚀 Startup event triggered")
    try:
        # Register routers first (safe here, no circular imports at startup)
        if not _routers_registered:
            logger.info("Registering routers...")
            _register_routers_on_app()
        
        # Then initialize retriever
        logger.info("Calling initialize_retriever...")
        initialize_retriever()
        logger.info("✓ Retriever initialization complete, _config=%s", _config)
        
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


# ---------------------------------------------------------------------------
# CORS middleware
# ---------------------------------------------------------------------------

allow_origins = os.getenv(
    "CORS_ORIGINS", "http://localhost:3000,http://localhost:3001"
).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
logger.info("CORS enabled for origins: %s", allow_origins)

# ---------------------------------------------------------------------------
# Re-export route handler functions for backward compatibility
# NOTE: Imports are deferred to avoid circular imports (see lazy __getattr__ below).
# Each router does ``import api`` which causes circular import at module load time.
# Functions are lazy-loaded when first accessed via module.__getattr__.
# ---------------------------------------------------------------------------

# Lazy function imports — see __getattr__ below for implementation
_router_functions: dict[str, Any] = {}
_routers_registered: bool = False

# Register routers immediately after module initialization to make them available to
# both the app and test clients. This happens AFTER all other module-level code executes,
# so circular imports from routers/*.py importing api are resolved by that point.
def _register_routers_on_app() -> None:
    """Register all routers on the app (called during startup)."""
    global _routers_registered
    if _routers_registered:
        return
    
    try:
        from routers.cache import router as cache_router  # noqa: F401
        from routers.config import router as config_router  # noqa: F401
        from routers.documents import router as documents_router  # noqa: F401
        from routers.health import router as health_router  # noqa: F401
        from routers.websocket import router as websocket_router  # noqa: F401
        
        app.include_router(health_router)
        app.include_router(config_router)
        app.include_router(cache_router)
        app.include_router(documents_router)
        app.include_router(websocket_router)
        _routers_registered = True
        logger.info("✓ Routers registered successfully")
    except Exception as e:
        logger.error(f"Failed to register routers: {e}", exc_info=True)
        _routers_registered = False
        raise


def __getattr__(name: str) -> Any:
    """Lazy-load route handler functions to avoid circular imports.
    
    When a function like `get_cache_stats` is accessed via `api.get_cache_stats`
    or imported via `from api import get_cache_stats`, this function is called
    to load the function on-demand from the appropriate router module.
    
    This approach avoids circular imports that would occur if we imported
    these functions at module load time.
    
    Args:
        name: The name of the attribute being accessed.
        
    Returns:
        The requested function from the appropriate router module.
        
    Raises:
        AttributeError: If the name is not a known router function.
    """
    # Map function names to (module_name, function_name) tuples
    router_function_map = {
        "get_cache_stats": ("routers.cache", "get_cache_stats"),
        "get_config": ("routers.config", "get_config"),
        "update_config": ("routers.config", "update_config"),
        "add_documents": ("routers.documents", "add_documents"),
        "get_document_sources": ("routers.documents", "get_document_sources"),
        "get_collections": ("routers.documents", "get_collections"),
        "health_check": ("routers.health", "health_check"),
        "root": ("routers.health", "root"),
        "websocket_chat": ("routers.websocket", "websocket_chat"),
    }
    
    if name not in router_function_map:
        raise AttributeError(f"module 'api' has no attribute '{name}'")
    
    # Lazy-load the function if not already cached
    if name not in _router_functions:
        module_name, func_name = router_function_map[name]
        module = __import__(module_name, fromlist=[func_name])
        _router_functions[name] = getattr(module, func_name)
    
    return _router_functions[name]


# NOTE: Router registration is deferred to startup_event() to avoid circular imports.
# Do NOT register routers here at module load time. The circular import sequence is:
# api.py (line N) -> _register_routers_on_app() -> routers.cache -> import api (incomplete)
# This causes the error: "cannot import name 'router' from partially initialized module"
# Solution: Only register routers in startup_event() after all modules are fully loaded.


if __name__ == "__main__":
    import uvicorn

    logger.info("🚀 Starting Hybrid RAG Retriever API...")
    logger.info("📖 Swagger UI: http://localhost:8000/docs")
    logger.info("📋 ReDoc: http://localhost:8000/redoc")
    logger.info("🔧 Health Check: http://localhost:8000/health")
    logger.info("💬 WebSocket Chat: ws://localhost:8000/ws/chat")

    uvicorn.run(app, host="0.0.0.0", port=8000)
