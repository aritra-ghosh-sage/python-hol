# Plan 20260420 Clarifications

## Objective
Stabilize and secure the caching rollout for Hybrid RAG by closing production-blocking security gaps identified in researcher outputs while preserving current architecture behavior (fail-open cache usage and deterministic keying).

## Clarified Critical Scope (Blocking Set)
The following items are blocking for the clarified critical scope and must be completed before production gating:

- SEC-001: Canonicalize JSON before cache-key hashing to prevent equivalent payloads producing different keys.
- SEC-002: Exclude multipart/file-upload endpoints from cache middleware body replay to avoid memory amplification and upload-path DoS.
- SEC-004: Enforce secure Redis transport/auth expectations for production (TLS-first Redis URL policy and validation).

## Deferred Item
- SEC-003 is deferred from the immediate blocking set and scheduled for the next implementation wave:
  - Add encryption-at-rest for cached payloads (for example, Fernet-backed value encryption with key from environment configuration).

## Architectural Decisions (Clarified)
1. Keep fail-open behavior: cache failures must not fail request handling.
2. Treat canonical request identity as a correctness invariant for cache keys (stable, normalized serialization before hashing).
3. Keep binary and large multipart traffic out of cache middleware replay/caching paths.
4. Apply environment-sensitive Redis security gates: strict transport requirements in production.
5. Stage encryption-at-rest as a planned hardening milestone (deferred SEC-003), not as a prerequisite to close current critical set.

## Staging vs Production Gate Notes
- Staging gate:
  - SEC-001, SEC-002, and SEC-004 implemented and validated.
  - Regression tests for canonical keys and excluded upload endpoints pass.
  - Cache behavior remains fail-open under backend fault simulation.

- Production gate:
  - Complete staging gate criteria first.
  - Complete deferred SEC-003 (cache payload encryption at rest).
  - Confirm operational security posture (Redis transport policy, credentials handling, and deployment-time validation checks).

## Risk List
- Risk: Cache fragmentation or poisoning via non-canonical payload serialization.
  - Mitigation: SEC-001 canonical JSON normalization.
- Risk: Memory pressure and DoS from multipart body replay/caching.
  - Mitigation: SEC-002 endpoint exclusion for upload routes.
- Risk: Confidentiality exposure in Redis transit if non-TLS configuration is allowed in production.
  - Mitigation: SEC-004 strict production validation.
- Risk: Confidentiality exposure at rest for cached retrieval payloads.
  - Mitigation: Deferred SEC-003 encryption-at-rest milestone before production sign-off.
- Risk: Operational regression if strict security checks disrupt existing deployments.
  - Mitigation: Environment-aware gates and staging verification before production rollout.

## Sources
- docs/plan/20260420-caching-blueprint/ANALYSIS_REPORT_DOUBLECHECK_QUALITY_PLAYBOOK.md
- docs/plan/20260420-caching-blueprint/AUDIT_REPORT_20260420.json
