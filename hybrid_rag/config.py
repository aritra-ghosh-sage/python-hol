"""Configuration classes and models for hybrid retrieval."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Literal, Optional
from urllib.parse import urlparse

if TYPE_CHECKING:
    from .cache import CacheBackend

from .constants import DEFAULT_EMBEDDING_MODEL_PATH, DEFAULT_RERANKER_MODEL_PATH

__all__ = [
    "HybridRetrieverConfig",
    "DEFAULT_CONFIG",
    "CacheSettings",
    "create_cache_backend",
]


@dataclass
class HybridRetrieverConfig:
    """Configuration parameters for hybrid retrieval combining semantic and keyword search.

    This configuration controls the behavior of the hybrid retrieval pipeline including
    semantic search, keyword search, score fusion, and optional reranking.

    Attributes:
        semantic_top_k: Number of results to retrieve from semantic search. Defaults to 10.
        keyword_top_k: Number of results to retrieve from keyword search. Defaults to 10.
        final_top_k: Maximum number of final deduplicated results to return. Defaults to 5.
        semantic_weight: Weight factor for semantic search scores in fusion (0-1). Defaults to 0.65.
        keyword_weight: Weight factor for keyword search scores in fusion (0-1). Defaults to 0.35.
        enable_rerank: Whether to apply cross-encoder reranking for better ranking. Defaults to True.
        pre_rerank_top_k: Number of candidates to rerank before selecting final_top_k. Defaults to 50.
        collection_name: Persisted ChromaDB collection name metadata associated with this
            configuration. This class stores and serializes the value, but does not itself
            select or initialize the active vector store collection. Defaults to
            "rag_collection".
        embedding_model_path: Local directory path to store/load the sentence-transformer
            embedding model. On first use the model is downloaded from Hugging Face and
            saved here; subsequent starts load it from disk. Defaults to
            DEFAULT_EMBEDDING_MODEL_PATH ("./models/embedding").
        reranker_model_path: Local directory path to store/load the cross-encoder reranker
            model. On first use the model is downloaded from Hugging Face and saved here;
            subsequent starts load it from disk. Defaults to
            DEFAULT_RERANKER_MODEL_PATH ("./models/reranker").

    Raises:
        ValueError: If weights don't sum to approximately 1.0 or are not in valid range.
    """

    semantic_top_k: int = 10
    keyword_top_k: int = 10
    final_top_k: int = 5

    semantic_weight: float = 0.65
    keyword_weight: float = 0.35

    enable_rerank: bool = True
    pre_rerank_top_k: int = 50
    collection_name: str = "rag_collection"
    embedding_model_path: str = DEFAULT_EMBEDDING_MODEL_PATH
    reranker_model_path: str = DEFAULT_RERANKER_MODEL_PATH

    def __post_init__(self) -> None:
        """Validate configuration parameters after initialization."""
        if not (0 < self.semantic_top_k):
            raise ValueError("semantic_top_k must be > 0")
        if not (0 < self.keyword_top_k):
            raise ValueError("keyword_top_k must be > 0")
        if not (0 < self.final_top_k):
            raise ValueError("final_top_k must be > 0")

        weight_sum = self.semantic_weight + self.keyword_weight
        if not (0.99 <= weight_sum <= 1.01):
            raise ValueError(
                f"semantic_weight + keyword_weight must equal 1.0, got {weight_sum}"
            )

        if not (0 <= self.semantic_weight <= 1):
            raise ValueError("semantic_weight must be in range [0, 1]")
        if not (0 <= self.keyword_weight <= 1):
            raise ValueError("keyword_weight must be in range [0, 1]")

        if not (0 < self.pre_rerank_top_k):
            raise ValueError("pre_rerank_top_k must be > 0")

        if not isinstance(self.collection_name, str) or not self.collection_name.strip():
            raise ValueError("collection_name must be a non-empty string")

    def update(self, **kwargs: Any) -> "HybridRetrieverConfig":
        """Create a new config instance with updated values.

        Validates all parameters before returning a new instance.
        Original config is not modified (immutable update pattern).

        Args:
            **kwargs: Configuration parameters to update. Valid keys are:
                - semantic_top_k, keyword_top_k, final_top_k
                - semantic_weight, keyword_weight
                - enable_rerank, pre_rerank_top_k
                - collection_name

        Returns:
            New HybridRetrieverConfig instance with updated values.

        Raises:
            ValueError: If any parameter is invalid or validation fails.
            TypeError: If an unknown parameter is provided.

        Example:
            >>> config = HybridRetrieverConfig()
            >>> new_config = config.update(semantic_weight=0.8, keyword_weight=0.2)
            >>> new_config.semantic_weight
            0.8
        """
        # Validate that only known parameters are provided
        valid_params = {
            "semantic_top_k",
            "keyword_top_k",
            "final_top_k",
            "semantic_weight",
            "keyword_weight",
            "enable_rerank",
            "pre_rerank_top_k",
            "collection_name",
            "embedding_model_path",
            "reranker_model_path",
        }
        unknown_params = set(kwargs.keys()) - valid_params
        if unknown_params:
            raise TypeError(
                f"Unknown configuration parameter(s): {', '.join(unknown_params)}"
            )

        # Create new instance with updated values
        updated_config = replace(self, **kwargs)
        # __post_init__ is called automatically, so validation happens here
        return updated_config

    def to_dict(self) -> dict[str, Any]:
        """Convert configuration to dictionary.

        Returns:
            Dictionary representation of the configuration.

        Example:
            >>> config = HybridRetrieverConfig()
            >>> config_dict = config.to_dict()
            >>> config_dict["semantic_weight"]
            0.65
        """
        return {
            "semantic_top_k": self.semantic_top_k,
            "keyword_top_k": self.keyword_top_k,
            "final_top_k": self.final_top_k,
            "semantic_weight": self.semantic_weight,
            "keyword_weight": self.keyword_weight,
            "enable_rerank": self.enable_rerank,
            "pre_rerank_top_k": self.pre_rerank_top_k,
            "collection_name": self.collection_name,
            "embedding_model_path": self.embedding_model_path,
            "reranker_model_path": self.reranker_model_path,
        }

    @classmethod
    def from_dict(cls, config_dict: dict[str, Any]) -> HybridRetrieverConfig:
        """Create configuration from dictionary.

        Args:
            config_dict: Dictionary with configuration parameters.

        Returns:
            New HybridRetrieverConfig instance.

        Example:
            >>> config_dict = {"semantic_weight": 0.8, "keyword_weight": 0.2}
            >>> config = HybridRetrieverConfig.from_dict(config_dict)
            >>> config.semantic_weight
            0.8
        """
        return cls(**config_dict)


# Default configuration instance
DEFAULT_CONFIG = HybridRetrieverConfig(
    enable_rerank=True,
    collection_name="rag_collection",
)


@dataclass
class CacheSettings:
    """Configuration for cache backend and behavior.

    Configures the caching layer for the hybrid retrieval pipeline, supporting both
    in-memory caching (for local development) and Redis caching (for distributed systems).

    The cache stores query results and intermediate computations to improve performance
    across multiple retrievals of the same or similar queries.

    Attributes:
        backend: Cache backend to use. Either 'memory' for in-process TTL cache,
            or 'redis' for distributed Redis-backed caching.
            Defaults to 'memory' for development, 'redis' for production.
        ttl_seconds: Time-to-live for cached entries in seconds. Defaults to 3600 (1 hour).
            Set to 0 for indefinite caching (not recommended for production).
        redis_url: Connection URL for Redis backend (e.g., 'redis://localhost:6379').
            Required if backend='redis', ignored if backend='memory'.
            Defaults to None.
        key_prefix: Prefix prepended to all cache keys to avoid collisions in shared Redis.
            Defaults to 'hybrid_rag_cache:'.
        max_size: Maximum number of entries in in-memory cache before eviction.
            Ignored if backend='redis'. Defaults to 10000.

    Example:
        >>> # In-memory cache for local development
        >>> settings = CacheSettings(
        ...     backend="memory",
        ...     ttl_seconds=3600,
        ...     max_size=10000
        ... )
        >>>
        >>> # Redis cache for production
        >>> settings = CacheSettings(
        ...     backend="redis",
        ...     redis_url="redis://prod-cache:6379/0",
        ...     key_prefix="myapp:",
        ...     ttl_seconds=1800
        ... )
    """

    backend: Literal["memory", "redis"] = field(
        default="memory",
        metadata={"description": "Cache backend: 'memory' or 'redis'"},
    )
    ttl_seconds: int = field(
        default=3600,
        metadata={"description": "Time-to-live for cache entries in seconds"},
    )
    redis_url: Optional[str] = field(
        default=None,
        metadata={"description": "Redis connection URL (required for redis backend)"},
    )
    key_prefix: str = field(
        default="hybrid_rag_cache:",
        metadata={"description": "Prefix for cache keys in Redis"},
    )
    max_size: int = field(
        default=10000,
        metadata={"description": "Max size for in-memory cache"},
    )

    def __post_init__(self) -> None:
        """Validate cache settings after initialization.

        Raises:
            ValueError: If configuration is invalid:
                - backend='redis' but redis_url is None
                - ttl_seconds <= 0
                - max_size <= 0
        """
        # Validate redis configuration
        if self.backend == "redis" and not self.redis_url:
            raise ValueError(
                "redis_url is required when backend='redis'. "
                f"Got backend='{self.backend}', redis_url={self.redis_url}"
            )

        # Enforce secure Redis configuration in production only.
        environment = os.getenv("ENVIRONMENT", "").strip().lower()
        if environment == "production" and self.backend == "redis" and self.redis_url:
            parsed_redis_url = urlparse(self.redis_url)
            if parsed_redis_url.scheme != "rediss":
                raise ValueError(
                    "Production Redis URL must use TLS with the 'rediss://' scheme. "
                    f"Got redis_url='{self.redis_url}'"
                )

            if not parsed_redis_url.password:
                raise ValueError(
                    "Production Redis URL must include authentication credentials/password. "
                    f"Got redis_url='{self.redis_url}'"
                )

        # Validate ttl_seconds
        if self.ttl_seconds <= 0:
            raise ValueError(
                f"ttl_seconds must be > 0, got {self.ttl_seconds}"
            )

        # Validate max_size
        if self.max_size <= 0:
            raise ValueError(
                f"max_size must be > 0, got {self.max_size}"
            )

    @classmethod
    def from_env(cls) -> CacheSettings:
        """Create CacheSettings from environment variables.

        Reads:
            CACHE_BACKEND: 'memory' or 'redis' (default: 'memory')
            REDIS_URL: Connection URL for Redis (required if CACHE_BACKEND='redis')
            CACHE_TTL_SECONDS: TTL in seconds (default: 3600)
            CACHE_KEY_PREFIX: Prefix for cache keys (default: 'hybrid_rag_cache:')
            CACHE_MAX_SIZE: Max in-memory cache size (default: 10000)

        Returns:
            CacheSettings instance configured from environment.

        Raises:
            ValueError: If configuration from environment is invalid.

        Example:
            >>> # With environment variables set:
            >>> # CACHE_BACKEND=redis
            >>> # REDIS_URL=redis://localhost:6379
            >>> settings = CacheSettings.from_env()
        """
        backend: Literal["memory", "redis"] = (
            os.getenv("CACHE_BACKEND", "memory")  # type: ignore[assignment]
        )
        redis_url = os.getenv("REDIS_URL")
        ttl_seconds = int(os.getenv("CACHE_TTL_SECONDS", "3600"))
        key_prefix = os.getenv("CACHE_KEY_PREFIX", "hybrid_rag_cache:")
        max_size = int(os.getenv("CACHE_MAX_SIZE", "10000"))

        return cls(
            backend=backend,
            redis_url=redis_url,
            ttl_seconds=ttl_seconds,
            key_prefix=key_prefix,
            max_size=max_size,
        )


def create_cache_backend(settings: CacheSettings) -> CacheBackend:
    """Factory function to create a cache backend from settings.

    Creates and returns the appropriate cache backend (InMemoryCache or RedisCache)
    based on the provided CacheSettings configuration.

    Args:
        settings: CacheSettings instance with backend configuration.

    Returns:
        CacheBackend: Initialized cache backend instance.
            - InMemoryCache if backend='memory'
            - RedisCache if backend='redis'

    Raises:
        ValueError: If settings validation fails.
        ImportError: If required dependencies for the backend are missing.

    Example:
        >>> from hybrid_rag.config import CacheSettings, create_cache_backend
        >>>
        >>> # Create in-memory cache
        >>> settings = CacheSettings(backend="memory", ttl_seconds=3600)
        >>> cache = create_cache_backend(settings)
        >>> cache.set("key", {"value": 123})
        >>>
        >>> # Create Redis cache
        >>> settings = CacheSettings(
        ...     backend="redis",
        ...     redis_url="redis://localhost:6379",
        ...     key_prefix="app:"
        ... )
        >>> cache = create_cache_backend(settings)
        >>> cache.set("key", {"value": 123})
    """
    from .cache import InMemoryCache, RedisCache

    if settings.backend == "memory":
        return InMemoryCache(
            ttl_seconds=settings.ttl_seconds,
            max_size=settings.max_size,
        )
    elif settings.backend == "redis":
        # redis_url is guaranteed to be not None by __post_init__ validation
        assert settings.redis_url is not None
        return RedisCache(
            redis_url=settings.redis_url,
            key_prefix=settings.key_prefix,
            ttl_seconds=settings.ttl_seconds,
        )
    else:
        raise ValueError(
            f"Unknown cache backend: {settings.backend}. "
            "Must be 'memory' or 'redis'."
        )

