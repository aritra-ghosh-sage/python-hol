"""Pytest configuration and shared fixtures for all tests."""

import logging
import sys
from pathlib import Path
import pytest
from typing import Generator
from fastapi.testclient import TestClient

# Ensure project root is importable when tests are run via uv/pytest.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import api
from hybrid_rag import initialize_vector_db, get_sample_documents, HybridRetriever, HybridRetrieverConfig
from hybrid_rag.cache import InMemoryCache
from hybrid_rag.config import CacheSettings, create_cache_backend

logger = logging.getLogger(__name__)

# Configure logging for tests
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


def _is_retriever_collection_healthy() -> bool:
    """Return True when the global retriever has an accessible collection."""
    if api._retriever is None:
        return False

    try:
        collection = api._retriever.collection
        # count() forces a round-trip to Chroma and surfaces stale/deleted handles.
        _ = collection.count()
        return True
    except Exception as exc:
        logger.warning("Retriever collection health check failed: %s", exc)
        return False


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment() -> None:
    """Set up test environment once per session."""
    # Ensure test environment variables are set
    import os
    os.environ.setdefault("CACHE_BACKEND", "memory")
    os.environ.setdefault("CACHE_TTL_SECONDS", "3600")
    os.environ.setdefault("CACHE_MAX_SIZE", "10000")
    logger.info("Test environment initialized")


@pytest.fixture(scope="function")
def initialized_app() -> Generator[TestClient, None, None]:
    """Create and initialize the app with retriever and cache.
    
    This fixture:
    1. Initializes the hybrid retriever
    2. Initializes the cache backend
    3. Returns a TestClient
    4. Cleans up after the test
    
    Yields:
        TestClient: A test client for the initialized app
    """
    # Always initialize a fresh retriever per test to avoid stale collection handles.
    # Some tests recreate/delete the same underlying collection name, which can invalidate
    # previously held retriever references across modules.
    logger.info("Initializing retriever for test...")
    try:
        config = HybridRetrieverConfig(
            semantic_weight=0.7,
            keyword_weight=0.3,
            enable_rerank=True
        )
        documents = get_sample_documents()
        collection = initialize_vector_db(documents)
        api._retriever = HybridRetriever(collection, config)
        api._config = config
        logger.info("✓ Retriever initialized")
    except Exception as e:
        logger.error(f"Failed to initialize retriever: {e}")
        raise

    # Always initialize a fresh cache backend for deterministic hit/miss counters.
    logger.info("Initializing cache for test...")
    try:
        cache_settings = CacheSettings.from_env()
        api._cache = create_cache_backend(cache_settings)
        logger.info("✓ Cache initialized")
    except Exception as e:
        logger.error(f"Failed to initialize cache: {e}")
        # Continue without cache
        api._cache = None

    # Reset shared cache generation token for test isolation.
    api._cache_generation = 0
    
    # Create test client
    client = TestClient(api.app)
    
    try:
        yield client
    finally:
        # Cleanup after test
        if api._cache is not None:
            try:
                api._cache.clear()
            except Exception as e:
                logger.warning(f"Error clearing cache after test: {e}")


@pytest.fixture(scope="function")
def client_with_fresh_cache(initialized_app: TestClient) -> TestClient:
    """TestClient with fresh (cleared) cache for each test.
    
    Args:
        initialized_app: The initialized app fixture
        
    Returns:
        TestClient: The app with cleared cache
    """
    # Clear cache before test
    if api._cache is not None:
        api._cache.clear()
    
    return initialized_app
