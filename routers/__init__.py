"""Route handlers for the Hybrid RAG REST API.

Each sub-module exposes a single ``router`` (``fastapi.APIRouter``) that is
registered on the main ``app`` instance in ``api.py``.

Sub-modules:
    health    -- ``GET /health`` and ``GET /``
    config    -- ``GET /config`` and ``PUT /config``
    cache     -- ``GET /cache/stats``
    documents -- ``POST /documents``, ``GET /documents/sources``,
                 ``GET /collections``
    websocket -- ``WS /ws/chat``

WHY: Routers/__init__.py is intentionally minimal (no imports).
     Importing routers here would create a circular dependency:
       api.py → routers/__init__.py → routers.cache → api.py (partially initialized)
     Instead, api.py imports directly from submodules, bypassing __init__.py.
     See api.py lines 635-640 for how the routers are imported.
"""

__all__ = [
    "health",
    "config",
    "cache",
    "documents",
    "websocket",
]
