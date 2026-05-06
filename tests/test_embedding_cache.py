"""Tests for the L2 embedding cache in HybridRetriever."""

import hashlib
import logging
from unittest.mock import MagicMock

import cachetools
import numpy as np
import pytest

from hybrid_rag import HybridRetriever, HybridRetrieverConfig
from hybrid_rag.vectordb import get_sample_documents, initialize_vector_db

logger = logging.getLogger(__name__)


@pytest.fixture
def retriever_fast() -> HybridRetriever:
    """HybridRetriever with a stub encoder — no model download, no ChromaDB.

    Bypasses __init__ and injects the minimum attributes needed for
    cache-structure and counter tests.  The encoder is a MagicMock so
    _get_or_encode_embedding() can still be called without a real model.
    """
    obj: HybridRetriever = object.__new__(HybridRetriever)
    obj.collection = MagicMock()
    obj.config = HybridRetrieverConfig(semantic_weight=0.7, keyword_weight=0.3)
    obj.reranker = None
    obj.encoder = MagicMock()
    obj.encoder.encode = lambda text: np.zeros(384, dtype=np.float32)
    obj._embedding_cache: cachetools.LRUCache = cachetools.LRUCache(maxsize=5000)
    obj._embedding_cache_hits = 0
    obj._embedding_cache_misses = 0
    return obj


@pytest.fixture
def retriever() -> HybridRetriever:
    """HybridRetriever backed by a real ChromaDB collection + sentence-transformer.

    Used only for tests that need real embeddings (similarity checks, retrieve()).
    Slow: loads the model on every call.
    """
    try:
        docs = get_sample_documents()
        collection = initialize_vector_db(docs)
        config = HybridRetrieverConfig(semantic_weight=0.7, keyword_weight=0.3)
        return HybridRetriever(collection, config)
    except Exception as e:
        pytest.skip(f"Skipping: retriever could not be initialized (network or model unavailable): {e}")


class TestEmbeddingCacheInitialization:
    """Test L2 embedding cache initialization."""

    def test_embedding_cache_initialized(self, retriever_fast: HybridRetriever) -> None:
        """_embedding_cache is initialized as LRUCache in __init__."""
        assert hasattr(retriever_fast, "_embedding_cache")
        assert retriever_fast._embedding_cache is not None

    def test_embedding_cache_has_correct_capacity(
        self, retriever_fast: HybridRetriever
    ) -> None:
        """_embedding_cache has default capacity of 5000."""
        assert retriever_fast._embedding_cache.maxsize == 5000

    def test_embedding_cache_hit_counter_initialized(
        self, retriever_fast: HybridRetriever
    ) -> None:
        """_embedding_cache_hits counter is initialized to 0."""
        assert hasattr(retriever_fast, "_embedding_cache_hits")
        assert retriever_fast._embedding_cache_hits == 0

    def test_embedding_cache_miss_counter_initialized(
        self, retriever_fast: HybridRetriever
    ) -> None:
        """_embedding_cache_misses counter is initialized to 0."""
        assert hasattr(retriever_fast, "_embedding_cache_misses")
        assert retriever_fast._embedding_cache_misses == 0


class TestGetOrEncodeEmbedding:
    """Test _get_or_encode_embedding wrapper method."""

    def test_method_exists(self, retriever_fast: HybridRetriever) -> None:
        """_get_or_encode_embedding method exists."""
        assert hasattr(retriever_fast, "_get_or_encode_embedding")
        assert callable(retriever_fast._get_or_encode_embedding)

    def test_embedding_cache_miss_on_first_call(
        self, retriever_fast: HybridRetriever
    ) -> None:
        """First call to _get_or_encode_embedding() caches result on miss."""
        query = "test query"
        embedding = retriever_fast._get_or_encode_embedding(query)

        assert isinstance(embedding, np.ndarray)
        assert len(embedding) > 0
        assert retriever_fast._embedding_cache_misses == 1
        assert retriever_fast._embedding_cache_hits == 0

    @pytest.mark.slow
    def test_embedding_cache_hit_on_second_call(
        self, retriever: HybridRetriever
    ) -> None:
        """Second call with same query returns cached result and increments hits."""
        query = "test query for caching"
        embedding1 = retriever._get_or_encode_embedding(query)
        embedding2 = retriever._get_or_encode_embedding(query)

        assert np.allclose(embedding1, embedding2)
        assert retriever._embedding_cache_misses == 1
        assert retriever._embedding_cache_hits == 1

    @pytest.mark.slow
    def test_different_queries_produce_different_embeddings(
        self, retriever: HybridRetriever
    ) -> None:
        """Different queries produce different embeddings (not from cache)."""
        query1 = "first query"
        query2 = "second query"

        embedding1 = retriever._get_or_encode_embedding(query1)
        embedding2 = retriever._get_or_encode_embedding(query2)

        assert not np.allclose(embedding1, embedding2)
        assert retriever._embedding_cache_misses == 2
        assert retriever._embedding_cache_hits == 0

    def test_cache_key_is_sha256_hash(self, retriever_fast: HybridRetriever) -> None:
        """Cache key is SHA-256 hash of query text."""
        query = "test query for hashing"
        retriever_fast._get_or_encode_embedding(query)

        expected_key = hashlib.sha256(query.encode()).hexdigest()
        assert expected_key in retriever_fast._embedding_cache

    def test_embedding_is_numpy_array(self, retriever_fast: HybridRetriever) -> None:
        """_get_or_encode_embedding returns np.ndarray."""
        query = "embedding type test"
        embedding = retriever_fast._get_or_encode_embedding(query)

        assert isinstance(embedding, np.ndarray)
        assert embedding.ndim == 1
        assert len(embedding) > 0


class TestRetrieveWithEmbeddingCache:
    """Test retrieve() method uses embedding cache."""

    @pytest.mark.slow
    def test_retrieve_updates_cache_hits(self, retriever: HybridRetriever) -> None:
        """retrieve() uses _get_or_encode_embedding and updates cache stats."""
        query = "How do I use Google Maps?"

        # First retrieve: cache miss
        results1 = retriever.retrieve(query)
        hits_after_first = retriever._embedding_cache_hits
        misses_after_first = retriever._embedding_cache_misses

        # Second retrieve with same query: cache hit
        results2 = retriever.retrieve(query)
        hits_after_second = retriever._embedding_cache_hits
        _misses_after_second = retriever._embedding_cache_misses

        # First call should have a miss
        assert misses_after_first >= 1

        # Second call should have an additional hit
        assert hits_after_second > hits_after_first

        # Results should be the same
        assert len(results1) == len(results2)

    @pytest.mark.slow
    def test_retrieve_works_normally(self, retriever: HybridRetriever) -> None:
        """retrieve() still returns correct results with embedding cache."""
        query = "Google Maps offline navigation"
        results = retriever.retrieve(query)

        # Should return results
        assert isinstance(results, list)
        assert len(results) > 0

        # Each result should have required keys
        for result in results:
            assert "id" in result
            assert "text" in result
            assert "score" in result
            assert "metadata" in result


class TestEmbeddingCacheStats:
    """Test embedding cache statistics."""

    def test_get_embedding_cache_stats_method_exists(
        self, retriever_fast: HybridRetriever
    ) -> None:
        """_get_embedding_cache_stats method exists."""
        assert hasattr(retriever_fast, "_get_embedding_cache_stats")
        assert callable(retriever_fast._get_embedding_cache_stats)

    def test_embedding_cache_stats_format(
        self, retriever_fast: HybridRetriever
    ) -> None:
        """_get_embedding_cache_stats returns correct structure."""
        stats = retriever_fast._get_embedding_cache_stats()

        assert isinstance(stats, dict)
        assert "hits" in stats
        assert "misses" in stats
        assert "size" in stats
        assert "capacity" in stats
        assert "hit_rate" in stats

    def test_embedding_cache_stats_values(
        self, retriever_fast: HybridRetriever
    ) -> None:
        """_get_embedding_cache_stats returns correct values."""
        query = "test query for stats"
        retriever_fast._get_or_encode_embedding(query)
        retriever_fast._get_or_encode_embedding(query)

        stats = retriever_fast._get_embedding_cache_stats()

        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["size"] == 1
        assert stats["capacity"] == 5000
        assert stats["hit_rate"] == 0.5

    def test_embedding_cache_hit_rate_calculation(
        self, retriever_fast: HybridRetriever
    ) -> None:
        """hit_rate is calculated correctly: hits / (hits + misses)."""
        retriever_fast._get_or_encode_embedding("query1")
        retriever_fast._get_or_encode_embedding("query2")
        retriever_fast._get_or_encode_embedding("query3")
        retriever_fast._get_or_encode_embedding("query1")
        retriever_fast._get_or_encode_embedding("query2")

        stats = retriever_fast._get_embedding_cache_stats()
        assert stats["hit_rate"] == 0.4

    def test_embedding_cache_hit_rate_zero_when_no_activity(
        self, retriever_fast: HybridRetriever
    ) -> None:
        """hit_rate is 0.0 when no cache activity."""
        stats = retriever_fast._get_embedding_cache_stats()
        assert stats["hit_rate"] == 0.0

    def test_embedding_cache_hit_rate_one_on_all_hits(
        self, retriever: HybridRetriever
    ) -> None:
        """hit_rate is 0.75 when three of four lookups are hits."""
        retriever._get_or_encode_embedding("query1")
        retriever._get_or_encode_embedding("query1")
        retriever._get_or_encode_embedding("query1")
        retriever._get_or_encode_embedding("query1")

        stats = retriever._get_embedding_cache_stats()
        assert stats["hit_rate"] == 0.75


class TestEmbeddingCacheTypeHints:
    """Test that type hints are present on new methods."""

    def test_get_or_encode_embedding_has_return_type(
        self, retriever_fast: HybridRetriever
    ) -> None:
        """_get_or_encode_embedding has return type annotation."""
        import inspect

        method = retriever_fast._get_or_encode_embedding
        sig = inspect.signature(method)
        assert sig.return_annotation != inspect.Signature.empty

    def test_get_embedding_cache_stats_has_return_type(
        self, retriever_fast: HybridRetriever
    ) -> None:
        """_get_embedding_cache_stats has return type annotation."""
        import inspect

        method = retriever_fast._get_embedding_cache_stats
        sig = inspect.signature(method)
        assert sig.return_annotation != inspect.Signature.empty


class TestEmbeddingCacheDocstrings:
    """Test that new methods have Google-style docstrings."""

    def test_get_or_encode_embedding_has_docstring(
        self, retriever_fast: HybridRetriever
    ) -> None:
        """_get_or_encode_embedding has comprehensive docstring."""
        method = retriever_fast._get_or_encode_embedding
        assert method.__doc__ is not None
        assert len(method.__doc__) > 50
        assert "Example" in method.__doc__

    def test_get_embedding_cache_stats_has_docstring(
        self, retriever_fast: HybridRetriever
    ) -> None:
        """_get_embedding_cache_stats has comprehensive docstring."""
        method = retriever_fast._get_embedding_cache_stats
        assert method.__doc__ is not None
        assert len(method.__doc__) > 50
