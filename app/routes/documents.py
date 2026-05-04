"""Document ingestion and sources endpoints."""

import base64
import hashlib
import io
import logging
from urllib.parse import urlparse

import api
import requests
from api import (
    DocumentIngestionRequest,
    DocumentIngestionResponse,
    DocumentResult,
    DocumentSource,
    SourcesResponse,
)
from fastapi import APIRouter, HTTPException
from hybrid_rag import (
    KNOWLEDGE_DB_DIRECTORY,
    chunk_document,
)

logger = logging.getLogger(__name__)

with_pdf_support = True
try:
    import pypdf
except ImportError:
    with_pdf_support = False

router = APIRouter()


def _extract_text_from_file(filename: str, content_bytes: bytes) -> str:
    """Extract text from various file formats."""
    filename_lower = filename.lower()

    if filename_lower.endswith(".txt") or filename_lower.endswith(".md"):
        return content_bytes.decode("utf-8", errors="ignore")
    elif filename_lower.endswith(".pdf"):
        if not with_pdf_support:
            raise ValueError(
                "PDF support not available. Install pypdf: pip install pypdf"
            )
        try:
            pdf_file = io.BytesIO(content_bytes)
            reader = pypdf.PdfReader(pdf_file)
            return "\n".join(page.extract_text() for page in reader.pages)
        except Exception as e:
            raise ValueError(f"Failed to extract PDF text: {str(e)}")
    else:
        raise ValueError(
            f"Unsupported file format: {filename}. Supported: .txt, .md, .pdf"
        )


@router.post(
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
    """
    if api._retriever is None or api._config is None:
        logger.error("Retriever not initialized")
        raise HTTPException(
            status_code=503,
            detail="Retriever service not initialized. Try again later.",
        )

    try:
        text_content = ""
        source_label = request.source_label

        logger.info(
            "Ingest type: %s; cache %s",
            request.ingest_type,
            "will be cleared" if request.ingest_type == "update" else "will be preserved",
        )

        if request.source_type == "text":
            text_content = request.content
            if not source_label:
                content_hash = hashlib.sha256(request.content.encode()).hexdigest()[:12]
                source_label = f"text_{content_hash}"
            logger.info("Ingesting text document: %s", source_label)

        elif request.source_type == "url":
            logger.info("Fetching content from URL: %s", request.content)
            try:
                headers = {
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.5",
                }
                response = requests.get(request.content, headers=headers, timeout=15)
                response.raise_for_status()
            except requests.RequestException as e:
                logger.error("Failed to fetch URL: %s", e)
                raise HTTPException(
                    status_code=502, detail=f"Failed to fetch URL: {str(e)}"
                )

            text_content = response.text
            source_label = request.source_label or request.content

        elif request.source_type == "file":
            try:
                file_bytes = base64.b64decode(request.content)
            except Exception as e:
                logger.error("Failed to decode base64: %s", e)
                raise HTTPException(status_code=400, detail="Invalid base64 encoding")

            if not request.filename:
                raise HTTPException(
                    status_code=400, detail="filename required for file uploads"
                )

            source_label = request.source_label or request.filename

            try:
                text_content = _extract_text_from_file(request.filename, file_bytes)
                logger.info("Extracted text from file: %s", request.filename)
            except ValueError as e:
                logger.error("Failed to extract file content: %s", e)
                raise HTTPException(status_code=400, detail=str(e))

        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported source_type: {request.source_type}",
            )

        # Note A1: chunk_size=400 aligns with ADR-0001 T1
        _source_hint = request.content if request.source_type == "url" else (request.filename or "")
        chunk_dicts = chunk_document(
            text_content, source_hint=_source_hint, chunk_size=400, chunk_overlap=50
        )
        if not chunk_dicts:
            logger.error("No content to chunk from source: %s", source_label)
            if request.source_type == "url":
                detail = (
                    f"No readable text could be extracted from {source_label}. "
                    "The page may require JavaScript, a login, or bot verification."
                )
            else:
                detail = f"No content to chunk from source: {source_label}"
            raise HTTPException(status_code=400, detail=detail)
        chunks = [cd["text"] for cd in chunk_dicts]

        logger.info("Created %d chunks from source: %s", len(chunks), source_label)

        try:
            collection = (
                api._retriever._collection
                if hasattr(api._retriever, "_collection")
                else api._retriever.collection
            )
            if not collection:
                raise HTTPException(
                    status_code=500, detail="Vector database collection not accessible"
                )

            doc_ids = [f"{source_label}_{i}" for i in range(len(chunks))]
            parsed = urlparse(request.content)
            is_http_url = parsed.scheme in ("http", "https") and bool(parsed.netloc)
            source_url = request.content if is_http_url else None
            url_meta: dict[str, str] = {"source_url": source_url} if source_url else {}
            metadatas = [
                {
                    "source": source_label,
                    "chunk_index": i,
                    **url_meta,
                    **{
                        k: v
                        for k, v in chunk_dicts[i]["metadata"].items()
                        if k in ("section_h1", "section_h2") and v is not None
                    },
                }
                for i in range(len(chunks))
            ]

            if "ingest_type" in request.model_fields_set:
                effective_ingest_type = request.ingest_type
                source_is_new = effective_ingest_type == "add"
                matched_by_url = False
            else:
                existing_by_label = collection.get(
                    where={"source": source_label}, limit=1, include=[]
                )
                matched_by_url = False
                if not existing_by_label["ids"] and source_url:
                    existing_by_url = collection.get(
                        where={"source_url": source_url}, limit=1, include=[]
                    )
                    matched_by_url = bool(existing_by_url["ids"])

                source_is_new = not existing_by_label["ids"] and not matched_by_url
                effective_ingest_type = "add" if source_is_new else "update"

            logger.info(
                "Ingest source_is_new=%s effective_ingest_type=%s source=%s",
                source_is_new,
                effective_ingest_type,
                source_label,
            )

            if effective_ingest_type == "update":
                old_ids_by_label = collection.get(
                    where={"source": source_label}, include=[]
                )["ids"]
                if old_ids_by_label:
                    collection.delete(ids=old_ids_by_label)
                    logger.info(
                        "Deleted %d stale chunks for source=%s",
                        len(old_ids_by_label),
                        source_label,
                    )
                if matched_by_url and source_url:
                    old_ids_by_url = collection.get(
                        where={"source_url": source_url}, include=[]
                    )["ids"]
                    remaining = [
                        id_ for id_ in old_ids_by_url if id_ not in set(old_ids_by_label)
                    ]
                    if remaining:
                        collection.delete(ids=remaining)
                        logger.info(
                            "Deleted %d stale chunks for source_url=%s (label changed)",
                            len(remaining),
                            source_url,
                        )

            collection.add(ids=doc_ids, documents=chunks, metadatas=metadatas)
            logger.info("Added %d chunks to collection from source: %s", len(chunks), source_label)

            if effective_ingest_type == "update":
                prev_version = api._corpus_version
                api._cache_generation += 1
                api._corpus_version = api._build_corpus_version_token()
                logger.info(
                    "cache.invalidation event=ingest_update prev_version=%s new_version=%s",
                    prev_version,
                    api._corpus_version,
                )
                if api._cache is not None:
                    try:
                        api.lazy_cache.clear()
                        logger.info("Ingest complete (type='update'); cache cleared")
                    except Exception as e:
                        logger.warning("Failed to clear cache after ingest: %s", e)
                else:
                    logger.debug("Ingest complete (type='update'); cache not initialized")
            else:
                prev_version = api._corpus_version
                api._corpus_version = api._build_corpus_version_token()
                logger.info(
                    "cache.invalidation event=ingest_add prev_version=%s new_version=%s",
                    prev_version,
                    api._corpus_version,
                )
                logger.info("Ingest complete (type='add'); cache preserved")

            return DocumentIngestionResponse(
                status="success",
                documents_added=1,
                chunks_created=len(chunks),
                message=f"Successfully ingested {len(chunks)} chunks from {source_label}",
            )

        except Exception as e:
            logger.error("Failed to add documents to collection: %s", e)
            raise HTTPException(
                status_code=500, detail=f"Failed to add documents: {str(e)}"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Unexpected error during document ingestion: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Document ingestion failed: {str(e)}",
        )


@router.get(
    "/documents/sources",
    response_model=SourcesResponse,
    tags=["Documents"],
    summary="List document sources",
)
async def get_document_sources() -> SourcesResponse:
    """Get list of all document sources in the retrieval system."""
    if api._retriever is None:
        logger.error("Retriever not initialized")
        raise HTTPException(
            status_code=503,
            detail="Retriever service not initialized. Try again later.",
        )

    try:
        collection = (
            api._retriever._collection
            if hasattr(api._retriever, "_collection")
            else api._retriever.collection
        )
        if not collection:
            raise HTTPException(
                status_code=500, detail="Vector database collection not accessible"
            )

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

        logger.info("Retrieved %d document sources", len(sources))
        return SourcesResponse(sources=sources)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to retrieve document sources: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve sources: {str(e)}",
        )
