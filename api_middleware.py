"""ASGI middleware for query result caching in Hybrid RAG API.

This module provides the QueryCacheMiddleware for caching POST /retrieve responses
at the API layer (L1 cache), improving performance for repeated queries.

The middleware implements:
- ASGI body replay pattern for reading request bodies without stream corruption
- Stable cache key generation from request body (SHA-256 with enable_rerank)
- Cache HIT/MISS/ERROR status tracking via X-Cache response header
- Fail-open error handling: cache failures never crash the API
- Configurable excluded paths for endpoints that should not be cached

Example:
    >>> from fastapi import FastAPI
    >>> from hybrid_rag.config import CacheSettings, create_cache_backend
    >>> from api_middleware import QueryCacheMiddleware
    >>>
    >>> settings = CacheSettings(backend="memory", ttl_seconds=3600)
    >>> cache = create_cache_backend(settings)
    >>>
    >>> app = FastAPI()
    >>> app.add_middleware(
    ...     QueryCacheMiddleware,
    ...     cache_backend=cache,
    ...     excluded_paths=["/health", "/config", "/ingest", "/cache/stats"]
    ... )
    >>>
    >>> # All POST /retrieve requests now cached with X-Cache header
    >>> @app.post("/retrieve")
    >>> async def retrieve(query: str) -> dict:
    ...     return {"results": [...]}
"""

import hashlib
import json
import logging
from typing import Any, Callable, Dict, List, Optional

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from hybrid_rag.cache import CacheBackend

__all__ = ["QueryCacheMiddleware"]

logger = logging.getLogger(__name__)


class QueryCacheMiddleware(BaseHTTPMiddleware):
    """ASGI middleware for caching POST /retrieve responses.

    This middleware intercepts HTTP requests and caches responses for POST /retrieve
    endpoints. It uses a stable cache key generated from the request body and
    implements the ASGI receive() replay pattern to avoid stream corruption.

    The middleware respects the enable_rerank parameter in cache key generation
    (ADR-002), ensuring that requests with different reranking settings are cached
    separately.

    Attributes:
        cache_backend: CacheBackend instance for storing/retrieving cached responses.
        excluded_paths: List of URL paths that should NOT be cached.
            Defaults to ['/health', '/config', '/ingest', '/documents', '/documents/sources', '/cache/stats'].

    Example:
        >>> from hybrid_rag.cache import InMemoryCache
        >>> from api_middleware import QueryCacheMiddleware
        >>>
        >>> cache = InMemoryCache(ttl_seconds=3600, max_size=10000)
        >>> middleware = QueryCacheMiddleware(
        ...     app=app,
        ...     cache_backend=cache,
        ...     excluded_paths=['/health', '/ingest']
        ... )
    """

    def __init__(
        self,
        app: ASGIApp,
        cache_backend: CacheBackend,
        excluded_paths: Optional[List[str]] = None,
    ) -> None:
        """Initialize the QueryCacheMiddleware.

        Args:
            app: The ASGI application to wrap.
            cache_backend: CacheBackend instance for caching responses.
            excluded_paths: List of URL paths to exclude from caching.
                Defaults to ['/health', '/config', '/ingest', '/documents', '/documents/sources', '/cache/stats'].

        Example:
            >>> from hybrid_rag.cache import InMemoryCache
            >>> cache = InMemoryCache()
            >>> middleware = QueryCacheMiddleware(
            ...     app=app,
            ...     cache_backend=cache,
            ...     excluded_paths=['/health', '/metrics']
            ... )
        """
        super().__init__(app)
        self.cache_backend: CacheBackend = cache_backend
        self.excluded_paths: List[str] = excluded_paths or [
            "/health",
            "/config",
            "/ingest",
            "/documents",
            "/documents/sources",
            "/cache/stats",
        ]
        logger.info(
            f"Initialized QueryCacheMiddleware with {len(self.excluded_paths)} "
            f"excluded paths: {', '.join(self.excluded_paths)}"
        )

    def _should_cache_request(self, request: Request) -> bool:
        """Determine if a request should be cached.

        A request is cached if:
        - Method is POST
        - Path is exactly '/retrieve'
        - Content-Type is not multipart/form-data
        - Path is not in excluded_paths

        Args:
            request: The incoming HTTP request.

        Returns:
            True if the request should be cached, False otherwise.
        """
        # Only cache POST requests to /retrieve
        if request.method != "POST" or request.url.path != "/retrieve":
            return False

        # Never process multipart/form-data through cache/body decoding path.
        content_type = request.headers.get("content-type", "").lower()
        if content_type.startswith("multipart/form-data"):
            return False

        # Check if path is excluded
        if request.url.path in self.excluded_paths:
            return False

        return True

    async def _read_request_body(self, request: Request) -> bytes:
        """Read request body and return it (can be called multiple times).

        This implements the ASGI receive() replay pattern to avoid stream corruption.
        The request body is cached in request.scope["_body"] after first read.

        Args:
            request: The incoming HTTP request.

        Returns:
            The request body as bytes.
        """
        # Check if we've already read the body
        if "_body" in request.scope:
            body: bytes = request.scope["_body"]
            return body

        # Read body from request
        body = await request.body()

        # Cache it in scope for future reads
        request.scope["_body"] = body

        return body

    def _generate_cache_key(
        self, body: bytes, enable_rerank: Optional[bool] = None
    ) -> str:
        """Generate a stable cache key from request body and enable_rerank flag.

        The cache key includes the enable_rerank parameter to ensure that
        responses with different reranking settings are cached separately (ADR-002).

        Args:
            body: The request body as bytes.
            enable_rerank: Whether reranking is enabled. If None, treated as part of body.

        Returns:
            SHA-256 hash of the cache key components, prefixed with 'cache:'.
        """
        try:
            decoded_body = body.decode("utf-8")
            body_data: Any = json.loads(decoded_body)

            # Canonicalize JSON so semantically equivalent payloads hash identically.
            canonical_json = json.dumps(
                body_data,
                sort_keys=True,
                separators=(",", ":"),
            )

            if enable_rerank is None:
                if isinstance(body_data, dict):
                    enable_rerank = bool(body_data.get("enable_rerank", False))
                else:
                    enable_rerank = False

            key_data = f"{canonical_json}:{str(enable_rerank)}"
            key_hash = hashlib.sha256(key_data.encode("utf-8")).hexdigest()
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            # Fail-open fallback: hash raw bytes to avoid exceptions on malformed payloads.
            rerank_marker = "none" if enable_rerank is None else str(enable_rerank)
            fallback_data = body + b":" + rerank_marker.encode("utf-8")
            key_hash = hashlib.sha256(fallback_data).hexdigest()

        return f"cache:{key_hash}"

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Any]
    ) -> Response:
        """Process the request with cache middleware logic.

        Implements the core middleware logic:
        1. Check if request should be cached (POST /retrieve)
        2. If yes, read body and check cache for HIT
        3. On HIT, return cached response with X-Cache: HIT
        4. On MISS, call next handler and cache 200 responses with X-Cache: MISS
        5. Non-200 responses returned with X-Cache: ERROR and not cached
        6. All cache errors are caught to implement fail-open principle

        Args:
            request: The incoming HTTP request.
            call_next: The next middleware/handler in the chain.

        Returns:
            HTTP Response with X-Cache header indicating HIT/MISS/ERROR status.
        """
        # Check if this request should be cached
        if not self._should_cache_request(request):
            # Pass through to next handler
            response_passthrough: Response = await call_next(request)
            return response_passthrough

        cache_key: str = ""
        should_check_cache: bool = True

        try:
            # Read request body (using replay pattern)
            body = await self._read_request_body(request)
            # Generate cache key
            cache_key = self._generate_cache_key(body)
        except Exception as error:
            # Any error reading body or generating key: log and proceed without caching
            logger.warning(
                f"Error preparing cache key: {type(error).__name__}: {error}"
            )
            should_check_cache = False

        # Check cache for HIT (if we successfully generated a key)
        if should_check_cache:
            try:
                cached_response = self.cache_backend.get(cache_key)
                if cached_response is not None:
                    logger.debug(
                        f"Cache HIT for {request.method} {request.url.path} "
                        f"(key: {cache_key[:16]}..., size: {len(cached_response)} bytes)"
                    )
                    # Return cached response with HIT header
                    response_obj: Response = Response(
                        content=cached_response,
                        status_code=200,
                        media_type="application/json",
                    )
                    response_obj.headers["X-Cache"] = "HIT"
                    return response_obj
            except Exception as cache_error:
                # Cache get error: log and continue (fail-open)
                logger.warning(
                    f"Cache get failed: {type(cache_error).__name__}: {cache_error}"
                )

            if cache_key:
                logger.debug(
                    f"Cache MISS for {request.method} {request.url.path} "
                    f"(key: {cache_key[:16]}...)"
                )

        # Call the next handler (this will actually process the request)
        response_from_next: Any = await call_next(request)
        response: Response = response_from_next

        # Only cache 200 responses if we have a valid cache key
        if response.status_code == 200 and should_check_cache and cache_key:
            try:
                # Extract response body using multiple strategies
                response_body: bytes = await self._extract_response_body(response)

                # Cache the response if we have content
                if response_body:
                    try:
                        self.cache_backend.set(cache_key, response_body)
                        logger.debug(
                            f"Cached response for {request.method} {request.url.path} "
                            f"(key: {cache_key[:16]}..., size: {len(response_body)} bytes)"
                        )
                    except Exception as cache_error:
                        # Cache set error: log and continue (fail-open)
                        logger.warning(
                            f"Cache set failed: {type(cache_error).__name__}: {cache_error}"
                        )

                    # Return response with MISS header
                    final_response: Response = Response(
                        content=response_body,
                        status_code=response.status_code,
                        media_type=response.media_type,
                    )
                    # Copy headers from original response
                    for key, value in response.headers.items():
                        if key.lower() not in ("content-length", "content-encoding"):
                            final_response.headers[key] = value
                    final_response.headers["X-Cache"] = "MISS"
                    return final_response

            except Exception as error:
                logger.warning(
                    f"Error handling response cache: {type(error).__name__}: {error}"
                )

        # Add X-Cache header for non-200 or other errors
        if response.status_code != 200:
            response.headers["X-Cache"] = "ERROR"
            logger.debug(
                f"Not caching non-200 response: {response.status_code} "
                f"for {request.method} {request.url.path}"
            )
        else:
            response.headers["X-Cache"] = "MISS"

        return response

    async def _extract_response_body(self, response: Response) -> bytes:
        """Extract response body from various Response types.

        Handles JSONResponse, StreamingResponse, and plain Response objects.

        Args:
            response: The response object to extract body from.

        Returns:
            Response body as bytes, or empty bytes if extraction fails.
        """
        response_body: bytes = b""

        # Try various methods to get the response body
        try:
            # Method 1: body() coroutine for Response objects
            if hasattr(response, "body") and callable(response.body):
                response_body = await response.body()
                if response_body:
                    return response_body
        except Exception as e:
            logger.debug(f"body() method failed: {e}")

        try:
            # Method 2: Check for _body attribute (Starlette internal)
            if hasattr(response, "_body"):
                body_attr: Any = response._body
                if isinstance(body_attr, bytes):
                    response_body = body_attr
                    if response_body:
                        return response_body
        except Exception as e:
            logger.debug(f"_body attribute failed: {e}")

        try:
            # Method 3: For JSONResponse, try to access body_iterator
            if hasattr(response, "body_iterator"):
                chunks: List[bytes] = []
                async for chunk in response.body_iterator:
                    if chunk:
                        chunks.append(chunk)
                if chunks:
                    return b"".join(chunks)
        except Exception as e:
            logger.debug(f"body_iterator failed: {e}")

        # Fallback: return empty bytes
        return b""
