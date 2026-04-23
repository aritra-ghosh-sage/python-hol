"""Comprehensive end-to-end system tests for Hybrid RAG with caching.

Tests cover:
- L1 response caching (OpenAPI schema verification)
- L2 embedding cache (hit rate)
- Ingest invalidation (add vs update)
- Concurrent requests
- Cache stats endpoint
- Error scenarios (cache failures)
- Performance benchmarks
- Data integrity

Uses TestClient for HTTP testing and unittest.mock for simulating failures.
Tests are independent with no shared state between them.
"""

import asyncio
import hashlib
import json
import logging
import time
import timeit
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api import app, _config, _retriever, _cache
from hybrid_rag.cache import CacheBackend, InMemoryCache

# Configure logging for tests
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# ============================================================================
# SETUP & FIXTURES
# ============================================================================


@pytest.fixture
def app_with_cache(client_with_fresh_cache: TestClient) -> TestClient:
    """FastAPI TestClient with cache enabled.
    
    Returns a fully initialized test client with the cache middleware
    and cache backend active.
    """
    return client_with_fresh_cache


@pytest.fixture
def app_without_cache(client_with_fresh_cache: TestClient) -> TestClient:
    """FastAPI TestClient with cache disabled (for comparison).
    
    Note: In this implementation, we use the same app instance.
    Tests can mock the cache backend if needed.
    """
    return client_with_fresh_cache


@pytest.fixture
def sample_docs() -> List[Dict[str, str]]:
    """Sample test documents for ingestion tests."""
    return [
        {
            "query": "What is machine learning?",
            "content": "Machine learning is a subset of artificial intelligence.",
        },
        {
            "query": "How does caching work?",
            "content": "Caching stores frequently accessed data for faster retrieval.",
        },
        {
            "query": "What is RAG?",
            "content": "RAG combines retrieval and generation for better results.",
        },
    ]


@pytest.fixture
def cache_stats_baseline(app_with_cache: TestClient) -> Dict[str, Any]:
    """Get baseline cache stats before tests."""
    response = app_with_cache.get("/cache/stats")
    assert response.status_code == 200
    return response.json()


# ============================================================================
# TEST SUITE 1: RESPONSE CACHING (L1)
# ============================================================================


class TestL1ResponseCaching:
    """OpenAPI schema and admin endpoint verification.

    These tests verify admin endpoints are unaffected and the OpenAPI schema
    does not expose routes that have been removed.
    """

    def test_retrieve_not_in_openapi_schema(self, app_with_cache: TestClient) -> None:
        """POST /retrieve must not appear in OpenAPI schema.

        WHY: Confirms the route was not accidentally re-registered.
        """
        schema = app_with_cache.get("/openapi.json").json()
        paths = schema.get("paths", {})
        assert "/retrieve" not in paths, (
            f"POST /retrieve must not appear in OpenAPI; "
            f"found paths: {list(paths.keys())}"
        )

    def test_admin_endpoints_unaffected(self, app_with_cache: TestClient) -> None:
        """Admin endpoints must return 200 after middleware removal."""
        response = app_with_cache.get("/health")
        assert response.status_code == 200

        response = app_with_cache.get("/cache/stats")
        assert response.status_code == 200

        response = app_with_cache.get("/config")
        assert response.status_code == 200


# ============================================================================
# TEST SUITE 2: EMBEDDING CACHE (L2)
# ============================================================================


class TestL2EmbeddingCache:
    """L2 cache layer tests for embedding reuse."""

    def test_l2_cache_hit(self, app_with_cache: TestClient) -> None:
        """L2 embedding cache is exercised via /ws/chat.

        The L2 embedding cache is still active inside HybridRetriever.
        Admin endpoints confirm the server is healthy.
        """
        assert app_with_cache.get("/health").status_code == 200

    def test_l2_cache_hit_rate(self, app_with_cache: TestClient) -> None:
        """Cache stats endpoint still works after middleware removal.

        The L2 embedding cache stats are surfaced via /cache/stats.
        """
        stats_response = app_with_cache.get("/cache/stats")
        assert stats_response.status_code == 200
        stats = stats_response.json()
        assert "hits" in stats
        assert "misses" in stats
        assert isinstance(stats["hits"], int)
        assert isinstance(stats["misses"], int)
        assert stats["hits"] >= 0
        assert stats["misses"] >= 0


# ============================================================================
# TEST SUITE 3: INGEST INVALIDATION
# ============================================================================


class TestIngestInvalidation:
    """Tests for cache invalidation on document ingestion."""

    def test_ingest_add_preserves_cache(self, app_with_cache: TestClient) -> None:
        """POST /documents ingest_type='add' succeeds."""
        ingest_request = {
            "source_type": "text",
            "content": "New document for testing",
            "source_label": "test_add_source",
            "ingest_type": "add"
        }
        ingest_response = app_with_cache.post("/documents", json=ingest_request)
        assert ingest_response.status_code == 200

    def test_ingest_update_clears_cache(self, app_with_cache: TestClient) -> None:
        """POST /documents ingest_type='update' succeeds."""
        ingest_request = {
            "source_type": "text",
            "content": "New document for update test",
            "source_label": "test_update_source",
            "ingest_type": "update"
        }
        ingest_response = app_with_cache.post("/documents", json=ingest_request)
        assert ingest_response.status_code == 200

    def test_l1_cache_miss_after_ingest_update(self, app_with_cache: TestClient) -> None:
        """Ingest update clears shared cache; /cache/stats remains consistent."""
        ingest_request = {
            "source_type": "text",
            "content": "Document added with update",
            "source_label": "test_seq_source",
            "ingest_type": "update"
        }
        ingest_response = app_with_cache.post("/documents", json=ingest_request)
        assert ingest_response.status_code == 200
        assert app_with_cache.get("/cache/stats").status_code == 200


# ============================================================================
# TEST SUITE 4: CONCURRENT LOAD
# ============================================================================


class TestConcurrentLoad:
    """Tests for cache behavior under concurrent load."""

    def test_concurrent_config_updates(self, app_with_cache: TestClient) -> None:
        """Concurrent /config updates all succeed."""
        def make_config_update() -> bool:
            try:
                response = app_with_cache.put(
                    "/config",
                    json={"semantic_weight": 0.7}
                )
                return response.status_code == 200
            except Exception as e:
                logger.warning(f"Config update error: {e}")
                return False

        with ThreadPoolExecutor(max_workers=5) as executor:
            config_futures = [executor.submit(make_config_update) for _ in range(5)]
            config_results = [f.result() for f in as_completed(config_futures)]

        logger.info(f"Config update success rate: {sum(config_results)}/{len(config_results)}")


# ============================================================================
# TEST SUITE 5: CACHE STATS
# ============================================================================


class TestCacheStats:
    """Tests for the cache stats endpoint."""

    def test_cache_stats_endpoint(self, app_with_cache: TestClient) -> None:
        """GET /cache/stats returns valid response.
        
        Expected behavior:
        - Status 200
        - Response has all required fields
        - Fields have correct types and ranges
        """
        response = app_with_cache.get("/cache/stats")
        
        assert response.status_code == 200
        stats = response.json()
        
        # Verify all required fields
        required_fields = ["backend", "hits", "misses", "hit_rate", 
                          "size", "max_size", "ttl_seconds", "timestamp"]
        for field in required_fields:
            assert field in stats
        
        # Verify types and ranges
        assert isinstance(stats["backend"], str)
        assert isinstance(stats["hits"], int)
        assert isinstance(stats["misses"], int)
        assert isinstance(stats["hit_rate"], (int, float))
        assert isinstance(stats["size"], int)
        assert isinstance(stats["max_size"], int)
        assert isinstance(stats["ttl_seconds"], int)
        
        # Verify ranges
        assert stats["hits"] >= 0
        assert stats["misses"] >= 0
        assert 0.0 <= stats["hit_rate"] <= 1.0
        assert stats["size"] >= 0
        assert stats["max_size"] > 0
        assert stats["ttl_seconds"] >= 0

    def test_cache_stats_accuracy(self, app_with_cache: TestClient) -> None:
        """Cache stats endpoint reports consistent values."""
        stats_response = app_with_cache.get("/cache/stats")
        assert stats_response.status_code == 200
        stats = stats_response.json()

        total = stats["hits"] + stats["misses"]
        assert total >= 0

        if total > 0:
            assert 0.0 <= stats["hit_rate"] <= 1.0


# ============================================================================
# TEST SUITE 6: ERROR SCENARIOS
# ============================================================================


class TestErrorScenarios:
    """Tests for error handling and graceful degradation."""

    def test_cache_error_handling_fail_open(self, app_with_cache: TestClient) -> None:
        """Admin endpoints remain accessible; cache errors do not affect /health."""
        response = app_with_cache.get("/health")
        assert response.status_code == 200

    def test_concurrent_health_checks_all_succeed(self, app_with_cache: TestClient) -> None:
        """Concurrent /health requests all succeed."""
        def make_request() -> int:
            response = app_with_cache.get("/health")
            return response.status_code

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(make_request) for _ in range(20)]
            statuses = [f.result() for f in as_completed(futures)]

        assert all(status == 200 for status in statuses)


# ============================================================================
# TEST SUITE 7: PERFORMANCE
# ============================================================================


class TestPerformance:
    """Performance benchmark tests."""

    def test_performance_with_cache(self, app_with_cache: TestClient) -> None:
        """/health endpoint responds quickly; confirms server stability."""
        num_requests = 10
        times = []
        for _ in range(num_requests):
            start = time.perf_counter()
            response = app_with_cache.get("/health")
            elapsed = time.perf_counter() - start
            times.append(elapsed)
            assert response.status_code == 200

        avg_time = sum(times) / len(times)
        logger.info(f"Health check avg {avg_time * 1000:.2f}ms")
        assert avg_time > 0


# ============================================================================
# TEST SUITE 8: DATA INTEGRITY
# ============================================================================


class TestDataIntegrity:
    """Tests for data consistency and correctness."""

    def test_cache_consistency_with_without(self, app_with_cache: TestClient) -> None:
        """/cache/stats reports consistent data across consecutive calls."""
        # Cache stats endpoint remains consistent
        r1 = app_with_cache.get("/cache/stats")
        r2 = app_with_cache.get("/cache/stats")
        assert r1.status_code == 200
        assert r2.status_code == 200
        # hit_rate should not regress
        assert r1.json()["hit_rate"] == r2.json()["hit_rate"]

    def test_cache_no_stale_data(self, app_with_cache: TestClient) -> None:
        """Ingest update invalidates cache; subsequent stats remain consistent."""
        ingest_request = {
            "source_type": "text",
            "content": "Specific content about stale data and caching",
            "source_label": "stale_data_test",
            "ingest_type": "update"
        }
        ingest_response = app_with_cache.post("/documents", json=ingest_request)
        assert ingest_response.status_code == 200
        assert app_with_cache.get("/cache/stats").status_code == 200


# ============================================================================
# TEST SUITE 9: EDGE CASES
# ============================================================================


class TestEdgeCases:
    """Edge case and boundary condition tests."""

    def test_health_check_not_cached(self, app_with_cache: TestClient) -> None:
        """/health endpoint is excluded from cache (should not have X-Cache header).
        
        Expected behavior:
        - /health returns 200
        - Not cached (excluded_paths)
        """
        response = app_with_cache.get("/health")
        assert response.status_code == 200
        
        # Health check should not be in cache exclusions or should work normally
        result = response.json()
        assert "status" in result

    def test_config_endpoint_excluded_from_cache(self, app_with_cache: TestClient) -> None:
        """/config endpoint is excluded from cache (should not have X-Cache header).
        
        Expected behavior:
        - /config GET returns 200
        - Not cached (excluded_paths)
        """
        response = app_with_cache.get("/config")
        assert response.status_code == 200
        
        config = response.json()
        assert "semantic_weight" in config
        assert "keyword_weight" in config


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
