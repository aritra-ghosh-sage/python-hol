# Hybrid RAG Caching System - Deployment Guide

**Document Version:** 1.0  
**Last Updated:** April 20, 2026  
**Applicable to:** Hybrid RAG v0.1.0+

---

## Table of Contents

1. [Overview](#overview)
2. [Development Setup](#development-setup)
3. [Production Setup](#production-setup)
4. [Environment Variables Reference](#environment-variables-reference)
5. [Troubleshooting](#troubleshooting)
6. [Monitoring & Observability](#monitoring--observability)
7. [FAQ](#faq)
8. [Production Checklist](#production-checklist)

---

## Overview

**Deployment Scenarios for Hybrid RAG Caching**

The Hybrid RAG caching system implements a **two-layer caching strategy**:

- **L1 Query Cache**: Caches complete retrieval results at the query level
- **L2 Embedding Cache**: Caches computed embeddings to avoid redundant encoder calls

Both layers support multiple backend implementations:

| Backend | Use Case | Data Persistence | Scalability |
|---------|----------|------------------|-------------|
| **InMemoryCache** | Local development, single-instance deployments | Lost on restart | Single process |
| **RedisCache** | Multi-instance production, distributed systems | Persistent (with Redis durability) | Distributed |

**Performance Impact** (from [CACHE_PERF_REPORT.md](./CACHE_PERF_REPORT.md)):
- **Embedding cache hit rate**: 60% on repeated queries
- **Mean latency**: 946.8 ms (cached) vs 979.2 ms (uncached)
- **Overall test coverage**: 64% with 163 passing tests

---

## Development Setup

### Default: InMemoryCache (No Redis Needed)

For local development, the Hybrid RAG system defaults to **InMemoryCache**, requiring no external dependencies:

- ✅ Zero setup required
- ✅ Fast in-memory storage with TTL support
- ✅ Thread-safe LRU eviction
- ⚠️ Cache data lost on server restart (acceptable for dev)
- ⚠️ Not suitable for multi-instance deployments

### Configuration

Create `.env.local` in the project root:

```bash
# Cache configuration for development
CACHE_BACKEND=memory
CACHE_TTL_SECONDS=3600
CACHE_MAX_SIZE=10000
```

### Running the Development Server

**Option 1: Using the main example**

```bash
cd /home/aritraghosh/projects/python-hol
source .venv/bin/activate
python main_example.py
```

**Option 2: Using FastAPI with auto-reload**

```bash
cd /home/aritraghosh/projects/python-hol
source .venv/bin/activate
uvicorn api:app --reload --host 0.0.0.0 --port 8000
```

### Verifying Development Cache

Test that caching is working:

```bash
# Terminal 1: Start the API
source .venv/bin/activate
uvicorn api:app --reload

# Terminal 2: Check cache stats
curl http://localhost:8000/cache/stats | jq .
```

**Expected response** (initially empty):

```json
{
  "backend": "memory",
  "hits": 0,
  "misses": 0,
  "hit_rate": 0.0,
  "size": 0,
  "max_size": 10000,
  "ttl_seconds": 3600
}
```

After running retrieval queries, `hits` and `misses` will increment.

---

## Production Setup

### Multi-Instance: RedisCache with Connection Pooling

For production deployments with multiple API instances, use **RedisCache** with a centralized Redis instance:

- ✅ Distributed cache shared across instances
- ✅ Data persistence via Redis durability
- ✅ Connection pooling for efficiency
- ✅ Fail-open error handling (graceful degradation)
- ✅ Comprehensive monitoring support

### Prerequisites

Ensure the following before deploying:

- **Redis >= 6.0** installed and running
- Redis accessible from your API instances (network connectivity)
- Redis port (default 6379) open and listening
- Sufficient Redis memory for cache size (see `CACHE_MAX_SIZE`)

### Installation

**On Linux (Ubuntu/Debian)**

```bash
sudo apt update
sudo apt install redis-server
sudo systemctl start redis-server
sudo systemctl enable redis-server
```

**On macOS (Homebrew)**

```bash
brew install redis
brew services start redis
```

**Docker (Recommended for Production)**

```dockerfile
# Dockerfile.redis
FROM redis:7-alpine
EXPOSE 6379
CMD ["redis-server", "--maxmemory", "1gb", "--maxmemory-policy", "allkeys-lru"]
```

Deploy with Docker Compose:

```yaml
version: '3.8'
services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    environment:
      - MAXMEMORY=1gb
      - MAXMEMORY_POLICY=allkeys-lru
    volumes:
      - redis-data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - CACHE_BACKEND=redis
      - REDIS_URL=redis://redis:6379
      - CACHE_TTL_SECONDS=86400
      - CACHE_KEY_PREFIX=prod_hybrid_rag:
      - CACHE_MAX_SIZE=100000
    depends_on:
      redis:
        condition: service_healthy

volumes:
  redis-data:
```

### Production Environment Configuration

Create `.env` in the project root (never commit this file):

```bash
# Production cache configuration
CACHE_BACKEND=redis
REDIS_URL=redis://redis-instance.internal:6379/0
CACHE_TTL_SECONDS=86400
CACHE_KEY_PREFIX=prod_hybrid_rag:
CACHE_MAX_SIZE=100000

# Optional: Redis password authentication
# REDIS_URL=redis://:password@redis-instance.internal:6379/0
```

**Configuration Notes:**

| Setting | Recommended Value | Rationale |
|---------|-------------------|-----------|
| `CACHE_BACKEND` | `redis` | Multi-instance deployments |
| `REDIS_URL` | `redis://redis:6379/0` | Direct connection (use docker hostname in containers) |
| `CACHE_TTL_SECONDS` | `86400` (24 hours) | Standard production TTL; adjust based on data freshness |
| `CACHE_KEY_PREFIX` | `prod_hybrid_rag:` | Namespace to avoid collisions with other apps |
| `CACHE_MAX_SIZE` | `100000` | Larger than development; adjust based on Redis memory |

### Health Check: Verify Redis Connectivity

Before deploying the API, verify Redis is accessible:

```bash
# Test Redis connectivity
redis-cli -h redis-instance -p 6379 ping

# Expected output
PONG
```

If using Docker:

```bash
# From Docker Compose
docker-compose exec redis redis-cli ping
```

### Starting the Production API

```bash
source .venv/bin/activate
uvicorn api:app --host 0.0.0.0 --port 8000 --workers 4
```

The API will automatically:
1. Load cache configuration from environment
2. Connect to Redis
3. Initialize the caching layer
4. Log initialization status to stdout

**Expected log output:**

```
INFO:hybrid_rag.cache:Connecting to Redis at redis://redis-instance:6379/0...
INFO:hybrid_rag.cache:Redis connection pool initialized with default backend
INFO:hybrid_rag.retriever:Hybrid retriever initialized with caching enabled
```

---

## Environment Variables Reference

### Configuration Table

| Variable | Type | Default | Required? | Description |
|----------|------|---------|-----------|-------------|
| `CACHE_BACKEND` | string | `'memory'` | No | Cache backend implementation: `'memory'` (local) or `'redis'` (distributed) |
| `REDIS_URL` | string | `None` | If `backend=redis` | Redis connection URL (format: `redis://[:password@]host[:port][/db]`) |
| `CACHE_TTL_SECONDS` | int | `3600` | No | Time-to-live for cache entries in seconds; set to 0 for indefinite caching |
| `CACHE_KEY_PREFIX` | string | `'hybrid_rag_cache:'` | No | Namespace prefix for all cache keys (useful in shared Redis instances) |
| `CACHE_MAX_SIZE` | int | `10000` | No | Maximum number of entries in InMemoryCache before LRU eviction (ignored for Redis) |

### Examples

**Development (default)**

```bash
CACHE_BACKEND=memory
CACHE_TTL_SECONDS=3600
CACHE_MAX_SIZE=10000
```

**Production with Redis**

```bash
CACHE_BACKEND=redis
REDIS_URL=redis://redis.prod.internal:6379/0
CACHE_TTL_SECONDS=86400
CACHE_KEY_PREFIX=myapp_prod:
CACHE_MAX_SIZE=100000
```

**Production with Redis Authentication**

```bash
CACHE_BACKEND=redis
REDIS_URL=redis://:MySecurePassword123@redis.prod.internal:6379/0
CACHE_TTL_SECONDS=86400
CACHE_KEY_PREFIX=myapp_prod:
```

**Long-Lived Cache (12 hours)**

```bash
CACHE_BACKEND=redis
REDIS_URL=redis://redis:6379
CACHE_TTL_SECONDS=43200
CACHE_KEY_PREFIX=app_cache:
```

---

## Troubleshooting

### Issue 1: Cache is Not Working

**Symptoms:**
- GET `/cache/stats` shows `hits: 0, misses: 0`
- Cache size remains 0 after multiple queries
- Performance improvements not observed

**Diagnosis Steps:**

1. Verify `CACHE_BACKEND` environment variable:
   ```bash
   python3 -c "import os; print(f'CACHE_BACKEND={os.getenv(\"CACHE_BACKEND\", \"memory\")}')"
   ```

2. Check cache stats endpoint:
   ```bash
   curl http://localhost:8000/cache/stats | jq .
   ```

3. Verify API server logs for cache initialization:
   ```bash
   # Look for "Cache initialized" message in stdout
   grep -i "cache" api_server.log | head -10
   ```

**Solutions:**

- **Restart the API server** to force cache reinitialization:
  ```bash
  # Press Ctrl+C if running locally
  # Or for production:
  systemctl restart api_service
  ```

- **Check for errors in logs**:
  ```bash
  journalctl -u api_service -n 50 --no-pager | grep -i cache
  ```

- **Verify configuration**: Ensure `.env` or environment variables are correctly set:
  ```bash
  env | grep CACHE
  ```

---

### Issue 2: Redis Connection Errors

**Symptoms:**
- API startup fails with `ConnectionError: Error 111 connecting to redis...`
- Logs show `ECONNREFUSED` or `Name or service not known`

**Error Messages:**

```
ConnectionError: Error 111 connecting to redis-instance:6379. Connection refused.
ConnectionError: Name or service not known
ERROR:hybrid_rag.cache:Failed to connect to Redis: ...
```

**Root Causes & Solutions:**

| Cause | Check | Solution |
|-------|-------|----------|
| Redis not running | `redis-cli ping` | Start Redis: `redis-server` or `systemctl start redis-server` |
| Wrong hostname/port | `REDIS_URL` value | Verify connectivity: `redis-cli -h <host> -p <port> ping` |
| Network unreachable | Container/host network | Check firewall rules, DNS resolution, VPC routing |
| Redis auth failed | Redis password required | Add password to `REDIS_URL`: `redis://:PASSWORD@host:6379` |

**Diagnostic Commands:**

```bash
# Test Redis availability
redis-cli -h <hostname> -p 6379 ping

# Test from container
docker exec <api_container> redis-cli -h redis -p 6379 ping

# Check network connectivity
nc -zv redis-instance 6379

# Verify environment variable
docker inspect <api_container> | grep REDIS_URL
```

**Graceful Degradation:**

If Redis is unavailable, the API will **fail-open**: it continues serving live retrieval results without caching. This ensures service availability but without performance benefits.

**Fallback Behavior:**

```python
# API behavior when Redis is down:
# 1. Cache.get() returns None (cache miss)
# 2. Retrieval proceeds with live computation
# 3. Cache.set() fails silently (no exceptions)
# 4. Service remains operational
```

---

### Issue 3: Low Cache Hit Rate

**Symptoms:**
- GET `/cache/stats` shows `hits << misses` (e.g., `hits: 5, misses: 245`)
- Cache hit rate < 10%

**Root Causes:**

| Cause | Typical Hit Rate | Solution |
|-------|-----------------|----------|
| Unique queries every time | < 5% | Expected for RAG workloads; monitor for trends |
| Frequent document ingestion | 5-15% | Ingest operations invalidate cache entries |
| Short TTL (3600s) | Varies | Increase `CACHE_TTL_SECONDS` if data freshness allows |
| Cache size too small | Variable | Increase `CACHE_MAX_SIZE` or Redis memory allocation |

**Diagnostics:**

```bash
# Monitor cache hit rate over time
watch -n 5 'curl -s http://localhost:8000/cache/stats | jq .hit_rate'

# Check for cache invalidation patterns in logs
grep -i "cache.*clear\|cache.*flush" api_server.log | tail -20
```

**Expected Cache Hit Rates:**

For RAG systems, **10-30% hit rate is typical** due to the diversity of queries:
- Many unique queries (low repeated coverage)
- Document updates clearing cache
- Dynamic context windows

**60%+ hit rate would be unusual** and might indicate:
- Query repetition patterns (e.g., testing)
- Limited query variance
- Very large cache capacity relative to usage

**Optimization:**

1. **Increase TTL** for stable data:
   ```bash
   CACHE_TTL_SECONDS=172800  # 48 hours instead of 1 hour
   ```

2. **Expand cache capacity**:
   ```bash
   CACHE_MAX_SIZE=500000  # For InMemoryCache
   # Or increase Redis maxmemory
   redis-cli CONFIG SET maxmemory 4gb
   ```

3. **Monitor with /cache/stats**:
   ```bash
   # Query every 30 seconds to track trends
   watch -n 30 'curl -s http://localhost:8000/cache/stats | jq "{hits, misses, hit_rate, size}"'
   ```

---

### Issue 4: Cache Consuming Too Much Memory

**Symptoms:**
- Redis memory usage growing unbounded
- API OOM (Out of Memory) errors
- System swap usage increasing
- Slow performance due to memory pressure

**Diagnosis:**

```bash
# Check Redis memory usage
redis-cli INFO memory | grep "used_memory_human"

# Output example
used_memory_human:512M

# Check current cache stats
curl http://localhost:8000/cache/stats | jq '.size'

# Monitor system memory
free -h  # Linux
# or
vm_stat  # macOS
```

**Solutions:**

1. **Reduce cache TTL**:
   ```bash
   CACHE_TTL_SECONDS=43200  # 12 hours instead of 24 hours
   ```

2. **Reduce cache max size**:
   ```bash
   CACHE_MAX_SIZE=50000  # Smaller LRU cache
   ```

3. **Increase Redis maxmemory**:
   ```bash
   redis-cli CONFIG SET maxmemory 4gb
   ```

4. **Set eviction policy** (Redis):
   ```bash
   redis-cli CONFIG SET maxmemory-policy allkeys-lru
   # Evicts least-recently-used keys when limit reached
   ```

5. **Manually clear cache** (for troubleshooting):
   ```bash
   # InMemoryCache: Restart API
   # Redis: Flush specific database
   redis-cli FLUSHDB
   ```

**Long-term Monitoring:**

```bash
# Add to monitoring dashboard
watch -n 60 'redis-cli INFO memory | grep "used_memory\|maxmemory"'
```

---

## Monitoring & Observability

### Cache Stats Endpoint

The API provides a real-time monitoring endpoint for cache metrics.

**Endpoint:** `GET /cache/stats`

**Authentication:** None (unauthenticated access)

**Response Schema:**

```json
{
  "backend": "memory|redis",
  "hits": 42,
  "misses": 158,
  "hit_rate": 0.21,
  "size": 18,
  "max_size": 10000,
  "ttl_seconds": 3600
}
```

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `backend` | string | Active cache backend: `"memory"` or `"redis"` |
| `hits` | int | Number of successful cache lookups (cumulative) |
| `misses` | int | Number of cache misses (cumulative) |
| `hit_rate` | float | Hit rate as percentage (0.0-1.0); formula: `hits / (hits + misses)` |
| `size` | int | Current number of entries in cache |
| `max_size` | int | Maximum cache capacity before eviction |
| `ttl_seconds` | int | Time-to-live for cache entries in seconds |

### Example Monitoring Queries

**Check current cache status:**

```bash
curl http://localhost:8000/cache/stats | jq .
```

**Extract hit rate:**

```bash
curl -s http://localhost:8000/cache/stats | jq '.hit_rate'
```

**Monitor continuously (every 10 seconds):**

```bash
watch -n 10 'curl -s http://localhost:8000/cache/stats | jq "{backend, hits, misses, hit_rate, size}"'
```

**Export to monitoring system (Prometheus, DataDog, etc.):**

```bash
# Parse stats and emit metrics
curl -s http://localhost:8000/cache/stats | jq -r '
  "hybrid_rag_cache_hits \(.hits)\n" +
  "hybrid_rag_cache_misses \(.misses)\n" +
  "hybrid_rag_cache_hit_rate \(.hit_rate)\n" +
  "hybrid_rag_cache_size \(.size)"
' | tee -a metrics.txt
```

### Health Indicator Thresholds

Use these thresholds to set up alerting:

| Metric | Green | Yellow | Red |
|--------|-------|--------|-----|
| **Hit Rate** | > 20% | 10-20% | < 10% (investigate) |
| **Cache Size** | < 80% of max | 80-95% of max | > 95% (alert on eviction) |
| **Redis Memory** | < 70% of maxmemory | 70-90% | > 90% (risk of OOM) |
| **Response Time** | < 500ms | 500-1000ms | > 1000ms |

### Dashboard Setup (Example - Grafana)

Create a Grafana dashboard with these queries:

```promql
# Cache hit rate over time
rate(hybrid_rag_cache_hits[5m]) / (rate(hybrid_rag_cache_hits[5m]) + rate(hybrid_rag_cache_misses[5m]))

# Cache size trend
hybrid_rag_cache_size

# Memory usage
redis_memory_used_bytes

# Eviction rate
rate(redis_evicted_keys_total[5m])
```

### Application Logging

Monitor cache-related log messages in API logs:

```bash
# View cache-related logs
journalctl -u api_service | grep -i cache

# Watch for errors
tail -f api_server.log | grep -i "error\|warning"
```

**Key Log Patterns:**

- `Cache initialized` - Successful cache setup on startup
- `Cache hit for key` - Successful cache lookup (debug level)
- `Cache miss for key` - Cache miss (debug level)
- `Error connecting to Redis` - Connection failure
- `Cache stats: hits=X, misses=Y` - Periodic summary

### Redis CLI Monitoring

**Real-time Redis stats:**

```bash
redis-cli --stat

# Output:
# keys=1842  mem=2.89M [match] calls/sec=1.23 hits/sec=0.23 misses/sec=0.12 evict/sec=0.00
```

**Memory breakdown:**

```bash
redis-cli INFO memory

# Output:
# used_memory_human:512M
# used_memory_peak_human:512M
# maxmemory_human:1G
# evicted_keys:2344
```

**Keyspace statistics:**

```bash
redis-cli INFO keyspace

# Output:
# db0:keys=1842,expires=1800,avg_ttl=3591200
```

---

## FAQ

### Q: Do I need Redis for caching?

**A:** No. By default, Hybrid RAG uses **InMemoryCache**, which requires no Redis installation.

- **Use InMemoryCache if:**
  - Running locally or in development
  - Single API instance
  - Cache data loss on restart is acceptable

- **Use RedisCache if:**
  - Running multiple API instances
  - Need persistent cache across restarts
  - Distributed deployment (Kubernetes, etc.)

---

### Q: What if Redis goes down?

**A:** The API implements **fail-open error handling**:

1. **Cache lookup fails** → Returns `None` (cache miss)
2. **Query proceeds** → Computation runs without cache
3. **Response served** → User gets fresh results
4. **No errors** → Service remains operational

**Impact:**
- ✅ Service continues to function
- ❌ Performance degradation (no cached results)
- ❌ Increased latency and compute load

**Recovery:**
- Redis automatically restarts (if configured with systemd/docker)
- Cache repopulates gradually as queries execute
- Hit rate recovers as cache warms up

---

### Q: How do I clear the cache?

**A:** Cache clearing depends on the backend:

**For InMemoryCache:**
- Restart the API server:
  ```bash
  # Stop API
  Ctrl+C
  # Start API
  uvicorn api:app --reload
  ```

**For RedisCache:**
- Flush the Redis database:
  ```bash
  redis-cli FLUSHDB
  ```

**Automatic Cache Invalidation:**
- `POST /config` endpoint (configuration changes)
- `POST /ingest` endpoint (document updates)
- TTL expiration (automatic)

---

### Q: Can I use Memcached instead of Redis?

**A:** Not currently. The Hybrid RAG caching layer is Redis-specific.

**Rationale:**
- Redis offers superior performance and feature set
- Memcached lacks TTL guarantees and distributed transaction support
- Redis ecosystem is more mature for production systems

**Future Support:**
- Future versions (v1.1+) may support pluggable backends
- Contributing a Memcached adapter is welcome

---

### Q: What's the expected cache hit rate?

**A:** For Retrieval-Augmented Generation systems, **10-30% hit rate is typical**.

**Why low hit rates are normal:**
- Queries are highly diverse (each user asks different questions)
- Documents frequently update (cache invalidates)
- Query embeddings are unique (low semantic similarity)

**Typical Breakdown:**
- 50% queries: Never cached (first occurrence)
- 30% queries: Cache misses (similar but not identical)
- 20% queries: Cache hits (identical or very similar queries)

**60%+ hit rates indicate:**
- Highly repetitive query patterns (unusual)
- Limited query diversity
- Very large cache relative to usage

**Monitor hit rate trends:**
```bash
# If hit_rate is stable > 20%, caching is healthy
# If hit_rate drops below 10%, investigate query patterns or cache size
```

---

### Q: Can I share Redis between multiple applications?

**A:** Yes, using the `CACHE_KEY_PREFIX` setting.

**Setup:**

```bash
# Application 1
CACHE_KEY_PREFIX=app1_cache:
REDIS_URL=redis://shared-redis:6379/0

# Application 2
CACHE_KEY_PREFIX=app2_cache:
REDIS_URL=redis://shared-redis:6379/0
```

This ensures cache keys don't collide:
- App1 keys: `app1_cache:query_abc123`
- App2 keys: `app2_cache:query_abc123`

---

### Q: How do I benchmark cache performance?

**A:** Use the included performance testing script:

```bash
python3 -c "
import time
from hybrid_rag.retriever import HybridRetriever

retriever = HybridRetriever()
query = 'What is machine learning?'

# Warm cache
retriever.retrieve(query, top_k=5)

# Measure cached performance
times = []
for _ in range(10):
    start = time.time()
    retriever.retrieve(query, top_k=5)
    times.append(time.time() - start)

avg_time = sum(times) / len(times)
print(f'Cached retrieval: {avg_time*1000:.1f}ms')
"
```

**Expected Results** (from [CACHE_PERF_REPORT.md](./CACHE_PERF_REPORT.md)):
- Uncached: ~979 ms
- Cached (hit): ~947 ms
- Improvement: ~3.4% with 60% hit rate

---

### Q: Can I adjust cache TTL per query?

**A:** Currently, TTL is global via `CACHE_TTL_SECONDS`. Per-query TTL requires a future enhancement.

**Workaround:**
- Use high TTL (e.g., 86400s) for stable data
- Use low TTL (e.g., 300s) for dynamic data
- Manually flush cache when data updates: `redis-cli FLUSHDB`

---

## Production Checklist

Use this checklist before deploying caching to production:

### Pre-Deployment

- [ ] Redis instance configured and running (version >= 6.0)
  ```bash
  redis-cli ping  # Should return PONG
  ```

- [ ] Redis accessible from all API instances
  ```bash
  redis-cli -h <redis-host> -p 6379 ping
  ```

- [ ] Environment variables configured in production `.env`:
  ```bash
  CACHE_BACKEND=redis
  REDIS_URL=redis://redis-prod:6379/0
  CACHE_TTL_SECONDS=86400
  CACHE_KEY_PREFIX=prod_hybrid_rag:
  ```

- [ ] Redis password set (if required):
  ```bash
  REDIS_URL=redis://:PASSWORD@redis-prod:6379/0
  ```

- [ ] Redis memory limit configured:
  ```bash
  redis-cli CONFIG SET maxmemory 2gb
  redis-cli CONFIG SET maxmemory-policy allkeys-lru
  ```

### Deployment

- [ ] API code deployed to all instances
  ```bash
  git pull origin main
  source .venv/bin/activate
  pip install -r requirements.txt
  ```

- [ ] Cache backend verified:
  ```bash
  python3 -c "from hybrid_rag.config import CacheSettings; print(CacheSettings.from_env().backend)"
  ```

- [ ] API started with correct workers:
  ```bash
  uvicorn api:app --workers 4 --host 0.0.0.0 --port 8000
  ```

### Post-Deployment Validation

- [ ] Health check passes:
  ```bash
  curl http://localhost:8000/health
  ```

- [ ] Cache stats endpoint responds:
  ```bash
  curl http://localhost:8000/cache/stats | jq .
  ```

- [ ] Initial cache hit rate baseline recorded
  ```bash
  curl http://localhost:8000/cache/stats | jq '.hit_rate'
  ```

- [ ] Monitoring dashboard configured
  - Set up Grafana or equivalent
  - Configure alerts for hit_rate < 10% or memory > 90%

### Production Observability

- [ ] Logs configured to capture cache errors
  ```bash
  journalctl -u api_service | grep -i cache
  ```

- [ ] Alert rules set up:
  - Redis connection failures
  - Memory pressure (> 80% of maxmemory)
  - High error rates from cache operations

- [ ] Fail-open behavior tested (simulate Redis outage):
  ```bash
  redis-cli SHUTDOWN  # Simulate Redis outage
  curl http://localhost:8000/retrieve -X POST ...  # API should still work
  ```

- [ ] Load test completed with caching enabled:
  ```bash
  # Run load test with concurrent requests
  ab -n 1000 -c 50 http://localhost:8000/cache/stats
  ```

### On-Going Monitoring

- [ ] Cache hit rate monitored daily
  ```bash
  # Add to cron job or monitoring dashboard
  curl -s http://localhost:8000/cache/stats | jq '.hit_rate'
  ```

- [ ] Memory usage within acceptable bounds (< 80% of maxmemory)

- [ ] No Redis connection errors in logs

- [ ] Backup strategy in place for Redis (if using persistence)

---

## References

- [CACHE_PERF_REPORT.md](./CACHE_PERF_REPORT.md) - Performance benchmarks and test results
- [API_INTEGRATION.md](./API_INTEGRATION.md) - Complete API endpoint documentation
- [LIBRARY_DESIGN.md](./LIBRARY_DESIGN.md) - Hybrid RAG architecture and design
- [Redis Official Documentation](https://redis.io/documentation)
- [Redis Connection Pooling](https://redis.io/docs/develop/clients/client-side-caching/)

---

**Document Status:** ✅ Production Ready  
**Maintained By:** Development Team  
**Last Review:** April 20, 2026
