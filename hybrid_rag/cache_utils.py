"""Shared cache utilities for api.py and mcp_server.py.

This module contains helpers that must produce identical output across both
entry points to enable Redis cache sharing. Do not modify these functions
without careful consideration of cross-process consistency.
"""

import hashlib
import json
from typing import Any, Optional


def build_corpus_version_token(
    retriever: Optional[Any],
    cache_generation: int,
) -> str:
    """Build a corpus version token combining generation counter with live collection count.

    This token is authoritative across both api.py and mcp_server.py processes,
    enabling them to share the warm L1 cache in Redis. The token encodes:
      1. Explicit cache invalidation via generation counter bumps
      2. Automatic invalidation on corpus mutations (doc count changes)

    Args:
        retriever: The initialized HybridRetriever, or None if not yet available.
        cache_generation: The current cache generation counter (incremented on invalidation).

    Returns:
        A string token like "gen0.n42" encoding both generation and corpus size.
        Falls back to "gen{N}.n0" if retriever or collection is unavailable, preserving
        the consistent token format for reliable log parsing and key-space analysis.
    """
    if retriever is not None:
        try:
            count = retriever.collection.count()
            return f"gen{cache_generation}.n{count}"
        except Exception:
            # Silent fallback: if we can't read the collection count, don't propagate.
            # The token format stays consistent for tooling.
            pass
    return f"gen{cache_generation}.n0"


def build_shared_retrieve_cache_key(
    query: str,
    config_dict: dict[str, Any],
    corpus_version: str,
    enable_rerank: bool,
) -> str:
    """Build a cache key for shared retrieval that matches across api.py and mcp_server.py.

    Both processes must produce identical keys for the same inputs to enable Redis
    cache sharing. This function is the single source of truth for cache key construction.

    Args:
        query: The user query (will be whitespace-normalized).
        config_dict: The retriever config as a dict (semantic_top_k, keyword_top_k, etc.).
        corpus_version: The corpus version token from build_corpus_version_token().
        enable_rerank: Whether cross-encoder reranking is enabled.

    Returns:
        A cache key string prefixed with "shared-retrieve:" followed by a SHA-256 hash.
    """
    # Normalize query whitespace (multiple spaces → single space)
    normalized_query = " ".join(query.split())

    # Build config fingerprint (same fields used by both api.py and mcp_server.py)
    config_fingerprint_payload = {
        "semantic_top_k": config_dict["semantic_top_k"],
        "keyword_top_k": config_dict["keyword_top_k"],
        "final_top_k": config_dict["final_top_k"],
        "semantic_weight": config_dict["semantic_weight"],
        "keyword_weight": config_dict["keyword_weight"],
        "enable_rerank": config_dict["enable_rerank"],
        "pre_rerank_top_k": config_dict["pre_rerank_top_k"],
    }
    config_fingerprint = hashlib.sha256(
        json.dumps(
            config_fingerprint_payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    # Build shared identity that both processes must agree on
    shared_identity = {
        "query": normalized_query,
        "effective_enable_rerank": enable_rerank,
        "config_fingerprint": config_fingerprint,
        "corpus_version": corpus_version,
    }

    cache_key = "shared-retrieve:" + hashlib.sha256(
        json.dumps(
            shared_identity,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    return cache_key
