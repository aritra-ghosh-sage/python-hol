# Production Deployment Guide

**Document Version:** 1.0  
**Last Updated:** 2026-04-22  
**Status:** 📋 DRAFT — INTERNAL v0.1 DEPLOYMENT READY, PUBLIC RELEASE BLOCKED

## Overview

This guide covers deploying Hybrid RAG to production environments. As validated in [SECURITY_COMPLIANCE.md](./SECURITY_COMPLIANCE.md), CRIT-001, CRIT-002, and HIGH-001 are already resolved in code. The remaining public-release blockers are CRIT-003 (cache encryption at rest) and the lack of authentication/authorization for write and admin flows. v0.1 deployments are therefore limited to internal, trusted environments.

**Prerequisites:**
- ✅ Resolved fixes already present in code: CRIT-001, CRIT-002, HIGH-001
- ⚠️ Remaining public-release blockers tracked separately: CRIT-003 and v0.2 authentication work
- ✅ Python 3.13+ environment
- ✅ Redis 6.0+ (optional for in-memory cache, required for distributed deployments)
- ✅ Network connectivity to vector database (local or remote)

---

## 🚨 Pre-Deployment: Security Fixes Checklist

Use this checklist to distinguish what is already satisfied in code from what still blocks broader production exposure.

| Issue | Status | Effort | Priority |
|-------|--------|--------|----------|
| CRIT-001: Cache Key Injection | ✅ RESOLVED | 0 hours | **CRITICAL** |
| CRIT-002: Multipart DoS | ✅ RESOLVED | 0 hours | **CRITICAL** |
| CRIT-003: Unencrypted Cache | ❌ UNRESOLVED | 2 hours | **CRITICAL** |
| HIGH-001: Redis TLS Enforcement | ✅ RESOLVED | 0 hours | **HIGH** |

### Remaining Security Work Before Broader Production Exposure

#### Phase 1: Already Satisfied in Current Code
**Effort: 0 hours | Risk: None | Dependencies: None**

1. **CRIT-002: Multipart DoS**
  - File endpoints are already excluded from middleware caching.
  - JSON-only request gating happens before body I/O.
  - Deployment impact: none; present in current code.

2. **CRIT-001: Cache Key Injection**
  - Cache keys are already normalized with canonical JSON serialization.
  - `enable_rerank` is already included in cache identity.
  - Deployment impact: none; present in current code.

3. **HIGH-001: Redis TLS Enforcement**
  - Production config already requires `rediss://` plus authentication.
  - Deployment impact: verify environment settings only.

#### Phase 2: Still Open Before Public or Multi-Tenant Release
**Effort: 2-16 hours | Risk: Medium | Dependencies: Product scope and security posture**

4. **CRIT-003: Unencrypted Cache (2 hours)**
   - Implement Fernet encryption layer in `hybrid_rag/cache.py`
   - Add `CACHE_ENCRYPTION_KEY` environment variable
   - Encrypt values before storing in Redis, decrypt on retrieval
   - Test: Verify encrypted values in Redis, decrypted in application
  - Deploy: Required for sensitive-data or public deployments; optional for strictly internal v0.1 use depending on risk acceptance

5. **AUTH-001: Authentication and Authorization (8-16 hours)**
  - Keep v0.1 deployments internal-only until auth exists.
  - Implement JWT/API-key auth and RBAC in v0.2.
  - Block public or multi-tenant rollout until complete.

---

## 📋 Environment Variables

### Full Environment Variables Reference

```bash
# ========================================
# CACHE CONFIGURATION
# ========================================

# Cache Backend Selection
# Development: 'memory' (in-process TTL cache)
# Production: 'redis' (distributed cache)
CACHE_BACKEND=redis

# Redis Connection URL
# Format: rediss://[user:password@]host:port/database
# Production example: rediss://cache.example.com:6380/0
# CRITICAL: Must use 'rediss://' scheme for TLS in production
REDIS_URL=rediss://prod-redis:6380/0

# Redis Username and Password (alternative to embedding in URL)
# Leave empty if credentials are in REDIS_URL
REDIS_USERNAME=prod_user
REDIS_PASSWORD=<generate-strong-password>

# Redis SSL/TLS Configuration
# Path to CA certificate for verifying Redis server
REDIS_SSL_CERT_PATH=/etc/ssl/certs/redis-ca.crt

# Path to client certificate (mTLS)
# Leave empty if Redis uses CA-only verification
REDIS_SSL_CLIENT_CERT_PATH=/etc/ssl/certs/redis-client.crt

# Path to client private key (mTLS)
REDIS_SSL_CLIENT_KEY_PATH=/etc/ssl/private/redis-client.key

# Verify Redis server certificate
# Set to 'true' in production, 'false' only for development
REDIS_SSL_VERIFY=true

# Cache Encryption Key
# Required for public or sensitive-data deployments once CRIT-003 is addressed.
# Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Never commit this to version control; use a secrets manager.
CACHE_ENCRYPTION_KEY=<generate-fernet-key>

# Cache TTL (Time-To-Live) in seconds
# How long entries remain valid before expiration
# Recommended: 1800 (30 min) for production
CACHE_TTL_SECONDS=1800

# Cache Key Prefix
# Prepended to all cache keys to avoid collisions
# Use unique prefix if multiple instances share Redis
CACHE_KEY_PREFIX=prod_rag_

# Maximum Cache Size (in-memory only, ignored for Redis)
CACHE_MAX_SIZE=10000

# ========================================
# FASTAPI & UVICORN
# ========================================

# API Server Host
# 0.0.0.0 to accept external connections, 127.0.0.1 for local only
API_HOST=0.0.0.0

# API Server Port
API_PORT=8000

# Number of Worker Processes
# Recommended: Number of CPU cores (for high concurrency)
API_WORKERS=4

# ========================================
# CORS & SECURITY
# ========================================

# Allowed CORS Origins
# Production: Specific frontend domains only
# Separate multiple origins with comma
CORS_ORIGINS=https://app.example.com,https://staging.example.com

# ========================================
# LOGGING
# ========================================

# Log Level
# Options: DEBUG, INFO, WARNING, ERROR, CRITICAL
# Recommended for production: INFO or WARNING
LOG_LEVEL=INFO

# ========================================
# VECTOR DATABASE
# ========================================

# Chroma Persistent Storage Path
# Path where ChromaDB stores vector data
# Must be writable directory, preferably on persistent volume
CHROMA_DB_PATH=/data/chromadb

# ========================================
# OPTIONAL: MONITORING & OBSERVABILITY
# ========================================

# Sentry DSN for error tracking (optional)
# SENTRY_DSN=https://key@sentry.example.com/project

# Datadog API Key for APM (optional)
# DATADOG_API_KEY=<your-api-key>

# Application version (for logging and monitoring)
APP_VERSION=0.1.0
```

### Environment Variable Validation

Create an `.env.validation.py` script to validate environment variables at startup:

```python
import os
from pathlib import Path

def validate_production_config():
    """Validate all required environment variables for production."""
    errors = []
    
    # Check required variables
    required_vars = [
        'CACHE_BACKEND',
        'REDIS_URL',
        'REDIS_PASSWORD',
        'CACHE_ENCRYPTION_KEY',
        'API_WORKERS',
        'CORS_ORIGINS',
    ]
    
    for var in required_vars:
        if not os.getenv(var):
            errors.append(f"Missing required environment variable: {var}")
    
    # Validate Redis configuration
    redis_url = os.getenv('REDIS_URL', '')
    if redis_url and not redis_url.startswith('rediss://'):
        errors.append("REDIS_URL must use 'rediss://' scheme for production (TLS required)")
    
    # Validate SSL certificates exist
    if os.getenv('CACHE_BACKEND') == 'redis':
        cert_path = os.getenv('REDIS_SSL_CERT_PATH')
        if cert_path and not Path(cert_path).exists():
            errors.append(f"Redis CA certificate not found: {cert_path}")
    
    # Validate cache encryption key format
    encryption_key = os.getenv('CACHE_ENCRYPTION_KEY', '')
    if encryption_key:
        try:
            from cryptography.fernet import Fernet
            Fernet(encryption_key.encode())
        except Exception as e:
            errors.append(f"Invalid CACHE_ENCRYPTION_KEY format: {e}")
    
    if errors:
        print("❌ Configuration Validation Failed:")
        for error in errors:
            print(f"  - {error}")
        raise RuntimeError("Environment configuration invalid")
    
    print("✅ Configuration Validation Passed")

if __name__ == "__main__":
    validate_production_config()
```

---

## 🔐 Redis TLS Setup

### 1. Generate TLS Certificates (Development/Self-Signed)

```bash
# Create CA certificate (valid for 10 years)
openssl genrsa -out redis-ca.key 2048
openssl req -new -x509 -days 3650 -key redis-ca.key -out redis-ca.crt \
  -subj "/CN=redis-ca"

# Create server certificate
openssl genrsa -out redis-server.key 2048
openssl req -new -key redis-server.key -out redis-server.csr \
  -subj "/CN=redis.example.com"

# Sign server certificate
openssl x509 -req -in redis-server.csr \
  -CA redis-ca.crt -CAkey redis-ca.key -CAcreateserial \
  -out redis-server.crt -days 365

# Create client certificate (for mTLS)
openssl genrsa -out redis-client.key 2048
openssl req -new -key redis-client.key -out redis-client.csr \
  -subj "/CN=redis-client"
openssl x509 -req -in redis-client.csr \
  -CA redis-ca.crt -CAkey redis-ca.key -CAcreateserial \
  -out redis-client.crt -days 365
```

### 2. Configure Redis Server (redis.conf)

```bash
# Enable TLS for client connections
port 0                          # Disable unencrypted port
tls-port 6380                   # TLS port
tls-cert-file /etc/redis/redis-server.crt
tls-key-file /etc/redis/redis-server.key
tls-ca-cert-file /etc/redis/redis-ca.crt

# Require TLS client certificates (mTLS)
tls-client-cert-file /etc/redis/redis-client.crt
tls-client-key-file /etc/redis/redis-client.key

# Optional: Require authentication
requirepass <generate-strong-password>

# Persistence
save 900 1         # Save if 1+ key changed in 900s
appendonly yes     # Append-only file for durability
```

### 3. Restart Redis

```bash
systemctl restart redis-server

# Verify TLS is working
redis-cli --cacert /etc/ssl/certs/redis-ca.crt \
  --cert /etc/ssl/certs/redis-client.crt \
  --key /etc/ssl/private/redis-client.key \
  -p 6380 PING
# Should respond: PONG
```

---

## 📦 Installation & Setup

### Step 1: Environment Setup

```bash
# Create production directory
mkdir -p /opt/hybrid-rag
cd /opt/hybrid-rag

# Create Python virtual environment
python3.13 -m venv venv
source venv/bin/activate

# Copy application files
cp -r /path/to/python-hol/* .

# Install dependencies
pip install -e ".[dev]"
```

### Step 2: Configure Environment

```bash
# Copy environment template
cp .env.local.example .env.production

# Edit for production (use secrets manager for sensitive values)
nano .env.production

# Set required variables (use your actual values)
cat >> .env.production << 'EOF'
CACHE_BACKEND=redis
REDIS_URL=rediss://prod-redis:6380/0
REDIS_PASSWORD=$(aws secretsmanager get-secret-value --secret-id redis-password --query SecretString --output text)
CACHE_ENCRYPTION_KEY=$(aws secretsmanager get-secret-value --secret-id cache-encryption-key --query SecretString --output text)
API_WORKERS=4
CORS_ORIGINS=https://app.example.com
LOG_LEVEL=INFO
EOF

# Validate configuration
python -c "from hybrid_rag.config import CacheSettings; CacheSettings(backend='redis')"
```

### Step 3: Initialize Vector Database

```bash
# Create ChromaDB persistent directory
mkdir -p /data/chromadb
chmod 755 /data/chromadb

# Initialize with sample data (optional)
python -c "
from hybrid_rag import initialize_vector_db, get_sample_documents
from pathlib import Path

# Initialize with sample documents
db_path = Path('/data/chromadb')
db, collection = initialize_vector_db(db_path)
print(f'✅ Vector database initialized at {db_path}')
"
```

### Step 4: Test API Locally

```bash
# Start API server (development, single worker)
uvicorn api:app --host 127.0.0.1 --port 8000 --reload

# In another terminal, test health endpoint
curl http://localhost:8000/health

# Test retrieval
curl -X POST http://localhost:8000/retrieve \
  -H "Content-Type: application/json" \
  -d '{"query": "test query"}'

# View config
curl http://localhost:8000/config

# Check cache stats
curl http://localhost:8000/cache/stats
```

---

## 🚀 Deployment to Production

### Option A: Systemd Service

Create `/etc/systemd/system/hybrid-rag.service`:

```ini
[Unit]
Description=Hybrid RAG API Service
After=network.target redis-server.service
Requires=redis-server.service

[Service]
Type=notify
User=hybrid-rag
WorkingDirectory=/opt/hybrid-rag
Environment="PATH=/opt/hybrid-rag/venv/bin"
EnvironmentFile=/opt/hybrid-rag/.env.production

# Main process
ExecStart=/opt/hybrid-rag/venv/bin/uvicorn \
  api:app \
  --host 0.0.0.0 \
  --port 8000 \
  --workers ${API_WORKERS} \
  --access-log \
  --log-level ${LOG_LEVEL}

# Graceful shutdown (30s timeout before SIGKILL)
ExecStop=/bin/kill -TERM $MAINPID
TimeoutStopSec=30

# Auto-restart on failure (max 5 restarts in 60s)
Restart=on-failure
RestartSec=10
StartLimitBurst=5
StartLimitIntervalSec=60

# Security hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=/opt/hybrid-rag /data/chromadb

[Install]
WantedBy=multi-user.target
```

Deploy:

```bash
# Copy service file
sudo cp hybrid-rag.service /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable and start service
sudo systemctl enable hybrid-rag.service
sudo systemctl start hybrid-rag.service

# Check status
sudo systemctl status hybrid-rag.service

# View logs
sudo journalctl -u hybrid-rag.service -f
```

### Option B: Docker Deployment

Create `Dockerfile`:

```dockerfile
FROM python:3.13-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy application
COPY . .

# Install Python dependencies
RUN pip install --no-cache-dir -e ".[dev]"

# Create data directory
RUN mkdir -p /data/chromadb

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

# Run API server
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
```

Build and run:

```bash
# Build image
docker build -t hybrid-rag:0.1.0 .

# Run container
docker run -d \
  --name hybrid-rag \
  --env-file .env.production \
  -p 8000:8000 \
  -v /data/chromadb:/data/chromadb \
  --restart unless-stopped \
  hybrid-rag:0.1.0

# Check logs
docker logs -f hybrid-rag

# Test health
curl http://localhost:8000/health
```

### Option C: Kubernetes Deployment

Create `k8s/deployment.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: hybrid-rag
  namespace: default
spec:
  replicas: 2
  selector:
    matchLabels:
      app: hybrid-rag
  template:
    metadata:
      labels:
        app: hybrid-rag
    spec:
      containers:
      - name: api
        image: hybrid-rag:0.1.0
        ports:
        - containerPort: 8000
        
        # Environment from secrets
        env:
        - name: CACHE_BACKEND
          value: "redis"
        - name: REDIS_URL
          valueFrom:
            secretKeyRef:
              name: hybrid-rag-secrets
              key: redis-url
        - name: REDIS_PASSWORD
          valueFrom:
            secretKeyRef:
              name: hybrid-rag-secrets
              key: redis-password
        - name: CACHE_ENCRYPTION_KEY
          valueFrom:
            secretKeyRef:
              name: hybrid-rag-secrets
              key: cache-encryption-key
        
        # Resource limits
        resources:
          requests:
            memory: "512Mi"
            cpu: "250m"
          limits:
            memory: "1Gi"
            cpu: "500m"
        
        # Health checks
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 30
        
        readinessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 10
        
        # Volume for ChromaDB
        volumeMounts:
        - name: chromadb-data
          mountPath: /data/chromadb
      
      volumes:
      - name: chromadb-data
        persistentVolumeClaim:
          claimName: chromadb-pvc
```

Deploy:

```bash
# Create secrets
kubectl create secret generic hybrid-rag-secrets \
  --from-literal=redis-url=rediss://prod-redis:6380/0 \
  --from-literal=redis-password=<password> \
  --from-literal=cache-encryption-key=<key>

# Create PersistentVolumeClaim for ChromaDB
kubectl apply -f k8s/pvc.yaml

# Deploy
kubectl apply -f k8s/deployment.yaml

# Check status
kubectl get pods -l app=hybrid-rag
kubectl logs -f deployment/hybrid-rag
```

---

## ✅ Post-Deployment Verification

### Immediate Checks (First 5 minutes)

```bash
# 1. Health check
curl -s http://localhost:8000/health | jq .
# Expected: {"status": "healthy", "retriever_ready": "yes"}

# 2. Configuration verification
curl -s http://localhost:8000/config | jq .
# Expected: Full config object returned

# 3. Cache stats
curl -s http://localhost:8000/cache/stats | jq .
# Expected: layered response with l1_query_cache, l2_embedding_cache, backend_health, timestamp

# 4. Test retrieval
curl -s -X POST http://localhost:8000/retrieve \
  -H "Content-Type: application/json" \
  -d '{"query": "test"}' | jq .

# 5. Redis connectivity
redis-cli -u rediss://user:password@prod-redis:6380/0 PING
# Expected: PONG
```

### Extended Checks (First hour)

```bash
# 1. Verify cache is working
# Send same query twice, check cache hit rate increases
for i in {1..5}; do
  curl -s -X POST http://localhost:8000/retrieve \
    -H "Content-Type: application/json" \
    -d '{"query": "test query"}'
done

curl -s http://localhost:8000/cache/stats | jq '.l1_query_cache.hit_rate'
# Expected: Should be > 0 after repeated identical queries

# 2. Check logs for errors
journalctl -u hybrid-rag.service --since "5 minutes ago" | grep -i error

# 3. Monitor memory usage
ps aux | grep uvicorn | grep -v grep

# 4. Verify TLS on Redis
openssl s_client -connect prod-redis:6380 -cert redis-client.crt -key redis-client.key
# Expected: Connection established, no SSL errors
```

### Security Verification Checklist

```bash
# 1. Verify CORS is restricted
curl -i -H "Origin: https://malicious.com" http://localhost:8000/health
# Expected: No Access-Control-Allow-Origin header OR mismatch error

# 2. Verify cache encryption (spot check Redis)
redis-cli -u rediss://user:password@prod-redis:6380/0 GET hybrid_rag:*
# Expected: Binary data (encrypted), NOT readable JSON

# 3. Verify no sensitive data in logs
journalctl -u hybrid-rag.service | grep -i "password\|token\|secret\|key"
# Expected: No matches (or only legitimate config keys)

# 4. Verify Redis requires TLS
redis-cli -p 6379 PING  # Try unencrypted port
# Expected: Connection refused or timeout (port 6379 should be closed)
```

---

## 📊 Monitoring & Alerting

### Key Metrics to Monitor

**System Health:**
- API response time (p50, p95, p99)
- Error rate (5xx responses)
- Cache hit rate
- Redis connection status
- Memory usage
- CPU utilization

**Business Metrics:**
- Queries per second (QPS)
- Average query response time
- Results returned per query
- Top queries

**Security Metrics:**
- CORS rejection count
- Invalid request count
- Cache key generation errors
- TLS handshake failures

### Prometheus Scrape Config

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'hybrid-rag'
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: '/metrics'  # Requires prometheus integration
```

### Alerts

```yaml
groups:
  - name: hybrid-rag
    rules:
      # High error rate
      - alert: HighErrorRate
        expr: rate(http_requests_total{status=~"5.."}[5m]) > 0.05
        for: 5m
        annotations:
          summary: "High error rate detected"
      
      # Cache hit rate too low
      - alert: LowCacheHitRate
        expr: cache_hit_rate < 0.2
        for: 10m
        annotations:
          summary: "Cache hit rate below 20%"
      
      # Redis unavailable
      - alert: RedisDown
        expr: up{job="redis"} == 0
        for: 1m
        annotations:
          summary: "Redis connection lost"
      
      # Memory pressure
      - alert: HighMemoryUsage
        expr: process_resident_memory_bytes > 800000000  # 800MB
        for: 5m
        annotations:
          summary: "API memory usage above 800MB"
```

---

## 🔄 Rollback Procedures

### Scenario 1: API Version Rollback

```bash
# Stop current service
sudo systemctl stop hybrid-rag.service

# Switch to previous version
cd /opt/hybrid-rag
git checkout v0.0.5  # Previous stable version

# Reinstall dependencies
source venv/bin/activate
pip install -e .

# Restart service
sudo systemctl start hybrid-rag.service

# Verify
curl http://localhost:8000/health
```

### Scenario 2: Configuration Rollback

```bash
# Restore previous .env.production
cp /backups/env.production.2026-04-20 /opt/hybrid-rag/.env.production

# Reload environment
sudo systemctl reload hybrid-rag.service

# Verify
curl http://localhost:8000/config
```

### Scenario 3: Cache Flush (Last Resort)

```bash
# Clear all cache entries (connection will be lost)
redis-cli -u rediss://user:password@prod-redis:6380/0 FLUSHDB

# Monitor cache rebuild
watch -n 1 'curl -s http://localhost:8000/cache/stats | jq .l1_query_cache.size'
```

---

## 📋 Pre-Production Checklist

Before deploying to production, verify:

### Security & Compliance
- [x] CRIT-001, CRIT-002, and HIGH-001 validated as implemented in code
- [ ] CRIT-003 resolved or explicitly risk-accepted for internal-only v0.1 use
- [ ] Public or multi-tenant deployment blocked until authentication and authorization are implemented
- [ ] Redis using TLS (rediss:// scheme) with valid certificates
- [ ] Cache encryption enabled with strong key management
- [ ] CORS origins restricted to known frontend domains
- [ ] All secrets managed via secrets manager (not in .env files)
- [ ] PostgreSQL passwords are 20+ characters, alphanumeric
- [ ] No sensitive data in logs
- [ ] SSL/TLS certificates valid and auto-renewal configured

### Infrastructure
- [ ] Redis cluster running with replication + persistence
- [ ] Persistent volume for ChromaDB data
- [ ] Network security groups restrict unnecessary access
- [ ] Load balancer/reverse proxy configured (if needed)
- [ ] CDN configured for static assets (if applicable)
- [ ] Backups configured for ChromaDB data

### Operations
- [ ] Monitoring and alerting configured
- [ ] Log aggregation (ELK, Splunk, CloudWatch) configured
- [ ] Runbooks created for common issues
- [ ] Incident response plan documented
- [ ] Team trained on deployment procedures
- [ ] Rollback procedures tested
- [ ] Disaster recovery plan in place

### Testing
- [ ] Load testing completed (QPS capacity determined)
- [ ] Failover testing completed (Redis failure scenarios)
- [ ] Security penetration testing completed
- [ ] Integration tests pass in staging environment
- [ ] Cache invalidation tested across scenarios

### Documentation
- [ ] Deployment documentation complete
- [ ] Configuration documentation complete
- [ ] Runbooks for operators created
- [ ] API documentation updated
- [ ] Known limitations documented

---

## 🆘 Troubleshooting

### API Won't Start

**Problem:** Uvicorn fails to start
**Check:**
```bash
# Check for syntax errors
python -m py_compile api.py

# Check imports
python -c "import api; print('OK')"

# Check configuration
python -c "from hybrid_rag.config import CacheSettings; print(CacheSettings())"
```

### Redis Connection Failed

**Problem:** `ConnectionError: Error connecting to Redis`
**Check:**
```bash
# Verify Redis is running
redis-cli -u $REDIS_URL PING

# Check firewall
telnet prod-redis 6380

# Verify credentials
redis-cli -u rediss://user:password@prod-redis:6380/0 PING

# Check TLS certificates
openssl s_client -connect prod-redis:6380 -cert redis-client.crt -key redis-client.key
```

### Cache Misses (Hit Rate Low)

**Problem:** Cache hit rate consistently below 20%
**Cause:** Either cache backend unreachable or identical queries not reaching cache
**Solutions:**
```bash
# 1. Check cache backend status
curl http://localhost:8000/cache/stats

# 2. Verify cache key generation (should be identical for same query)
# Send same query twice with detailed logging

# 3. Check TTL not expiring too quickly
echo $CACHE_TTL_SECONDS  # Should be > 300 seconds

# 4. Verify cache prefix not conflicting
# If multiple instances share Redis, use unique CACHE_KEY_PREFIX
```

### High Memory Usage

**Problem:** Memory usage grows unbounded
**Cause:** Either ChromaDB leaking memory or cache not evicting
**Solutions:**
```bash
# 1. Check max cache size is set
echo $CACHE_MAX_SIZE  # Should be <= 10000

# 2. Check ChromaDB isn't loading entire vector DB into memory
# Verify ChromaDB is using disk storage, not RAM

# 3. Monitor garbage collection
python -c "import gc; gc.collect()" # Force GC, check if memory drops

# 4. Restart service if stuck
sudo systemctl restart hybrid-rag.service
```

---

## 📞 Support & Escalation

For production issues:

1. **Check logs first:** `journalctl -u hybrid-rag.service -n 100`
2. **Run health check:** `curl http://localhost:8000/health`
3. **Check monitoring:** Prometheus, Grafana, or alerting system
4. **Review runbooks:** Common issues documented in operations guide
5. **Escalate if:** Issue persists >30 min or requires code changes

**Emergency contacts:**
- On-call engineer: [TODO]
- Platform team: [TODO]
- Database team: [TODO]

---

## 📚 See Also

- [Security Compliance](./SECURITY_COMPLIANCE.md) — Security vulnerabilities and fixes
- [API Integration](./API_INTEGRATION.md) — API endpoints and usage
- [Library Design](./LIBRARY_DESIGN.md) — Architecture and components
- [CACHE_DEPLOYMENT.md](./CACHE_DEPLOYMENT.md) — Detailed caching deployment guide
- [MONITORING_OBSERVABILITY.md](./MONITORING_OBSERVABILITY.md) — Monitoring setup (when available)
