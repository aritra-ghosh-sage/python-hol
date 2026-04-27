"""Core hybrid retrieval engine combining semantic and keyword search."""

import hashlib
import logging
import re
from typing import Any

import cachetools
import numpy as np
from chromadb.api.models.Collection import Collection
from sentence_transformers import SentenceTransformer

from .config import HybridRetrieverConfig
from .constants import STOP_WORDS
from .exceptions import RetrievalError
from .reranker import CrossEncoderReranker

__all__ = ["HybridRetriever"]

logger = logging.getLogger(__name__)


class HybridRetriever:
    """Hybrid retriever combining semantic search, keyword search, and reranking.

    Implements a multi-stage retrieval pipeline for finding relevant documents:
    1. Semantic search using embeddings for meaning-based matching
    2. Keyword search with stop word filtering for exact term matching
    3. Score fusion combining both signals with configurable weights
    4. Optional cross-encoder reranking for improved ranking
    5. Source-based deduplication to avoid redundant results

    The retriever balances precision and recall by combining complementary search
    strategies, providing more robust and accurate retrieval than either method alone.

    Attributes:
        collection: ChromaDB collection containing embedded documents.
        config: Configuration parameters controlling retrieval behavior.
        reranker: Cross-encoder model for optional reranking.

    Example:
        >>> from hybrid_rag import HybridRetriever, HybridRetrieverConfig
        >>> from hybrid_rag.vectordb import initialize_vector_db, get_sample_documents
        >>> docs = get_sample_documents()
        >>> collection = initialize_vector_db(docs)
        >>> config = HybridRetrieverConfig(semantic_weight=0.7, keyword_weight=0.3)
        >>> retriever = HybridRetriever(collection, config)
        >>> results = retriever.retrieve("How do I use offline maps?")
    """

    def __init__(
        self, collection: Collection, config: HybridRetrieverConfig | None = None
    ) -> None:
        """Initialize the hybrid retriever with a ChromaDB collection and configuration.

        Args:
            collection: ChromaDB collection containing embedded documents.
            config: Configuration parameters for retrieval and reranking.
                   If None, uses default configuration.

        Raises:
            ValueError: If collection is None or invalid.
            Exception: If reranker initialization fails.
        """
        if collection is None:
            raise ValueError("Collection cannot be None")

        self.collection = collection
        self.config = config or HybridRetrieverConfig()
        logger.debug(f"Initializing HybridRetriever with config: {self.config}")

        try:
            self.reranker = CrossEncoderReranker()
        except Exception as e:
            logger.warning(f"Failed to initialize reranker, reranking disabled: {e}")
            self.reranker = None

        # Initialize encoder for embedding queries
        try:
            logger.debug("Initializing SentenceTransformer encoder")
            self.encoder: SentenceTransformer = SentenceTransformer(
                "all-MiniLM-L6-v2"
            )
        except Exception as e:
            logger.error(f"Failed to initialize encoder: {e}")
            raise

        # Initialize L2 embedding cache
        self._embedding_cache: cachetools.LRUCache[str, np.ndarray] = (
            cachetools.LRUCache(maxsize=5000)
        )
        self._embedding_cache_hits: int = 0
        self._embedding_cache_misses: int = 0
        logger.debug("L2 embedding cache initialized with capacity 5000")

    def update_config(self, **kwargs: Any) -> HybridRetrieverConfig:
        """Update the retriever's configuration with new values.

        Updates configuration parameters and validates them before applying.
        Only provided parameters are updated.

        Args:
            **kwargs: Configuration parameters to update. Valid keys are:
                - semantic_top_k, keyword_top_k, final_top_k
                - semantic_weight, keyword_weight
                - enable_rerank, pre_rerank_top_k
                - collection_name

                Updating ``collection_name`` only changes the in-memory
                configuration value. It does not switch, rebind, or
                reinitialize ``self.collection`` for retrieval or storage.

        Returns:
            The new updated configuration object.

        Raises:
            ValueError: If any parameter is invalid or validation fails.
            TypeError: If an unknown parameter is provided.

        Example:
            >>> config = retriever.update_config(semantic_weight=0.8, keyword_weight=0.2)
            >>> retriever.config.semantic_weight
            0.8
        """
        try:
            logger.info(f"Updating retriever configuration with: {kwargs}")
            self.config = self.config.update(**kwargs)
            logger.info("Retriever configuration updated successfully")
            return self.config
        except (ValueError, TypeError) as e:
            logger.error(f"Configuration update failed: {e}")
            raise

    def _get_or_encode_embedding(self, query_text: str) -> np.ndarray:
        """Get or compute embedding for query text with L2 caching.

        Uses SHA-256 hash of query text as cache key. Checks cache first,
        returns cached embedding on hit. On miss, encodes query using
        SentenceTransformer model and caches result.

        Args:
            query_text: The query string to encode.

        Returns:
            np.ndarray: The embedding vector for the query text.

        Example:
            >>> embedding = retriever._get_or_encode_embedding("What is RAG?")
            >>> print(embedding.shape)
            (384,)
            >>> # Call again with same query - returns cached result
            >>> cached_embedding = retriever._get_or_encode_embedding("What is RAG?")
            >>> np.array_equal(embedding, cached_embedding)
            True
        """
        # Compute cache key from query text
        cache_key: str = hashlib.sha256(query_text.encode()).hexdigest()

        # Check cache
        if cache_key in self._embedding_cache:
            self._embedding_cache_hits += 1
            cached_embedding: np.ndarray = self._embedding_cache[cache_key]
            logger.debug(
                f"Embedding cache hit for query hash: {cache_key[:16]}... "
                f"(total hits: {self._embedding_cache_hits})"
            )
            return cached_embedding

        # Cache miss - encode the query
        self._embedding_cache_misses += 1
        logger.debug(
            f"Embedding cache miss for query hash: {cache_key[:16]}... "
            f"(total misses: {self._embedding_cache_misses})"
        )

        embedding: np.ndarray = self.encoder.encode(query_text)  # type: ignore[assignment]
        # Store in cache
        self._embedding_cache[cache_key] = embedding

        return embedding

    def _get_embedding_cache_stats(self) -> dict[str, Any]:
        """Get statistics about the L2 embedding cache.

        Returns cache hit/miss counts, current size, capacity, and hit rate.

        Returns:
            Dict with keys:
                - hits (int): Total cache hits
                - misses (int): Total cache misses
                - size (int): Current number of cached embeddings
                - capacity (int): Maximum capacity of cache
                - hit_rate (float): Hit rate as hits / (hits + misses),
                                   or 0.0 if no activity

        Example:
            >>> stats = retriever._get_embedding_cache_stats()
            >>> print(f"Cache hit rate: {stats['hit_rate']:.2%}")
            >>> print(f"Cached embeddings: {stats['size']}/{stats['capacity']}")
        """
        total_accesses: int = self._embedding_cache_hits + self._embedding_cache_misses
        hit_rate: float = (
            self._embedding_cache_hits / total_accesses
            if total_accesses > 0
            else 0.0
        )

        return {
            "hits": self._embedding_cache_hits,
            "misses": self._embedding_cache_misses,
            "size": len(self._embedding_cache),
            "capacity": self._embedding_cache.maxsize,
            "hit_rate": hit_rate,
        }

    def get_embedding_cache_stats(self) -> dict[str, Any]:
        """Public accessor for L2 embedding cache statistics.

        WHY: The /cache/stats endpoint needs to populate the l2_embedding_cache
        section of the layered stats schema (OPTB-008).  Exposing a public
        method avoids reaching into private internals from outside the class
        boundary.  The implementation delegates directly to the private helper
        so there is a single source of truth.

        Returns:
            Dict with keys: hits, misses, size, capacity, hit_rate.
            Same contract as _get_embedding_cache_stats().

        Example:
            >>> stats = retriever.get_embedding_cache_stats()
            >>> print(f"L2 hit rate: {stats['hit_rate']:.2%}")
        """
        # Delegate to the private implementation — single source of truth for
        # the stats computation logic.
        return self._get_embedding_cache_stats()

    def _dedupe_by_source(self, docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Remove duplicate documents from the same source URL.

        Keeps the first (highest-ranked) result per unique source and limits
        final output to config.final_top_k results. This prevents showing
        multiple chunks from the same document source.

        Args:
            docs: List of document dictionaries with metadata containing 'source'.

        Returns:
            Deduplicated list of documents, one per source, up to final_top_k.

        Example:
            >>> docs = [
            ...     {"id": "1", "metadata": {"source": "url1"}, "score": 0.9},
            ...     {"id": "2", "metadata": {"source": "url1"}, "score": 0.85},
            ...     {"id": "3", "metadata": {"source": "url2"}, "score": 0.8},
            ... ]
            >>> deduped = retriever._dedupe_by_source(docs)
            >>> len(deduped) == 2  # One per unique source
            True
        """
        deduped = []
        seen_sources = set()

        for doc in docs:
            source = doc.get("metadata", {}).get("source")
            source_key = source if source else doc.get("id")

            if source_key in seen_sources:
                logger.debug(f"Skipping duplicate source: {source_key}")
                continue

            seen_sources.add(source_key)
            deduped.append(doc)

            if len(deduped) >= self.config.final_top_k:
                logger.debug(f"Reached final_top_k limit: {self.config.final_top_k}")
                break

        return deduped

    def _semantic_search(self, query: str) -> list[dict[str, Any]]:
        """Perform semantic similarity search using embeddings.

        Queries the ChromaDB collection using the embedding of the input query
        and returns documents ranked by cosine similarity. The score represents
        how semantically similar the document is to the query.

        Args:
            query: Search query string to encode and match against documents.

        Returns:
            List of documents with embedding similarity scores in [0, 1].
            Higher scores indicate more similar documents.

        Raises:
            RetrievalError: If semantic search fails.
        """
        try:
            logger.debug(f"Performing semantic search for query: {query[:50]}...")
            
            # Get or encode embedding (with caching)
            query_embedding = self._get_or_encode_embedding(query)
            
            res = self.collection.query(
                query_embeddings=[query_embedding.tolist()],
                n_results=self.config.semantic_top_k,
                include=["documents", "distances", "metadatas"],
            )

            results = []
            for i, doc_id in enumerate(res["ids"][0]):
                # Cosine distance in [0, 1]: 0 = identical, so similarity = 1 - distance
                score = 1 - res["distances"][0][i]
                results.append(
                    {
                        "id": doc_id,
                        "text": res["documents"][0][i],
                        "metadata": res["metadatas"][0][i],
                        "score": score,
                    }
                )

            logger.debug(f"Semantic search returned {len(results)} results")
            return results

        except Exception as e:
            logger.error(f"Semantic search failed: {e}")
            raise RetrievalError(f"Semantic search failed: {e}") from e

    def _keyword_search(self, query: str) -> list[dict[str, Any]]:
        """Perform keyword-based search filtering stop words.

        Extracts keywords from the query (excluding common stop words) and performs
        full-text search on the document collection. Scores documents based on
        cumulative frequency of keyword matches.

        Args:
            query: Search query string to extract keywords from.

        Returns:
            List of documents matching keywords with aggregate match scores.
            Scores are normalized by the number of keywords found.

        Raises:
            RetrievalError: If keyword search fails.
        """
        keywords = [w for w in query.lower().split() if w not in STOP_WORDS]

        if not keywords:
            logger.debug("No keywords found after stop word filtering")
            return []

        try:
            logger.debug(f"Performing keyword search for keywords: {keywords}")
            results_dict: dict[str, dict[str, Any]] = {}

            for keyword in keywords:
                try:
                    res = self.collection.query(
                        query_texts=[keyword],
                        n_results=self.config.keyword_top_k,
                        where_document={"$contains": keyword},
                        include=["documents", "metadatas"],
                    )

                    if not res or not res.get("ids") or not res["ids"][0]:
                        logger.debug(f"No results for keyword: {keyword}")
                        continue

                    for i, doc_id in enumerate(res["ids"][0]):
                        if doc_id not in results_dict:
                            results_dict[doc_id] = {
                                "id": doc_id,
                                "text": res["documents"][0][i],
                                "metadata": res["metadatas"][0][i],
                                "score": 0.0,
                            }
                        # Normalize score by number of keywords
                        results_dict[doc_id]["score"] += 1.0 / len(keywords)

                except Exception as e:
                    logger.warning(f"Keyword search error for '{keyword}': {e}")
                    continue

            results = list(results_dict.values())
            logger.debug(f"Keyword search returned {len(results)} results")
            return results

        except Exception as e:
            logger.error(f"Keyword search failed: {e}")
            raise RetrievalError(f"Keyword search failed: {e}") from e

    def _fusion(
        self, semantic: list[dict[str, Any]], keyword: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Fuse semantic and keyword search results with configurable weights.

        Combines results from both search methods, aggregating scores for documents
        appearing in both result sets. Documents from semantic search are weighted by
        semantic_weight; keyword search results by keyword_weight.

        Args:
            semantic: Results from semantic search with 'score' key.
            keyword: Results from keyword search with 'score' key.

        Returns:
            Fused list of documents with combined weighted scores.

        Example:
            >>> semantic = [{"id": "1", "text": "doc1", "metadata": {}, "score": 0.8}]
            >>> keyword = [{"id": "1", "text": "doc1", "metadata": {}, "score": 0.9}]
            >>> fused = retriever._fusion(semantic, keyword)
            >>> # Score is weighted combination: 0.7*0.8 + 0.3*0.9
        """
        results: list[tuple] = []

        # Add semantic results with semantic weight
        for doc in semantic:
            id_ = doc["id"]
            text = doc["text"]
            metadata = doc["metadata"]
            score = self.config.semantic_weight * doc["score"]

            existing = next((item for item in results if item[0] == id_), None)
            if existing:
                idx = results.index(existing)
                results[idx] = (id_, text, metadata, existing[3] + score)
            else:
                results.append((id_, text, metadata, score))

        # Add keyword results with keyword weight
        for doc in keyword:
            id_ = doc["id"]
            text = doc["text"]
            metadata = doc["metadata"]
            score = self.config.keyword_weight * doc["score"]

            existing = next((item for item in results if item[0] == id_), None)
            if existing:
                idx = results.index(existing)
                results[idx] = (id_, text, metadata, existing[3] + score)
            else:
                results.append((id_, text, metadata, score))

        fused = [
            {"id": item[0], "text": item[1], "metadata": item[2], "score": item[3]}
            for item in results
        ]

        logger.debug(f"Fusion produced {len(fused)} results")
        return fused

    def retrieve(
        self, query: str, enable_rerank: bool | None = None
    ) -> list[dict[str, Any]]:
        """Execute hybrid retrieval pipeline to find most relevant documents.

        Performs semantic and keyword search, fuses results with configured weights,
        optionally reranks using cross-encoder, and returns deduplicated top results.

        The pipeline stages are:
        1. Clean query (remove special characters)
        2. Semantic search
        3. Keyword search
        4. Score fusion
        5. Optional reranking
        6. Deduplication by source

        Args:
            query: User search query string.
            enable_rerank: Optional per-request override for reranking behavior.
                If None, uses the retriever configuration value.

        Returns:
            List of relevant documents with scores, deduplicated by source.
            Returns up to final_top_k results.

        Raises:
            ValueError: If query is empty after cleaning.
            RetrievalError: If retrieval pipeline fails.

        Example:
            >>> results = retriever.retrieve("How do I find places on Google Maps?")
            >>> print(f"Found {len(results)} results")
            >>> for result in results:
            ...     print(f"Score: {result['score']:.3f}, Text: {result['text'][:50]}")
        """
        # Clean query by removing special characters
        cleaned_query = re.sub(r"[^\w\s?!]", "", query).strip()

        if not cleaned_query:
            raise ValueError("Query is empty after cleaning")

        try:
            logger.info(f"Starting retrieval for query: {cleaned_query[:50]}...")

            # Execute search strategies
            semantic = self._semantic_search(cleaned_query)
            keyword = self._keyword_search(cleaned_query)

            # Fuse results
            fused = self._fusion(semantic, keyword)

            # Apply per-request override without mutating global retriever configuration.
            rerank_enabled = (
                self.config.enable_rerank
                if enable_rerank is None
                else enable_rerank
            )

            # Optionally rerank results
            if rerank_enabled and self.reranker is not None:
                logger.debug("Applying cross-encoder reranking")
                candidates = sorted(
                    fused, key=lambda x: x["score"], reverse=True
                )[: self.config.pre_rerank_top_k]

                reranked = self.reranker.rerank(cleaned_query, candidates)
                final_results = self._dedupe_by_source(reranked)
            else:
                logger.debug("Reranking disabled or unavailable")
                ranked = sorted(fused, key=lambda x: x["score"], reverse=True)
                final_results = self._dedupe_by_source(ranked)

            logger.info(
                f"Retrieval complete: returned {len(final_results)} results"
            )
            return final_results

        except (ValueError, RetrievalError) as e:
            logger.error(f"Retrieval pipeline failed: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in retrieval pipeline: {e}")
            raise RetrievalError(f"Retrieval pipeline failed: {e}") from e
