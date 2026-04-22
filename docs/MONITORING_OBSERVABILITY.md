# Monitoring & Observability

**Document Version:** 1.0  
**Last Updated:** 2026-04-22  
**Status:** 📋 DRAFT — Production Monitoring Strategy

## Overview

This guide covers setting up monitoring, logging, metrics, and observability for the Hybrid RAG platform. Effective observability enables:

- **Rapid incident detection** and alerting
- **Root cause analysis** via correlated logs and metrics
- **Performance optimization** based on real data
- **Capacity planning** from historical trends
- **User experience monitoring** and SLA tracking

---

## 🔍 Observability Stack

### Recommended Tools

**Logging:**
- **Development:** Console logs (Python logging module)
- **Production:** ELK Stack (Elasticsearch, Logstash, Kibana) or CloudWatch

**Metrics:**
- **Collection:** Prometheus or Datadog
- **Visualization:** Grafana or Datadog dashboards
- **Alerting:** Prometheus AlertManager or Datadog alerts

**Tracing:**
- **Distributed Tracing:** Jaeger or Datadog APM
- **Span instrumentation:** OpenTelemetry Python SDK

**Error Tracking:**
- **Production:** Sentry or Rollbar
- **Development:** Console + local logging

---

## 📋 Logging Strategy

### Log Levels

```python
import logging

logger = logging.getLogger(__name__)

logger.debug("Detailed operation info")     # Development only
logger.info("Business events")              # Key operations
logger.warning("Recoverable issues")        # Warnings
logger.error("Errors requiring attention")  # Recoverable errors
logger.critical("System failure")           # System-level failures
```

### Recommended Log Level

| Environment | Level | Use Case |
|------------|-------|----------|
| Development | DEBUG | Full diagnostics |
| Staging | INFO | Business events + errors |
| Production | WARNING | Only warnings and errors |

### Structured Logging

Always log structured data for easier searching and analytics:

```python
logger.info(
    "Query processed",
    extra={
        "query": query,
        "results_count": len(results),
        "processing_time_ms": elapsed,
        "cache_hit": was_cache_hit,
        "user_id": user_id,  # When available in v0.2
        "request_id": request_id,
    }
)
```

### Critical Events to Log

**Authentication & Authorization (v0.2+):**
```python
logger.warning("Authentication failed", extra={"user": username})
logger.warning("Authorization denied", extra={"user": user_id, "resource": resource})
```

**Query Operations:**
```python
logger.info("Retrieval started", extra={"query": query[:100], "enable_rerank": enable_rerank})
logger.info("Retrieval completed", extra={"query": query[:100], "results": len(results)})
logger.error("Retrieval failed", extra={"query": query[:100], "error": str(error)})
```

**Cache Operations:**
```python
logger.debug("Cache hit", extra={"key": cache_key, "ttl_remaining": ttl})
logger.debug("Cache miss", extra={"key": cache_key})
logger.warning("Cache error", extra={"operation": "set", "error": str(error)})
```

**Configuration Changes:**
```python
logger.info("Configuration updated", extra={
    "semantic_weight": new_config.semantic_weight,
    "enable_rerank": new_config.enable_rerank,
    "changed_by": user_id  # v0.2
})
```

**System Events:**
```python
logger.info("Service starting", extra={"version": "0.1.0", "cache_backend": "redis"})
logger.warning("Redis connection slow", extra={"latency_ms": 250})
logger.critical("Vector DB unavailable", extra={"error": str(error)})
```

### Log Format

Standard Python logging format:

```
%(asctime)s - %(name)s - %(levelname)s - %(message)s
```

Example:
```
2026-04-22 15:30:45,123 - api - INFO - Query processed
```

### Log Rotation

For file-based logging:

```python
from logging.handlers import RotatingFileHandler

handler = RotatingFileHandler(
    filename='hybrid_rag.log',
    maxBytes=100 * 1024 * 1024,  # 100MB
    backupCount=10               # Keep 10 old files
)
```

---

## 📊 Key Metrics to Track

### System Metrics

**CPU & Memory:**
- Process CPU usage (%)
- Resident memory (MB)
- Virtual memory (MB)
- GC pause time (ms)

**Disk:**
- Disk I/O read/write (MB/s)
- ChromaDB storage size (GB)
- Disk free space (%)

**Network:**
- HTTP connections (active count)
- WebSocket connections (active count)
- Redis connection pool (active/available)
- Network latency (ms)

### Application Metrics

**Request Metrics:**
- Requests per second (QPS)
- Request latency (ms) — p50, p95, p99
- Error rate (%)
- HTTP status code distribution

**Retrieval Metrics:**
- Query processing time (ms)
- Embedding computation time (ms)
- Reranking time (ms)
- Results returned (average count)
- Score distribution (histogram)

**Cache Metrics:**
- Cache hit rate (%)
- Cache miss rate (%)
- Cache eviction rate
- Cache memory usage (MB)
- Redis memory usage (MB)

**Vector DB Metrics:**
- Query latency (ms) — p50, p95, p99
- Collection size (documents)
- Chunk count (total)
- Index size (MB)

**WebSocket Metrics:**
- Active connections (count)
- Connection duration (mean, max)
- Messages per connection
- Error rate (%)

---

## 🎯 Prometheus Metrics

### Setup

Install client library:
```bash
pip install prometheus-client
```

### Integration with FastAPI

```python
from prometheus_client import Counter, Histogram, Gauge
from prometheus_client import CollectorRegistry, generate_latest

# Create metrics
request_count = Counter(
    'hybrid_rag_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'status']
)

request_latency = Histogram(
    'hybrid_rag_request_latency_ms',
    'HTTP request latency',
    ['method', 'endpoint'],
    buckets=(50, 100, 250, 500, 1000, 2500, 5000)
)

active_connections = Gauge(
    'hybrid_rag_active_connections',
    'Active WebSocket connections'
)

cache_hits = Counter(
    'hybrid_rag_cache_hits_total',
    'Total cache hits',
    ['operation']
)

retrieval_time = Histogram(
    'hybrid_rag_retrieval_time_ms',
    'Retrieval operation time',
    buckets=(50, 100, 250, 500, 1000, 2500, 5000)
)

# Endpoint for Prometheus scraping
@app.get("/metrics")
async def metrics():
    return generate_latest()

# Middleware to track requests
@app.middleware("http")
async def track_metrics(request: Request, call_next):
    import time
    start = time.time()
    
    response = await call_next(request)
    
    elapsed = (time.time() - start) * 1000
    request_count.labels(
        method=request.method,
        endpoint=request.url.path,
        status=response.status_code
    ).inc()
    
    request_latency.labels(
        method=request.method,
        endpoint=request.url.path
    ).observe(elapsed)
    
    return response
```

### Prometheus Scrape Config

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'hybrid-rag'
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: '/metrics'
    scrape_interval: 15s
    scrape_timeout: 10s
```

---

## 📈 Grafana Dashboards

### Dashboard 1: Service Health

**Panels:**
- API uptime (%)
- Request throughput (QPS)
- Error rate (%) with alert threshold lines
- Response time (p50, p95, p99)
- Active WebSocket connections
- Cache hit rate (%)

### Dashboard 2: Performance

**Panels:**
- Retrieval latency (histogram)
- Embedding computation time (ms)
- Reranking time (ms)
- Query count distribution (by semantic_weight)
- Results per query (histogram)
- Document count (ChromaDB)

### Dashboard 3: Resource Utilization

**Panels:**
- CPU usage (%)
- Memory usage (MB)
- Disk I/O (MB/s)
- Redis memory (MB)
- Network bandwidth (Mbps)
- Connection pool utilization (%)

### Dashboard 4: Cache Performance

**Panels:**
- Cache hit rate (%) — trend over time
- Cache misses (count)
- Cache evictions (count)
- Redis memory usage (MB)
- Cache operation latency (ms)
- Key distribution (top keys by size)

---

## 🚨 Alerting Rules

### Critical Alerts (Immediate Action Required)

```yaml
groups:
  - name: hybrid-rag-critical
    interval: 30s
    rules:
      # Service down
      - alert: ServiceDown
        expr: up == 0
        for: 1m
        annotations:
          summary: "Hybrid RAG service is down"
          action: "Restart service, check logs"
      
      # High error rate
      - alert: HighErrorRate
        expr: rate(hybrid_rag_requests_total{status=~"5.."}[5m]) > 0.1
        for: 5m
        annotations:
          summary: "Error rate > 10% for 5+ minutes"
          action: "Check application logs"
      
      # Redis unavailable
      - alert: RedisUnavailable
        expr: redis_up == 0
        for: 2m
        annotations:
          summary: "Redis connection lost"
          action: "Check Redis server, verify TLS cert"
      
      # Vector DB issues
      - alert: VectorDBLatencyHigh
        expr: histogram_quantile(0.95, rate(hybrid_rag_retrieval_time_ms_bucket[5m])) > 5000
        for: 5m
        annotations:
          summary: "Vector DB p95 latency > 5s"
          action: "Check ChromaDB status, verify indexes"
      
      # Memory pressure
      - alert: HighMemoryUsage
        expr: process_resident_memory_bytes > 900000000
        for: 5m
        annotations:
          summary: "Memory usage > 900MB for 5+ minutes"
          action: "Check for memory leaks, consider restart"
```

### Important Alerts (Action Needed Within 30 Minutes)

```yaml
  - name: hybrid-rag-important
    interval: 60s
    rules:
      # Low cache hit rate
      - alert: LowCacheHitRate
        expr: hybrid_rag_cache_hits_total / (hybrid_rag_cache_hits_total + hybrid_rag_cache_misses_total) < 0.2
        for: 15m
        annotations:
          summary: "Cache hit rate < 20% for 15+ minutes"
          action: "Investigate cache configuration, query patterns"
      
      # High p99 latency
      - alert: HighP99Latency
        expr: histogram_quantile(0.99, rate(hybrid_rag_request_latency_ms_bucket[5m])) > 2000
        for: 10m
        annotations:
          summary: "P99 request latency > 2000ms"
          action: "Profile slow queries, check resource usage"
      
      # Reranking failures
      - alert: RerankerFailures
        expr: rate(hybrid_rag_reranking_failures_total[5m]) > 0.05
        for: 5m
        annotations:
          summary: "Reranking failures > 5%"
          action: "Check reranker model availability"
      
      # ChromaDB growth rate unusual
      - alert: UnusualGrowthRate
        expr: rate(hybrid_rag_documents_total[1h]) > 1000
        for: 30m
        annotations:
          summary: "Document ingestion rate > 1000/hour"
          action: "Investigate unusual ingestion, check for duplicates"
```

### Informational Alerts (Monitoring & Trending)

```yaml
  - name: hybrid-rag-info
    interval: 5m
    rules:
      # Maintenance window approaching
      - alert: HardwareMaintenanceScheduled
        expr: time() > 1703683200 and time() < 1703710800
        annotations:
          summary: "Scheduled maintenance window active"
      
      # Cache statistics trending
      - alert: CacheTrendingDown
        expr: histogram_quantile(0.5, rate(hybrid_rag_cache_hits_total[1h])) < histogram_quantile(0.5, rate(hybrid_rag_cache_hits_total[1d] offset 1d))
        for: 4h
        annotations:
          summary: "Cache hit rate trending downward over past day"
          action: "Monitor, investigate if trend continues"
```

---

## 🔍 Debugging Guide

### Common Issues & Diagnostics

#### Issue: High Latency

**Investigation:**
```bash
# 1. Check infrastructure metrics
curl http://localhost:9090/api/v1/query?query=process_resident_memory_bytes
curl http://localhost:9090/api/v1/query?query=process_cpu_seconds_total

# 2. Check application metrics
curl http://localhost:8000/metrics | grep "request_latency"

# 3. Check Redis latency
redis-cli --latency

# 4. Check ChromaDB query performance
# Query log analysis in Grafana dashboard

# 5. Profile slow query
# Enable DEBUG logging:
LOG_LEVEL=DEBUG python api.py
```

**Common Causes:**
- Redis connection timeout → Check network, TLS cert
- ChromaDB query slow → Check collection size, indexes
- Embedding computation → Normal, takes 500-2000ms
- High GC pause → Check memory usage

#### Issue: Low Cache Hit Rate

**Investigation:**
```bash
# 1. Check cache statistics
curl http://localhost:8000/cache/stats

# 2. Verify cache backend is connected
redis-cli ping

# 3. Check if cache keys are being generated consistently
# Enable DEBUG logging for cache operations

# 4. Verify TTL setting
grep "CACHE_TTL" .env.production

# 5. Analyze query patterns
# Are queries substantially different each time?
```

**Common Causes:**
- TTL too short → Increase CACHE_TTL_SECONDS
- Queries highly varied → Normal behavior
- Redis disconnected → Restart Redis, check TLS
- Cache injection bug → See SECURITY_COMPLIANCE.md CRIT-001

#### Issue: Memory Leak

**Investigation:**
```bash
# 1. Monitor memory over time
while true; do
  ps aux | grep uvicorn | grep -v grep | awk '{print $6}'
  sleep 60
done

# 2. Check for large objects in memory
python -m memory_profiler api.py

# 3. Check for circular references
python -c "import gc; gc.collect(); print(len(gc.get_objects()))"

# 4. Enable gc debugging
import gc
gc.set_debug(gc.DEBUG_SAVEALL)
```

**Common Causes:**
- ChromaDB cache not cleared → Normal, cleared on restart
- Zustand stores in frontend → Check for circular references
- Event listener leaks → Verify cleanup in useEffect

---

## 🔐 Security Monitoring

### Events to Alert On

**Authentication (v0.2+):**
- Failed login attempts (5+ in 5 minutes)
- Unauthorized API access attempts
- Invalid token usage

**Data Access:**
- Unusual query patterns (high volume, sensitive keywords)
- Bulk data export attempts
- Access from unexpected IPs

**Configuration:**
- Unauthorized configuration changes
- Security setting modifications
- API key or password changes

**System:**
- Unencrypted Redis connections
- SSL/TLS certificate expiration
- Service restart frequency

### Example Security Alert

```yaml
- alert: SuspiciousQueryVolume
  expr: rate(hybrid_rag_requests_total[5m]) > 1000
  for: 2m
  annotations:
    summary: "Unusual query volume (>1000 QPS)"
    action: "Check for attacks, verify legitimate traffic"

- alert: TLSCertificateExpiringSoon
  expr: ssl_cert_expiration_time - time() < 86400 * 30
  annotations:
    summary: "TLS certificate expires in < 30 days"
    action: "Renew certificate immediately"
```

---

## 📞 On-Call Runbooks

### Runbook 1: High Error Rate Response

**Symptom:** Error rate > 10% for 5+ minutes

**Steps:**
1. Check logs: `journalctl -u hybrid-rag.service -n 100 --severity=err`
2. Check Redis: `redis-cli ping`
3. Check ChromaDB: `curl http://localhost:8000/health`
4. Check if configuration is valid: `curl http://localhost:8000/config`
5. Restart service if needed: `sudo systemctl restart hybrid-rag.service`
6. Monitor error rate for 10 minutes
7. If persists, escalate to platform team

### Runbook 2: Memory Leak Detected

**Symptom:** Memory usage > 900MB and growing

**Steps:**
1. Check current memory: `ps aux | grep uvicorn`
2. Gather memory snapshot: `python -m memory_profiler api.py`
3. Identify top objects
4. Schedule service restart during maintenance window
5. Rotate logs: `journalctl --vacuum-time=30d`
6. Monitor memory after restart
7. If recurring, open issue for investigation

### Runbook 3: Cache Unavailable

**Symptom:** Redis connection errors in logs

**Steps:**
1. Check Redis: `redis-cli ping`
2. Check TLS certificate: `openssl s_client -connect redis-host:6380`
3. Check Redis logs: `journalctl -u redis-server -n 50`
4. Restart Redis: `sudo systemctl restart redis-server`
5. Monitor cache stats: `curl http://localhost:8000/cache/stats`
6. Verify cache is working after restart
7. If TLS issue, update certificates

---

## 📚 References

- **Prometheus:** https://prometheus.io/docs/
- **Grafana:** https://grafana.com/docs/
- **Python logging:** https://docs.python.org/3/library/logging.html
- **OpenTelemetry:** https://opentelemetry.io/docs/
- **Sentry:** https://docs.sentry.io/
- **ELK Stack:** https://www.elastic.co/guide/

## 🔗 See Also

- [API Integration](./API_INTEGRATION.md) — Endpoints and responses
- [Deployment Guide](./DEPLOYMENT_PRODUCTION.md) — Production setup
- [Security Compliance](./SECURITY_COMPLIANCE.md) — Security vulnerabilities
