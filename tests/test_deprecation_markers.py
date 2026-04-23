"""Tests for deprecation markers on POST /retrieve (internal endpoint).

Verifies that:
1. The OpenAPI schema marks the endpoint with deprecated: true.
2. Runtime behaviour (response body / status code) is unchanged.
"""

from typing import Any, Dict, List, Optional

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
        self._count = 1

    @property
    def collection(self):
        from types import SimpleNamespace
        return SimpleNamespace(count=lambda: self._count)

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
# POST /retrieve — response body and OpenAPI schema
# ---------------------------------------------------------------------------

def test_retrieve_response_body_shape(deprecation_client: TestClient) -> None:
    """Response body must contain the expected top-level keys."""
    response = deprecation_client.post("/retrieve", json={"query": "test query"})
    assert response.status_code == 200
    body = response.json()
    assert "query" in body
    assert "results" in body
    assert "total_results" in body


def test_openapi_marks_retrieve_as_deprecated(deprecation_client: TestClient) -> None:
    schema = deprecation_client.get("/openapi.json").json()
    retrieve_op = schema["paths"]["/retrieve"]["post"]
    assert retrieve_op.get("deprecated") is True
