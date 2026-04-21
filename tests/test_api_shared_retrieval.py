"""Tests for shared retrieval facade usage across REST and WebSocket handlers."""

from typing import Any, Dict, List, Optional

import pytest
from fastapi import WebSocketDisconnect

import api
from hybrid_rag import HybridRetrieverConfig
from hybrid_rag.cache import InMemoryCache


class GuardConfig:
    """Config object that rejects request-time enable_rerank mutation."""

    def __init__(self, enable_rerank: bool = True) -> None:
        self.__dict__["enable_rerank"] = enable_rerank

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "enable_rerank" and "enable_rerank" in self.__dict__:
            raise AssertionError("request-time mutation of global config is not allowed")
        self.__dict__[name] = value


class FakeWebSocket:
    """Minimal websocket double for endpoint testing without network I/O."""

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


class FakeCollection:
    """Minimal collection double used for corpus-version-aware cache keys."""

    def __init__(self, count_value: int = 1) -> None:
        self._count_value = count_value
        self.add_calls = 0

    def count(self) -> int:
        return self._count_value

    def add(
        self,
        ids: List[str],
        documents: List[str],
        metadatas: List[Dict[str, Any]],
    ) -> None:
        self.add_calls += 1
        self._count_value += len(ids)


class FakeRetriever:
    """Retriever double with observable calls and stable result payload."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []
        self.collection = FakeCollection()

    def retrieve(self, query: str, enable_rerank: Optional[bool] = None) -> List[Dict[str, Any]]:
        self.calls.append({"query": query, "enable_rerank": enable_rerank})
        effective_rerank = True if enable_rerank is None else enable_rerank
        return [
            {
                "id": f"doc-{query}",
                "text": f"result for {query}",
                "metadata": {"source": "fake-source"},
                "score": 0.97 if effective_rerank else 0.93,
            }
        ]


@pytest.fixture
def parity_harness(monkeypatch: pytest.MonkeyPatch) -> FakeRetriever:
    """Prepare isolated retriever/config/cache globals for parity contract tests."""

    retriever = FakeRetriever()
    config = HybridRetrieverConfig(
        semantic_weight=0.7,
        keyword_weight=0.3,
        enable_rerank=True,
    )

    monkeypatch.setattr(api, "_retriever", retriever)
    monkeypatch.setattr(api, "_config", config)
    monkeypatch.setattr(api, "_cache", InMemoryCache(ttl_seconds=3600, max_size=100))

    return retriever


def _assert_ws_results_message(ws: FakeWebSocket) -> Dict[str, Any]:
    """Return the first results message from sent websocket payloads."""
    for payload in ws.sent_messages:
        if payload.get("type") == "results":
            return payload
    raise AssertionError("results message not sent")


@pytest.mark.asyncio
async def test_retrieve_uses_shared_facade_with_request_local_rerank(monkeypatch: pytest.MonkeyPatch) -> None:
    """REST /retrieve uses shared facade and does not mutate global config."""

    observed: Dict[str, Any] = {}

    def fake_shared_retrieve_documents(query: str, enable_rerank: Optional[bool] = None) -> List[Dict[str, Any]]:
        observed["query"] = query
        observed["enable_rerank"] = enable_rerank
        return [
            {
                "id": "doc-1",
                "text": "hello",
                "metadata": {"source": "unit"},
                "score": 0.91,
            }
        ]

    monkeypatch.setattr(api, "_retriever", object())
    monkeypatch.setattr(api, "_config", GuardConfig(enable_rerank=True))
    monkeypatch.setattr(api, "_shared_retrieve_documents", fake_shared_retrieve_documents)

    response = await api.retrieve(api.RetrievalRequest(query="hello", enable_rerank=False))

    assert observed["query"] == "hello"
    assert observed["enable_rerank"] is False
    assert response.total_results == 1
    assert response.results[0].id == "doc-1"


@pytest.mark.asyncio
async def test_websocket_uses_shared_facade_and_preserves_message_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    """WS /ws/chat uses shared facade and keeps status/results message contract."""

    observed: Dict[str, Any] = {}

    def fake_shared_retrieve_documents(query: str, enable_rerank: Optional[bool] = None) -> List[Dict[str, Any]]:
        observed["query"] = query
        observed["enable_rerank"] = enable_rerank
        return [
            {
                "id": "doc-2",
                "text": "from ws",
                "metadata": {"source": "ws-test"},
                "score": 0.95,
            }
        ]

    monkeypatch.setattr(api, "_retriever", object())
    monkeypatch.setattr(api, "_config", GuardConfig(enable_rerank=True))
    monkeypatch.setattr(api, "_shared_retrieve_documents", fake_shared_retrieve_documents)

    fake_websocket = FakeWebSocket(
        incoming_messages=[{"query": "from websocket", "enable_rerank": False}]
    )

    await api.websocket_chat(fake_websocket)

    assert fake_websocket.accepted is True
    assert observed["query"] == "from websocket"
    assert observed["enable_rerank"] is False
    assert len(fake_websocket.sent_messages) >= 2

    status_message = fake_websocket.sent_messages[0]
    results_message = fake_websocket.sent_messages[1]

    assert status_message["type"] == "status"
    assert results_message["type"] == "results"
    assert results_message["query"] == "from websocket"
    assert results_message["total_results"] == 1


@pytest.mark.asyncio
async def test_parity_repeated_equivalent_query_rest_then_ws_hits_shared_cache(
    parity_harness: FakeRetriever,
) -> None:
    """Equivalent REST/WS queries share cache behavior under the approved policy."""

    rest_response = await api.retrieve(
        api.RetrievalRequest(query="cache parity query", enable_rerank=False)
    )

    ws = FakeWebSocket(
        incoming_messages=[{"query": "cache parity query", "enable_rerank": False}]
    )
    await api.websocket_chat(ws)
    ws_results = _assert_ws_results_message(ws)

    assert len(parity_harness.calls) == 1
    assert ws_results["total_results"] == rest_response.total_results
    assert ws_results["results"][0]["id"] == rest_response.results[0].id
    assert ws_results["results"][0]["source"] == rest_response.results[0].source
    assert ws_results["results"][0]["score"] == rest_response.results[0].score


@pytest.mark.asyncio
async def test_parity_config_update_invalidates_shared_cache_for_rest_and_ws(
    parity_harness: FakeRetriever,
) -> None:
    """Successful config updates invalidate shared retrieval cache across both transports."""

    await api.retrieve(api.RetrievalRequest(query="cfg parity", enable_rerank=False))
    assert len(parity_harness.calls) == 1

    await api.update_config(
        api.ConfigUpdateRequest(semantic_weight=0.6, keyword_weight=0.4)
    )

    ws = FakeWebSocket(incoming_messages=[{"query": "cfg parity", "enable_rerank": False}])
    await api.websocket_chat(ws)
    assert len(parity_harness.calls) == 2

    await api.retrieve(api.RetrievalRequest(query="cfg parity", enable_rerank=False))
    assert len(parity_harness.calls) == 2


@pytest.mark.asyncio
async def test_parity_ingest_add_preserves_cache_and_update_invalidates(
    parity_harness: FakeRetriever,
) -> None:
    """ingest_type add preserves cache; update invalidates it for subsequent equivalent queries."""

    await api.retrieve(api.RetrievalRequest(query="ingest parity", enable_rerank=False))
    assert len(parity_harness.calls) == 1

    add_response = await api.add_documents(
        api.DocumentIngestionRequest(
            source_type="text",
            content="new document content",
            source_label="parity-add",
            ingest_type="add",
        )
    )
    assert add_response.status == "success"

    ws_after_add = FakeWebSocket(
        incoming_messages=[{"query": "ingest parity", "enable_rerank": False}]
    )
    await api.websocket_chat(ws_after_add)
    assert len(parity_harness.calls) == 1

    update_response = await api.add_documents(
        api.DocumentIngestionRequest(
            source_type="text",
            content="replacement content",
            source_label="parity-update",
            ingest_type="update",
        )
    )
    assert update_response.status == "success"

    ws_after_update = FakeWebSocket(
        incoming_messages=[{"query": "ingest parity", "enable_rerank": False}]
    )
    await api.websocket_chat(ws_after_update)
    assert len(parity_harness.calls) == 2


@pytest.mark.asyncio
async def test_rerank_override_isolation_no_global_config_bleed_under_mixed_calls(
    parity_harness: FakeRetriever,
) -> None:
    """Mixed REST/WS calls keep rerank override request-local without mutating global config."""

    await api.retrieve(api.RetrievalRequest(query="rerank isolation", enable_rerank=False))

    ws_default = FakeWebSocket(incoming_messages=[{"query": "rerank isolation"}])
    await api.websocket_chat(ws_default)

    # Repeat both variants to ensure cache identity separation and stable reuse.
    await api.retrieve(api.RetrievalRequest(query="rerank isolation", enable_rerank=False))
    ws_default_repeat = FakeWebSocket(incoming_messages=[{"query": "rerank isolation"}])
    await api.websocket_chat(ws_default_repeat)

    assert len(parity_harness.calls) == 2
    observed_rerank_values = {call["enable_rerank"] for call in parity_harness.calls}
    assert observed_rerank_values == {False, True}
    assert api._config is not None
    assert api._config.enable_rerank is True
