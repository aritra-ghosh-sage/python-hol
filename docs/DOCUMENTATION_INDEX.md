# Documentation Index & Consolidation Map

**Last Updated:** 2026-04-22  
**Purpose:** Guide users to the right documentation and track consolidation from plan to production docs

---

## 📚 Core Documentation (Production Ready)

### Architecture & Design
- **[LIBRARY_DESIGN.md](./LIBRARY_DESIGN.md)** — Hybrid RAG library architecture, all 8 modules documented
  - Caching strategy (2 implemented layers: shared L1 query cache and L2 embedding cache)
  - Cache consistency policy (REST vs WebSocket parity)
  - Architectural decisions and rationale
  - **Consolidated from:** `plan/20260420-caching-blueprint/*`

- **[API_INTEGRATION.md](./API_INTEGRATION.md)** — Complete REST and WebSocket API contracts
  - 10 REST endpoints with request/response schemas
  - WebSocket request/response message schemas
  - Client integration patterns (vanilla JS, React hooks)
  - Error handling and validation
  - **Consolidated from:** `plan/20260420-caching-blueprint/CACHE-003-completion.md`

### Deployment & Operations
- **[DEPLOYMENT_PRODUCTION.md](./DEPLOYMENT_PRODUCTION.md)** — Production deployment guide
  - Security fixes checklist (CRIT-001/002/003, HIGH-001)
  - 50+ environment variables documented
  - 3 deployment platforms (Systemd, Docker, Kubernetes)
  - Redis TLS setup with certificate generation
  - Troubleshooting and rollback procedures
  - Pre-production checklist
  - **Consolidated from:** `plan/20260420-caching-blueprint/IMPLEMENTATION_SUMMARY.md`

- **[MONITORING_OBSERVABILITY.md](./MONITORING_OBSERVABILITY.md)** — Monitoring, logging, and alerting
  - Key metrics by category (system, application, retrieval, cache, WebSocket)
  - Prometheus configuration with 20+ metrics
  - Critical/Important/Informational alert rules
  - Debugging guides and runbooks
  - Security monitoring patterns
  - **New documentation** created for Task 8

### Security & Compliance
- **[SECURITY_COMPLIANCE.md](./SECURITY_COMPLIANCE.md)** — Vulnerabilities and remediation roadmap
  - 4 documented issues: CRIT-001 (cache injection), CRIT-002 (multipart DoS), CRIT-003 (unencrypted cache), HIGH-001 (TLS enforcement)
  - OWASP 2025 compliance matrix
  - Remediation timeline and effort estimates
  - **Consolidated from:** `plan/20260420-caching-blueprint/ANALYSIS_REPORT_DOUBLECHECK_QUALITY_PLAYBOOK.md`

- **[AUTHENTICATION_AUTHORIZATION.md](./AUTHENTICATION_AUTHORIZATION.md)** — Auth requirements and v0.2 roadmap
  - v0.1 status (zero implementation)
  - v0.2 reference architecture with JWT + RBAC
  - Decision framework (implement v0.1 vs defer to v0.2)
  - Type-safe auth patterns
  - **New documentation** created for Task 2

### Frontend Documentation
- **[frontend/README.md](../frontend/README.md)** — Next.js 16 frontend guide
  - Project structure and feature-based organization
  - API integration examples (REST and WebSocket)
  - State management (Zustand patterns)
  - Type safety and testing
  - Frontend setup and runtime behavior
  - **Updated** for Task 7

- **API contract notes are consolidated into [API_INTEGRATION.md](./API_INTEGRATION.md)**
  - Use that file as the canonical REST/WebSocket contract reference
  - Prefer frontend source types in `frontend/src/lib/types.ts` for implementation details

---

## 📋 Plan Documents (Historical Reference)

Plan documents in `docs/plan/` contain detailed analysis, decision matrices, and technical justification. **Most findings have been consolidated into production docs above.**

Start with **[docs/plan/README.md](./plan/README.md)** for archive navigation, reading order, and key historical artifacts.

Use plan docs for:
- Detailed decision rationale
- QA test matrices and assertions
- Full architectural blueprints with C4 diagrams
- Implementation wave planning

| Plan Document | Purpose | Consolidated Into |
|---|---|---|
| `plan/20260420/CACHE-CONSISTENCY-POLICY.md` | Cache parity contract between REST/WS | [LIBRARY_DESIGN.md#cache-consistency-policy](./LIBRARY_DESIGN.md#cache-consistency-policy-rest-vs-websocket) |
| `plan/20260420-caching-blueprint/Caching_Architecture_Blueprint.md` | Earlier caching architecture analysis | [LIBRARY_DESIGN.md#cachepy---cache-backends-and-runtime-cache-design](./LIBRARY_DESIGN.md#cachepy---cache-backends-and-runtime-cache-design) |
| `plan/20260420-caching-blueprint/ANALYSIS_REPORT_DOUBLECHECK_QUALITY_PLAYBOOK.md` | Security and quality findings | [SECURITY_COMPLIANCE.md](./SECURITY_COMPLIANCE.md) |
| `plan/20260420/qa-cache-consistency-policy-matrix.md` | Observable test assertions for cache parity | Testing guide (TBD) |
| `plan/20260420-caching-blueprint/CACHE-001-summary.md` | Cache implementation details | [LIBRARY_DESIGN.md#cachepy---cache-backends-and-runtime-cache-design](./LIBRARY_DESIGN.md#cachepy---cache-backends-and-runtime-cache-design) |
| `plan/20260420-caching-blueprint/IMPLEMENTATION_SUMMARY.md` | 169 passing tests, implementation status | [DEPLOYMENT_PRODUCTION.md](./DEPLOYMENT_PRODUCTION.md) |

---

## 🎯 Quick Navigation by Role

### **For Backend Developers**
1. Start: [LIBRARY_DESIGN.md](./LIBRARY_DESIGN.md) — Understand the architecture
2. Deep dive: [API_INTEGRATION.md](./API_INTEGRATION.md) — See API contracts
3. Security: [SECURITY_COMPLIANCE.md](./SECURITY_COMPLIANCE.md) — Know the vulnerabilities
4. Historical reference: [plan/README.md](./plan/README.md) — Archive index, key files, and reading order

### **For DevOps/SRE**
1. Start: [DEPLOYMENT_PRODUCTION.md](./DEPLOYMENT_PRODUCTION.md) — Complete deployment guide
2. Operations: [MONITORING_OBSERVABILITY.md](./MONITORING_OBSERVABILITY.md) — Alerting and runbooks
3. Security: [SECURITY_COMPLIANCE.md#deployment](./SECURITY_COMPLIANCE.md) — Security fixes checklist
4. Historical reference: [plan/README.md](./plan/README.md) — Archive index and implementation-history pointers

### **For Frontend Developers**
1. Start: [frontend/README.md](../frontend/README.md) — Project overview
2. API Integration: [API_INTEGRATION.md](./API_INTEGRATION.md) — Endpoint contracts
3. Contract Reference: [API_INTEGRATION.md](./API_INTEGRATION.md) — REST and WebSocket contracts
4. Setup: [frontend/SETUP.md](../frontend/SETUP.md) — Environment configuration

### **For Security Review**
1. Start: [SECURITY_COMPLIANCE.md](./SECURITY_COMPLIANCE.md) — Known issues and fixes
2. Auth: [AUTHENTICATION_AUTHORIZATION.md](./AUTHENTICATION_AUTHORIZATION.md) — Auth requirements
3. Deployment: [DEPLOYMENT_PRODUCTION.md](./DEPLOYMENT_PRODUCTION.md) — Security setup
4. Historical reference: [plan/README.md](./plan/README.md) — Archive index and source-analysis pointers

### **For Product Managers**
1. Start: [README.md](../README.md) — Project overview
2. API: [API_INTEGRATION.md](./API_INTEGRATION.md) — Feature capabilities
3. Auth: [AUTHENTICATION_AUTHORIZATION.md](./AUTHENTICATION_AUTHORIZATION.md) — Auth roadmap
4. Monitoring: [MONITORING_OBSERVABILITY.md](./MONITORING_OBSERVABILITY.md) — Observability

---

## ✅ Consolidation Status

**Task 9 Status:** Consolidation of plan documents into main documentation

| Category | Status | Effort |
|----------|--------|--------|
| Security findings (CRIT-001/002/003, HIGH-001) | ✅ Complete | Consolidated to SECURITY_COMPLIANCE.md |
| Cache consistency policy | ✅ Complete | Consolidated to LIBRARY_DESIGN.md |
| Caching architecture | ✅ Complete | Consolidated to LIBRARY_DESIGN.md + API_INTEGRATION.md |
| Deployment procedures | ✅ Complete | Documented in DEPLOYMENT_PRODUCTION.md |
| API contracts | ✅ Complete | Documented in API_INTEGRATION.md |
| Monitoring & alerting | ✅ Complete | Documented in MONITORING_OBSERVABILITY.md |
| Test matrices (optional reference) | 📋 Available | In plan docs for QA reference |
| Architectural diagrams (C4) | 📋 Available | In plan docs for reference |

**Note:** Plan documents are preserved as historical reference containing decision matrices, detailed analysis, and C4 architecture diagrams. All critical findings have been extracted and consolidated into production documentation.

---

## 📖 Documentation Standards

All production documentation follows:
- **Format:** Markdown with consistent structure
- **Type Safety:** Code examples include type hints
- **Completeness:** Covers both "why" and "how"
- **Accessibility:** Clear sections, navigation, examples
- **Maintenance:** Cross-links between related docs
- **Version:** Each doc includes version and last-updated date

---

## 🔗 Document Relationships

```
LIBRARY_DESIGN.md (Architecture)
  ├── SECURITY_COMPLIANCE.md (Known issues)
  ├── API_INTEGRATION.md (REST + WebSocket contracts)
  │   └── frontend/README.md (Client integration)
  └── AUTHENTICATION_AUTHORIZATION.md (Auth v0.2 roadmap)

DEPLOYMENT_PRODUCTION.md (Operations)
  ├── MONITORING_OBSERVABILITY.md (Alerting & runbooks)
  ├── SECURITY_COMPLIANCE.md (Security fixes)
  └── AUTHENTICATION_AUTHORIZATION.md (Auth setup)
```

---

## 📝 Next Steps

**Remaining Tasks:**
- **Optional:** Create a QA/Testing guide documenting cache parity test assertions from `plan/20260420/qa-cache-consistency-policy-matrix.md`

**Maintenance:**
- Plan documents retained in `docs/plan/` for historical reference
- Update cross-references if documentation structure changes
- Keep consolidation table current as new docs are added
