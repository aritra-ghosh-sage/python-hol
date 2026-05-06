"""Health and info endpoints.

Routes:
    GET /health  -- Liveness probe for the retrieval service.
    GET /        -- Root endpoint with API discovery links.
"""

import api  # shared state — accessed inside function bodies to avoid circular-import issues
from api_models import HealthResponse
from fastapi import APIRouter

router = APIRouter()


@router.get(
    "/health",
    response_model=HealthResponse,
    tags=["Health"],
    summary="Health check endpoint",
)
async def health_check() -> HealthResponse:
    """Check the health status of the retrieval service.

    Returns:
        HealthResponse with service status and retriever readiness.

    Example:
        GET /health
        Response: {"status": "healthy", "retriever_ready": "yes"}
    """
    is_ready = api._retriever is not None
    return HealthResponse(
        status="healthy", retriever_ready="yes" if is_ready else "no"
    )


@router.get("/", tags=["Info"], summary="API information")
async def root() -> dict:
    """Root endpoint with API information."""
    return {
        "name": "Hybrid RAG Retriever API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
        "websocket": "/ws/chat",
    }
