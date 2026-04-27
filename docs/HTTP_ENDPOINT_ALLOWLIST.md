# HTTP Endpoint Allowlist Policy

**Status**: Active (T09)
**Last Updated**: 2026-04-23
**Owner**: Platform Team

## Purpose

This document defines the approved HTTP endpoint surface for the Hybrid RAG API and establishes governance to prevent unauthorized endpoint additions.

## Policy

### Approved HTTP Endpoints (Admin-Only)

The following HTTP endpoints are **approved** for production use:

| Endpoint | Methods | Purpose | Auth Required |
|----------|---------|---------|---------------|
| `/health` | GET | Health check and readiness probe | No |
| `/config` | GET, PUT | Retriever configuration management | Yes (admin) |
| `/documents` | POST | Document ingestion | Yes (admin) |
| `/documents/sources` | GET | List document sources with chunk counts | Yes (admin) |
| `/collections` | GET | List ChromaDB collections with document counts | Yes (admin) |
| `/cache/stats` | GET | Cache statistics and observability | Yes (admin) |
| `/` | GET | API information and version | No |

**Auto-generated documentation endpoints** (required for OpenAPI):
- `/openapi.json` - OpenAPI schema
- `/docs` - Swagger UI
- `/redoc` - ReDoc UI
- `/docs/oauth2-redirect` - OAuth2 redirect for Swagger

### Approved WebSocket Endpoints

| Endpoint | Purpose | Auth Required |
|----------|---------|---------------|
| `/ws/chat` | Real-time document retrieval and chat | Yes |

## Rationale

### WebSocket-Only Retrieval

As of T08, all document retrieval operations **must** use the WebSocket interface (`/ws/chat`). This decision was made to:

1. **Eliminate duplication**: Single retrieval code path reduces maintenance burden
2. **Enable streaming**: Progressive result delivery for better UX
3. **Simplify caching**: Unified cache layer in retrieval handler vs. split HTTP/retrieval caching
4. **Support real-time features**: Foundation for future conversational capabilities

### Admin-Only HTTP Surface

The HTTP API is intentionally limited to **administrative operations only**:
- Configuration management
- Document ingestion
- Observability (health, cache stats)

This constraint:
- **Reduces attack surface**: Fewer endpoints to secure and monitor
- **Simplifies API versioning**: Breaking changes only affect admin tooling, not end-user clients
- **Prevents drift**: Explicit allowlist makes unauthorized additions immediately visible

## Governance

### Adding New Endpoints

Any new HTTP endpoint must follow this approval process:

1. **Proposal**: Submit ADR (Architecture Decision Record) with:
   - Use case and business justification
   - Why existing endpoints cannot satisfy the requirement
   - Security implications and auth requirements
   - Impact on API versioning and client compatibility

2. **Review**: Platform team reviews against these criteria:
   - Does it fit the "admin-only" policy?
   - Can it be implemented as a WebSocket message type instead?
   - Does it introduce security or compliance risks?

3. **Approval**: Requires sign-off from:
   - Platform lead
   - Security reviewer (if auth-related or data-sensitive)

4. **Implementation**:
   - Add endpoint to `api.py`
   - Update `ALLOWED_HTTP_PATHS` in `tests/test_route_allowlist.py`
   - Update this policy document
   - Add endpoint to OpenAPI documentation

5. **CI Enforcement**: The `test_route_allowlist.py` test will fail if:
   - New endpoints are added without updating the allowlist
   - Forbidden endpoints are reintroduced
   - OpenAPI schema contains retrieval references

### Exception Process

**There are no exceptions.** The allowlist is mandatory for all branches and deployments.

If you believe the policy itself should change:
1. Propose a policy update via ADR
2. Discuss in architecture review
3. Update this document if approved
4. Update CI tests to reflect new policy

## Enforcement

### Automated Checks

The following automated tests enforce this policy:

1. **`tests/test_route_allowlist.py::test_http_routes_match_allowlist`**
   - Fails if unauthorized HTTP routes detected
   - Fails if expected routes missing

2. **`tests/test_route_allowlist.py::test_websocket_routes_match_allowlist`**
   - Fails if unauthorized WebSocket routes detected

3. **`tests/test_route_allowlist.py::test_no_retrieval_http_endpoints`**
   - Fails if any HTTP path contains "retrieve"

4. **`tests/test_route_allowlist.py::test_openapi_schema_no_retrieval_references`**
   - Fails if OpenAPI schema exposes unexpected retrieval paths

5. **`tests/test_route_allowlist.py::test_route_inventory_documentation`**
   - Generates route inventory for CI artifacts
   - Validates route counts match expectations

### CI/CD Integration

The allowlist tests run on:
- **Every pull request** (required status check)
- **Pre-merge** (blocking gate for protected branches)
- **Post-deployment** (smoke test in staging/production)

**Failure handling**:
- Failed allowlist test → PR blocked from merge
- Cannot be overridden or bypassed
- Requires code change to fix (no policy exceptions)

### Manual Verification

Beyond automated tests, the following manual checks are recommended:

1. **Code Review**: Reviewers should verify that new endpoints:
   - Are listed in this policy document
   - Have appropriate authentication/authorization
   - Include comprehensive tests

2. **Security Review**: For endpoints that:
   - Accept user input (potential injection attacks)
   - Return sensitive data (potential leaks)
   - Modify system state (potential abuse)

## Monitoring

### Observability

Track these metrics to detect policy violations or drift:

1. **Route Count Metrics**:
   - `http_endpoint_count`: Should stay at 11-12
   - `websocket_endpoint_count`: Should stay at 1
   - Alert on any increase

2. **Route Inventory Logs**:
   - `test_route_inventory_documentation` emits full inventory in CI logs
   - Review after deployments to verify expected state

3. **OpenAPI Schema Monitoring**:
   - Periodically audit `/openapi.json` for unexpected changes

### Incident Response

If an unauthorized endpoint is detected in production:

1. **Immediate**: Rollback deployment to last known good state
2. **Investigation**: Review how the endpoint bypassed CI checks
3. **Fix**: Remove unauthorized endpoint and strengthen CI checks
4. **Post-mortem**: Document lessons learned and update runbook

## References

- **T08**: WebSocket-only retrieval migration
- **T09**: Admin-only HTTP allowlist enforcement (this task)
- **ADR-006**: Cache invalidation on config updates
- **RSK-001**: Cache observability (T03)

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-04-23 | Initial policy creation (T09) | Claude Agent |
