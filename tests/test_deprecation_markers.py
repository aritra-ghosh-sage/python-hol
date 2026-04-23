"""Tests for deprecation markers on POST /retrieve and POST /retrieve-filtered.

Verifies that:
1. Both endpoints emit Deprecation, Sunset, and Link response headers.
2. The OpenAPI schema marks both endpoints with deprecated: true.
3. Runtime behaviour (response body / status code) is unchanged.
"""

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import api
from hybrid_rag import HybridRetrieverConfig
from hybrid_rag.cache import InMemoryCache


# ---------------------------------------------------------------------------
# Shared stubs
# ---------------------------------------------------------------------------

class FakeRetriever:
    """Minimal retriever double that returns one above-threshold result."""

    def __init__(self) -> None:
        self.collection = MagicMock()
        self.collection.count.return_value = 1

    def retrieve(self, query: str, enable_rerank: Optional[bool] = None) -> List[Dict[str, Any]]:
        return [
            {
                "id": "dep-doc-1",
                "text": "deprecation test result",
                "metadata": {"source": "test-source"},
                "score": 0.92,
            }
        ]


@pytest.fixture()
def deprecation_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """TestClient with a fake retriever so no real model is loaded."""
    retriever = FakeRetriever()
    config = HybridRetrieverConfig(semantic_weight=0.7, keyword_weight=0.3, enable_rerank=False)
    monkeypatch.setattr(api, "_retriever", retriever)
    monkeypatch.setattr(api, "_config", config)
    monkeypatch.setattr(api, "_cache", InMemoryCache(ttl_seconds=3600, max_size=100))
    monkeypatch.setattr(api, "_cache_generation", 0)
    monkeypatch.setattr(api, "_corpus_version", "gen0.n1")
    return TestClient(api.app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# POST /retrieve — deprecation headers
# ---------------------------------------------------------------------------

def test_retrieve_returns_deprecation_header(deprecation_client: TestClient) -> None:
    response = deprecation_client.post("/retrieve", json={"query": "test query"})
    assert response.status_code == 200
    assert response.headers.get("deprecation") == "true"


def test_retrieve_returns_sunset_header(deprecation_client: TestClient) -> None:
    response = deprecation_client.post("/retrieve", json={"query": "test query"})
    assert response.status_code == 200
    assert response.headers.get("sunset") == "Sat, 31 Oct 2026 23:59:59 GMT"


def test_retrieve_returns_link_header(deprecation_client: TestClient) -> None:
    response = deprecation_client.post("/retrieve", json={"query": "test query"})
    assert response.status_code == 200
    assert "link" in response.headers
    assert "/ws/chat" in response.headers["link"]
    assert "successor-version" in response.headers["link"]


def test_retrieve_response_body_unchanged(deprecation_client: TestClient) -> None:
    """Deprecation headers must not change the response body or schema."""
    response = deprecation_client.post("/retrieve", json={"query": "test query"})
    assert response.status_code == 200
    body = response.json()
    assert "query" in body
    assert "results" in body
    assert "total_results" in body


# ---------------------------------------------------------------------------
# POST /retrieve-filtered — deprecation headers
# ---------------------------------------------------------------------------

def test_retrieve_filtered_returns_deprecation_header(deprecation_client: TestClient) -> None:
    response = deprecation_client.post(
        "/retrieve-filtered?min_score=0.5", json={"query": "test query"}
    )
    assert response.status_code == 200
    assert response.headers.get("deprecation") == "true"


def test_retrieve_filtered_returns_sunset_header(deprecation_client: TestClient) -> None:
    response = deprecation_client.post(
        "/retrieve-filtered?min_score=0.5", json={"query": "test query"}
    )
    assert response.status_code == 200
    assert response.headers.get("sunset") == "Sat, 31 Oct 2026 23:59:59 GMT"


def test_retrieve_filtered_returns_link_header(deprecation_client: TestClient) -> None:
    response = deprecation_client.post(
        "/retrieve-filtered?min_score=0.5", json={"query": "test query"}
    )
    assert response.status_code == 200
    assert "link" in response.headers
    assert "/ws/chat" in response.headers["link"]
    assert "successor-version" in response.headers["link"]


def test_retrieve_filtered_response_body_unchanged(deprecation_client: TestClient) -> None:
    """Deprecation headers must not change the response body or schema."""
    response = deprecation_client.post(
        "/retrieve-filtered?min_score=0.5", json={"query": "test query"}
    )
    assert response.status_code == 200
    body = response.json()
    assert "query" in body
    assert "results" in body
    assert "total_results" in body


# ---------------------------------------------------------------------------
# OpenAPI schema — deprecated: true
# ---------------------------------------------------------------------------

def test_openapi_marks_retrieve_as_deprecated(deprecation_client: TestClient) -> None:
    schema = deprecation_client.get("/openapi.json").json()
    retrieve_op = schema["paths"]["/retrieve"]["post"]
    assert retrieve_op.get("deprecated") is True


def test_openapi_marks_retrieve_filtered_as_deprecated(deprecation_client: TestClient) -> None:
    schema = deprecation_client.get("/openapi.json").json()
    retrieve_filtered_op = schema["paths"]["/retrieve-filtered"]["post"]
    assert retrieve_filtered_op.get("deprecated") is True
