"""T06 — WS-first retrieval critical path tests.

This module establishes the WS-first retrieval contract, replacing critical-path
assertions that were previously exercised only against HTTP retrieval routes.

Migration matrix
----------------
Each test maps to one or more legacy checks that it supersedes:

  New WS test                                      Legacy HTTP check superseded
  -----------------------------------------------  -------------------------------------------------------
  test_ws_filters_results_below_threshold          TestRestApi.test_retrieve_filters_below_threshold
  test_ws_total_results_reflects_post_filter_count TestRestApi.test_retrieve_result_count_reflects_filter
  test_ws_results_sorted_descending                TestRestApi.test_retrieve_results_sorted_descending
  test_ws_error_on_retrieval_failure               (new — no HTTP equivalent; T04 live-backend only)
  test_ws_error_on_retriever_not_initialized       (new — WS error-type contract; previously untested)
  test_ws_success_result_fields_populated          (new — field-level contract for WS results payload)
  test_ws_empty_results_on_all_below_threshold     (new — boundary condition for 100% filtered corpus)

All tests use the ``FakeWebSocket`` + ``api.websocket_chat`` pattern established
in ``test_ws_http_middleware_tradeoffs_e2e.py`` so they run offline (no live
backend required).

Dependencies satisfied (guard-rail check):
  T03 — WS cache-status payload field contract: implemented and tested
  T04 — /retrieve-filtered removed: implemented (no active tests reference it)
"""

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest
from fastapi import WebSocketDisconnect

import api
from hybrid_rag import HybridRetrieverConfig
from hybrid_rag.cache import InMemoryCache
from hybrid_rag.exceptions import RetrievalError


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class FakeWebSocket:
    """Minimal websocket double for driving api.websocket_chat() offline."""

    def __init__(self, incoming_messages: List[Dict[str, Any]]) -> None:
        self._incoming = list(incoming_messages)
        self.sent_messages: List[Dict[str, Any]] = []
        self.accepted = False

    async def accept(self) -> None:
        self.accepted = True

    async def receive_json(self) -> Dict[str, Any]:
        if self._incoming:
            return self._incoming.pop(0)
        raise WebSocketDisconnect()

    async def send_json(self, payload: Dict[str, Any]) -> None:
        self.sent_messages.append(payload)


class ErrorRetriever:
    """Retriever double that raises RetrievalError on every call."""

    def __init__(self) -> None:
        self.collection = MagicMock()
        self.collection.count.return_value = 1

    def retrieve(self, query: str, enable_rerank: Optional[bool] = None) -> List[Dict[str, Any]]:
        raise RetrievalError("simulated retrieval failure")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ws_harness(monkeypatch: pytest.MonkeyPatch) -> "DeterministicRetriever":
    """Install a deterministic retriever/config/cache for WS critical-path tests."""

    class DeterministicRetriever:
        def __init__(self, results: Optional[List[Dict[str, Any]]] = None) -> None:
            from types import SimpleNamespace

            self.collection = SimpleNamespace(count=lambda: 1)
            self._results = results or [
                {
                    "id": "doc-alpha",
                    "text": "relevant document",
                    "metadata": {"source": "test-src"},
                    "score": 0.92,
                }
            ]

        def retrieve(self, query: str, enable_rerank: Optional[bool] = None) -> List[Dict[str, Any]]:
            return list(self._results)

    retriever = DeterministicRetriever()
    monkeypatch.setattr(api, "_retriever", retriever)
    monkeypatch.setattr(
        api,
        "_config",
        HybridRetrieverConfig(semantic_weight=0.7, keyword_weight=0.3, enable_rerank=True),
    )
    monkeypatch.setattr(api, "_cache", InMemoryCache(ttl_seconds=3600, max_size=256))
    monkeypatch.setattr(api, "_cache_generation", 0)
    monkeypatch.setattr(api, "_corpus_version", "gen0.n1")
    return retriever


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_results_message(ws: FakeWebSocket) -> Dict[str, Any]:
    for msg in ws.sent_messages:
        if msg.get("type") == "results":
            return msg
    raise AssertionError(f"No results message found in: {ws.sent_messages}")


def _get_error_message(ws: FakeWebSocket) -> Dict[str, Any]:
    for msg in ws.sent_messages:
        if msg.get("type") == "error":
            return msg
    raise AssertionError(f"No error message found in: {ws.sent_messages}")


# ---------------------------------------------------------------------------
# T06 WS critical-path tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ws_filters_results_below_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    """WS path discards results with score < 0.80 and returns only results at or above the floor.

    Supersedes: TestRestApi.test_retrieve_filters_below_threshold
    (live-backend HTTP test in test_retrieval_filtering.py)
    """
    from types import SimpleNamespace

    class MixedScoreRetriever:
        def __init__(self) -> None:
            self.collection = SimpleNamespace(count=lambda: 1)

        def retrieve(self, query: str, enable_rerank: Optional[bool] = None) -> List[Dict[str, Any]]:
            return [
                {"id": "pass-high", "text": "doc1", "metadata": {"source": "s1"}, "score": 0.95},
                {"id": "fail-low", "text": "doc2", "metadata": {"source": "s2"}, "score": 0.79},
                {"id": "pass-boundary", "text": "doc3", "metadata": {"source": "s3"}, "score": 0.80},
                {"id": "fail-very-low", "text": "doc4", "metadata": {"source": "s4"}, "score": 0.40},
            ]

    monkeypatch.setattr(api, "_retriever", MixedScoreRetriever())
    monkeypatch.setattr(
        api, "_config",
        HybridRetrieverConfig(semantic_weight=0.7, keyword_weight=0.3, enable_rerank=True),
    )
    monkeypatch.setattr(api, "_cache", InMemoryCache(ttl_seconds=3600, max_size=256))
    monkeypatch.setattr(api, "_cache_generation", 0)
    monkeypatch.setattr(api, "_corpus_version", "gen0.n1")

    ws = FakeWebSocket(incoming_messages=[{"query": "threshold filter test", "enable_rerank": False}])
    await api.websocket_chat(ws)

    results_msg = _get_results_message(ws)
    returned_ids = [r["id"] for r in results_msg["results"]]

    assert "pass-high" in returned_ids
    assert "pass-boundary" in returned_ids
    assert "fail-low" not in returned_ids, "score 0.79 must be filtered"
    assert "fail-very-low" not in returned_ids, "score 0.40 must be filtered"
    assert all(r["score"] >= 0.80 for r in results_msg["results"])


@pytest.mark.asyncio
async def test_ws_total_results_reflects_post_filter_count(monkeypatch: pytest.MonkeyPatch) -> None:
    """WS total_results equals the length of the filtered results list.

    Supersedes: TestRestApi.test_retrieve_result_count_reflects_filter
    (live-backend HTTP test in test_retrieval_filtering.py)
    """
    from types import SimpleNamespace

    class PartialPassRetriever:
        def __init__(self) -> None:
            self.collection = SimpleNamespace(count=lambda: 1)

        def retrieve(self, query: str, enable_rerank: Optional[bool] = None) -> List[Dict[str, Any]]:
            return [
                {"id": "d1", "text": "t1", "metadata": {"source": "s"}, "score": 0.91},
                {"id": "d2", "text": "t2", "metadata": {"source": "s"}, "score": 0.50},
                {"id": "d3", "text": "t3", "metadata": {"source": "s"}, "score": 0.82},
            ]

    monkeypatch.setattr(api, "_retriever", PartialPassRetriever())
    monkeypatch.setattr(
        api, "_config",
        HybridRetrieverConfig(semantic_weight=0.7, keyword_weight=0.3, enable_rerank=True),
    )
    monkeypatch.setattr(api, "_cache", InMemoryCache(ttl_seconds=3600, max_size=256))
    monkeypatch.setattr(api, "_cache_generation", 0)
    monkeypatch.setattr(api, "_corpus_version", "gen0.n1")

    ws = FakeWebSocket(incoming_messages=[{"query": "count accuracy test", "enable_rerank": False}])
    await api.websocket_chat(ws)

    results_msg = _get_results_message(ws)
    assert results_msg["total_results"] == len(results_msg["results"]), (
        f"total_results ({results_msg['total_results']}) must equal "
        f"len(results) ({len(results_msg['results'])})"
    )
    assert results_msg["total_results"] == 2


@pytest.mark.asyncio
async def test_ws_results_sorted_descending(monkeypatch: pytest.MonkeyPatch) -> None:
    """WS results remain in descending score order when the retriever returns sorted output.

    The WS handler (via ``_to_filtered_document_results``) preserves the order returned by
    the retriever and only filters out below-threshold docs.  Real retrievers return
    results sorted by score descending; this test verifies that filtering does not break
    that order.

    Supersedes: TestRestApi.test_retrieve_results_sorted_descending
    (live-backend HTTP test in test_retrieval_filtering.py)
    """
    from types import SimpleNamespace

    class PreSortedRetriever:
        """Returns results pre-sorted descending (as a real hybrid retriever does)."""

        def __init__(self) -> None:
            self.collection = SimpleNamespace(count=lambda: 1)

        def retrieve(self, query: str, enable_rerank: Optional[bool] = None) -> List[Dict[str, Any]]:
            return [
                {"id": "highest", "text": "t", "metadata": {"source": "s"}, "score": 0.97},
                {"id": "mid", "text": "t", "metadata": {"source": "s"}, "score": 0.88},
                {"id": "low-filtered", "text": "t", "metadata": {"source": "s"}, "score": 0.50},
                {"id": "low-pass", "text": "t", "metadata": {"source": "s"}, "score": 0.81},
            ]

    monkeypatch.setattr(api, "_retriever", PreSortedRetriever())
    monkeypatch.setattr(
        api, "_config",
        HybridRetrieverConfig(semantic_weight=0.7, keyword_weight=0.3, enable_rerank=True),
    )
    monkeypatch.setattr(api, "_cache", InMemoryCache(ttl_seconds=3600, max_size=256))
    monkeypatch.setattr(api, "_cache_generation", 0)
    monkeypatch.setattr(api, "_corpus_version", "gen0.n1")

    ws = FakeWebSocket(incoming_messages=[{"query": "sort order test", "enable_rerank": False}])
    await api.websocket_chat(ws)

    results_msg = _get_results_message(ws)
    scores = [r["score"] for r in results_msg["results"]]
    assert scores == sorted(scores, reverse=True), (
        f"Results must be sorted in descending score order, got: {scores}"
    )
    assert "low-filtered" not in [r["id"] for r in results_msg["results"]]


@pytest.mark.asyncio
async def test_ws_error_on_retrieval_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """WS sends an error-type message when the retriever raises RetrievalError."""
    monkeypatch.setattr(api, "_retriever", ErrorRetriever())
    monkeypatch.setattr(
        api, "_config",
        HybridRetrieverConfig(semantic_weight=0.7, keyword_weight=0.3, enable_rerank=True),
    )
    monkeypatch.setattr(api, "_cache", InMemoryCache(ttl_seconds=3600, max_size=256))
    monkeypatch.setattr(api, "_cache_generation", 0)
    monkeypatch.setattr(api, "_corpus_version", "gen0.n1")

    ws = FakeWebSocket(incoming_messages=[{"query": "error case", "enable_rerank": False}])
    await api.websocket_chat(ws)

    error_msg = _get_error_message(ws)
    assert error_msg["type"] == "error"
    assert "message" in error_msg
    assert error_msg["message"], "Error message must not be empty"


@pytest.mark.asyncio
async def test_ws_error_on_retriever_not_initialized(monkeypatch: pytest.MonkeyPatch) -> None:
    """WS sends an error-type message when the retriever has not been initialized."""
    monkeypatch.setattr(api, "_retriever", None)
    monkeypatch.setattr(api, "_config", None)

    ws = FakeWebSocket(incoming_messages=[{"query": "uninitialized test"}])
    await api.websocket_chat(ws)

    error_msg = _get_error_message(ws)
    assert error_msg["type"] == "error"
    assert "message" in error_msg


@pytest.mark.asyncio
async def test_ws_success_result_fields_populated(ws_harness: Any) -> None:
    """Every result in a successful WS response carries id, text, source, and score."""
    ws = FakeWebSocket(incoming_messages=[{"query": "field structure test", "enable_rerank": False}])
    await api.websocket_chat(ws)

    results_msg = _get_results_message(ws)
    assert results_msg["type"] == "results"
    assert "query" in results_msg
    assert "total_results" in results_msg
    assert isinstance(results_msg["results"], list)

    for result in results_msg["results"]:
        assert "id" in result, f"id missing from result: {result}"
        assert "text" in result, f"text missing from result: {result}"
        assert "source" in result, f"source missing from result: {result}"
        assert "score" in result, f"score missing from result: {result}"


@pytest.mark.asyncio
async def test_ws_empty_results_on_all_below_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    """WS returns an empty results list (not an error) when all scores are below 0.80."""
    from types import SimpleNamespace

    class AllFilteredRetriever:
        def __init__(self) -> None:
            self.collection = SimpleNamespace(count=lambda: 1)

        def retrieve(self, query: str, enable_rerank: Optional[bool] = None) -> List[Dict[str, Any]]:
            return [
                {"id": "x1", "text": "t", "metadata": {"source": "s"}, "score": 0.79},
                {"id": "x2", "text": "t", "metadata": {"source": "s"}, "score": 0.50},
                {"id": "x3", "text": "t", "metadata": {"source": "s"}, "score": 0.20},
            ]

    monkeypatch.setattr(api, "_retriever", AllFilteredRetriever())
    monkeypatch.setattr(
        api, "_config",
        HybridRetrieverConfig(semantic_weight=0.7, keyword_weight=0.3, enable_rerank=True),
    )
    monkeypatch.setattr(api, "_cache", InMemoryCache(ttl_seconds=3600, max_size=256))
    monkeypatch.setattr(api, "_cache_generation", 0)
    monkeypatch.setattr(api, "_corpus_version", "gen0.n1")

    ws = FakeWebSocket(incoming_messages=[{"query": "all filtered", "enable_rerank": False}])
    await api.websocket_chat(ws)

    results_msg = _get_results_message(ws)
    assert results_msg["type"] == "results"
    assert results_msg["total_results"] == 0
    assert results_msg["results"] == []

