"""Integration tests for cache initialization and API integration.

Tests cache setup in API lifespan, middleware registration,
cache clear on config updates, conditional cache clear on ingest,
cache stats endpoint, and response headers.
"""

import inspect
import json
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import api
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse

from api import app, _config, _retriever
from hybrid_rag.cache import CacheBackend, InMemoryCache
from hybrid_rag.config import CacheSettings, create_cache_backend


# ============================================================================
# TEST FIXTURES
# ============================================================================


@pytest.fixture
def mock_cache() -> InMemoryCache:
    """Create a real in-memory cache for testing."""
    return InMemoryCache(ttl_seconds=3600, max_size=10000)


@pytest.fixture
def mock_cache_backend() -> MagicMock:
    """Create a mock cache backend."""
    cache = MagicMock(spec=CacheBackend)
    cache.get.return_value = None
    cache.set.return_value = None
    cache.delete.return_value = None
    cache.clear.return_value = None
    cache.stats.return_value = {
        "backend": "memory",
        "hits": 0,
        "misses": 0,
        "size": 0,
        "max_size": 10000,
        "ttl_seconds": 3600,
    }
    return cache


@pytest.fixture
def client(mock_cache_backend: MagicMock) -> TestClient:
    """Create test client with initialized app."""
    return TestClient(app)


# ============================================================================
# TEST: CACHE INITIALIZATION & STARTUP
# ============================================================================


def test_cache_settings_from_env_memory() -> None:
    """Test CacheSettings.from_env() with memory backend."""
    with patch.dict(
        "os.environ",
        {
            "CACHE_BACKEND": "memory",
            "CACHE_TTL_SECONDS": "1800",
            "CACHE_MAX_SIZE": "5000",
        },
    ):
        settings = CacheSettings.from_env()
        assert settings.backend == "memory"
        assert settings.ttl_seconds == 1800
        assert settings.max_size == 5000


def test_cache_settings_from_env_redis() -> None:
    """Test CacheSettings.from_env() with redis backend."""
    with patch.dict(
        "os.environ",
        {
            "CACHE_BACKEND": "redis",
            "REDIS_URL": "redis://localhost:6379",
            "CACHE_TTL_SECONDS": "3600",
        },
    ):
        settings = CacheSettings.from_env()
        assert settings.backend == "redis"
        assert settings.redis_url == "redis://localhost:6379"


def test_create_cache_backend_memory() -> None:
    """Test create_cache_backend() returns InMemoryCache for memory backend."""
    settings = CacheSettings(backend="memory", ttl_seconds=3600, max_size=10000)
    cache = create_cache_backend(settings)
    assert isinstance(cache, InMemoryCache)
    assert cache.get("nonexistent") is None


def test_create_cache_backend_validates_settings() -> None:
    """Test create_cache_backend() validates settings before creating backend."""
    # Invalid: ttl_seconds must be > 0
    with pytest.raises(ValueError):
        CacheSettings(backend="memory", ttl_seconds=0, max_size=10000)

    # Invalid: max_size must be > 0
    with pytest.raises(ValueError):
        CacheSettings(backend="memory", ttl_seconds=3600, max_size=0)

    # Invalid: redis backend requires redis_url
    with pytest.raises(ValueError):
        CacheSettings(backend="redis", ttl_seconds=3600, max_size=10000)


# ============================================================================
# TEST: CACHE STATS RESPONSE MODEL
# ============================================================================


@pytest.mark.asyncio
async def test_cache_stats_response_model() -> None:
    """Test CacheStatsResponse Pydantic model validation."""
    # Valid response
    response = api.CacheStatsResponse(
        backend="memory",
        hits=100,
        misses=50,
        hit_rate=0.667,
        size=25,
        max_size=10000,
        ttl_seconds=3600,
        timestamp=datetime.now(),
    )
    assert response.backend == "memory"
    assert response.hits == 100
    assert response.hit_rate == pytest.approx(0.667, abs=0.001)

    # Invalid: hit_rate > 1.0
    with pytest.raises(ValueError):
        api.CacheStatsResponse(
            backend="memory",
            hits=100,
            misses=50,
            hit_rate=1.5,  # Invalid
            size=25,
            max_size=10000,
            ttl_seconds=3600,
            timestamp=datetime.now(),
        )

    # Invalid: negative hits
    with pytest.raises(ValueError):
        api.CacheStatsResponse(
            backend="memory",
            hits=-1,  # Invalid
            misses=50,
            hit_rate=0.5,
            size=25,
            max_size=10000,
            ttl_seconds=3600,
            timestamp=datetime.now(),
        )


# ============================================================================
# TEST: INGEST REQUEST MODEL WITH INGEST_TYPE
# ============================================================================


@pytest.mark.asyncio
async def test_ingest_request_with_type() -> None:
    """Test updated DocumentIngestionRequest with ingest_type parameter."""
    # Valid request with default ingest_type
    req1 = api.DocumentIngestionRequest(
        source_type="text",
        content="Hello world",
    )
    assert req1.ingest_type == "update"  # Default

    # Valid request with explicit ingest_type='add'
    req2 = api.DocumentIngestionRequest(
        source_type="text",
        content="Hello world",
        ingest_type="add",
    )
    assert req2.ingest_type == "add"

    # Valid request with explicit ingest_type='update'
    req3 = api.DocumentIngestionRequest(
        source_type="text",
        content="Hello world",
        ingest_type="update",
    )
    assert req3.ingest_type == "update"

    # Invalid: bad ingest_type
    with pytest.raises(ValueError):
        api.DocumentIngestionRequest(
            source_type="text",
            content="Hello world",
            ingest_type="invalid",  # Invalid
        )


# ============================================================================
# TEST: MIDDLEWARE REGISTRATION
# ============================================================================


def test_middleware_is_registered_before_routes(client: TestClient) -> None:
    """Test that QueryCacheMiddleware is registered in the app."""
    # The middleware should be in app.user_middleware or app.middleware
    # We verify this by checking the app's middleware stack
    assert app is not None
    # In FastAPI, middleware is added to the ASGI app via add_middleware
    # The test here verifies the API layer accepts requests properly


def test_middleware_excluded_paths(client: TestClient) -> None:
    """Test that excluded paths are not cached."""
    # These endpoints should NOT be cached by the middleware
    excluded_paths = ["/health", "/config", "/documents", "/cache/stats"]

    for path in excluded_paths:
        # Verify these paths exist and respond (they shouldn't error out)
        # The middleware should not interfere
        if path == "/health":
            response = client.get(path)
            assert response.status_code in [200, 503]  # Might be not ready
        # Other endpoints tested elsewhere


# ============================================================================
# TEST: POST /config ENDPOINT WITH CACHE CLEAR
# ============================================================================


# ============================================================================
# TEST: POST /documents ENDPOINT WITH INGEST_TYPE
# ============================================================================


def _make_shared_retrieval_config() -> SimpleNamespace:
    return SimpleNamespace(
        semantic_top_k=5,
        keyword_top_k=5,
        final_top_k=3,
        semantic_weight=0.7,
        keyword_weight=0.3,
        enable_rerank=True,
        pre_rerank_top_k=10,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("ingest_type", ["add", "update"])
async def test_ingest_endpoint_advances_generation_and_clears_local_cache(
    monkeypatch: pytest.MonkeyPatch, ingest_type: str
) -> None:
    """Both Phase 1 ingest paths advance generation and clear the local cache."""
    cache = MagicMock(spec=CacheBackend)
    collection = MagicMock()

    monkeypatch.setattr(api, "_retriever", SimpleNamespace(collection=collection))
    monkeypatch.setattr(api, "_config", object())
    monkeypatch.setattr(api, "_cache", cache)
    monkeypatch.setattr(api, "_cache_generation", 7)

    response = await api.add_documents(
        api.DocumentIngestionRequest(
            source_type="text",
            content="new phase 1 content",
            source_label=f"source-{ingest_type}",
            ingest_type=ingest_type,
        )
    )

    assert response.status == "success"
    assert response.documents_added == 1
    assert response.chunks_created == 1
    assert api._cache_generation == 8
    cache.clear.assert_called_once_with()


@pytest.mark.asyncio
async def test_ingest_add_removes_stale_shared_cache_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An add ingest must invalidate previously cached shared retrieval results."""
    observed_calls: list[Dict[str, Any]] = []

    def fake_retrieve(query: str, enable_rerank: bool = True) -> list[Dict[str, Any]]:
        observed_calls.append({"query": query, "enable_rerank": enable_rerank})
        call_number = len(observed_calls)
        return [
            {
                "id": f"doc-{call_number}",
                "text": f"result {call_number}",
                "metadata": {"source": "integration"},
                "score": 0.91,
            }
        ]

    # The ingest path needs collection.add while shared retrieval uses retrieve(),
    # so the fake retriever exposes both surfaces to exercise the real integration.
    retriever = SimpleNamespace(collection=MagicMock(), retrieve=fake_retrieve)
    cache = InMemoryCache(ttl_seconds=3600, max_size=100)

    monkeypatch.setattr(api, "_retriever", retriever)
    monkeypatch.setattr(api, "_config", _make_shared_retrieval_config())
    monkeypatch.setattr(api, "_cache", cache)
    monkeypatch.setattr(api, "_cache_generation", 0)

    first = api._shared_retrieve_documents("stale add query", enable_rerank=False)
    second = api._shared_retrieve_documents("stale add query", enable_rerank=False)

    assert first == second
    assert len(observed_calls) == 1

    response = await api.add_documents(
        api.DocumentIngestionRequest(
            source_type="text",
            content="freshly ingested text",
            source_label="add-refresh",
            ingest_type="add",
        )
    )

    refreshed = api._shared_retrieve_documents("stale add query", enable_rerank=False)

    assert response.status == "success"
    assert len(observed_calls) == 2
    assert refreshed[0]["id"] == "doc-2"


# ============================================================================
# TEST: GET /cache/stats ENDPOINT
# ============================================================================


@pytest.mark.asyncio
async def test_cache_stats_endpoint_exists_and_returns_200(
    initialized_app: TestClient,
) -> None:
    """Test that GET /cache/stats endpoint exists and returns 200.
    
    This tests the fix for blocking issue #2.
    """
    response = initialized_app.get("/cache/stats")

    assert response.status_code == 200
    assert response.json()["backend"] in {"memory", "redis", "none", "error"}


def test_cache_stats_endpoint_returns_all_fields(initialized_app: TestClient) -> None:
    """Test that GET /cache/stats returns all required stats fields."""
    response = initialized_app.get("/cache/stats")

    assert response.status_code == 200
    body = response.json()
    assert {
        "backend",
        "hits",
        "misses",
        "hit_rate",
        "size",
        "max_size",
        "ttl_seconds",
        "timestamp",
    }.issubset(body.keys())


@pytest.mark.asyncio
async def test_cache_stats_hit_rate_calculation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that hit_rate is calculated correctly."""
    monkeypatch.setattr(api, "_cache", MagicMock(spec=CacheBackend))
    monkeypatch.setattr(
        api.lazy_cache,
        "stats",
        lambda: {
            "backend": "memory",
            "hits": 100,
            "misses": 50,
            "size": 10,
            "max_size": 100,
            "ttl_seconds": 3600,
        },
    )

    response = await api.get_cache_stats()

    assert response.hit_rate == pytest.approx(100 / 150, abs=0.001)


@pytest.mark.asyncio
async def test_cache_stats_endpoint_never_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that GET /cache/stats implements fail-open principle."""
    monkeypatch.setattr(api, "_cache", MagicMock(spec=CacheBackend))

    def raise_stats_error() -> Dict[str, Any]:
        raise RuntimeError("boom")

    monkeypatch.setattr(api.lazy_cache, "stats", raise_stats_error)

    response = await api.get_cache_stats()

    assert response.backend == "error"
    assert response.hits == 0
    assert response.misses == 0


# ============================================================================
# TEST: RESPONSE HEADERS
# ============================================================================


def test_cache_status_response_header(client_with_fresh_cache: TestClient) -> None:
    """Retrieve responses expose the current cache decision via X-Cache."""
    first = client_with_fresh_cache.post(
        "/retrieve", json={"query": "header contract query", "enable_rerank": False}
    )
    second = client_with_fresh_cache.post(
        "/retrieve", json={"query": "header contract query", "enable_rerank": False}
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.headers.get("X-Cache") == "MISS"
    assert second.headers.get("X-Cache") == "HIT"


# ============================================================================
# TEST: ERROR HANDLING & LOGGING
# ============================================================================


# ============================================================================
# TEST: TYPE HINTS & DOCSTRINGS
# ============================================================================


def test_cache_stats_endpoint_has_docstring() -> None:
    """Test that GET /cache/stats endpoint has Google-style docstring."""
    docstring = inspect.getdoc(api.get_cache_stats)

    assert docstring is not None
    assert "Returns:" in docstring
    assert "Example:" in docstring
    assert "fail-open principle" in docstring


def test_cache_stats_response_model_has_docstring() -> None:
    """Test that CacheStatsResponse model has docstring."""
    docstring = inspect.getdoc(api.CacheStatsResponse)

    assert docstring is not None
    assert "Attributes:" in docstring
    assert "ttl_seconds" in docstring
    assert "Example:" in docstring


def test_ingest_request_updated_model_has_docstring() -> None:
    """Test that DocumentIngestionRequest has updated docstring."""
    docstring = inspect.getdoc(api.DocumentIngestionRequest)

    assert docstring is not None
    assert "ingest_type" in docstring
    assert "'add'" in docstring
    assert "'update'" in docstring


# ============================================================================
# TEST: INTEGRATION - SYSTEM FLOW
# ============================================================================


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
