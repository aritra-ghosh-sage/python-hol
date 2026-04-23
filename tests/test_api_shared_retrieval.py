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
async def test_retrieve_endpoint_removed_after_t08(monkeypatch: pytest.MonkeyPatch) -> None:
    """T08: POST /retrieve endpoint has been permanently removed from api.py.

    The `retrieve` handler function and the /retrieve route no longer exist.
    Calling POST /retrieve must return 404.
    """
    monkeypatch.setattr(api, "_retriever", object())
    monkeypatch.setattr(api, "_config", GuardConfig(enable_rerank=True))
    monkeypatch.setattr(api, "_cache", InMemoryCache(ttl_seconds=3600, max_size=100))
    monkeypatch.setattr(api, "_cache_generation", 0)
    monkeypatch.setattr(api, "_corpus_version", "gen0.n1")

    from fastapi.testclient import TestClient
    client = TestClient(api.app)
    response = client.post("/retrieve", json={"query": "hello", "enable_rerank": False})
    assert response.status_code == 404, (
        f"Expected 404 (T08 retirement), got {response.status_code}"
    )

    # The `retrieve` function itself must no longer be exposed on the api module.
    assert not hasattr(api, "retrieve"), (
        "api.retrieve must not exist after T08 retirement"
    )


@pytest.mark.asyncio
async def test_websocket_uses_shared_facade_and_preserves_message_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    """WS /ws/chat uses shared facade and keeps status/results message contract."""

    observed: Dict[str, Any] = {}

    def fake_shared_retrieve_documents(
        query: str,
        enable_rerank: Optional[bool] = None,
        correlation_id: Optional[str] = None,
        _out_cache_status: Optional[List[str]] = None,
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
    """T08: Two identical WS queries share the cache (REST path is retired).

    WHY: The shared retrieval cache is keyed by (query, rerank, corpus_version).
    The second identical WS query must be a cache HIT with zero additional retriever calls.
    """
    ws1 = FakeWebSocket(
        incoming_messages=[{"query": "cache parity query", "enable_rerank": False}]
    )
    await api.websocket_chat(ws1)
    ws1_results = _assert_ws_results_message(ws1)
    assert len(parity_harness.calls) == 1

    ws2 = FakeWebSocket(
        incoming_messages=[{"query": "cache parity query", "enable_rerank": False}]
    )
    await api.websocket_chat(ws2)
    ws2_results = _assert_ws_results_message(ws2)

    # Second WS call must be a HIT — no additional retriever call
    assert len(parity_harness.calls) == 1
    assert ws2_results["total_results"] == ws1_results["total_results"]
    assert ws2_results["results"][0]["id"] == ws1_results["results"][0]["id"]


@pytest.mark.asyncio
async def test_parity_config_update_invalidates_shared_cache_for_rest_and_ws(
    parity_harness: FakeRetriever,
) -> None:
    """T08: Config update invalidates shared cache; subsequent WS query is a miss."""

    ws1 = FakeWebSocket(incoming_messages=[{"query": "cfg parity", "enable_rerank": False}])
    await api.websocket_chat(ws1)
    assert len(parity_harness.calls) == 1

    await api.update_config(
        api.ConfigUpdateRequest(semantic_weight=0.6, keyword_weight=0.4)
    )

    ws2 = FakeWebSocket(incoming_messages=[{"query": "cfg parity", "enable_rerank": False}])
    await api.websocket_chat(ws2)
    assert len(parity_harness.calls) == 2  # miss after invalidation

    # Third WS call with same query should be a HIT (cache warm from ws2)
    ws3 = FakeWebSocket(incoming_messages=[{"query": "cfg parity", "enable_rerank": False}])
    await api.websocket_chat(ws3)
    assert len(parity_harness.calls) == 2  # HIT


@pytest.mark.asyncio
async def test_parity_ingest_add_bumps_version_and_update_also_invalidates(
    parity_harness: FakeRetriever,
) -> None:
    """T08: ingest_type add bumps corpus_version (WS miss); update clears cache and bumps again.

    WHY: When 'add' ingests new documents, the collection count changes which means
    _build_corpus_version_token() returns a new token.  Subsequent WS queries built
    against the new token will be cache misses.  'update' additionally clears the
    L1 cache giving the same guarantee with even stronger consistency.

    Expected retriever call counts:
      1 -- initial WS query (cold miss)
      2 -- WS query after 'add' (corpus_version changed -> new cache key -> miss)
      3 -- WS query after 'update' (corpus_version changed again + cache cleared -> miss)
    """

    ws1 = FakeWebSocket(incoming_messages=[{"query": "ingest parity", "enable_rerank": False}])
    await api.websocket_chat(ws1)
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

    version_after_update = api._corpus_version
    assert version_after_update != version_after_add, (
        f"corpus_version must change after 'update', was {version_after_add!r} -> {version_after_update!r}"
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
    """T08: WS-only mixed rerank calls keep override request-local without mutating global config."""

    ws_no_rerank = FakeWebSocket(incoming_messages=[{"query": "rerank isolation", "enable_rerank": False}])
    await api.websocket_chat(ws_no_rerank)

    ws_default = FakeWebSocket(incoming_messages=[{"query": "rerank isolation"}])
    await api.websocket_chat(ws_default)

    # Repeat both variants to ensure cache identity separation and stable reuse.
    ws_no_rerank_repeat = FakeWebSocket(incoming_messages=[{"query": "rerank isolation", "enable_rerank": False}])
    await api.websocket_chat(ws_no_rerank_repeat)
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
    """T08: Both WS queries observe a cache miss after an 'add' ingest bumps corpus_version.

    WHY: _build_corpus_version_token() incorporates the live collection count.
    When 'add' inserts documents the count grows, producing a new version token.
    Any query after the bump uses a different cache key - guaranteed miss,
    so freshly-added documents are reachable.  Once one WS call populates the new
    key a second identical WS call reuses it (shared cache - hit).

    Scenario:
      1. WS query (corpus_version="gen0.n1") -> miss, calls=1
      2. 'add' ingest  -> collection count 1->2, corpus_version->"gen0.n2"
      3. WS same query (corpus_version="gen0.n2") -> miss, calls=2
      4. WS same query (corpus_version="gen0.n2") -> HIT (step 3 populated it), calls=2
    """
    # Step 1: initial WS query populates cache with corpus_version "gen0.n1"
    ws_before = FakeWebSocket(
        incoming_messages=[{"query": "version bump add parity", "enable_rerank": False}]
    )
    await api.websocket_chat(ws_before)
    ws_before_results = _assert_ws_results_message(ws_before)
    assert len(parity_harness.calls) == 1

    # Step 2: 'add' ingest - collection count grows, corpus_version token changes
    add_response = await api.add_documents(
        api.DocumentIngestionRequest(
            source_type="text",
            content="brand new document for add test",
            source_label="optb007-add",
            ingest_type="add",
        )
    )
    assert add_response.status == "success"

    # Step 3: WS query with new corpus_version -> cache MISS (new key)
    ws_after_add = FakeWebSocket(
        incoming_messages=[{"query": "version bump add parity", "enable_rerank": False}]
    )
    await api.websocket_chat(ws_after_add)
    assert len(parity_harness.calls) == 2  # miss -- new corpus_version key

    ws_after_add_results = _assert_ws_results_message(ws_after_add)

    # Step 4: second WS with same corpus_version -> HIT from cache step 3 just populated
    ws_hit = FakeWebSocket(
        incoming_messages=[{"query": "version bump add parity", "enable_rerank": False}]
    )
    await api.websocket_chat(ws_hit)
    assert len(parity_harness.calls) == 2  # HIT -- same corpus_version key

    ws_hit_results = _assert_ws_results_message(ws_hit)
    assert ws_hit_results["total_results"] == ws_after_add_results["total_results"]


@pytest.mark.asyncio
async def test_parity_corpus_version_bumps_on_update_both_transports_see_miss(
    parity_harness: FakeRetriever,
) -> None:
    """T08: Both WS queries observe a cache miss after an 'update' ingest bumps corpus_version.

    WHY: 'update' increments _cache_generation AND clears the L1 cache, then
    _build_corpus_version_token() produces a new token (gen incremented, count grown).
    The first WS query after the update is always a miss; a second identical WS query
    reuses the freshly-populated entry (shared-cache hit).

    Scenario:
      1. WS query                     -> miss, calls=1
      2. 'update' ingest              -> corpus_version changes, cache cleared
      3. WS same query (new version)  -> miss, calls=2
      4. WS same query (new version)  -> HIT, calls=2
    """
    # Step 1: warm the cache under the initial corpus_version
    ws_before = FakeWebSocket(
        incoming_messages=[{"query": "version bump update parity", "enable_rerank": False}]
    )
    await api.websocket_chat(ws_before)
    assert len(parity_harness.calls) == 1

    # Step 2: 'update' ingest - generation bumped, cache cleared, version token changed
    update_response = await api.add_documents(
        api.DocumentIngestionRequest(
            source_type="text",
            content="replacement document for update test",
            source_label="optb007-update",
            ingest_type="update",
        )
    )
    assert update_response.status == "success"

    # Step 3: WS query under new corpus_version -> cache MISS
    ws_after_update = FakeWebSocket(
        incoming_messages=[{"query": "version bump update parity", "enable_rerank": False}]
    )
    await api.websocket_chat(ws_after_update)
    assert len(parity_harness.calls) == 2  # miss -- new corpus_version key

    ws_after_update_results = _assert_ws_results_message(ws_after_update)

    # Step 4: second WS under same new corpus_version -> HIT
    ws_hit = FakeWebSocket(
        incoming_messages=[{"query": "version bump update parity", "enable_rerank": False}]
    )
    await api.websocket_chat(ws_hit)
    assert len(parity_harness.calls) == 2  # HIT -- shared key

    ws_hit_results = _assert_ws_results_message(ws_hit)
    assert ws_hit_results["total_results"] == ws_after_update_results["total_results"]


@pytest.mark.asyncio
async def test_parity_ws_first_rest_second_shares_same_corpus_version_key(
    parity_harness: FakeRetriever,
) -> None:
    """T08: Two WS queries share the same cache key under the same corpus_version.

    WHY: Both WS calls use _shared_retrieve_documents which computes the cache key
    using the module-level _corpus_version token.  Because that token is shared state,
    both calls produce the same key for the same (query, rerank, config) tuple.
    The first WS query populates the cache; the second must be a HIT.

    Scenario:
      WS1  query -> miss, retriever called once (calls=1)
      WS2  same query -> HIT (WS1 populated it), calls still 1
    """
    # Step 1: WS query goes in first - cold miss populates shared cache
    ws1 = FakeWebSocket(
        incoming_messages=[{"query": "ws rest share key", "enable_rerank": False}]
    )
    await api.websocket_chat(ws1)
    ws1_results = _assert_ws_results_message(ws1)
    assert len(parity_harness.calls) == 1

    # Step 2: Second identical WS query - must be a cache HIT (no additional retriever call)
    ws2 = FakeWebSocket(
        incoming_messages=[{"query": "ws rest share key", "enable_rerank": False}]
    )
    await api.websocket_chat(ws2)
    ws2_results = _assert_ws_results_message(ws2)
    assert len(parity_harness.calls) == 1  # HIT -- retriever NOT called again

    # Payloads must be equivalent (same cached results surfaced)
    assert ws2_results["total_results"] == ws1_results["total_results"]
    assert ws2_results["results"][0]["id"] == ws1_results["results"][0]["id"]
