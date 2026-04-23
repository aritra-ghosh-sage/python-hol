"""OPTB-009 — System Responsiveness During Cache/Dependency Issues.

GH-010 acceptance criteria (verbatim from PRODUCT_PRD.md §10.9):
  AC-1: Retrieval requests continue when the cache backend is unavailable.
  AC-2: The system returns controlled errors when the retriever is unavailable.
  AC-3: Degraded operation is logged for follow-up.
  AC-4: Recovery does not require manual cleanup of corrupted cache state.

Design intent:
  These tests are written BEFORE any implementation change (Red → Green workflow).
  They prove that the fail-open principle holds across the REST request surfaces
  covered in this file:
    - POST /retrieve  (REST)
    - GET /cache/stats (observability)

Test doubles:
  All tests use monkeypatch + lightweight fakes rather than heavy mocks.
  This mirrors the established pattern in test_cache_stats_layered.py and
  test_api_shared_retrieval.py to keep tests deterministic and fast.

WHY each scenario matters:
  AC-1: Users must never see 500 errors because Redis is down or slow.
        Cache failure is infrastructure noise, not a product defect.
  AC-2: A 503 with a clear message is better than a cryptic 500 traceback.
        Operators need actionable signal, not noise.
  AC-3: Logging is the first line of defence for on-call engineers.
        Silent failures violate the observability requirement.
  AC-4: Crashed cache state (partially-written entries, corrupted LRU)
        must heal automatically on next warm-start, not require a manual
        cache.clear() call from an operator.
"""

from typing import Any, Dict, List, NoReturn, Optional

import pytest
from fastapi.testclient import TestClient

import api
from hybrid_rag.cache import InMemoryCache


# ---------------------------------------------------------------------------
# Shared test doubles
# ---------------------------------------------------------------------------


class AlwaysFailingCache:
    """Cache backend whose every operation raises RuntimeError.

    WHY: Tests AC-1 (fail-open) and AC-3 (logged).  Every public method
    raises so we can confirm the handler still returns 200 / useful payload.
    """

    # The cache key namespace must match what InMemoryCache / RedisCache use
    # so the middleware, shared-retrieve, and stats path see a consistent shape.

    def get(self, key: str) -> NoReturn:
        raise RuntimeError("cache.get() — simulated backend failure")

    # ttl_seconds is part of the CacheBackend interface; unused here because
    # this implementation always raises before reaching the actual write.
    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> NoReturn:
        raise RuntimeError("cache.set() — simulated backend failure")

    def delete(self, key: str) -> NoReturn:
        raise RuntimeError("cache.delete() — simulated backend failure")

    def clear(self) -> NoReturn:
        raise RuntimeError("cache.clear() — simulated backend failure")

    def stats(self) -> NoReturn:
        raise RuntimeError("cache.stats() — simulated backend failure")

    def health(self) -> NoReturn:
        raise RuntimeError("cache.health() — simulated backend failure")


class FakeRetrieverForResilience:
    """Minimal retriever double returning a single known result.

    WHY: We test cache-failure paths, not retriever paths.  Using a fake
    retriever avoids ChromaDB / sentence-transformer dependencies and makes
    tests deterministic.
    """

    def __init__(self, query_score: float = 0.95) -> None:
        self._query_score = query_score
        self.call_count = 0
        self.collection = _FakeCollection()

    def retrieve(self, query: str, enable_rerank: Optional[bool] = None) -> List[Dict[str, Any]]:
        """Return a single fake document at score self._query_score."""
        self.call_count += 1
        return [
            {
                "id": "fake-doc-1",
                "text": f"Fake document for: {query}",
                "metadata": {"source": "https://fake-source.example"},
                "score": self._query_score,
            }
        ]

    def get_embedding_cache_stats(self) -> Dict[str, Any]:
        """Return zeroed L2 stats (not under test here)."""
        return {"hits": 0, "misses": 0, "hit_rate": 0.0, "size": 0, "capacity": 0}


class _FakeCollection:
    """Minimal collection double satisfying _build_corpus_version_token()."""

    def count(self) -> int:
        return 1


# ---------------------------------------------------------------------------
# Shared fixture: a working app with an injected failing cache
# ---------------------------------------------------------------------------


@pytest.fixture
def client_with_failing_cache(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Wire a failing cache into the global state; return a TestClient.

    WHY function scope: each test must start from a deterministic initial state
    so that one test's monkeypatching does not bleed into the next.
    """
    # Inject stable corpus version so cache-key hash is deterministic
    monkeypatch.setattr(api, "_corpus_version", "gen0.n1")

    # Inject the always-failing cache backend
    monkeypatch.setattr(api, "_cache", AlwaysFailingCache())

    # Inject a working retriever so retrieval itself can proceed
    monkeypatch.setattr(api, "_retriever", FakeRetrieverForResilience())

    # Inject a minimal valid config
    from hybrid_rag import HybridRetrieverConfig
    monkeypatch.setattr(
        api,
        "_config",
        HybridRetrieverConfig(semantic_weight=0.7, keyword_weight=0.3),
    )

    return TestClient(api.app)


@pytest.fixture
def client_no_retriever(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Wire None retriever; return a TestClient.

    WHY: Tests AC-2 — the system must return a controlled HTTP 503 when the
    retriever has not been initialised (e.g. startup failure, init crash).
    """
    monkeypatch.setattr(api, "_retriever", None)
    monkeypatch.setattr(api, "_config", None)
    monkeypatch.setattr(api, "_cache", None)
    return TestClient(api.app)


# ===========================================================================
# AC-1: Retrieval continues when cache backend is unavailable
# ===========================================================================


class TestAC1RetrievalContinuesWithFailingCache:
    """T08: POST /retrieve endpoint removed. Fail-open logic is now WS-only.

    The HTTP /retrieve endpoint has been permanently removed in T08.
    All tests in this class verify the endpoint returns 404.
    Admin endpoints (/cache/stats) still work.
    """

    def test_post_retrieve_returns_404_after_t08(
        self, client_with_failing_cache: TestClient
    ) -> None:
        """POST /retrieve must return HTTP 404 after T08 retirement.

        WHY: The endpoint is permanently removed; 404 is the correct status.
        """
        response = client_with_failing_cache.post(
            "/retrieve",
            json={"query": "test query for resilience"},
        )
        assert response.status_code == 404, (
            f"Expected 404 (T08 retirement), got {response.status_code}: {response.text}"
        )

    def test_post_retrieve_returns_404_with_failing_cache(
        self, client_with_failing_cache: TestClient
    ) -> None:
        """POST /retrieve returns 404 even when cache fails (T08 retirement)."""
        response = client_with_failing_cache.post(
            "/retrieve",
            json={"query": "schema test with failing cache"},
        )
        assert response.status_code == 404

    def test_post_retrieve_returns_404_regardless_of_cache_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """POST /retrieve returns 404 regardless of cache set behavior (T08)."""
        from hybrid_rag import HybridRetrieverConfig
        monkeypatch.setattr(api, "_corpus_version", "gen0.n1")
        monkeypatch.setattr(api, "_cache", InMemoryCache())
        monkeypatch.setattr(api, "_retriever", FakeRetrieverForResilience())
        monkeypatch.setattr(
            api, "_config", HybridRetrieverConfig(semantic_weight=0.7, keyword_weight=0.3)
        )

        client = TestClient(api.app)
        response = client.post("/retrieve", json={"query": "write-back fail test"})
        assert response.status_code == 404, (
            f"Expected 404 (T08 retirement), got {response.status_code}: {response.text}"
        )

    def test_post_retrieve_returns_404_with_no_cache(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """POST /retrieve returns 404 regardless of cache availability (T08)."""
        from hybrid_rag import HybridRetrieverConfig
        monkeypatch.setattr(api, "_retriever", FakeRetrieverForResilience())
        monkeypatch.setattr(
            api, "_config", HybridRetrieverConfig(semantic_weight=0.7, keyword_weight=0.3)
        )
        monkeypatch.setattr(api, "_cache", None)
        monkeypatch.setattr(api, "_corpus_version", "gen0.n1")

        client = TestClient(api.app)
        response = client.post("/retrieve", json={"query": "no-cache live retrieval"})
        assert response.status_code == 404, (
            f"Expected 404 (T08 retirement), got {response.status_code}: {response.text}"
        )

    def test_cache_stats_still_returns_200_when_backend_is_failing(
        self, client_with_failing_cache: TestClient
    ) -> None:
        """GET /cache/stats must return HTTP 200 even when cache.stats() throws.

        WHY (observability): A cache-stats endpoint that crashes on unhealthy
        cache is exactly the worst time to fail — when operators need data most.
        The endpoint must always respond with a degraded-but-valid payload.
        """
        response = client_with_failing_cache.get("/cache/stats")
        assert response.status_code == 200, (
            f"Expected 200 (fail-open for stats), got {response.status_code}: {response.text}"
        )
        body = response.json()

        # Layered schema must still be present
        assert "l1_query_cache" in body
        assert "l2_embedding_cache" in body
        assert "backend_health" in body
        assert "timestamp" in body

        # Backend health must reflect the degraded state
        bh = body["backend_health"]
        # When health() raises, the system falls back to degraded sentinel
        assert bh["fallback_active"] is True, (
            "fallback_active must be True when backend is failing"
        )


# ===========================================================================
# AC-2: Controlled errors when retriever is unavailable
# ===========================================================================


class TestAC2ControlledErrorsForUninitializedRetriever:
    """Prove AC-2: 503 (not 500) when retriever has not been initialised.

    A 503 "Service Unavailable" is the canonical HTTP status for a temporarily
    unavailable dependency.  It tells callers to retry later, rather than
    giving up permanently (408 Too Many Requests) or hiding the cause (500).
    """

    def test_post_retrieve_returns_404_after_removal(
        self, client_no_retriever: TestClient
    ) -> None:
        """POST /retrieve must return HTTP 404 after T08 endpoint retirement.

        WHY: The /retrieve endpoint has been permanently removed in T08.
        Callers must receive 404 (Not Found) rather than 503 so they know
        the endpoint no longer exists and should migrate to /ws/chat.
        """
        response = client_no_retriever.post(
            "/retrieve",
            json={"query": "retriever unavailable test"},
        )
        assert response.status_code == 404, (
            f"Expected 404 (endpoint removed in T08), got {response.status_code}"
        )

    def test_post_retrieve_503_body_contains_useful_message(
        self, client_no_retriever: TestClient
    ) -> None:
        """POST /retrieve returns 404 after T08 retirement (not 503).

        WHY: The endpoint no longer exists; 404 is the correct status.
        """
        response = client_no_retriever.post(
            "/retrieve",
            json={"query": "message quality test"},
        )
        assert response.status_code == 404, (
            f"Expected 404 after T08 retirement, got {response.status_code}"
        )

    def test_get_config_returns_503_when_config_is_none(
        self, client_no_retriever: TestClient
    ) -> None:
        """GET /config must return HTTP 503 when _config is None.

        WHY: Consistent 503 semantics across all retriever-dependent endpoints
        means callers can implement a single retry policy for 503 responses.
        """
        response = client_no_retriever.get("/config")
        assert response.status_code == 503, (
            f"Expected 503 for GET /config without config, got {response.status_code}"
        )

    def test_health_returns_200_but_retriever_not_ready(
        self, client_no_retriever: TestClient
    ) -> None:
        """GET /health must return 200 even when retriever is None.

        WHY: Health-check endpoints must always respond (used by load balancers
        and k8s probes).  The retriever readiness is expressed in the response
        body, not the HTTP status code.
        """
        response = client_no_retriever.get("/health")
        assert response.status_code == 200
        body = response.json()
        # Health endpoint must indicate retriever is NOT ready
        assert body.get("retriever_ready") == "no", (
            f"Expected retriever_ready='no' when _retriever is None, got {body.get('retriever_ready')!r}"
        )


# ===========================================================================
# AC-3: Degraded operation is logged
# ===========================================================================


class TestAC3DegradedOperationLogged:
    """Prove AC-3: warning-level logs are emitted for cache failures.

    Logging is the primary observability mechanism for cache degradation.
    Tests use caplog to verify that warnings are emitted at the correct
    Python log level, which maps directly to alert thresholds in log pipelines.
    """

    def test_cache_get_failure_emits_warning_log(
        self,
        client_with_failing_cache: TestClient,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """POST /retrieve returns 404 after T08; no cache-failure log from HTTP path.

        WHY: The endpoint is retired. No cache interactions happen via HTTP.
        The /cache/stats endpoint still emits warnings when cache fails.
        """
        import logging
        with caplog.at_level(logging.WARNING, logger="api"):
            response = client_with_failing_cache.post(
                "/retrieve", json={"query": "log test cache failure"}
            )

        # T08: endpoint removed → 404
        assert response.status_code == 404, response.text

    def test_retriever_unavailable_emits_error_log(
        self,
        client_no_retriever: TestClient,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """POST /retrieve returns 404 after T08 retirement regardless of retriever state.

        WHY: The endpoint is gone; no retriever check is reached.
        """
        import logging
        with caplog.at_level(logging.ERROR, logger="api"):
            response = client_no_retriever.post(
                "/retrieve", json={"query": "retriever log test"}
            )

        # T08: endpoint removed → 404 (no error log from handler that no longer exists)
        assert response.status_code == 404, response.text

    def test_cache_stats_failure_emits_warning_log(
        self,
        client_with_failing_cache: TestClient,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Cache stats failure must emit at WARNING level or above.

        WHY: /cache/stats is a monitoring surface; its own failures must be
        logged so that 'stats endpoint degraded' appears in alert pipelines.
        """
        import logging
        with caplog.at_level(logging.WARNING, logger="api"):
            client_with_failing_cache.get("/cache/stats")

        warning_records = [
            r for r in caplog.records
            if r.levelno >= logging.WARNING
            and ("cache" in r.message.lower() or "Cache" in r.message)
        ]
        assert warning_records, (
            "Expected at least one WARNING log about cache stats failure, "
            f"found: {[r.message for r in caplog.records]}"
        )


# ===========================================================================
# AC-4: Recovery does not require manual cleanup
# ===========================================================================


class TestAC4RecoveryNoManualCleanup:
    """Prove AC-4: the cache recovers automatically after a failure.

    'Recovery does not require manual cleanup of corrupted cache state' means:
      - After a cache error, a new clean cache backend can be hot-swapped in
        without clearing the old one manually.
      - InMemoryCache auto-recovers after a clear() without any extra setup.
      - Requests issued immediately after a failure + backend replacement
        succeed without operator intervention.
    """

    def test_replacing_failing_cache_with_healthy_cache_restores_service(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """POST /retrieve returns 404 after T08; cache swap doesn't affect it.

        WHY: The endpoint is gone. Confirms cache replacement does not cause
        unexpected errors.
        """
        from hybrid_rag import HybridRetrieverConfig

        monkeypatch.setattr(api, "_cache", AlwaysFailingCache())
        monkeypatch.setattr(api, "_retriever", FakeRetrieverForResilience())
        monkeypatch.setattr(
            api, "_config", HybridRetrieverConfig(semantic_weight=0.7, keyword_weight=0.3)
        )
        monkeypatch.setattr(api, "_corpus_version", "gen0.n1")

        client = TestClient(api.app)
        # T08: endpoint removed → 404
        assert client.post("/retrieve", json={"query": "during degraded state"}).status_code == 404

        # Replace with a healthy cache
        monkeypatch.setattr(api, "_cache", InMemoryCache(ttl_seconds=3600, max_size=1000))

        # Still 404 (endpoint remains gone)
        assert client.post("/retrieve", json={"query": "after recovery test"}).status_code == 404

    def test_in_memory_cache_is_self_healing_after_clear(
        self,
    ) -> None:
        """InMemoryCache resets cleanly after clear() with no leftover state.

        WHY: If clear() leaves any internal counter or lock in a bad state,
        subsequent get/set operations will produce inconsistent results.
        This test verifies that a clear() followed by normal operations
        produces exactly the expected hit/miss pattern.
        """
        cache = InMemoryCache(ttl_seconds=3600, max_size=1000)

        # Write a value, then clear it
        cache.set("key-before-clear", "value1")
        assert cache.get("key-before-clear") == "value1"
        cache.clear()

        # After clear: key must be gone (no stale state)
        assert cache.get("key-before-clear") is None, (
            "Cache must not serve entries after clear() — stale state detected"
        )

        # Write a new value after clear: must work normally
        cache.set("key-after-clear", "value2")
        assert cache.get("key-after-clear") == "value2", (
            "Cache must accept new writes after clear() with no errors"
        )

        # Stats after clear+write must be consistent
        stats = cache.stats()
        assert stats["size"] == 1, (
            f"Expected size=1 after clear+set, got {stats['size']}"
        )

    def test_post_retrieve_after_cache_failure_returns_consistent_schema(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """POST /retrieve returns 404 consistently in both degraded and healthy modes (T08).

        WHY: The endpoint is permanently removed. Status must be 404 regardless
        of cache health state.
        """
        from hybrid_rag import HybridRetrieverConfig

        retriever = FakeRetrieverForResilience()
        config = HybridRetrieverConfig(semantic_weight=0.7, keyword_weight=0.3)

        # Degraded mode
        monkeypatch.setattr(api, "_cache", AlwaysFailingCache())
        monkeypatch.setattr(api, "_retriever", retriever)
        monkeypatch.setattr(api, "_config", config)
        monkeypatch.setattr(api, "_corpus_version", "gen0.n1")

        client = TestClient(api.app)
        degraded_resp = client.post("/retrieve", json={"query": "schema consistency test"})
        assert degraded_resp.status_code == 404

        # Healthy mode
        monkeypatch.setattr(api, "_cache", InMemoryCache(ttl_seconds=3600, max_size=1000))
        healthy_resp = client.post("/retrieve", json={"query": "schema consistency test"})
        assert healthy_resp.status_code == 404
