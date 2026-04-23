# WebSocket-Only Retrieval Migration - Rollback Runbook

**Document Version:** 1.0
**Last Updated:** 2026-04-23
**Applicable to:** Hybrid RAG v1.0.0+
**Migration Reference:** `docs/plan/20260423-ws-only-retrieval-deprecation/`

---

## Table of Contents

1. [Overview](#overview)
2. [Decision Gates and Approval Trail](#decision-gates-and-approval-trail)
3. [Stage-Specific Rollback Procedures](#stage-specific-rollback-procedures)
4. [Rollback Validation Checklist](#rollback-validation-checklist)
5. [Monitoring During Rollback](#monitoring-during-rollback)
6. [Post-Rollback Operations](#post-rollback-operations)
7. [Escalation Contacts](#escalation-contacts)

---

## Overview

### Purpose

This runbook provides **executable, stage-specific procedures** for rolling back the WebSocket-only retrieval migration (Tasks T01-T11) in case of production incidents or unforeseen issues.

### When to Use This Runbook

Execute a rollback if any of the following conditions occur:

- **Critical Production Incident**: WebSocket `/ws/chat` endpoint experiencing >5% error rate for >10 minutes
- **Data Loss Detection**: Document retrieval returning incorrect or incomplete results
- **Performance Degradation**: Mean retrieval latency increases >200ms from baseline
- **Security Incident**: Vulnerability discovered in WebSocket implementation
- **Business Decision**: Strategic pivot requiring restoration of REST endpoints

### Rollback Philosophy

- **Fail-Safe**: Rollback procedures preserve data integrity and service availability
- **Reversible**: All changes can be undone without data loss
- **Executable**: Operators can execute rollback using this runbook alone (no tribal knowledge required)
- **Validated**: Each rollback stage includes verification checkpoints

---

## Decision Gates and Approval Trail

### Original Approval Chain

All decision gates from the migration project are documented here for auditability:

| Gate | Date | Decision | Approver | Evidence |
|------|------|----------|----------|----------|
| **T07 - Go/No-Go for `/retrieve` Removal** | 2026-04-23 | ✅ GO | @aritra-ghosh-sage | `docs/plan/.../T07-gate-record.md` |
| **T08 - Execute Endpoint Removal** | 2026-04-23 | ✅ EXECUTED | Engineering | PR #36 merged |
| **T09 - Enforce Allowlist Policy** | 2026-04-23 | ✅ EXECUTED | Engineering | PR #38 merged |
| **T11 - Test Rationalization** | 2026-04-23 | ✅ KEEP ALL | QA | PR #40 merged |
| **OPTB-011 - Rollout Risk Review (Wave 6)** | 2026-04-23 | ✅ SIGNED OFF | Operations | `docs/plan/.../OPTB-011-rollout-risk-review.md` |

### Rollback Decision Authority

| Stage | Approval Required | Authority |
|-------|-------------------|-----------|
| **Development/Staging** | Team Lead | Engineering Manager |
| **Production (Low-Impact)** | Incident Commander + Platform Lead | On-call Incident Commander |
| **Production (High-Impact)** | Incident Commander + VP Engineering | VP Engineering or designee |

**Escalation Path**: Team Lead → Engineering Manager → VP Engineering → CTO

---

## Stage-Specific Rollback Procedures

### Pre-Rollback Checklist

Before initiating any rollback, complete these steps:

- [ ] **Identify Impact Scope**: Development / Staging / Production
- [ ] **Capture Current State**: Take database backup and log snapshot
- [ ] **Notify Stakeholders**: Alert engineering team via Slack/PagerDuty
- [ ] **Create Incident Ticket**: Document rollback reason and approver
- [ ] **Verify Rollback Tag Exists**: Confirm `pre-retrieve-removal-v1` tag is available

```bash
# Verify rollback tag exists
git tag | grep pre-retrieve-removal-v1
# Expected output: pre-retrieve-removal-v1

# Check tag details
git show pre-retrieve-removal-v1 --no-patch
# Expected commit: a8e3ec7 (T05: Align HTTP middleware scope for transition period)
```

---

### Stage 1: Development Environment Rollback

**Scope**: Local developer machines and development servers
**Estimated Time**: 5-10 minutes
**Risk**: LOW (no user impact)

#### Procedure

1. **Stop Development Server**
   ```bash
   # If running with uvicorn
   pkill -f "uvicorn api:app"

   # If running in Docker
   docker-compose down
   ```

2. **Checkout Pre-Removal State**
   ```bash
   cd /path/to/python-hol
   git fetch --all --tags
   git checkout pre-retrieve-removal-v1
   ```

3. **Verify Rollback Code State**
   ```bash
   # Confirm /retrieve endpoint exists in api.py
   grep -n "POST.*retrieve" api.py
   # Expected: Line match showing @app.post("/retrieve", ...)

   # Confirm QueryCacheMiddleware exists
   grep -n "QueryCacheMiddleware" api_middleware.py
   # Expected: Multiple line matches
   ```

4. **Reinstall Dependencies (if needed)**
   ```bash
   source .venv/bin/activate
   pip install -e .
   ```

5. **Restart Development Server**
   ```bash
   uvicorn api:app --reload --host 0.0.0.0 --port 8000
   ```

6. **Validate Rollback** (See [Rollback Validation Checklist](#rollback-validation-checklist))

---

### Stage 2: Staging Environment Rollback

**Scope**: Pre-production staging environment
**Estimated Time**: 15-20 minutes
**Risk**: MEDIUM (internal testing impact only)

#### Procedure

1. **Notify QA Team**
   ```bash
   # Post to #engineering-staging Slack channel
   "🚨 STAGING ROLLBACK IN PROGRESS: Rolling back to pre-WS-only state. ETA: 20 minutes."
   ```

2. **Capture Current Staging State**
   ```bash
   # SSH into staging server
   ssh staging-server

   # Backup current deployment
   cd /opt/hybrid-rag
   git rev-parse HEAD > /tmp/rollback-from-commit.txt

   # Capture current cache stats
   curl http://localhost:8000/cache/stats | jq . > /tmp/pre-rollback-cache-stats.json
   ```

3. **Stop Staging Services**
   ```bash
   # If using systemd
   sudo systemctl stop hybrid-rag-api

   # If using Docker
   docker-compose -f docker-compose.staging.yml down
   ```

4. **Rollback Code**
   ```bash
   cd /opt/hybrid-rag
   git fetch --all --tags
   git checkout pre-retrieve-removal-v1
   ```

5. **Clear Cache (Force Fresh State)**
   ```bash
   # If using Redis
   redis-cli FLUSHDB

   # If using in-memory cache, skip (cleared on restart)
   ```

6. **Restart Services**
   ```bash
   # If using systemd
   sudo systemctl start hybrid-rag-api
   sudo systemctl status hybrid-rag-api

   # If using Docker
   docker-compose -f docker-compose.staging.yml up -d
   ```

7. **Validate Rollback** (See [Rollback Validation Checklist](#rollback-validation-checklist))

8. **Notify QA Team - Complete**
   ```bash
   "✅ STAGING ROLLBACK COMPLETE: REST /retrieve endpoint restored. Please re-test affected features."
   ```

---

### Stage 3: Production Environment Rollback

**Scope**: Live production environment
**Estimated Time**: 30-45 minutes
**Risk**: HIGH (user-facing impact)

#### Pre-Production Rollback Approvals

- [ ] **Incident Commander Approval**: Documented in incident ticket
- [ ] **Platform Lead Approval**: Confirmed via Slack/PagerDuty
- [ ] **VP Engineering Approval** (if high-impact): Email or Slack confirmation

#### Procedure

1. **Activate Incident Response**
   ```bash
   # Page on-call team
   PagerDuty: Trigger "Production Rollback - WS-Only Migration"

   # Post to #incidents Slack channel
   "🚨 PRODUCTION ROLLBACK INITIATED: WebSocket-only retrieval migration. ETA: 45 minutes."
   ```

2. **Capture Production Metrics Baseline**
   ```bash
   # SSH into production primary instance
   ssh production-primary

   # Capture metrics
   curl http://localhost:8000/cache/stats | jq . > /tmp/prod-rollback-cache-stats-$(date +%s).json
   curl http://localhost:8000/health | jq . > /tmp/prod-rollback-health-$(date +%s).json

   # Capture error rate from monitoring dashboard
   # Export Prometheus/Grafana dashboard for last 1 hour
   ```

3. **Rolling Rollback (Zero-Downtime)**

   **For Multi-Instance Deployment (Recommended):**

   ```bash
   # Rollback one instance at a time to maintain availability

   # Instance 1
   ssh production-instance-1
   cd /opt/hybrid-rag
   git fetch --all --tags
   git checkout pre-retrieve-removal-v1
   sudo systemctl restart hybrid-rag-api

   # Wait 2 minutes and verify health
   curl http://localhost:8000/health
   # If healthy, proceed to next instance

   # Instance 2
   ssh production-instance-2
   # Repeat checkout and restart

   # Instance N
   # Continue for all instances
   ```

   **For Single-Instance Deployment:**

   ```bash
   # Accept brief downtime (~30 seconds)
   ssh production-server
   cd /opt/hybrid-rag

   # Stop service
   sudo systemctl stop hybrid-rag-api

   # Rollback code
   git fetch --all --tags
   git checkout pre-retrieve-removal-v1

   # Clear cache for fresh state
   redis-cli -h production-redis FLUSHDB

   # Restart service
   sudo systemctl start hybrid-rag-api
   sudo systemctl status hybrid-rag-api
   ```

4. **Verify Load Balancer Health Checks**
   ```bash
   # Check all instances reporting healthy
   curl http://load-balancer/health

   # Expected: All instances return 200 OK
   ```

5. **Validate Rollback** (See [Rollback Validation Checklist](#rollback-validation-checklist))

6. **Monitor Production Metrics (15 minutes)**

   Watch these metrics for 15 minutes post-rollback:

   - **Error Rate**: Should return to <1%
   - **Latency (p95)**: Should return to baseline (<1000ms)
   - **Cache Hit Rate**: Should stabilize at 10-30%
   - **Request Rate**: Should match pre-incident levels

7. **Notify Stakeholders - Complete**
   ```bash
   # Post to #incidents
   "✅ PRODUCTION ROLLBACK COMPLETE: REST /retrieve endpoint restored. Monitoring metrics for 15 minutes. Incident ticket: INC-12345"
   ```

---

## Rollback Validation Checklist

Execute these validation steps after every rollback (Development, Staging, Production):

### Health Check

- [ ] **API Health**: `GET /health` returns `200 OK`
  ```bash
  curl http://localhost:8000/health | jq .
  # Expected: {"status": "healthy", "retriever_ready": "yes"}
  ```

- [ ] **REST Endpoint Restored**: `POST /retrieve` returns `200 OK`
  ```bash
  curl -X POST http://localhost:8000/retrieve \
    -H "Content-Type: application/json" \
    -d '{"query": "test query"}' | jq .
  # Expected: {"query": "test query", "results": [...], "total_results": N}
  ```

- [ ] **WebSocket Still Works**: `/ws/chat` accepts connections
  ```bash
  echo '{"query": "test query"}' | websocat ws://localhost:8000/ws/chat
  # Expected: Status message + results message
  ```

### Cache Validation

- [ ] **Cache Stats Endpoint**: `GET /cache/stats` returns `200 OK`
  ```bash
  curl http://localhost:8000/cache/stats | jq .
  # Expected: Full stats object with l1_query_cache and l2_embedding_cache
  ```

- [ ] **Cache Middleware Active**: REST requests show `X-Cache` header
  ```bash
  curl -v -X POST http://localhost:8000/retrieve \
    -H "Content-Type: application/json" \
    -d '{"query": "cache test"}' 2>&1 | grep "X-Cache"
  # Expected: X-Cache: MISS (first request) or X-Cache: HIT (second request)
  ```

### Admin Endpoints

- [ ] **Config Endpoint**: `GET /config` returns `200 OK`
  ```bash
  curl http://localhost:8000/config | jq .
  ```

- [ ] **Documents Endpoint**: `POST /documents` returns `200 OK`
  ```bash
  curl -X POST http://localhost:8000/documents \
    -H "Content-Type: application/json" \
    -d '{"source_type": "text", "content": "test", "source_label": "test"}' | jq .
  ```

### Test Suite

- [ ] **Critical Path Tests**: Run WS critical path tests
  ```bash
  pytest tests/test_ws_retrieval_critical_path.py -v
  # Expected: 7/7 tests passing
  ```

- [ ] **Middleware Tests**: Run cache middleware tests
  ```bash
  pytest tests/test_query_cache_middleware.py -v
  # Expected: All tests passing (47 tests in pre-removal state)
  ```

---

## Monitoring During Rollback

### Key Metrics to Watch

| Metric | Healthy Threshold | Alert Threshold |
|--------|------------------|-----------------|
| **Error Rate** | < 1% | > 5% |
| **Latency (p95)** | < 1000ms | > 1500ms |
| **Cache Hit Rate** | 10-30% | < 5% (investigate) |
| **WebSocket Connections** | Stable | Sudden drop >50% |
| **REST Requests** | Stable after rollback | 0 requests (endpoint broken) |

### Dashboard Links

- **Production Metrics**: `https://grafana.company.com/d/hybrid-rag-prod`
- **Cache Statistics**: `http://production-lb/cache/stats`
- **Error Logs**: `https://logging.company.com/search?app=hybrid-rag&level=error`

### Alert Configuration

Ensure these alerts are active during rollback:

- `HybridRAG - Error Rate > 5%` → PagerDuty critical
- `HybridRAG - Latency p95 > 1500ms` → PagerDuty warning
- `HybridRAG - Cache Hit Rate < 5%` → Slack notification

---

## Post-Rollback Operations

### Immediate Actions (0-24 hours)

1. **Root Cause Analysis**
   - Document why rollback was necessary
   - Identify specific failure mode (error logs, metrics)
   - Determine if issue was code, config, or infrastructure

2. **Update Incident Ticket**
   - Record rollback completion time
   - Link to monitoring dashboards
   - Document validation results

3. **Stakeholder Communication**
   - Engineering team: Slack update in #engineering
   - Product team: Email summary of impact
   - Customer support: If customer-facing, update status page

4. **Re-Enable Monitoring Baselines**
   - Update Grafana dashboards to reflect pre-WS-only state
   - Adjust alert thresholds if needed
   - Re-enable any alerts disabled during migration

### Follow-Up Actions (1-7 days)

1. **Post-Mortem Meeting**
   - Schedule within 48 hours of rollback
   - Attendees: Engineering, QA, Platform, Product
   - Outcome: Documented lessons learned and action items

2. **Fix Planning**
   - Create tickets for identified issues
   - Prioritize fixes based on severity
   - Plan re-migration timeline (if applicable)

3. **Documentation Updates**
   - Update runbook with lessons learned
   - Add new edge cases to test suite
   - Document any workarounds applied

4. **QA Re-Testing**
   - Execute full regression suite
   - Verify no side effects from rollback
   - Confirm cache behavior is stable

### Long-Term Actions (1-4 weeks)

1. **Re-Migration Assessment**
   - Determine if WS-only migration should be retried
   - Identify additional safeguards needed
   - Update migration plan with new controls

2. **Architectural Review**
   - Evaluate if rollback revealed design flaws
   - Consider alternative approaches
   - Document decision in ADR (Architecture Decision Record)

---

## Escalation Contacts

### Primary Contacts

| Role | Name | Contact | Availability |
|------|------|---------|--------------|
| **Incident Commander** | On-call rotation | PagerDuty: `hybrid-rag-oncall` | 24/7 |
| **Engineering Manager** | @aritra-ghosh-sage | Slack: `@aritra` | Business hours |
| **Platform Lead** | TBD | Email: `platform@company.com` | Business hours |
| **VP Engineering** | TBD | Email: `vp-eng@company.com` | Critical incidents only |

### Escalation Thresholds

- **Level 1 (Team Lead)**: Development/Staging rollbacks, low-impact production issues
- **Level 2 (Engineering Manager)**: Production rollbacks with <10% user impact
- **Level 3 (VP Engineering)**: Production rollbacks with >10% user impact or >1 hour downtime

### External Vendor Contacts

- **Redis Support**: If cache backend issues detected during rollback
- **AWS Support**: If infrastructure issues (EC2, Load Balancer) detected
- **Monitoring Vendor** (Datadog/New Relic): If observability gaps identified

---

## Appendix: Historical Rollback Reference

### Pre-Removal Git Tag

- **Tag Name**: `pre-retrieve-removal-v1`
- **Commit SHA**: `a8e3ec7`
- **Commit Message**: `T05: Align HTTP middleware scope for transition period (#33)`
- **Date**: 2026-04-23
- **Branch**: Merged into `main` via PR #33

### File State Verification

Expected file states after rollback to `pre-retrieve-removal-v1`:

| File | Expected State |
|------|---------------|
| `api.py` | Contains `@app.post("/retrieve", ...)` handler |
| `api_middleware.py` | Contains `QueryCacheMiddleware` class (full file) |
| `tests/test_query_cache_middleware.py` | Exists (47 tests) |
| `tests/test_deprecation_markers.py` | Exists (3 tests) |
| `docs/HTTP_ENDPOINT_ALLOWLIST.md` | Does NOT exist (created in T09) |

### Rollback Smoke Test Script

Use this script to quickly validate rollback success:

```bash
#!/bin/bash
# rollback-smoke-test.sh

set -e

API_URL="${API_URL:-http://localhost:8000}"

echo "🔍 Validating rollback to pre-WS-only state..."

# 1. Health check
echo "✓ Checking /health..."
curl -sf "$API_URL/health" > /dev/null || { echo "❌ Health check failed"; exit 1; }

# 2. REST /retrieve endpoint exists
echo "✓ Checking /retrieve endpoint..."
curl -sf -X POST "$API_URL/retrieve" \
  -H "Content-Type: application/json" \
  -d '{"query": "test"}' > /dev/null || { echo "❌ /retrieve endpoint missing"; exit 1; }

# 3. X-Cache header present
echo "✓ Checking X-Cache header..."
CACHE_HEADER=$(curl -sf -X POST "$API_URL/retrieve" \
  -H "Content-Type: application/json" \
  -d '{"query": "cache test"}' -v 2>&1 | grep -i "X-Cache" || echo "")
[[ -n "$CACHE_HEADER" ]] || { echo "❌ X-Cache header missing"; exit 1; }

# 4. Cache stats endpoint
echo "✓ Checking /cache/stats..."
curl -sf "$API_URL/cache/stats" > /dev/null || { echo "❌ Cache stats failed"; exit 1; }

echo "✅ Rollback validation PASSED"
```

---

**Document Status:** ✅ Approved for Operational Use
**Maintained By:** Platform Engineering Team
**Last Rollback Drill:** Never (document created 2026-04-23)
**Next Review Date:** 2026-07-23 (quarterly review)
