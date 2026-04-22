# Security Compliance & Vulnerability Management

**Document Version:** 1.0  
**Last Updated:** 2026-04-22  
**Status:** ⚠️ DRAFT — VALIDATED AGAINST CURRENT CODE

## Overview

This document catalogs known security vulnerabilities, compliance gaps, and remediation roadmap for the Hybrid RAG platform. This version has been validated against the current implementation on 2026-04-22. Three previously documented findings are already resolved in code; the remaining open gaps are cache encryption at rest and the deliberate v0.1 authentication scope decision.

## Executive Summary

| Category | Status | Finding |
|----------|--------|---------|
| **Critical Security Issues** | 🟢 2 OF 3 FIXED | CRIT-001 ✅ FIXED, CRIT-002 ✅ FIXED, CRIT-003 ❌ OPEN |
| **High Severity Issues** | 🟢 FIXED | HIGH-001 (TLS enforcement) ✅ RESOLVED |
| **Authentication/Authorization** | ❌ NOT IMPLEMENTED | Deliberately deferred to v0.2; v0.1 must be internal use only |
| **OWASP Coverage** | 🟡 PARTIAL | A05 cache-key issue fixed; A04 cache encryption and A01 access control remain open |
| **Production Readiness** | 🟡 CONDITIONAL | Acceptable for internal v0.1 use; public production requires auth and security hardening |

---

## 🔴 CRITICAL SECURITY ISSUES

### CRIT-001: Cache Key Injection Vulnerability

**Severity:** CRITICAL (95% confidence)  
**Component:** `api_middleware.py` — `_generate_cache_key()` method  
**OWASP:** A05 (Injection)  
**Impact:** Cache bypass, cache poisoning, information disclosure  
**Status:** ✅ RESOLVED IN CURRENT CODE  
**Validated Against:** `api_middleware.py`

#### Resolution

This issue is already fixed in the current implementation. The middleware parses and canonicalizes JSON before hashing, and includes `enable_rerank` in the key so logically distinct requests cannot collide.

```python
decoded_body = body.decode("utf-8")
body_data: Any = json.loads(decoded_body)
canonical_json = json.dumps(
    body_data,
    sort_keys=True,
    separators=(",", ":"),
)
key_data = f"{canonical_json}:{str(enable_rerank)}"
key_hash = hashlib.sha256(key_data.encode("utf-8")).hexdigest()
```

#### Validation Notes

- Semantically identical JSON payloads now hash to the same cache key.
- The implementation falls back to hashing raw bytes only for malformed payloads.
- `enable_rerank` is part of cache identity, preventing cross-mode cache reuse.

---

### CRIT-002: Multipart Upload DoS via Response Caching

**Severity:** CRITICAL (90% confidence)  
**Component:** `api_middleware.py` — cache exclusion list  
**OWASP:** A05 (Injection) + Denial of Service  
**Impact:** Memory exhaustion, OOM crashes, service disruption  
**Status:** ✅ RESOLVED IN CURRENT CODE  
**Validated Against:** `api_middleware.py`

#### Resolution

This issue is already fixed in the current implementation. Upload and source-management endpoints are excluded from response caching, and the middleware performs a header-only eligibility gate before any request body read.

```python
self.excluded_paths: List[str] = excluded_paths or [
    "/health",
    "/config",
    "/ingest",
    "/documents",
    "/documents/sources",
    "/cache/stats",
]
```

#### Validation Notes

- File upload endpoints are not cache-eligible.
- The middleware only caches `POST /retrieve` requests with JSON content types.
- Non-JSON and excluded-path requests are rejected before body I/O.

---

### CRIT-003: Unencrypted Cache at Rest

**Severity:** IMPORTANT (88% confidence)  
**Component:** `hybrid_rag/cache.py` — `RedisCache` class  
**OWASP:** A04 (Cryptographic Failures)  
**Impact:** Information disclosure, sensitive data exposure  
**Effort to Fix:** 2 hours  
**Assigned To:** [TODO]

#### Problem

Redis stores full `RetrievalResponse` objects as unencrypted JSON. If Redis is exposed on internal network or has weak authentication, all cached search results and source documents are readable:

```python
# Current behavior: stores as plain JSON in Redis
cache_entry = json.dumps({
    "query": "sensitive query about financial risks",
    "results": [
        {
            "text": "Confidential financial document content...",
            "source": "internal://financial-2024.pdf",
            "score": 0.95
        }
    ]
})
redis.set(cache_key, cache_entry, ex=3600)

# Anyone with Redis access can read:
redis.get(cache_key)
# → Returns unencrypted JSON with sensitive content
```

#### Root Cause

No encryption layer in `RedisCache` implementation. Relying on network isolation / Redis AUTH, which are insufficient for highly sensitive data.

#### Recommended Fix

Encrypt cache values using Fernet (symmetric encryption):

```python
from cryptography.fernet import Fernet
import os

class RedisCache(CacheBackend):
    """Redis-backed cache with optional encryption at rest."""
    
    def __init__(
        self,
        redis_url: str,
        encryption_key: Optional[str] = None,
        ttl_seconds: int = 3600
    ):
        """Initialize Redis cache.
        
        Args:
            redis_url: Redis connection URL (redis:// or rediss://)
            encryption_key: Base64-encoded Fernet key for encryption at rest.
                           If None, no encryption (development only).
            ttl_seconds: Default cache TTL in seconds
        """
        self.redis_client = redis.from_url(redis_url, decode_responses=False)
        self.ttl_seconds = ttl_seconds
        
        if encryption_key:
            try:
                self._cipher = Fernet(encryption_key.encode())
                self._encrypted = True
                logger.info("Redis cache initialized with encryption enabled")
            except Exception as e:
                logger.error(f"Invalid encryption key: {e}")
                raise ValueError(f"Invalid Fernet encryption key: {e}")
        else:
            self._cipher = None
            self._encrypted = False
            logger.warning("Redis cache initialized WITHOUT encryption (development only)")
    
    def get(self, key: str) -> Optional[Any]:
        """Retrieve and decrypt value from Redis."""
        try:
            cached_value = self.redis_client.get(key)
            if cached_value is None:
                return None
            
            # Decrypt if enabled
            if self._encrypted:
                cached_value = self._cipher.decrypt(cached_value)
            
            return json.loads(cached_value.decode() if isinstance(cached_value, bytes) else cached_value)
        except Exception as e:
            logger.error(f"Cache get failed for key {key}: {e}")
            return None
    
    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        """Encrypt and store value in Redis."""
        try:
            json_data = json.dumps(value).encode()
            
            # Encrypt if enabled
            if self._encrypted:
                json_data = self._cipher.encrypt(json_data)
            
            ttl = ttl_seconds or self.ttl_seconds
            self.redis_client.setex(key, ttl, json_data)
        except Exception as e:
            logger.error(f"Cache set failed for key {key}: {e}")
            # Fail open: cache issue doesn't break requests
```

Configuration via environment variable:

```python
# .env.local or deployment config
CACHE_BACKEND=redis
REDIS_URL=rediss://redis.example.com:6379
CACHE_ENCRYPTION_KEY=your-base64-encoded-fernet-key
# Generate key with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Usage in `create_cache_backend()`:

```python
def create_cache_backend(settings: CacheSettings) -> CacheBackend:
    """Factory for cache backends."""
    if settings.backend == "redis":
        encryption_key = os.getenv("CACHE_ENCRYPTION_KEY")  # Optional, defaults to None
        return RedisCache(
            redis_url=settings.redis_url,
            encryption_key=encryption_key,
            ttl_seconds=settings.ttl_seconds
        )
    elif settings.backend == "memory":
        return InMemoryCache(max_size=settings.max_size)
    else:
        raise ValueError(f"Unknown cache backend: {settings.backend}")
```

#### Verification Test

```python
def test_redis_cache_encryption():
    """Verify cache values are encrypted at rest."""
    encryption_key = Fernet.generate_key().decode()
    cache = RedisCache(
        redis_url="redis://localhost:6379",
        encryption_key=encryption_key
    )
    
    # Store a value
    test_data = {"query": "sensitive", "results": ["confidential"]}
    cache.set("test_key", test_data)
    
    # Verify it's encrypted in Redis (raw value should not be JSON)
    raw_value = redis_client.get("test_key")
    assert not raw_value.decode().startswith("{"), "Value not encrypted!"
    
    # Verify decryption works
    retrieved = cache.get("test_key")
    assert retrieved == test_data, "Decrypted value doesn't match"
```

#### Timeline

- **Sprint planning:** Add to roadmap (2-hour task)
- **Implementation:** Code + tests
- **Before production:** Must be deployed with generated encryption keys

---

### HIGH-001: Missing Redis TLS Enforcement

**Severity:** HIGH (85% confidence)  
**Component:** `hybrid_rag/config.py` — `CacheSettings.__post_init__()`  
**OWASP:** A04 (Cryptographic Failures)  
**Impact:** Network eavesdropping, credential theft, data interception  
**Status:** ✅ RESOLVED IN CURRENT CODE  
**Validated Against:** `hybrid_rag/config.py`

#### Resolution

This issue is already fixed in the current implementation. Production Redis settings are validated during `CacheSettings` initialization and must use TLS plus authentication.

```python
environment = os.getenv("ENVIRONMENT", "").strip().lower()
if environment == "production" and self.backend == "redis" and self.redis_url:
    parsed_redis_url = urlparse(self.redis_url)
    if parsed_redis_url.scheme != "rediss":
        raise ValueError(
            "Production Redis URL must use TLS with the 'rediss://' scheme. "
            f"Got redis_url='{self.redis_url}'"
        )

    if not parsed_redis_url.password:
        raise ValueError(
            "Production Redis URL must include authentication credentials/password. "
            f"Got redis_url='{self.redis_url}'"
        )
```

#### Validation Notes

- `ENVIRONMENT=production` activates Redis transport validation.
- Non-TLS `redis://` URLs are rejected.
- Passwordless production Redis URLs are rejected.

---

## AUTHENTICATION & AUTHORIZATION GAP

### AUTH-001: No Authentication/Authorization Implemented

**Severity:** CRITICAL  
**Status:** ❌ NOT IMPLEMENTED  
**OWASP:** A01 (Broken Access Control), A07 (Authentication Failures)  
**Impact:** All endpoints publicly accessible without authentication  
**Recorded Decision:** v0.1 remains internal-only; authentication and authorization are deferred to v0.2.

#### Issue

Product PRD (v0.1) defines role-based access control (RBAC) with user roles:
- **End user:** Can submit queries, view results
- **Knowledge operator:** Can ingest sources, manage content
- **Platform administrator:** Can view/update config, cache settings

**Current Reality:** All endpoints are public. No authentication, no role checks. Anyone can call any endpoint.

```python
# Current state: NO AUTH on any endpoint
@app.post("/retrieve")
async def retrieve(request: RetrievalRequest):
    # Anyone can call this with any query
    return retriever.retrieve(request.query)

@app.post("/documents")
async def add_documents(request: DocumentIngestionRequest):
    # Anyone can ingest malicious documents
    return vectordb.ingest(request.documents)

@app.put("/config")
async def update_config(request: ConfigUpdateRequest):
    # Anyone can misconfigure the retriever
    return update_retriever_config(request)
```

#### Recorded Decision

Choose one of two paths:

**Option A: Implement RBAC (Recommended for v0.2)**
- Implement JWT-based authentication
- Add role middleware  
- Protect endpoints with role checks
- Effort: 8-16 hours
- Timeline: Next sprint

**Option B: Descope Auth to Future Release (v0.2+)**
- Update PRD to remove RBAC from v0.1 scope
- Document that v0.1 is for **development/internal use only**
- Flag as security issue to resolve before public/multi-tenant deployment
- Effort: 1 hour (documentation only)
- Timeline: Immediate

#### Recommendation

**For this release (v0.1):** Choose Option B — descope auth, document as "internal use only"  
**For next release (v0.2):** Implement Option A with full RBAC

---

## OWASP Coverage Matrix

| OWASP 2025 Category | Finding | Status |
|---|---|---|
| **A01: Broken Access Control** | No RBAC; all endpoints public | ❌ NOT IMPLEMENTED |
| **A02: Security Misconfiguration** | Redis TLS enforced in production; other deployment review still required | 🟡 PARTIAL |
| **A03: Supply Chain Failures** | Dependencies tracked; npm audit passing | ✅ PASSING |
| **A04: Cryptographic Failures** | Cache at rest unencrypted; TLS enforced in production | 🟡 PARTIAL |
| **A05: Injection** | Cache-key normalization fixed; general input hardening remains | 🟡 PARTIAL |
| **A06: Insecure Design** | No threat model; resilience gaps documented | 🟡 PLANNED |
| **A07: Auth Failures** | Zero auth implementation despite PRD | ❌ NOT IMPLEMENTED |
| **A08: Data Integrity Failures** | Cache key normalization present in middleware | ✅ PASSING |
| **A09: Logging & Alerting** | Basic logging present; no alerting | 🟡 PARTIAL |
| **A10: Exceptions** | Error messages may leak info | 🟡 REVIEW NEEDED |

---

## Vulnerability Remediation Roadmap

### Immediate (This Sprint - April 22-26)

- [x] **CRIT-002 Fix:** File endpoints excluded from cache
- [x] **CRIT-001 Fix:** Cache key normalization implemented
- [x] **HIGH-001 Fix:** Redis TLS enforcement implemented
- [x] **Documentation:** Align this document with validated code state
- [x] **Total Remaining Effort:** 0 minutes

### Short-term (Sprint 2 - May)

- [ ] **CRIT-003 Fix:** Add encryption to RedisCache (2 hours)
- [ ] **AUTH Follow-up:** Track v0.2 RBAC implementation work
- [ ] **Security Tests:** Add focused regression coverage for cache transport and encryption decisions
- [ ] **Total Effort:** ~3-5 hours

### Medium-term (Sprint 3+)

- [ ] **AUTH Implementation:** JWT + RBAC (if Option A chosen) — 8-16 hours
- [ ] **Threat Modeling:** Formal threat model with attack trees — 4 hours
- [ ] **Security Testing:** SAST/DAST integration — 6 hours
- [ ] **Resilience:** Circuit breaker, cache stampede prevention — 6 hours

---

## Compliance Checklist

**Before v0.1 Production Deployment:**

- [ ] Remaining critical decision accepted: internal-only v0.1 without auth, or implement auth before public release
- [x] HIGH severity issues addressed
- [x] Authentication scope decided for v0.1: defer auth to v0.2, internal-use-only release
- [x] Security documentation complete
- [ ] Security tests added to CI/CD
- [ ] Code reviewed for OWASP issues
- [ ] Deployment checklist (see DEPLOYMENT_PRODUCTION.md)

**Before Multi-tenant / Public Release:**

- [ ] Full RBAC implementation (Option A)
- [ ] Threat model complete
- [ ] Penetration test completed
- [ ] SAST findings resolved
- [ ] Audit logging enabled
- [ ] Security monitoring active

---

## Related Documents

- [DEPLOYMENT_PRODUCTION.md](./DEPLOYMENT_PRODUCTION.md) — Environment setup, TLS, monitoring
- [AUTHENTICATION_AUTHORIZATION.md](./AUTHENTICATION_AUTHORIZATION.md) — v0.1 scope decision and v0.2 RBAC design
- [ERROR_RECOVERY_RESILIENCE.md](./ERROR_RECOVERY_RESILIENCE.md) — Planned future documentation for failure scenarios and mitigation
- [plan/README.md](./plan/README.md) — Plan archive index (includes source analysis documents and key security-planning artifacts)

---

## Questions & Decisions

| Question | Owner | Deadline | Decision |
|----------|-------|----------|----------|
| Implement RBAC in v0.1 or defer to v0.2? | Product/Architecture | 2026-04-25 | Defer to v0.2; v0.1 internal use only |
| Who reviews security fixes before merge? | Security / Lead Dev | 2026-04-22 | [TODO: Assign] |
| Is this product for internal use only or public-facing? | Product | 2026-04-25 | Internal use only for v0.1; revisit for v0.2 |

---

## Feedback & Updates

To report new vulnerabilities or suggest improvements, open a GitHub issue with label `security` or contact the security team.

**Last reviewed:** 2026-04-22  
**Next review:** 2026-05-06 (bi-weekly)
