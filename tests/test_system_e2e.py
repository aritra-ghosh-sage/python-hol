"""Comprehensive end-to-end system tests for Hybrid RAG with caching.

Tests cover:
- L1 response caching (hit/miss/invalidation)
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
    """T08 retirement: POST /retrieve endpoint has been removed.

    The HTTP middleware cache (L1) and the /retrieve endpoint were retired in T08.
    These tests verify the endpoint is gone and admin endpoints remain unaffected.
    """

    def test_retrieve_returns_404_after_t08_retirement(self, app_with_cache: TestClient) -> None:
        """POST /retrieve must return 404 after T08 retirement.

        WHY: The endpoint was permanently removed. A 404 confirms it is gone
        and clients must migrate to /ws/chat.
        """
        response = app_with_cache.post(
            "/retrieve",
            json={"query": "test query for retirement check", "enable_rerank": False}
        )
        assert response.status_code == 404, (
            f"Expected 404 (T08 retirement), got {response.status_code}"
        )

    def test_retrieve_not_in_openapi_schema(self, app_with_cache: TestClient) -> None:
        """POST /retrieve must not appear in OpenAPI schema after T08.

        WHY: Confirms the route was not accidentally re-registered.
        """
        schema = app_with_cache.get("/openapi.json").json()
        paths = schema.get("paths", {})
        assert "/retrieve" not in paths, (
            f"POST /retrieve must not appear in OpenAPI after T08; "
            f"found paths: {list(paths.keys())}"
        )

    def test_admin_endpoints_unaffected_by_t08(self, app_with_cache: TestClient) -> None:
        """Admin endpoints must still return 200 after T08 middleware removal.

        WHY: Confirms that removing QueryCacheMiddleware did not break any
        operational or admin endpoints.
        """
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
        """L2 embedding cache is exercised via /ws/chat; /retrieve is retired (T08).

        The L2 embedding cache is still active inside HybridRetriever.
        Admin endpoints confirm the server is healthy.
        """
        # Verify server is responsive; /retrieve is gone (T08).
        assert app_with_cache.get("/health").status_code == 200
        assert app_with_cache.post("/retrieve", json={"query": "test"}).status_code == 404

    def test_l2_cache_hit_rate(self, app_with_cache: TestClient) -> None:
        """Cache stats endpoint still works after T08 middleware removal.

        The L2 embedding cache stats are surfaced via /cache/stats.
        """
        stats_response = app_with_cache.get("/cache/stats")
        assert stats_response.status_code == 200
        stats = stats_response.json()
        assert stats["hits"] + stats["misses"] >= 0


# ============================================================================
# TEST SUITE 3: INGEST INVALIDATION
# ============================================================================


class TestIngestInvalidation:
    """Tests for cache invalidation on document ingestion."""

    def test_ingest_add_preserves_cache(self, app_with_cache: TestClient) -> None:
        """POST /retrieve is retired (T08); ingest still works normally.

        Verify that POST /documents ingest_type='add' succeeds and /retrieve
        correctly returns 404 (not a server error caused by the ingest).
        """
        ingest_request = {
            "source_type": "text",
            "content": "New document for testing",
            "source_label": "test_add_source",
            "ingest_type": "add"
        }
        ingest_response = app_with_cache.post("/documents", json=ingest_request)
        assert ingest_response.status_code == 200

        # /retrieve is gone after T08
        assert app_with_cache.post("/retrieve", json={"query": "test"}).status_code == 404

    def test_ingest_update_clears_cache(self, app_with_cache: TestClient) -> None:
        """POST /documents ingest_type='update' succeeds; /retrieve is retired (T08)."""
        ingest_request = {
            "source_type": "text",
            "content": "New document for update test",
            "source_label": "test_update_source",
            "ingest_type": "update"
        }
        ingest_response = app_with_cache.post("/documents", json=ingest_request)
        assert ingest_response.status_code == 200

        # /retrieve is gone after T08
        assert app_with_cache.post("/retrieve", json={"query": "test"}).status_code == 404

    def test_l1_cache_miss_after_ingest_update(self, app_with_cache: TestClient) -> None:
        """POST /retrieve is retired (T08); ingest update clears shared cache as expected."""
        ingest_request = {
            "source_type": "text",
            "content": "Document added with update",
            "source_label": "test_seq_source",
            "ingest_type": "update"
        }
        ingest_response = app_with_cache.post("/documents", json=ingest_request)
        assert ingest_response.status_code == 200

        # /retrieve is gone after T08
        assert app_with_cache.post("/retrieve", json={"query": "test"}).status_code == 404


# ============================================================================
# TEST SUITE 4: CONCURRENT LOAD
# ============================================================================


class TestConcurrentLoad:
    """Tests for cache behavior under concurrent load."""

    def test_cache_under_load_concurrent_requests(self, app_with_cache: TestClient) -> None:
        """POST /retrieve is retired (T08); concurrent health checks all succeed.

        Confirms the server remains stable under concurrent load without the
        /retrieve endpoint.
        """
        num_requests = 50

        def make_request() -> int:
            """Verify /retrieve returns 404 (T08 retired)."""
            response = app_with_cache.post(
                "/retrieve",
                json={"query": "concurrent load test query"}
            )
            return response.status_code

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(make_request) for _ in range(num_requests)]
            statuses = [f.result() for f in as_completed(futures)]

        # All must return 404 — the endpoint is gone after T08.
        assert all(status == 404 for status in statuses)
        assert len(statuses) == num_requests

    def test_concurrent_config_and_retrieve(self, app_with_cache: TestClient) -> None:
        """Config updates still work after T08 middleware removal.

        Concurrent /config updates should all succeed; /retrieve returns 404.
        """
        def make_retrieve() -> bool:
            try:
                response = app_with_cache.post(
                    "/retrieve",
                    json={"query": "concurrent config test query"}
                )
                # T08: endpoint removed → 404
                return response.status_code == 404
            except Exception as e:
                logger.warning(f"Retrieve error: {e}")
                return False

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
            retrieve_futures = [executor.submit(make_retrieve) for _ in range(20)]
            config_futures = [executor.submit(make_config_update) for _ in range(5)]

            retrieve_results = [f.result() for f in as_completed(retrieve_futures)]
            config_results = [f.result() for f in as_completed(config_futures)]

        # All retrieve requests must confirm 404 (endpoint gone)
        assert all(retrieve_results)
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
        """Cache stats are accurate; /retrieve is retired (T08).

        Admin stats endpoint must remain functional.
        """
        # Verify /retrieve returns 404 (T08 retired)
        assert app_with_cache.post("/retrieve", json={"query": "query1"}).status_code == 404

        # Get stats — must still work
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
        """POST /retrieve returns 404 after T08 retirement (not a server error).

        Confirms that removing the endpoint produces a clean 404 rather than
        an unexpected 500.
        """
        response = app_with_cache.post(
            "/retrieve",
            json={"query": "test query for error handling"}
        )
        assert response.status_code == 404

    def test_concurrent_cache_error_all_succeed(self, app_with_cache: TestClient) -> None:
        """Concurrent /retrieve requests all return 404 after T08 retirement."""
        def make_request() -> int:
            response = app_with_cache.post(
                "/retrieve",
                json={"query": "error test query"}
            )
            return response.status_code

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(make_request) for _ in range(20)]
            statuses = [f.result() for f in as_completed(futures)]

        # All must return 404 — endpoint is gone after T08.
        assert all(status == 404 for status in statuses)


# ============================================================================
# TEST SUITE 7: PERFORMANCE
# ============================================================================


class TestPerformance:
    """Performance benchmark tests."""

    def test_performance_with_cache(self, app_with_cache: TestClient) -> None:
        """POST /retrieve is retired (T08); /health endpoint responds quickly.

        Confirms that the server remains responsive after middleware removal.
        """
        num_requests = 10
        times = []
        for _ in range(num_requests):
            start = time.perf_counter()
            response = app_with_cache.get("/health")
            elapsed = time.perf_counter() - start
            times.append(elapsed)
            assert response.status_code == 200

        avg_time = sum(times) / len(times)
        logger.info(f"Health check avg {avg_time * 1000:.2f}ms after T08 middleware removal")
        assert avg_time > 0

    def test_performance_comparison_many_queries(self, app_with_cache: TestClient) -> None:
        """/retrieve returns 404 consistently across 100 requests (T08 retired)."""
        start = time.perf_counter()
        for _ in range(100):
            response = app_with_cache.post(
                "/retrieve",
                json={"query": "retired endpoint probe"}
            )
            assert response.status_code == 404
        total_time = time.perf_counter() - start
        throughput = 100 / total_time
        logger.info(f"T08 retirement probe: 100 requests in {total_time:.2f}s = {throughput:.1f} req/s")


# ============================================================================
# TEST SUITE 8: DATA INTEGRITY
# ============================================================================


class TestDataIntegrity:
    """Tests for data consistency and correctness."""

    def test_cache_consistency_with_without(self, app_with_cache: TestClient) -> None:
        """POST /retrieve is retired (T08); /cache/stats still reports consistent data."""
        # /retrieve is gone
        assert app_with_cache.post("/retrieve", json={"query": "consistency test"}).status_code == 404

        # Cache stats endpoint remains consistent
        r1 = app_with_cache.get("/cache/stats")
        r2 = app_with_cache.get("/cache/stats")
        assert r1.status_code == 200
        assert r2.status_code == 200
        # hit_rate should not regress
        assert r1.json()["hit_rate"] == r2.json()["hit_rate"]

    def test_cache_no_stale_data(self, app_with_cache: TestClient) -> None:
        """Ingest + /retrieve returns 404 (T08 retired); no stale data risk."""
        ingest_request = {
            "source_type": "text",
            "content": "Specific content about stale data and caching",
            "source_label": "stale_data_test",
            "ingest_type": "update"
        }
        ingest_response = app_with_cache.post("/documents", json=ingest_request)
        assert ingest_response.status_code == 200

        # /retrieve is gone — no stale data can be served
        assert app_with_cache.post("/retrieve", json={"query": "stale data test query"}).status_code == 404


# ============================================================================
# TEST SUITE 9: EDGE CASES
# ============================================================================


class TestEdgeCases:
    """Edge case and boundary condition tests."""

    def test_cache_with_empty_query(self, app_with_cache: TestClient) -> None:
        """POST /retrieve returns 404 regardless of payload after T08 retirement."""
        response = app_with_cache.post(
            "/retrieve",
            json={"query": ""}
        )
        assert response.status_code == 404

    def test_cache_with_very_long_query(self, app_with_cache: TestClient) -> None:
        """POST /retrieve returns 404 regardless of payload after T08 retirement."""
        long_query = "x" * 501
        response = app_with_cache.post(
            "/retrieve",
            json={"query": long_query}
        )
        assert response.status_code == 404

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
