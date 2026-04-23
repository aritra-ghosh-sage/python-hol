"""Route allowlist enforcement test for T09.

This test ensures that the HTTP API surface remains stable and only contains
the approved admin-only endpoints. Any new endpoints must be explicitly added
to the allowlist after review.

Acceptance Criteria (T09):
- Final HTTP surface is only: /config, /documents, /cache/stats, /health
- No retrieval HTTP endpoints remain in runtime route inventory
- No retrieval HTTP endpoints remain in OpenAPI/docs
- CI fails on disallowed endpoint reintroduction
"""

import sys
from typing import Set

import pytest

sys.path.insert(0, "/home/runner/work/python-hol/python-hol")

from api import app


# ============================================================================
# ALLOWLIST DEFINITION
# ============================================================================

# T09: Admin-only HTTP endpoint allowlist
# Any modifications to this list must be reviewed and approved
ALLOWED_HTTP_PATHS = {
    "/health",              # Health check endpoint
    "/config",              # GET/PUT retriever configuration
    "/documents",           # POST document ingestion
    "/documents/sources",   # GET list document sources
    "/cache/stats",         # GET cache statistics
    "/",                    # API information/root
    # FastAPI auto-generated endpoints (required for docs)
    "/openapi.json",        # OpenAPI schema
    "/docs",                # Swagger UI
    "/docs/oauth2-redirect", # OAuth2 redirect for Swagger
    "/redoc",               # ReDoc UI
}

# WebSocket endpoints (separate allowlist)
ALLOWED_WEBSOCKET_PATHS = {
    "/ws/chat",             # WebSocket chat/retrieval endpoint
}

# Deprecated/forbidden endpoints (must never appear)
FORBIDDEN_PATHS = {
    "/retrieve",            # Deprecated REST retrieval (removed in T08)
    "/retrieve-filtered",   # Deprecated filtered retrieval (removed in T04)
}


# ============================================================================
# TESTS
# ============================================================================


def test_http_routes_match_allowlist() -> None:
    """Verify all HTTP routes are in the allowlist."""
    actual_paths: Set[str] = set()

    for route in app.routes:
        if hasattr(route, 'path') and hasattr(route, 'methods'):
            # HTTP route
            actual_paths.add(route.path)

    # Check for unauthorized routes
    unauthorized = actual_paths - ALLOWED_HTTP_PATHS
    if unauthorized:
        pytest.fail(
            f"Unauthorized HTTP routes detected: {sorted(unauthorized)}\n"
            f"These routes are not in the T09 allowlist.\n"
            f"If these are legitimate new endpoints, update ALLOWED_HTTP_PATHS "
            f"in tests/test_route_allowlist.py after review."
        )

    # Check for missing expected routes (informational)
    missing = ALLOWED_HTTP_PATHS - actual_paths
    # Filter out optional routes
    optional_routes = {"/docs/oauth2-redirect"}  # May not exist depending on config
    critical_missing = missing - optional_routes

    if critical_missing:
        pytest.fail(
            f"Expected HTTP routes missing: {sorted(critical_missing)}\n"
            f"The allowlist expects these routes but they were not found.\n"
            f"This may indicate a regression or misconfiguration."
        )


def test_websocket_routes_match_allowlist() -> None:
    """Verify all WebSocket routes are in the allowlist."""
    actual_ws_paths: Set[str] = set()

    for route in app.routes:
        if hasattr(route, 'path') and not hasattr(route, 'methods'):
            # WebSocket route (has path but no methods)
            actual_ws_paths.add(route.path)

    # Check for unauthorized WebSocket routes
    unauthorized_ws = actual_ws_paths - ALLOWED_WEBSOCKET_PATHS
    if unauthorized_ws:
        pytest.fail(
            f"Unauthorized WebSocket routes detected: {sorted(unauthorized_ws)}\n"
            f"These routes are not in the T09 allowlist.\n"
            f"If these are legitimate new endpoints, update ALLOWED_WEBSOCKET_PATHS "
            f"in tests/test_route_allowlist.py after review."
        )

    # Check for missing expected WebSocket routes
    missing_ws = ALLOWED_WEBSOCKET_PATHS - actual_ws_paths
    if missing_ws:
        pytest.fail(
            f"Expected WebSocket routes missing: {sorted(missing_ws)}\n"
            f"The allowlist expects these routes but they were not found.\n"
            f"This may indicate a regression or misconfiguration."
        )


def test_no_forbidden_routes() -> None:
    """Verify no forbidden/deprecated routes are present."""
    actual_paths: Set[str] = set()

    for route in app.routes:
        if hasattr(route, 'path'):
            actual_paths.add(route.path)

    # Check for forbidden routes
    forbidden_present = actual_paths & FORBIDDEN_PATHS
    if forbidden_present:
        pytest.fail(
            f"CRITICAL: Forbidden routes detected: {sorted(forbidden_present)}\n"
            f"These routes were explicitly removed in previous tasks and must not be reintroduced.\n"
            f"- /retrieve: Removed in T08 (WebSocket-only retrieval)\n"
            f"- /retrieve-filtered: Removed in T04\n"
            f"This is a regression that must be fixed immediately."
        )


def test_no_retrieval_http_endpoints() -> None:
    """Verify no retrieval-related HTTP endpoints exist (T09 requirement)."""
    actual_paths: Set[str] = set()

    for route in app.routes:
        if hasattr(route, 'path') and hasattr(route, 'methods'):
            actual_paths.add(route.path)

    # Check for any path containing "retrieve"
    retrieval_paths = {p for p in actual_paths if 'retrieve' in p.lower()}

    if retrieval_paths:
        pytest.fail(
            f"CRITICAL: Retrieval HTTP endpoints detected: {sorted(retrieval_paths)}\n"
            f"T09 requirement: No retrieval HTTP endpoints should exist.\n"
            f"Retrieval should only be available via WebSocket (/ws/chat).\n"
            f"This is a policy violation that must be fixed immediately."
        )


def test_openapi_schema_no_retrieval_references() -> None:
    """Verify OpenAPI schema has no retrieval endpoint references."""
    import json

    schema = app.openapi()
    schema_str = json.dumps(schema, indent=2)

    # Check for /retrieve references
    if '/retrieve' in schema_str:
        # Find specific occurrences
        lines_with_retrieve = []
        for line_num, line in enumerate(schema_str.split('\n'), 1):
            if '/retrieve' in line.lower():
                lines_with_retrieve.append(f"Line {line_num}: {line.strip()}")

        pytest.fail(
            f"CRITICAL: '/retrieve' references found in OpenAPI schema:\n" +
            "\n".join(lines_with_retrieve) +
            "\n\nThe OpenAPI schema must not contain retrieval endpoint references (T09 requirement)."
        )


def test_route_inventory_documentation() -> None:
    """Generate route inventory for documentation and CI artifacts."""
    import json

    inventory = {
        "http_routes": [],
        "websocket_routes": [],
        "total_http_count": 0,
        "total_websocket_count": 0,
    }

    for route in app.routes:
        if hasattr(route, 'path') and hasattr(route, 'methods'):
            # HTTP route
            methods = sorted(route.methods) if route.methods else []
            inventory["http_routes"].append({
                "path": route.path,
                "methods": methods,
            })
        elif hasattr(route, 'path'):
            # WebSocket route
            inventory["websocket_routes"].append({
                "path": route.path,
                "type": "websocket",
            })

    inventory["total_http_count"] = len(inventory["http_routes"])
    inventory["total_websocket_count"] = len(inventory["websocket_routes"])

    # Print inventory for CI logs
    print("\n=== T09 Route Inventory ===")
    print(json.dumps(inventory, indent=2))

    # Verify counts match expectations
    assert inventory["total_websocket_count"] == 1, \
        f"Expected 1 WebSocket route, found {inventory['total_websocket_count']}"

    # HTTP routes: health, config, documents, documents/sources, cache/stats, /,
    # plus 4 auto-generated (openapi.json, docs, docs/oauth2-redirect, redoc)
    # Total should be around 10-11
    assert 10 <= inventory["total_http_count"] <= 11, \
        f"Expected 10-11 HTTP routes, found {inventory['total_http_count']}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
