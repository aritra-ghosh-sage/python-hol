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
        from types import SimpleNamespace
        self.collection = SimpleNamespace(count=lambda: 1)

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

def test_retrieve_endpoint_removed_from_openapi(deprecation_client: TestClient) -> None:
    """POST /retrieve must NOT appear in the OpenAPI schema after T08 retirement.
    
    WHY: The endpoint has been permanently removed. If it reappears in the schema,
    it means the route was accidentally re-registered.
    """
    schema = deprecation_client.get("/openapi.json").json()
    paths = schema.get("paths", {})
    assert "/retrieve" not in paths, (
        f"POST /retrieve must not appear in OpenAPI after T08 retirement; "
        f"found paths: {list(paths.keys())}"
    )


def test_retrieve_returns_404_after_removal(deprecation_client: TestClient) -> None:
    """POST /retrieve must return 404 after T08 endpoint retirement.
    
    WHY: Confirms the route no longer exists at runtime.
    """
    response = deprecation_client.post("/retrieve", json={"query": "test query"})
    assert response.status_code == 404, (
        f"Expected 404 (endpoint removed), got {response.status_code}"
    )
