"""Health check and root endpoints."""

import logging

import api
from api import HealthResponse
from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["Health"], summary="Health check endpoint")
async def health_check() -> HealthResponse:
    """Check the health status of the retrieval service."""
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
