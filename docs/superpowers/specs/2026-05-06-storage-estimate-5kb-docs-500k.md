# Storage Estimate Recalculation: 500k Documents @ 5KB Average

**Updated Date:** 2026-05-06  
**Key Change:** 5KB avg file size (vs. 2KB original estimate)

---

## Storage Calculation (5KB Documents)

### Chunking Math

**Assumptions:**
- Avg document: **5 KB = 5,000 characters**
- Chunk size: 400 chars
- Chunk overlap: 50 chars
- Chunk stride: 400 - 50 = 350 chars per new chunk

**Chunks per document:**
```
Number of chunks = ceil((doc_length - chunk_overlap) / (chunk_size - chunk_overlap))
                 = ceil((5000 - 50) / 350)
                 = ceil(14.14)
                 = ~15 chunks per document
```

**Total at 500k documents:**
```
500,000 docs × 15 chunks/doc = 7,500,000 total chunks
```

---

## Storage Per Chunk Breakdown

| Component | Size | Notes |
|-----------|------|-------|
| **Vector embedding** | 6.0 KB | 1536-dim float32 (BAAI/bge-small-en-v1.5) |
| **Text content** | 0.35 KB | ~350 chars after normalization (~0.36 KB before) |
| **Metadata** | 0.25 KB | source, chunk_index, section_h1/h2, source_url |
| **ChromaDB overhead** | 1.5 KB | Index pointers, doc IDs, field indexes, bloom filters |
| **Per-chunk total** | **~8.1 KB** | |

---

## Total Storage Requirement

### Single Node (No Replication)

```
7,500,000 chunks × 8.1 KB/chunk = 60.75 TB (base)

With 15% overhead (indexes, WAL, temp files):
60.75 TB × 1.15 = 69.9 TB ≈ 70 TB
```

### With High Availability

```
2x replication (failover):
  70 TB × 2 = 140 TB total

3x replication (recommended for prod):
  70 TB × 3 = 210 TB total
```

### Storage Comparison: Before vs. After Normalization

| Aspect | Impact |
|--------|--------|
| **Text per chunk (before normalization)** | ~360 chars (0.36 KB) |
| **Text per chunk (after normalization)** | ~350 chars (0.35 KB) — 12% whitespace reduction |
| **Savings per chunk** | ~0.01 KB (negligible) |
| **Total savings at 7.5M chunks** | 7.5M × 0.01 = **75 GB (0.1% of 70 TB)** |
| **Conclusion** | **Whitespace normalization saves ~75 GB (negligible)** |

---

## Infrastructure Cost Impact @ 500k Docs

### EC2 Storage Options

#### Option 1: Single Large Instance (Non-HA)

```
Instance: i4i.8xlarge (60 TB NVMe + 256 GB RAM)
- 60 TB NVMe: $8,000–$10,000/month
- 256 GB RAM: included
- 32 vCPU: included
- Compute: ~$5/hour = $3,600/month

Total: ~$12,000–$13,500/month ($144k–$162k/year)
Problem: Single point of failure; 70 TB storage exceeds 60 TB NVMe
```

#### Option 2: Sharded Cluster (2x i4i.4xlarge with replication)

```
Each node: i4i.4xlarge (30 TB NVMe + 128 GB RAM)
- 2 nodes: 60 TB usable (with replication factor=2)
- Cost per node: ~$6,000–$7,000/month
- 2 × $6,500 = $13,000/month

Total: ~$13,000/month ($156k/year)
Benefit: HA, failover, distributed queries
```

#### Option 3: EBS gp3 + Smaller Instance (More Flexible)

```
Instance: r7g.8xlarge (32 cores, 256 GB RAM)
- Compute: ~$4,000/month
- EBS gp3 (70 TB, 3000 IOPS):
  * Storage: $70,000 ÷ 12 = ~$5,800/month
  * IOPS: $0.06/iops-month × 3000 = $180/month
- EBS throughput: $0.024/MB-month × 125 MB/s = $260/month

Total: ~$10,300/month ($123k/year)
Benefit: Scalable storage, cheaper than NVMe
Risk: ~10x slower than NVMe; may not meet query latency SLAs
```

### Docker/Fargate Deployment

```
Fargate + EBS:
- CPU: 32 vCPU
- Memory: 256 GB
- Storage: 70 TB EBS gp3

Monthly cost:
  - CPU: $32 × $0.04672/hour × 730 hours = ~$1,090
  - Memory: $256 × $0.004949/hour × 730 hours = ~$925
  - Storage: ~$5,800/month (EBS gp3 70 TB)

Total: ~$7,815/month ($93.8k/year)
Benefit: No upfront CapEx; auto-scaling available
```

---

## Updated Infrastructure Summary (5KB Docs @ 500k)

| Metric | Estimate | Notes |
|--------|----------|-------|
| **Total chunks** | 7.5M | 500k docs × 15 chunks |
| **Base storage** | 60.75 TB | Before overhead |
| **With 15% overhead** | **70 TB** | Production-ready |
| **With 2x replication** | 140 TB | HA + failover |
| **With 3x replication** | 210 TB | Enterprise grade |
| | | |
| **EC2 NVMe (i4i.8xl)** | $144k–$162k/year | Largest option: 60 TB limit; exceeds needs |
| **EC2 Sharded (2×i4i.4xl)** | $156k/year | Recommended; HA built-in |
| **EC2 + EBS gp3** | $123k/year | Cheaper; slower (may not meet SLA) |
| **Fargate + EBS** | **$93.8k/year** | Most economical; best for cloud-native |

---

## Performance Impact at 70 TB

### Query Latency

| Storage Layer | Latency Impact | Notes |
|---------------|----------------|-------|
| **NVMe (i4i series)** | Baseline (50–100ms ChromaDB I/O) | Fast; acceptable |
| **EBS gp3 (3000 IOPS)** | +100–500ms per query | Slower; depends on working set in memory |
| **Network attached** | +1000ms+ | Unacceptable for real-time queries |

**Recommendation:** 
- If query SLA < 200ms → Use NVMe (i4i) or Fargate with adequate RAM cache
- If query SLA < 500ms → EBS gp3 acceptable if working set fits in 128–256 GB RAM
- If query SLA > 1s → Any storage works

### Memory Tuning at 70 TB

```
ChromaDB working set (typical):
- Active indexes: ~5–10% of dataset = 3.5–7 TB
- LRU embedding cache: 10,000 entries × 6 KB = 60 MB

For 256 GB RAM:
- ChromaDB indexes in OS buffer cache: ~3–5 TB usable
- Application cache (L2): 60 MB
- OS overhead: ~50 GB
- Available: ~200 GB for page cache

Conclusion: Only 3–5 TB of 70 TB indexes stay hot in RAM
→ 95% of queries require disk I/O (EBS/NVMe)
```

---

## Whitespace Normalization Impact @ 5KB Scale

| Aspect | Before | After | Delta |
|--------|--------|-------|-------|
| **Total chunks** | 7.5M | 7.5M | 0% |
| **Avg text/chunk** | 360 chars | 350 chars | -2.8% |
| **Storage/chunk** | 8.11 KB | 8.1 KB | -0.1% |
| **Total storage** | 60.8 TB | 60.75 TB | -75 GB (0.1%) |
| **Ingestion time** | 270 ms/doc | 270.1 ms/doc | +0.04% |
| **Query latency** | 60–270 ms | 60–270 ms (possibly faster) | ±0% (neutral/slight gain) |

**Conclusion:** Whitespace normalization has **negligible storage/performance impact** at 500k scale. Benefits are semantic quality, not resource efficiency.

---

## Revised Infrastructure Recommendation for 5KB @ 500k

### Development/Trial (Current Phase)
```
Single EC2 r7g.4xlarge + 100 GB EBS:
  - Cost: ~$1,500/month
  - Storage: Enough for ~6.25M documents (scaled linearly)
  - Suitable for: Testing, edge case validation, performance profiling
```

### Production (500k Documents)

**Option A: Cloud-native (Recommended for your use case)**
```
Fargate + EBS gp3:
- 32 vCPU, 256 GB RAM, 70 TB EBS
- Cost: $93.8k/year
- Auto-scaling: Available
- HA: Built-in via Fargate
- Best for: Multi-tenant, dynamic workloads
```

**Option B: High-performance (If query SLA < 150ms required)**
```
EC2 Sharded (2× i4i.4xlarge) + failover:
- 70 TB NVMe (distributed)
- Cost: $156k/year
- Query latency: 50–100ms (fast)
- HA: Manual failover (can add auto-scaling)
- Best for: Real-time, latency-critical workloads
```

**Option C: Cost-optimized (If query SLA < 500ms acceptable)**
```
EC2 r7g.8xlarge + 70 TB gp3:
- Cost: $123k/year
- Query latency: 100–300ms (acceptable)
- Scaling: Single instance (replicates via backups)
- Best for: Batch retrieval, overnight analytics
```

---

## Storage Projection at Other Scales

| Scale | Chunks | Storage (Base) | Storage (HA 3x) | Est. Annual Cost |
|-------|--------|----------------|-----------------|------------------|
| 50k docs (5KB avg) | 750k | 6.0 TB | 18 TB | $9.4k |
| 100k docs | 1.5M | 12 TB | 36 TB | $18.8k |
| 250k docs | 3.75M | 30 TB | 90 TB | $47k |
| **500k docs** | **7.5M** | **60 TB** | **180 TB** | **$93.8k–$156k** |
| 1M docs | 15M | 120 TB | 360 TB | $187k–$312k |

---

## Key Takeaways

1. **5KB avg file = 70 TB storage** (not 26 TB) at 500k documents
2. **Whitespace normalization saves ~75 GB** — negligible for scaling decisions
3. **Infrastructure cost is dominated by storage**, not compute
4. **Fargate + EBS is most economical** ($93.8k/year) for this scale
5. **Query latency** depends on storage type:
   - NVMe: 50–100ms (best)
   - EBS gp3: 100–300ms (acceptable)
   - Network: >1000ms (unacceptable)

**Recommendation for 500k deployment:**
- Choose **Fargate + EBS gp3** for flexibility and cost ($93.8k/year)
- Or choose **EC2 Sharded NVMe** if latency SLA < 150ms ($156k/year)
- Monitor query latency; add read replicas if P95 > 500ms

