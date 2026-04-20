# RUN_CODE_REVIEW.md — Caching System Code Review Protocol

**Purpose:** Structured guardrails for code review (human or AI) of cache-related changes.

**When to use:** Before merging any PR that touches `hybrid_rag/cache.py`, `api_middleware.py`, `api.py` (cache integration), or `hybrid_rag/config.py`.

**How it works:** Three phases: (1) prepare, (2) review with guardrails, (3) regression tests.

---

## Phase 1: Preparation

### Step 1.1: Read Context Files

Before reviewing a single line of code, read these files in order:

1. **quality/QUALITY.md** (5 min) — Understand what quality means for this system
2. **Caching_Architecture_Blueprint.md** § 1-3 (10 min) — Understand 3-layer strategy
3. **plan.yaml** (5 min) — Understand implementation roadmap and ADRs
4. **The PR description** (5 min) — What problem does this PR solve?

### Step 1.2: Identify Which Scenarios Apply

Match the PR against fitness scenarios in QUALITY.md:

| PR Focus | Relevant Scenario(s) |
|----------|---------------------|
| Config update + cache invalidation | Scenario #1 (config-aware keys) |
| Concurrent requests; latency issues | Scenario #2 (stampede) |
| Ingest with cache clear behavior | Scenario #3 (aggressive invalidation) |
| Redis/backend failure handling | Scenario #4 (fail-open) |
| Threading; concurrent cache ops | Scenario #5 (thread safety) |
| Cache key generation logic | Scenario #6 (canonicalization) |
| Hit rate / TTL tuning | Scenario #7 (hit rate distribution) |
| X-Cache header; stats endpoint | Scenario #8 (X-Cache accuracy) |

**Record:** "This PR affects Scenarios #X, #Y, #Z"

### Step 1.3: List Files Changed

Run: `git diff --name-only`

Organize into subsystems:

```
Core caching (hybrid_rag/cache.py):
- [file1.py] [line range] [change type]

API integration (api.py, api_middleware.py):
- [file2.py] [line range] [change type]

Configuration (hybrid_rag/config.py):
- [file3.py] [line range] [change type]

Tests (tests/, quality/):
- [test_file.py] [line range] [change type]
```

---

## Phase 2: Code Review with Guardrails

### Mandatory Guardrail 1: Line Numbers

**Rule:** Every finding must include a file and line number. No line number = not reviewable.

**Pattern:** `[file.py:LINE] finding description`

**Example:**
✓ `[hybrid_rag/cache.py:145] Missing type hint on return value`  
✗ `In cache.py, there's a potential race condition` ← No line number

**How:** Use `grep -n` to find patterns:
```bash
grep -n "def set" hybrid_rag/cache.py
grep -n "threading" hybrid_rag/cache.py
grep -n "json.dumps" api_middleware.py
```

### Mandatory Guardrail 2: Grep Before Claiming

**Rule:** Before saying "this code is missing X", verify that X is actually missing by grepping for it.

**Pattern:** Grep for the pattern you claim is missing; if it exists, retract the finding.

**Examples:**

❌ **WRONG:**
> "There's no error handling in the cache.get() method."

**FIX:** Grep first:
```bash
grep -A 10 "def get" hybrid_rag/cache.py | grep -E "except|try"
```
If try/except is there, retract the finding.

✓ **CORRECT:**
> "[hybrid_rag/cache.py:67] Missing error handling in get() method. Found bare except clause (line 70) but no logging. Should log at WARNING level."

### Mandatory Guardrail 3: Read Function Bodies, Not Just Signatures

**Rule:** Don't judge a function by its name and docstring; read the implementation.

**Example:**

❌ **SURFACE REVIEW:**
```python
def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
    """Store value in cache."""
    # Looks complete from the signature
```

✓ **DEEP REVIEW:**
```python
def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
    """Store value in cache."""
    try:
        self._cache[key] = value
    except Exception as e:
        logger.warning(f"Cache set failed: {e}")
        # Verify: (1) is logger created? (2) is the error level right?
        # (3) does it fail gracefully (not crash)?
```

**How:** For every function you review:
1. Read the entire function body (not just first 5 lines)
2. Trace the data flow (inputs → processing → outputs)
3. Check error paths (what happens on failure?)
4. Verify assumptions (e.g., "dict[key] exists")

### Mandatory Guardrail 4: Flag Uncertain Findings as QUESTION

**Rule:** If you're not sure whether something is a bug, mark it as `QUESTION`, not `BUG`.

**Pattern:** `[file.py:LINE] QUESTION: Is X correct? Evidence: ...`

**Example:**
```
[api_middleware.py:95] QUESTION: Should TTL override respect per-key values?
Current: ttl_seconds parameter accepted but ignored by cachetools.TTLCache
Evidence: cachetools.TTLCache uses global TTL, not per-key TTL
Suggestion: Document this limitation in docstring or switch to custom TTL impl
```

**Why:** False positives destroy trust in code reviews. Better to ask than to claim.

### Mandatory Guardrail 5: Never Suggest Style Changes

**Rule:** Flag only things that are incorrect, not things that are different from your preferred style.

❌ **WRONG:**
> "I would use f-strings instead of .format()"

✓ **CORRECT:**
> "[api_middleware.py:67] Typo in error message: 'retreive' should be 'retrieve'"

### Security Focus Areas (Pre-Check)

Before the full review, scan for these security patterns:

| Pattern | Command | Risk |
|---------|---------|------|
| Unencrypted PII | `grep -n "password\|ssn\|credit" api.py` | Data leak in Redis |
| SQL injection (N/A here) | `grep -n "db.execute\|query\|SELECT" api.py` | Query manipulation |
| Secrets in logs | `grep -n "logger.*password\|logger.*secret" *.py` | Secrets exposure |
| Unvalidated cache keys | `grep -n "cache.set.*user_input" api.py` | Key collision / bypass |
| Unsafe deserialization | `grep -n "pickle\|eval\|exec" hybrid_rag/cache.py` | Code execution |

**Action:** If any matches, flag them; if none, note "Security pre-check: OK"

### Review Checklist by Subsystem

#### hybrid_rag/cache.py

- [ ] CacheBackend ABC has exactly 5 abstract methods (get, set, delete, clear, stats)
- [ ] InMemoryCache uses threading.Lock for thread safety
- [ ] RedisCache has try-except around redis.Redis operations (fail-open)
- [ ] All JSON serialization has error handling
- [ ] stats() returns dict with exactly: backend, hits, misses, hit_rate, size, max_size, ttl_seconds, timestamp
- [ ] Every public function has complete type hints
- [ ] Every public function has Google-style docstring with Example section
- [ ] No bare `except:` clauses; always catch specific exceptions
- [ ] All logging at appropriate level (DEBUG, INFO, WARNING, ERROR)
- [ ] TTL expiration tested (values expire after ttl_seconds)

#### api_middleware.py

- [ ] QueryCacheMiddleware uses ASGI receive() replay pattern correctly
- [ ] Cache key generation is deterministic (same input → same key)
- [ ] Cache key includes `enable_rerank` flag (ADR-002)
- [ ] X-Cache response header set to HIT, MISS, or ERROR
- [ ] Excluded paths respected (health, config, ingest, cache/stats)
- [ ] Try-except around all cache operations (fail-open)
- [ ] Request body not corrupted by replay pattern (no double-read)
- [ ] Middleware preserves original response body (not consumed)
- [ ] All logging at INFO (for operations) or WARNING (for errors)

#### api.py (cache integration)

- [ ] Cache initialized in startup_event() from CacheSettings.from_env()
- [ ] create_cache_backend() factory called to instantiate backend
- [ ] Lazy wrapper used if cache optional
- [ ] POST /config calls cache.clear() after config update (ADR-006)
- [ ] POST /ingest checks ingest_type before calling cache.clear() (ADR-003)
- [ ] GET /cache/stats endpoint returns CacheStatsResponse model
- [ ] Cache stats accessible without auth (or documented if auth required)
- [ ] Cache initialized before routes are added to app
- [ ] Cache cleared on shutdown (if resources require cleanup)
- [ ] All cache operations wrapped in try-except (fail-open)

#### hybrid_rag/config.py

- [ ] CacheSettings dataclass has all required fields
- [ ] __post_init__ validates backend + redis_url consistency
- [ ] CacheSettings.from_env() reads environment variables with correct defaults
- [ ] create_cache_backend() returns correct backend type for setting.backend
- [ ] Error messages are clear (not "Invalid backend" but "backend must be 'redis' or 'memory'")

---

## Phase 3: Regression Tests

For every BUG finding in Phase 2, write a regression test that reproduces the bug.

### Step 3.1: Categorize Findings

```
BUG findings:  [List]
QUESTION findings: [List]
SUGGESTION findings: [List]
False positives to retract: [List]
```

### Step 3.2: Write Regression Tests

For each BUG:

**Template:**
```python
def test_regression_[short_bug_name]():
    """Regression test for [bug description].
    
    Bug: [from code review finding]
    Expected: [what should happen]
    Actual (before fix): [what actually happens]
    """
    # Reproduce the bug
    # Verify the bug exists
    assert False, "Bug should be fixed; this test should pass"
```

**Example:**
```python
def test_regression_cache_not_thread_safe():
    """Regression: InMemoryCache not thread-safe under concurrent writes.
    
    Bug: [hybrid_rag/cache.py:123] Missing threading.Lock in __setitem__
    Expected: Concurrent writes don't corrupt cache state
    Actual: Race condition when 2+ threads write simultaneously
    """
    cache = InMemoryCache()
    errors = []
    
    def concurrent_writer(idx):
        try:
            for i in range(100):
                cache.set(f"key_{idx}_{i}", f"value_{idx}_{i}")
        except Exception as e:
            errors.append(e)
    
    threads = [threading.Thread(target=concurrent_writer, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    
    # Before fix: len(errors) > 0
    # After fix: len(errors) == 0
    assert len(errors) == 0
```

### Step 3.3: Run Tests and Report

**Command:**
```bash
cd quality/
pytest test_regression_*.py -v
```

**Report format:**

```
Regression Test Results
=======================

[BUG: description]
  Test: test_regression_xxx
  Status: PASS ✓ (bug is fixed)
  or
  Status: FAIL ✗ (bug still present)

[BUG: description]
  ...
```

---

## Output Format

Present findings as a structured report:

```
CODE REVIEW REPORT — Caching System
====================================

PR: [PR number and title]
Affects scenarios: #1, #4
Files changed: 3 (api_middleware.py, api.py, test_query_cache_middleware.py)

SECURITY PRE-CHECK
  ✓ No unencrypted PII in cache keys
  ✓ No secrets in logs
  ✓ No unsafe deserialization

FINDINGS (by severity)

CRITICAL BUGS:
  [ ] None found

IMPORTANT BUGS:
  [api_middleware.py:145] Missing error handling in cache.set() call
     Error: Line 145 has cache.set(key, value) with no try-except
     Impact: If cache backend fails, entire request fails
     Fix: Wrap in try-except with logging at WARNING level

SUGGESTIONS:
  [hybrid_rag/cache.py:89] Consider adding max_size validation in __post_init__
     Current: max_size accepted but not validated
     Suggestion: Validate max_size > 0 in __post_init__, raise ValueError if not

QUESTIONS (need author input):
  [api.py:234] QUESTION: Should cache clear on ingest with type="add"?
     Current code: if ingest_type == "update": cache.clear()
     Evidence: blueprint.md suggests "add" preserves cache, "update" clears
     Clarification needed: Is this the intended behavior?

REGRESSION TESTS
  ✓ test_regression_cache_error_handling: PASS
  ✓ test_regression_thread_safety: PASS
  ✓ test_regression_config_invalidation: PASS

RECOMMENDATION: [APPROVE | REQUEST CHANGES | NEEDS DISCUSSION]
  - All critical bugs fixed
  - 1 suggestion (non-blocking)
  - 1 question requires clarification before merge
```

---

## Reference: Search Commands

**Common grep patterns for cache review:**

```bash
# Find all cache operations
grep -n "cache\." api.py api_middleware.py

# Find try-except blocks
grep -B 2 -A 5 "except" hybrid_rag/cache.py

# Find type hints
grep -n "def " hybrid_rag/cache.py | grep -v "->"

# Find logging calls
grep -n "logger\." hybrid_rag/cache.py

# Find JSON operations (serialization risks)
grep -n "json\." hybrid_rag/cache.py api_middleware.py

# Find threading operations
grep -n "threading\|Thread\|Lock" hybrid_rag/cache.py

# Find hardcoded values (should use constants)
grep -n "3600\|10000\|86400" hybrid_rag/cache.py

# Find incomplete error handling
grep -n "except.*:" hybrid_rag/cache.py | grep -v "Exception\|Error"
```

---

## When to Halt the Review

Stop and escalate if:

1. **Security finding:** Unencrypted secrets in cache or logs → immediately escalate to security team
2. **Data corruption risk:** Race condition or state corruption → don't merge; needs architecture fix
3. **Silent failure:** Code that fails silently without logging → request logging before merge
4. **Test coverage:** Tests missing for new scenarios → request tests before merge
5. **Unclear intent:** Code that's unclear and no docstring → request documentation before merge

---

## Example: Full Review Session

**Scenario:** PR adds config change invalidation (ADR-006 implementation)

**Preparation:**
- ✓ Read QUALITY.md
- ✓ Read Caching_Architecture_Blueprint.md
- ✓ Read plan.yaml
- PR: "Implement ADR-006: Clear cache on config updates"
- Affects: Scenario #1 (config-aware keys)
- Files: api.py (+15 lines), tests/test_config_api.py (+20 lines)

**Phase 2 Review:**

```
[api.py:234] FINDING: Config update handler
Line 234-240:
    def put_config(update: ConfigUpdateRequest) -> ConfigResponse:
        global _config
        _config = _config.update(**update.dict())
        # Missing: lazy_cache.clear()
        return _config.to_response()

BUG FOUND: [api.py:234-240] Config update does not clear cache (ADR-006 not implemented)
  Severity: CRITICAL
  Impact: Users change config, but cached responses still use old config
  Fix: Add line before return: lazy_cache.clear()
  Grep confirm: grep -n "lazy_cache.clear" api.py → [no match]
```

```
[tests/test_config_api.py:45] FINDING: Test coverage for cache clear
test_config_update_clears_cache():
    cache.set("query_key", "old_response")
    resp = client.put("/config", json={"semantic_weight": 0.8})
    # Missing: Assert cache is cleared
    assert resp.status_code == 200

SUGGESTION: Assert cache is actually cleared
  Add: assert cache.stats()["size"] == 0
```

**Phase 3: Regression Tests**

```python
def test_regression_config_update_cache_clear():
    """ADR-006: Config update must clear cache."""
    cache = InMemoryCache()
    
    # Pre-populate cache
    cache.set("query_key", {"results": ["old"]})
    assert cache.stats()["size"] == 1
    
    # Call config update (in real test, use TestClient)
    # config.update(semantic_weight=0.8)
    # cache.clear()  # This is the fix
    
    assert cache.stats()["size"] == 0  # Cache cleared
```

**Output:**

```
RECOMMENDATION: REQUEST CHANGES
- 1 CRITICAL bug (missing cache.clear())
- 1 SUGGESTION (add assertion to test)
- After fixes: APPROVE
```
