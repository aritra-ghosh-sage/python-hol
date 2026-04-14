"""FastAPI REST API for Hybrid RAG Retrieval Service.

This module provides a production-ready REST API for the hybrid RAG library,
including health checks, retrieval endpoints, and configuration management.
"""

import logging
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from hybrid_rag import (
    HybridRetriever,
    HybridRetrieverConfig,
    RetrievalError,
    RetrieverNotInitializedError,
    VectorDBError,
    initialize_vector_db,
    get_sample_documents,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

__all__ = ["app", "initialize_retriever"]

# Global retriever instance
_retriever: Optional[HybridRetriever] = None
_config: Optional[HybridRetrieverConfig] = None


# Pydantic models for request/response validation
class RetrievalRequest(BaseModel):
    """Request model for document retrieval."""

    query: str = Field(
        ..., min_length=1, max_length=500, description="Search query"
    )
    enable_rerank: Optional[bool] = Field(
        None, description="Override reranking setting"
    )


class DocumentResult(BaseModel):
    """Model representing a single retrieved document."""

    id: str = Field(..., description="Document identifier")
    text: str = Field(..., description="Document text content")
    source: str = Field(..., description="Document source URL")
    score: float = Field(..., ge=0.0, le=1.0, description="Relevance score")


class RetrievalResponse(BaseModel):
    """Response model for retrieval requests."""

    query: str = Field(..., description="Original search query")
    results: List[DocumentResult] = Field(
        ..., description="List of retrieved documents"
    )
    total_results: int = Field(..., ge=0, description="Total number of results")


class ConfigResponse(BaseModel):
    """Response model for configuration endpoint."""

    semantic_top_k: int
    keyword_top_k: int
    final_top_k: int
    semantic_weight: float
    keyword_weight: float
    enable_rerank: bool
    pre_rerank_top_k: int


class HealthResponse(BaseModel):
    """Response model for health check endpoint."""

    status: str = Field(..., description="Service status")
    retriever_ready: str = Field(..., description="Retriever readiness status")


class ConfigUpdateRequest(BaseModel):
    """Request model for configuration updates.

    All fields are optional - only provided fields will be updated.
    """

    semantic_top_k: Optional[int] = Field(
        None, gt=0, description="Number of semantic search results"
    )
    keyword_top_k: Optional[int] = Field(
        None, gt=0, description="Number of keyword search results"
    )
    final_top_k: Optional[int] = Field(
        None, gt=0, description="Maximum final results to return"
    )
    semantic_weight: Optional[float] = Field(
        None, ge=0.0, le=1.0, description="Weight for semantic search (0-1)"
    )
    keyword_weight: Optional[float] = Field(
        None, ge=0.0, le=1.0, description="Weight for keyword search (0-1)"
    )
    enable_rerank: Optional[bool] = Field(
        None, description="Enable cross-encoder reranking"
    )
    pre_rerank_top_k: Optional[int] = Field(
        None, gt=0, description="Candidates to rerank before selection"
    )


def initialize_retriever() -> None:
    """Initialize the global hybrid retriever instance.

    Sets up the vector database and creates a HybridRetriever with default
    configuration. Called during application startup.

    Raises:
        VectorDBError: If vector database initialization fails.
        Exception: If any other initialization step fails.
    """
    global _retriever, _config

    try:
        logger.info("Initializing hybrid retriever...")

        # Initialize configuration
        _config = HybridRetrieverConfig(
            semantic_weight=0.7, keyword_weight=0.3, enable_rerank=True
        )

        # Initialize vector database
        logger.debug("Loading sample documents...")
        documents = get_sample_documents()

        logger.debug("Initializing vector database...")
        collection = initialize_vector_db(documents)

        # Create retriever
        _retriever = HybridRetriever(collection, _config)
        logger.info("✓ Hybrid retriever initialized successfully")

    except VectorDBError as e:
        logger.error(f"Vector DB initialization failed: {e}")
        raise
    except Exception as e:
        logger.error(f"Retriever initialization failed: {e}")
        raise


# FastAPI application
app = FastAPI(
    title="Hybrid RAG Retriever API",
    description="REST API for hybrid semantic and keyword-based document retrieval",
    version="1.0.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
)


@app.on_event("startup")
async def startup_event() -> None:
    """Application startup event handler."""
    try:
        initialize_retriever()
    except Exception as e:
        logger.critical(f"Failed to start application: {e}")
        raise


@app.get(
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
    is_ready = _retriever is not None
    return HealthResponse(
        status="healthy", retriever_ready="yes" if is_ready else "no"
    )


@app.post(
    "/retrieve",
    response_model=RetrievalResponse,
    tags=["Retrieval"],
    summary="Retrieve relevant documents",
)
async def retrieve(request: RetrievalRequest) -> RetrievalResponse:
    """Retrieve documents relevant to the provided query.

    Performs hybrid retrieval combining semantic and keyword search,
    with optional cross-encoder reranking.

    Args:
        request: RetrievalRequest with query and optional reranking setting.

    Returns:
        RetrievalResponse with relevant documents and scores.

    Raises:
        HTTPException: 503 if retriever not initialized, 500 if retrieval fails.

    Example:
        POST /retrieve
        {
            "query": "How do I use offline maps?",
            "enable_rerank": true
        }
    """
    if _retriever is None or _config is None:
        logger.error("Retriever not initialized")
        raise HTTPException(
            status_code=503,
            detail="Retriever service not initialized. Try again later.",
        )

    try:
        logger.info(f"Retrieval request: {request.query[:50]}...")

        # Temporarily override reranking if requested
        original_rerank = _config.enable_rerank
        if request.enable_rerank is not None:
            _config.enable_rerank = request.enable_rerank
            logger.debug(f"Reranking override: {request.enable_rerank}")

        try:
            results = _retriever.retrieve(request.query)
        finally:
            # Restore original setting
            _config.enable_rerank = original_rerank

        # Convert results to response model
        doc_results = [
            DocumentResult(
                id=r["id"],
                text=r["text"],
                source=r["metadata"]["source"],
                score=float(r["score"]),
            )
            for r in results
        ]

        logger.info(f"Retrieval complete: {len(doc_results)} results")
        return RetrievalResponse(
            query=request.query, results=doc_results, total_results=len(doc_results)
        )

    except RetrievalError as e:
        logger.error(f"Retrieval error: {e}")
        raise HTTPException(status_code=500, detail=f"Retrieval failed: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error during retrieval: {e}")
        raise HTTPException(status_code=500, detail=f"Retrieval failed: {str(e)}")


@app.post(
    "/retrieve-filtered",
    response_model=RetrievalResponse,
    tags=["Retrieval"],
    summary="Retrieve documents with score filtering",
)
async def retrieve_filtered(
    request: RetrievalRequest, min_score: float = 0.5
) -> RetrievalResponse:
    """Retrieve documents with optional minimum score filtering.

    Similar to /retrieve but filters results by minimum relevance score.

    Args:
        request: RetrievalRequest with query and optional reranking setting.
        min_score: Minimum relevance score (0.0-1.0) for results. Defaults to 0.5.

    Returns:
        RetrievalResponse with filtered documents.

    Raises:
        HTTPException: 400 if min_score invalid, 503 if not initialized, 500 if fails.

    Example:
        POST /retrieve-filtered?min_score=0.8
        {
            "query": "How do I update maps?"
        }
    """
    if not 0.0 <= min_score <= 1.0:
        logger.warning(f"Invalid min_score: {min_score}")
        raise HTTPException(
            status_code=400, detail="min_score must be in range [0.0, 1.0]"
        )

    if _retriever is None or _config is None:
        logger.error("Retriever not initialized")
        raise HTTPException(
            status_code=503,
            detail="Retriever service not initialized. Try again later.",
        )

    try:
        logger.info(
            f"Filtered retrieval request: {request.query[:50]}... (min_score={min_score})"
        )

        original_rerank = _config.enable_rerank
        if request.enable_rerank is not None:
            _config.enable_rerank = request.enable_rerank

        try:
            results = _retriever.retrieve(request.query)
        finally:
            _config.enable_rerank = original_rerank

        # Filter results by minimum score
        filtered_results = [r for r in results if r["score"] >= min_score]
        logger.debug(
            f"Filtered from {len(results)} to {len(filtered_results)} results"
        )

        doc_results = [
            DocumentResult(
                id=r["id"],
                text=r["text"],
                source=r["metadata"]["source"],
                score=float(r["score"]),
            )
            for r in filtered_results
        ]

        logger.info(f"Filtered retrieval complete: {len(doc_results)} results")
        return RetrievalResponse(
            query=request.query, results=doc_results, total_results=len(doc_results)
        )

    except RetrievalError as e:
        logger.error(f"Retrieval error: {e}")
        raise HTTPException(status_code=500, detail=f"Retrieval failed: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error during filtered retrieval: {e}")
        raise HTTPException(status_code=500, detail=f"Retrieval failed: {str(e)}")


@app.get(
    "/config",
    response_model=ConfigResponse,
    tags=["Configuration"],
    summary="Get retriever configuration",
)
async def get_config() -> ConfigResponse:
    """Get the current retriever configuration.

    Returns:
        ConfigResponse with all configuration parameters.

    Raises:
        HTTPException: 503 if retriever not initialized.

    Example:
        GET /config
        Response: {
            "semantic_top_k": 10,
            "keyword_top_k": 10,
            ...
        }
    """
    if _config is None:
        logger.error("Retriever not initialized")
        raise HTTPException(
            status_code=503,
            detail="Retriever not initialized. Try again later.",
        )

    return ConfigResponse(
        semantic_top_k=_config.semantic_top_k,
        keyword_top_k=_config.keyword_top_k,
        final_top_k=_config.final_top_k,
        semantic_weight=_config.semantic_weight,
        keyword_weight=_config.keyword_weight,
        enable_rerank=_config.enable_rerank,
        pre_rerank_top_k=_config.pre_rerank_top_k,
    )


@app.put(
    "/config",
    response_model=ConfigResponse,
    tags=["Configuration"],
    summary="Update retriever configuration",
)
async def update_config(request: ConfigUpdateRequest) -> ConfigResponse:
    """Update the retriever configuration with new values.

    Only provided fields are updated. Configuration updates are validated
    before being applied, ensuring semantic_weight + keyword_weight = 1.0
    and all parameters are within valid ranges.

    Args:
        request: ConfigUpdateRequest with fields to update (all optional).

    Returns:
        ConfigResponse with the updated configuration.

    Raises:
        HTTPException: 400 if validation fails, 503 if not initialized.

    Example:
        PUT /config
        {
            "semantic_weight": 0.8,
            "keyword_weight": 0.2
        }
        Response: {
            "semantic_top_k": 10,
            "semantic_weight": 0.8,
            "keyword_weight": 0.2,
            ...
        }
    """
    global _config

    if _config is None:
        logger.error("Retriever not initialized")
        raise HTTPException(
            status_code=503,
            detail="Retriever not initialized. Try again later.",
        )

    try:
        # Extract only provided fields
        update_dict = request.model_dump(exclude_unset=True)

        if not update_dict:
            logger.debug("No configuration updates provided")
            return ConfigResponse(
                semantic_top_k=_config.semantic_top_k,
                keyword_top_k=_config.keyword_top_k,
                final_top_k=_config.final_top_k,
                semantic_weight=_config.semantic_weight,
                keyword_weight=_config.keyword_weight,
                enable_rerank=_config.enable_rerank,
                pre_rerank_top_k=_config.pre_rerank_top_k,
            )

        logger.info(f"Updating configuration with: {update_dict}")

        # Create updated configuration (validates automatically in __post_init__)
        _config = _config.update(**update_dict)

        logger.info("Configuration updated successfully")
        return ConfigResponse(
            semantic_top_k=_config.semantic_top_k,
            keyword_top_k=_config.keyword_top_k,
            final_top_k=_config.final_top_k,
            semantic_weight=_config.semantic_weight,
            keyword_weight=_config.keyword_weight,
            enable_rerank=_config.enable_rerank,
            pre_rerank_top_k=_config.pre_rerank_top_k,
        )

    except ValueError as e:
        logger.warning(f"Configuration validation failed: {e}")
        raise HTTPException(
            status_code=400,
            detail=f"Configuration validation failed: {str(e)}",
        )
    except TypeError as e:
        logger.warning(f"Invalid configuration parameter: {e}")
        raise HTTPException(
            status_code=400,
            detail=f"Invalid configuration parameter: {str(e)}",
        )
    except Exception as e:
        logger.error(f"Configuration update failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Configuration update failed: {str(e)}",
        )


# Application info endpoints
@app.get("/", tags=["Info"], summary="API information")
async def root() -> dict:
    """Root endpoint with API information."""
    return {
        "name": "Hybrid RAG Retriever API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
    }


if __name__ == "__main__":
    import uvicorn

    logger.info("🚀 Starting Hybrid RAG Retriever API...")
    logger.info("📖 Swagger UI: http://localhost:8000/docs")
    logger.info("📋 ReDoc: http://localhost:8000/redoc")
    logger.info("🔧 Health Check: http://localhost:8000/health")

    uvicorn.run(app, host="0.0.0.0", port=8000)
