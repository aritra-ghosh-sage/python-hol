# AI Agents Guide - Hybrid RAG Project

This document provides an overview of available AI agents and tools for development assistance in the Hybrid RAG project.

## Available AI Agents

The project includes custom AI agents in `.github/agents/` for specialized development tasks:

### Core Development Agents

- **explore-hybrid-rag.agent.md** - Architecture explorer
  - Understand library design and structure
  - Review caching architecture
  - Analyze code patterns

- **gem-planner.agent.md** - DAG-based task planning
  - Break down complex features into steps
  - Identify task dependencies
  - Plan implementation sequences

- **gem-implementer.agent.md** - TDD-focused implementation
  - Write tests before code
  - Red-Green-Refactor workflow
  - Deliver working implementations

- **gem-critic.agent.md** - Challenge and validate
  - Find edge cases and potential bugs
  - Question design assumptions
  - Suggest improvements

- **gem-reviewer.agent.md** - Security auditing
  - Review code for security issues
  - Check OWASP compliance
  - Validate error handling

### Specialized Agents

- **principal-software-engineer.agent.md** - Principal-level guidance
  - Architecture review and advice
  - Best practices and standards
  - Design validation

- **qa-subagent.agent.md** - Quality assurance
  - Comprehensive testing strategies
  - Edge case identification
  - Test coverage analysis

- **adr-generator.agent.md** - Architecture Decision Records
  - Document design decisions
  - Create ADR templates
  - Maintain architecture history

- **se-system-architecture-reviewer.agent.md** - Architecture validation
  - Review system design
  - Validate scalability
  - Check design patterns

## Caching Documentation

### Getting Started with Caching

**Quick Reference:**
- Out-of-the-box caching: In-memory cache enabled by default
- Configuration: Set `CACHE_BACKEND=memory` (dev) or `redis` (prod)
- Monitoring: Call `GET /cache/stats` endpoint to view hit rates

**Configuration File:**
- `.env.local.example` - Complete cache configuration with comments
- `CACHE_BACKEND`: Backend selection (memory/redis)
- `REDIS_URL`: Redis connection string (if using Redis)
- `CACHE_TTL_SECONDS`: Cache expiration time
- `CACHE_MAX_SIZE`: Maximum in-memory cache entries

### Key Documentation Files

| Document | Purpose | Audience |
|----------|---------|----------|
| [README.md](../README.md#-caching-layer) | Caching overview and quick start | All users |
| [docs/QUICK_START.md](../docs/QUICK_START.md#configuring-cache) | Cache configuration tutorial | New users |
| [docs/CACHE_DEPLOYMENT.md](../docs/CACHE_DEPLOYMENT.md) | Advanced production setup | DevOps/SRE |
| [docs/CACHE_DEPLOYMENT.md](../docs/CACHE_DEPLOYMENT.md) | Cache architecture and operations | Architecture |

### Architecture Layers

The system implements a 2-layer runtime caching architecture:

```
L1: Shared Query Cache
  ↓ Backed by CacheBackend
  ↓ Used by middleware and shared retrieval flow

L2: Embedding Cache (LRU in HybridRetriever)
    ↓ Caches embedding computations
  ↓ Speeds up repeated encoder calls

Storage: Vector Storage (ChromaDB)
    ↓ Persistent document vector store
```

### Common Tasks

#### Enable Redis Caching (Production)
```bash
# 1. Update .env.local
export CACHE_BACKEND=redis
export REDIS_URL=redis://localhost:6379/0

# 2. Start API
python api.py

# 3. Monitor cache
curl http://localhost:8000/cache/stats
```

#### Monitor Cache Performance
```bash
# View cache statistics
curl http://localhost:8000/cache/stats | jq

# Expected response includes hit_rate, size, backend
```

#### Bulk Document Ingestion (Preserve Cache)
```bash
# Add documents without clearing cache
curl -X POST http://localhost:8000/documents \
  -H "Content-Type: application/json" \
  -d '{
    "ingest_type": "add",
    "source_type": "text",
    "content": "Document content..."
  }'
```

#### Configure Cache Expiration
```bash
# Set TTL to 30 minutes (1800 seconds)
export CACHE_TTL_SECONDS=1800

# Set TTL to 1 hour (default)
export CACHE_TTL_SECONDS=3600
```

## Using Agents in Your Development

### Example: Planning a Feature

1. Use **gem-planner.agent.md** to break down the feature into tasks
2. Use **gem-implementer.agent.md** to write implementation with tests
3. Use **gem-critic.agent.md** to find edge cases
4. Use **gem-reviewer.agent.md** to check security
5. Use **principal-software-engineer.agent.md** for final architectural review

### Example: Adding Cache Configuration

1. **Understand current design**: Use explore-hybrid-rag.agent.md
2. **Create implementation plan**: Use gem-planner.agent.md
3. **Implement with tests**: Use gem-implementer.agent.md
4. **Security review**: Use gem-reviewer.agent.md
5. **Document decision**: Use adr-generator.agent.md

## Cache-Related Commands

### Development Setup

```bash
# Clone and setup
git clone <repo>
cd python-hol
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Copy environment template
cp .env.local.example .env.local

# Run with default in-memory cache
python api.py
```

### Testing Cache

```bash
# Run cache-specific tests
pytest tests/test_cache.py -v

# Test with cache statistics
python -c "
import requests
resp = requests.get('http://localhost:8000/cache/stats')
print(resp.json())
"

# Benchmark cache performance
python /tmp/cache_benchmark.py
```

### Production Deployment

```bash
# With Redis
export CACHE_BACKEND=redis
export REDIS_URL=redis://prod-cache:6379/0
export CACHE_TTL_SECONDS=1800
python api.py

# Monitor
watch -n 5 'curl -s http://localhost:8000/cache/stats | jq'
```

## Further Reading

- **Hybrid RAG Architecture**: See [docs/LIBRARY_DESIGN.md](../docs/LIBRARY_DESIGN.md)
- **API Integration**: See [docs/API_INTEGRATION.md](../docs/API_INTEGRATION.md)
- **Cache Operations**: See [docs/CACHE_DEPLOYMENT.md](../docs/CACHE_DEPLOYMENT.md)
- **Security**: Check `.github/instructions/security-and-owasp.instructions.md`

## Contributing

When adding new features or fixes:

1. Reference relevant agents in `.github/agents/` for guidance
2. Update documentation (README.md, QUICK_START.md, etc.)
3. Add cache configuration notes if applicable
4. Link to CACHE_DEPLOYMENT.md for advanced features
5. Update this file if adding new agents or cache documentation

---

**Last Updated**: April 20, 2026  
**Maintained By**: Development Team  
**Cache System Version**: v0.1.0 (Blueprint Phase)
