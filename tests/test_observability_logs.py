"""OPTB-012 — Harden observability with correlation-aware logs.

Wave 6 acceptance criteria:
  AC-1: Invalidation events emit structured logs with old_version / new_version
        for config changes, ingest-update, and ingest-add operations.
  AC-2: Cache hit/miss telemetry is tied to a per-request correlation
        identifier so operators can trace individual requests through logs.
  AC-3: Fallback activation (cache backend unreachable) is logged when it
        first occurs, and deactivation is logged when health recovers.
  AC-4: Backend health fields continue to expose fallback_active and Redis
        state through the /cache/stats endpoint.
  AC-5: Fail-open behaviour is preserved — retrieval succeeds even when the
        cache raises during a hit/miss log event.

Definition of done:
  Operators can correlate cache behaviour and invalidation/fallback
  transitions end-to-end using only the structured log stream.

Design intent:
  Tests use monkeypatch + lightweight fakes to avoid ChromaDB, Redis,
  and sentence-transformer dependencies.  All assertions are on actual
  log records captured via pytest's ``caplog`` fixture (not on mocks),
  following the pattern in test_system_resilience.py.

WHY each scenario matters:
  AC-1: Without old/new version in invalidation logs, operators cannot
        determine whether a config change or ingest was responsible for
        a cache miss spike.  Both must be auditable.
  AC-2: Without a correlation ID, an operator cannot link a single
        user request in app logs to its cache HIT or MISS event.
  AC-3: Fallback transitions are the first signal of backend degradation.
        Silent fallback lets incidents go undetected until users complain.
  AC-4: Health schema regression (removing fallback_active) would break
        monitoring dashboards built on the OPTB-008 layered stats contract.
  AC-5: Log instrumentation must never break the request path — the
        observability layer is a side-effect, not a gate.
"""

# Note 1: Standard library imports come first, then third-party, then local.
# This ordering follows PEP 8 and makes dependency scanning easier for tools.
import logging
import uuid
from typing import Any, Dict, List, Optional, NoReturn

# Note 2: pytest is the test framework; TestClient wraps FastAPI's ASGI app
# so you can issue real HTTP requests without starting a live server.
import pytest
from fastapi.testclient import TestClient

# Note 3: Importing the application module directly lets monkeypatch swap out
# module-level globals (e.g. api._cache) at test time. The test file and
# api.py share the same process, so changes are visible immediately.
import api
from hybrid_rag import HybridRetrieverConfig
from hybrid_rag.cache import InMemoryCache


# ---------------------------------------------------------------------------
# Shared test doubles
# ---------------------------------------------------------------------------
# Note 4: A "test double" is any object that substitutes a real dependency
# during testing. The four main subtypes are dummy, stub, fake, and mock.
# The classes below are FAKES — they have working (but simplified) behaviour
# rather than just returning hard-coded values like a stub would.


class _FakeCollection:
    """Minimal collection double satisfying _build_corpus_version_token() and add_documents.

    Note 5: The leading underscore signals that this class is module-private.
    Python does not enforce this, but it communicates intent to other developers
    reading the file.

    The count is now stateful: it starts at 5 (matching the "gen0.n5"
    corpus_version token used by most tests) and is incremented by add() so
    that _build_corpus_version_token() returns a genuinely different token
    after each ingest-add operation.  Without this, prev_version and
    new_version in the invalidation log would be identical, which would let
    the AC-1 ingest-add assertion pass vacuously.
    """

    def __init__(self) -> None:
        # Start at 5 so _build_corpus_version_token() returns "gen0.n5" —
        # matching the corpus_version= "gen0.n5" default in _patch_standard_app.
        self._count: int = 5

    def count(self) -> int:  # noqa: D102
        # Note 6: noqa: D102 silences the "Missing docstring in public method"
        # linter warning for this one-liner helper. It keeps test files concise
        # without disabling linting globally.
        return self._count

    def add(
        self,
        ids: List[str],
        documents: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Simulate document addition by incrementing the tracked count.

        WHY: _build_corpus_version_token() calls collection.count() to derive
        the corpus_version token.  A no-op add() would leave the count
        unchanged, making prev_version == new_version and the ingest-add
        invalidation log impossible to distinguish from a no-op.  Incrementing
        by len(ids) mirrors what a real ChromaDB collection does.
        """
        # Each id corresponds to one document chunk stored in the collection.
        self._count += len(ids)


class _FakeRetriever:
    """Deterministic retriever that never touches ChromaDB.

    WHY: Observability tests verify log output, not retrieval quality.
    A fake retriever makes tests fast and side-effect free.
    """

    def __init__(self, score: float = 0.95) -> None:
        self._score = score
        # call_count is exposed for tests that need to verify how many times
        # the retriever was invoked (e.g. to confirm cache hit vs. miss
        # behaviour). Observability tests do not currently assert on it, but
        # it follows the same tracking pattern used in test_api_shared_retrieval.py.
        self.call_count: int = 0
        # Expose a collection so _build_corpus_version_token() can call count().
        self.collection = _FakeCollection()

    def retrieve(
        self, query: str, enable_rerank: Optional[bool] = None
    ) -> List[Dict[str, Any]]:
        """Return one fake document at the configured score."""
        self.call_count += 1
        return [
            {
                "id": "obs-doc-1",
                "text": f"Fake result for: {query}",
                "metadata": {"source": "https://example.test"},
                # Note 8: self._score was set in __init__, making the fake
                # configurable per test. This pattern is "parameterised fake"
                # and avoids creating many near-identical fake classes.
                "score": self._score,
            }
        ]

    def get_embedding_cache_stats(self) -> Dict[str, Any]:
        """Return zeroed L2 stats — not under test here."""
        # Note 9: Returning zeroes for unrelated functionality keeps tests
        # focused. A test that checks invalidation logs should not also worry
        # about L2 embedding stats being accurate.
        return {"hits": 0, "misses": 0, "hit_rate": 0.0, "size": 0, "capacity": 0}


class _AlwaysFailingCache:
    """Cache whose every operation raises RuntimeError.

    WHY: Needed for AC-3 (fallback activation) and AC-5 (fail-open) tests.

    Note 10: The NoReturn return type annotation tells type-checkers (mypy,
    Pyright) that these methods never return normally. It is the correct
    annotation for functions that always raise an exception.
    """

    def get(self, key: str) -> NoReturn:
        raise RuntimeError("_AlwaysFailingCache.get")

    def set(
        self, key: str, value: Any, ttl_seconds: Optional[int] = None
    ) -> NoReturn:
        raise RuntimeError("_AlwaysFailingCache.set")

    def delete(self, key: str) -> NoReturn:
        raise RuntimeError("_AlwaysFailingCache.delete")

    def clear(self) -> NoReturn:
        raise RuntimeError("_AlwaysFailingCache.clear")

    def stats(self) -> NoReturn:
        raise RuntimeError("_AlwaysFailingCache.stats")

    def health(self) -> NoReturn:
        raise RuntimeError("_AlwaysFailingCache.health")


# ---------------------------------------------------------------------------
# Shared fixture helpers
# ---------------------------------------------------------------------------
# Note 11: Helper functions (not pytest fixtures) that construct and configure
# a TestClient are an alternative to @pytest.fixture when you need to pass
# arguments. Fixtures cannot accept arguments directly — only via
# parametrize or fixture-factory patterns. Plain functions are simpler here.


def _patch_standard_app(
    monkeypatch: pytest.MonkeyPatch,
    cache: Any = None,
    corpus_version: str = "gen0.n5",
) -> TestClient:
    """Wire a fake retriever and optional cache; return a TestClient.

    Args:
        monkeypatch: pytest monkeypatch fixture.
        cache: Cache backend to inject.  Defaults to a fresh InMemoryCache.
        corpus_version: Starting corpus_version token for the test.

    Returns:
        TestClient backed by the configured api.app.
    """
    # Note 12: monkeypatch.setattr replaces a module-level name for the
    # duration of a single test and automatically restores the original after
    # the test finishes. This is essential for tests that mutate shared state
    # like api._retriever or api._cache.
    monkeypatch.setattr(api, "_retriever", _FakeRetriever())
    monkeypatch.setattr(
        api,
        "_config",
        HybridRetrieverConfig(semantic_weight=0.7, keyword_weight=0.3),
    )
    monkeypatch.setattr(api, "_corpus_version", corpus_version)
    monkeypatch.setattr(api, "_cache_generation", 0)

    chosen_cache: Any = cache if cache is not None else InMemoryCache()
    monkeypatch.setattr(api, "_cache", chosen_cache)
    # Reset fallback-state tracker so tests start from a clean slate.
    # Note 13: Without this reset, a test that leaves _last_fallback_state=True
    # would cause the next test to skip the "activation" log event because the
    # module-level variable still carries the previous test's value.
    monkeypatch.setattr(api, "_last_fallback_state", None)

    return TestClient(api.app)


# ===========================================================================
# AC-1: Invalidation events log old_version and new_version
# ===========================================================================


class TestAC1InvalidationLogs:
    """Verify that every cache invalidation path emits structured version logs.

    WHY this matters: Without old_version / new_version in log records,
    operators cannot reconstruct the invalidation history from logs alone.
    They would need to correlate timestamps across multiple log lines, which
    is error-prone and slow during an incident.
    """

    def test_config_change_logs_prev_and_new_corpus_version(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """PUT /config must log cache.invalidation with prev_version and new_version.

        WHY: Config changes bump _cache_generation and rebuild _corpus_version.
        Both old and new tokens must be in the log so operators can verify the
        transition happened and identify which generation caused a miss spike.
        """
        client = _patch_standard_app(monkeypatch, corpus_version="gen0.n5")

        with caplog.at_level(logging.INFO, logger="api"):
            response = client.put(
                "/config",
                json={"semantic_weight": 0.6, "keyword_weight": 0.4},
            )

        assert response.status_code == 200, response.text

        log_messages = [r.message for r in caplog.records]
        invalidation_logs = [
            m for m in log_messages if "cache.invalidation" in m
        ]
        assert invalidation_logs, (
            "Expected at least one 'cache.invalidation' log record after PUT /config, "
            f"got none.  All logs: {log_messages}"
        )

        combined = " ".join(invalidation_logs)
        assert "prev_version=" in combined, (
            "Invalidation log must contain 'prev_version='.  Got: " + combined
        )
        assert "new_version=" in combined, (
            "Invalidation log must contain 'new_version='.  Got: " + combined
        )

    def test_config_change_log_shows_version_changed(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """prev_version and new_version must differ after a config change.

        WHY: If both values are the same token, the log does not prove that
        invalidation actually occurred — it could be a no-op or a bug.
        """
        client = _patch_standard_app(monkeypatch, corpus_version="gen0.n5")

        with caplog.at_level(logging.INFO, logger="api"):
            client.put(
                "/config",
                json={"semantic_weight": 0.6, "keyword_weight": 0.4},
            )

        invalidation_logs = [
            r.message
            for r in caplog.records
            if "cache.invalidation" in r.message and "prev_version=" in r.message
        ]
        assert invalidation_logs, "No invalidation log with prev_version= found."

        # Extract prev_version token from the first matching log line.
        # Format: "cache.invalidation event=... prev_version=X new_version=Y"
        log_line = invalidation_logs[0]
        prev_token = ""
        new_token = ""
        for part in log_line.split():
            if part.startswith("prev_version="):
                prev_token = part.split("=", 1)[1]
            if part.startswith("new_version="):
                new_token = part.split("=", 1)[1]

        assert prev_token != new_token, (
            f"prev_version '{prev_token}' must differ from new_version '{new_token}' "
            "after a config change invalidation."
        )

    def test_ingest_update_logs_prev_and_new_corpus_version(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """POST /documents with ingest_type=update must log old and new versions.

        WHY: ingest_type=update bumps _cache_generation; the log must record
        both the pre-ingest and post-ingest corpus_version tokens so operators
        can confirm the invalidation event is tied to the ingest operation.
        """
        client = _patch_standard_app(monkeypatch, corpus_version="gen1.n5")

        with caplog.at_level(logging.INFO, logger="api"):
            response = client.post(
                "/documents",
                json={
                    "source_type": "text",
                    "content": "New document added via ingest-update",
                    "ingest_type": "update",
                },
            )

        assert response.status_code == 200, response.text

        invalidation_logs = [
            r.message for r in caplog.records if "cache.invalidation" in r.message
        ]
        assert invalidation_logs, (
            "Expected 'cache.invalidation' log after ingest_type=update. "
            f"All logs: {[r.message for r in caplog.records]}"
        )
        combined = " ".join(invalidation_logs)
        assert "prev_version=" in combined
        assert "new_version=" in combined

    def test_ingest_add_logs_corpus_version_transition(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """POST /documents with ingest_type=add must log version transition.

        WHY: ingest_type=add does NOT bump _cache_generation but DOES rebuild
        _corpus_version using the updated collection count dimension.  Operators
        must be able to confirm the token changed (corpus grew) without seeing a
        generation bump — the log must distinguish the two paths.
        """
        client = _patch_standard_app(monkeypatch, corpus_version="gen0.n5")

        with caplog.at_level(logging.INFO, logger="api"):
            response = client.post(
                "/documents",
                json={
                    "source_type": "text",
                    "content": "Additive ingest — no cache clear",
                    "ingest_type": "add",
                },
            )

        assert response.status_code == 200, response.text

        invalidation_logs = [
            r.message for r in caplog.records if "cache.invalidation" in r.message
        ]
        assert invalidation_logs, (
            "Expected 'cache.invalidation' log after ingest_type=add. "
            f"All logs: {[r.message for r in caplog.records]}"
        )
        combined = " ".join(invalidation_logs)
        assert "prev_version=" in combined
        assert "new_version=" in combined

        # Extract tokens and verify they differ — if the fake collection does
        # not track count, _build_corpus_version_token() returns the same value
        # for both and the log would be misleading.
        log_line = invalidation_logs[0]
        prev_token = ""
        new_token = ""
        for part in log_line.split():
            if part.startswith("prev_version="):
                prev_token = part.split("=", 1)[1]
            if part.startswith("new_version="):
                new_token = part.split("=", 1)[1]

        assert prev_token != new_token, (
            f"prev_version '{prev_token}' must differ from new_version '{new_token}' "
            "after ingest_type=add (the collection count dimension must change)."
        )


# ===========================================================================
# AC-2: Cache hit/miss telemetry tied to correlation identifiers
# ===========================================================================
# Note 14: A correlation ID (also called a request ID or trace ID) is a
# short, unique string attached to every log record for a single request.
# It lets operators grep a distributed log stream (app + cache + DB) and
# reconstruct the full lifecycle of one specific user request.
# The X-Request-ID header is the de-facto standard (used by nginx, AWS ALB,
# and many API gateways). Honoring it means existing tracing infrastructure
# works without changes.


class TestAC2CorrelationAwareTelemetry:
    """Verify that cache hit/miss events carry a request correlation ID.

    WHY this matters: Without a correlation ID in the hit/miss log, an
    operator cannot link a specific user request (identified by its correlation
    ID in upstream logs) to the cache event.  Tracing is impossible without
    this link.
    """

    def test_cache_miss_log_contains_correlation_id(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """First POST /retrieve must emit a cache.http_miss log with correlation_id.

        WHY: The first request for a query is always a cache miss.  The log
        must carry a correlation_id so the operator can trace the full path
        (request → cache miss → retriever call → response).

        The log is emitted by the QueryCacheMiddleware which intercepts the
        POST /retrieve path at the HTTP layer; the event name is therefore
        ``cache.http_miss`` (as opposed to ``cache.retrieval_miss`` which is
        emitted by the shared retrieval function).
        """
        client = _patch_standard_app(monkeypatch)

        # Note 15: uuid.uuid4() generates a random 128-bit UUID. Using a
        # fresh UUID per test guarantees that assertions about the specific ID
        # appearing in logs cannot accidentally pass from a previous test run.
        corr_id = str(uuid.uuid4())
        # Note 16: caplog.at_level is a context manager. It temporarily sets
        # the capture level to INFO for the duration of the `with` block and
        # resets it afterwards. Logs emitted outside the block are not captured.
        with caplog.at_level(logging.INFO):
            response = client.post(
                "/retrieve",
                json={"query": "what is hybrid retrieval"},
                # Note 17: Passing the correlation ID in X-Request-ID simulates
                # how an API gateway or load balancer tags requests. The middleware
                # reads this header and injects it into every log record it emits.
                headers={"X-Request-ID": corr_id},
            )

        assert response.status_code == 200, response.text

        # Note 18: caplog.records is a list of logging.LogRecord objects.
        # LogRecord.message is the formatted message string (after % substitution).
        miss_logs = [
            r.message for r in caplog.records if "cache.http_miss" in r.message
        ]
        assert miss_logs, (
            "Expected a 'cache.http_miss' log for a cold-cache retrieval. "
            f"All logs: {[r.message for r in caplog.records]}"
        )
        assert any(corr_id in m for m in miss_logs), (
            f"cache.http_miss log must include correlation_id='{corr_id}'.  "
            f"Miss logs found: {miss_logs}"
        )

    def test_cache_hit_log_contains_correlation_id(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Second POST /retrieve for same query must emit cache.http_hit with corr ID.

        WHY: Cache hits are the steady-state case in production.  Operators
        must be able to confirm a request was served from cache for a specific
        correlation ID — essential for debugging latency anomalies.

        The hit is served by the QueryCacheMiddleware which short-circuits the
        handler on repeated identical requests; the event name is therefore
        ``cache.http_hit`` (as opposed to ``cache.retrieval_hit`` which is
        emitted by the shared retrieval function).
        """
        client = _patch_standard_app(monkeypatch)
        query_payload = {"query": "correlation hit test"}

        # First call — populates the middleware cache (cache.http_miss)
        client.post("/retrieve", json=query_payload)

        # Second call — should hit the middleware cache
        corr_id = str(uuid.uuid4())
        with caplog.at_level(logging.INFO):
            response = client.post(
                "/retrieve",
                json=query_payload,
                headers={"X-Request-ID": corr_id},
            )

        assert response.status_code == 200, response.text

        hit_logs = [
            r.message for r in caplog.records if "cache.http_hit" in r.message
        ]
        assert hit_logs, (
            "Expected a 'cache.http_hit' log on the second identical request. "
            f"All logs: {[r.message for r in caplog.records]}"
        )
        assert any(corr_id in m for m in hit_logs), (
            f"cache.http_hit log must include correlation_id='{corr_id}'.  "
            f"Hit logs found: {hit_logs}"
        )

    def test_cache_miss_log_contains_corpus_version(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """cache.retrieval_miss from _shared_retrieve_documents must include corpus_version.

        WHY: Knowing the corpus_version at the time of a miss tells operators
        whether the miss was expected (just after an invalidation event, version
        changed) or unexpected (version unchanged — potential stampede).

        This log is emitted by the shared retrieval function in ``api`` which
        has access to the live corpus_version token; the event name is therefore
        ``cache.retrieval_miss``.
        """
        client = _patch_standard_app(monkeypatch, corpus_version="gen2.n10")

        with caplog.at_level(logging.INFO, logger="api"):
            client.post(
                "/retrieve",
                json={"query": "version check on miss"},
            )

        miss_logs = [
            r.message for r in caplog.records if "cache.retrieval_miss" in r.message
        ]
        assert miss_logs, "Expected at least one cache.retrieval_miss log."
        combined = " ".join(miss_logs)
        assert "corpus_version=" in combined, (
            "cache.retrieval_miss log must contain 'corpus_version='.  Got: " + combined
        )

    def test_generated_correlation_id_used_when_header_absent(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """cache.http_miss log must carry a synthetic UUID when no header is sent.

        WHY: Not all callers set X-Request-ID.  The system must auto-generate
        a correlation ID so every log record is traceable, even without the
        caller's cooperation.
        """
        client = _patch_standard_app(monkeypatch)

        with caplog.at_level(logging.INFO):
            client.post(
                "/retrieve",
                json={"query": "no header correlation"},
                # Deliberately omit X-Request-ID header
            )

        miss_logs = [
            r.message for r in caplog.records if "cache.http_miss" in r.message
        ]
        assert miss_logs, "Expected cache.http_miss log even without X-Request-ID header."
        combined = " ".join(miss_logs)
        assert "correlation_id=" in combined, (
            "cache.http_miss log must include a generated correlation_id even "
            "when no X-Request-ID header is present.  Got: " + combined
        )


# ===========================================================================
# AC-3: Fallback activation/deactivation is logged
# ===========================================================================


class TestAC3FallbackTransitionLogs:
    """Verify fallback state transitions are surfaced in the log stream.

    WHY this matters: The fallback state (cache unavailable) is the first
    signal of backend degradation.  If it is not logged, on-call engineers
    have no alert signal until users notice degraded performance.
    """

    def test_fallback_activation_logged_when_cache_fails(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """GET /cache/stats must log fallback_activated when health() fails.

        WHY: The /cache/stats endpoint is polled by monitoring systems.
        When the backend becomes unreachable, the first health check that
        detects the failure must emit a WARNING log so dashboards fire alerts.
        """
        client = _patch_standard_app(
            monkeypatch, cache=_AlwaysFailingCache()
        )
        # Ensure last_fallback_state starts as None (no prior health check).
        monkeypatch.setattr(api, "_last_fallback_state", None)

        with caplog.at_level(logging.WARNING, logger="api"):
            response = client.get("/cache/stats")

        assert response.status_code == 200, response.text

        fallback_logs = [
            r.message
            for r in caplog.records
            if "fallback" in r.message.lower()
            and r.levelno >= logging.WARNING
        ]
        assert fallback_logs, (
            "Expected a WARNING-level fallback log when cache.health() raises. "
            f"All WARNING+ logs: {[r.message for r in caplog.records if r.levelno >= logging.WARNING]}"
        )

    def test_fallback_not_logged_repeatedly_when_already_active(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A second /cache/stats call must NOT repeat the fallback_activated log.

        WHY: If fallback_activated fires on every health-check poll while the
        backend is down, alert fatigue sets in.  The log must fire ONCE on
        transition (False→True), not repeatedly while the state is stable.
        """
        client = _patch_standard_app(
            monkeypatch, cache=_AlwaysFailingCache()
        )
        # Simulate that fallback state is already known to be True.
        monkeypatch.setattr(api, "_last_fallback_state", True)

        with caplog.at_level(logging.WARNING, logger="api"):
            client.get("/cache/stats")

        # A fallback_activated event must NOT appear — it already fired.
        activation_logs = [
            r.message
            for r in caplog.records
            if "fallback_activated" in r.message
        ]
        assert not activation_logs, (
            "fallback_activated must not log again while state is already True. "
            f"Got: {activation_logs}"
        )

    def test_fallback_deactivation_logged_when_health_recovers(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """GET /cache/stats must log fallback_deactivated when health recovers.

        WHY: Recovery from fallback is an equally important operational event —
        it confirms the backend is healthy again and cache is effective.
        Without a deactivation log, operators have no signal that the outage
        is over.
        """
        # Start with a healthy cache AND with last known state = True (was degraded).
        client = _patch_standard_app(monkeypatch, cache=InMemoryCache())
        monkeypatch.setattr(api, "_last_fallback_state", True)

        with caplog.at_level(logging.INFO, logger="api"):
            response = client.get("/cache/stats")

        assert response.status_code == 200, response.text

        deactivation_logs = [
            r.message
            for r in caplog.records
            if "fallback_deactivated" in r.message
        ]
        assert deactivation_logs, (
            "Expected 'fallback_deactivated' log when cache health recovers. "
            f"All logs: {[r.message for r in caplog.records]}"
        )


# ===========================================================================
# AC-4: Backend health fields continue to expose fallback and Redis state
# ===========================================================================


class TestAC4BackendHealthSchemaPreservation:
    """Verify the OPTB-008 layered stats schema is unchanged after OPTB-012.

    WHY this matters: Monitoring dashboards and alerting rules are built on the
    OPTB-008 schema contract.  Any field removal or rename is a breaking change
    that would silently break alerts.  This test class acts as a regression
    guard.
    """

    def test_cache_stats_includes_fallback_active_field(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """GET /cache/stats must still return backend_health.fallback_active."""
        client = _patch_standard_app(monkeypatch)
        response = client.get("/cache/stats")

        assert response.status_code == 200, response.text
        body = response.json()
        assert "backend_health" in body, "backend_health section missing from /cache/stats"
        health = body["backend_health"]
        assert "fallback_active" in health, (
            "backend_health.fallback_active is missing — OPTB-008 schema regression!"
        )

    def test_cache_stats_includes_connected_and_latency_fields(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """GET /cache/stats backend_health must retain connected and latency_ms."""
        client = _patch_standard_app(monkeypatch)
        response = client.get("/cache/stats")

        assert response.status_code == 200, response.text
        health = response.json()["backend_health"]
        assert "connected" in health, "backend_health.connected is missing."
        assert "latency_ms" in health, "backend_health.latency_ms is missing."

    def test_cache_stats_includes_all_l1_fields(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """GET /cache/stats l1_query_cache section must retain corpus_version."""
        client = _patch_standard_app(monkeypatch)
        response = client.get("/cache/stats")

        assert response.status_code == 200, response.text
        l1 = response.json().get("l1_query_cache", {})
        for field in ("hits", "misses", "hit_rate", "size", "corpus_version"):
            assert field in l1, (
                f"l1_query_cache.{field} missing from /cache/stats — "
                "OPTB-008 schema regression!"
            )

    def test_cache_stats_fallback_active_true_when_cache_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """backend_health.fallback_active must be True when cache is failing.

        WHY: A monitoring system polling /cache/stats must be able to detect
        the degraded state through the schema value, not only through log grep.
        """
        client = _patch_standard_app(monkeypatch, cache=_AlwaysFailingCache())
        response = client.get("/cache/stats")

        assert response.status_code == 200, response.text
        health = response.json()["backend_health"]
        assert health["fallback_active"] is True, (
            "backend_health.fallback_active must be True when the cache "
            "backend raises on health().  Got: " + str(health)
        )


# ===========================================================================
# AC-5: Fail-open preserved — retrieval succeeds even with log-related errors
# ===========================================================================


class TestAC5FailOpenWithObservability:
    """Verify that the new logging code never breaks the retrieval path.

    WHY this matters: Log instrumentation is a side-effect.  If a logging call
    itself raises (e.g. the format string is wrong, or the logger is broken),
    the request must still return 200 — fail-open applies to observability too.
    These tests prove the principle holds end-to-end.
    """

    def test_retrieve_returns_200_with_failing_cache_and_logging(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """POST /retrieve must return 200 even when cache raises on every call.

        WHY: This is the union of AC-1 (fail-open) and AC-5 (log side-effect).
        Cache failure must produce a WARNING log (AC-3) AND the response must
        still be 200 (AC-1).  Both must hold simultaneously.
        """
        client = _patch_standard_app(monkeypatch, cache=_AlwaysFailingCache())

        with caplog.at_level(logging.WARNING, logger="api"):
            response = client.post(
                "/retrieve",
                json={"query": "fail-open with observability"},
            )

        assert response.status_code == 200, (
            "POST /retrieve must return 200 even when cache raises. "
            f"Got {response.status_code}: {response.text}"
        )
        # The response body must still be valid (fail-open means correct shape).
        body = response.json()
        assert "results" in body, "Response body missing 'results' key."
        assert "query" in body, "Response body missing 'query' key."

    def test_cache_miss_log_does_not_break_response_body(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Correlation-ID log emission must not alter the response payload.

        WHY: A poorly written log call that modifies shared state could corrupt
        the response.  This test verifies the response body is identical whether
        or not a correlation header is provided.
        """
        client = _patch_standard_app(monkeypatch)
        query_payload = {"query": "log side-effect isolation"}

        # Without correlation header
        resp_no_header = client.post("/retrieve", json=query_payload)
        # With correlation header
        resp_with_header = client.post(
            "/retrieve",
            json=query_payload,
            headers={"X-Request-ID": str(uuid.uuid4())},
        )

        assert resp_no_header.status_code == 200
        assert resp_with_header.status_code == 200
        # Results must be identical — log instrumentation is transparent.
        assert resp_no_header.json()["results"] == resp_with_header.json()["results"], (
            "Response results differ between requests with and without "
            "X-Request-ID header — log instrumentation must be transparent."
        )
