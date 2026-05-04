"""MCP (Model Context Protocol) server for Hybrid RAG retrieval.

Exposes the hybrid RAG query pipeline as MCP tools accessible via stdio transport
(e.g., Claude Desktop, Claude API with mcp.json configuration).
"""

import asyncio
import logging
import os
from typing import Any, Optional

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from hybrid_rag import (
    DEFAULT_CONFIG,
    HybridRetriever,
    HybridRetrieverConfig,
    RetrieverNotInitializedError,
    RetrievalError,
)

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

# Initialize FastMCP server
mcp = FastMCP("hybrid-rag")

# Global state
_retriever: Optional[HybridRetriever] = None
_config: HybridRetrieverConfig = DEFAULT_CONFIG


async def _initialize_retriever() -> None:
    """Initialize the hybrid retriever (called at server startup)."""
    global _retriever, _config

    if _retriever is not None:
        return  # Already initialized

    try:
        collection_name = os.getenv("COLLECTION_NAME", "rag_collection")
        _retriever = HybridRetriever(config=_config)
        _retriever.initialize(collection_name=collection_name)
        logger.info(f"Retriever initialized with collection: {collection_name}")
    except Exception as e:
        logger.error(f"Failed to initialize retriever: {e}")
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
    except Exception as e:
        logger.error(f"Unexpected error in query_knowledge_base: {e}")
        raise ValueError(f"An unexpected error occurred: {str(e)}")


@mcp.tool()
async def get_config() -> dict[str, Any]:
    """Get the current hybrid retriever configuration.

    Returns:
        Dictionary with current configuration values (semantic_top_k,
        keyword_top_k, final_top_k, weights, reranking settings, etc.)
    """
    if _config is None:
        raise ValueError("Configuration not available")

    return _config.__dict__


async def main() -> None:
    """Start the MCP server."""
    await _initialize_retriever()
    async with mcp.run_stdio():
        await asyncio.Event().wait()  # Run forever


if __name__ == "__main__":
    asyncio.run(main())
