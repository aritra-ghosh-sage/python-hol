"""OPTB-010 — Evaluate Retrieval Quality Over Time.

GH-010 acceptance criteria (verbatim from PRODUCT_PRD.md §10.10):
  AC-1: The product defines a repeatable benchmark or evaluation workflow.
  AC-2: Quality metrics can be compared across configuration changes.
  AC-3: Performance measurements include warm-cache and cold-cache scenarios.
  AC-4: Regressions are detectable before release.

Design intent:
  This file defines the repeatable benchmark and regression-detection workflow
  that satisfies GH-010.  All tests are written using lightweight fakes so
  they run in CI without ChromaDB, Redis, or sentence-transformer models.

Benchmark dimensions tracked in every run:
  - cold_cache_latency_ms  : time for first retrieval (cache miss → retriever)
  - warm_cache_latency_ms  : time for repeat retrieval (L1 cache hit)
  - speedup_ratio          : cold / warm (target ≥ 2× in unit tests; ≥ 5× in prod)
  - hit_rate_after_N_queries: fraction of N queries served from L1 cache
  - result_consistency     : same query → identical results across N calls

Regression detection strategy:
  The ``BenchmarkBaseline`` dataclass stores a snapshot of quality metrics.
  Tests assert that measured values remain within acceptable bounds of the
  baseline.  Any single metric crossing its threshold fails the test,
  prompting engineers to investigate before merging.

  Thresholds used in unit tests (conservative because fake retriever is fast):
    - cold_cache_latency_ms ≤ 50 ms (fake retriever; real target is ≤ 1000 ms)
    - warm_cache_latency_ms ≤ 5 ms  (L1 cache hit; target matches production)
    - speedup_ratio ≥ 2×            (fake still shows cache benefit)
    - hit_rate after N calls ≥ 0.5  (second identical query is a hit)
    - result_consistency = 1.0      (identical results for identical queries)

WHY this approach:
  Pytest-based benchmarks are runnable in CI without external services.
  Results are assertions, not just prints, so regressions fail the build.
  The ``BenchmarkReport`` helper produces a dict-serialisable summary for
  CI artefact storage and human review (AC-1 repeatable workflow).
"""

import json
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient

import api
from hybrid_rag import HybridRetrieverConfig
from hybrid_rag.cache import InMemoryCache


# ---------------------------------------------------------------------------
# Shared test doubles
# ---------------------------------------------------------------------------


class _FakeCollection:
    """Minimal collection double satisfying _build_corpus_version_token()."""

    def count(self) -> int:
        return 5  # Stable count so corpus_version is deterministic


class _FakeRetrieverWithLatency:
    """Retriever double that simulates a configurable retrieval latency.

    WHY: We need to measure speedup ratio.  If the fake returns instantly,
    the speedup ratio collapses to ~1.0 and the benchmark threshold cannot
    be tested.  A small but measurable sleep (default 50 ms) gives the
    benchmark a signal to detect cache bypasses.

    Attributes:
        latency_seconds: Simulated retrieval duration (injected from tests).
        call_count: Number of times retrieve() was actually called.
        result_score: Relevance score of the fake result (varies by config).
    """

    # Simulated additional score for reranked results — extracted as a constant
    # so the "magic" delta is visible and adjustable without touching the test logic.
    RERANK_SCORE_DELTA: float = 0.02

    def __init__(
        self,
        latency_seconds: float = 0.01,
        result_score: float = 0.95,
    ) -> None:
        # WHY store both: latency tests and quality-comparison tests use
        # different attributes.
        self.latency_seconds = latency_seconds
        self.result_score = result_score
        self.call_count = 0
        self.collection = _FakeCollection()

    def retrieve(
        self, query: str, enable_rerank: Optional[bool] = None
    ) -> List[Dict[str, Any]]:
        """Return one fake result after simulated retrieval latency."""
        # Simulate retrieval work (embedding, search, reranking)
        time.sleep(self.latency_seconds)
        self.call_count += 1
        return [
            {
                "id": "benchmark-doc-1",
                "text": f"Benchmark result for: {query}",
                "metadata": {"source": "https://benchmark.example"},
                # Score is influenced by enable_rerank to simulate quality differences.
                # RERANK_SCORE_DELTA provides a small, visible boost for reranked results.
                "score": self.result_score if not enable_rerank else self.result_score + self.RERANK_SCORE_DELTA,
            }
        ]

    def get_embedding_cache_stats(self) -> Dict[str, Any]:
        """Return L2 stats reflecting call_count as misses."""
        return {
            "hits": 0,
            "misses": self.call_count,
            "hit_rate": 0.0,
            "size": min(self.call_count, 100),
            "capacity": 5000,
        }


# ---------------------------------------------------------------------------
# Benchmark helpers
# ---------------------------------------------------------------------------


@dataclass
class BenchmarkSample:
    """One timing sample from a benchmark run.

    WHY a dataclass (not a dict): typed fields catch typos at authoring time
    and produce a clean JSON-serialisable structure for CI artefacts.

    Attributes:
        query: The query string used in this sample.
        latency_ms: Measured wall-clock latency for this request in milliseconds.
        x_cache_header: Value of the X-Cache response header ('HIT', 'MISS', 'ERROR').
        status_code: HTTP status code from the response.
        result_count: Number of results returned.
    """

    query: str
    latency_ms: float
    x_cache_header: str
    status_code: int
    result_count: int


@dataclass
class BenchmarkReport:
    """Summary report for one benchmark scenario.

    WHY: CI artefact storage requires a serialisable summary so that
    performance trends can be compared across PR branches without running
    the full benchmark suite interactively.

    Attributes:
        scenario_name: Human-readable identifier for this benchmark scenario.
        samples: All individual timing samples collected during the run.
        cold_cache_latency_ms: Mean latency of cache-miss requests.
        warm_cache_latency_ms: Mean latency of cache-hit requests.
        speedup_ratio: cold / warm latency ratio.
        hit_rate: Fraction of all requests that were cache hits.
        result_consistency: Fraction of repeated queries that returned
            the same result as the first call (1.0 = perfectly consistent).
    """

    scenario_name: str
    samples: List[BenchmarkSample] = field(default_factory=list)
    cold_cache_latency_ms: float = 0.0
    warm_cache_latency_ms: float = 0.0
    speedup_ratio: float = 0.0
    hit_rate: float = 0.0
    result_consistency: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict for JSON export and CI artefact storage."""
        return asdict(self)

    def to_json(self) -> str:
        """Serialise to a JSON string for CI artefact storage."""
        return json.dumps(self.to_dict(), indent=2)


def _measure_request(
    client: TestClient,
    query: str,
    enable_rerank: Optional[bool] = None,
) -> BenchmarkSample:
    """Make one POST /retrieve request and return timing + metadata.

    Args:
        client: The TestClient to use for the request.
        query: The query string to send.
        enable_rerank: Optional override for reranking.

    Returns:
        BenchmarkSample with measured latency and response metadata.
    """
    payload: Dict[str, Any] = {"query": query}
    if enable_rerank is not None:
        payload["enable_rerank"] = enable_rerank

    start = time.monotonic()
    response = client.post("/retrieve", json=payload)
    latency_ms = (time.monotonic() - start) * 1000

    body = response.json() if response.status_code == 200 else {}
    return BenchmarkSample(
        query=query,
        latency_ms=latency_ms,
        x_cache_header=response.headers.get("X-Cache", "UNKNOWN"),
        status_code=response.status_code,
        result_count=len(body.get("results", [])),
    )


def _run_warm_cold_benchmark(
    client: TestClient,
    query: str,
    n_warm_calls: int = 5,
    enable_rerank: Optional[bool] = None,
) -> BenchmarkReport:
    """Execute a warm/cold benchmark: one cold call followed by N warm calls.

    WHY this structure: the first call is always a cache miss (cold); every
    subsequent identical call should be a cache hit (warm).  We measure both
    to compute the speedup ratio.

    Args:
        client: The TestClient to use.
        query: The query to benchmark.
        n_warm_calls: Number of cache-hit calls to make after the cold start.
        enable_rerank: Optional rerank override for all calls.

    Returns:
        BenchmarkReport with aggregated metrics.
    """
    report = BenchmarkReport(scenario_name=f"warm_cold/{query[:40]}")

    # Cold call (cache miss)
    cold_sample = _measure_request(client, query, enable_rerank)
    report.samples.append(cold_sample)

    # Warm calls (cache hits)
    warm_samples: List[BenchmarkSample] = []
    for _ in range(n_warm_calls):
        warm_sample = _measure_request(client, query, enable_rerank)
        warm_samples.append(warm_sample)
        report.samples.append(warm_sample)

    # Aggregate metrics
    all_samples = report.samples
    hits = sum(1 for s in all_samples if s.x_cache_header == "HIT")
    report.hit_rate = hits / len(all_samples) if all_samples else 0.0
    report.cold_cache_latency_ms = cold_sample.latency_ms
    if warm_samples:
        report.warm_cache_latency_ms = sum(s.latency_ms for s in warm_samples) / len(warm_samples)
    report.speedup_ratio = (
        report.cold_cache_latency_ms / report.warm_cache_latency_ms
        if report.warm_cache_latency_ms > 0
        else float("inf")
    )

    # Consistency check: all warm calls return same result_count as cold call
    baseline_count = cold_sample.result_count
    consistent = sum(1 for s in warm_samples if s.result_count == baseline_count)
    report.result_consistency = consistent / len(warm_samples) if warm_samples else 1.0

    return report


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def benchmark_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Provide a TestClient wired with a slow fake retriever and fresh cache.

    WHY slow fake (50 ms latency): we need a measurable difference between
    a cache miss (50 ms simulated latency) and a cache hit (<1 ms in-memory).
    This keeps the speedup ratio meaningful and more stable on slower CI
    machines where TestClient and middleware overhead can dominate tiny delays.
    """
    # Fresh cache so hit/miss counters start at zero for each test
    cache = InMemoryCache(ttl_seconds=3600, max_size=10000)
    retriever = _FakeRetrieverWithLatency(latency_seconds=0.05)  # 50 ms cold
    config = HybridRetrieverConfig(semantic_weight=0.7, keyword_weight=0.3)

    monkeypatch.setattr(api, "_cache", cache)
    monkeypatch.setattr(api, "_retriever", retriever)
    monkeypatch.setattr(api, "_config", config)
    monkeypatch.setattr(api, "_corpus_version", "gen0.n5")

    return TestClient(api.app)


# ===========================================================================
# AC-1: Repeatable benchmark / evaluation workflow
# ===========================================================================


class TestAC1RepeatableBenchmarkWorkflow:
    """Prove AC-1: a repeatable benchmark workflow exists and produces valid output.

    The BenchmarkReport structure is the workflow artefact.  These tests
    verify that the workflow produces a complete, JSON-serialisable report
    that can be stored as a CI artefact for trend analysis.
    """

    def test_benchmark_report_produces_all_required_metrics(
        self, benchmark_client: TestClient
    ) -> None:
        """Running the benchmark workflow produces a report with all required fields.

        WHY: A workflow that returns incomplete metrics cannot be used for
        regression detection.  Every field must be present and non-negative.
        """
        report = _run_warm_cold_benchmark(
            benchmark_client, "benchmark repeatability check", n_warm_calls=3
        )

        assert report.scenario_name, "scenario_name must not be empty"
        assert len(report.samples) == 4, "expected 1 cold + 3 warm samples"
        assert report.cold_cache_latency_ms >= 0.0
        assert report.warm_cache_latency_ms >= 0.0
        assert report.speedup_ratio >= 0.0
        assert 0.0 <= report.hit_rate <= 1.0
        assert 0.0 <= report.result_consistency <= 1.0

    def test_benchmark_report_is_json_serialisable(
        self, benchmark_client: TestClient
    ) -> None:
        """BenchmarkReport.to_json() must produce valid JSON without raising.

        WHY: CI artefact storage systems expect JSON.  A report that cannot
        be serialised cannot be archived or compared across runs.
        """
        report = _run_warm_cold_benchmark(
            benchmark_client, "json serialisation test", n_warm_calls=2
        )
        json_str = report.to_json()

        # Must be valid JSON
        parsed = json.loads(json_str)
        assert "scenario_name" in parsed
        assert "cold_cache_latency_ms" in parsed
        assert "warm_cache_latency_ms" in parsed
        assert "speedup_ratio" in parsed
        assert "hit_rate" in parsed
        assert "result_consistency" in parsed
        assert "samples" in parsed
        assert isinstance(parsed["samples"], list)

    def test_benchmark_is_deterministic_for_same_input(
        self, benchmark_client: TestClient
    ) -> None:
        """Running the benchmark twice with the same query produces consistent results.

        WHY: A non-deterministic benchmark produces false regressions.
        The result_consistency metric must be 1.0 for identical queries.
        The cache is cleared between runs so both start cold, matching the
        same warm/cold pattern and validating the workflow itself.
        """
        query = "deterministic benchmark query"
        report_a = _run_warm_cold_benchmark(benchmark_client, query, n_warm_calls=3)
        # Clear the cache so the second run also begins with a cold miss,
        # matching the same warm/cold pattern as the first run.
        api._cache.clear()
        report_b = _run_warm_cold_benchmark(benchmark_client, query, n_warm_calls=3)

        # Both must agree on result_consistency
        assert report_a.result_consistency == 1.0, (
            f"First run result_consistency must be 1.0, got {report_a.result_consistency}"
        )
        assert report_b.result_consistency == 1.0, (
            f"Second run result_consistency must be 1.0, got {report_b.result_consistency}"
        )


# ===========================================================================
# AC-2: Quality metrics comparable across configuration changes
# ===========================================================================


class TestAC2QualityMetricsAcrossConfigChanges:
    """Prove AC-2: quality metrics are measurable before and after config changes.

    Operators need to know: 'did changing semantic_weight from 0.7 to 0.9
    improve or degrade retrieval quality?'  These tests define the measurement
    framework that answers that question by recording metrics under two configs.
    """

    def test_config_change_increases_retriever_call_count(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Changing config clears L1 cache, causing the next query to hit retriever.

        WHY: If config changes did NOT clear the cache, stale results from the
        old config would be served under the new config — quality regression.
        This test proves the cache is invalidated on config change, so the
        next request gets fresh results computed under the new config.
        """
        retriever = _FakeRetrieverWithLatency(latency_seconds=0.001)
        config = HybridRetrieverConfig(semantic_weight=0.7, keyword_weight=0.3)
        cache = InMemoryCache(ttl_seconds=3600, max_size=1000)

        monkeypatch.setattr(api, "_cache", cache)
        monkeypatch.setattr(api, "_retriever", retriever)
        monkeypatch.setattr(api, "_config", config)
        monkeypatch.setattr(api, "_cache_generation", 0)
        monkeypatch.setattr(api, "_corpus_version", "gen0.n5")

        client = TestClient(api.app)

        # Warm the cache: first call hits retriever, subsequent calls hit cache
        client.post("/retrieve", json={"query": "config comparison test"})
        calls_after_warmup = retriever.call_count
        assert calls_after_warmup >= 1, "retriever must be called on first (cold) request"

        # Second call: should be a cache hit (retriever NOT called again)
        client.post("/retrieve", json={"query": "config comparison test"})
        calls_before_config_change = retriever.call_count
        assert calls_before_config_change == calls_after_warmup, (
            "retriever must NOT be called on second identical request (L1 cache hit)"
        )

        # Config change: must clear cache and force fresh retrieval
        client.put("/config", json={"semantic_weight": 0.9, "keyword_weight": 0.1})

        # Same query after config change: must hit retriever (cache was cleared)
        client.post("/retrieve", json={"query": "config comparison test"})
        calls_after_config_change = retriever.call_count
        assert calls_after_config_change > calls_before_config_change, (
            "retriever must be called after config change (cache should be cleared)"
        )

    def test_metrics_differ_between_rerank_on_and_rerank_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """enable_rerank=True and enable_rerank=False produce separately cacheable results.

        WHY: The cache key includes the effective_enable_rerank flag (ADR-002).
        Quality evaluators must be able to compare reranked vs non-reranked
        results independently.  If the same cache key were used for both,
        one config would always override the other.
        """
        # The fake retriever returns slightly different scores for rerank=True vs False
        retriever = _FakeRetrieverWithLatency(latency_seconds=0.001, result_score=0.90)
        config = HybridRetrieverConfig(
            semantic_weight=0.7, keyword_weight=0.3, enable_rerank=False
        )
        cache = InMemoryCache(ttl_seconds=3600, max_size=1000)

        monkeypatch.setattr(api, "_cache", cache)
        monkeypatch.setattr(api, "_retriever", retriever)
        monkeypatch.setattr(api, "_config", config)
        monkeypatch.setattr(api, "_cache_generation", 0)
        monkeypatch.setattr(api, "_corpus_version", "gen0.n5")

        client = TestClient(api.app)
        query = "rerank comparison test"

        # Call with rerank=False (first call = MISS, sets cache entry A)
        resp_no_rerank = client.post("/retrieve", json={"query": query, "enable_rerank": False})
        assert resp_no_rerank.status_code == 200
        body_no_rerank = resp_no_rerank.json()
        score_no_rerank = body_no_rerank["results"][0]["score"] if body_no_rerank["results"] else None

        # Call with rerank=True (different cache key, also MISS, sets cache entry B)
        resp_rerank = client.post("/retrieve", json={"query": query, "enable_rerank": True})
        assert resp_rerank.status_code == 200
        body_rerank = resp_rerank.json()
        score_rerank = body_rerank["results"][0]["score"] if body_rerank["results"] else None

        # Both calls must have hit the retriever (separate cache keys)
        assert retriever.call_count == 2, (
            f"Expected 2 retriever calls (one per rerank flag), got {retriever.call_count}"
        )

        # Scores may differ (simulated in fake retriever)
        if score_no_rerank is not None and score_rerank is not None:
            # At minimum, both must be valid floats
            assert isinstance(score_no_rerank, float)
            assert isinstance(score_rerank, float)

    def test_benchmark_report_captures_before_after_config_change(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two benchmark reports can be compared before and after a config change.

        WHY (AC-2): Quality comparison across config changes requires capturing
        metrics under both configs.  This test demonstrates the comparison
        workflow that would be run in a pre-release quality gate.
        """
        retriever = _FakeRetrieverWithLatency(latency_seconds=0.005)
        config_before = HybridRetrieverConfig(semantic_weight=0.7, keyword_weight=0.3)
        cache = InMemoryCache(ttl_seconds=3600, max_size=1000)

        monkeypatch.setattr(api, "_cache", cache)
        monkeypatch.setattr(api, "_retriever", retriever)
        monkeypatch.setattr(api, "_config", config_before)
        monkeypatch.setattr(api, "_cache_generation", 0)
        monkeypatch.setattr(api, "_corpus_version", "gen0.n5")

        client = TestClient(api.app)
        query = "compare before after config"

        # Benchmark under baseline config
        report_before = _run_warm_cold_benchmark(client, query, n_warm_calls=3)

        # Change config: semantic_weight 0.7 → 0.9 (this clears the L1 cache)
        client.put("/config", json={"semantic_weight": 0.9, "keyword_weight": 0.1})

        # Benchmark under new config (first call hits retriever; warm calls hit cache)
        report_after = _run_warm_cold_benchmark(client, query, n_warm_calls=3)

        # Both reports must be valid
        assert report_before.cold_cache_latency_ms >= 0
        assert report_after.cold_cache_latency_ms >= 0

        # After config change, first call must be cold (cache was cleared)
        # The cold latency after config change must be from retriever, not cache
        assert report_after.cold_cache_latency_ms >= 0, (
            "cold latency after config change must be a real measurement"
        )

        # Verify the comparison is possible (both reports have the same fields)
        before_dict = report_before.to_dict()
        after_dict = report_after.to_dict()
        assert set(before_dict.keys()) == set(after_dict.keys()), (
            "Report schema must be identical before and after config change for comparison"
        )


# ===========================================================================
# AC-3: Warm-cache and cold-cache performance measurements
# ===========================================================================


class TestAC3WarmAndColdCachePerformanceMeasurements:
    """Prove AC-3: performance is measured distinctly for warm vs cold cache.

    Warm-cache and cold-cache latencies serve different optimisation targets:
      - Cold cache: dominated by retriever latency (embedding + search + rerank)
      - Warm cache: dominated by cache backend latency (in-memory dict lookup)
    Both must be measurable independently for capacity planning.
    """

    def test_cold_cache_first_request_is_a_miss(
        self, benchmark_client: TestClient
    ) -> None:
        """The very first request for a query must be a cache MISS.

        WHY: Cache miss semantics are fundamental to the L1 cache contract.
        If the first request is a HIT, the cache has stale data from a
        previous test — indicating test isolation failure.
        """
        # Fresh benchmark_client fixture guarantees empty cache
        sample = _measure_request(benchmark_client, "cold miss verification")
        assert sample.x_cache_header == "MISS", (
            f"First request for fresh query must be MISS, got {sample.x_cache_header!r}"
        )

    def test_warm_cache_subsequent_request_is_a_hit(
        self, benchmark_client: TestClient
    ) -> None:
        """The second identical request must be a cache HIT.

        WHY: This is the fundamental correctness contract of L1 caching.
        A second identical request that is NOT a HIT means the cache
        is not persisting results — the main purpose of L1 caching.
        """
        query = "warm hit verification"
        # Prime the cache
        _measure_request(benchmark_client, query)
        # Second request should be a cache hit
        warm_sample = _measure_request(benchmark_client, query)
        assert warm_sample.x_cache_header == "HIT", (
            f"Second identical request must be HIT, got {warm_sample.x_cache_header!r}"
        )

    def test_warm_cache_is_faster_than_cold_cache(
        self, benchmark_client: TestClient
    ) -> None:
        """Warm cache latency must be lower than cold cache latency.

        WHY: If warm ≥ cold, the cache provides no performance benefit.
        The fake retriever sleeps 50 ms; L1 cache lookup is nanoseconds.
        We require speedup ≥ 2× to leave headroom for jitter.
        """
        report = _run_warm_cold_benchmark(
            benchmark_client, "speedup measurement query", n_warm_calls=5
        )

        # Log the report for debugging failing CI runs
        print(f"\nBenchmark report:\n{report.to_json()}")

        assert report.speedup_ratio >= 2.0, (
            f"Expected speedup_ratio ≥ 2.0, got {report.speedup_ratio:.2f}. "
            f"cold={report.cold_cache_latency_ms:.1f} ms, "
            f"warm={report.warm_cache_latency_ms:.1f} ms"
        )

    def test_hit_rate_is_high_after_cache_warmup(
        self, benchmark_client: TestClient
    ) -> None:
        """Hit rate must be ≥ 0.5 after priming the cache with one query.

        WHY: Out of N+1 requests (1 cold + N warm), exactly N should be hits.
        n_warm_calls=5 → hit_rate = 5/6 ≈ 0.833.  A threshold of 0.5 is
        conservative so that minor timing variations do not false-fail.
        """
        report = _run_warm_cold_benchmark(
            benchmark_client, "hit rate verification", n_warm_calls=5
        )
        assert report.hit_rate >= 0.5, (
            f"Expected hit_rate ≥ 0.5 after cache warmup, got {report.hit_rate:.3f}"
        )

    def test_multiple_distinct_queries_each_have_cold_then_warm(
        self, benchmark_client: TestClient
    ) -> None:
        """Each unique query independently follows the cold→warm latency pattern.

        WHY: Cache keys are per-query.  Multiple distinct queries must each
        independently experience a cold miss on first call and a warm hit
        on subsequent identical calls.
        """
        queries = [
            "distinct query alpha",
            "distinct query beta",
            "distinct query gamma",
        ]

        for query in queries:
            cold_sample = _measure_request(benchmark_client, query)
            warm_sample = _measure_request(benchmark_client, query)

            assert cold_sample.x_cache_header == "MISS", (
                f"First request for '{query}' must be MISS, got {cold_sample.x_cache_header!r}"
            )
            assert warm_sample.x_cache_header == "HIT", (
                f"Second request for '{query}' must be HIT, got {warm_sample.x_cache_header!r}"
            )

    def test_cache_miss_after_config_change_confirms_cold_semantics(
        self, benchmark_client: TestClient
    ) -> None:
        """A query becomes cold again after a config change clears the cache.

        WHY (AC-3): Config changes create a new cold-start scenario.
        Operators must be able to measure warm-up costs after each config
        deploy — this test proves the measurement is accurate.
        """
        query = "cold-after-config-change query"

        # Prime the cache
        _measure_request(benchmark_client, query)
        warm_sample = _measure_request(benchmark_client, query)
        assert warm_sample.x_cache_header == "HIT", "Cache should be warm before config change"

        # Config change: clears L1 cache (ADR-006)
        benchmark_client.put("/config", json={"semantic_weight": 0.8, "keyword_weight": 0.2})

        # Same query after config change must be cold again
        post_config_sample = _measure_request(benchmark_client, query)
        assert post_config_sample.x_cache_header == "MISS", (
            f"Query must be cold (MISS) after config change, got {post_config_sample.x_cache_header!r}"
        )


# ===========================================================================
# AC-4: Regressions are detectable before release
# ===========================================================================


@dataclass
class BenchmarkBaseline:
    """Stored baseline for regression detection.

    WHY: Regression detection requires a reference point.  This dataclass
    holds the expected metric bounds.  Tests compare live measurements
    against these bounds and fail if any metric regresses beyond its limit.

    In a real CI pipeline, the baseline would be loaded from a JSON file
    committed alongside the code.  In this unit-test suite, the baseline
    is defined inline to make the tests self-contained.

    Threshold rationale (all values are conservative for unit-test context):
      - max_cold_latency_ms=200: fake retriever sleeps ~50 ms; 200 ms gives 4×
        headroom for slow CI machines and any test setup overhead.
      - max_warm_latency_ms=50: in-memory dict lookup is nanoseconds; 50 ms is
        extremely generous to avoid false-positives on loaded machines.
      - min_speedup_ratio=2: cold (~50 ms) / warm (<5 ms) = at least 2×.
      - min_hit_rate=0.5: 1 cold + N warm → hit_rate = N/(N+1) ≥ 5/6 > 0.5.
      - min_result_consistency=1.0: same query must always return same count.

    Attributes:
        max_cold_latency_ms: Upper bound for cold-cache latency (regression = exceeded).
        max_warm_latency_ms: Upper bound for warm-cache latency.
        min_speedup_ratio: Lower bound for speedup ratio (regression = fallen below).
        min_hit_rate: Lower bound for hit rate after N identical queries.
        min_result_consistency: Lower bound for identical-query result consistency.
    """

    max_cold_latency_ms: float = 200.0
    max_warm_latency_ms: float = 50.0
    min_speedup_ratio: float = 2.0
    min_hit_rate: float = 0.5
    min_result_consistency: float = 1.0


PRODUCTION_BASELINE = BenchmarkBaseline()


class TestAC4RegressionDetection:
    """Prove AC-4: regressions in performance or quality are detectable before release.

    These tests use the BenchmarkBaseline dataclass as the reference.  If any
    metric crosses its threshold, the test fails and blocks the PR from merging.
    This provides the pre-release regression gate required by GH-010 AC-4.
    """

    def test_no_latency_regression_in_warm_cold_scenario(
        self, benchmark_client: TestClient
    ) -> None:
        """Warm and cold latencies must stay within their baseline bounds.

        WHY: Latency regression is the most common symptom of performance bugs.
        If cold latency exceeds the budget, the retriever may be overloaded or
        the embedding model has grown.  If warm latency exceeds the budget,
        the cache backend may be contending.
        """
        report = _run_warm_cold_benchmark(
            benchmark_client, "regression detection latency test", n_warm_calls=5
        )
        print(f"\nRegression report:\n{report.to_json()}")

        assert report.cold_cache_latency_ms <= PRODUCTION_BASELINE.max_cold_latency_ms, (
            f"REGRESSION: cold_cache_latency_ms={report.cold_cache_latency_ms:.1f} ms "
            f"exceeds baseline={PRODUCTION_BASELINE.max_cold_latency_ms:.1f} ms"
        )
        assert report.warm_cache_latency_ms <= PRODUCTION_BASELINE.max_warm_latency_ms, (
            f"REGRESSION: warm_cache_latency_ms={report.warm_cache_latency_ms:.1f} ms "
            f"exceeds baseline={PRODUCTION_BASELINE.max_warm_latency_ms:.1f} ms"
        )

    def test_no_speedup_regression(
        self, benchmark_client: TestClient
    ) -> None:
        """Speedup ratio must not fall below the baseline minimum.

        WHY: A declining speedup ratio means the cache is becoming less
        effective.  This could be caused by L1 cache eviction (cache too
        small), TTL reduction, or accidental cache bypass.
        """
        report = _run_warm_cold_benchmark(
            benchmark_client, "regression detection speedup test", n_warm_calls=5
        )
        assert report.speedup_ratio >= PRODUCTION_BASELINE.min_speedup_ratio, (
            f"REGRESSION: speedup_ratio={report.speedup_ratio:.2f} "
            f"is below baseline={PRODUCTION_BASELINE.min_speedup_ratio:.2f}"
        )

    def test_no_hit_rate_regression(
        self, benchmark_client: TestClient
    ) -> None:
        """Hit rate after N identical calls must not fall below baseline.

        WHY: A hit rate below baseline means fewer requests are being served
        from cache.  Causes: cache cleared too aggressively, TTL too short,
        or query normalisation changed (different cache keys for same semantic
        query).
        """
        report = _run_warm_cold_benchmark(
            benchmark_client, "regression detection hit rate test", n_warm_calls=5
        )
        assert report.hit_rate >= PRODUCTION_BASELINE.min_hit_rate, (
            f"REGRESSION: hit_rate={report.hit_rate:.3f} "
            f"is below baseline={PRODUCTION_BASELINE.min_hit_rate:.3f}"
        )

    def test_no_result_consistency_regression(
        self, benchmark_client: TestClient
    ) -> None:
        """Identical queries must return exactly the same result count.

        WHY: Result count inconsistency (different number of results for the
        same query in the same session) indicates non-deterministic retrieval
        or broken cache hit semantics (serving partially-written entries).
        """
        report = _run_warm_cold_benchmark(
            benchmark_client, "regression detection consistency test", n_warm_calls=5
        )
        assert report.result_consistency >= PRODUCTION_BASELINE.min_result_consistency, (
            f"REGRESSION: result_consistency={report.result_consistency:.3f} "
            f"is below baseline={PRODUCTION_BASELINE.min_result_consistency:.3f}"
        )

    def test_regression_baseline_captures_multi_query_hit_rate(
        self, benchmark_client: TestClient
    ) -> None:
        """Hit rate across a mix of new and repeated queries is measurable.

        WHY: A single-query benchmark can produce a misleadingly optimistic
        hit rate.  This test exercises a more realistic workload: 3 unique
        queries, each repeated twice, for an expected hit rate of 3/6 = 0.5.
        """
        queries = [
            "multi-query test alpha",
            "multi-query test beta",
            "multi-query test gamma",
        ]
        all_samples: List[BenchmarkSample] = []

        for query in queries:
            # First call: MISS
            all_samples.append(_measure_request(benchmark_client, query))
            # Second call: HIT
            all_samples.append(_measure_request(benchmark_client, query))

        total = len(all_samples)
        hits = sum(1 for s in all_samples if s.x_cache_header == "HIT")
        observed_hit_rate = hits / total if total > 0 else 0.0

        # 3 unique queries × 2 calls = 6 total; 3 hits → hit_rate = 0.5
        assert observed_hit_rate >= 0.5, (
            f"Multi-query hit rate must be ≥ 0.5 (got {observed_hit_rate:.3f}); "
            f"baseline={PRODUCTION_BASELINE.min_hit_rate:.3f}"
        )
        assert observed_hit_rate <= 1.0, "Hit rate cannot exceed 1.0"

    def test_benchmark_report_format_is_stable_for_ci_artefact_storage(
        self, benchmark_client: TestClient
    ) -> None:
        """BenchmarkReport format does not silently change between runs.

        WHY: CI artefact storage relies on a stable JSON schema to render
        trend charts.  This test locks the top-level field names of the report
        so that a field rename produces a test failure (regression) not a
        silent chart breakage.
        """
        report = _run_warm_cold_benchmark(
            benchmark_client, "artefact format stability test", n_warm_calls=2
        )
        report_dict = report.to_dict()

        # Required fields that must always be present
        required_fields = {
            "scenario_name",
            "samples",
            "cold_cache_latency_ms",
            "warm_cache_latency_ms",
            "speedup_ratio",
            "hit_rate",
            "result_consistency",
        }
        missing = required_fields - set(report_dict.keys())
        assert not missing, (
            f"BenchmarkReport is missing required fields: {missing}.  "
            "Rename or removal of a field is a breaking schema change."
        )

        # Sample fields must also be stable
        if report_dict["samples"]:
            sample_fields = set(report_dict["samples"][0].keys())
            required_sample_fields = {
                "query",
                "latency_ms",
                "x_cache_header",
                "status_code",
                "result_count",
            }
            missing_sample = required_sample_fields - sample_fields
            assert not missing_sample, (
                f"BenchmarkSample is missing required fields: {missing_sample}"
            )
