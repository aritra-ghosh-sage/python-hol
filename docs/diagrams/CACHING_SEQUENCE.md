# Hybrid RAG Caching System - Sequence Diagram

**Document Version:** 1.1
**Last Updated:** 2026-04-24

---

## 0. Unified Cache Sequence Flow

> Mirrors [`cache-sequence-flow.svg`](./cache-sequence-flow.svg) exactly — both HIT and MISS branches in a single diagram. Actor colours match the SVG palette.

```mermaid
%%{init: {
  "theme": "base",
  "themeVariables": {
    "background":        "#ffffff",
    "primaryColor":      "#f0fdf4",
    "primaryBorderColor":"#4ade80",
    "primaryTextColor":  "#1e293b",
    "secondaryColor":    "#f5f3ff",
    "secondaryBorderColor":"#a78bfa",
    "tertiaryColor":     "#fef2f2",
    "tertiaryBorderColor":"#f87171",
    "noteBkgColor":      "#fffde7",
    "noteBorderColor":   "#f9a825",
    "noteTextColor":     "#b45309",
    "sequenceNumberColor":"#ffffff",
    "actorBkg":          "#ffffff",
    "actorBorder":       "#94a3b8",
    "actorTextColor":    "#1e293b",
    "actorLineColor":    "#999999",
    "signalColor":       "#334155",
    "signalTextColor":   "#334155",
    "loopTextColor":     "#475569",
    "labelBoxBkgColor":  "#fffde7",
    "labelBoxBorderColor":"#f9a825",
    "labelTextColor":    "#b45309",
    "activationBorderColor":"#64748b",
    "activationBkgColor":"#f1f5f9"
  }
}}%%
sequenceDiagram
    %% Actor colour hints via classDef are not supported in sequenceDiagram;
    %% colours above match the SVG palette as closely as Mermaid allows.
    %%
    %% SVG actor → colour
    %%  User/Browser             stroke rgb(232,121,249)  fill rgb(253,244,255)
    %%  WS /ws/chat              stroke rgb(45,212,191)   fill rgb(240,253,250)
    %%  _shared_retrieve_docs    stroke rgb(74,222,128)   fill rgb(240,253,244)
    %%  LazyCache/CacheBackend   stroke rgb(167,139,250)  fill rgb(245,243,255)
    %%  HybridRetriever          stroke rgb(248,113,113)  fill rgb(254,242,242)
    %%  L2 Embedding LRU         stroke rgb(250,204,21)   fill rgb(254,252,232)
    %%  ChromaDB (persistent)    stroke rgb(129,140,248)  fill rgb(238,242,255)

    actor  U   as User/Browser
    participant WS  as WS /ws/chat
    participant SR  as _shared_retrieve_documents
    participant CB  as LazyCache / CacheBackend
    participant R   as HybridRetriever
    participant L2  as L2 Embedding LRU
    participant V   as ChromaDB (persistent)

    U->>WS: send_json {query, enable_rerank}
    WS->>WS: validate, generate correlation_id
    WS-->>U: {type: "status"}
    WS->>SR: _shared_retrieve_documents(query, ...)
    SR->>SR: normalize, build cache_key (SHA-256)
    SR->>CB: lazy_cache.get(cache_key)

    Note over SR,CB: Cache HIT path
    CB-->>SR: cached results (HIT)
    SR->>SR: _out_cache_status → "HIT"
    SR-->>WS: return results
    WS-->>U: {type:"results", cache_status:"HIT"}

    Note over SR,CB: Cache MISS path
    CB-->>SR: None (MISS)
    SR->>SR: _out_cache_status → "MISS"
    SR->>R: retrieve(query, enable_rerank)
    R->>L2: _get_or_encode_embedding(query)
    L2->>L2: SHA-256 key lookup
    L2->>V: s11 encode via SentenceTransformer
    V-->>L2: embedding vector
    L2-->>R: embedding (cached in L2)
    R->>V: ChromaDB.query(embedding, top_k)
    V-->>R: semantic results
    R->>R: BM25 keyword search + score fusion
    R->>R: s12 cross-encoder rerank
    R->>R: source deduplication
    R-->>SR: return results
    SR->>CB: lazy_cache.set(cache_key, results)
    SR-->>WS: return results
    WS-->>U: {type:"results", cache_status:"MISS"}
```

---

## 1. WebSocket Query — Cache Hit

```mermaid
sequenceDiagram
    actor Client as WS Client
    participant WS as websocket_chat<br/>(api.py)
    participant SRD as _shared_retrieve_documents<br/>(api.py)
    participant LC as LazyCache<br/>(lazy_cache wrapper)
    participant CB as CacheBackend<br/>(InMemory | Redis)

    Client->>WS: send_json {query, enable_rerank}
    WS->>WS: validate query (1–500 chars)
    WS-->>Client: {type: "status", message: "Retrieving documents..."}

    WS->>WS: generate ws_correlation_id (UUID)
    WS->>SRD: _shared_retrieve_documents(query, enable_rerank,<br/>correlation_id, _out_cache_status=[])

    SRD->>SRD: normalize query (strip whitespace)
    SRD->>SRD: compute config_fingerprint (SHA-256)
    SRD->>SRD: build shared_identity {query, enable_rerank,<br/>config_fingerprint, corpus_version}
    SRD->>SRD: compute cache_key = SHA-256(shared_identity)

    SRD->>LC: get(cache_key)
    LC->>CB: get(cache_key)
    CB-->>LC: cached results (list)
    LC-->>SRD: cached results

    SRD->>SRD: log cache.retrieval_hit (correlation_id, corpus_version)
    SRD->>SRD: _out_cache_status.append("HIT")
    SRD-->>WS: cached results

    WS->>WS: filter results (score ≥ 0.80)
    WS-->>Client: {type: "results", results, total_results,<br/>cache_status: "HIT"}
```

---

## 2. WebSocket Query — Cache Miss (full retrieval pipeline)

```mermaid
sequenceDiagram
    actor Client as WS Client
    participant WS as websocket_chat<br/>(api.py)
    participant SRD as _shared_retrieve_documents<br/>(api.py)
    participant LC as LazyCache
    participant CB as CacheBackend<br/>(InMemory | Redis)
    participant RET as HybridRetriever<br/>(retriever.py)
    participant L2 as L2 Embedding Cache<br/>(LRUCache, 5000 cap)
    participant ENC as SentenceTransformer<br/>(encoder)
    participant VDB as ChromaDB<br/>(persistent vector store)

    Client->>WS: send_json {query, enable_rerank}
    WS-->>Client: {type: "status", message: "Retrieving documents..."}

    WS->>SRD: _shared_retrieve_documents(query, ...)

    SRD->>SRD: compute cache_key
    SRD->>LC: get(cache_key)
    LC->>CB: get(cache_key)
    CB-->>LC: None (miss)
    LC-->>SRD: None

    SRD->>SRD: log cache.retrieval_miss
    SRD->>SRD: _out_cache_status.append("MISS")

    SRD->>RET: retrieve(query, enable_rerank)

    Note over RET: Stage 1 — Semantic Search
    RET->>L2: get(SHA-256(query))
    alt L2 Hit
        L2-->>RET: cached embedding vector
    else L2 Miss
        RET->>ENC: encode(query)
        ENC-->>RET: embedding vector
        RET->>L2: store(SHA-256(query), embedding)
    end
    RET->>VDB: query(embedding, semantic_top_k)
    VDB-->>RET: semantic results

    Note over RET: Stage 2 — Keyword Search
    RET->>RET: BM25 keyword search (stop-word filtered)

    Note over RET: Stage 3 — Score Fusion
    RET->>RET: weighted combination<br/>(semantic_weight + keyword_weight)

    Note over RET: Stage 4 — Reranking (if enabled)
    opt enable_rerank = true
        RET->>RET: cross-encoder rerank<br/>(ms-marco model, pre_rerank_top_k)
    end

    Note over RET: Stage 5 — Deduplication
    RET->>RET: deduplicate by source

    RET-->>SRD: results list

    SRD->>LC: set(cache_key, results)
    LC->>CB: set(cache_key, results, ttl)
    CB-->>LC: ok

    SRD-->>WS: results

    WS->>WS: filter results (score ≥ 0.80)
    WS-->>Client: {type: "results", results, total_results,<br/>cache_status: "MISS"}
```

---

## 3. Cache Backend Error — Fail-Open Path

```mermaid
sequenceDiagram
    participant SRD as _shared_retrieve_documents
    participant LC as LazyCache
    participant CB as RedisCache
    participant RET as HybridRetriever

    SRD->>LC: get(cache_key)
    LC->>CB: get(cache_key)
    CB-->>LC: raises Exception (connection error)
    LC-->>SRD: raises Exception

    SRD->>SRD: except: log warning (cache read failed)
    SRD->>SRD: log cache.retrieval_error (correlation_id)
    SRD->>SRD: _out_cache_status.append("ERROR")

    SRD->>RET: retrieve(query, enable_rerank)
    RET-->>SRD: results

    Note over SRD,CB: Write-back also fail-open
    SRD->>LC: set(cache_key, results)
    LC->>CB: set(cache_key, results, ttl)
    CB-->>LC: raises Exception
    SRD->>SRD: except: log warning (cache write failed)

    SRD-->>SRD: return results (retrieval unaffected)
```

---

## 4. Cache Invalidation — Config Update (`PUT /config`)

```mermaid
sequenceDiagram
    actor Admin
    participant API as PUT /config<br/>(update_config)
    participant LC as LazyCache
    participant CB as CacheBackend
    participant ST as Global State<br/>(_cache_generation, _corpus_version)

    Admin->>API: PUT /config {semantic_weight, ...}
    API->>API: validate & apply config fields
    API->>ST: _cache_generation += 1
    API->>ST: _corpus_version = _build_corpus_version_token()<br/>(gen{N}.n{collection_count})
    API->>API: log cache.invalidation (prev→new corpus_version)
    API->>LC: clear()
    LC->>CB: clear() — flush all keys
    CB-->>LC: ok
    API-->>Admin: 200 ConfigResponse
```

---

## 5. Cache Invalidation — Document Ingest (`POST /documents`)

```mermaid
sequenceDiagram
    actor User
    participant API as POST /documents<br/>(add_documents)
    participant VDB as ChromaDB Collection
    participant LC as LazyCache
    participant ST as Global State<br/>(_corpus_version)

    User->>API: POST /documents {ingest_type, content, ...}
    API->>API: extract & chunk text
    API->>VDB: collection.add(ids, documents, metadatas)
    VDB-->>API: ok

    alt ingest_type = "update"
        API->>ST: _cache_generation += 1
        API->>ST: _corpus_version = _build_corpus_version_token()
        API->>API: log cache.invalidation event=ingest_update
        API->>LC: clear() — full L1 flush
        LC-->>API: ok
    else ingest_type = "add"
        API->>ST: _corpus_version = _build_corpus_version_token()<br/>(count dimension only, generation unchanged)
        API->>API: log cache.invalidation event=ingest_add
        Note over LC: L1 preserved — prior results still valid
    end

    API-->>User: 200 DocumentIngestionResponse
```

---

## 6. Cache Stats Observability (`GET /cache/stats`)

```mermaid
sequenceDiagram
    actor Operator
    participant API as GET /cache/stats
    participant LC as LazyCache
    participant CB as CacheBackend
    participant RET as HybridRetriever

    Operator->>API: GET /cache/stats

    API->>LC: stats()
    LC->>CB: stats()
    CB-->>LC: {backend, size, hits, misses}
    LC-->>API: raw L1 stats

    API->>LC: health()
    LC->>CB: health()
    note right of CB: InMemory: always connected<br/>Redis: PING round-trip
    CB-->>LC: {connected, latency_ms, fallback_active, error}
    LC-->>API: backend_health

    API->>RET: _get_embedding_cache_stats()
    RET-->>API: {hits, misses, hit_rate, size, capacity}

    API->>API: compute hit_rate = hits / (hits + misses)
    API->>API: attach corpus_version token

    API-->>Operator: 200 LayeredCacheStatsResponse<br/>{l1_query_cache, l2_embedding_cache, backend_health, timestamp}
```

---

## Cache Key Construction Reference

| Layer | Key Components | Algorithm |
|-------|---------------|-----------|
| L1 (shared retrieval) | `normalized_query` + `effective_enable_rerank` + `config_fingerprint` + `corpus_version` | `SHA-256(JSON(shared_identity))` |
| L2 (embedding) | `query_text` (raw) | `SHA-256(query_text.encode())` |
| `corpus_version` token | `_cache_generation` + `collection.count()` | `"gen{N}.n{count}"` |
