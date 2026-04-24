# AI Agents Guide - Hybrid RAG Project

This guide reflects the current agent catalog, documentation layout, and operational commands for this repository.

## Available AI Agents

All custom agents live in `.github/agents/`.

### Planning and Orchestration

- **gem-orchestrator.agent.md**: Multi-step orchestration and execution flow control
- **gem-planner.agent.md**: DAG-based task decomposition and dependency planning
- **gem-researcher.agent.md**: Clarification and focused codebase research

### Implementation and Debugging

- **gem-implementer.agent.md**: TDD-first implementation of backend/frontend tasks
- **gem-implementer-mobile.agent.md**: Mobile-focused implementation tasks
- **gem-debugger.agent.md**: Root-cause analysis and minimal fix proposals
- **gem-code-simplifier.agent.md**: Refactoring for reduced complexity without behavior drift

### Review and Quality

- **gem-reviewer.agent.md**: Security/compliance review (including OWASP-focused checks)
- **gem-critic.agent.md**: Edge-case and assumption challenge
- **qa-subagent.agent.md**: QA validation and test gap analysis
- **gem-browser-tester.agent.md**: Browser E2E flow validation
- **gem-mobile-tester.agent.md**: Mobile E2E validation

### Architecture and Documentation

- **explore-hybrid-rag.agent.md**: Hybrid RAG architecture exploration and explanation
- **arch.agent.md**: Architecture design and review support
- **adr-generator.agent.md**: ADR drafting support
- **gem-documentation-writer.agent.md**: Developer-facing documentation updates
- **prd.agent.md**: Product requirement drafting support

### Design

- **gem-designer.agent.md**: Web UI/UX design guidance
- **gem-designer-mobile.agent.md**: Mobile UX and interaction guidance

## Documentation Map

### Primary Project Docs

- [../README.md](../README.md): Project overview and high-level usage
- [../docs/QUICK_START.md](../docs/QUICK_START.md): Fast setup and first-run workflow
- [../docs/LIBRARY_DESIGN.md](../docs/LIBRARY_DESIGN.md): Backend architecture and module relationships
- [../docs/API_INTEGRATION.md](../docs/API_INTEGRATION.md): API contracts and integration guidance

### Caching and Runtime Behavior

- [../docs/CACHING_ARCHITECTURE.md](../docs/CACHING_ARCHITECTURE.md): Detailed cache-layer architecture
- [../docs/CACHE_DEPLOYMENT.md](../docs/CACHE_DEPLOYMENT.md): Production cache deployment guidance
- [../docs/CACHE_PERF_REPORT.md](../docs/CACHE_PERF_REPORT.md): Cache benchmark and performance analysis
- [../docs/HTTP_ENDPOINT_ALLOWLIST.md](../docs/HTTP_ENDPOINT_ALLOWLIST.md): Endpoint allowlist guidance

### Testing and Planning

- [../docs/E2E_TESTS_SUMMARY.md](../docs/E2E_TESTS_SUMMARY.md): End-to-end test status and notes
- [../docs/PRODUCT_PRD.md](../docs/PRODUCT_PRD.md): Product requirement baseline
- [../docs/plan/](../docs/plan/): Planning artifacts
- [../docs/diagrams/](../docs/diagrams/): Architecture and flow diagrams

### Frontend-Specific Docs

- [../frontend/AGENTS.md](../frontend/AGENTS.md): Frontend agent usage and guardrails
- [../frontend/SETUP.md](../frontend/SETUP.md): Frontend setup details
- [../frontend/README.md](../frontend/README.md): Frontend module overview

## Caching Quick Reference

- Default backend: `memory`
- Production backend: `redis`
- Key endpoint: `GET /cache/stats`

Configuration variables:

- `CACHE_BACKEND` (`memory` or `redis`)
- `REDIS_URL` (required when `CACHE_BACKEND=redis`)
- `CACHE_TTL_SECONDS`
- `CACHE_MAX_SIZE`
- `CACHE_KEY_PREFIX`

## Common Commands

### Backend

```bash
# from repository root
source .venv/bin/activate
uv sync

# run API
uvicorn api:app --reload
# or
python api.py

# run tests
pytest tests/ -v
```

### Frontend

```bash
cd frontend
pnpm install
pnpm dev
pnpm build
pnpm lint
pnpm test:unit
```

### Cache Operations

```bash
# switch to redis cache
export CACHE_BACKEND=redis
export REDIS_URL=redis://localhost:6379/0

# inspect cache stats
curl -s http://localhost:8000/cache/stats | jq
```

## Recommended Agent Workflow

For feature delivery:

1. Use `gem-researcher.agent.md` or `explore-hybrid-rag.agent.md` to gather context.
2. Use `gem-planner.agent.md` for implementation planning.
3. Use `gem-implementer.agent.md` (or mobile variant) for TDD execution.
4. Use `gem-critic.agent.md` for edge cases and design pressure testing.
5. Use `gem-reviewer.agent.md` plus `qa-subagent.agent.md` for security and quality verification.
6. Use `gem-documentation-writer.agent.md` or `adr-generator.agent.md` for artifacts.

## Related Governance and Standards

- [./instructions/security-and-owasp.instructions.md](./instructions/security-and-owasp.instructions.md)
- [./instructions/performance-optimization.instructions.md](./instructions/performance-optimization.instructions.md)
- [./instructions/agent-safety.instructions.md](./instructions/agent-safety.instructions.md)
- [./copilot-instructions.md](./copilot-instructions.md)

---

**Last Updated**: April 24, 2026  
**Maintained By**: Development Team  
**Cache System Version**: v0.1.0
