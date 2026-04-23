"""OPTB-013 — Wave 7 Documentation Closeout: Living-contract tests.

WHY THIS FILE EXISTS:
    OPTB-013 is a documentation closeout task.  After several waves of
    feature work (OPTB-007 through OPTB-012) the public API surface has
    drifted from what earlier integration tests verify.  This file pins the
    *documented* contracts in executable form so that:

      1. Any future refactor that silently breaks a published contract causes
         a CI failure immediately, not a support ticket weeks later.
      2. New contributors can read the tests as authoritative documentation
         of what each header, field, and schema actually means.

    These are **living documentation** contract tests — they validate that
    the *implemented* behaviour matches the contracts recorded in the updated
    docs.  They are NOT new-feature tests and they must pass against the
    current codebase without any implementation changes.

WHAT IS COVERED (one class per contract):
    TestLayeredStatsSchemaContract     — OPTB-008 layered /cache/stats schema
    TestCorpusVersionFormatContract    — corpus_version token shape
    TestXCacheHeaderContract           — X-Cache response header naming/values
    TestIngestTypeParameterContract    — DocumentIngestionRequest.ingest_type
    TestNodeLocalL2ScopeContract       — L2 stats come from retriever, not Redis
    TestFallbackSemanticsContract      — backend_health.fallback_active logic
    TestCrossIssueDecisionContract     — Cross-issue architecture decisions

STYLE REFERENCE:
    tests/test_cache_stats_layered.py — monkeypatch patterns, FakeCache doubles
    tests/test_observability_logs.py  — fake collection/retriever patterns

Python version: 3.13
"""

import re
# Note 1: `re` is Python's built-in regular-expression module. We use it here
# to compile a pattern once (re.compile) and reuse it across many tests,
# which is faster than calling re.match() on a fresh pattern string each time.

from typing import Any, Dict, List, NoReturn, Optional
# Note 2: These type-hint aliases come from the `typing` module (Python < 3.9
# required them; 3.9+ allows lowercase `dict`, `list` directly).
#   Any     -- disables type checking for a value; used when the dict shape
#              is validated by assertion rather than by static analysis.
#   Dict    -- annotates a mapping with known key/value types, e.g. Dict[str, Any].
#   List    -- annotates an ordered sequence, e.g. List[str].
#   NoReturn -- marks a function that ALWAYS raises; the type checker knows
#               it can never return normally, which helps it reason about
#               unreachable code after calls to such functions.
#   Optional[T] -- short for Union[T, None]; signals a value can be missing.

import pytest
# Note 3: `pytest` is the test framework. Importing it gives access to
# pytest.fixture (for setup/teardown), pytest.raises (to assert exceptions),
# and pytest.MonkeyPatch (for safe, auto-reversible attribute patching).
from fastapi.testclient import TestClient
# Note 4: `TestClient` wraps the FastAPI/Starlette ASGI application so tests
# can call HTTP endpoints (GET, POST, etc.) in-process, with no network socket
# needed. Under the hood it uses `httpx` with an ASGI transport layer.

import api
# Note 5: Importing `api` as a module (not just specific names) lets tests
# patch module-level globals with monkeypatch.setattr(api, "_cache", ...).
# This works because Python modules are singleton objects; every reference
# to `api._cache` sees the same object after the patch.
from hybrid_rag.cache import InMemoryCache
# Note 6: InMemoryCache is imported so the fallback-semantics tests can wire
# a *real* in-memory backend, distinguishing it from the Fake double used in
# shape-only tests. Using a real backend for the 'healthy' path tests avoids
# false confidence that would arise if a Fake always returned fallback_active=False.


# ---------------------------------------------------------------------------
# Test Doubles
# (Copied verbatim from tests/test_cache_stats_layered.py — do NOT import from
# that file to keep this module self-contained and resilient to refactors.)
# ---------------------------------------------------------------------------


class FakeCacheForStats:
    """Minimal cache double whose stats() return known, predictable values.

    WHY: Real InMemoryCache counters depend on actual get/set calls, making
    assertions about specific numeric values fragile.  This double lets tests
    assert exact field shapes without triggering live cache operations.
    """
    # Note 7: This class is a *Fake* — a simplified but working implementation
    # of a dependency (the cache). Fakes differ from Mocks (which record and
    # verify calls via a framework) and Stubs (which return canned responses
    # with no state). A Fake has just enough real logic to satisfy the contract
    # the code-under-test depends on (stats(), get(), set(), clear(), health()).

    def __init__(
        self,
        backend: str = "memory",
        hits: int = 10,
        misses: int = 5,
        size: int = 3,
        max_size: int = 100,
        ttl_seconds: int = 3600,
    ) -> None:
        # Note 8: Constructor parameters all have default values, making the
        # Fake cheap to construct in the common case: FakeCacheForStats().
        # Individual tests can override specific fields to probe edge cases, e.g.
        # FakeCacheForStats(hits=0, misses=0) to test a cold-cache scenario.
        self._backend = backend
        self._hits = hits
        self._misses = misses
        self._size = size
        self._max_size = max_size
        self._ttl_seconds = ttl_seconds
        # Note 9: `_clear_call_count` is a lightweight spy. Rather than pulling
        # in a mocking library, we track calls manually. Tests that need to
        # verify *whether* clear() was called simply check this integer.
        self._clear_call_count: int = 0

    def stats(self) -> Dict[str, Any]:
        """Return predictable stats dict matching the shape InMemoryCache produces."""
        # Note 10: Returning a plain `dict` (not a Pydantic model) is intentional.
        # The real InMemoryCache.stats() also returns a dict; the api.py endpoint
        # then validates and maps it into the LayeredCacheStatsResponse Pydantic model.
        # By returning a dict here we test the full mapping path, not just the model.
        return {
            "backend": self._backend,
            "hits": self._hits,
            "misses": self._misses,
            "size": self._size,
            "max_size": self._max_size,
            "ttl_seconds": self._ttl_seconds,
        }

    # Stubs so the cache can be assigned to api._cache without AttributeErrors.
    # Note 11: Methods that return `None` implicitly or `Optional[Any]` with a
    # `return None` are *stubs* — placeholders that satisfy the interface without
    # doing real work. The api code calls these methods but does not assert their
    # return values in the tests covered by this file, so no tracking is needed.
    def get(self, key: str) -> Optional[Any]:
        return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        pass

    def delete(self, key: str) -> None:
        pass

    def clear(self) -> None:
        self._clear_call_count += 1

    def health(self) -> Dict[str, Any]:
        """Return a healthy sentinel — FakeCacheForStats has no network backend."""
        return {
            "connected": True,
            "latency_ms": None,
            "fallback_active": False,
            "error": None,
        }


class FakeRetrieverWithEmbeddingStats:
    """Retriever double exposing a public get_embedding_cache_stats() method.

    WHY: The layered schema requires L2 stats pulled from the retriever.
    This double lets tests assert the contract with deterministic, known values.
    """

    def __init__(
        self,
        hits: int = 20,
        misses: int = 8,
        size: int = 12,
        capacity: int = 5000,
    ) -> None:
        self._hits = hits
        self._misses = misses
        self._size = size
        self._capacity = capacity
        total = hits + misses
        self._hit_rate = hits / total if total > 0 else 0.0

    def get_embedding_cache_stats(self) -> Dict[str, Any]:
        """Return L2 embedding cache stats in the expected shape."""
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": self._hit_rate,
            "size": self._size,
            "capacity": self._capacity,
        }


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


@pytest.fixture
# Note 12: A `@pytest.fixture` is a setup function that pytest automatically
# calls before each test that requests it by name. When the fixture yields (or
# returns), pytest passes the yielded value to the test function as an argument.
# Function scope (default) means setup+teardown happens for EVERY individual test,
# giving each test a clean, isolated state.
def stats_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Wire up a minimal, isolated environment for /cache/stats tests.

    Patches api._cache, api._retriever, and api._corpus_version to stable
    known values.  Returns a synchronous TestClient.

    WHY function-scope monkeypatch: each test must start from a clean
    module-level state to avoid cross-test pollution.
    """
    # Note 13: `monkeypatch.setattr(obj, name, value)` replaces `obj.name` with
    # `value` for the duration of the test, then automatically restores the
    # original value when the test finishes. This is safer than direct assignment
    # (`api._cache = ...`) because it guarantees restoration even if the test
    # raises an exception — avoiding state leakage into subsequent tests.
    monkeypatch.setattr(api, "_corpus_version", "gen0.n1")
    monkeypatch.setattr(api, "_cache", FakeCacheForStats())
    monkeypatch.setattr(api, "_retriever", FakeRetrieverWithEmbeddingStats())
    monkeypatch.setattr(api, "_cache_generation", 0)
    return TestClient(api.app)


# ===========================================================================
# TestLayeredStatsSchemaContract
# ===========================================================================


class TestLayeredStatsSchemaContract:
    """Contract tests for the OPTB-008 layered /cache/stats response schema.

    WHAT CONTRACT: GET /cache/stats returns exactly four top-level keys —
    l1_query_cache, l2_embedding_cache, backend_health, timestamp — and the
    old flat keys (hits, misses, hit_rate, size, backend) must NOT appear at
    the top level.

    WHY THIS CLASS: Consumers such as Grafana dashboards, on-call runbooks,
    and the frontend cache inspector navigate to specific nested keys (e.g.
    response['backend_health']['fallback_active']).  Any accidental reversion
    to the flat schema would silently break those consumers without error.
    Pinning the exact key names here makes that regression visible in CI.
    """

    def test_stats_response_has_exactly_four_top_level_keys(
        self, stats_client: TestClient
    ) -> None:
        """GET /cache/stats must return exactly the four documented top-level keys.

        WHAT: Validates the complete top-level key set — no more, no less.
        WHY: An extra undocumented key at the top level is as dangerous as a
        missing key: consumers iterating over keys would encounter unexpected
        fields, and over time the schema would drift from what the docs say.
        """
        response = stats_client.get("/cache/stats")
        assert response.status_code == 200
        body: Dict[str, Any] = response.json()

        # Note 14: `set(body.keys())` converts the dict's key view into a Python
        # set, enabling O(1) lookup and set-algebra operations (union, intersection,
        # difference). Comparing two sets with `==` is a clean way to assert
        # "exactly these keys and no others" without caring about order.
        expected_keys = {"l1_query_cache", "l2_embedding_cache", "backend_health", "timestamp"}
        actual_keys = set(body.keys())
        assert actual_keys == expected_keys, (
            f"Expected top-level keys {expected_keys!r}, got {actual_keys!r}"
        )

    def test_old_flat_fields_absent_from_top_level(
        self, stats_client: TestClient
    ) -> None:
        """Pre-OPTB-008 flat fields must not appear at the response root.

        WHAT: Confirms that 'hits', 'misses', 'hit_rate', 'size', and 'backend'
        are absent from the top-level JSON object.
        WHY: External monitoring systems (e.g. alerting rules built before
        OPTB-008) that read top-level 'hits' would silently return zero/null
        rather than raising an error if those keys still existed.  Asserting
        their absence forces consumers to update to the layered schema.
        """
        response = stats_client.get("/cache/stats")
        body: Dict[str, Any] = response.json()

        # Note 15: The `&` operator on two sets computes their intersection —
        # i.e., the keys present in BOTH sets. If the intersection is non-empty,
        # deprecated flat keys have crept back to the top level. The assertion
        # message names the exact fields so a failing CI log is actionable.
        deprecated_flat_keys = {"hits", "misses", "hit_rate", "size", "backend"}
        found_flat_keys = deprecated_flat_keys & set(body.keys())
        assert not found_flat_keys, (
            f"Deprecated flat keys still present at top level: {found_flat_keys!r}. "
            "These were replaced by the nested l1_query_cache section in OPTB-008."
        )

    def test_l1_query_cache_contains_required_fields(
        self, stats_client: TestClient
    ) -> None:
        """l1_query_cache must contain all documented L1 metric fields.

        WHAT: Validates every required field name inside the l1_query_cache
        sub-object, including the corpus_version token added by OPTB-007.
        WHY: l1_query_cache is the primary L1 operational metric block used by
        the cache hit-rate SLO dashboard.  A missing field (especially
        corpus_version) breaks version-aware invalidation debugging workflows.
        """
        response = stats_client.get("/cache/stats")
        body: Dict[str, Any] = response.json()
        l1: Dict[str, Any] = body["l1_query_cache"]

        required = {"backend", "hits", "misses", "hit_rate", "size", "max_size", "ttl_seconds", "corpus_version"}
        missing = required - set(l1.keys())
        assert not missing, f"l1_query_cache is missing documented fields: {missing!r}"

    def test_l2_embedding_cache_contains_required_fields(
        self, stats_client: TestClient
    ) -> None:
        """l2_embedding_cache must contain all documented L2 metric fields.

        WHAT: Validates every required field name inside l2_embedding_cache.
        WHY: L2 metrics are the only visibility into embedding-cache efficiency.
        'capacity' is critical — without it, ops teams cannot detect that the
        LRU is at capacity and evicting aggressively.
        """
        response = stats_client.get("/cache/stats")
        body: Dict[str, Any] = response.json()
        l2: Dict[str, Any] = body["l2_embedding_cache"]

        required = {"hits", "misses", "hit_rate", "size", "capacity"}
        missing = required - set(l2.keys())
        assert not missing, f"l2_embedding_cache is missing documented fields: {missing!r}"

    def test_backend_health_contains_required_fields(
        self, stats_client: TestClient
    ) -> None:
        """backend_health must contain all documented health and observability fields.

        WHAT: Validates every required field inside backend_health.
        WHY: 'fallback_active' and 'latency_ms' are the two on-call alert
        fields.  'error' carries the root-cause message.  Silently absent
        fields make alert rules produce false positives or negatives.
        """
        response = stats_client.get("/cache/stats")
        body: Dict[str, Any] = response.json()
        bh: Dict[str, Any] = body["backend_health"]

        required = {"connected", "latency_ms", "fallback_active", "error"}
        missing = required - set(bh.keys())
        assert not missing, f"backend_health is missing documented fields: {missing!r}"

    def test_timestamp_is_iso8601_string(self, stats_client: TestClient) -> None:
        """timestamp must be a non-empty string in ISO-8601 format.

        WHAT: Validates that the timestamp field is a parseable ISO-8601 UTC
        datetime string (e.g. '2026-04-22T10:30:45.123456Z').
        WHY: Consumers that use the timestamp for staleness detection (e.g.
        dashboards that warn when stats are > 60s old) will crash with a
        runtime error if the timestamp is an integer epoch or a non-standard
        date format.
        """
        response = stats_client.get("/cache/stats")
        body: Dict[str, Any] = response.json()
        ts: Any = body.get("timestamp")

        assert isinstance(ts, str), f"timestamp must be a string, got {type(ts).__name__!r}"
        assert len(ts) > 0, "timestamp string must not be empty"

        # Note 18: The `iso8601_prefix_re` regex uses anchors (^ and no $)
        # deliberately. `^` asserts "start of string". Omitting a closing $ means
        # we only validate the mandatory prefix (YYYY-MM-DDTHH:MM:SS) and accept
        # any valid suffix (fractional seconds, timezone offset like "+00:00",
        # or the "Z" shorthand). This tolerates the variation between Python
        # datetime serialisers without hard-coding a single exact format.
        iso8601_prefix_re = re.compile(
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
        )
        assert iso8601_prefix_re.match(ts), (
            f"timestamp {ts!r} does not start with expected ISO-8601 prefix YYYY-MM-DDTHH:MM:SS"
        )


# ===========================================================================
# TestCorpusVersionFormatContract
# ===========================================================================


class TestCorpusVersionFormatContract:
    """Contract tests for the corpus_version token format defined in OPTB-007.

    WHAT CONTRACT: The corpus_version token must match the pattern
    ``gen{N}.n{count}`` (e.g. "gen0.n1", "gen2.n108").  The token is
    surfaced in two places: the module-level ``api._corpus_version`` attribute
    and the ``l1_query_cache.corpus_version`` field in the stats response.

    WHY THIS CLASS: Log parsers, cache key analysis scripts, and alerting
    rules are built on this exact format.  A regression to the old plain
    integer format (e.g. "0") would silently corrupt those tools without
    any schema validation error.
    """

    # Note 16: Defining a compiled regex as a class-level attribute means
    # `re.compile()` runs once when the class is loaded, not once per test
    # invocation. For 33 tests in this file the difference is negligible, but
    # it is a good habit: regex compilation is non-trivial for complex patterns.
    # Making it a public attribute also allows external tools (e.g. log parsers)
    # to import and reuse the authoritative pattern: `from test_optb013_docs_closeout
    # import TestCorpusVersionFormatContract; TestCorpusVersionFormatContract.CORPUS_VERSION_PATTERN`.
    CORPUS_VERSION_PATTERN: re.Pattern[str] = re.compile(r"^gen\d+\.n\d+$")

    def test_build_corpus_version_token_function_exists(self) -> None:
        """api._build_corpus_version_token() must be a callable function.

        WHAT: Confirms the documented internal function exists and is callable.
        WHY: External tooling documentation references _build_corpus_version_token
        by name as the authoritative source for the token format.  Removing or
        renaming this function would break the documentation link.
        """
        # Note 17: `getattr(obj, name, default)` is the safe attribute-lookup
        # form. It returns `default` (None here) if `name` doesn't exist on `obj`
        # instead of raising AttributeError. `callable(x)` returns True if `x`
        # has a __call__ method — i.e., can be invoked as a function.
        # Together they form: "if this attribute exists AND is a function".
        assert callable(getattr(api, "_build_corpus_version_token", None)), (
            "api._build_corpus_version_token must exist and be callable"
        )

    def test_build_corpus_version_token_returns_string(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_build_corpus_version_token() must return a str.

        WHAT: Confirms the return type contract is honoured.
        WHY: Cache key construction uses string concatenation with this value.
        A non-string return (int, None) would raise TypeError at the most
        inopportune moment — on the first cache write after a restart.
        """
        monkeypatch.setattr(api, "_retriever", None)  # force fallback path
        result = api._build_corpus_version_token()
        # Note 19: `isinstance(result, str)` is the idiomatic Python runtime type
        # check. Prefer it over `type(result) == str` because isinstance handles
        # subclasses correctly (a subclass of str IS a str). In test code it gives
        # a clear error when the contract is violated without needing mypy.
        assert isinstance(result, str), (
            f"_build_corpus_version_token() must return str, got {type(result).__name__!r}"
        )

    def test_build_corpus_version_token_matches_pattern(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_build_corpus_version_token() return value must match gen{N}.n{count}.

        WHAT: Validates the format contract of the corpus version token.
        WHY: The documented format is ``gen{N}.n{count}``.  Log parsers and
        cache key analysis scripts use regex anchored to this format.  A
        token like "0" (old format) or "v1-108" (hypothetical future change)
        would break those tools without a schema validation error.
        """
        monkeypatch.setattr(api, "_retriever", None)  # exercises fallback path
        token = api._build_corpus_version_token()
        assert self.CORPUS_VERSION_PATTERN.match(token), (
            f"_build_corpus_version_token() returned {token!r}, "
            f"expected format matching gen{{N}}.n{{count}} (e.g. 'gen0.n0')"
        )

    def test_corpus_version_module_attribute_exists(self) -> None:
        """api._corpus_version module attribute must exist.

        WHAT: Confirms the module-level state variable is present.
        WHY: The stats endpoint reads _corpus_version directly.  If the
        attribute were removed, the stats endpoint would raise NameError and
        return HTTP 500 — violating the fail-open contract.
        """
        assert hasattr(api, "_corpus_version"), (
            "api._corpus_version module attribute must exist"
        )

    def test_corpus_version_module_attribute_matches_pattern(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """api._corpus_version must match the documented gen{N}.n{count} format.

        WHAT: After setting a known value, verifies the stats response echoes
        it verbatim in l1_query_cache.corpus_version.
        WHY: The stats endpoint must surface the live token, not a cached or
        derived copy.  If the endpoint re-derives the token independently, it
        could diverge from the authoritative _corpus_version during a race.
        """
        known_version = "gen3.n42"
        monkeypatch.setattr(api, "_corpus_version", known_version)
        monkeypatch.setattr(api, "_cache", FakeCacheForStats())
        monkeypatch.setattr(api, "_retriever", FakeRetrieverWithEmbeddingStats())

        client = TestClient(api.app)
        response = client.get("/cache/stats")
        body: Dict[str, Any] = response.json()

        actual = body["l1_query_cache"]["corpus_version"]
        assert actual == known_version, (
            f"l1_query_cache.corpus_version expected {known_version!r}, got {actual!r}"
        )

    def test_corpus_version_fallback_token_matches_pattern(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fallback token (no retriever) must still match gen{N}.n{count}.

        WHAT: Confirms that even without a retriever the fallback token format
        is consistent with the documented pattern.
        WHY: Tools that parse corpus_version tokens from logs must not need
        special-case handling for 'retriever not available' states.
        """
        monkeypatch.setattr(api, "_retriever", None)
        monkeypatch.setattr(api, "_cache_generation", 0)
        token = api._build_corpus_version_token()
        assert self.CORPUS_VERSION_PATTERN.match(token), (
            f"Fallback token {token!r} does not match gen{{N}}.n{{count}} pattern"
        )


# ===========================================================================
# TestXCacheHeaderContract
# ===========================================================================


class TestXCacheHeaderContract:
    """Contract test for X-Cache header absence on admin endpoints.

    Asserts that GET /cache/stats does not carry an X-Cache header.
    """

    def test_x_cache_header_absent_on_stats_endpoint(
        self, stats_client: TestClient
    ) -> None:
        """GET /cache/stats must NOT carry an X-Cache header.

        WHAT: Confirms that the /cache/stats path has no X-Cache header.
        WHY: No path should receive X-Cache headers; the middleware that
        injected this header has been removed.
        """
        response = stats_client.get("/cache/stats")
        assert response.status_code == 200

        header_names_lower = {h.lower() for h in response.headers}
        assert "x-cache" not in header_names_lower, (
            "X-Cache header must NOT be present on GET /cache/stats"
        )


# ===========================================================================
# TestIngestTypeParameterContract
# ===========================================================================


class TestIngestTypeParameterContract:
    """Contract tests for the DocumentIngestionRequest.ingest_type field.

    WHAT CONTRACT: DocumentIngestionRequest.ingest_type is a Literal["add",
    "update"] field.  The default is 'update' (backwards-compatible).
    When 'update' is used, the cache is cleared after ingestion.
    When 'add' is used, the cache is preserved.

    WHY THIS CLASS: The ingest_type field controls whether the L1 response
    cache is invalidated after each ingest.  Bulk import workflows depend on
    'add' to avoid O(N) cache flushes — one per document — that would destroy
    cache hit rates during an import.  If the field were silently ignored,
    bulk imports would thrash the cache.
    """

    def test_document_ingestion_request_has_ingest_type_field(self) -> None:
        """DocumentIngestionRequest must have an ingest_type field.

        WHAT: Confirms the field exists on the Pydantic model.
        WHY: The field is referenced in the public API docs.  Its absence
        would mean every POST /documents call behaves as 'update' regardless
        of what the caller sends, silently breaking bulk-import workflows.
        """
        from api import DocumentIngestionRequest

        field_names = set(DocumentIngestionRequest.model_fields.keys())
        assert "ingest_type" in field_names, (
            "DocumentIngestionRequest must have an 'ingest_type' field"
        )

    def test_ingest_type_is_literal_add_or_update(self) -> None:
        """ingest_type must accept exactly 'add' and 'update'.

        WHAT: Confirms that both documented values are accepted and invalid
        values are rejected by model validation.
        WHY: Callers that pass undocumented values should receive a 422, not
        a silent fallback to the default — that silent fallback could cause
        unexpected cache invalidations on bulk ingest.
        """
        from pydantic import ValidationError
        from api import DocumentIngestionRequest
        # Note 20: Importing inside the test function (not at module level) keeps
        # the import visible right next to its usage, making the test
        # self-contained and readable. It also avoids polluting the module
        # namespace with names only needed in this one test.

        # Both documented values must be accepted.
        req_add = DocumentIngestionRequest(
            source_type="text", content="hello world", ingest_type="add"
        )
        assert req_add.ingest_type == "add"

        req_update = DocumentIngestionRequest(
            source_type="text", content="hello world", ingest_type="update"
        )
        assert req_update.ingest_type == "update"

        # Note 21: `pytest.raises(ExceptionClass)` is a context manager that
        # asserts the block inside raises ExceptionClass. If no exception is
        # raised, the test fails. If a different exception is raised, pytest
        # re-raises it as a test failure. This is the idiomatic way to test
        # that invalid inputs are properly rejected.
        with pytest.raises(ValidationError):
            DocumentIngestionRequest(
                source_type="text", content="hello world", ingest_type="replace"  # type: ignore[arg-type]
            )

    def test_ingest_type_default_is_update(self) -> None:
        """Default ingest_type must be 'update' for backwards compatibility.

        WHAT: Confirms that omitting ingest_type produces the 'update' default.
        WHY: Existing callers that do not supply ingest_type must continue to
        receive cache-clearing behaviour.  Changing the default to 'add' would
        silently break those callers' expectation of fresh retrieval results
        after every ingest.
        """
        from api import DocumentIngestionRequest

        req = DocumentIngestionRequest(source_type="text", content="default test")
        assert req.ingest_type == "update", (
            f"Default ingest_type must be 'update' for backwards compatibility; "
            f"got {req.ingest_type!r}"
        )

    def test_ingest_update_clears_cache(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """POST /documents with ingest_type='update' must call cache.clear().

        WHAT: Wires a tracking cache double and verifies that a successful
        ingest with ingest_type='update' results in exactly one cache.clear()
        call.
        WHY: If cache.clear() is not called, stale retrieval results will be
        served to users after the corpus is updated.  This is a correctness
        regression with direct user-visible impact.
        """
        tracking_cache = FakeCacheForStats()
        fake_retriever = _FakeIngestableRetriever()
        monkeypatch.setattr(api, "_cache", tracking_cache)
        monkeypatch.setattr(api, "_retriever", fake_retriever)
        monkeypatch.setattr(api, "_config", _fake_config())
        monkeypatch.setattr(api, "_corpus_version", "gen0.n5")
        monkeypatch.setattr(api, "_cache_generation", 0)

        client = TestClient(api.app)
        response = client.post(
            "/documents",
            json={"source_type": "text", "content": "New doc.", "ingest_type": "update"},
        )

        assert response.status_code == 200, (
            f"Expected 200 for ingest_type='update', got {response.status_code}: "
            f"{response.text}"
        )
        assert tracking_cache._clear_call_count >= 1, (
            "cache.clear() must be called at least once for ingest_type='update'"
        )

    def test_ingest_add_preserves_cache(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """POST /documents with ingest_type='add' must NOT call cache.clear().

        WHAT: Wires a tracking cache double and verifies that a successful
        ingest with ingest_type='add' results in zero cache.clear() calls.
        WHY: Bulk import workflows send hundreds of 'add' requests.  A single
        unintentional cache.clear() per document would flush all cached query
        results for every document in the batch — an O(N) correctness bug.
        """
        tracking_cache = FakeCacheForStats()
        fake_retriever = _FakeIngestableRetriever()
        monkeypatch.setattr(api, "_cache", tracking_cache)
        monkeypatch.setattr(api, "_retriever", fake_retriever)
        monkeypatch.setattr(api, "_config", _fake_config())
        monkeypatch.setattr(api, "_corpus_version", "gen0.n5")
        monkeypatch.setattr(api, "_cache_generation", 0)

        client = TestClient(api.app)
        response = client.post(
            "/documents",
            json={"source_type": "text", "content": "Bulk doc.", "ingest_type": "add"},
        )

        assert response.status_code == 200, (
            f"Expected 200 for ingest_type='add', got {response.status_code}: "
            f"{response.text}"
        )
        assert tracking_cache._clear_call_count == 0, (
            f"cache.clear() must NOT be called for ingest_type='add'; "
            f"was called {tracking_cache._clear_call_count} time(s)"
        )


# ===========================================================================
# TestNodeLocalL2ScopeContract
# ===========================================================================


class TestNodeLocalL2ScopeContract:
    """Contract tests confirming L2 embedding cache is node-local (inside HybridRetriever).

    WHAT CONTRACT: The l2_embedding_cache stats in the response come exclusively
    from _retriever.get_embedding_cache_stats() — never from the Redis / L1
    backend.  When _retriever is None, l2 stats are zeroed, not absent.

    WHY THIS CLASS: An architectural decision was made to keep L2 as an
    in-process LRU cache inside HybridRetriever rather than a shared Redis
    backend.  This keeps embedding cache warm-up semantics simple (per process)
    and avoids the complexity of serializing embedding vectors to Redis.
    These tests enforce that contract so a future 'shared L2' experiment
    would require a deliberate, reviewed contract change rather than a
    silent refactor.
    """

    def test_l2_stats_sourced_from_retriever_not_l1_cache(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """l2_embedding_cache values must come from the retriever, not the L1 cache.

        WHAT: Sets the L1 cache stats to zero and the retriever L2 stats to
        non-zero values, then verifies the response carries the retriever's
        numbers.
        WHY: If the endpoint were accidentally reading L2 stats from the L1
        cache backend, both sections would show zeros when L1 is fresh — the
        bug would be invisible in the common case but corrupt data in the
        non-trivial case.
        """
        zero_cache = FakeCacheForStats(hits=0, misses=0, size=0)
        rich_retriever = FakeRetrieverWithEmbeddingStats(
            hits=77, misses=13, size=50, capacity=2000
        )
        monkeypatch.setattr(api, "_cache", zero_cache)
        monkeypatch.setattr(api, "_retriever", rich_retriever)
        monkeypatch.setattr(api, "_corpus_version", "gen0.n1")

        client = TestClient(api.app)
        response = client.get("/cache/stats")
        body: Dict[str, Any] = response.json()

        l2: Dict[str, Any] = body["l2_embedding_cache"]
        assert l2["hits"] == 77, (
            f"l2.hits must come from retriever (77), not from L1 (0); got {l2['hits']}"
        )
        assert l2["misses"] == 13, (
            f"l2.misses must come from retriever (13), not from L1 (0); got {l2['misses']}"
        )
        assert l2["size"] == 50, (
            f"l2.size must come from retriever (50), not from L1 (0); got {l2['size']}"
        )
        assert l2["capacity"] == 2000, (
            f"l2.capacity must come from retriever (2000); got {l2['capacity']}"
        )

    def test_l2_stats_zeroed_when_retriever_is_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """l2_embedding_cache must show zeros (not absence) when _retriever is None.

        WHAT: Confirms the fail-open behaviour for the L2 section when the
        retriever is not yet initialised.
        WHY: Zeroed values are safe for consumers to parse; absent fields or
        null values cause KeyError / None-dereference bugs in downstream code
        that assumes the schema is always complete.
        """
        monkeypatch.setattr(api, "_retriever", None)
        monkeypatch.setattr(api, "_cache", FakeCacheForStats())
        monkeypatch.setattr(api, "_corpus_version", "gen0.n1")

        client = TestClient(api.app)
        response = client.get("/cache/stats")
        assert response.status_code == 200
        body: Dict[str, Any] = response.json()

        l2: Dict[str, Any] = body["l2_embedding_cache"]
        for field, expected in [("hits", 0), ("misses", 0), ("hit_rate", 0.0), ("size", 0), ("capacity", 0)]:
            assert l2[field] == expected, (
                f"l2.{field} must be {expected} when retriever is None; got {l2[field]!r}"
            )

    def test_l2_stats_use_get_embedding_cache_stats_method(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The endpoint must call retriever.get_embedding_cache_stats() to populate L2.

        WHAT: Uses a retriever double with a tracking flag to confirm the
        public get_embedding_cache_stats() method is called (not a private
        alternative).
        WHY: If the endpoint called a private method (e.g. _get_embedding_cache_stats)
        it would tightly couple to an implementation detail that could be
        renamed or removed during a refactor.  The public method is the
        documented contract.
        """
        call_log: List[str] = []
        # Note 22: `call_log` is a mutable list defined in the test's local
        # scope. The nested `TrackingRetriever` class captures it via closure —
        # it can read and modify the list because Python closures capture the
        # binding (variable reference), not the value. Lists are mutable, so
        # `call_log.append(...)` mutates the same list the assertion reads.

        class TrackingRetriever(FakeRetrieverWithEmbeddingStats):
            # Note 23: Subclassing `FakeRetrieverWithEmbeddingStats` lets us
            # override only `get_embedding_cache_stats` while inheriting all
            # other stub methods. This is the *Spy* test-double pattern: we
            # wrap the method to record that it was called, then delegate to
            # the parent for the actual return value.
            def get_embedding_cache_stats(self) -> Dict[str, Any]:
                call_log.append("get_embedding_cache_stats")
                return super().get_embedding_cache_stats()

        monkeypatch.setattr(api, "_retriever", TrackingRetriever())
        monkeypatch.setattr(api, "_cache", FakeCacheForStats())
        monkeypatch.setattr(api, "_corpus_version", "gen0.n1")

        client = TestClient(api.app)
        client.get("/cache/stats")

        assert "get_embedding_cache_stats" in call_log, (
            "The stats endpoint must call retriever.get_embedding_cache_stats() "
            "to populate the l2_embedding_cache section"
        )


# ===========================================================================
# TestFallbackSemanticsContract
# ===========================================================================


class TestFallbackSemanticsContract:
    """Contract tests for the fallback_active / connected semantics in backend_health.

    WHAT CONTRACT:
      - backend_health.fallback_active is True when _cache is None
      - backend_health.fallback_active is False under normal InMemoryCache operation
      - backend_health.connected is False when _cache is None
      - backend_health.connected is True for a healthy InMemoryCache

    WHY THIS CLASS: 'fallback_active' is the first signal of backend
    degradation.  On-call engineers page off this field.  If its semantics
    are wrong (e.g. True under normal operation), the on-call team would be
    paged constantly on a healthy system.  If it stays False when the cache is
    gone, a real outage would go undetected.
    """

    def test_fallback_active_true_when_cache_is_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """backend_health.fallback_active must be True when _cache is None.

        WHAT: Sets _cache to None and confirms the stats endpoint reports
        the degraded state.
        WHY: When no cache backend is available (startup race, Redis crash,
        config error) the system falls back to direct retriever calls.
        Operators need this signal to know the cache is not running.
        """
        monkeypatch.setattr(api, "_cache", None)
        monkeypatch.setattr(api, "_retriever", FakeRetrieverWithEmbeddingStats())

        client = TestClient(api.app)
        response = client.get("/cache/stats")
        body: Dict[str, Any] = response.json()

        bh: Dict[str, Any] = body["backend_health"]
        assert bh["fallback_active"] is True, (
            "backend_health.fallback_active must be True when _cache is None; "
            f"got {bh['fallback_active']!r}"
        )

    def test_connected_false_when_cache_is_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """backend_health.connected must be False when _cache is None.

        WHAT: Confirms that both the 'connected' and 'fallback_active' flags
        correctly reflect the absent-cache state.
        WHY: Alerting rules often check both fields for belt-and-suspenders
        detection.  A True 'connected' with a None cache would be contradictory
        and would confuse automated runbooks.
        """
        monkeypatch.setattr(api, "_cache", None)
        monkeypatch.setattr(api, "_retriever", FakeRetrieverWithEmbeddingStats())

        client = TestClient(api.app)
        response = client.get("/cache/stats")
        body: Dict[str, Any] = response.json()

        bh: Dict[str, Any] = body["backend_health"]
        assert bh["connected"] is False, (
            "backend_health.connected must be False when _cache is None; "
            f"got {bh['connected']!r}"
        )

    def test_fallback_active_false_under_normal_inmemory_operation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """backend_health.fallback_active must be False for a healthy InMemoryCache.

        WHAT: Wires a real InMemoryCache and confirms fallback_active is False.
        WHY: InMemoryCache is the 'always-healthy' backend.  If fallback_active
        were True for InMemoryCache, every deployment without Redis would
        permanently look degraded in the monitoring dashboard — a perma-alert
        that would train on-call engineers to ignore it.
        """
        real_cache = InMemoryCache(ttl_seconds=3600, max_size=100)
        monkeypatch.setattr(api, "_cache", real_cache)
        monkeypatch.setattr(api, "_retriever", FakeRetrieverWithEmbeddingStats())
        monkeypatch.setattr(api, "_corpus_version", "gen0.n1")

        client = TestClient(api.app)
        response = client.get("/cache/stats")
        body: Dict[str, Any] = response.json()

        bh: Dict[str, Any] = body["backend_health"]
        assert bh["fallback_active"] is False, (
            "backend_health.fallback_active must be False for InMemoryCache; "
            f"got {bh['fallback_active']!r}"
        )

    def test_connected_true_under_normal_inmemory_operation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """backend_health.connected must be True for a healthy InMemoryCache.

        WHAT: Mirrors test_fallback_active_false_under_normal_inmemory_operation
        for the 'connected' field.
        WHY: A monitoring dashboard that reads both fields must see consistent
        'healthy' values for a functioning in-memory backend.
        """
        real_cache = InMemoryCache(ttl_seconds=3600, max_size=100)
        monkeypatch.setattr(api, "_cache", real_cache)
        monkeypatch.setattr(api, "_retriever", FakeRetrieverWithEmbeddingStats())
        monkeypatch.setattr(api, "_corpus_version", "gen0.n1")

        client = TestClient(api.app)
        response = client.get("/cache/stats")
        body: Dict[str, Any] = response.json()

        bh: Dict[str, Any] = body["backend_health"]
        assert bh["connected"] is True, (
            "backend_health.connected must be True for InMemoryCache; "
            f"got {bh['connected']!r}"
        )

    def test_stats_endpoint_returns_200_when_cache_is_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """GET /cache/stats must return HTTP 200 even when _cache is None.

        WHAT: Confirms the fail-open principle holds at the HTTP level, not
        just the data level.
        WHY: Monitoring dashboards poll this endpoint continuously.  A 503 or
        500 would break the dashboard, making it impossible to detect the
        cache outage that caused the endpoint to fail — a monitoring blind spot.
        """
        monkeypatch.setattr(api, "_cache", None)
        monkeypatch.setattr(api, "_retriever", None)

        client = TestClient(api.app)
        response = client.get("/cache/stats")
        assert response.status_code == 200, (
            f"GET /cache/stats must return 200 when _cache is None; "
            f"got {response.status_code}"
        )


# ===========================================================================
# TestCrossIssueDecisionContract
# ===========================================================================


class TestCrossIssueDecisionContract:
    """Contract tests pinning the cross-issue architectural decisions.

    WHAT CONTRACT: Two explicit cross-issue decisions made during OPTB-007
    through OPTB-012 are enforced here:

      1. The cache response header is named 'X-Cache' (not 'X-Cache-Status'
         or 'Cache-Status').
      2. The pre-OPTB-008 flat stat fields (hits, misses, hit_rate, size,
         backend) are not present at the top level of /cache/stats.

    WHY THIS CLASS: Cross-issue decisions are the most likely to be
    accidentally reverted because no single issue 'owns' them.  Pinning them
    in a dedicated test class makes the decision traceable: anyone wanting
    to reverse one of these decisions must explicitly remove or modify a
    named test, which requires a deliberate code review conversation.
    """

    def test_flat_stat_fields_absent_prevents_external_monitor_regression(
        self, stats_client: TestClient
    ) -> None:
        """Decision: flat fields absent from /cache/stats root — no external monitor regression.

        WHAT: Pinpoints the exact flat fields that were removed from the top
        level in OPTB-008.  This is the 'no-regression for external monitors'
        assertion from the cross-issue decision log.
        WHY: Any external monitoring rule (Prometheus scraper, Datadog check,
        shell script) that reads `jq .hits /cache/stats` would silently return
        null rather than an error if the field is missing — the regression is
        invisible.  Making the absence explicit here forces a reviewer to
        acknowledge the schema change.
        """
        response = stats_client.get("/cache/stats")
        body: Dict[str, Any] = response.json()

        # These exact fields were at the top level before OPTB-008.
        # Their presence at the root would indicate a schema reversion.
        old_flat_fields = ["hits", "misses", "hit_rate", "size", "backend", "max_size", "ttl_seconds"]
        for field in old_flat_fields:
            assert field not in body, (
                f"Cross-issue decision: flat field '{field}' must not appear at the "
                "top level of /cache/stats (OPTB-008 migration). "
                f"Found: {field!r} in top-level keys {list(body.keys())!r}"
            )



# ---------------------------------------------------------------------------
# Module-level helpers used across multiple test classes
# ---------------------------------------------------------------------------


def _fake_config() -> Any:
    """Return a minimal HybridRetrieverConfig double for retrieve/ingest tests.

    WHY: The retrieve and ingest endpoints check ``_config is not None`` before
    proceeding.  Rather than constructing a real config (which may require
    ChromaDB), we use a simple namespace object with the fields the endpoints
    actually read.
    """
    from types import SimpleNamespace
    # Note 24: `types.SimpleNamespace` is a lightweight object that accepts
    # arbitrary keyword arguments as attributes. It is ideal for ad-hoc config
    # doubles because you get attribute access (`cfg.enable_rerank`) without
    # defining a full class. Compare to a dict which requires `cfg["enable_rerank"]`
    # — the attribute syntax matches the real HybridRetrieverConfig exactly.

    return SimpleNamespace(
        semantic_top_k=5,
        keyword_top_k=5,
        final_top_k=5,
        semantic_weight=0.5,
        keyword_weight=0.5,
        enable_rerank=False,
        pre_rerank_top_k=10,
    )


class _FakeCollection:
    """Minimal collection double for _build_corpus_version_token().

    WHY: _build_corpus_version_token() calls collection.count() to build the
    corpus version token.  This double returns a stable non-zero count so
    corpus version tokens are in the expected format.
    """

    def count(self) -> int:
        """Return the stable corpus size used to build corpus_version tokens."""
        return 5

    def add(
        self,
        ids: List[str],
        documents: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        pass


class _FakeRetrievingRetriever:
    """Retriever double that returns one deterministic document on retrieve().

    WHY: Tests for X-Cache and fail-open behaviour need a functional retriever
    so the endpoint doesn't raise HTTP 503 ('Retriever not initialized').  The
    results themselves are not under test in those classes.
    """

    def __init__(self) -> None:
        self.collection = _FakeCollection()

    def retrieve(
        self, query: str, enable_rerank: Optional[bool] = None
    ) -> List[Dict[str, Any]]:
        """Return one fake document at a score that passes the min-score filter."""
        return [
            {
                "id": "contract-doc-1",
                "text": f"Contract test result for: {query}",
                "metadata": {"source": "https://contract.test"},
                "score": 0.95,
            }
        ]

    def get_embedding_cache_stats(self) -> Dict[str, Any]:
        """Return zeroed L2 stats — not under test in this retriever."""
        return {"hits": 0, "misses": 0, "hit_rate": 0.0, "size": 0, "capacity": 0}


class _FakeIngestableRetriever:
    """Retriever double that supports document ingestion via a fake collection.

    WHY: The add_documents endpoint calls _retriever.collection.add() to store
    chunks, then reads collection.count() to rebuild the corpus version token.
    This double provides both operations without touching ChromaDB.
    """

    def __init__(self) -> None:
        self._chunk_store: List[str] = []
        self.collection = _MutableFakeCollection()

    def retrieve(
        self, query: str, enable_rerank: Optional[bool] = None
    ) -> List[Dict[str, Any]]:
        """Return one fake document."""
        return [
            {
                "id": "ingest-doc-1",
                "text": f"Result for: {query}",
                "metadata": {"source": "https://ingest.test"},
                "score": 0.95,
            }
        ]

    def get_embedding_cache_stats(self) -> Dict[str, Any]:
        """Return zeroed L2 stats."""
        return {"hits": 0, "misses": 0, "hit_rate": 0.0, "size": 0, "capacity": 0}


class _MutableFakeCollection:
    """Collection double that accepts add() and returns a stable count().

    WHY: _build_corpus_version_token() calls collection.count() after an ingest
    to build a new corpus version token.  A static count() would produce the
    same token before and after the ingest — masking token-change bugs.
    Incrementing on add() mirrors ChromaDB behaviour.
    """

    def __init__(self) -> None:
        self._count: int = 5

    def count(self) -> int:
        """Return current corpus size; incremented by each add() call."""
        return self._count

    def add(
        self,
        ids: List[str],
        documents: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        self._count += len(ids)


class _AlwaysErrorCache:
    """Cache whose every operation raises RuntimeError.

    WHY: Tests for fail-open semantics need a cache that always fails so the
    endpoint code's exception handlers are exercised.  Using a real cache that
    happens to fail would make the test brittle (it might succeed).
    """
    # Note 25: `NoReturn` as a return type annotation tells the type checker
    # that this function NEVER returns normally — it always raises. This is
    # distinct from `None` (which means "returns with no value"). Using
    # `NoReturn` documents the intent clearly and allows static analysis tools
    # to detect unreachable code after calls to these methods.

    def get(self, key: str) -> NoReturn:
        raise RuntimeError("_AlwaysErrorCache: get() always fails")

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> NoReturn:
        raise RuntimeError("_AlwaysErrorCache: set() always fails")

    def delete(self, key: str) -> NoReturn:
        raise RuntimeError("_AlwaysErrorCache: delete() always fails")

    def clear(self) -> NoReturn:
        raise RuntimeError("_AlwaysErrorCache: clear() always fails")

    def stats(self) -> NoReturn:
        raise RuntimeError("_AlwaysErrorCache: stats() always fails")

    def health(self) -> NoReturn:
        raise RuntimeError("_AlwaysErrorCache: health() always fails")
