"""End-to-end style tests proving WS vs HTTP cache/middleware trade-offs (B1-B4).

These tests exercise the real FastAPI app routes for HTTP (/retrieve) and the real
WebSocket handler coroutine (websocket_chat) with an in-process websocket double.

Coverage:
- B1: Observability split (HTTP emits cache.http_*; WS emits cache.retrieval_*)
- B2: Score filtering parity between REST and WS paths
- B3 (T03 updated): REST X-Cache header and WS cache_status payload field are both present
- B4: REST MISS causes two cache writes (middleware key + shared-retrieve key)
- C1 (T03 RSK-002): WS cache HIT — payload field and log event both signal HIT
- C2 (T03 RSK-002): WS cache MISS — payload field and log event both signal MISS
- C3 (T03 RSK-002): WS cache invalidation — post-invalidation WS query shows MISS
"""

from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

import api
from hybrid_rag import HybridRetrieverConfig
from hybrid_rag.cache import CacheBackend, InMemoryCache


class DeterministicRetriever:
    """Retriever double with deterministic outputs and call tracking."""

    def __init__(self, results: Optional[List[Dict[str, Any]]] = None) -> None:
        self.calls: List[Dict[str, Any]] = []
        self.collection = SimpleNamespace(count=lambda: 1)
        self._results = results or [
            {
                "id": "doc-1",
                "text": "deterministic result",
                "metadata": {"source": "test-source"},
                "score": 0.92,
            }
        ]

    def retrieve(self, query: str, enable_rerank: Optional[bool] = None) -> List[Dict[str, Any]]:
        self.calls.append({"query": query, "enable_rerank": enable_rerank})
        return list(self._results)


class FakeWebSocket:
    """Minimal websocket double for driving api.websocket_chat()."""

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


class CountingCache(CacheBackend):
    """Simple in-memory cache backend that records get/set keys."""

    def __init__(self) -> None:
        self._store: Dict[str, Any] = {}
        self.get_keys: List[str] = []
        self.set_keys: List[str] = []
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Optional[Any]:
        self.get_keys.append(key)
        if key in self._store:
            self._hits += 1
            return self._store[key]
        self._misses += 1
        return None

    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        self.set_keys.append(key)
        self._store[key] = value

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()

    def stats(self) -> Dict[str, Any]:
        return {
            "backend": "counting",
            "size": len(self._store),
            "hits": self._hits,
            "misses": self._misses,
        }


def _extract_ws_results_message(ws: FakeWebSocket) -> Dict[str, Any]:
    for payload in ws.sent_messages:
        if payload.get("type") == "results":
            return payload
    raise AssertionError(f"Expected a WS results message, got: {ws.sent_messages}")


@pytest.fixture
def ws_http_harness(monkeypatch: pytest.MonkeyPatch) -> DeterministicRetriever:
    """Install deterministic retriever/config/cache globals for transport tests."""

    retriever = DeterministicRetriever()
    monkeypatch.setattr(api, "_retriever", retriever)
    monkeypatch.setattr(
        api,
        "_config",
        HybridRetrieverConfig(
            semantic_weight=0.7,
            keyword_weight=0.3,
            enable_rerank=True,
        ),
    )
    monkeypatch.setattr(api, "_cache", InMemoryCache(ttl_seconds=3600, max_size=256))
    monkeypatch.setattr(api, "_cache_generation", 0)
    monkeypatch.setattr(api, "_corpus_version", "gen0.n1")

    return retriever


@pytest.mark.asyncio
async def test_b1_observability_split_http_vs_ws_events(
    ws_http_harness: DeterministicRetriever,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """B1: HTTP and WS emit different cache event namespaces by design."""

    client = TestClient(api.app)
    query = "b1-observability-split"

    # Warm once so second HTTP call is a middleware HIT.
    client.post("/retrieve", json={"query": query, "enable_rerank": False})

    caplog.clear()
    with caplog.at_level("INFO", logger="api"):
        client.post("/retrieve", json={"query": query, "enable_rerank": False})

    http_messages = [r.message for r in caplog.records]
    assert any("cache.http_hit" in msg for msg in http_messages)

    caplog.clear()
    ws = FakeWebSocket(
        incoming_messages=[{"query": "b1-ws-path", "enable_rerank": False}]
    )
    with caplog.at_level("INFO", logger="api"):
        await api.websocket_chat(ws)

    ws_messages = [r.message for r in caplog.records]
    assert any("cache.retrieval_miss" in msg for msg in ws_messages)
    assert not any("cache.http_hit" in msg or "cache.http_miss" in msg for msg in ws_messages)


@pytest.mark.asyncio
async def test_b2_rest_and_ws_apply_same_min_score_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    """B2: Prove current flow applies the same 0.80 filter in both REST and WS."""

    retriever = DeterministicRetriever(
        results=[
            {
                "id": "below-threshold",
                "text": "should be filtered",
                "metadata": {"source": "src-a"},
                "score": 0.79,
            },
            {
                "id": "above-threshold",
                "text": "should remain",
                "metadata": {"source": "src-b"},
                "score": 0.81,
            },
        ]
    )
    monkeypatch.setattr(api, "_retriever", retriever)
    monkeypatch.setattr(
        api,
        "_config",
        HybridRetrieverConfig(
            semantic_weight=0.7,
            keyword_weight=0.3,
            enable_rerank=True,
        ),
    )
    monkeypatch.setattr(api, "_cache", InMemoryCache(ttl_seconds=3600, max_size=256))
    monkeypatch.setattr(api, "_cache_generation", 0)
    monkeypatch.setattr(api, "_corpus_version", "gen0.n1")

    client = TestClient(api.app)

    rest_response = client.post(
        "/retrieve",
        json={"query": "b2-filter", "enable_rerank": False},
    )
    assert rest_response.status_code == 200, rest_response.text
    rest_body = rest_response.json()
    rest_ids = [item["id"] for item in rest_body["results"]]

    ws = FakeWebSocket(incoming_messages=[{"query": "b2-filter", "enable_rerank": False}])
    await api.websocket_chat(ws)
    ws_results = _extract_ws_results_message(ws)
    ws_ids = [item["id"] for item in ws_results["results"]]

    assert rest_ids == ["above-threshold"]
    assert ws_ids == ["above-threshold"]


@pytest.mark.asyncio
async def test_b3_http_and_ws_both_expose_cache_status_in_their_respective_contracts(
    ws_http_harness: DeterministicRetriever,
) -> None:
    """B3 (updated for T03): REST exposes X-Cache header; WS payload now carries cache_status field.

    T03 decision: payload-field contract.  WS clients receive ``cache_status``
    (HIT / MISS / ERROR) in the results message so they have the same cache
    visibility that REST clients get via the ``X-Cache`` response header.
    """

    client = TestClient(api.app)

    response = client.post(
        "/retrieve",
        json={"query": "b3-header-vs-ws", "enable_rerank": False},
    )
    assert response.status_code == 200
    assert response.headers.get("X-Cache") in {"MISS", "HIT", "ERROR"}

    ws = FakeWebSocket(
        incoming_messages=[{"query": "b3-header-vs-ws", "enable_rerank": False}]
    )
    await api.websocket_chat(ws)
    ws_results = _extract_ws_results_message(ws)

    # T03 contract: WS results message MUST carry cache_status
    assert "cache_status" in ws_results
    assert ws_results["cache_status"] in {"HIT", "MISS", "ERROR"}
    # Second call (same query, shared cache warm from REST call above) → HIT
    assert ws_results["cache_status"] == "HIT"


def test_b4_rest_miss_causes_two_cache_writes_middleware_plus_shared_facade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B4: First REST /retrieve miss writes two cache keys at different layers."""

    retriever = DeterministicRetriever()
    counting_cache = CountingCache()

    monkeypatch.setattr(api, "_retriever", retriever)
    monkeypatch.setattr(
        api,
        "_config",
        HybridRetrieverConfig(
            semantic_weight=0.7,
            keyword_weight=0.3,
            enable_rerank=True,
        ),
    )
    monkeypatch.setattr(api, "_cache", counting_cache)
    monkeypatch.setattr(api, "_cache_generation", 0)
    monkeypatch.setattr(api, "_corpus_version", "gen0.n1")

    client = TestClient(api.app)

    response = client.post(
        "/retrieve",
        json={"query": "b4-double-write", "enable_rerank": False},
    )
    assert response.status_code == 200, response.text

    # One write from _shared_retrieve_documents (shared-retrieve:*),
    # one write from QueryCacheMiddleware (cache:*).
    assert len(counting_cache.set_keys) >= 2, counting_cache.set_keys
    assert any(key.startswith("shared-retrieve:") for key in counting_cache.set_keys)
    assert any(key.startswith("cache:") for key in counting_cache.set_keys)


# ---------------------------------------------------------------------------
# T03 RSK-002: WS cache-status visibility tests (C1–C3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_c1_ws_cache_hit_reflected_in_payload_and_log(
    ws_http_harness: DeterministicRetriever,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """C1 (T03 RSK-002): WS results message shows HIT and log emits cache.retrieval_hit.

    Sequence: first WS query warms the shared retrieval cache; second identical
    WS query should report HIT in both the payload field and the structured log.
    """
    query = "c1-ws-cache-hit"

    # First query populates the shared retrieval cache (MISS).
    ws_first = FakeWebSocket(incoming_messages=[{"query": query, "enable_rerank": False}])
    await api.websocket_chat(ws_first)
    first_results = _extract_ws_results_message(ws_first)
    assert first_results["cache_status"] == "MISS"

    # Second identical query should be served from the shared retrieval cache (HIT).
    caplog.clear()
    ws_second = FakeWebSocket(incoming_messages=[{"query": query, "enable_rerank": False}])
    with caplog.at_level("INFO", logger="api"):
        await api.websocket_chat(ws_second)

    second_results = _extract_ws_results_message(ws_second)
    assert second_results["cache_status"] == "HIT"

    log_messages = [r.message for r in caplog.records]
    assert any("cache.retrieval_hit" in msg for msg in log_messages)


@pytest.mark.asyncio
async def test_c2_ws_cache_miss_reflected_in_payload_and_log(
    ws_http_harness: DeterministicRetriever,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """C2 (T03 RSK-002): WS results message shows MISS and log emits cache.retrieval_miss.

    A fresh query (never seen before) must report MISS in the payload and emit
    a structured ``cache.retrieval_miss`` log record.
    """
    query = "c2-ws-cache-miss-unique"

    caplog.clear()
    ws = FakeWebSocket(incoming_messages=[{"query": query, "enable_rerank": False}])
    with caplog.at_level("INFO", logger="api"):
        await api.websocket_chat(ws)

    ws_results = _extract_ws_results_message(ws)
    assert ws_results["cache_status"] == "MISS"

    log_messages = [r.message for r in caplog.records]
    assert any("cache.retrieval_miss" in msg for msg in log_messages)
    assert not any("cache.retrieval_hit" in msg for msg in log_messages)


@pytest.mark.asyncio
async def test_c3_ws_cache_invalidation_shows_miss_after_config_update(
    ws_http_harness: DeterministicRetriever,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """C3 (T03 RSK-002): After cache invalidation WS query reports MISS, not stale HIT.

    Sequence:
    1. Warm the cache via a first WS query (MISS → cache populated).
    2. Trigger invalidation via PUT /config (bumps corpus_version / cache generation).
    3. Re-run the same WS query — must report MISS because the old cache entry
       is no longer valid for the new corpus_version.

    This verifies that clients can observe invalidation events through the WS
    cache_status payload field without needing access to internal server state.
    """
    query = "c3-ws-invalidation-test"

    # Step 1: warm the cache.
    ws_warm = FakeWebSocket(incoming_messages=[{"query": query, "enable_rerank": False}])
    await api.websocket_chat(ws_warm)
    warm_results = _extract_ws_results_message(ws_warm)
    assert warm_results["cache_status"] == "MISS"

    # Step 2: invalidate by changing config (this bumps _cache_generation and
    # rebuilds _corpus_version, so existing shared-retrieve keys are stale).
    from fastapi.testclient import TestClient

    client = TestClient(api.app)
    config_response = client.put(
        "/config",
        json={"semantic_weight": 0.6, "keyword_weight": 0.4},
    )
    assert config_response.status_code == 200, config_response.text

    # Step 3: same query post-invalidation must be a MISS again.
    caplog.clear()
    ws_post = FakeWebSocket(incoming_messages=[{"query": query, "enable_rerank": False}])
    with caplog.at_level("INFO", logger="api"):
        await api.websocket_chat(ws_post)

    post_results = _extract_ws_results_message(ws_post)
    assert post_results["cache_status"] == "MISS", (
        "Expected MISS after cache invalidation, got HIT — "
        "cache_generation or corpus_version was not bumped correctly"
    )

    log_messages = [r.message for r in caplog.records]
    assert any("cache.retrieval_miss" in msg for msg in log_messages)

