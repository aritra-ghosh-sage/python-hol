"""OPTB-008 — TDD Red Phase: Failing tests for layered /cache/stats schema.

WHY THIS FILE EXISTS:
    The current /cache/stats endpoint returns a flat schema (backend, hits,
    misses, hit_rate, size, max_size, ttl_seconds, timestamp) defined by the
    CacheStatsResponse Pydantic model.

    OPTB-008 requires a layered schema with exactly four top-level keys:
        l1_query_cache  — L1 response cache metrics + corpus_version token
        l2_embedding_cache — L2 embedding LRU-cache metrics from HybridRetriever
        backend_health  — connection health, latency, fallback flag, error
        timestamp       — ISO-8601 datetime string

    All tests in this file MUST FAIL before the implementation is written
    (Red phase).  They will pass only after api.py is updated in the Green
    phase.  Acceptable failure modes: AssertionError or KeyError — never
    ImportError.

STYLE REFERENCE:
    tests/test_system_e2e.py      — monkeypatch patterns, FakeRetriever doubles
    tests/test_api_shared_retrieval.py — TestClient usage, fixture patterns
"""

from typing import Any, Dict, List, NoReturn, Optional
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import api
from hybrid_rag.cache import InMemoryCache


# ---------------------------------------------------------------------------
# Test Doubles
# ---------------------------------------------------------------------------


class FakeCacheForStats:
    """Minimal cache double whose stats() return known, predictable values.

    WHY: Real InMemoryCache counters depend on actual get/set calls, making
    assertions about specific numeric values fragile.  This double lets tests
    assert exact field shapes without triggering live cache operations.
    """

    def __init__(
        self,
        backend: str = "memory",
        hits: int = 10,
        misses: int = 5,
        size: int = 3,
        max_size: int = 100,
        ttl_seconds: int = 3600,
    ) -> None:
        self._backend = backend
        self._hits = hits
        self._misses = misses
        self._size = size
        self._max_size = max_size
        self._ttl_seconds = ttl_seconds

    def stats(self) -> Dict[str, Any]:
        """Return predictable stats dict matching the shape InMemoryCache produces."""
        return {
            "backend": self._backend,
            "hits": self._hits,
            "misses": self._misses,
            "size": self._size,
            "max_size": self._max_size,
            "ttl_seconds": self._ttl_seconds,
        }

    # Stubs so the cache can be assigned to api._cache without AttributeErrors
    def get(self, key: str) -> Optional[Any]:
        """Return None — FakeCacheForStats never stores values."""
        return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """No-op — FakeCacheForStats discards all writes."""

    def delete(self, key: str) -> None:
        """No-op — FakeCacheForStats has no stored state to delete."""

    def clear(self) -> None:
        """No-op — FakeCacheForStats has no stored state to clear."""

    def health(self) -> Dict[str, Any]:
        """Return a healthy sentinel — FakeCacheForStats has no network backend."""
        return {
            "connected": True,
            "latency_ms": None,
            "fallback_active": False,
            "error": None,
        }


class BrokenCache(FakeCacheForStats):
    """Cache whose stats() always raises, exercising the fail-open path.

    WHY: We need to confirm the endpoint swallows any exception from the
    cache backend and still returns HTTP 200.
    """

    def stats(self) -> NoReturn:  # type: ignore[override]
        raise RuntimeError("simulated stats failure")

    def health(self) -> NoReturn:  # type: ignore[override]
        """Health also raises to exercise outer fail-open guard."""
        raise RuntimeError("simulated health failure")


class FakeRetrieverWithEmbeddingStats:
    """Retriever double exposing a public get_embedding_cache_stats() method.

    WHY: The new layered schema requires L2 stats pulled from the retriever.
    The production HybridRetriever exposes _get_embedding_cache_stats()
    (private).  OPTB-008 implementation will add / expose a public
    get_embedding_cache_stats() method.  This double lets tests assert the
    contract before that method exists.
    """

    def __init__(
        self,
        hits: int = 20,
        misses: int = 8,
        size: int = 12,
        capacity: int = 5000,
    ) -> None:
        self._hits = hits
        self._misses = misses
        self._size = size
        self._capacity = capacity
        total = hits + misses
        self._hit_rate = hits / total if total > 0 else 0.0

    def get_embedding_cache_stats(self) -> Dict[str, Any]:
        """Return L2 embedding cache stats in the expected shape."""
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": self._hit_rate,
            "size": self._size,
            "capacity": self._capacity,
        }


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def stats_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Wire up a minimal, isolated environment for /cache/stats tests.

    Patches api._cache, api._retriever, api._config and api._corpus_version
    to known, stable values.  Returns a synchronous TestClient.

    WHY monkeypatch (function scope): each test must start from a clean
    module-level state to avoid cross-test pollution.
    """
    # Known corpus version so corpus_version assertions are deterministic
    monkeypatch.setattr(api, "_corpus_version", "gen0.n1")

    # Fresh in-memory cache for most tests (can be overridden per-test)
    monkeypatch.setattr(api, "_cache", FakeCacheForStats())

    # Retriever with public embedding-cache stats method
    monkeypatch.setattr(api, "_retriever", FakeRetrieverWithEmbeddingStats())

    return TestClient(api.app)


# ===========================================================================
# TestLayeredCacheStatsShape
# ===========================================================================


class TestLayeredCacheStatsShape:
    """Integration tests verifying the layered /cache/stats response contract.

    WHAT: Checks the structural shape of the new layered response schema.
    WHY: The contract switch from a flat dict to a 3-section hierarchy is
    breaking — any consumer relying on top-level 'backend' or 'hits' keys
    will break.  These tests guard the NEW contract before implementation.
    """

    def test_stats_endpoint_returns_200_always(
        self, stats_client: TestClient
    ) -> None:
        """GET /cache/stats MUST always return HTTP 200.

        WHAT: Basic liveness check for the endpoint.
        WHY: Fail-open is a hard requirement; monitoring dashboards must
        never see a 5xx from /cache/stats even when the cache is unhealthy.
        """
        response = stats_client.get("/cache/stats")
        # WILL FAIL until implementation: shape may be wrong but status must be 200
        assert response.status_code == 200

    def test_stats_response_has_all_required_sections(
        self, stats_client: TestClient
    ) -> None:
        """Response JSON must have exactly the four required top-level keys.

        WHAT: Validates the top-level structure of the layered schema.
        WHY: Consumers like Grafana dashboards or frontend polling will
        navigate directly to response['l1_query_cache'] etc.; if any key is
        missing, downstream observability breaks silently.

        The four keys are: l1_query_cache, l2_embedding_cache, backend_health
        (the three data sections), plus timestamp.

        WILL FAIL (Red): current flat schema has 'backend', 'hits', etc.
        at the root — not the three nested sections.
        """
        response = stats_client.get("/cache/stats")
        assert response.status_code == 200
        body: Dict[str, Any] = response.json()

        # These four keys are the contract — no more, no less
        assert "l1_query_cache" in body, "missing top-level key: l1_query_cache"
        assert "l2_embedding_cache" in body, "missing top-level key: l2_embedding_cache"
        assert "backend_health" in body, "missing top-level key: backend_health"
        assert "timestamp" in body, "missing top-level key: timestamp"

    def test_l1_section_shape(self, stats_client: TestClient) -> None:
        """l1_query_cache must contain all required L1 metric fields.

        WHAT: Validates every field name in the l1_query_cache sub-object.
        WHY: l1_query_cache is the primary operational metric block.
        Missing fields (e.g. corpus_version) would break version-aware
        debugging workflows that rely on the stats endpoint.

        WILL FAIL (Red): l1_query_cache key does not exist in the flat schema.
        """
        response = stats_client.get("/cache/stats")
        body: Dict[str, Any] = response.json()
        l1: Dict[str, Any] = body["l1_query_cache"]  # KeyError if flat schema

        required_fields = {
            "backend",
            "hits",
            "misses",
            "hit_rate",
            "size",
            "max_size",
            "ttl_seconds",
            "corpus_version",
        }
        missing = required_fields - set(l1.keys())
        assert not missing, f"l1_query_cache missing fields: {missing}"

    def test_l2_section_shape(self, stats_client: TestClient) -> None:
        """l2_embedding_cache must contain all required L2 metric fields.

        WHAT: Validates the field names inside l2_embedding_cache.
        WHY: L2 metrics are the only visibility into embedding-cache
        efficiency; without 'capacity' teams cannot detect cache exhaustion.

        WILL FAIL (Red): l2_embedding_cache key does not exist in flat schema.
        """
        response = stats_client.get("/cache/stats")
        body: Dict[str, Any] = response.json()
        l2: Dict[str, Any] = body["l2_embedding_cache"]  # KeyError if flat schema

        required_fields = {"hits", "misses", "hit_rate", "size", "capacity"}
        missing = required_fields - set(l2.keys())
        assert not missing, f"l2_embedding_cache missing fields: {missing}"

    def test_backend_health_section_shape(self, stats_client: TestClient) -> None:
        """backend_health must contain all required health/observability fields.

        WHAT: Validates the field names inside backend_health.
        WHY: 'latency_ms' and 'fallback_active' are the two fields that alert
        on-call engineers; 'error' provides the root-cause message.  Silently
        missing fields make alerting rules produce false-positives/negatives.

        WILL FAIL (Red): backend_health key does not exist in flat schema.
        """
        response = stats_client.get("/cache/stats")
        body: Dict[str, Any] = response.json()
        bh: Dict[str, Any] = body["backend_health"]  # KeyError if flat schema

        required_fields = {"connected", "latency_ms", "fallback_active", "error"}
        missing = required_fields - set(bh.keys())
        assert not missing, f"backend_health missing fields: {missing}"

    def test_l1_corpus_version_reflects_current_state(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """l1_query_cache.corpus_version must match the live api._corpus_version token.

        WHAT: Validates that the layered response exposes the authoritative
        corpus version that controls cache key namespacing.
        WHY: Operators debugging stale-result issues need to see which corpus
        version is active.  If the field is hardcoded or stale, the debug
        information is misleading.

        WILL FAIL (Red): corpus_version field does not exist in flat schema.
        """
        # Arrange: inject a distinctive version token
        monkeypatch.setattr(api, "_corpus_version", "gen1.n42")
        monkeypatch.setattr(api, "_cache", FakeCacheForStats())
        monkeypatch.setattr(api, "_retriever", FakeRetrieverWithEmbeddingStats())

        client = TestClient(api.app)
        response = client.get("/cache/stats")

        body: Dict[str, Any] = response.json()
        l1: Dict[str, Any] = body["l1_query_cache"]  # KeyError if flat schema
        assert l1["corpus_version"] == "gen1.n42", (
            f"expected corpus_version='gen1.n42', got {l1.get('corpus_version')!r}"
        )

    def test_stats_fail_open_when_cache_is_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Endpoint must return 200 with degraded stats when _cache is None.

        WHAT: Validates the null-cache degraded mode.
        WHY: On startup before the cache backend is ready, or after a Redis
        disconnect causes the cache to be torn down, /cache/stats must still
        respond.  A 500 here would mask the real failure and confuse alerts.

        WILL FAIL (Red): the current implementation already handles this path
        but does NOT return the layered schema — so the key assertions fail.
        """
        monkeypatch.setattr(api, "_cache", None)
        monkeypatch.setattr(api, "_retriever", FakeRetrieverWithEmbeddingStats())

        client = TestClient(api.app)
        response = client.get("/cache/stats")

        assert response.status_code == 200, (
            f"expected 200 when _cache is None, got {response.status_code}"
        )
        body: Dict[str, Any] = response.json()

        # backend_health must signal degraded state
        bh: Dict[str, Any] = body["backend_health"]  # KeyError if flat schema
        assert bh["connected"] is False, (
            "backend_health.connected must be False when _cache is None"
        )
        assert bh["fallback_active"] is True, (
            "backend_health.fallback_active must be True when _cache is None"
        )

    def test_stats_fail_open_when_stats_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Endpoint must return 200 even when cache.stats() raises an exception.

        WHAT: Validates that internal errors in the cache backend are fully
        swallowed and never surface as HTTP 500.
        WHY: Cache health telemetry must be resilient to the very failures
        it is meant to surface.  A recursive 500 here would crash monitoring.

        WILL FAIL (Red): current flat schema — backend_health key missing.
        """
        monkeypatch.setattr(api, "_cache", BrokenCache())
        monkeypatch.setattr(api, "_retriever", FakeRetrieverWithEmbeddingStats())

        client = TestClient(api.app)
        response = client.get("/cache/stats")

        assert response.status_code == 200, (
            f"expected 200 when cache.stats() raises, got {response.status_code}"
        )

    def test_l2_populated_from_retriever_embedding_cache(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """l2_embedding_cache values must come from retriever.get_embedding_cache_stats().

        WHAT: Validates that the endpoint delegates L2 stats to the retriever
        rather than returning zeroes unconditionally.
        WHY: Without this delegation, L2 stats would always be 0/0/0.0/0/0,
        making the cache section useless for observability.

        WILL FAIL (Red): l2_embedding_cache key does not exist in flat schema.
        """
        # Arrange: retriever with known, non-zero L2 stats
        fake_retriever = FakeRetrieverWithEmbeddingStats(
            hits=42, misses=7, size=15, capacity=5000
        )
        expected_hit_rate = 42 / (42 + 7)

        monkeypatch.setattr(api, "_retriever", fake_retriever)
        monkeypatch.setattr(api, "_cache", FakeCacheForStats())
        monkeypatch.setattr(api, "_corpus_version", "gen0.n1")

        client = TestClient(api.app)
        response = client.get("/cache/stats")

        body: Dict[str, Any] = response.json()
        l2: Dict[str, Any] = body["l2_embedding_cache"]  # KeyError if flat schema

        assert l2["hits"] == 42, f"expected l2.hits=42, got {l2.get('hits')}"
        assert l2["misses"] == 7, f"expected l2.misses=7, got {l2.get('misses')}"
        assert l2["size"] == 15, f"expected l2.size=15, got {l2.get('size')}"
        assert l2["capacity"] == 5000, f"expected l2.capacity=5000, got {l2.get('capacity')}"
        assert abs(l2["hit_rate"] - expected_hit_rate) < 1e-6, (
            f"expected l2.hit_rate≈{expected_hit_rate:.6f}, got {l2.get('hit_rate')}"
        )


# ===========================================================================
# TestLayeredCacheStatsDegradedMode
# ===========================================================================


class TestLayeredCacheStatsDegradedMode:
    """Tests verifying correct behaviour when system components are absent.

    WHAT: Exercises the degraded-mode branches: no retriever, no cache.
    WHY: Degraded-mode coverage ensures the fail-open principle is robust
    across all component combinations, not just the happy path.
    """

    def test_degraded_mode_no_retriever(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """l2_embedding_cache must be zeroed when _retriever is None.

        WHAT: Validates that the endpoint handles None retriever gracefully.
        WHY: During startup the retriever may not be initialised.  Returning
        zeroes for L2 is correct; raising an exception (AttributeError on
        None) is a bug.

        WILL FAIL (Red): l2_embedding_cache key does not exist in flat schema.
        """
        monkeypatch.setattr(api, "_retriever", None)
        monkeypatch.setattr(api, "_cache", FakeCacheForStats())
        monkeypatch.setattr(api, "_corpus_version", "gen0.n1")

        client = TestClient(api.app)
        response = client.get("/cache/stats")

        assert response.status_code == 200, (
            f"expected 200 when _retriever is None, got {response.status_code}"
        )
        body: Dict[str, Any] = response.json()
        l2: Dict[str, Any] = body["l2_embedding_cache"]  # KeyError if flat schema

        # All L2 counters must be zeroed — not absent
        assert l2["hits"] == 0, (
            f"l2.hits must be 0 when retriever is None, got {l2.get('hits')}"
        )
        assert l2["misses"] == 0, (
            f"l2.misses must be 0 when retriever is None, got {l2.get('misses')}"
        )
        assert l2["hit_rate"] == 0.0, (
            f"l2.hit_rate must be 0.0 when retriever is None, got {l2.get('hit_rate')}"
        )
        assert l2["size"] == 0, (
            f"l2.size must be 0 when retriever is None, got {l2.get('size')}"
        )
        assert l2["capacity"] == 0, (
            f"l2.capacity must be 0 when retriever is None, got {l2.get('capacity')}"
        )

    def test_degraded_mode_in_memory_backend_health(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """backend_health must show connected=True, fallback_active=False for InMemoryCache.

        WHAT: Validates that a healthy in-memory backend reports as connected
        with no fallback active.
        WHY: InMemoryCache never fails connectivity — it has no network hop.
        Reporting it as disconnected or fallback would generate spurious alerts.

        WILL FAIL (Red): backend_health key does not exist in flat schema.
        """
        # Use a real InMemoryCache (not the mock) to test the actual backend path
        real_cache = InMemoryCache(ttl_seconds=3600, max_size=100)
        monkeypatch.setattr(api, "_cache", real_cache)
        monkeypatch.setattr(api, "_retriever", FakeRetrieverWithEmbeddingStats())
        monkeypatch.setattr(api, "_corpus_version", "gen0.n1")

        client = TestClient(api.app)
        response = client.get("/cache/stats")

        assert response.status_code == 200
        body: Dict[str, Any] = response.json()
        bh: Dict[str, Any] = body["backend_health"]  # KeyError if flat schema

        assert bh["connected"] is True, (
            f"backend_health.connected must be True for InMemoryCache, got {bh.get('connected')}"
        )
        assert bh["fallback_active"] is False, (
            f"backend_health.fallback_active must be False for InMemoryCache, "
            f"got {bh.get('fallback_active')}"
        )
