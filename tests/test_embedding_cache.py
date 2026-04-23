"""Tests for the L2 embedding cache in HybridRetriever."""

import hashlib
import logging

import numpy as np
import pytest

from hybrid_rag import HybridRetriever, HybridRetrieverConfig
from hybrid_rag.vectordb import get_sample_documents, initialize_vector_db

logger = logging.getLogger(__name__)


@pytest.fixture
def retriever() -> HybridRetriever:
    """Create a HybridRetriever instance for testing."""
    try:
        docs = get_sample_documents()
        collection = initialize_vector_db(docs)
        config = HybridRetrieverConfig(semantic_weight=0.7, keyword_weight=0.3)
        return HybridRetriever(collection, config)
    except Exception as e:
        pytest.skip(f"Skipping: retriever could not be initialized (network or model unavailable): {e}")


class TestEmbeddingCacheInitialization:
    """Test L2 embedding cache initialization."""

    def test_embedding_cache_initialized(self, retriever: HybridRetriever) -> None:
        """_embedding_cache is initialized as LRUCache in __init__."""
        assert hasattr(retriever, "_embedding_cache")
        assert retriever._embedding_cache is not None

    def test_embedding_cache_has_correct_capacity(
        self, retriever: HybridRetriever
    ) -> None:
        """_embedding_cache has default capacity of 5000."""
        # LRUCache has a 'maxsize' attribute
        assert retriever._embedding_cache.maxsize == 5000

    def test_embedding_cache_hit_counter_initialized(
        self, retriever: HybridRetriever
    ) -> None:
        """_embedding_cache_hits counter is initialized to 0."""
        assert hasattr(retriever, "_embedding_cache_hits")
        assert retriever._embedding_cache_hits == 0

    def test_embedding_cache_miss_counter_initialized(
        self, retriever: HybridRetriever
    ) -> None:
        """_embedding_cache_misses counter is initialized to 0."""
        assert hasattr(retriever, "_embedding_cache_misses")
        assert retriever._embedding_cache_misses == 0


class TestGetOrEncodeEmbedding:
    """Test _get_or_encode_embedding wrapper method."""

    def test_method_exists(self, retriever: HybridRetriever) -> None:
        """_get_or_encode_embedding method exists."""
        assert hasattr(retriever, "_get_or_encode_embedding")
        assert callable(retriever._get_or_encode_embedding)

    def test_embedding_cache_miss_on_first_call(
        self, retriever: HybridRetriever
    ) -> None:
        """First call to _get_or_encode_embedding() caches result on miss."""
        query = "test query"
        embedding = retriever._get_or_encode_embedding(query)

        # Should return an ndarray
        assert isinstance(embedding, np.ndarray)
        assert len(embedding) > 0

        # Cache should have 1 miss and 0 hits
        assert retriever._embedding_cache_misses == 1
        assert retriever._embedding_cache_hits == 0

    def test_embedding_cache_hit_on_second_call(
        self, retriever: HybridRetriever
    ) -> None:
        """Second call with same query returns cached result and increments hits."""
        query = "test query for caching"
        embedding1 = retriever._get_or_encode_embedding(query)
        embedding2 = retriever._get_or_encode_embedding(query)

        # Both should be identical numpy arrays
        assert np.allclose(embedding1, embedding2)

        # After 2 calls: 1 miss + 1 hit
        assert retriever._embedding_cache_misses == 1
        assert retriever._embedding_cache_hits == 1

    def test_different_queries_produce_different_embeddings(
        self, retriever: HybridRetriever
    ) -> None:
        """Different queries produce different embeddings (not from cache)."""
        query1 = "first query"
        query2 = "second query"

        embedding1 = retriever._get_or_encode_embedding(query1)
        embedding2 = retriever._get_or_encode_embedding(query2)

        # Embeddings should be different
        assert not np.allclose(embedding1, embedding2)

        # Both should be misses
        assert retriever._embedding_cache_misses == 2
        assert retriever._embedding_cache_hits == 0

    def test_cache_key_is_sha256_hash(self, retriever: HybridRetriever) -> None:
        """Cache key is SHA-256 hash of query text."""
        query = "test query for hashing"
        embedding = retriever._get_or_encode_embedding(query)

        # Compute expected cache key
        expected_key = hashlib.sha256(query.encode()).hexdigest()

        # Cache should contain the key
        assert expected_key in retriever._embedding_cache

    def test_embedding_is_numpy_array(self, retriever: HybridRetriever) -> None:
        """_get_or_encode_embedding returns np.ndarray."""
        query = "embedding type test"
        embedding = retriever._get_or_encode_embedding(query)

        assert isinstance(embedding, np.ndarray)
        assert embedding.ndim == 1  # Should be 1D array
        assert len(embedding) > 0


class TestRetrieveWithEmbeddingCache:
    """Test retrieve() method uses embedding cache."""

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
        misses_after_second = retriever._embedding_cache_misses

        # First call should have a miss
        assert misses_after_first >= 1

        # Second call should have an additional hit
        assert hits_after_second > hits_after_first

        # Results should be the same
        assert len(results1) == len(results2)

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
        self, retriever: HybridRetriever
    ) -> None:
        """_get_embedding_cache_stats method exists."""
        assert hasattr(retriever, "_get_embedding_cache_stats")
        assert callable(retriever._get_embedding_cache_stats)

    def test_embedding_cache_stats_format(
        self, retriever: HybridRetriever
    ) -> None:
        """_get_embedding_cache_stats returns correct structure."""
        stats = retriever._get_embedding_cache_stats()

        assert isinstance(stats, dict)
        assert "hits" in stats
        assert "misses" in stats
        assert "size" in stats
        assert "capacity" in stats
        assert "hit_rate" in stats

    def test_embedding_cache_stats_values(
        self, retriever: HybridRetriever
    ) -> None:
        """_get_embedding_cache_stats returns correct values."""
        query = "test query for stats"
        # First call: miss
        retriever._get_or_encode_embedding(query)
        # Second call: hit
        retriever._get_or_encode_embedding(query)

        stats = retriever._get_embedding_cache_stats()

        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["size"] == 1
        assert stats["capacity"] == 5000
        assert stats["hit_rate"] == 0.5  # 1 hit / (1 hit + 1 miss)

    def test_embedding_cache_hit_rate_calculation(
        self, retriever: HybridRetriever
    ) -> None:
        """hit_rate is calculated correctly: hits / (hits + misses)."""
        # 3 misses
        retriever._get_or_encode_embedding("query1")
        retriever._get_or_encode_embedding("query2")
        retriever._get_or_encode_embedding("query3")

        # 2 hits
        retriever._get_or_encode_embedding("query1")
        retriever._get_or_encode_embedding("query2")

        stats = retriever._get_embedding_cache_stats()

        # hit_rate = 2 / (2 + 3) = 0.4
        assert stats["hit_rate"] == 0.4

    def test_embedding_cache_hit_rate_zero_when_no_activity(
        self, retriever: HybridRetriever
    ) -> None:
        """hit_rate is 0.0 when no cache activity."""
        stats = retriever._get_embedding_cache_stats()
        assert stats["hit_rate"] == 0.0

    def test_embedding_cache_hit_rate_one_on_all_hits(
        self, retriever: HybridRetriever
    ) -> None:
        """hit_rate is 1.0 when all lookups are hits."""
        # Single miss
        retriever._get_or_encode_embedding("query1")

        # Multiple hits on same query
        retriever._get_or_encode_embedding("query1")
        retriever._get_or_encode_embedding("query1")
        retriever._get_or_encode_embedding("query1")

        stats = retriever._get_embedding_cache_stats()

        # hit_rate = 3 / (3 + 1) = 0.75
        assert stats["hit_rate"] == 0.75


class TestEmbeddingCacheTypeHints:
    """Test that type hints are present on new methods."""

    def test_get_or_encode_embedding_has_return_type(
        self, retriever: HybridRetriever
    ) -> None:
        """_get_or_encode_embedding has return type annotation."""
        import inspect

        method = retriever._get_or_encode_embedding
        sig = inspect.signature(method)
        assert sig.return_annotation != inspect.Signature.empty

    def test_get_embedding_cache_stats_has_return_type(
        self, retriever: HybridRetriever
    ) -> None:
        """_get_embedding_cache_stats has return type annotation."""
        import inspect

        method = retriever._get_embedding_cache_stats
        sig = inspect.signature(method)
        assert sig.return_annotation != inspect.Signature.empty


class TestEmbeddingCacheDocstrings:
    """Test that new methods have Google-style docstrings."""

    def test_get_or_encode_embedding_has_docstring(
        self, retriever: HybridRetriever
    ) -> None:
        """_get_or_encode_embedding has comprehensive docstring."""
        method = retriever._get_or_encode_embedding
        assert method.__doc__ is not None
        assert len(method.__doc__) > 50
        # Should contain Examples section
        assert "Example" in method.__doc__

    def test_get_embedding_cache_stats_has_docstring(
        self, retriever: HybridRetriever
    ) -> None:
        """_get_embedding_cache_stats has comprehensive docstring."""
        method = retriever._get_embedding_cache_stats
        assert method.__doc__ is not None
        assert len(method.__doc__) > 50
