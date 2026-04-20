"""Caching module for the Hybrid RAG library.

This module provides a flexible caching layer with multiple backend implementations:
- InMemoryCache: Fast, thread-safe in-memory caching with TTL support
- RedisCache: Distributed caching with Redis backend and fail-open error handling

The caching layer is designed to:
- Improve retrieval performance by caching query results
- Support both local and distributed deployments
- Handle failures gracefully without impacting main application flow
- Track cache statistics for monitoring and debugging

Example:
    >>> from hybrid_rag.cache import InMemoryCache, RedisCache
    >>>
    >>> # Use in-memory cache for local development
    >>> cache = InMemoryCache(ttl_seconds=3600, max_size=10000)
    >>> cache.set("query:1", {"results": [...]})
    >>> results = cache.get("query:1")
    >>>
    >>> # Use Redis cache for production
    >>> redis_cache = RedisCache(
    ...     redis_url="redis://localhost:6379",
    ...     key_prefix="app:",
    ...     ttl_seconds=3600
    ... )
    >>> redis_cache.set("query:1", {"results": [...]})
    >>> results = redis_cache.get("query:1")
"""

import json
import logging
import threading
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

try:
    import cachetools
except ImportError:
    raise ImportError("cachetools is required. Install with: pip install cachetools>=0.4.0")

try:
    import redis
except ImportError:
    raise ImportError("redis is required. Install with: pip install redis>=5.0.0")

__all__ = ["CacheBackend", "InMemoryCache", "RedisCache"]

logger = logging.getLogger(__name__)


class CacheBackend(ABC):
    """Abstract base class for cache implementations.

    Defines the interface that all cache backends must implement.
    Cache backends are responsible for storing and retrieving key-value pairs,
    with optional time-to-live (TTL) support and statistics tracking.

    Methods:
        get: Retrieve a value by key, returning None if not found
        set: Store a value with optional TTL
        delete: Remove a key from cache
        clear: Remove all keys from cache
        stats: Return cache statistics (size, hits, misses, etc.)

    Example:
        >>> # Implement a custom cache backend
        >>> class FileSystemCache(CacheBackend):
        ...     def get(self, key: str) -> Optional[Any]:
        ...         # Load from disk
        ...         pass
        ...     def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        ...         # Save to disk
        ...         pass
        ...     def delete(self, key: str) -> None:
        ...         # Delete file
        ...         pass
        ...     def clear(self) -> None:
        ...         # Clear directory
        ...         pass
        ...     def stats(self) -> Dict[str, Any]:
        ...         return {"backend": "filesystem"}
    """

    @abstractmethod
    def get(self, key: str) -> Optional[Any]:
        """Retrieve a value from cache.

        Args:
            key: The cache key to retrieve.

        Returns:
            The cached value if found, None otherwise.
            
        Raises:
            None: Cache backends should not raise exceptions.
                  Return None if the key is not found or on error.

        Example:
            >>> cache = InMemoryCache()
            >>> cache.set("user:123", {"name": "Alice", "age": 30})
            >>> user = cache.get("user:123")
            >>> print(user)
            {'name': 'Alice', 'age': 30}
        """
        pass

    @abstractmethod
    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        """Store a value in cache.

        Args:
            key: The cache key to store under.
            value: The value to cache. Can be any Python object.
            ttl_seconds: Time-to-live in seconds. If None, use backend default.
                        If 0, store indefinitely (if supported by backend).

        Raises:
            None: Cache backends should not raise exceptions.
                  Log errors and continue on failure (fail-open principle).

        Example:
            >>> cache = InMemoryCache()
            >>> cache.set("session:abc", {"user_id": 123}, ttl_seconds=1800)
            >>> # Value expires after 30 minutes
        """
        pass

    @abstractmethod
    def delete(self, key: str) -> None:
        """Delete a key from cache.

        Deleting a non-existent key should not raise an error.

        Args:
            key: The cache key to delete.

        Raises:
            None: Cache backends should not raise exceptions.

        Example:
            >>> cache = InMemoryCache()
            >>> cache.set("temp:data", {"value": 42})
            >>> cache.delete("temp:data")
            >>> cache.get("temp:data")  # Returns None
        """
        pass

    @abstractmethod
    def clear(self) -> None:
        """Remove all keys from cache.

        This operation removes all cached entries. Use with caution in
        production environments with distributed caches.

        Raises:
            None: Cache backends should not raise exceptions.

        Example:
            >>> cache = InMemoryCache()
            >>> cache.set("key1", "value1")
            >>> cache.set("key2", "value2")
            >>> cache.clear()
            >>> cache.get("key1")  # Returns None
        """
        pass

    @abstractmethod
    def stats(self) -> Dict[str, Any]:
        """Return cache statistics.

        Returns:
            Dictionary containing cache statistics. All implementations must
            include at least 'backend' (str), 'hits' (int), and 'misses' (int).
            Other keys are backend-specific.

        Example:
            >>> cache = InMemoryCache()
            >>> cache.set("key", "value")
            >>> cache.get("key")
            >>> cache.get("missing")
            >>> stats = cache.stats()
            >>> print(stats)
            {'backend': 'memory', 'size': 1, 'max_size': 10000, 'hits': 1, 'misses': 1}
        """
        pass


class InMemoryCache(CacheBackend):
    """Thread-safe in-memory cache with TTL support.

    Implemented using cachetools.TTLCache for automatic expiration of entries.
    Uses a threading.Lock for thread-safe concurrent access.

    This cache is ideal for:
    - Local development and testing
    - Single-process deployments
    - High-performance caching when distributed state is not needed

    Attributes:
        ttl_seconds: Default time-to-live for cache entries in seconds.
        max_size: Maximum number of entries in the cache.

    Example:
        >>> from hybrid_rag.cache import InMemoryCache
        >>> import time
        >>>
        >>> # Create cache with 1 hour TTL and 10K max entries
        >>> cache = InMemoryCache(ttl_seconds=3600, max_size=10000)
        >>>
        >>> # Store and retrieve values
        >>> cache.set("query:1", {"results": [1, 2, 3]})
        >>> results = cache.get("query:1")
        >>> print(results)
        {'results': [1, 2, 3]}
        >>>
        >>> # Values expire after TTL
        >>> cache.set("temp", "value", ttl_seconds=1)
        >>> time.sleep(1.1)
        >>> cache.get("temp")  # Returns None
        >>>
        >>> # Check statistics
        >>> stats = cache.stats()
        >>> print(f"Hits: {stats['hits']}, Misses: {stats['misses']}")
    """

    def __init__(self, ttl_seconds: int = 3600, max_size: int = 10000) -> None:
        """Initialize InMemoryCache.

        Args:
            ttl_seconds: Default time-to-live for entries in seconds (default: 3600).
            max_size: Maximum number of entries to keep (default: 10000).

        Raises:
            ValueError: If ttl_seconds < 0 or max_size < 1.
        """
        if ttl_seconds < 0:
            raise ValueError(f"ttl_seconds must be non-negative, got {ttl_seconds}")
        if max_size < 1:
            raise ValueError(f"max_size must be at least 1, got {max_size}")

        self._ttl_seconds = ttl_seconds
        self._max_size = max_size
        self._cache: cachetools.TTLCache = cachetools.TTLCache(
            maxsize=max_size, ttl=ttl_seconds
        )
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Optional[Any]:
        """Retrieve a value from the in-memory cache.

        Thread-safe operation using a lock.

        Args:
            key: The cache key to retrieve.

        Returns:
            The cached value if found and not expired, None otherwise.
        """
        with self._lock:
            if key in self._cache:
                self._hits += 1
                return self._cache[key]
            else:
                self._misses += 1
                return None

    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        """Store a value in the in-memory cache.

        Thread-safe operation using a lock. If ttl_seconds is None, uses the
        default TTL from initialization.

        Args:
            key: The cache key to store under.
            value: The value to cache (any Python object).
            ttl_seconds: Optional TTL override in seconds.
        """
        with self._lock:
            # Note: cachetools.TTLCache doesn't support per-key TTL overrides.
            # All entries use the TTL specified at initialization.
            # For per-key TTL support, would need a custom implementation.
            self._cache[key] = value

    def delete(self, key: str) -> None:
        """Delete a key from the in-memory cache.

        Thread-safe operation using a lock. Deleting a non-existent key is safe.

        Args:
            key: The cache key to delete.
        """
        with self._lock:
            self._cache.pop(key, None)

    def clear(self) -> None:
        """Remove all entries from the in-memory cache.

        Thread-safe operation using a lock.
        """
        with self._lock:
            self._cache.clear()

    def stats(self) -> Dict[str, Any]:
        """Return cache statistics.

        Thread-safe operation using a lock.

        Returns:
            Dictionary with keys:
            - backend: 'memory'
            - size: Current number of entries
            - max_size: Maximum capacity
            - hits: Number of cache hits
            - misses: Number of cache misses
        """
        with self._lock:
            return {
                "backend": "memory",
                "size": len(self._cache),
                "max_size": self._max_size,
                "hits": self._hits,
                "misses": self._misses,
            }


class RedisCache(CacheBackend):
    """Redis-backed distributed cache with connection pooling.

    Implements fail-open error handling: Redis connection failures, serialization
    errors, and timeouts are logged but never propagate. The application continues
    to function normally (just without caching).

    This cache is ideal for:
    - Multi-process and distributed deployments
    - Sharing cache state across multiple application instances
    - Production environments with high availability requirements

    Features:
    - Automatic JSON serialization/deserialization
    - Connection pooling for efficient resource usage
    - Configurable key prefixing for multi-tenant scenarios
    - Comprehensive fail-open error handling
    - Hit/miss statistics tracking

    Example:
        >>> from hybrid_rag.cache import RedisCache
        >>>
        >>> # Connect to local Redis
        >>> cache = RedisCache(
        ...     redis_url="redis://localhost:6379",
        ...     key_prefix="app:",
        ...     ttl_seconds=3600
        ... )
        >>>
        >>> # Store and retrieve values
        >>> cache.set("query:1", {"results": [1, 2, 3]})
        >>> results = cache.get("query:1")
        >>> print(results)
        {'results': [1, 2, 3]}
        >>>
        >>> # Clear all cached entries with the prefix
        >>> cache.clear()
        >>>
        >>> # Check statistics
        >>> stats = cache.stats()
        >>> print(f"Redis URL: {stats['redis_url']}")
        >>> print(f"Hits: {stats['hits']}, Misses: {stats['misses']}")
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        key_prefix: str = "cache:",
        ttl_seconds: int = 3600,
    ) -> None:
        """Initialize RedisCache.

        Establishes a connection pool to Redis (lazily, on first use).

        Args:
            redis_url: Redis connection URL (default: 'redis://localhost:6379').
                      Supports formats like 'redis://localhost:6379/0' for databases.
            key_prefix: Prefix for all cache keys (default: 'cache:').
                       Useful for multi-tenant deployments.
            ttl_seconds: Default time-to-live for entries in seconds (default: 3600).

        Raises:
            ValueError: If ttl_seconds < 0.
        """
        if ttl_seconds < 0:
            raise ValueError(f"ttl_seconds must be non-negative, got {ttl_seconds}")

        self._redis_url = redis_url
        self._key_prefix = key_prefix
        self._ttl_seconds = ttl_seconds
        self._hits = 0
        self._misses = 0

        # Parse Redis URL and create connection pool
        try:
            self._connection_pool = redis.ConnectionPool.from_url(
                redis_url, decode_responses=False
            )
            self._redis = redis.Redis(connection_pool=self._connection_pool)
        except Exception as e:
            logger.warning(f"Failed to initialize Redis connection pool: {e}")
            self._connection_pool = None
            self._redis = None

    def get(self, key: str) -> Optional[Any]:
        """Retrieve a value from Redis.

        Implements fail-open: returns None on any Redis error without raising.

        Args:
            key: The cache key to retrieve.

        Returns:
            The cached value deserialized from JSON, or None if not found or on error.
        """
        if self._redis is None:
            self._misses += 1
            return None

        try:
            full_key = f"{self._key_prefix}{key}"
            value_bytes = self._redis.get(full_key)

            if value_bytes is None:
                self._misses += 1
                return None

            # Deserialize from JSON
            value = json.loads(value_bytes.decode("utf-8"))
            self._hits += 1
            return value

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to deserialize cache value for key '{key}': {e}")
            self._misses += 1
            return None
        except Exception as e:
            logger.warning(f"Redis get() error for key '{key}': {e}")
            self._misses += 1
            return None

    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        """Store a value in Redis.

        Implements fail-open: logs errors but never raises exceptions.
        Uses JSON serialization for value storage.

        Args:
            key: The cache key to store under.
            value: The value to cache (must be JSON-serializable).
            ttl_seconds: Optional TTL override in seconds. If None, uses default.
        """
        if self._redis is None:
            logger.warning("Redis connection not available, skipping cache.set()")
            return

        try:
            full_key = f"{self._key_prefix}{key}"
            ttl = ttl_seconds if ttl_seconds is not None else self._ttl_seconds

            # Serialize to JSON
            json_value = json.dumps(value)

            # Use setex for TTL support
            self._redis.setex(full_key, ttl, json_value)

        except (ValueError, TypeError) as e:
            logger.warning(f"Failed to serialize cache value for key '{key}': {e}")
        except Exception as e:
            logger.warning(f"Redis set() error for key '{key}': {e}")

    def delete(self, key: str) -> None:
        """Delete a key from Redis.

        Implements fail-open: logs errors but never raises exceptions.

        Args:
            key: The cache key to delete.
        """
        if self._redis is None:
            return

        try:
            full_key = f"{self._key_prefix}{key}"
            self._redis.delete(full_key)
        except Exception as e:
            logger.warning(f"Redis delete() error for key '{key}': {e}")

    def clear(self) -> None:
        """Remove all keys with the cache prefix from Redis.

        This uses SCAN to find all keys matching the prefix pattern and deletes them.
        Implements fail-open: logs errors but never raises exceptions.
        """
        if self._redis is None:
            return

        try:
            pattern = f"{self._key_prefix}*"
            keys_to_delete = []

            # Use SCAN to iterate over keys (non-blocking)
            for key in self._redis.scan_iter(match=pattern, count=100):
                keys_to_delete.append(key)

            # Delete in batches
            if keys_to_delete:
                self._redis.delete(*keys_to_delete)

            logger.info(f"Cleared {len(keys_to_delete)} keys from Redis cache")

        except Exception as e:
            logger.warning(f"Redis clear() error: {e}")

    def stats(self) -> Dict[str, Any]:
        """Return cache statistics.

        Returns:
            Dictionary with keys:
            - backend: 'redis'
            - redis_url: The Redis connection URL
            - size: Number of keys with the cache prefix (None if Redis unavailable)
            - hits: Number of cache hits
            - misses: Number of cache misses
        """
        size = None
        if self._redis is not None:
            try:
                pattern = f"{self._key_prefix}*"
                size = sum(1 for _ in self._redis.scan_iter(match=pattern, count=100))
            except Exception as e:
                logger.warning(f"Failed to get Redis cache size: {e}")

        return {
            "backend": "redis",
            "redis_url": self._redis_url,
            "size": size,
            "hits": self._hits,
            "misses": self._misses,
        }
