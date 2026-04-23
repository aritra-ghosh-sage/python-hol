# T03 Decision: WS Observability and Cache-Status Contract

## Status

**ACCEPTED** — Contract locked. Unblocks T04, T06, T08.

---

## Context

The Hybrid RAG API exposes two transport paths for document retrieval:

- **HTTP REST** (`POST /retrieve`) — passes through `QueryCacheMiddleware`, which
  caches full responses and exposes cache state via the `X-Cache: HIT|MISS|ERROR`
  response header.
- **WebSocket** (`/ws/chat`) — bypasses `QueryCacheMiddleware`; retrieval is served
  through the shared `_shared_retrieve_documents` facade, which maintains its own
  retrieval-layer cache (`shared-retrieve:*` key space).

Before T03, WS clients had **no way to observe cache state** in the message payload.
Cache activity was visible only in server logs (`cache.retrieval_hit` /
`cache.retrieval_miss`) and in the aggregate `/cache/stats` endpoint.

This created two risks:

- **RSK-001 (Observability split):** HTTP and WS paths emit different telemetry
  event names (`cache.http_*` vs `cache.retrieval_*`). Without a documented
  contract, dashboard migrations could accidentally conflate or drop WS events.
- **RSK-002 (WS cache-status visibility):** After any future HTTP endpoint removal
  or routing change, WS clients would have no per-message signal to verify cache
  behavior during regression testing.

---

## Decision

**Chosen contract: payload field.**

The `WsResultsMessage` schema is extended with a `cache_status` field of type
`Literal["HIT", "MISS", "ERROR"]`:

```json
{
  "type": "results",
  "query": "...",
  "results": [...],
  "total_results": 1,
  "cache_status": "HIT"
}
```

`cache_status` reflects the **retrieval-layer** cache outcome (from
`_shared_retrieve_documents`), not the HTTP middleware layer, because WebSocket
traffic never passes through `QueryCacheMiddleware`.

---

## Options Considered

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **Payload field** (chosen) | Per-message, client-verifiable, no extra round-trip | Adds one field to message schema | ✅ Adopted |
| Status event | Separate `{"type": "cache_event", ...}` message before results | Clients must handle extra message type; ordering sensitive | ❌ Rejected — more complex, no incremental benefit |
| Logs-only | No schema change | Clients cannot verify cache state; insufficient for RSK-002 | ❌ Rejected — fails acceptance criterion "clients can verify cache state" |

---

## Rationale

1. **Client visibility (RSK-002):** A payload field gives WS clients the same
   per-request cache signal that REST clients get via `X-Cache`. This is the
   only option that satisfies "clients can verify cache state post-endpoint
   removal" without an extra server round-trip.

2. **Minimal schema impact:** A single optional field with a default of `"MISS"`
   is backward-compatible with existing clients. Clients that do not read
   `cache_status` are unaffected.

3. **Layer clarity:** The field carries the *retrieval-layer* status
   (`cache.retrieval_*`), not the HTTP-middleware status (`cache.http_*`).
   This distinction is documented in the field description and prevents
   consumers from misinterpreting WS hits as HTTP middleware hits.

4. **Structured telemetry alignment (RSK-001):** Both the HTTP and WS paths now
   have explicit, named telemetry events defined in
   `hybrid_rag.constants.CACHE_TELEMETRY_LABELS`. Dashboard queries can reference
   these constants rather than ad-hoc string literals.

---

## Contract Specification

### WsResultsMessage schema (after T03)

```python
class WsResultsMessage(BaseModel):
    type: Literal["results"] = "results"
    query: str
    results: List[DocumentResult]
    total_results: int
    cache_status: Literal["HIT", "MISS", "ERROR"] = "MISS"
```

### Semantics

| Value | Meaning |
|---|---|
| `HIT` | Result was served from the shared retrieval cache (`shared-retrieve:*`). The underlying retriever was NOT invoked. |
| `MISS` | No valid cached entry was found; the retriever was invoked and the result was written to the retrieval cache. |
| `ERROR` | A cache read fault occurred (e.g., Redis timeout); the retriever was invoked as a fail-open fallback. |

### Source of truth

`cache_status` is populated by `_shared_retrieve_documents` via the
`_out_cache_status` out-parameter. If `_out_cache_status` is empty (e.g., when
`_cache` is `None` at startup), the default `"MISS"` is used.

---

## Telemetry Label Alignment (RSK-001)

All cache telemetry event names are now defined in
`hybrid_rag/constants.py::CACHE_TELEMETRY_LABELS` and imported by both
`api.py` and `api_middleware.py`:

```python
CACHE_TELEMETRY_LABELS = {
    "http_hit":              "cache.http_hit",
    "http_miss":             "cache.http_miss",
    "retrieval_hit":         "cache.retrieval_hit",
    "retrieval_miss":        "cache.retrieval_miss",
    "retrieval_error":       "cache.retrieval_error",
    "fallback_activated":    "cache.fallback_activated",
    "fallback_deactivated":  "cache.fallback_deactivated",
}
```

### Dashboard migration path

| Old log pattern (ad-hoc string) | New constant key | Structured log value |
|---|---|---|
| `"cache.http_hit"` | `http_hit` | `cache.http_hit` |
| `"cache.http_miss"` | `http_miss` | `cache.http_miss` |
| `"cache.retrieval_hit"` | `retrieval_hit` | `cache.retrieval_hit` |
| `"cache.retrieval_miss"` | `retrieval_miss` | `cache.retrieval_miss` |
| `"cache.retrieval_error"` | `retrieval_error` | `cache.retrieval_error` |
| `"cache.fallback_activated"` | `fallback_activated` | `cache.fallback_activated` |
| `"cache.fallback_deactivated"` | `fallback_deactivated` | `cache.fallback_deactivated` |

**String values are unchanged** — existing Grafana/Kibana dashboard queries
(`grep cache.http_hit`) continue to work without modification. The change
prevents future regressions where a string rename would silently break alert
rules.

### Observability split (HTTP vs WS)

The HTTP and WS paths intentionally emit different label prefixes:

- HTTP middleware → `cache.http_*` (QueryCacheMiddleware, key space `cache:*`)
- WS/shared retrieval → `cache.retrieval_*` (_shared_retrieve_documents, key space `shared-retrieve:*`)

This split is **by design** and must be preserved. Alert rules that tally total
cache hits must SUM both namespaces; rules scoped to one transport should filter
on the prefix.

---

## Contract Implications for Clients

1. **No breaking change.** The `cache_status` field has a default value of
   `"MISS"`, so existing clients that deserialize `WsResultsMessage` without the
   new field will simply receive the default.

2. **New capability.** Clients can now verify cache behavior per-message without
   polling `/cache/stats`. This is sufficient for regression testing and
   observability dashboards.

3. **WS ≠ HTTP cache layer.** `cache_status: "HIT"` on a WS message means the
   result came from the retrieval-layer cache (`shared-retrieve:*`). It does NOT
   imply that the HTTP middleware cache was hit. Clients that mix REST and WS
   calls will see both layers, but each message only reports its own layer.

4. **Aggregate stats.** `/cache/stats` continues to report aggregate backend
   counters. Both HTTP middleware lookups and WS/shared-facade lookups increment
   the same backend counters, so WS cache activity IS visible in `/cache/stats`.

---

## Test Coverage

| Test | Coverage |
|---|---|
| `test_b1_observability_split_http_vs_ws_events` | HTTP emits `cache.http_*`; WS emits `cache.retrieval_*` |
| `test_b3_http_and_ws_both_expose_cache_status_in_their_respective_contracts` | REST `X-Cache` header + WS `cache_status` field both present |
| `test_c1_ws_cache_hit_reflected_in_payload_and_log` | WS HIT: payload `cache_status=HIT` + `cache.retrieval_hit` log |
| `test_c2_ws_cache_miss_reflected_in_payload_and_log` | WS MISS: payload `cache_status=MISS` + `cache.retrieval_miss` log |
| `test_c3_ws_cache_invalidation_shows_miss_after_config_update` | Post-invalidation WS query shows MISS, not stale HIT |

All tests are in `tests/test_ws_http_middleware_tradeoffs_e2e.py`.

---

## Related

- Depends on: #17
- Unblocks: T04, T06, T08
- Risks mitigated: RSK-001 (Observability split), RSK-002 (WS cache-status visibility)
