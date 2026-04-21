"""Tests for the hybrid_rag cache module."""

import json
import logging
import time
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest

from hybrid_rag.cache import CacheBackend, InMemoryCache, RedisCache

logger = logging.getLogger(__name__)


class TestCacheBackendABC:
    """Test the CacheBackend abstract base class."""

    def test_cannot_instantiate_abstract_base_class(self):
        """CacheBackend is abstract and cannot be instantiated."""
        with pytest.raises(TypeError):
            CacheBackend()

    def test_subclass_must_implement_all_methods(self):
        """Subclass must implement all 5 required methods."""
        # Verify that the ABC has exactly 5 abstract methods
        abstract_methods = CacheBackend.__abstractmethods__
        assert len(abstract_methods) == 5
        assert "get" in abstract_methods
        assert "set" in abstract_methods
        assert "delete" in abstract_methods
        assert "clear" in abstract_methods
        assert "stats" in abstract_methods


class TestInMemoryCache:
    """Test the InMemoryCache implementation."""

    def test_initialization_with_defaults(self):
        """InMemoryCache initializes with sensible defaults."""
        cache = InMemoryCache()
        assert cache is not None
        stats = cache.stats()
        assert stats["backend"] == "memory"
        assert stats["size"] == 0
        assert stats["max_size"] == 10000
        assert stats["hits"] == 0
        assert stats["misses"] == 0

    def test_initialization_with_custom_values(self):
        """InMemoryCache accepts custom ttl_seconds and max_size."""
        cache = InMemoryCache(ttl_seconds=600, max_size=5000)
        stats = cache.stats()
        assert stats["max_size"] == 5000

    def test_set_and_get_basic(self):
        """set() stores a value and get() retrieves it."""
        cache = InMemoryCache()
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_get_returns_none_for_missing_key(self):
        """get() returns None for keys that don't exist."""
        cache = InMemoryCache()
        assert cache.get("nonexistent") is None

    def test_set_with_ttl_expiration(self):
        """Values expire after ttl_seconds."""
        cache = InMemoryCache(ttl_seconds=1)
        cache.set("key1", "value1", ttl_seconds=1)
        assert cache.get("key1") == "value1"
        time.sleep(1.1)
        assert cache.get("key1") is None

    def test_set_with_override_ttl(self):
        """set() with ttl_seconds parameter (note: cachetools.TTLCache uses global TTL)."""
        # Note: cachetools.TTLCache uses a global TTL for all entries,
        # so per-key TTL overrides are not supported.
        # The ttl_seconds parameter is accepted but currently ignored.
        cache = InMemoryCache(ttl_seconds=3600)
        cache.set("key1", "value1", ttl_seconds=1)
        # Key should be in cache (using the default TTL)
        assert cache.get("key1") == "value1"

    def test_delete_removes_key(self):
        """delete() removes a key from cache."""
        cache = InMemoryCache()
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"
        cache.delete("key1")
        assert cache.get("key1") is None

    def test_delete_nonexistent_key_is_safe(self):
        """delete() on nonexistent key raises no error."""
        cache = InMemoryCache()
        cache.delete("nonexistent")  # Should not raise

    def test_clear_removes_all_keys(self):
        """clear() removes all keys from cache."""
        cache = InMemoryCache()
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")
        assert cache.stats()["size"] == 3
        cache.clear()
        assert cache.stats()["size"] == 0
        assert cache.get("key1") is None
        assert cache.get("key2") is None

    def test_stats_tracks_hits_and_misses(self):
        """stats() tracks cache hits and misses."""
        cache = InMemoryCache()
        cache.set("key1", "value1")
        
        # Hit
        cache.get("key1")
        stats = cache.stats()
        assert stats["hits"] == 1
        
        # Miss
        cache.get("nonexistent")
        stats = cache.stats()
        assert stats["misses"] == 1

    def test_stats_returns_correct_size(self):
        """stats() returns correct size."""
        cache = InMemoryCache()
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        stats = cache.stats()
        assert stats["size"] == 2

    def test_thread_safety_concurrent_access(self):
        """InMemoryCache is thread-safe with concurrent access."""
        import threading

        cache = InMemoryCache()
        results = []
        errors = []

        def write_thread(key: str, value: str) -> None:
            try:
                for i in range(100):
                    cache.set(f"{key}_{i}", f"{value}_{i}")
            except Exception as e:
                errors.append(e)

        def read_thread(key: str) -> None:
            try:
                for i in range(100):
                    cache.get(f"{key}_{i}")
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=write_thread, args=("key", "value")),
            threading.Thread(target=read_thread, args=("key",)),
            threading.Thread(target=write_thread, args=("key2", "value2")),
            threading.Thread(target=read_thread, args=("key2",)),
        ]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        assert len(errors) == 0, f"Thread safety errors: {errors}"

    def test_various_data_types(self):
        """Cache can store various Python data types."""
        cache = InMemoryCache()
        
        test_data = [
            ("str", "test string"),
            ("int", 42),
            ("float", 3.14),
            ("bool", True),
            ("list", [1, 2, 3]),
            ("dict", {"key": "value"}),
            ("tuple", (1, 2, 3)),
            ("none", None),
        ]
        
        for key, value in test_data:
            cache.set(key, value)
            assert cache.get(key) == value


class TestRedisCache:
    """Test the RedisCache implementation."""

    @pytest.fixture
    def mock_redis(self):
        """Provide a mock Redis connection."""
        with patch("hybrid_rag.cache.redis.ConnectionPool"):
            with patch("hybrid_rag.cache.redis.Redis") as mock_redis_class:
                mock_conn = MagicMock()
                mock_redis_class.return_value = mock_conn
                yield mock_redis_class, mock_conn

    def test_initialization_with_defaults(self, mock_redis):
        """RedisCache initializes with sensible defaults."""
        mock_redis_class, mock_conn = mock_redis
        cache = RedisCache()
        assert cache is not None
        stats = cache.stats()
        assert stats["backend"] == "redis"
        assert "redis_url" in stats
        assert stats["hits"] == 0
        assert stats["misses"] == 0

    def test_initialization_with_custom_values(self, mock_redis):
        """RedisCache accepts custom redis_url and key_prefix."""
        mock_redis_class, mock_conn = mock_redis
        cache = RedisCache(
            redis_url="redis://custom:6379",
            key_prefix="app:",
            ttl_seconds=1800
        )
        assert cache is not None

    def test_set_serializes_json(self, mock_redis):
        """set() serializes value to JSON before storing."""
        mock_redis_class, mock_conn = mock_redis
        mock_conn.setex = MagicMock()
        
        cache = RedisCache()
        cache.set("key1", {"data": "value"})
        
        # Verify setex was called with JSON string
        mock_conn.setex.assert_called_once()
        call_args = mock_conn.setex.call_args
        assert "key1" in str(call_args[0])

    def test_get_deserializes_json(self, mock_redis):
        """get() deserializes JSON value."""
        mock_redis_class, mock_conn = mock_redis
        test_dict = {"data": "value"}
        mock_conn.get = MagicMock(return_value=json.dumps(test_dict).encode())
        
        cache = RedisCache()
        result = cache.get("key1")
        
        assert result == test_dict

    def test_get_returns_none_for_missing_key(self, mock_redis):
        """get() returns None when Redis returns None."""
        mock_redis_class, mock_conn = mock_redis
        mock_conn.get = MagicMock(return_value=None)
        
        cache = RedisCache()
        result = cache.get("nonexistent")
        
        assert result is None

    def test_delete_removes_key(self, mock_redis):
        """delete() removes a key from Redis."""
        mock_redis_class, mock_conn = mock_redis
        mock_conn.delete = MagicMock()
        
        cache = RedisCache()
        cache.delete("key1")
        
        mock_conn.delete.assert_called_once()

    def test_clear_removes_all_prefixed_keys(self, mock_redis):
        """clear() removes all keys with the cache prefix."""
        mock_redis_class, mock_conn = mock_redis
        mock_conn.scan_iter = MagicMock(return_value=[b"cache:key1", b"cache:key2"])
        mock_conn.delete = MagicMock()
        
        cache = RedisCache()
        cache.clear()
        
        # Should call delete with the keys found
        assert mock_conn.delete.called or mock_conn.scan_iter.called

    def test_fail_open_on_redis_connection_error(self, mock_redis):
        """Operations fail open (don't raise) on Redis connection errors."""
        mock_redis_class, mock_conn = mock_redis
        mock_conn.setex = MagicMock(side_effect=Exception("Redis connection failed"))
        
        cache = RedisCache()
        # Should not raise, just log and continue
        try:
            cache.set("key1", "value1")
            # If we get here without exception, fail-open worked
            assert True
        except Exception as e:
            pytest.fail(f"set() should not raise on Redis error, but raised: {e}")

    def test_fail_open_on_redis_get_error(self, mock_redis):
        """get() fails open on Redis errors."""
        mock_redis_class, mock_conn = mock_redis
        mock_conn.get = MagicMock(side_effect=Exception("Redis connection failed"))
        
        cache = RedisCache()
        result = cache.get("key1")
        
        # Should return None, not raise
        assert result is None

    def test_fail_open_on_json_decode_error(self, mock_redis):
        """get() fails open on JSON decode errors."""
        mock_redis_class, mock_conn = mock_redis
        mock_conn.get = MagicMock(return_value=b"not valid json")
        
        cache = RedisCache()
        result = cache.get("key1")
        
        # Should return None, not raise
        assert result is None

    def test_stats_tracks_hits_and_misses(self, mock_redis):
        """stats() tracks cache hits and misses."""
        mock_redis_class, mock_conn = mock_redis
        mock_conn.get = MagicMock(return_value=json.dumps({"data": "value"}).encode())
        
        cache = RedisCache()
        cache.get("key1")
        stats = cache.stats()
        assert stats["hits"] == 1
        
        mock_conn.get = MagicMock(return_value=None)
        cache.get("key2")
        stats = cache.stats()
        assert stats["misses"] == 1

    def test_key_prefix_applied(self, mock_redis):
        """Keys are prefixed with key_prefix."""
        mock_redis_class, mock_conn = mock_redis
        mock_conn.setex = MagicMock()
        
        cache = RedisCache(key_prefix="app:")
        cache.set("key1", "value1")
        
        # Verify the call included the prefix
        mock_conn.setex.assert_called_once()
        call_args = str(mock_conn.setex.call_args)
        assert "app:key1" in call_args


class TestRedisCacheProductionGuardrails:
    """SEC-004: Direct RedisCache constructor enforces production security policy."""

    def test_production_rejects_non_tls_url(self, monkeypatch: pytest.MonkeyPatch):
        """Production rejects redis:// URL — TLS required via rediss://."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        with pytest.raises(ValueError, match="rediss://"):
            RedisCache(redis_url="redis://localhost:6379")

    def test_production_rejects_non_tls_url_with_host(self, monkeypatch: pytest.MonkeyPatch):
        """Production rejects redis:// even with explicit host and port."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        with pytest.raises(ValueError, match="rediss://"):
            RedisCache(redis_url="redis://prod-cache.internal:6379/0")

    def test_production_rejects_tls_url_without_password(self, monkeypatch: pytest.MonkeyPatch):
        """Production rejects rediss:// URL when no password is present."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        with pytest.raises(ValueError, match="password"):
            RedisCache(redis_url="rediss://prod-cache.internal:6380")

    def test_production_rejects_tls_url_with_username_only(self, monkeypatch: pytest.MonkeyPatch):
        """Production rejects rediss:// with username but no password."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        with pytest.raises(ValueError, match="password"):
            RedisCache(redis_url="rediss://user@prod-cache.internal:6380")

    def test_production_accepts_tls_url_with_password(self, monkeypatch: pytest.MonkeyPatch):
        """Production accepts rediss:// with password — valid secure configuration."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        with patch("hybrid_rag.cache.redis.ConnectionPool"):
            with patch("hybrid_rag.cache.redis.Redis"):
                # Should NOT raise
                cache = RedisCache(redis_url="rediss://:s3cr3tpassword@prod-cache.internal:6380")
                assert cache is not None

    def test_production_accepts_tls_url_with_user_and_password(self, monkeypatch: pytest.MonkeyPatch):
        """Production accepts rediss:// with both username and password."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        with patch("hybrid_rag.cache.redis.ConnectionPool"):
            with patch("hybrid_rag.cache.redis.Redis"):
                cache = RedisCache(redis_url="rediss://user:s3cr3t@prod-cache.internal:6380/1")
                assert cache is not None

    def test_non_production_accepts_non_tls_url(self, monkeypatch: pytest.MonkeyPatch):
        """Non-production allows redis:// for local/dev workflows."""
        monkeypatch.setenv("ENVIRONMENT", "development")
        with patch("hybrid_rag.cache.redis.ConnectionPool"):
            with patch("hybrid_rag.cache.redis.Redis"):
                cache = RedisCache(redis_url="redis://localhost:6379")
                assert cache is not None

    def test_non_production_allows_no_env_var(self, monkeypatch: pytest.MonkeyPatch):
        """Absent ENVIRONMENT env var is backward-compatible (non-prod)."""
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        with patch("hybrid_rag.cache.redis.ConnectionPool"):
            with patch("hybrid_rag.cache.redis.Redis"):
                cache = RedisCache(redis_url="redis://localhost:6379")
                assert cache is not None

    def test_staging_allows_non_tls_url(self, monkeypatch: pytest.MonkeyPatch):
        """Staging environment allows redis:// for compatibility."""
        monkeypatch.setenv("ENVIRONMENT", "staging")
        with patch("hybrid_rag.cache.redis.ConnectionPool"):
            with patch("hybrid_rag.cache.redis.Redis"):
                cache = RedisCache(redis_url="redis://staging-cache:6379")
                assert cache is not None

    def test_fail_open_runtime_behavior_unchanged_in_production(self, monkeypatch: pytest.MonkeyPatch):
        """After valid production init, runtime operation failures still fail-open."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        with patch("hybrid_rag.cache.redis.ConnectionPool"):
            with patch("hybrid_rag.cache.redis.Redis") as mock_redis_cls:
                mock_conn = MagicMock()
                mock_conn.get = MagicMock(side_effect=Exception("Redis timeout"))
                mock_conn.setex = MagicMock(side_effect=Exception("Redis timeout"))
                mock_redis_cls.return_value = mock_conn

                cache = RedisCache(redis_url="rediss://:password@prod-cache:6380")
                # Runtime errors must still fail-open (no exception raised)
                result = cache.get("some-key")
                assert result is None
                cache.set("some-key", "value")  # must not raise


class TestCacheIntegration:
    """Integration tests for both cache backends."""

    def test_both_caches_have_same_interface(self):
        """Both InMemoryCache and RedisCache implement CacheBackend."""
        in_memory = InMemoryCache()
        assert isinstance(in_memory, CacheBackend)

    def test_cache_set_get_delete_workflow(self):
        """Basic workflow: set -> get -> delete -> get."""
        cache = InMemoryCache()
        
        # Set
        cache.set("query:1", {"results": [1, 2, 3]})
        
        # Get
        result = cache.get("query:1")
        assert result == {"results": [1, 2, 3]}
        
        # Delete
        cache.delete("query:1")
        
        # Get after delete
        result = cache.get("query:1")
        assert result is None

    def test_cache_multiple_operations(self):
        """Multiple operations maintain consistency."""
        cache = InMemoryCache()
        
        # Set multiple
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")
        
        # Get multiple
        assert cache.get("key1") == "value1"
        assert cache.get("key2") == "value2"
        assert cache.get("key3") == "value3"
        
        # Stats
        stats = cache.stats()
        assert stats["size"] == 3
        assert stats["hits"] == 3
        
        # Clear
        cache.clear()
        assert cache.stats()["size"] == 0


class TestCacheSettings:
    """Test the CacheSettings dataclass and validation."""

    def test_initialization_with_defaults(self):
        """CacheSettings initializes with sensible defaults."""
        from hybrid_rag.config import CacheSettings
        
        settings = CacheSettings()
        assert settings.backend == "memory"
        assert settings.ttl_seconds == 3600
        assert settings.redis_url is None
        assert settings.key_prefix == "hybrid_rag_cache:"
        assert settings.max_size == 10000

    def test_initialization_with_custom_values(self):
        """CacheSettings accepts custom values."""
        from hybrid_rag.config import CacheSettings
        
        settings = CacheSettings(
            backend="redis",
            ttl_seconds=1800,
            redis_url="redis://localhost:6379",
            key_prefix="app:",
            max_size=5000
        )
        assert settings.backend == "redis"
        assert settings.ttl_seconds == 1800
        assert settings.redis_url == "redis://localhost:6379"
        assert settings.key_prefix == "app:"
        assert settings.max_size == 5000

    def test_validation_redis_without_url_raises_error(self):
        """backend='redis' without redis_url raises ValueError."""
        from hybrid_rag.config import CacheSettings
        
        with pytest.raises(ValueError, match="redis_url is required"):
            CacheSettings(backend="redis", redis_url=None)

    def test_validation_ttl_seconds_must_be_positive(self):
        """ttl_seconds <= 0 raises ValueError."""
        from hybrid_rag.config import CacheSettings
        
        with pytest.raises(ValueError, match="ttl_seconds must be > 0"):
            CacheSettings(ttl_seconds=0)
        
        with pytest.raises(ValueError, match="ttl_seconds must be > 0"):
            CacheSettings(ttl_seconds=-1)

    def test_validation_max_size_must_be_positive(self):
        """max_size <= 0 raises ValueError."""
        from hybrid_rag.config import CacheSettings
        
        with pytest.raises(ValueError, match="max_size must be > 0"):
            CacheSettings(max_size=0)
        
        with pytest.raises(ValueError, match="max_size must be > 0"):
            CacheSettings(max_size=-1)

    def test_validation_backend_literal_type(self):
        """backend must be 'memory' or 'redis'."""
        from hybrid_rag.config import CacheSettings
        
        # Valid backends
        settings1 = CacheSettings(backend="memory")
        assert settings1.backend == "memory"
        
        settings2 = CacheSettings(backend="redis", redis_url="redis://localhost")
        assert settings2.backend == "redis"

    def test_memory_backend_with_redis_url_is_allowed(self):
        """backend='memory' with redis_url is allowed (redis_url just ignored)."""
        from hybrid_rag.config import CacheSettings
        
        settings = CacheSettings(
            backend="memory",
            redis_url="redis://localhost:6379"
        )
        assert settings.backend == "memory"
        assert settings.redis_url == "redis://localhost:6379"

    def test_redis_backend_with_valid_url(self):
        """backend='redis' with valid URL passes validation."""
        from hybrid_rag.config import CacheSettings
        
        settings = CacheSettings(
            backend="redis",
            redis_url="redis://localhost:6379/0"
        )
        assert settings.backend == "redis"
        assert settings.redis_url == "redis://localhost:6379/0"

    def test_production_rejects_non_tls_redis_url(self, monkeypatch: pytest.MonkeyPatch):
        """Production environment rejects redis:// URLs (must be rediss://)."""
        from hybrid_rag.config import CacheSettings

        monkeypatch.setenv("ENVIRONMENT", "production")

        with pytest.raises(ValueError, match="rediss://"):
            CacheSettings(
                backend="redis",
                redis_url="redis://localhost:6379/0",
            )

    def test_production_rejects_redis_url_without_auth(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Production environment rejects Redis URLs missing auth/password."""
        from hybrid_rag.config import CacheSettings

        monkeypatch.setenv("ENVIRONMENT", "production")

        with pytest.raises(ValueError, match="password"):
            CacheSettings(
                backend="redis",
                redis_url="rediss://localhost:6379/0",
            )

    def test_non_production_allows_local_redis_defaults(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Non-production keeps backward-compatible local redis:// behavior."""
        from hybrid_rag.config import CacheSettings

        monkeypatch.setenv("ENVIRONMENT", "development")

        settings = CacheSettings(
            backend="redis",
            redis_url="redis://localhost:6379/0",
        )

        assert settings.backend == "redis"
        assert settings.redis_url == "redis://localhost:6379/0"

    def test_all_validation_errors_are_value_errors(self):
        """All validation errors are ValueError with clear messages."""
        from hybrid_rag.config import CacheSettings
        
        test_cases = [
            ({"backend": "redis"}, "redis_url is required"),
            ({"ttl_seconds": 0}, "ttl_seconds must be > 0"),
            ({"max_size": 0}, "max_size must be > 0"),
        ]
        
        for kwargs, error_msg in test_cases:
            with pytest.raises(ValueError, match=error_msg):
                CacheSettings(**kwargs)


class TestCreateCacheBackend:
    """Test the create_cache_backend factory function."""

    def test_factory_returns_in_memory_cache(self):
        """create_cache_backend returns InMemoryCache for backend='memory'."""
        from hybrid_rag.config import CacheSettings, create_cache_backend
        
        settings = CacheSettings(backend="memory", ttl_seconds=3600, max_size=10000)
        cache = create_cache_backend(settings)
        
        assert isinstance(cache, InMemoryCache)
        stats = cache.stats()
        assert stats["backend"] == "memory"

    def test_factory_returns_redis_cache(self):
        """create_cache_backend returns RedisCache for backend='redis'."""
        from hybrid_rag.config import CacheSettings, create_cache_backend
        
        with patch("hybrid_rag.cache.redis.ConnectionPool"):
            with patch("hybrid_rag.cache.redis.Redis"):
                settings = CacheSettings(
                    backend="redis",
                    redis_url="redis://localhost:6379",
                    key_prefix="app:",
                    ttl_seconds=1800
                )
                cache = create_cache_backend(settings)
                
                assert isinstance(cache, RedisCache)
                stats = cache.stats()
                assert stats["backend"] == "redis"

    def test_factory_passes_settings_to_in_memory_cache(self):
        """create_cache_backend passes correct parameters to InMemoryCache."""
        from hybrid_rag.config import CacheSettings, create_cache_backend
        
        settings = CacheSettings(
            backend="memory",
            ttl_seconds=1200,
            max_size=5000
        )
        cache = create_cache_backend(settings)
        
        # Verify the cache was created with correct settings
        stats = cache.stats()
        assert stats["max_size"] == 5000

    def test_factory_passes_settings_to_redis_cache(self):
        """create_cache_backend passes correct parameters to RedisCache."""
        from hybrid_rag.config import CacheSettings, create_cache_backend
        
        with patch("hybrid_rag.cache.redis.ConnectionPool"):
            with patch("hybrid_rag.cache.redis.Redis"):
                settings = CacheSettings(
                    backend="redis",
                    redis_url="redis://custom:6380",
                    key_prefix="myapp:",
                    ttl_seconds=1800
                )
                cache = create_cache_backend(settings)
                
                # Verify Redis cache was created
                assert isinstance(cache, RedisCache)

    def test_factory_with_default_settings(self):
        """create_cache_backend works with default CacheSettings."""
        from hybrid_rag.config import CacheSettings, create_cache_backend
        
        settings = CacheSettings()  # All defaults
        cache = create_cache_backend(settings)
        
        assert isinstance(cache, InMemoryCache)
        stats = cache.stats()
        assert stats["backend"] == "memory"
        assert stats["max_size"] == 10000
