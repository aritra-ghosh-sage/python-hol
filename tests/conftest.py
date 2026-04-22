"""Pytest configuration and shared fixtures for all tests."""

import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import BinaryIO, Generator
from urllib.error import URLError
from urllib.request import urlopen

import pytest
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

TEST_PERSIST_DIR = Path(
    tempfile.mkdtemp(prefix="hybrid_rag_test_")
).resolve()
TEST_COLLECTION_NAME = "hybrid_rag_test_collection"
TEST_SERVER_PERSIST_DIR = Path(
    tempfile.mkdtemp(prefix="hybrid_rag_test_server_")
).resolve()
TEST_SERVER_COLLECTION_NAME = "hybrid_rag_test_server_collection"


def _wait_for_backend(base_url: str, timeout_seconds: int = 30) -> bool:
    """Wait for the backend /health endpoint to respond."""
    deadline = time.time() + timeout_seconds
    health_url = f"{base_url.rstrip('/')}/health"
    while time.time() < deadline:
        try:
            with urlopen(health_url, timeout=1) as response:
                if response.status == 200:
                    return True
        except URLError:
            time.sleep(1)
    return False


def _start_backend_process(
    base_url: str,
) -> tuple[subprocess.Popen[bytes], Path, BinaryIO]:
    """Start the API backend process for integration tests."""
    uv_path = shutil.which("uv")
    command = [uv_path, "run", "api.py"] if uv_path else [sys.executable, "api.py"]
    if uv_path is None:
        logger.warning("uv not found; starting backend with %s", sys.executable)

    env = os.environ.copy()
    env["HYBRID_RAG_EMBEDDING_BACKEND"] = "hash"
    env["HYBRID_RAG_PERSIST_DIR"] = str(TEST_SERVER_PERSIST_DIR)
    env["HYBRID_RAG_COLLECTION_NAME"] = TEST_SERVER_COLLECTION_NAME
    env["CACHE_BACKEND"] = "memory"
    env["CACHE_TTL_SECONDS"] = "3600"
    env["CACHE_MAX_SIZE"] = "10000"
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONPATH"] = str(PROJECT_ROOT)

    log_file = Path(
        tempfile.mkstemp(prefix="hybrid_rag_api_", suffix=".log")[1]
    ).resolve()
    log_handle = log_file.open("wb")
    process = subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    return process, log_file, log_handle


def _shutdown_backend(process: subprocess.Popen[bytes]) -> None:
    """Terminate the backend process gracefully."""
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)

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
    os.environ["CACHE_BACKEND"] = "memory"
    os.environ["CACHE_TTL_SECONDS"] = "3600"
    os.environ["CACHE_MAX_SIZE"] = "10000"
    os.environ["HYBRID_RAG_EMBEDDING_BACKEND"] = "hash"
    os.environ["HYBRID_RAG_PERSIST_DIR"] = str(TEST_PERSIST_DIR)
    os.environ["HYBRID_RAG_COLLECTION_NAME"] = TEST_COLLECTION_NAME
    logger.info("Test environment initialized")


@pytest.fixture(scope="session", autouse=True)
def backend_server() -> Generator[str, None, None]:
    """Ensure the backend server is running for integration tests."""
    base_url = os.getenv("HYBRID_RAG_TEST_BASE_URL", "http://localhost:8000")
    if _wait_for_backend(base_url, timeout_seconds=2):
        yield base_url
        return

    process, log_file, log_handle = _start_backend_process(base_url)
    try:
        if not _wait_for_backend(base_url, timeout_seconds=45):
            log_contents = log_file.read_text(encoding="utf-8", errors="replace")
            raise RuntimeError(
                "Backend failed to start. Log output:\n" + log_contents[-2000:]
            )
        yield base_url
    finally:
        _shutdown_backend(process)
        if log_handle is not None:
            log_handle.close()


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
