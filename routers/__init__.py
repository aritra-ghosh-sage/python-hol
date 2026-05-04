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
"""

from routers.cache import router as cache_router
from routers.config import router as config_router
from routers.documents import router as documents_router
from routers.health import router as health_router
from routers.websocket import router as websocket_router

__all__ = [
    "health_router",
    "config_router",
    "cache_router",
    "documents_router",
    "websocket_router",
]
