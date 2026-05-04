"""Cache statistics endpoint."""

import logging
from datetime import datetime, timezone

import api
from api import (
    BackendHealthStats,
    L1QueryCacheStats,
    L2EmbeddingCacheStats,
    LayeredCacheStatsResponse,
)
from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/cache/stats",
    response_model=LayeredCacheStatsResponse,
    tags=["Cache"],
    summary="Get layered cache statistics",
)
async def get_cache_stats() -> LayeredCacheStatsResponse:
    """Get layered cache statistics for monitoring and debugging.

    Returns a three-section response covering L1 query-response cache metrics,
    L2 embedding LRU cache metrics, and backend connectivity health.

    Implements fail-open principle: always returns HTTP 200 even when
    the cache backend is unavailable or the retriever is not initialized.
    """
    _zeroed_l1 = L1QueryCacheStats(
        backend="none",
        hits=0,
        misses=0,
        hit_rate=0.0,
        size=0,
        max_size=0,
        ttl_seconds=0,
        corpus_version=api._corpus_version,
    )
    _zeroed_l2 = L2EmbeddingCacheStats(
        hits=0, misses=0, hit_rate=0.0, size=0, capacity=0
    )
    _degraded_health = BackendHealthStats(
        connected=False,
        latency_ms=None,
        fallback_active=True,
        error=None,
    )

    try:
        if api._cache is None:
            l1 = _zeroed_l1
            backend_health = _degraded_health
        else:
            try:
                raw = api.lazy_cache.stats()
                hits = int(raw.get("hits", 0))
                misses = int(raw.get("misses", 0))
                total = hits + misses
                hit_rate = (hits / total) if total > 0 else 0.0

                l1 = L1QueryCacheStats(
                    backend=str(raw.get("backend", "unknown")),
                    hits=hits,
                    misses=misses,
                    hit_rate=hit_rate,
                    size=int(raw.get("size", 0) or 0),
                    max_size=int(raw.get("max_size", 0) or 0),
                    ttl_seconds=int(raw.get("ttl_seconds", 0) or 0),
                    corpus_version=api._corpus_version,
                )
                logger.debug(
                    "L1 stats: backend=%s hits=%d misses=%d hit_rate=%.2f corpus_version=%s",
                    l1.backend,
                    l1.hits,
                    l1.misses,
                    l1.hit_rate,
                    l1.corpus_version,
                )
            except Exception as l1_err:
                logger.warning("Failed to read L1 cache stats: %s", l1_err)
                l1 = _zeroed_l1

            try:
                raw_health = api.lazy_cache.health()
                backend_health = BackendHealthStats(
                    connected=bool(raw_health.get("connected", False)),
                    latency_ms=raw_health.get("latency_ms"),
                    fallback_active=bool(raw_health.get("fallback_active", False)),
                    error=raw_health.get("error"),
                )
            except Exception as health_err:
                logger.warning("Failed to read backend health: %s", health_err)
                backend_health = _degraded_health

            api._log_fallback_transition(backend_health.fallback_active)

        if api._retriever is None:
            l2 = _zeroed_l2
        else:
            try:
                raw_l2 = api._retriever.get_embedding_cache_stats()
                l2_hits = int(raw_l2.get("hits", 0))
                l2_misses = int(raw_l2.get("misses", 0))
                l2_total = l2_hits + l2_misses
                l2_hit_rate = (l2_hits / l2_total) if l2_total > 0 else 0.0
                l2 = L2EmbeddingCacheStats(
                    hits=l2_hits,
                    misses=l2_misses,
                    hit_rate=l2_hit_rate,
                    size=int(raw_l2.get("size", 0)),
                    capacity=int(raw_l2.get("capacity", 0)),
                )
                logger.debug(
                    "L2 stats: hits=%d misses=%d hit_rate=%.2f size=%d/%d",
                    l2.hits,
                    l2.misses,
                    l2.hit_rate,
                    l2.size,
                    l2.capacity,
                )
            except Exception as l2_err:
                logger.warning("Failed to read L2 embedding cache stats: %s", l2_err)
                l2 = _zeroed_l2

        return LayeredCacheStatsResponse(
            l1_query_cache=l1,
            l2_embedding_cache=l2,
            backend_health=backend_health,
            timestamp=datetime.now(timezone.utc),
        )

    except Exception as outer_err:
        logger.warning("Unexpected error building cache stats response: %s", outer_err)
        return LayeredCacheStatsResponse(
            l1_query_cache=_zeroed_l1,
            l2_embedding_cache=_zeroed_l2,
            backend_health=_degraded_health,
            timestamp=datetime.now(timezone.utc),
        )
