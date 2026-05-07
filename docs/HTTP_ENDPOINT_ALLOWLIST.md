# HTTP Endpoint Allowlist

Status: active
Scope: FastAPI routes in `api.py` and `routers/`

## Purpose

This file defines the approved public route surface for the backend.
Use it with `tests/test_route_allowlist.py` to prevent accidental endpoint drift.

## Approved HTTP Routes

- `GET /`
  Returns API name, version, and discovery links.
- `GET /health`
  Liveness and retriever readiness probe.
- `GET /config`
  Returns the active retriever configuration.
- `PUT /config`
  Updates the active retriever configuration.
- `POST /documents`
  Ingests text, URL, or file content into the active collection.
- `GET /documents/sources`
  Lists stored document sources and chunk counts.
- `GET /collections`
  Lists available ChromaDB collections and counts.
- `GET /cache/stats`
  Returns layered cache metrics and backend health.

## Approved WebSocket Route

- `WS /ws/chat`
  Primary query path for retrieval and result delivery.

## OpenAPI Routes

These routes are expected when docs are enabled:

- `GET /openapi.json`
- `GET /docs`
- `GET /redoc`
- `GET /docs/oauth2-redirect`

## Policy

- Retrieval stays on `WS /ws/chat`.
- HTTP routes are limited to service info, configuration, ingestion, and observability.
- No new route should be added without updating this file and the allowlist test.
- This repository does not currently enforce authentication in code.
  Production deployments should place auth in front of write and admin endpoints.

## Change Checklist

If you add, rename, or remove a route:

1. Update the router implementation.
2. Update `tests/test_route_allowlist.py`.
3. Update this file.
4. Verify the docs and OpenAPI surface still match reality.

## Verification

Run:

```bash
uv run pytest tests/test_route_allowlist.py -q
uv run pytest tests/ -q
```

## Current Route Inventory

- HTTP business routes: 8
- WebSocket business routes: 1
- Auto-generated docs routes: 4

Keep this file short and factual. If the code changes, update the counts.
