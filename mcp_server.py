"""MCP (Model Context Protocol) server for Hybrid RAG retrieval.

Exposes the hybrid RAG query pipeline as MCP tools accessible via stdio or
streamable HTTP transport (e.g., Claude Desktop, hosted MCP gateways).
"""

import asyncio
import logging
import os
from typing import Any, Optional

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from hybrid_rag import (
    DEFAULT_CONFIG,
    KNOWLEDGE_DB_DIRECTORY,
    HybridRetriever,
    HybridRetrieverConfig,
    RetrievalError,
    get_sample_documents,
    initialize_vector_db,
    list_existing_collections,
    open_collection,
)

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

try:
    from hybrid_rag.persistence import load_config_from_disk
except ImportError:  # pragma: no cover - compatibility without persistence module
    load_config_from_disk = None

# Initialize FastMCP server
mcp = FastMCP(
    "hybrid-rag",
    host=os.getenv("MCP_HOST", "127.0.0.1"),
    port=int(os.getenv("MCP_PORT", "8000")),
)

# Global state
_retriever: Optional[HybridRetriever] = None
_config: HybridRetrieverConfig = DEFAULT_CONFIG


def _load_initial_config() -> HybridRetrieverConfig:
    """Load startup configuration, preferring persisted settings when available."""
    config = HybridRetrieverConfig(**DEFAULT_CONFIG.to_dict())

    if load_config_from_disk is not None:
        try:
            persisted_config = load_config_from_disk(KNOWLEDGE_DB_DIRECTORY)
            if persisted_config is not None:
                config = persisted_config
                logger.info("Loaded persisted MCP configuration")
        except (OSError, ValueError, TypeError):
            logger.exception(
                "Failed to load persisted configuration; falling back to defaults"
            )

    env_collection_name = os.getenv("COLLECTION_NAME")
    if env_collection_name:
        config = config.update(collection_name=env_collection_name)

    return config


async def _initialize_retriever() -> None:
    """Initialize the hybrid retriever (called at server startup)."""
    global _config, _retriever

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
        - results: List of documents, each with query and metadata fields
        - total_results: Number of documents returned
    """
    if _retriever is None:
        raise ValueError("Retriever not initialized")

    query_str = query.strip()
    if not query_str or len(query_str) < 1 or len(query_str) > 500:
        raise ValueError("Query must be between 1 and 500 characters")

    try:
        # Run retrieval pipeline
        raw_results = _retriever.retrieve(query_str, enable_rerank=enable_rerank)

        # Filter results by minimum relevance score (matching api.py behavior)
        filtered_results = [r for r in raw_results if r.get("score", 0) >= 0.40]

        return {
            "results": filtered_results,
            "total_results": len(filtered_results),
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
    if transport == "stdio":
        await mcp.run_stdio_async()
    else:
        await mcp.run_streamable_http_async()


if __name__ == "__main__":
    asyncio.run(main())
