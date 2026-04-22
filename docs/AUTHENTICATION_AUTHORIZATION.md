# Authentication & Authorization Architecture

**Document Version:** 1.0  
**Status:** 📋 DECIDED — Deferred to v0.2; v0.1 internal use only  
**Last Updated:** 2026-04-22

## Overview

This document defines authentication and authorization requirements for the Hybrid RAG platform, current implementation status, and a reference architecture for future releases.

## Executive Summary

| Aspect | v0.1 Status | v0.2+ Plan |
|--------|------------|-----------|
| **Authentication** | ❌ Not implemented | JWT + API Key options |
| **Authorization (RBAC)** | ❌ Not implemented | 3-tier role system |
| **Public Endpoints** | ✅ All endpoints | 🔒 Protected routes + public docs |
| **Scope** | Internal development | Internal + potential external |

---

## Current Status (v0.1)

### What's Implemented

**Zero authentication/authorization controls:**
- All REST endpoints publicly accessible
- No API key validation
- No user context tracking
- No role-based access control
- No rate limiting per user

```python
# Example: Current state - ALL ENDPOINTS PUBLIC
@app.post("/retrieve")
async def retrieve(request: RetrievalRequest):
    # No authentication check
    return retriever.retrieve(request.query)

@app.post("/config")
async def update_config(request: ConfigUpdateRequest):
    # No authorization check - anyone can change settings
    return config.update(request)

@app.post("/documents")
async def ingest_documents(request: DocumentIngestionRequest):
    # No role check - anyone can pollute the knowledge base
    return vectordb.ingest(request.documents)
```

### Intended Use (v0.1)

- **Development environments:** Local machine or internal lab
- **Team internal use:** Behind corporate network/VPN
- **Testing & prototyping:** Single-user or trusted team

### Not Suitable For (v0.1)

- ❌ Public internet exposure
- ❌ Multi-tenant deployments
- ❌ Production without network isolation
- ❌ Systems handling sensitive data

---

## Product Requirements (From PRD)

The Product Requirements Document (v0.1) defines these user personas and access levels:

### Personas & Access Control

| Persona | Endpoints Access | Capabilities | v0.1 | v0.2 |
|---------|-----------------|--------------|------|------|
| **End User** | `/retrieve` | Query knowledge base, view results | 🚀 | 🔒 auth required |
| **Knowledge Operator** | `/documents`, `/documents/sources` | Ingest docs, manage sources | 🚀 | 🔒 role: operator |
| **Platform Admin** | `/config`, `/cache/stats` | Adjust settings, monitor | 🚀 | 🔒 role: admin |
| **Platform Admin** | `/health`, debug endpoints | System monitoring | 🚀 | 🔒 role: admin |

### Access Levels Definition

```
ROLE_END_USER = {
  "permissions": ["retrieve:query"]
}

ROLE_OPERATOR = {
  "permissions": [
    "retrieve:query",
    "documents:ingest",
    "documents:list"
  ]
}

ROLE_ADMIN = {
  "permissions": [
    "retrieve:query",
    "documents:ingest",
    "documents:list",
    "config:read",
    "config:write",
    "cache:stats",
    "system:health"
  ]
}
```

---

## Version Decision: v0.1 → v0.2

### Option A: Implement RBAC in v0.2 ✅ **RECOMMENDED**

**Decision:** Defer authentication to v0.2. Update PRD scope to "Internal use only for v0.1".

**Rationale:**
- v0.1 is prototype/internal use — acceptable without auth
- Reduces v0.1 scope, enables faster release
- v0.2 can add RBAC with proper design & testing
- Security gap documented and tracked

**Action Items:**
1. Update PRD to clarify v0.1 internal use
2. Document security implications
3. Plan RBAC architecture for v0.2
4. Create GitHub issues for v0.2 work

**Timeline:** Implement in v0.2 sprint (2-3 sprints out)

---

### Option B: Implement RBAC in v0.1

**Rationale:** "Secure by default from launch"

**Tradeoff:** +8-16 hours of work, delays v0.1 release

**If chosen:** See "Reference Architecture for v0.2" below for implementation guide.

---

## Recommended Path: v0.2 RBAC Architecture

This section describes the recommended implementation for v0.2. **Not required for v0.1.**

### JWT + API Key Strategy

Support both:
1. **JWT tokens** for web/frontend usage (short-lived session)
2. **API keys** for service-to-service and automation (long-lived)

### Architecture Components

```
┌─────────────────────────────────────────┐
│  Client (Frontend/API Consumer)         │
└──────────────────┬──────────────────────┘
                   │
            ┌──────▼─────────┐
            │ Send Auth      │
            │ (JWT or API Key)
            └──────┬─────────┘
                   │
    ┌──────────────▼──────────────┐
    │  FastAPI Middleware         │
    │  - Extract token            │
    │  - Validate signature       │
    │  - Decode claims            │
    │  - Attach user_id + role    │
    └──────────────┬──────────────┘
                   │
    ┌──────────────▼──────────────┐
    │  Permission Check           │
    │  @requires_role("admin")    │
    │  @require_permission(...)   │
    └──────────────┬──────────────┘
                   │
            ┌──────▼─────────┐
            │ Route Handler  │
            │ (has context:  │
            │  request.user) │
            └────────────────┘
```

### Authentication Methods

#### JWT (Session-based)

```python
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthCredentials
import jwt

ALGORITHM = "HS256"
SECRET_KEY = os.getenv("JWT_SECRET_KEY")  # Keep secret!

async def verify_jwt(credentials: HTTPAuthCredentials = Depends(HTTPBearer())) -> dict:
    """Verify JWT token and return user claims."""
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        role: str = payload.get("role")
        if not user_id or not role:
            raise HTTPException(status_code=401, detail="Invalid token claims")
        return {"user_id": user_id, "role": role}
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

def create_jwt(user_id: str, role: str, expires_hours: int = 24) -> str:
    """Create JWT token (server-side, after login/authentication)."""
    exp = datetime.utcnow() + timedelta(hours=expires_hours)
    payload = {"sub": user_id, "role": role, "exp": exp}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
```

#### API Key (Service-to-Service)

```python
from fastapi.security import APIKeyHeader

API_KEYS = {  # In production: load from secure config
    "key_admin_xyz": {"role": "admin", "description": "Admin automation"},
    "key_user_abc": {"role": "user", "description": "Public API"},
}

async def verify_api_key(api_key: str = Depends(APIKeyHeader(name="X-API-Key"))) -> dict:
    """Verify API key and return user context."""
    if api_key not in API_KEYS:
        raise HTTPException(status_code=403, detail="Invalid API key")
    key_info = API_KEYS[api_key]
    return {"user_id": f"service:{api_key[:8]}...", "role": key_info["role"]}

# Usage in endpoints
def get_current_user(
    jwt_user: dict = Depends(verify_jwt),
    api_key_user: dict = Depends(verify_api_key)
) -> dict:
    """Prefer JWT, fallback to API key."""
    return jwt_user or api_key_user
```

### Authorization: Role-Based Access Control (RBAC)

```python
from enum import Enum
from typing import List

class Role(str, Enum):
    ADMIN = "admin"
    OPERATOR = "operator"
    USER = "user"

# Permission mappings
PERMISSIONS = {
    Role.ADMIN: [
        "retrieve:query",
        "documents:ingest",
        "documents:delete",
        "config:read",
        "config:write",
        "cache:stats",
        "health:check"
    ],
    Role.OPERATOR: [
        "retrieve:query",
        "documents:ingest",
        "documents:list"
    ],
    Role.USER: [
        "retrieve:query"
    ]
}

def require_role(*allowed_roles: Role):
    """Decorator to enforce role-based access."""
    async def check_role(current_user: dict = Depends(get_current_user)):
        if current_user["role"] not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"Role {current_user['role']} not allowed. Required: {allowed_roles}"
            )
        return current_user
    return check_role

def require_permission(permission: str):
    """Decorator to enforce specific permission."""
    async def check_permission(current_user: dict = Depends(get_current_user)):
        user_permissions = PERMISSIONS.get(current_user["role"], [])
        if permission not in user_permissions:
            raise HTTPException(
                status_code=403,
                detail=f"Permission '{permission}' denied for role '{current_user['role']}'"
            )
        return current_user
    return check_permission

# Usage in endpoints
@app.post("/retrieve")
async def retrieve(
    request: RetrievalRequest,
    current_user: dict = Depends(require_permission("retrieve:query"))
):
    """Retrieve documents (requires 'retrieve:query' permission)."""
    logger.info(f"Query from user {current_user['user_id']}: {request.query}")
    return retriever.retrieve(request.query)

@app.post("/config")
async def update_config(
    request: ConfigUpdateRequest,
    current_user: dict = Depends(require_role(Role.ADMIN))
):
    """Update config (admin only)."""
    logger.info(f"Config update by admin {current_user['user_id']}: {request}")
    return config.update(request)

@app.post("/documents")
async def ingest_documents(
    request: DocumentIngestionRequest,
    current_user: dict = Depends(require_role(Role.OPERATOR, Role.ADMIN))
):
    """Ingest documents (operator or admin)."""
    logger.info(f"Document ingest by {current_user['user_id']}")
    return vectordb.ingest(request.documents)
```

### User Context in Request

```python
from fastapi import Request

class UserContext:
    """User context available in all request handlers."""
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role
        self.permissions = PERMISSIONS[role]

@app.post("/retrieve")
async def retrieve(
    request: RetrievalRequest,
    user: UserContext = Depends(require_permission("retrieve:query"))
):
    """Example handler with user context."""
    # Log audit trail
    logger.info(f"[AUDIT] User {user.user_id} ({user.role}) queried: {request.query}")
    
    # Optionally scope results by user
    # (e.g., only show documents operator ingested)
    
    return retriever.retrieve(request.query)
```

### Session Management (Web Frontend)

```python
class LoginRequest(BaseModel):
    username: str
    password: str

@app.post("/login")
async def login(request: LoginRequest) -> dict:
    """
    Authenticate user and return JWT token.
    
    In production:
    - Verify password against secure hash (bcrypt/Argon2)
    - Fetch role from database
    - Consider MFA/2FA
    """
    # Pseudo-code; real implementation uses secure auth
    user = authenticate_user(request.username, request.password)
    
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    token = create_jwt(user_id=user.id, role=user.role, expires_hours=24)
    
    return {"access_token": token, "token_type": "bearer"}

@app.post("/logout")
async def logout(current_user: dict = Depends(get_current_user)):
    """Logout endpoint (token invalidation in production)."""
    # In production: add token to revocation list (Redis)
    logger.info(f"User {current_user['user_id']} logged out")
    return {"message": "Logged out successfully"}
```

### Rate Limiting by User

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@app.post("/retrieve")
@limiter.limit("100/minute")  # Per-user rate limit
async def retrieve(
    request: RetrievalRequest,
    current_user: dict = Depends(require_permission("retrieve:query"))
):
    """Retrieve documents (rate-limited per user)."""
    return retriever.retrieve(request.query)
```

---

## Implementation Roadmap for v0.2

### Phase 1: Foundation (Week 1)

- [ ] Create `auth/models.py` with User, Role, Permission classes
- [ ] Create `auth/jwt_handler.py` with JWT encode/decode
- [ ] Create `auth/api_key_handler.py` for API key validation
- [ ] Add decorators: `@require_role()`, `@require_permission()`
- [ ] Add integration tests for auth middleware

### Phase 2: Endpoint Migration (Week 2)

- [ ] Protect `/retrieve` endpoint with user permission
- [ ] Protect `/documents` endpoints with operator role
- [ ] Protect `/config` endpoints with admin role
- [ ] Add audit logging to all endpoints
- [ ] Update API documentation (Swagger)

### Phase 3: Testing & QA (Week 3)

- [ ] Unit tests for all decorators
- [ ] Integration tests for role-based access
- [ ] E2E tests for login/logout flow
- [ ] Security review of JWT implementation
- [ ] Penetration testing

### Phase 4: Documentation & Release (Week 4)

- [ ] User guide: "How to authenticate with Hybrid RAG"
- [ ] Operator guide: "Managing API keys and users"
- [ ] Migration guide: "Updating clients to include auth tokens"
- [ ] Security best practices document
- [ ] v0.2 release with breaking change notice

---

## Environment Variables (v0.2)

```bash
# JWT Configuration
JWT_SECRET_KEY=your-secret-key-min-32-chars
JWT_ALGORITHM=HS256
JWT_EXPIRATION_HOURS=24

# Authentication Mode
AUTH_ENABLED=true  # false for v0.1, true for v0.2+
AUTH_METHOD=jwt    # jwt, api_key, or both

# Rate Limiting (per-user)
RATE_LIMIT_ENABLED=true
RATE_LIMIT_QUERIES_PER_MINUTE=100
RATE_LIMIT_INGEST_PER_HOUR=50

# Audit Logging
AUDIT_LOG_ENABLED=true
AUDIT_LOG_FILE=/var/log/hybrid-rag/audit.log
```

---

## Follow-Up Decisions for v0.2

| Question | Target | Deadline |
|----------|--------|----------|
| Implement RBAC in v0.1 or defer to v0.2? | Product/Tech Lead | 2026-04-25 |
| If v0.2: JWT, API Keys, or both? | Architecture | 2026-05-01 |
| Database for user storage (SQL, managed)? | DevOps/DBA | 2026-05-01 |
| Multi-tenant or single-tenant in v0.2? | Product | 2026-05-01 |

**Recorded decision:** RBAC is deferred to v0.2. v0.1 is limited to internal and trusted-team deployments.

---

## Related Documents

- [SECURITY_COMPLIANCE.md](./SECURITY_COMPLIANCE.md) — Security vulnerabilities and fixes
- [DEPLOYMENT_PRODUCTION.md](./DEPLOYMENT_PRODUCTION.md) — Deployment constraints and public-release blockers
- [PRODUCT_PRD.md](./PRODUCT_PRD.md) — Updated v0.1 internal-use scope and v0.2 auth requirements

---

## References

- OWASP Authentication Cheat Sheet: https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html
- FastAPI Security: https://fastapi.tiangolo.com/tutorial/security/
- JWT Best Practices: https://tools.ietf.org/html/rfc8949
- Role-Based Access Control: https://en.wikipedia.org/wiki/Role-based_access_control
