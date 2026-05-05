"""MCP (Model Context Protocol) server for Hybrid RAG retrieval.

Exposes the hybrid RAG query pipeline as MCP tools accessible via stdio or
streamable HTTP transport (e.g., Claude Desktop, hosted MCP gateways).
"""

import asyncio
import signal
import hashlib
import json
import logging
import os
import uuid
from typing import Any, Optional

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from hybrid_rag import (
    CACHE_TELEMETRY_LABELS,
    DEFAULT_CONFIG,
    KNOWLEDGE_DB_DIRECTORY,
    CacheBackend,
    CacheSettings,
    HybridRetriever,
    HybridRetrieverConfig,
    RetrievalError,
    create_cache_backend,
    get_sample_documents,
    initialize_vector_db,
    is_valid_collection_name,
    list_existing_collections,
    load_config_from_disk,
    open_collection,
)

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Initialize FastMCP server
mcp = FastMCP(
    "hybrid-rag",
    host=os.getenv("MCP_HOST", "127.0.0.1"),
    port=int(os.getenv("MCP_PORT", "8000")),
)

# Global state
_retriever: Optional[HybridRetriever] = None
_config: HybridRetrieverConfig = DEFAULT_CONFIG
_cache: Optional[CacheBackend] = None
_cache_generation: int = 0
_corpus_version: str = "0"


def _load_initial_config() -> HybridRetrieverConfig:
    """Load startup configuration, preferring persisted settings when available.

    Attempts to load configuration from knowledge_db/config.json. If no persisted
    config exists or loading fails, uses DEFAULT_CONFIG. Environment variable
    COLLECTION_NAME (if set and valid) overrides the loaded collection_name.

    Returns:
        Loaded or default HybridRetrieverConfig.

    Raises:
        ValueError: If COLLECTION_NAME env var is invalid.
    """
    # Try to load persisted configuration first
    try:
        config = load_config_from_disk(KNOWLEDGE_DB_DIRECTORY)
        if config is not None:
            logger.info("Loaded persisted configuration from disk")
        else:
            logger.info("No persisted configuration found, using defaults")
            config = DEFAULT_CONFIG
    except Exception as e:
        logger.warning("Failed to load persisted configuration: %s; using defaults", e)
        config = DEFAULT_CONFIG

    # Override collection_name with COLLECTION_NAME env var if present
    env_collection_name = os.getenv("COLLECTION_NAME")
    if env_collection_name:
        if not is_valid_collection_name(env_collection_name):
            raise ValueError(
                f"Invalid COLLECTION_NAME '{env_collection_name}': must be 6-20 chars, "
                "alphanumeric/underscore/hyphen only"
            )
        config = config.update(collection_name=env_collection_name)
        logger.info("Overriding collection_name from COLLECTION_NAME env var: %s", env_collection_name)

    return config


def _build_corpus_version_token() -> str:
    """Build a corpus version token combining the cache generation counter with the live collection count.

    Mirrors the same helper in api.py so the two processes produce identical cache
    keys when pointed at the same Chroma DB and Redis instance, enabling them to
    share the warm L1 cache across restarts and deployments.

    Returns:
        Token string like ``"gen0.n42"`` encoding both generation and corpus size.
        Falls back to ``"gen{N}.n0"`` when the collection is unavailable.
    """
    if _retriever is not None:
        try:
            count = _retriever.collection.count()
            return f"gen{_cache_generation}.n{count}"
        except Exception as exc:
            logger.warning("Could not read collection count for corpus_version: %s", exc)
    return f"gen{_cache_generation}.n0"


async def _initialize_retriever() -> None:
    """Initialize the hybrid retriever and cache backend (called at server startup)."""
    global _config, _retriever, _cache, _corpus_version

    if _retriever is not None:
        return  # Already initialized

    try:
        config = _load_initial_config()
        existing = list_existing_collections(KNOWLEDGE_DB_DIRECTORY)
        if config.collection_name in existing:
            collection = open_collection(
                persist_dir=KNOWLEDGE_DB_DIRECTORY,
                collection_name=config.collection_name,
            )
        else:
            collection = initialize_vector_db(
                get_sample_documents(),
                persist_dir=KNOWLEDGE_DB_DIRECTORY,
                collection_name=config.collection_name,
            )
        _config = config
        _retriever = HybridRetriever(collection, config)
        logger.info("Retriever initialized with collection: %s", config.collection_name)

        # Initialize L1 query cache (same backend as api.py — shares Redis when configured).
        try:
            cache_settings = CacheSettings.from_env()
            _cache = create_cache_backend(cache_settings)
            logger.info(
                "Cache initialized: backend=%s ttl=%ss",
                cache_settings.backend,
                cache_settings.ttl_seconds,
            )
        except Exception:
            logger.warning("Cache initialization failed; continuing without cache")
            _cache = None

        _corpus_version = _build_corpus_version_token()
        logger.info("Corpus version token: %s", _corpus_version)
    except Exception:
        logger.exception("Failed to initialize retriever")
        raise


@mcp.tool()
async def query_knowledge_base(
    query: str,
    enable_rerank: Optional[bool] = None,
) -> dict[str, Any]:
    """Query the hybrid RAG knowledge base using semantic and keyword search.

    Combines semantic search (embeddings), keyword search (BM25-style),
    score fusion, and optional cross-encoder reranking.

    Args:
        query: The search query (1-500 characters).
        enable_rerank: Whether to apply cross-encoder reranking. If None,
            uses the current configuration default.

    Returns:
        A dictionary with:
        - results: List of normalized documents, each with id, text, source,
          source_url, and score fields
        - total_results: Number of documents returned
    """
    if _retriever is None:
        raise ValueError("Retriever not initialized")

    query_str = query.strip()
    if not query_str or len(query_str) < 1 or len(query_str) > 500:
        raise ValueError("Query must be between 1 and 500 characters")

    try:
        effective_enable_rerank = (
            _config.enable_rerank if enable_rerank is None else bool(enable_rerank)
        )

        # Build a cache key that matches api.py's _shared_retrieve_documents so the
        # two processes share the same warm Redis cache when deployed together.
        config_fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "semantic_top_k": _config.semantic_top_k,
                    "keyword_top_k": _config.keyword_top_k,
                    "final_top_k": _config.final_top_k,
                    "semantic_weight": _config.semantic_weight,
                    "keyword_weight": _config.keyword_weight,
                    "enable_rerank": _config.enable_rerank,
                    "pre_rerank_top_k": _config.pre_rerank_top_k,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        cache_key = "shared-retrieve:" + hashlib.sha256(
            json.dumps(
                {
                    "query": " ".join(query_str.split()),
                    "effective_enable_rerank": effective_enable_rerank,
                    "config_fingerprint": config_fingerprint,
                    "corpus_version": _corpus_version,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        correlation_id = str(uuid.uuid4())

        # L1 cache read — fail-open on errors
        if _cache is not None:
            try:
                cached = _cache.get(cache_key)
                if isinstance(cached, list):
                    logger.info(
                        "%s correlation_id=%s corpus_version=%s",
                        CACHE_TELEMETRY_LABELS["retrieval_hit"],
                        correlation_id,
                        _corpus_version,
                    )
                    raw_results = cached
                else:
                    logger.info(
                        "%s correlation_id=%s corpus_version=%s",
                        CACHE_TELEMETRY_LABELS["retrieval_miss"],
                        correlation_id,
                        _corpus_version,
                    )
                    raw_results = _retriever.retrieve(
                        query_str, enable_rerank=effective_enable_rerank
                    )
                    try:
                        _cache.set(cache_key, raw_results)
                    except Exception as write_err:
                        logger.warning("Cache write failed: %s", write_err)
            except Exception as read_err:
                logger.warning("Cache read failed: %s", read_err)
                logger.info(
                    "%s correlation_id=%s corpus_version=%s",
                    CACHE_TELEMETRY_LABELS["retrieval_error"],
                    correlation_id,
                    _corpus_version,
                )
                raw_results = _retriever.retrieve(
                    query_str, enable_rerank=effective_enable_rerank
                )
        else:
            raw_results = _retriever.retrieve(
                query_str, enable_rerank=effective_enable_rerank
            )

        # Filter and normalize to the same {id, text, source, source_url, score}
        # contract used by every other retrieval entrypoint in api.py.
        normalized_results = [
            {
                "id": r["id"],
                "text": r["text"],
                "source": r.get("metadata", {}).get("source", "unknown"),
                "source_url": r.get("metadata", {}).get("source_url"),
                "score": float(r["score"]),
            }
            for r in raw_results
            if float(r.get("score", 0.0)) >= 0.40
        ]

        return {
            "results": normalized_results,
            "total_results": len(normalized_results),
        }
    except RetrievalError as e:
        raise ValueError(f"Retrieval failed: {str(e)}")
    except Exception:
        logger.exception("Unexpected error in query_knowledge_base")
        raise ValueError("An unexpected error occurred")


@mcp.tool()
async def get_config() -> dict[str, Any]:
    """Get the current hybrid retriever configuration.

    Returns:
        Dictionary with current configuration values (semantic_top_k,
        keyword_top_k, final_top_k, weights, reranking settings, etc.)
    """
    if _config is None:
        raise ValueError("Configuration not available")

    return _config.to_dict()


def _resolve_transport() -> str:
    """Resolve MCP transport mode from environment."""
    configured_transport = os.getenv("MCP_TRANSPORT", "stdio").strip().lower()
    if configured_transport == "stdio":
        return "stdio"
    if configured_transport in {"http", "streamable-http", "streamable_http"}:
        return "streamable-http"
    raise ValueError(
        f"Unsupported MCP_TRANSPORT '{configured_transport}'. "
        "Use one of: stdio, http, streamable-http."
    )


async def main() -> None:
    """Start the MCP server."""
    await _initialize_retriever()
    transport = _resolve_transport()

    # Use an event to wait for shutdown signals (SIGINT, SIGTERM).
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    def _on_signal() -> None:
        logger.info("Shutdown signal received, stopping MCP server...")
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _on_signal)
        except NotImplementedError:
            # add_signal_handler is not implemented on some platforms (Windows/uvloop),
            # rely on default signal handling in those cases.
            pass

    # Run the MCP transport in the background so we can wait for signals.
    if transport == "stdio":
        mcp_task = asyncio.create_task(mcp.run_stdio_async())
    else:
        mcp_task = asyncio.create_task(mcp.run_streamable_http_async())

    # Wait until a shutdown signal is received or the mcp task finishes.
    # asyncio.wait() requires actual Task/Future objects (not raw coroutines),
    # so wrap the shutdown_event.wait() coroutine in a Task.
    shutdown_wait_task = asyncio.create_task(shutdown_event.wait())
    try:
        done, pending = await asyncio.wait(
            [shutdown_wait_task, mcp_task], return_when=asyncio.FIRST_COMPLETED
        )
    finally:
        # If the wait returned early for any reason, ensure we don't leave the
        # shutdown_wait_task pending.
        if not shutdown_wait_task.done():
            shutdown_wait_task.cancel()
            try:
                await shutdown_wait_task
            except asyncio.CancelledError:
                pass

    # Surface transport exception if task exited before a shutdown signal
    if mcp_task in done and not shutdown_event.is_set():
        mcp_task.result()  # re-raises any stored exception

    # If shutdown_event triggered, attempt graceful stop of MCP transport.
    if shutdown_event.is_set():
        # Try to call an explicit shutdown/stop method if available on FastMCP.
        for method_name in ("shutdown", "stop", "close", "terminate"):
            fn = getattr(mcp, method_name, None)
            if callable(fn):
                try:
                    maybe = fn()
                    if asyncio.iscoroutine(maybe):
                        await maybe
                    logger.info("Called mcp.%s() for graceful shutdown", method_name)
                except Exception as e:
                    logger.warning("mcp.%s() raised during shutdown: %s", method_name, e)
                break

        # Cancel the transport task if still running
        if not mcp_task.done():
            mcp_task.cancel()
            try:
                await mcp_task
            except asyncio.CancelledError:
                logger.info("MCP transport task cancelled")

    # Cleanup shared resources (mirror api.py shutdown behavior)
    try:
        if _cache is not None:
            try:
                _cache.clear()
                logger.info("Cache cleared on shutdown")
            except Exception as e:
                logger.warning("Error clearing cache on shutdown: %s", e)
    finally:
        # Release retriever reference to allow clean process exit
        global _retriever
        _retriever = None


if __name__ == "__main__":
    asyncio.run(main())
