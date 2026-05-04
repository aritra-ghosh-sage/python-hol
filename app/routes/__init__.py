from app.routes.health import router as health_router
from app.routes.config import router as config_router
from app.routes.cache import router as cache_router
from app.routes.documents import router as documents_router
from app.routes.collections import router as collections_router
from app.routes.ws import router as ws_router

__all__ = [
    "health_router",
    "config_router",
    "cache_router",
    "documents_router",
    "collections_router",
    "ws_router",
]
