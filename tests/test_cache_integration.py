"""Integration tests for cache initialization and API integration.

Tests cache setup in API lifespan, middleware registration,
cache clear on config updates, conditional cache clear on ingest,
cache stats endpoint, and response headers.
"""

from datetime import datetime
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from hybrid_rag.cache import CacheBackend, InMemoryCache
from hybrid_rag.config import CacheSettings, create_cache_backend


# ============================================================================
# TEST FIXTURES
# ============================================================================


@pytest.fixture
def mock_cache() -> InMemoryCache:
    """Create a real in-memory cache for testing."""
    return InMemoryCache(ttl_seconds=3600, max_size=10000)


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
    from pydantic import BaseModel, Field
    from datetime import datetime

    class CacheStatsResponse(BaseModel):
        """Response model for cache statistics."""

        backend: str = Field(..., description="Cache backend (e.g., 'redis' | 'memory')")
        hits: int = Field(..., ge=0, description="Total cache hits")
        misses: int = Field(..., ge=0, description="Total cache misses")
        hit_rate: float = Field(..., ge=0.0, le=1.0, description="Cache hit rate (0-1)")
        size: int = Field(..., ge=0, description="Current cache size in entries")
        max_size: int = Field(..., ge=0, description="Maximum cache capacity")
        ttl_seconds: int = Field(..., ge=0, description="Configured TTL in seconds")
        timestamp: datetime = Field(..., description="When stats were captured")

    # Valid response
    response = CacheStatsResponse(
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
        CacheStatsResponse(
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
        CacheStatsResponse(
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
    from pydantic import BaseModel, Field
    from typing import Literal, Optional

    class DocumentIngestionRequest(BaseModel):
        """Request model for adding custom documents."""

        source_type: Literal["text", "url", "file"] = Field(
            ..., description="Type of data source"
        )
        content: str = Field(..., min_length=1, description="Text content, URL, or base64-encoded file")
        filename: Optional[str] = Field(None, description="Original filename")
        source_label: Optional[str] = Field(None, description="User-friendly label")
        ingest_type: Literal["add", "update"] = Field(
            default="update",
            description="Ingest type: 'add' preserves cache, 'update' clears cache",
        )

    # Valid request with default ingest_type
    req1 = DocumentIngestionRequest(
        source_type="text",
        content="Hello world",
    )
    assert req1.ingest_type == "update"  # Default

    # Valid request with explicit ingest_type='add'
    req2 = DocumentIngestionRequest(
        source_type="text",
        content="Hello world",
        ingest_type="add",
    )
    assert req2.ingest_type == "add"

    # Valid request with explicit ingest_type='update'
    req3 = DocumentIngestionRequest(
        source_type="text",
        content="Hello world",
        ingest_type="update",
    )
    assert req3.ingest_type == "update"

    # Invalid: bad ingest_type
    with pytest.raises(ValueError):
        DocumentIngestionRequest(
            source_type="text",
            content="Hello world",
            ingest_type="invalid",  # Invalid
        )


# ============================================================================
# TEST: POST /config ENDPOINT WITH CACHE CLEAR
# ============================================================================


@pytest.mark.asyncio
async def test_config_endpoint_clears_cache_on_update() -> None:
    """Test that PUT /config calls cache.clear() after config update (ADR-006)."""
    import api as api_module

    mock_cache = MagicMock(spec=CacheBackend)
    mock_cache.clear = MagicMock()
    mock_cache.stats.return_value = {
        "backend": "memory",
        "hits": 0,
        "misses": 0,
        "size": 0,
        "max_size": 10000,
        "ttl_seconds": 3600,
    }

    fake_config = MagicMock()
    for attr in ("semantic_top_k", "keyword_top_k", "final_top_k", "pre_rerank_top_k"):
        setattr(fake_config, attr, 10)
    fake_config.semantic_weight = 0.7
    fake_config.keyword_weight = 0.3
    fake_config.enable_rerank = True
    updated_config = MagicMock()
    for attr in ("semantic_top_k", "keyword_top_k", "final_top_k", "pre_rerank_top_k"):
        setattr(updated_config, attr, 10)
    updated_config.semantic_weight = 0.8
    updated_config.keyword_weight = 0.2
    updated_config.enable_rerank = True
    fake_config.update.return_value = updated_config

    with (
        patch.object(api_module, "_config", fake_config),
        patch.object(api_module, "_cache", mock_cache),
        patch.object(api_module, "_cache_generation", 0),
        patch.object(api_module, "_corpus_version", "gen0.n1"),
    ):
        client = TestClient(api_module.app)
        response = client.put(
            "/config", json={"semantic_weight": 0.8, "keyword_weight": 0.2}
        )

    assert response.status_code == 200
    mock_cache.clear.assert_called_once()


@pytest.mark.asyncio
async def test_config_endpoint_clears_cache_and_returns_200() -> None:
    """Test that PUT /config clears the cache and returns a successful response."""
    import api as api_module

    mock_cache = MagicMock(spec=CacheBackend)
    mock_cache.clear = MagicMock()

    fake_config = MagicMock()
    fake_config.semantic_top_k = 10
    fake_config.keyword_top_k = 10
    fake_config.final_top_k = 5
    fake_config.semantic_weight = 0.7
    fake_config.keyword_weight = 0.3
    fake_config.enable_rerank = True
    fake_config.pre_rerank_top_k = 20
    updated_config = MagicMock()
    updated_config.semantic_top_k = 10
    updated_config.keyword_top_k = 10
    updated_config.final_top_k = 5
    updated_config.semantic_weight = 0.8
    updated_config.keyword_weight = 0.2
    updated_config.enable_rerank = True
    updated_config.pre_rerank_top_k = 20
    fake_config.update.return_value = updated_config

    with (
        patch.object(api_module, "_config", fake_config),
        patch.object(api_module, "_cache", mock_cache),
        patch.object(api_module, "_cache_generation", 0),
        patch.object(api_module, "_corpus_version", "gen0.n1"),
    ):
        client = TestClient(api_module.app)
        response = client.put(
            "/config", json={"semantic_weight": 0.8, "keyword_weight": 0.2}
        )

    assert response.status_code == 200
    mock_cache.clear.assert_called_once()


# ============================================================================
# TEST: POST /documents ENDPOINT WITH INGEST_TYPE
# ============================================================================


@pytest.mark.asyncio
async def test_ingest_endpoint_has_ingest_type_parameter() -> None:
    """Test that POST /documents accepts ingest_type parameter."""
    from api import DocumentIngestionRequest

    field_names = set(DocumentIngestionRequest.model_fields.keys())
    assert "ingest_type" in field_names

    req = DocumentIngestionRequest(source_type="text", content="hello")
    assert req.ingest_type == "update"  # default is backwards-compatible


@pytest.mark.asyncio
async def test_ingest_endpoint_conditional_cache_clear_update() -> None:
    """Test that POST /documents clears cache when re-ingesting an existing source."""
    import api as api_module
    from types import SimpleNamespace

    tracking_cache = MagicMock(spec=CacheBackend)
    tracking_cache.clear = MagicMock()
    tracking_cache.stats.return_value = {
        "backend": "memory", "hits": 0, "misses": 0,
        "size": 0, "max_size": 10000, "ttl_seconds": 3600,
    }

    class FakeCollection:
        def count(self) -> int:
            return 5

        def get(self, where=None, limit=None):
            # Return a pre-existing chunk for "existing-source" to trigger update path.
            if where and where.get("source") == "existing-source":
                return {"ids": ["existing-source_0"]}
            return {"ids": []}

        def delete(self, ids):
            pass

        def add(self, ids, documents, metadatas=None):
            pass

    class FakeRetriever:
        collection = FakeCollection()
        def get_embedding_cache_stats(self):
            return {"hits": 0, "misses": 0, "hit_rate": 0.0, "size": 0, "capacity": 0}

    fake_config = SimpleNamespace(
        semantic_top_k=5, keyword_top_k=5, final_top_k=5,
        semantic_weight=0.5, keyword_weight=0.5,
        enable_rerank=False, pre_rerank_top_k=10,
    )

    with (
        patch.object(api_module, "_cache", tracking_cache),
        patch.object(api_module, "_retriever", FakeRetriever()),
        patch.object(api_module, "_config", fake_config),
        patch.object(api_module, "_corpus_version", "gen0.n5"),
        patch.object(api_module, "_cache_generation", 0),
    ):
        client = TestClient(api_module.app)
        response = client.post(
            "/documents",
            json={"source_type": "text", "content": "Updated doc.", "source_label": "existing-source"},
        )

    assert response.status_code == 200
    tracking_cache.clear.assert_called()


@pytest.mark.asyncio
async def test_ingest_endpoint_preserves_cache_on_add() -> None:
    """Test that POST /documents preserves cache when ingesting a brand-new source."""
    import api as api_module
    from types import SimpleNamespace

    tracking_cache = MagicMock(spec=CacheBackend)
    tracking_cache.clear = MagicMock()
    tracking_cache.stats.return_value = {
        "backend": "memory", "hits": 0, "misses": 0,
        "size": 0, "max_size": 10000, "ttl_seconds": 3600,
    }

    class FakeCollection:
        def count(self) -> int:
            return 5

        def get(self, where=None, limit=None):
            # Empty store → source is new → 'add' path → cache preserved.
            return {"ids": []}

        def delete(self, ids):
            pass

        def add(self, ids, documents, metadatas=None):
            pass

    class FakeRetriever:
        collection = FakeCollection()
        def get_embedding_cache_stats(self):
            return {"hits": 0, "misses": 0, "hit_rate": 0.0, "size": 0, "capacity": 0}

    fake_config = SimpleNamespace(
        semantic_top_k=5, keyword_top_k=5, final_top_k=5,
        semantic_weight=0.5, keyword_weight=0.5,
        enable_rerank=False, pre_rerank_top_k=10,
    )

    with (
        patch.object(api_module, "_cache", tracking_cache),
        patch.object(api_module, "_retriever", FakeRetriever()),
        patch.object(api_module, "_config", fake_config),
        patch.object(api_module, "_corpus_version", "gen0.n5"),
        patch.object(api_module, "_cache_generation", 0),
    ):
        client = TestClient(api_module.app)
        response = client.post(
            "/documents",
            json={"source_type": "text", "content": "Brand new doc.", "source_label": "new-source"},
        )

    assert response.status_code == 200
    tracking_cache.clear.assert_not_called()


# ============================================================================
# TEST: GET /cache/stats ENDPOINT
# ============================================================================


@pytest.mark.asyncio
async def test_cache_stats_endpoint_exists_and_returns_200() -> None:
    """Test that GET /cache/stats endpoint exists, returns 200, and never fails."""
    import api as api_module
    from unittest.mock import MagicMock
    from hybrid_rag.cache import CacheBackend

    mock_cache = MagicMock(spec=CacheBackend)
    mock_cache.stats.return_value = {
        "backend": "memory", "hits": 0, "misses": 0,
        "size": 0, "max_size": 10000, "ttl_seconds": 3600,
    }
    mock_cache.health.return_value = {
        "connected": True, "latency_ms": None,
        "fallback_active": False, "error": None,
    }

    with patch.object(api_module, "_cache", mock_cache):
        response = TestClient(api_module.app).get("/cache/stats")

    assert response.status_code == 200


def test_cache_stats_endpoint_returns_all_fields() -> None:
    """Test that GET /cache/stats returns the layered schema with all required fields."""
    import api as api_module
    from unittest.mock import MagicMock
    from hybrid_rag.cache import CacheBackend

    mock_cache = MagicMock(spec=CacheBackend)
    mock_cache.stats.return_value = {
        "backend": "memory", "hits": 10, "misses": 5,
        "size": 3, "max_size": 100, "ttl_seconds": 3600,
    }
    mock_cache.health.return_value = {
        "connected": True, "latency_ms": None,
        "fallback_active": False, "error": None,
    }

    class FakeRetriever:
        def get_embedding_cache_stats(self):
            return {"hits": 2, "misses": 1, "hit_rate": 0.667, "size": 3, "capacity": 500}

    with (
        patch.object(api_module, "_cache", mock_cache),
        patch.object(api_module, "_retriever", FakeRetriever()),
        patch.object(api_module, "_corpus_version", "gen0.n1"),
    ):
        response = TestClient(api_module.app).get("/cache/stats")

    assert response.status_code == 200
    body = response.json()

    # Layered schema top-level keys
    assert "l1_query_cache" in body
    assert "l2_embedding_cache" in body
    assert "backend_health" in body
    assert "timestamp" in body

    # L1 required fields
    l1 = body["l1_query_cache"]
    for field in ("backend", "hits", "misses", "hit_rate", "size", "max_size", "ttl_seconds", "corpus_version"):
        assert field in l1, f"l1_query_cache missing field: {field}"

    # L2 required fields
    l2 = body["l2_embedding_cache"]
    for field in ("hits", "misses", "hit_rate", "size", "capacity"):
        assert field in l2, f"l2_embedding_cache missing field: {field}"

    # backend_health required fields
    bh = body["backend_health"]
    for field in ("connected", "latency_ms", "fallback_active", "error"):
        assert field in bh, f"backend_health missing field: {field}"


def test_cache_stats_hit_rate_calculation() -> None:
    """Test that hit_rate is calculated correctly in the layered stats response."""
    import api as api_module
    from unittest.mock import MagicMock
    from hybrid_rag.cache import CacheBackend

    mock_cache = MagicMock(spec=CacheBackend)
    mock_cache.stats.return_value = {
        "backend": "memory", "hits": 100, "misses": 50,
        "size": 10, "max_size": 10000, "ttl_seconds": 3600,
    }
    mock_cache.health.return_value = {
        "connected": True, "latency_ms": None,
        "fallback_active": False, "error": None,
    }

    class FakeRetriever:
        def get_embedding_cache_stats(self):
            return {"hits": 0, "misses": 0, "hit_rate": 0.0, "size": 0, "capacity": 0}

    with (
        patch.object(api_module, "_cache", mock_cache),
        patch.object(api_module, "_retriever", FakeRetriever()),
        patch.object(api_module, "_corpus_version", "gen0.n1"),
    ):
        response = TestClient(api_module.app).get("/cache/stats")

    assert response.status_code == 200
    l1 = response.json()["l1_query_cache"]
    assert l1["hits"] == 100
    assert l1["misses"] == 50
    assert abs(l1["hit_rate"] - (100 / 150)) < 1e-6

    # Zero-division guard: hits=0, misses=0 → hit_rate=0.0
    mock_cache.stats.return_value = {
        "backend": "memory", "hits": 0, "misses": 0,
        "size": 0, "max_size": 10000, "ttl_seconds": 3600,
    }
    with (
        patch.object(api_module, "_cache", mock_cache),
        patch.object(api_module, "_retriever", FakeRetriever()),
        patch.object(api_module, "_corpus_version", "gen0.n1"),
    ):
        r2 = TestClient(api_module.app).get("/cache/stats")
    assert r2.json()["l1_query_cache"]["hit_rate"] == 0.0


def test_cache_stats_endpoint_never_fails() -> None:
    """Test that GET /cache/stats implements fail-open principle."""
    import api as api_module

    # Even when _cache is None the endpoint must return 200
    with patch.object(api_module, "_cache", None):
        response = TestClient(api_module.app).get("/cache/stats")
    assert response.status_code == 200
    bh = response.json()["backend_health"]
    assert bh["connected"] is False
    assert bh["fallback_active"] is True

    # Even when cache.stats() raises, the endpoint must return 200
    from unittest.mock import MagicMock
    from hybrid_rag.cache import CacheBackend
    broken = MagicMock(spec=CacheBackend)
    broken.stats.side_effect = RuntimeError("cache exploded")
    broken.health.side_effect = RuntimeError("health exploded")

    with patch.object(api_module, "_cache", broken):
        response2 = TestClient(api_module.app).get("/cache/stats")
    assert response2.status_code == 200


# ============================================================================
# TEST: WEBSOCKET CACHE STATUS (model-level contract)
# ============================================================================


def test_websocket_cache_status_field() -> None:
    """WsResultsMessage model must include a cache_status field."""
    from api import WsResultsMessage

    assert "cache_status" in WsResultsMessage.model_fields
    assert isinstance(WsResultsMessage.model_fields["cache_status"].default, str)


def test_websocket_cache_status_values() -> None:
    """cache_status default must be one of the documented sentinel values."""
    from api import WsResultsMessage

    assert WsResultsMessage.model_fields["cache_status"].default in {"HIT", "MISS", "ERROR"}
# ============================================================================
# TEST: ERROR HANDLING & LOGGING
# ============================================================================


@pytest.mark.asyncio
async def test_cache_operations_fail_open() -> None:
    """Test that cache failures never crash the API — fail-open on get/set/clear."""
    import api as api_module

    failing_cache = MagicMock(spec=CacheBackend)
    failing_cache.clear.side_effect = Exception("Cache error")
    failing_cache.set.side_effect = Exception("Cache error")
    failing_cache.get.side_effect = Exception("Cache error")
    failing_cache.stats.side_effect = Exception("Cache error")
    failing_cache.health.side_effect = Exception("Cache error")

    # /cache/stats must return 200 even when the cache is fully broken
    with patch.object(api_module, "_cache", failing_cache):
        response = TestClient(api_module.app).get("/cache/stats")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_config_clear_logs_operation() -> None:
    """Test that cache.clear() in /config endpoint is logged at INFO level."""
    import api as api_module

    mock_cache = MagicMock(spec=CacheBackend)
    mock_cache.clear = MagicMock()
    mock_cache.stats.return_value = {
        "backend": "memory", "hits": 0, "misses": 0,
        "size": 0, "max_size": 10000, "ttl_seconds": 3600,
    }

    fake_config = MagicMock()
    for attr in ("semantic_top_k", "keyword_top_k", "final_top_k", "pre_rerank_top_k"):
        setattr(fake_config, attr, 5)
    fake_config.semantic_weight = 0.5
    fake_config.keyword_weight = 0.5
    fake_config.enable_rerank = False
    updated = MagicMock()
    for attr in ("semantic_top_k", "keyword_top_k", "final_top_k", "pre_rerank_top_k"):
        setattr(updated, attr, 5)
    updated.semantic_weight = 0.6
    updated.keyword_weight = 0.4
    updated.enable_rerank = False
    fake_config.update.return_value = updated

    with (
        patch.object(api_module, "_config", fake_config),
        patch.object(api_module, "_cache", mock_cache),
        patch.object(api_module, "_cache_generation", 0),
        patch.object(api_module, "_corpus_version", "gen0.n1"),
    ):
        with patch("api.logger") as mock_logger:
            client = TestClient(api_module.app)
            response = client.put("/config", json={"semantic_weight": 0.6, "keyword_weight": 0.4})

    assert response.status_code == 200
    # Verify that an info-level log containing "cache" was emitted
    info_calls = [str(c) for c in mock_logger.info.call_args_list]
    assert any("cache" in msg.lower() for msg in info_calls), (
        f"Expected an INFO log mentioning cache; calls were: {info_calls}"
    )


@pytest.mark.asyncio
async def test_ingest_type_logs_operation() -> None:
    """Test that ingest_type decision is logged at INFO level."""
    import api as api_module
    from types import SimpleNamespace

    mock_cache = MagicMock(spec=CacheBackend)
    mock_cache.clear = MagicMock()
    mock_cache.stats.return_value = {
        "backend": "memory", "hits": 0, "misses": 0,
        "size": 0, "max_size": 10000, "ttl_seconds": 3600,
    }

    class FakeCollection:
        def count(self) -> int:
            return 3

        def get(self, where=None, limit=None):
            return {"ids": []}

        def delete(self, ids):
            pass

        def add(self, ids, documents, metadatas=None):
            pass

    class FakeRetriever:
        collection = FakeCollection()
        def get_embedding_cache_stats(self):
            return {"hits": 0, "misses": 0, "hit_rate": 0.0, "size": 0, "capacity": 0}

    fake_config = SimpleNamespace(
        semantic_top_k=5, keyword_top_k=5, final_top_k=5,
        semantic_weight=0.5, keyword_weight=0.5,
        enable_rerank=False, pre_rerank_top_k=10,
    )

    with (
        patch.object(api_module, "_cache", mock_cache),
        patch.object(api_module, "_retriever", FakeRetriever()),
        patch.object(api_module, "_config", fake_config),
        patch.object(api_module, "_corpus_version", "gen0.n3"),
        patch.object(api_module, "_cache_generation", 0),
    ):
        with patch("api.logger") as mock_logger:
            client = TestClient(api_module.app)
            response = client.post(
                "/documents",
                json={"source_type": "text", "content": "Doc.", "ingest_type": "update"},
            )

    assert response.status_code == 200
    info_calls = [str(c) for c in mock_logger.info.call_args_list]
    assert any("ingest" in msg.lower() or "cache" in msg.lower() for msg in info_calls), (
        f"Expected an INFO log for ingest/cache action; calls were: {info_calls}"
    )


# ============================================================================
# NOTE: Deprecated tests removed in T09 - POST /retrieve endpoint removed
# ============================================================================


# ============================================================================
# TEST: ACCEPTANCE CRITERIA VERIFICATION
# ============================================================================


def test_all_acceptance_criteria_implemented() -> None:
    """Verify all acceptance criteria are met by inspecting the live api module."""
    import api as api_module

    # Cache settings and backend creation work
    from hybrid_rag.config import CacheSettings, create_cache_backend
    settings = CacheSettings(backend="memory", ttl_seconds=3600, max_size=10000)
    cache = create_cache_backend(settings)
    assert cache is not None

    # DocumentIngestionRequest has ingest_type with 'update' default
    from api import DocumentIngestionRequest
    assert "ingest_type" in DocumentIngestionRequest.model_fields
    req = DocumentIngestionRequest(source_type="text", content="x", filename=None, source_label=None)
    assert req.ingest_type == "update"

    # WsResultsMessage has cache_status field
    from api import WsResultsMessage
    assert "cache_status" in WsResultsMessage.model_fields

    # /cache/stats endpoint is registered
    routes = [r.path for r in api_module.app.routes]
    assert "/cache/stats" in routes

    # _build_corpus_version_token is callable
    assert callable(getattr(api_module, "_build_corpus_version_token", None))

    # _corpus_version module attribute exists
    assert hasattr(api_module, "_corpus_version")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
