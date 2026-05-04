"""Tests for FastAPI /mcp/ protocol endpoints in api.py."""

from typing import Any, Optional

import pytest
from fastapi.testclient import TestClient

import api


# ---------------------------------------------------------------------------
# Shared retrieval stub
# ---------------------------------------------------------------------------

def fake_retrieve(
    query: str,
    enable_rerank: Optional[bool] = None,
    correlation_id: Optional[str] = None,
    _out_cache_status: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    """Minimal shared-retrieval stub that returns one document above threshold."""
    if _out_cache_status is not None:
        _out_cache_status.append("MISS")
    return [
        {
            "id": "mcp-doc-1",
            "text": "MCP test document",
            "metadata": {"source": "mcp-test.txt", "source_url": None},
            "score": 0.90,
        }
    ]


# ---------------------------------------------------------------------------
# GET /mcp/health
# ---------------------------------------------------------------------------

class TestMcpHealth:
    """Tests for GET /mcp/health."""

    def test_health_returns_200_and_ok_status(self, fake_initialized_app: TestClient) -> None:
        response = fake_initialized_app.get("/mcp/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_health_returns_200_when_retriever_is_none(
        self, fake_initialized_app: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Health endpoint is always available — it is a liveness probe and must
        # not depend on retriever state.
        monkeypatch.setattr(api, "_retriever", None)
        response = fake_initialized_app.get("/mcp/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_health_content_type_is_json(self, fake_initialized_app: TestClient) -> None:
        response = fake_initialized_app.get("/mcp/health")
        assert "application/json" in response.headers["content-type"]


# ---------------------------------------------------------------------------
# GET /mcp/config
# ---------------------------------------------------------------------------

class TestMcpGetConfig:
    """Tests for GET /mcp/config."""

    def test_get_config_returns_200_with_required_fields(
        self, fake_initialized_app: TestClient
    ) -> None:
        response = fake_initialized_app.get("/mcp/config")
        assert response.status_code == 200
        data = response.json()
        required_fields = [
            "semantic_top_k",
            "keyword_top_k",
            "final_top_k",
            "semantic_weight",
            "keyword_weight",
            "enable_rerank",
            "pre_rerank_top_k",
            "collection_name",
        ]
        for field in required_fields:
            assert field in data, f"Expected field '{field}' in /mcp/config response"

    def test_get_config_returns_503_when_retriever_not_initialized(
        self, fake_initialized_app: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(api, "_retriever", None)
        monkeypatch.setattr(api, "_config", None)
        response = fake_initialized_app.get("/mcp/config")
        assert response.status_code == 503
        assert "detail" in response.json()

    def test_get_config_values_match_current_state(
        self, fake_initialized_app: TestClient
    ) -> None:
        """Config endpoint returns values that match the current module-level config."""
        response = fake_initialized_app.get("/mcp/config")
        assert response.status_code == 200
        data = response.json()
        assert data["semantic_weight"] == api._config.semantic_weight
        assert data["keyword_weight"] == api._config.keyword_weight
        assert data["enable_rerank"] == api._config.enable_rerank


# ---------------------------------------------------------------------------
# PUT /mcp/config
# ---------------------------------------------------------------------------

class TestMcpPutConfig:
    """Tests for PUT /mcp/config."""

    def test_put_config_updates_semantic_weight(
        self, fake_initialized_app: TestClient
    ) -> None:
        response = fake_initialized_app.put(
            "/mcp/config", json={"semantic_weight": 0.6, "keyword_weight": 0.4}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["semantic_weight"] == 0.6
        assert data["keyword_weight"] == 0.4

    def test_put_config_empty_body_returns_current_config(
        self, fake_initialized_app: TestClient
    ) -> None:
        # Empty body → no changes, returns existing config unchanged.
        response = fake_initialized_app.put("/mcp/config", json={})
        assert response.status_code == 200
        assert "semantic_top_k" in response.json()

    def test_put_config_returns_503_when_not_initialized(
        self, fake_initialized_app: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(api, "_config", None)
        response = fake_initialized_app.put(
            "/mcp/config", json={"enable_rerank": False}
        )
        assert response.status_code == 503
        assert "detail" in response.json()

    def test_put_config_rejects_invalid_collection_name(
        self, fake_initialized_app: TestClient
    ) -> None:
        # Dots and spaces are not allowed in collection names.
        response = fake_initialized_app.put(
            "/mcp/config", json={"collection_name": "bad.name!"}
        )
        assert response.status_code == 400
        assert "detail" in response.json()

    def test_put_config_increments_cache_generation(
        self, fake_initialized_app: TestClient
    ) -> None:
        original_generation = api._cache_generation
        fake_initialized_app.put("/mcp/config", json={"enable_rerank": False})
        assert api._cache_generation == original_generation + 1

    def test_put_config_returns_all_required_fields(
        self, fake_initialized_app: TestClient
    ) -> None:
        response = fake_initialized_app.put("/mcp/config", json={"enable_rerank": True})
        assert response.status_code == 200
        data = response.json()
        for field in [
            "semantic_top_k",
            "keyword_top_k",
            "final_top_k",
            "semantic_weight",
            "keyword_weight",
            "enable_rerank",
            "pre_rerank_top_k",
            "collection_name",
        ]:
            assert field in data


# ---------------------------------------------------------------------------
# POST /mcp/query
# ---------------------------------------------------------------------------

class TestMcpQuery:
    """Tests for POST /mcp/query."""

    def test_query_returns_200_with_results(
        self, fake_initialized_app: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(api, "_shared_retrieve_documents", fake_retrieve)
        response = fake_initialized_app.post(
            "/mcp/query", json={"query": "test query"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert "total_results" in data
        assert isinstance(data["results"], list)
        assert isinstance(data["total_results"], int)

    def test_query_response_contains_document_fields(
        self, fake_initialized_app: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(api, "_shared_retrieve_documents", fake_retrieve)
        response = fake_initialized_app.post(
            "/mcp/query", json={"query": "hello world"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total_results"] == 1
        doc = data["results"][0]
        assert doc["id"] == "mcp-doc-1"
        assert doc["text"] == "MCP test document"

    def test_query_returns_503_when_not_initialized(
        self, fake_initialized_app: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(api, "_retriever", None)
        monkeypatch.setattr(api, "_config", None)
        response = fake_initialized_app.post(
            "/mcp/query", json={"query": "should fail"}
        )
        assert response.status_code == 503
        assert "detail" in response.json()

    def test_query_rejects_empty_query(
        self, fake_initialized_app: TestClient
    ) -> None:
        response = fake_initialized_app.post("/mcp/query", json={"query": ""})
        assert response.status_code == 400
        assert "detail" in response.json()

    def test_query_rejects_oversized_query(
        self, fake_initialized_app: TestClient
    ) -> None:
        response = fake_initialized_app.post(
            "/mcp/query", json={"query": "x" * 501}
        )
        assert response.status_code == 400
        assert "detail" in response.json()

    def test_query_accepts_enable_rerank_override(
        self, fake_initialized_app: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[dict[str, Any]] = []

        def _record_retrieve(
            query: str,
            enable_rerank: Optional[bool] = None,
            correlation_id: Optional[str] = None,
            _out_cache_status: Optional[list[str]] = None,
        ) -> list[dict[str, Any]]:
            calls.append({"query": query, "enable_rerank": enable_rerank})
            if _out_cache_status is not None:
                _out_cache_status.append("MISS")
            return [
                {
                    "id": "d1",
                    "text": "doc",
                    "metadata": {"source": "s.txt", "source_url": None},
                    "score": 0.90,
                }
            ]

        monkeypatch.setattr(api, "_shared_retrieve_documents", _record_retrieve)
        response = fake_initialized_app.post(
            "/mcp/query", json={"query": "test", "enable_rerank": True}
        )
        assert response.status_code == 200
        assert len(calls) == 1
        assert calls[0]["enable_rerank"] is True

    def test_query_filters_low_score_results(
        self, fake_initialized_app: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Results below 0.40 relevance threshold are excluded from the response."""

        def _low_score_retrieve(
            query: str,
            enable_rerank: Optional[bool] = None,
            correlation_id: Optional[str] = None,
            _out_cache_status: Optional[list[str]] = None,
        ) -> list[dict[str, Any]]:
            if _out_cache_status is not None:
                _out_cache_status.append("MISS")
            return [
                {
                    "id": "high",
                    "text": "relevant",
                    "metadata": {"source": "a.txt", "source_url": None},
                    "score": 0.85,
                },
                {
                    "id": "low",
                    "text": "irrelevant",
                    "metadata": {"source": "b.txt", "source_url": None},
                    "score": 0.20,  # below 0.40 threshold
                },
            ]

        monkeypatch.setattr(api, "_shared_retrieve_documents", _low_score_retrieve)
        response = fake_initialized_app.post(
            "/mcp/query", json={"query": "filter test"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total_results"] == 1
        assert data["results"][0]["id"] == "high"

    def test_query_returns_empty_results_when_all_filtered(
        self, fake_initialized_app: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _all_low(
            query: str,
            enable_rerank: Optional[bool] = None,
            correlation_id: Optional[str] = None,
            _out_cache_status: Optional[list[str]] = None,
        ) -> list[dict[str, Any]]:
            if _out_cache_status is not None:
                _out_cache_status.append("MISS")
            return [
                {
                    "id": "d1",
                    "text": "low",
                    "metadata": {"source": "x.txt", "source_url": None},
                    "score": 0.10,
                }
            ]

        monkeypatch.setattr(api, "_shared_retrieve_documents", _all_low)
        response = fake_initialized_app.post(
            "/mcp/query", json={"query": "nothing relevant"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total_results"] == 0
        assert data["results"] == []

    def test_query_missing_body_returns_422(
        self, fake_initialized_app: TestClient
    ) -> None:
        """Missing request body returns 422 Unprocessable Entity (FastAPI validation)."""
        response = fake_initialized_app.post("/mcp/query")
        assert response.status_code == 422

    def test_query_rejects_whitespace_only(
        self, fake_initialized_app: TestClient
    ) -> None:
        """Whitespace-only queries are stripped to empty and rejected."""
        response = fake_initialized_app.post(
            "/mcp/query", json={"query": "   "}
        )
        assert response.status_code == 400
