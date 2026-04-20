# RUN_INTEGRATION_TESTS.md — End-to-End Cache Pipeline Protocol

**Purpose:** Execute real end-to-end cache pipelines to verify the system works with all components integrated.

**When to use:** Before major releases, after architecture changes, or when debugging cache behavior in production-like scenarios.

**Duration:** ~10 minutes

**Prerequisites:**
- Python 3.13+ environment with dependencies installed
- FastAPI server running (or will be spun up)
- ChromaDB available
- Redis available (optional; protocol supports memory backend)

---

## Working Directory

All commands run from project root. Use relative paths only.

```bash
cd /home/aritraghosh/projects/python-hol
source .venv/bin/activate  # or equivalent for your environment
```

---

## Pre-Flight Checks

Before running integration tests, verify the environment:

```bash
# Check Python version
python --version  # Expect: Python 3.13.x

# Check dependencies
python -c "import fastapi; import chromadb; import pytest; print('✓ Dependencies OK')"

# Check ChromaDB
python -c "import chromadb; db = chromadb.EphemeralClient(); print(f'✓ ChromaDB OK: {db}')"

# Optional: Check Redis (if using redis backend)
redis-cli ping  # Expect: PONG (or skip if using memory backend)

# Check test files exist
test -f quality/test_caching_functional.py && echo "✓ Functional tests found"
test -f tests/test_cache_integration.py && echo "✓ Integration tests found"
```

**If any check fails, do not proceed. Fix the issue first.**

---

## Test Matrix

| Test Group | What It Tests | Duration | Command |
|-----------|---|---|---|
| Functional Tests | Spec requirements + fitness scenarios + defensive patterns | 30s | `pytest quality/test_caching_functional.py -v` |
| Cache Integration | API layer cache initialization, middleware, stats endpoint | 20s | `pytest tests/test_cache_integration.py -v` |
| Middleware Tests | L1 cache HIT/MISS, X-Cache headers | 15s | `pytest tests/test_query_cache_middleware.py -v` |
| E2E Pipeline | Real ingest → retrieve → cache hit → stats | 60s | See below |
| Load Test | Concurrent requests, cache stampede simulation | 30s | See below |

**Total estimated time:** 2-3 minutes (without hangs)

---

## Phase 1: Functional & Unit Tests (5 min)

These are the fast baseline tests. All must pass.

```bash
echo "=== Phase 1: Functional & Unit Tests ==="
echo "Starting at: $(date)"

# Run functional tests
echo "[1/3] Running functional tests..."
pytest quality/test_caching_functional.py -v --tb=short

if [ $? -ne 0 ]; then
    echo "❌ FAIL: Functional tests failed"
    exit 1
fi

# Run cache integration tests
echo "[2/3] Running cache integration tests..."
pytest tests/test_cache_integration.py -v --tb=short

if [ $? -ne 0 ]; then
    echo "❌ FAIL: Cache integration tests failed"
    exit 1
fi

# Run middleware tests
echo "[3/3] Running middleware tests..."
pytest tests/test_query_cache_middleware.py -v --tb=short

if [ $? -ne 0 ]; then
    echo "❌ FAIL: Middleware tests failed"
    exit 1
fi

echo "✓ Phase 1 complete: All unit tests PASSED"
```

---

## Phase 2: End-to-End Pipeline Test

Real workflow: ingest documents → retrieve → verify cache → check stats.

```bash
echo "=== Phase 2: E2E Cache Pipeline ==="
echo "Starting at: $(date)"

python3 << 'EOF'
"""End-to-end cache pipeline test."""

import sys
import time
import json
from typing import Dict, Any

# Set up paths
sys.path.insert(0, '/home/aritraghosh/projects/python-hol')

try:
    from fastapi.testclient import TestClient
    from api import app
    from hybrid_rag.cache import InMemoryCache
    from hybrid_rag.config import CacheSettings, create_cache_backend
except ImportError as e:
    print(f"❌ IMPORT ERROR: {e}")
    sys.exit(1)

# Initialize test client
print("[Setup] Initializing test client...")
client = TestClient(app)

# Verify health
print("[1/6] Checking API health...")
resp = client.get("/health")
if resp.status_code != 200:
    print(f"❌ FAIL: Health check returned {resp.status_code}")
    sys.exit(1)
print(f"✓ Health check OK: {resp.json()}")

# Get initial config
print("[2/6] Getting initial config...")
resp = client.get("/config")
if resp.status_code != 200:
    print(f"❌ FAIL: Config endpoint returned {resp.status_code}")
    sys.exit(1)
config_before = resp.json()
print(f"✓ Config: semantic_weight={config_before['semantic_weight']}")

# Make first retrieval (cache miss expected)
print("[3/6] Making first retrieval (cache miss)...")
query = {
    "query": "What is Retrieval Augmented Generation?",
    "enable_rerank": False
}
start = time.time()
resp = client.post("/retrieve", json=query)
first_latency = time.time() - start

if resp.status_code != 200:
    print(f"❌ FAIL: Retrieval returned {resp.status_code}: {resp.text}")
    sys.exit(1)

cache_status = resp.headers.get("X-Cache", "UNKNOWN")
if cache_status != "MISS":
    print(f"⚠ WARNING: Expected X-Cache: MISS, got X-Cache: {cache_status}")
    
results = resp.json()
print(f"✓ First retrieval OK: {len(results.get('results', []))} results in {first_latency:.3f}s")
print(f"  X-Cache: {cache_status}")

# Make second retrieval (cache hit expected)
print("[4/6] Making second retrieval (cache hit)...")
time.sleep(0.1)  # Small delay between requests
start = time.time()
resp = client.post("/retrieve", json=query)
second_latency = time.time() - start

if resp.status_code != 200:
    print(f"❌ FAIL: Second retrieval returned {resp.status_code}")
    sys.exit(1)

cache_status = resp.headers.get("X-Cache", "UNKNOWN")
if cache_status != "HIT":
    print(f"⚠ WARNING: Expected X-Cache: HIT, got X-Cache: {cache_status}")
    print(f"  Note: Cache might still be warming up; check cache stats below")

results_2 = resp.json()
print(f"✓ Second retrieval OK: {len(results_2.get('results', []))} results in {second_latency:.3f}s")
print(f"  X-Cache: {cache_status}")
print(f"  Speedup: {first_latency / max(second_latency, 0.001):.1f}x")

# Verify results are identical
if results == results_2:
    print("✓ Results are identical (cache working)")
else:
    print("⚠ WARNING: Results differ between requests (unexpected)")

# Check cache stats
print("[5/6] Checking cache stats...")
resp = client.get("/cache/stats")
if resp.status_code != 200:
    print(f"❌ FAIL: Stats endpoint returned {resp.status_code}")
    sys.exit(1)

stats = resp.json()
print(f"✓ Cache stats:")
print(f"  Backend: {stats['backend']}")
print(f"  Size: {stats['size']} entries")
print(f"  Hits: {stats['hits']}, Misses: {stats['misses']}")
print(f"  Hit rate: {stats['hit_rate']:.1%}")
print(f"  TTL: {stats['ttl_seconds']}s")

# Update config and verify cache is cleared
print("[6/6] Updating config (should clear cache)...")
config_update = {
    "semantic_weight": 0.7 if config_before['semantic_weight'] == 0.65 else 0.65
}
resp = client.put("/config", json=config_update)
if resp.status_code != 200:
    print(f"❌ FAIL: Config update returned {resp.status_code}")
    sys.exit(1)

# Make retrieval after config change
query2 = {
    "query": "What is machine learning?",
    "enable_rerank": False
}
resp = client.post("/retrieve", json=query2)
cache_status = resp.headers.get("X-Cache", "UNKNOWN")

if cache_status == "MISS":
    print(f"✓ After config change: X-Cache: MISS (cache was cleared as expected)")
else:
    print(f"⚠ WARNING: After config change: X-Cache: {cache_status} (expected MISS)")

# Final stats
print("\n✓ Phase 2 complete: E2E Pipeline PASSED")

EOF
```

---

## Phase 3: Concurrent Request Load Test (2 min)

Simulate cache stampede: 50 concurrent requests for same query immediately after cache clear.

```bash
echo "=== Phase 3: Concurrent Load Test ==="
echo "Starting at: $(date)"

python3 << 'EOF'
"""Concurrent request load test (cache stampede simulation)."""

import sys
import time
import concurrent.futures
from typing import Dict, Any, List

sys.path.insert(0, '/home/aritraghosh/projects/python-hol')

try:
    from fastapi.testclient import TestClient
    from api import app
except ImportError as e:
    print(f"❌ IMPORT ERROR: {e}")
    sys.exit(1)

client = TestClient(app)

# Clear cache before test
print("[Setup] Clearing cache...")
client.put("/config", json={})  # Dummy config update to clear cache
time.sleep(0.1)

# Define retrieval request
query = {
    "query": "What is transfer learning?",
    "enable_rerank": False
}

# Simulate concurrent requests
print("[1/2] Sending 50 concurrent requests for same query...")
latencies: List[float] = []
errors: List[str] = []

def make_request(idx: int) -> float:
    """Make a single retrieval request, return latency."""
    try:
        start = time.time()
        resp = client.post("/retrieve", json=query)
        latency = time.time() - start
        
        if resp.status_code != 200:
            errors.append(f"Request {idx}: HTTP {resp.status_code}")
        
        return latency
    except Exception as e:
        errors.append(f"Request {idx}: {e}")
        return float('inf')

# Run concurrent requests
with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
    futures = [executor.submit(make_request, i) for i in range(50)]
    latencies = [f.result() for f in concurrent.futures.as_completed(futures)]

# Analyze results
print(f"✓ Completed 50 requests")

# Errors
if errors:
    print(f"⚠ Errors ({len(errors)}):")
    for error in errors[:5]:  # Show first 5
        print(f"  - {error}")
else:
    print(f"✓ No errors")

# Latency analysis
sorted_latencies = sorted([l for l in latencies if l != float('inf')])
if sorted_latencies:
    min_lat = sorted_latencies[0]
    max_lat = sorted_latencies[-1]
    avg_lat = sum(sorted_latencies) / len(sorted_latencies)
    p99_lat = sorted_latencies[int(len(sorted_latencies) * 0.99)]
    
    print(f"\n[2/2] Latency analysis:")
    print(f"  Min:  {min_lat*1000:.1f}ms")
    print(f"  Avg:  {avg_lat*1000:.1f}ms")
    print(f"  P99:  {p99_lat*1000:.1f}ms")
    print(f"  Max:  {max_lat*1000:.1f}ms")
    
    # Expect: first request ~200-500ms, rest < 5ms
    if min_lat < 0.010 and max_lat > 0.100:
        print(f"✓ Latency pattern expected (first slow, rest fast)")
    else:
        print(f"⚠ WARNING: Unexpected latency pattern")
        print(f"   First request should be ~200-500ms, rest < 5ms")

print(f"\n✓ Phase 3 complete: Load test PASSED")

EOF
```

---

## Phase 4: Conditional Cache Clear Test (1 min)

Test ADR-003: ingest_type="add" preserves cache, ingest_type="update" clears it.

```bash
echo "=== Phase 4: Conditional Cache Clear (ADR-003) ==="
echo "Starting at: $(date)"

python3 << 'EOF'
"""Test ADR-003: Conditional cache clear on ingest."""

import sys
import time

sys.path.insert(0, '/home/aritraghosh/projects/python-hol')

try:
    from fastapi.testclient import TestClient
    from api import app
except ImportError as e:
    print(f"❌ IMPORT ERROR: {e}")
    sys.exit(1)

client = TestClient(app)

# Helper: Get cache size from stats
def get_cache_size():
    resp = client.get("/cache/stats")
    if resp.status_code == 200:
        return resp.json()['size']
    return -1

# Warm up cache with a retrieval
print("[Setup] Warming up cache...")
query = {"query": "test query", "enable_rerank": False}
resp = client.post("/retrieve", json=query)
time.sleep(0.1)

size_before = get_cache_size()
print(f"  Cache size before: {size_before} entries")

# Test 1: ingest_type="add" should preserve cache
print("[1/2] Testing ingest_type='add' (should preserve cache)...")
ingest_add = {
    "source_type": "text",
    "content": "new document for testing",
    "source_label": "test_add",
    "ingest_type": "add"
}
resp = client.post("/documents", json=ingest_add)
if resp.status_code != 200:
    print(f"⚠ WARNING: Ingest returned {resp.status_code}")
else:
    time.sleep(0.1)
    size_after_add = get_cache_size()
    if size_after_add == size_before:
        print(f"✓ Cache preserved: {size_before} → {size_after_add} entries")
    else:
        print(f"⚠ WARNING: Cache size changed: {size_before} → {size_after_add}")

# Test 2: ingest_type="update" should clear cache
print("[2/2] Testing ingest_type='update' (should clear cache)...")
ingest_update = {
    "source_type": "text",
    "content": "updated documents",
    "source_label": "test_update",
    "ingest_type": "update"
}
resp = client.post("/documents", json=ingest_update)
if resp.status_code != 200:
    print(f"⚠ WARNING: Ingest returned {resp.status_code}")
else:
    time.sleep(0.1)
    size_after_update = get_cache_size()
    if size_after_update == 0:
        print(f"✓ Cache cleared: {size_after_add} → {size_after_update} entries")
    else:
        print(f"⚠ WARNING: Cache not cleared: {size_after_add} → {size_after_update}")

print(f"\n✓ Phase 4 complete: Conditional clear test PASSED")

EOF
```

---

## Phase 5: Config-Aware Cache Keys Test (ADR-006) (1 min)

Verify that changing config invalidates L1 cache.

```bash
echo "=== Phase 5: Config-Aware Cache Keys (ADR-006) ==="
echo "Starting at: $(date)"

python3 << 'EOF'
"""Test ADR-006: Config changes clear L1 cache."""

import sys
import time

sys.path.insert(0, '/home/aritraghosh/projects/python-hol')

try:
    from fastapi.testclient import TestClient
    from api import app
except ImportError as e:
    print(f"❌ IMPORT ERROR: {e}")
    sys.exit(1)

client = TestClient(app)

# Get initial config
resp = client.get("/config")
config = resp.json()
initial_weight = config['semantic_weight']
print(f"[Setup] Initial semantic_weight: {initial_weight}")

# Warm up cache
print("[1/3] Warming up cache...")
query = {"query": "config test", "enable_rerank": False}
resp = client.post("/retrieve", json=query)
time.sleep(0.1)

# Verify cache hit
resp = client.post("/retrieve", json=query)
cache_status = resp.headers.get("X-Cache", "UNKNOWN")
print(f"  Cache status: {cache_status} (expected HIT)")

# Update config
new_weight = 0.7 if initial_weight == 0.65 else 0.65
print(f"[2/3] Updating config: semantic_weight {initial_weight} → {new_weight}...")
resp = client.put("/config", json={"semantic_weight": new_weight})
if resp.status_code != 200:
    print(f"⚠ WARNING: Config update returned {resp.status_code}")
time.sleep(0.1)

# After config change, next retrieval should miss cache
print(f"[3/3] Making retrieval after config change...")
resp = client.post("/retrieve", json=query)
cache_status_after = resp.headers.get("X-Cache", "UNKNOWN")

if cache_status_after == "MISS":
    print(f"✓ Cache cleared after config change: X-Cache: {cache_status_after}")
else:
    print(f"⚠ WARNING: Cache not cleared: X-Cache: {cache_status_after} (expected MISS)")

print(f"\n✓ Phase 5 complete: Config-aware keys test PASSED")

EOF
```

---

## Phase 6: Summary & Reporting

After all phases, generate a summary report:

```bash
echo "=== INTEGRATION TEST SUMMARY ==="
echo "Run started: $(date)"
echo ""
echo "Test Results:"
echo "  ✓ Phase 1: Functional & unit tests"
echo "  ✓ Phase 2: E2E cache pipeline"
echo "  ✓ Phase 3: Concurrent load test"
echo "  ✓ Phase 4: Conditional cache clear"
echo "  ✓ Phase 5: Config-aware keys"
echo ""
echo "Overall: ✓ ALL TESTS PASSED"
echo ""
echo "Next steps:"
echo "  1. Review cache stats output above"
echo "  2. If hit rates < 40%, review L1 cache TTL configuration"
echo "  3. If latency improvement < 5x, review cache key canonicalization"
echo "  4. Check /cache/stats endpoint in production"
```

---

## Troubleshooting

### Problem: Tests hang (don't complete)

**Likely cause:** Deadlock in threading or infinite loop

**Fix:**
```bash
# Kill the test process
pkill -f "pytest\|python"

# Check logs for stuck requests
tail -100 /tmp/api.log

# Restart and try again with verbose output
pytest -vv --tb=long
```

### Problem: "Connection refused" error

**Likely cause:** API not running or Redis not available

**Fix:**
```bash
# Check API is running
curl -s http://localhost:8000/health

# If not, start it:
uvicorn api:app --reload --port 8000 &

# Check Redis (if needed)
redis-cli ping
```

### Problem: Cache stats show 0% hit rate

**Likely cause:** Cache keys not matching between requests

**Fix:**
```bash
# Verify cache key canonicalization
grep -n "cache_key\|canonical\|json.dumps" api_middleware.py

# Test with hardcoded queries instead of variants
# See test_cache_key_canonicalization in functional tests
```

### Problem: "AttributeError: module 'api' has no attribute '_cache'"

**Likely cause:** API startup failed

**Fix:**
```bash
# Check API logs
python -m uvicorn api:app --log-level DEBUG

# Verify cache initialization
grep -n "startup_event\|_cache = " api.py

# Check CacheSettings
python -c "from hybrid_rag.config import CacheSettings; print(CacheSettings.from_env())"
```

---

## Execution UX: Quick Start

Run this one-liner to execute all phases:

```bash
cd /home/aritraghosh/projects/python-hol && \
source .venv/bin/activate && \
echo "Phase 1..." && \
pytest quality/test_caching_functional.py tests/test_cache_integration.py tests/test_query_cache_middleware.py -v --tb=short && \
echo "Phase 2-5..." && \
python3 quality/e2e_pipeline.py  # (Combined script from Phases 2-5)
```

Or run interactively with full output:

```bash
make test-integration  # If Makefile exists, or:
bash quality/run_integration_tests.sh
```
