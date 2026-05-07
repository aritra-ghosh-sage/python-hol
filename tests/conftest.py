"""Pytest configuration and shared fixtures for all tests."""

import logging
import sys
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock

import cachetools
import numpy as np
import pytest
from fastapi.testclient import TestClient

# Ensure project root is importable when tests are run via uv/pytest.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import api  # noqa: E402
from hybrid_rag import HybridRetriever, HybridRetrieverConfig, initialize_vector_db, get_sample_documents  # noqa: E402
from hybrid_rag.cache import InMemoryCache  # noqa: E402
from hybrid_rag.config import CacheSettings, create_cache_backend  # noqa: E402

logger = logging.getLogger(__name__)

# Configure logging for tests
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-slow",
        action="store_true",
        default=False,
        help="Run tests marked @pytest.mark.slow (downloads models, makes network calls).",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if config.getoption("--run-slow"):
        return
    skip_slow = pytest.mark.skip(reason="slow test — pass --run-slow to enable")
    for item in items:
        if item.get_closest_marker("slow"):
            item.add_marker(skip_slow)


def _make_fake_retriever() -> HybridRetriever:
    """Build a HybridRetriever stub that never loads the sentence-transformer model.

    Bypasses __init__ and injects the minimum attributes required by api.py:
    collection (with a count() method), config, encoder (stub), and L2 cache.
    """
    obj: HybridRetriever = object.__new__(HybridRetriever)
    collection = MagicMock()
    collection.count.return_value = 5
    obj.collection = collection
    obj.config = HybridRetrieverConfig(
        semantic_weight=0.65, keyword_weight=0.35, enable_rerank=False
    )
    obj.reranker = None
    obj.encoder = MagicMock()
    obj.encoder.encode = lambda text: np.zeros(384, dtype=np.float32)
    obj._embedding_cache: cachetools.LRUCache = cachetools.LRUCache(maxsize=5000)
    obj._embedding_cache_hits = 0
    obj._embedding_cache_misses = 0
    return obj


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment() -> None:
    """Set up test environment once per session."""
    import os
    os.environ.setdefault("CACHE_BACKEND", "memory")
    os.environ.setdefault("CACHE_TTL_SECONDS", "3600")
    os.environ.setdefault("CACHE_MAX_SIZE", "10000")
    logger.info("Test environment initialized")


@pytest.fixture(scope="function")
def initialized_app(request: pytest.FixtureRequest) -> Generator[TestClient, None, None]:
    """Create and initialize the app with retriever and cache.

    This fixture:
    1. Initializes the hybrid retriever
    2. Initializes the cache backend
    3. Returns a TestClient
    4. Cleans up after the test

    Yields:
        TestClient: A test client for the initialized app
    """
    if not request.config.getoption("--run-slow", default=False):
        pytest.skip("slow test — pass --run-slow to enable (downloads embedding model)")
    # Always initialize a fresh retriever per test to avoid stale collection handles.
    # Some tests recreate/delete the same underlying collection name, which can invalidate
    # previously held retriever references across modules.
    logger.info("Initializing retriever for test...")
    try:
        config = HybridRetrieverConfig(
            semantic_weight=0.65,
            keyword_weight=0.35,
            enable_rerank=True
        )
        documents = get_sample_documents()
        collection = initialize_vector_db(documents)
        api._retriever = HybridRetriever(collection, config)
        api._config = config
        logger.info("✓ Retriever initialized")
    except Exception as e:
        logger.error(f"Failed to initialize retriever: {e}")
        pytest.skip(f"Skipping: retriever could not be initialized (network or model unavailable): {e}")

    # Always initialize a fresh cache backend for deterministic hit/miss counters.
    logger.info("Initializing cache for test...")
    try:
        cache_settings = CacheSettings.from_env()
        api._cache = create_cache_backend(cache_settings)
        logger.info("✓ Cache initialized")
    except Exception as e:
        logger.error(f"Failed to initialize cache: {e}")
        api._cache = None

    # Reset shared cache generation token for test isolation.
    api._cache_generation = 0

    with TestClient(api.app) as client:
        try:
            yield client
        finally:
            if api._cache is not None:
                try:
                    api._cache.clear()
                except Exception as e:
                    logger.warning(f"Error clearing cache after test: {e}")


@pytest.fixture(scope="function")
def fake_initialized_app() -> Generator[TestClient, None, None]:
    """TestClient with a stub retriever — no ChromaDB, no model download.

    Used by tests that only inspect HTTP response shapes (status codes, JSON
    field names, admin endpoints) and never call the retrieval pipeline.
    Setup cost is <10 ms vs 10–18 s for the real initialized_app fixture.

    Yields:
        TestClient: A test client backed by an in-memory cache and stub retriever.
    """
    api._retriever = _make_fake_retriever()
    api._config = api._retriever.config
    api._cache = InMemoryCache(ttl_seconds=3600, max_size=10000)
    api._cache_generation = 0

    # Patch initialize_retriever to a no-op so the lifespan runs (registers routers)
    # without triggering a HuggingFace model download. State is already injected above.
    original_initialize = api.initialize_retriever
    api.initialize_retriever = lambda: None
    try:
        with TestClient(api.app) as client:
            try:
                yield client
            finally:
                if api._cache is not None:
                    try:
                        api._cache.clear()
                    except Exception:
                        pass
    finally:
        api.initialize_retriever = original_initialize


@pytest.fixture(scope="function")
def client_with_fresh_cache(fake_initialized_app: TestClient) -> TestClient:
    """TestClient with fresh (cleared) cache for each test.

    Args:
        fake_initialized_app: The stub-backed app fixture (no model load).

    Returns:
        TestClient: The app with cleared cache.
    """
    if api._cache is not None:
        api._cache.clear()

    return fake_initialized_app
