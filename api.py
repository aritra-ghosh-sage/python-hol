"""FastAPI REST API for Hybrid RAG Retrieval Service.

This module provides a production-ready REST API for the hybrid RAG library,
including health checks, retrieval endpoints, configuration management,
document ingestion, and WebSocket-based chat.
"""

import base64
import io
import logging
import os
from typing import List, Literal, Optional
from contextlib import asynccontextmanager

import requests
from fastapi import FastAPI, HTTPException, WebSocketDisconnect, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from hybrid_rag import (
    HybridRetriever,
    HybridRetrieverConfig,
    RetrievalError,
    RetrieverNotInitializedError,
    VectorDBError,
    initialize_vector_db,
    get_sample_documents,
    chunk_text,
)

with_pdf_support = True
try:
    import pypdf
except ImportError:
    with_pdf_support = False

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
    score: float = Field(..., description="Relevance score (may be negative due to fusion/reranking)")


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


class DocumentIngestionRequest(BaseModel):
    """Request model for adding custom documents."""

    source_type: Literal["text", "url", "file"] = Field(
        ..., description="Type of data source: 'text', 'url', or 'file'"
    )
    content: str = Field(
        ..., min_length=1, description="Text content, URL, or base64-encoded file"
    )
    filename: Optional[str] = Field(
        None, description="Original filename (for file uploads)"
    )
    source_label: Optional[str] = Field(
        None, description="User-friendly label for the data source"
    )


class DocumentIngestionResponse(BaseModel):
    """Response model for document ingestion."""

    status: str = Field(..., description="Operation status ('success' or 'error')")
    documents_added: int = Field(..., description="Number of documents added")
    chunks_created: int = Field(..., description="Number of chunks created")
    message: Optional[str] = Field(None, description="Additional message")


class DocumentSource(BaseModel):
    """Model representing a document source."""

    source: str = Field(..., description="Source identifier")
    count: int = Field(..., description="Number of chunks from this source")


class SourcesResponse(BaseModel):
    """Response model for listing document sources."""

    sources: List[DocumentSource] = Field(
        ..., description="List of available document sources"
    )


class WsMessageBase(BaseModel):
    """Base model for WebSocket messages."""

    type: str = Field(..., description="Message type")


class WsQueryMessage(BaseModel):
    """WebSocket message sent by client (query request)."""

    query: str = Field(
        ..., min_length=1, max_length=500, description="Search query"
    )
    enable_rerank: Optional[bool] = Field(
        None, description="Override reranking setting"
    )


class WsStatusMessage(BaseModel):
    """WebSocket status message sent by server."""

    type: Literal["status"] = "status"
    message: str = Field(..., description="Status message")


class WsResultsMessage(BaseModel):
    """WebSocket results message sent by server."""

    type: Literal["results"] = "results"
    query: str = Field(..., description="Original query")
    results: List[DocumentResult] = Field(..., description="Retrieved documents")
    total_results: int = Field(..., description="Total number of results")


class WsErrorMessage(BaseModel):
    """WebSocket error message sent by server."""

    type: Literal["error"] = "error"
    message: str = Field(..., description="Error message")


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


# @app.on_event("startup")
@asynccontextmanager
async def startup_event(app: FastAPI):
    """Application startup event handler."""
    try:
        initialize_retriever()
        yield
    except Exception as e:
        logger.critical(f"Failed to start application: {e}")
        raise
    global _retriever, _config
    _retriever = None
    _config = None
    logger.info("Application shutdown complete")


# FastAPI application
app = FastAPI(
    title="Hybrid RAG Retriever API",
    description="REST API for hybrid semantic and keyword-based document retrieval with WebSocket chat",
    version="1.0.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
    lifespan=startup_event
)

# Add CORS middleware
allow_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:3001").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
logger.info(f"CORS enabled for origins: {allow_origins}")

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

        # Filter results by minimum score threshold (0.85)
        min_score_threshold = 0.85
        filtered_results = [r for r in results if r["score"] >= min_score_threshold]
        logger.debug(
            f"Filtered from {len(results)} to {len(filtered_results)} results (min_score={min_score_threshold})"
        )

        # Convert results to response model
        doc_results = [
            DocumentResult(
                id=r["id"],
                text=r["text"],
                source=r["metadata"]["source"],
                score=float(r["score"]),
            )
            for r in filtered_results
        ]

        logger.info(f"Retrieval complete: {len(doc_results)} results after filtering")
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

        # Filter results by minimum score, enforcing floor of 0.85 for chat quality
        effective_min_score = max(0.85, min_score)
        filtered_results = [r for r in results if r["score"] >= effective_min_score]
        logger.debug(
            f"Filtered from {len(results)} to {len(filtered_results)} results (min_score={effective_min_score})"
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

        logger.info(f"Filtered retrieval complete: {len(doc_results)} results after filtering")
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


# WebSocket endpoint for real-time chat
@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time document queries.

    Client sends: {"query": str, "enable_rerank": bool?}
    Server sends (in sequence):
      - {"type": "status", "message": str}
      - {"type": "results", "query": str, "results": [...], "total_results": int}
      - {"type": "error", "message": str} (on failure)
    """
    await websocket.accept()
    logger.info("WebSocket client connected")

    try:
        while True:
            # Receive query from client
            data = await websocket.receive_json()
            query = data.get("query", "").strip()
            enable_rerank = data.get("enable_rerank")

            # Validate query
            if not query or len(query) < 1 or len(query) > 500:
                error_msg = WsErrorMessage(
                    message="Query must be between 1 and 500 characters"
                )
                await websocket.send_json(error_msg.model_dump())
                continue

            if _retriever is None or _config is None:
                error_msg = WsErrorMessage(message="Retriever not initialized")
                await websocket.send_json(error_msg.model_dump())
                continue

            try:
                # Send initial status
                status_msg = WsStatusMessage(message="Retrieving documents...")
                await websocket.send_json(status_msg.model_dump())

                # Perform retrieval
                original_rerank = _config.enable_rerank
                if enable_rerank is not None:
                    _config.enable_rerank = enable_rerank

                try:
                    results = _retriever.retrieve(query)
                finally:
                    _config.enable_rerank = original_rerank

                # Filter results by minimum score threshold (0.85)
                min_score_threshold = 0.85
                filtered_results = [r for r in results if r["score"] >= min_score_threshold]
                logger.debug(
                    f"Filtered from {len(results)} to {len(filtered_results)} results (min_score={min_score_threshold})"
                )

                # Convert results to response model
                doc_results = [
                    DocumentResult(
                        id=r["id"],
                        text=r["text"],
                        source=r["metadata"]["source"],
                        score=float(r["score"]),
                    )
                    for r in filtered_results
                ]

                # Send results (total_results reflects post-filter count)
                results_msg = WsResultsMessage(
                    query=query, results=doc_results, total_results=len(doc_results)
                )
                await websocket.send_json(results_msg.model_dump())
                logger.info(f"WebSocket query succeeded: {query[:50]}... ({len(doc_results)} results after filtering)")

            except RetrievalError as e:
                logger.error(f"WebSocket retrieval error: {e}")
                error_msg = WsErrorMessage(message=f"Retrieval failed: {str(e)}")
                await websocket.send_json(error_msg.model_dump())
            except Exception as e:
                logger.error(f"WebSocket unexpected error: {e}")
                error_msg = WsErrorMessage(message="An unexpected error occurred")
                await websocket.send_json(error_msg.model_dump())

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            error_msg = WsErrorMessage(message="Connection error")
            await websocket.send_json(error_msg.model_dump())
        except Exception:
            pass


def _extract_text_from_file(filename: str, content_bytes: bytes) -> str:
    """Extract text from various file formats."""
    filename_lower = filename.lower()

    if filename_lower.endswith(".txt"):
        return content_bytes.decode("utf-8", errors="ignore")
    elif filename_lower.endswith(".md"):
        return content_bytes.decode("utf-8", errors="ignore")
    elif filename_lower.endswith(".pdf"):
        if not with_pdf_support:
            raise ValueError(
                "PDF support not available. Install pypdf: pip install pypdf"
            )
        try:
            pdf_file = io.BytesIO(content_bytes)
            reader = pypdf.PdfReader(pdf_file)
            text_parts = []
            for page in reader.pages:
                text_parts.append(page.extract_text())
            return "\n".join(text_parts)
        except Exception as e:
            raise ValueError(f"Failed to extract PDF text: {str(e)}")
    else:
        raise ValueError(
            f"Unsupported file format: {filename}. Supported: .txt, .md, .pdf"
        )


@app.post(
    "/documents",
    response_model=DocumentIngestionResponse,
    tags=["Documents"],
    summary="Add custom documents",
)
async def add_documents(request: DocumentIngestionRequest) -> DocumentIngestionResponse:
    """Add custom documents to the retrieval system.

    Supports three types of document sources:
    - text: Raw text content (paste directly)
    - url: URL to fetch content from
    - file: Base64-encoded file (txt, md, pdf)

    Args:
        request: DocumentIngestionRequest with source type, content, and optional label.

    Returns:
        DocumentIngestionResponse with status and document/chunk counts.

    Raises:
        HTTPException: 400 on validation error, 503 if retriever not initialized, 500 on failure.
    """
    if _retriever is None or _config is None:
        logger.error("Retriever not initialized")
        raise HTTPException(
            status_code=503,
            detail="Retriever service not initialized. Try again later.",
        )

    try:
        text_content = ""
        source_label = request.source_label or request.source_type

        if request.source_type == "text":
            text_content = request.content
            logger.info(f"Ingesting text document: {source_label}")

        elif request.source_type == "url":
            logger.info(f"Fetching content from URL: {request.content}")
            try:
                response = requests.get(request.content, timeout=10)
                response.raise_for_status()
                text_content = response.text
                source_label = request.source_label or request.content
            except requests.RequestException as e:
                logger.error(f"Failed to fetch URL: {e}")
                raise HTTPException(
                    status_code=400, detail=f"Failed to fetch URL: {str(e)}"
                )

        elif request.source_type == "file":
            # Decode base64
            try:
                file_bytes = base64.b64decode(request.content)
            except Exception as e:
                logger.error(f"Failed to decode base64: {e}")
                raise HTTPException(
                    status_code=400, detail="Invalid base64 encoding"
                )

            if not request.filename:
                raise HTTPException(
                    status_code=400, detail="filename required for file uploads"
                )

            # Extract text from file
            try:
                text_content = _extract_text_from_file(request.filename, file_bytes)
                logger.info(f"Extracted text from file: {request.filename}")
            except ValueError as e:
                logger.error(f"Failed to extract file content: {e}")
                raise HTTPException(status_code=400, detail=str(e))

        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported source_type: {request.source_type}",
            )

        # Chunk the text content
        chunks = chunk_text(text_content, chunk_size=500, chunk_overlap=50)
        if not chunks:
            raise HTTPException(
                status_code=400, detail="No content to chunk from source"
            )

        logger.info(f"Created {len(chunks)} chunks from source: {source_label}")

        # Add chunks to vector database collection
        try:
            # Use the collection from the global retriever
            collection = _retriever._collection if hasattr(_retriever, "_collection") else _retriever.collection
            if not collection:
                raise HTTPException(
                    status_code=500, detail="Vector database collection not accessible"
                )

            # Prepare documents for ChromaDB
            doc_ids = [f"{source_label}_{i}" for i in range(len(chunks))]
            metadatas = [
                {"source": source_label, "chunk_index": i} for i in range(len(chunks))
            ]

            # Add to collection
            collection.add(
                ids=doc_ids,
                documents=chunks,
                metadatas=metadatas,
            )
            logger.info(
                f"Added {len(chunks)} chunks to collection from source: {source_label}"
            )

            return DocumentIngestionResponse(
                status="success",
                documents_added=1,
                chunks_created=len(chunks),
                message=f"Successfully ingested {len(chunks)} chunks from {source_label}",
            )

        except Exception as e:
            logger.error(f"Failed to add documents to collection: {e}")
            raise HTTPException(
                status_code=500, detail=f"Failed to add documents: {str(e)}"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error during document ingestion: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Document ingestion failed: {str(e)}",
        )


@app.get(
    "/documents/sources",
    response_model=SourcesResponse,
    tags=["Documents"],
    summary="List document sources",
)
async def get_document_sources() -> SourcesResponse:
    """Get list of all document sources in the retrieval system.

    Returns:
        SourcesResponse with list of sources and chunk counts.

    Raises:
        HTTPException: 503 if retriever not initialized, 500 on failure.
    """
    if _retriever is None:
        logger.error("Retriever not initialized")
        raise HTTPException(
            status_code=503,
            detail="Retriever service not initialized. Try again later.",
        )

    try:
        collection = _retriever._collection if hasattr(_retriever, "_collection") else _retriever.collection
        if not collection:
            raise HTTPException(
                status_code=500, detail="Vector database collection not accessible"
            )

        # Get all documents and count by source
        all_docs = collection.get()
        source_counts: dict[str, int] = {}

        if all_docs and all_docs["metadatas"]:
            for metadata in all_docs["metadatas"]:
                source = metadata.get("source", "unknown")
                source_counts[source] = source_counts.get(source, 0) + 1

        sources = [
            DocumentSource(source=src, count=count)
            for src, count in sorted(source_counts.items())
        ]

        logger.info(f"Retrieved {len(sources)} document sources")
        return SourcesResponse(sources=sources)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to retrieve document sources: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve sources: {str(e)}",
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
        "websocket": "/ws/chat",
    }


if __name__ == "__main__":
    import uvicorn

    logger.info("🚀 Starting Hybrid RAG Retriever API...")
    logger.info("📖 Swagger UI: http://localhost:8000/docs")
    logger.info("📋 ReDoc: http://localhost:8000/redoc")
    logger.info("🔧 Health Check: http://localhost:8000/health")
    logger.info("💬 WebSocket Chat: ws://localhost:8000/ws/chat")

    uvicorn.run(app, host="0.0.0.0", port=8000)
