"""Document ingestion and source management endpoints.

Routes:
    POST /documents          -- Ingest a document (text, URL, or file).
    GET  /documents/sources  -- List all ingested document sources.
    GET  /collections        -- List all ChromaDB collections.
"""

import base64
import hashlib
import io
import ipaddress
import socket
from typing import Optional
from urllib.parse import urlparse, urlunparse

import api  # shared state — accessed inside function bodies; api.requests + api.chromadb used
# to ensure monkeypatch("api.requests.get") and monkeypatch(api.chromadb, "PersistentClient")
# intercept calls in tests.
from api_models import (
    CollectionInfo,
    CollectionsResponse,
    DocumentIngestionRequest,
    DocumentIngestionResponse,
    DocumentSource,
    SourcesResponse,
)
from fastapi import APIRouter, HTTPException
from hybrid_rag import (
    KNOWLEDGE_DB_DIRECTORY,
    VectorDBError,
    chunk_document,
)

# All log calls use ``api.logger`` directly so that tests which patch
# ``api.logger`` (e.g. ``with patch("api.logger") as mock_logger:``)
# continue to intercept log output without modification.  Accessing the
# attribute at call time (not import time) ensures the mock is captured.


router = APIRouter()

with_pdf_support = True
try:
    import pypdf
except ImportError:
    with_pdf_support = False


def _validate_url_for_ssrf(url: str) -> str:
    """Validate a user-supplied URL for SSRF and return a safe reconstructed URL.

    Checks the URL scheme, netloc, and resolves the hostname to reject private,
    loopback, link-local, and reserved IP addresses (RFC 1918 / 4193 / 3927 /
    cloud-metadata range 169.254.0.0/16).

    Returns a URL reconstructed from the individual parsed components rather than
    the raw user-supplied string, so that downstream code (and static analysis
    tools) can trace the request URL back to server-validated data rather than
    direct user input.

    Note: A DNS rebinding (TOCTOU) race is theoretically possible between this
    check and the actual TCP connection.  For complete protection deploy a
    network-level egress firewall in addition to this check.

    Args:
        url: The URL string provided by the user.

    Returns:
        A safe URL string reconstructed from the validated parsed components.

    Raises:
        HTTPException: 400 if scheme/host is invalid or IP is private/reserved.
        HTTPException: 502 if DNS resolution fails.
    """
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise HTTPException(
            status_code=400,
            detail="Only HTTP/HTTPS URLs are supported for document ingestion.",
        )
    if not parsed.netloc:
        raise HTTPException(
            status_code=400,
            detail="Invalid URL: missing hostname.",
        )

    hostname = parsed.hostname or ""
    try:
        resolved_ip = socket.gethostbyname(hostname)
    except socket.gaierror as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to resolve hostname '{hostname}': {exc}",
        )

    try:
        addr = ipaddress.ip_address(resolved_ip)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid resolved IP address: {resolved_ip}",
        )

    if (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Requests to private, loopback, link-local, reserved, or multicast "
                "IP addresses are not permitted."
            ),
        )

    # Reconstruct the URL from the individually validated components so that
    # the value passed to requests.get() is derived from parsed/server-validated
    # data, not the raw user string.  urlunparse is a no-op if the components
    # are unchanged, but the data-flow path is now sanitized.
    safe_url = urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        parsed.query,
        "",  # strip fragment — not sent to server
    ))
    return safe_url


def _extract_text_from_file(filename: str, content_bytes: bytes) -> str:
    """Extract plain text from a supported file format.

    Supported formats: ``.txt``, ``.md``, ``.pdf`` (requires ``pypdf``).

    Args:
        filename: Original filename used to detect the format by extension.
        content_bytes: Raw file bytes to parse.

    Returns:
        Extracted plain-text string.

    Raises:
        ValueError: If the file format is unsupported or PDF parsing fails.
    """
    filename_lower = filename.lower()

    if filename_lower.endswith(".txt") or filename_lower.endswith(".md"):
        return content_bytes.decode("utf-8", errors="ignore")

    if filename_lower.endswith(".pdf"):
        if not with_pdf_support:
            raise ValueError(
                "PDF support not available. Install pypdf: pip install pypdf"
            )
        try:
            pdf_file = io.BytesIO(content_bytes)
            reader = pypdf.PdfReader(pdf_file)
            text_parts = [page.extract_text() or "" for page in reader.pages]
            return "\n".join(text_parts)
        except Exception as exc:
            raise ValueError(f"Failed to extract PDF text: {str(exc)}")

    raise ValueError(
        f"Unsupported file format: {filename}. Supported: .txt, .md, .pdf"
    )


@router.post(
    "/documents",
    response_model=DocumentIngestionResponse,
    tags=["Documents"],
    summary="Add custom documents",
)
async def add_documents(
    request: DocumentIngestionRequest,
) -> DocumentIngestionResponse:
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
        HTTPException: 400 on validation error, 503 if retriever not initialized,
            500 on failure.
    """
    if api._retriever is None or api._config is None:
        api.logger.error("Retriever not initialized")
        raise HTTPException(
            status_code=503,
            detail="Retriever service not initialized. Try again later.",
        )

    try:
        text_content = ""
        source_label: Optional[str] = request.source_label

        api.logger.info(
            "Ingest type: %s; cache %s",
            request.ingest_type,
            "will be cleared" if request.ingest_type == "update" else "will be preserved",
        )

        if request.source_type == "text":
            text_content = request.content
            if not source_label:
                content_hash = hashlib.sha256(request.content.encode()).hexdigest()[:12]
                source_label = f"text_{content_hash}"
            api.logger.info("Ingesting text document: %s", source_label)

        elif request.source_type == "url":
            # SSRF guard: validate scheme, netloc, and resolved IP; returns a
            # URL reconstructed from validated components (not raw user input).
            safe_url = _validate_url_for_ssrf(request.content)

            api.logger.info("Fetching content from URL: %s", safe_url)
            try:
                headers = {
                    "User-Agent": "HybridRAG/1.0 document-ingestion",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.5",
                }
                response = api.requests.get(
                    safe_url, headers=headers, timeout=15, allow_redirects=False
                )
                response.raise_for_status()
            except api.requests.RequestException as exc:
                api.logger.error("Failed to fetch URL: %s", exc)
                raise HTTPException(
                    status_code=502, detail=f"Failed to fetch URL: {str(exc)}"
                )

            text_content = response.text
            source_label = request.source_label or request.content

        elif request.source_type == "file":
            try:
                file_bytes = base64.b64decode(request.content)
            except Exception as exc:
                api.logger.error("Failed to decode base64: %s", exc)
                raise HTTPException(status_code=400, detail="Invalid base64 encoding")

            if not request.filename:
                raise HTTPException(
                    status_code=400, detail="filename required for file uploads"
                )

            source_label = request.source_label or request.filename

            try:
                text_content = _extract_text_from_file(request.filename, file_bytes)
                api.logger.info("Extracted text from file: %s", request.filename)
            except ValueError as exc:
                api.logger.error("Failed to extract file content: %s", exc)
                raise HTTPException(status_code=400, detail=str(exc))

        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported source_type: {request.source_type}",
            )

        # Note A1: chunk_size=400 aligns with ADR-0001 T1 — reduced from 500 to
        # 400 characters to improve retrieval precision and provide more headroom
        # under BAAI/bge-small-en-v1.5's 512-token max sequence length
        # (ADR-0001 EMB-006), avoiding the observed risk of silent tail truncation.
        _source_hint = request.content if request.source_type == "url" else (
            request.filename or ""
        )
        chunk_dicts = chunk_document(
            text_content, source_hint=_source_hint, chunk_size=400, chunk_overlap=50
        )
        if not chunk_dicts:
            api.logger.error("No content to chunk from source: %s", source_label)
            if request.source_type == "url":
                detail = (
                    f"No readable text could be extracted from {source_label}. "
                    "The page may require JavaScript, a login, or bot verification."
                )
            else:
                detail = f"No content to chunk from source: {source_label}"
            raise HTTPException(status_code=400, detail=detail)
        chunks = [cd["text"] for cd in chunk_dicts]

        api.logger.info("Created %d chunks from source: %s", len(chunks), source_label)

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
            url_meta: dict = {"source_url": source_url} if source_url else {}
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

            api.logger.info(
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
                    api.logger.info(
                        "Deleted %d stale chunks for source=%s",
                        len(old_ids_by_label),
                        source_label,
                    )
                if matched_by_url and source_url:
                    old_ids_by_url = collection.get(
                        where={"source_url": source_url}, include=[]
                    )["ids"]
                    remaining = [
                        id_
                        for id_ in old_ids_by_url
                        if id_ not in set(old_ids_by_label)
                    ]
                    if remaining:
                        collection.delete(ids=remaining)
                        api.logger.info(
                            "Deleted %d stale chunks for source_url=%s (label changed)",
                            len(remaining),
                            source_url,
                        )

            collection.add(ids=doc_ids, documents=chunks, metadatas=metadatas)
            api.logger.info(
                "Added %d chunks to collection from source: %s",
                len(chunks),
                source_label,
            )

            if effective_ingest_type == "update":
                prev_version = api._corpus_version
                api._cache_generation += 1
                api._corpus_version = api._build_corpus_version_token()
                api.logger.info(
                    "cache.invalidation event=ingest_update prev_version=%s new_version=%s",
                    prev_version,
                    api._corpus_version,
                )
                if api._cache is not None:
                    try:
                        api.lazy_cache.clear()
                        api.logger.info("Ingest complete (type='update'); cache cleared")
                    except Exception as exc:
                        api.logger.warning("Failed to clear cache after ingest: %s", exc)
                else:
                    api.logger.debug("Ingest complete (type='update'); cache not initialized")
            else:
                prev_version = api._corpus_version
                api._corpus_version = api._build_corpus_version_token()
                api.logger.info(
                    "cache.invalidation event=ingest_add prev_version=%s new_version=%s",
                    prev_version,
                    api._corpus_version,
                )
                api.logger.info("Ingest complete (type='add'); cache preserved")

            return DocumentIngestionResponse(
                status="success",
                documents_added=1,
                chunks_created=len(chunks),
                message=f"Successfully ingested {len(chunks)} chunks from {source_label}",
            )

        except Exception as exc:
            api.logger.error("Failed to add documents to collection: %s", exc)
            raise HTTPException(
                status_code=500, detail=f"Failed to add documents: {str(exc)}"
            )

    except HTTPException:
        raise
    except Exception as exc:
        api.logger.error("Unexpected error during document ingestion: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Document ingestion failed: {str(exc)}",
        )


@router.get(
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
    if api._retriever is None:
        api.logger.error("Retriever not initialized")
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

        api.logger.info("Retrieved %d document sources", len(sources))
        return SourcesResponse(sources=sources)

    except HTTPException:
        raise
    except Exception as exc:
        api.logger.error("Failed to retrieve document sources: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve sources: {str(exc)}",
        )


@router.get(
    "/collections",
    response_model=CollectionsResponse,
    tags=["Documents"],
    summary="List ChromaDB collections",
)
async def get_collections() -> CollectionsResponse:
    """Get list of all ChromaDB collections in the vector database.

    Returns:
        CollectionsResponse with list of collections and their document counts.

    Raises:
        HTTPException: 503 if retriever not initialized, 500 on failure.
    """
    if api._retriever is None:
        api.logger.error("Retriever not initialized")
        raise HTTPException(
            status_code=503,
            detail="Retriever service not initialized. Try again later.",
        )

    if api._retriever.collection is None:
        raise HTTPException(
            status_code=500,
            detail="Vector database collection not initialized.",
        )

    try:
        client = api.chromadb.PersistentClient(path=KNOWLEDGE_DB_DIRECTORY)
        all_collections = client.list_collections()
        active_name = api._retriever.collection.name

        collections: list[CollectionInfo] = []
        for chroma_collection in all_collections:
            name = chroma_collection.name
            if name == active_name:
                count = api._retriever.collection.count()
            else:
                count = client.get_collection(name).count()
            collections.append(CollectionInfo(name=name, count=count))

        api.logger.info("Retrieved %d collections", len(collections))
        return CollectionsResponse(collections=collections)

    except VectorDBError as exc:
        api.logger.error("Failed to list collections: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list collections: {str(exc)}",
        )
    except HTTPException:
        raise
    except Exception as exc:
        api.logger.error("Failed to retrieve collections: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve collections: {str(exc)}",
        )
