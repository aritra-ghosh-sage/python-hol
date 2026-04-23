"""Tests for shared retrieval facade usage across REST and WebSocket handlers."""

from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest
from fastapi import WebSocketDisconnect

import api
from hybrid_rag import HybridRetrieverConfig
from hybrid_rag.cache import InMemoryCache


def _fake_http_request(headers: Optional[Dict[str, str]] = None) -> Any:
    """Return a minimal HTTP-request stub for tests that call api.retrieve() directly.

    The retrieve handler now accepts an ``http_request: Request`` argument to
    extract the X-Request-ID header for correlation-aware cache logging (OPTB-012).
    Tests that call the handler as a plain coroutine need to supply a stub that
    satisfies ``request.headers.get(...)`` and ``request.state``.

    ``state`` is a ``SimpleNamespace`` (no pre-existing attributes) rather than
    a MagicMock so that ``getattr(stub.state, "correlation_id", None)`` returns
    ``None`` instead of a truthy MagicMock instance.  This ensures the handler
    follows the correct fallback path (header → UUID) in unit tests.

    Args:
        headers: Optional dict of headers to expose on the stub.

    Returns:
        A stub whose ``.headers.get(...)`` returns values from *headers* and
        whose ``.state`` starts as an empty ``SimpleNamespace``.
    """
    stub = MagicMock()
    stub.headers = MagicMock()
    stub.headers.get = (headers or {}).get
    # Use SimpleNamespace so attribute access on .state behaves like a plain
    # object: missing attributes raise AttributeError (caught by getattr default),
    # and assignments persist within the stub for the duration of the test.
    stub.state = SimpleNamespace()
    return stub


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
    """Prepare isolated retriever/config/cache globals for parity contract tests.

    Also resets _corpus_version to the token that _build_corpus_version_token() would
    produce for this FakeRetriever: _cache_generation=0 and FakeCollection.count()=1
    → "gen0.n1".  This mirrors the authoritative token so that all parity tests start
    from a known, stable cache-key namespace.
    """

    retriever = FakeRetriever()
    config = HybridRetrieverConfig(
        semantic_weight=0.7,
        keyword_weight=0.3,
        enable_rerank=True,
    )

    monkeypatch.setattr(api, "_retriever", retriever)
    monkeypatch.setattr(api, "_config", config)
    monkeypatch.setattr(api, "_cache", InMemoryCache(ttl_seconds=3600, max_size=100))
    monkeypatch.setattr(api, "_cache_generation", 0)
    # Reset corpus_version to the token matching generation=0 and collection count=1.
    # FakeCollection starts with count_value=1, so the authoritative token is "gen0.n1".
    monkeypatch.setattr(api, "_corpus_version", "gen0.n1")

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

    def fake_shared_retrieve_documents(
        query: str,
        enable_rerank: Optional[bool] = None,
        correlation_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
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

    response = await api.retrieve(api.RetrievalRequest(query="hello", enable_rerank=False), _fake_http_request(), MagicMock())

    assert observed["query"] == "hello"
    assert observed["enable_rerank"] is False
    assert response.total_results == 1
    assert response.results[0].id == "doc-1"


@pytest.mark.asyncio
async def test_websocket_uses_shared_facade_and_preserves_message_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    """WS /ws/chat uses shared facade and keeps status/results message contract."""

    observed: Dict[str, Any] = {}

    def fake_shared_retrieve_documents(
        query: str,
        enable_rerank: Optional[bool] = None,
        correlation_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
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
        api.RetrievalRequest(query="cache parity query", enable_rerank=False),
        _fake_http_request(),
        MagicMock(),
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

    await api.retrieve(api.RetrievalRequest(query="cfg parity", enable_rerank=False), _fake_http_request(), MagicMock())
    assert len(parity_harness.calls) == 1

    await api.update_config(
        api.ConfigUpdateRequest(semantic_weight=0.6, keyword_weight=0.4)
    )

    ws = FakeWebSocket(incoming_messages=[{"query": "cfg parity", "enable_rerank": False}])
    await api.websocket_chat(ws)
    assert len(parity_harness.calls) == 2

    await api.retrieve(api.RetrievalRequest(query="cfg parity", enable_rerank=False), _fake_http_request(), MagicMock())
    assert len(parity_harness.calls) == 2


@pytest.mark.asyncio
async def test_parity_ingest_add_bumps_version_and_update_also_invalidates(
    parity_harness: FakeRetriever,
) -> None:
    """ingest_type add bumps corpus_version (cache miss); update clears cache and bumps again.

    WHY: When 'add' ingests new documents, the collection count changes which means
    _build_corpus_version_token() returns a new token.  Subsequent queries built
    against the new token will be cache misses — ensuring freshly-ingested documents
    are visible.  'update' additionally clears the L1 cache, giving the same guarantee
    with even stronger consistency.

    Expected retriever call counts:
      1 — initial query (cold miss)
      2 — query after 'add' (corpus_version changed → new cache key → miss)
      3 — query after 'update' (corpus_version changed again + cache cleared → miss)
    """

    await api.retrieve(api.RetrievalRequest(query="ingest parity", enable_rerank=False), _fake_http_request(), MagicMock())
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

    # After 'add' the corpus_version token has changed (collection count grew).
    # The same query must hit a different cache key → retriever called again.
    # Verify the token has the expected "gen{N}.n{count}" format.
    version_after_add = api._corpus_version
    assert version_after_add.startswith("gen"), (
        f"corpus_version after add should start with 'gen', got: {version_after_add!r}"
    )
    assert ".n" in version_after_add, (
        f"corpus_version after add should contain '.n', got: {version_after_add!r}"
    )

    ws_after_add = FakeWebSocket(
        incoming_messages=[{"query": "ingest parity", "enable_rerank": False}]
    )
    await api.websocket_chat(ws_after_add)
    assert len(parity_harness.calls) == 2

    update_response = await api.add_documents(
        api.DocumentIngestionRequest(
            source_type="text",
            content="replacement content",
            source_label="parity-update",
            ingest_type="update",
        )
    )
    assert update_response.status == "success"

    # After 'update' the corpus_version token changed again and cache was cleared.
    # The generation counter should have incremented, so the token differs from post-add.
    version_after_update = api._corpus_version
    assert version_after_update != version_after_add, (
        f"corpus_version must change after 'update', was {version_after_add!r} → {version_after_update!r}"
    )

    ws_after_update = FakeWebSocket(
        incoming_messages=[{"query": "ingest parity", "enable_rerank": False}]
    )
    await api.websocket_chat(ws_after_update)
    assert len(parity_harness.calls) == 3


@pytest.mark.asyncio
async def test_rerank_override_isolation_no_global_config_bleed_under_mixed_calls(
    parity_harness: FakeRetriever,
) -> None:
    """Mixed REST/WS calls keep rerank override request-local without mutating global config."""

    await api.retrieve(api.RetrievalRequest(query="rerank isolation", enable_rerank=False), _fake_http_request(), MagicMock())

    ws_default = FakeWebSocket(incoming_messages=[{"query": "rerank isolation"}])
    await api.websocket_chat(ws_default)

    # Repeat both variants to ensure cache identity separation and stable reuse.
    await api.retrieve(api.RetrievalRequest(query="rerank isolation", enable_rerank=False), _fake_http_request(), MagicMock())
    ws_default_repeat = FakeWebSocket(incoming_messages=[{"query": "rerank isolation"}])
    await api.websocket_chat(ws_default_repeat)

    assert len(parity_harness.calls) == 2
    observed_rerank_values = {call["enable_rerank"] for call in parity_harness.calls}
    assert observed_rerank_values == {False, True}
    assert api._config is not None
    assert api._config.enable_rerank is True


# ---------------------------------------------------------------------------
# New OPTB-007 parity tests — corpus_version-aware transport symmetry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parity_corpus_version_bumps_on_add_both_transports_see_miss(
    parity_harness: FakeRetriever,
) -> None:
    """Both REST and WS observe a cache miss after an 'add' ingest bumps corpus_version.

    WHY: _build_corpus_version_token() incorporates the live collection count.
    When 'add' inserts documents the count grows, producing a new version token.
    Any transport querying after the bump uses a different cache key → guaranteed miss,
    so freshly-added documents are reachable.  Once one transport populates the new
    key the other transport reuses it (shared cache → hit).

    Scenario:
      1. REST query (corpus_version="gen0.n1") → miss, calls=1
      2. 'add' ingest  → collection count 1→2, corpus_version→"gen0.n2"
      3. WS   same query (corpus_version="gen0.n2") → miss, calls=2
      4. REST same query (corpus_version="gen0.n2") → HIT  (WS populated it), calls=2
    """
    # Step 1: initial REST query populates cache with corpus_version "gen0.n1"
    rest_response_before = await api.retrieve(
        api.RetrievalRequest(query="version bump add parity", enable_rerank=False),
        _fake_http_request(),
        MagicMock(),
    )
    assert len(parity_harness.calls) == 1

    # Step 2: 'add' ingest — collection count grows → corpus_version token changes
    add_response = await api.add_documents(
        api.DocumentIngestionRequest(
            source_type="text",
            content="brand new document for add test",
            source_label="optb007-add",
            ingest_type="add",
        )
    )
    assert add_response.status == "success"

    # Step 3: WS query with new corpus_version → cache MISS (new key)
    ws_after_add = FakeWebSocket(
        incoming_messages=[{"query": "version bump add parity", "enable_rerank": False}]
    )
    await api.websocket_chat(ws_after_add)
    assert len(parity_harness.calls) == 2  # miss — new corpus_version key

    ws_results = _assert_ws_results_message(ws_after_add)

    # Step 4: REST with same corpus_version → HIT from cache WS just populated
    rest_response_after = await api.retrieve(
        api.RetrievalRequest(query="version bump add parity", enable_rerank=False),
        _fake_http_request(),
        MagicMock(),
    )
    assert len(parity_harness.calls) == 2  # HIT — same corpus_version key

    # Both transports return equivalent payloads from the shared cache entry
    assert rest_response_after.total_results == ws_results["total_results"]


@pytest.mark.asyncio
async def test_parity_corpus_version_bumps_on_update_both_transports_see_miss(
    parity_harness: FakeRetriever,
) -> None:
    """Both REST and WS observe a cache miss after an 'update' ingest bumps corpus_version.

    WHY: 'update' increments _cache_generation AND clears the L1 cache, then
    _build_corpus_version_token() produces a new token (gen incremented, count grown).
    The first transport to query after the update is always a miss; the second transport
    reuses the freshly-populated entry (shared-cache hit).

    Scenario:
      1. REST query                     → miss, calls=1
      2. 'update' ingest                → corpus_version changes, cache cleared
      3. WS   same query (new version)  → miss, calls=2
      4. REST same query (new version)  → HIT, calls=2
    """
    # Step 1: warm the cache under the initial corpus_version
    await api.retrieve(
        api.RetrievalRequest(query="version bump update parity", enable_rerank=False),
        _fake_http_request(),
        MagicMock(),
    )
    assert len(parity_harness.calls) == 1

    # Step 2: 'update' ingest — generation bumped, cache cleared, version token changed
    update_response = await api.add_documents(
        api.DocumentIngestionRequest(
            source_type="text",
            content="replacement document for update test",
            source_label="optb007-update",
            ingest_type="update",
        )
    )
    assert update_response.status == "success"

    # Step 3: WS query under new corpus_version → cache MISS
    ws_after_update = FakeWebSocket(
        incoming_messages=[{"query": "version bump update parity", "enable_rerank": False}]
    )
    await api.websocket_chat(ws_after_update)
    assert len(parity_harness.calls) == 2  # miss — new corpus_version key

    ws_results = _assert_ws_results_message(ws_after_update)

    # Step 4: REST under the same new corpus_version → HIT from what WS just stored
    rest_response_after = await api.retrieve(
        api.RetrievalRequest(query="version bump update parity", enable_rerank=False),
        _fake_http_request(),
        MagicMock(),
    )
    assert len(parity_harness.calls) == 2  # HIT — shared key with WS entry

    assert rest_response_after.total_results == ws_results["total_results"]


@pytest.mark.asyncio
async def test_parity_ws_first_rest_second_shares_same_corpus_version_key(
    parity_harness: FakeRetriever,
) -> None:
    """WS and REST share the same cache key under the same corpus_version.

    WHY: Both transports call _shared_retrieve_documents which computes the cache key
    using the module-level _corpus_version token.  Because that token is shared state,
    both transports produce the same key for the same (query, rerank, config) tuple.
    A WS query should populate the cache such that a subsequent identical REST query
    is a hit — and vice versa.

    Scenario:
      WS   query → miss, retriever called once (calls=1)
      REST same query → HIT (WS populated it), calls still 1
    """
    # Step 1: WS query goes in first — cold miss populates shared cache
    ws = FakeWebSocket(
        incoming_messages=[{"query": "ws rest share key", "enable_rerank": False}]
    )
    await api.websocket_chat(ws)
    ws_results = _assert_ws_results_message(ws)
    assert len(parity_harness.calls) == 1

    # Step 2: REST identical query — must be a cache HIT (no additional retriever call)
    rest_response = await api.retrieve(
        api.RetrievalRequest(query="ws rest share key", enable_rerank=False),
        _fake_http_request(),
        MagicMock(),
    )
    assert len(parity_harness.calls) == 1  # HIT — retriever NOT called again

    # Payloads must be equivalent (same cached results surfaced to both transports)
    assert rest_response.total_results == ws_results["total_results"]
    assert rest_response.results[0].id == ws_results["results"][0]["id"]
