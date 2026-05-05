"""Tests for the MCP server."""

import pytest
from unittest.mock import AsyncMock, MagicMock

import mcp_server
from hybrid_rag import DEFAULT_CONFIG
import asyncio


@pytest.fixture
def mock_retriever():
    """Create a mock retriever."""
    retriever = MagicMock()
    retriever.retrieve.return_value = [
        {
            "id": "doc1",
            "text": "Sample document text",
            "metadata": {"source": "test_doc.txt", "source_url": None},
            "score": 0.85,
        }
    ]
    return retriever


@pytest.fixture(autouse=True)
def restore_module_state():
    """Restore mutable module globals after each test."""
    original_retriever = mcp_server._retriever
    original_config = mcp_server._config
    original_cache = mcp_server._cache
    original_corpus_version = mcp_server._corpus_version
    yield
    mcp_server._retriever = original_retriever
    mcp_server._config = original_config
    mcp_server._cache = original_cache
    mcp_server._corpus_version = original_corpus_version


@pytest.mark.asyncio
async def test_query_knowledge_base_returns_results(mock_retriever):
    """Test that query_knowledge_base returns properly formatted results."""
    # Initialize server state with mock
    mcp_server._retriever = mock_retriever
    mcp_server._config = DEFAULT_CONFIG

    result = await mcp_server.query_knowledge_base("test query")

    assert "results" in result
    assert "total_results" in result
    assert len(result["results"]) == 1
    assert result["total_results"] == 1
    doc = result["results"][0]
    assert doc["id"] == "doc1"
    assert doc["text"] == "Sample document text"
    assert doc["source"] == "test_doc.txt"
    assert doc["source_url"] is None
    assert doc["score"] == 0.85
    assert "metadata" not in doc


@pytest.mark.asyncio
async def test_query_knowledge_base_filters_low_scores(mock_retriever):
    """Test that results below min_score_threshold are filtered."""
    mock_retriever.retrieve.return_value = [
        {"id": "d1", "text": "high", "metadata": {"source": "a.txt", "source_url": None}, "score": 0.85},
        {"id": "d2", "text": "low", "metadata": {"source": "b.txt","source_url": None}, "score": 0.30},  # Below threshold
    ]
    mcp_server._retriever = mock_retriever
    mcp_server._config = DEFAULT_CONFIG

    result = await mcp_server.query_knowledge_base("test query")

    # Only the high-score result should be included
    assert result["total_results"] == 1
    assert result["results"][0]["score"] == 0.85


@pytest.mark.asyncio
async def test_query_knowledge_base_empty_query():
    """Test that empty queries are rejected."""
    mcp_server._retriever = MagicMock()

    with pytest.raises(ValueError, match="Query must be between 1 and 500 characters"):
        await mcp_server.query_knowledge_base("")


@pytest.mark.asyncio
async def test_query_knowledge_base_oversized_query():
    """Test that oversized queries are rejected."""
    mcp_server._retriever = MagicMock()

    with pytest.raises(ValueError, match="Query must be between 1 and 500 characters"):
        await mcp_server.query_knowledge_base("x" * 501)


@pytest.mark.asyncio
async def test_query_knowledge_base_not_initialized():
    """Test that querying without initialization raises error."""
    mcp_server._retriever = None

    with pytest.raises(ValueError, match="Retriever not initialized"):
        await mcp_server.query_knowledge_base("test")


@pytest.mark.asyncio
async def test_get_config():
    """Test that get_config returns current configuration."""
    mcp_server._config = DEFAULT_CONFIG

    result = await mcp_server.get_config()

    assert isinstance(result, dict)
    assert "semantic_top_k" in result
    assert "keyword_top_k" in result
    assert "final_top_k" in result
    assert "enable_rerank" in result


@pytest.mark.asyncio
async def test_query_knowledge_base_enable_rerank_override(mock_retriever):
    """Test that enable_rerank parameter is passed through."""
    mcp_server._retriever = mock_retriever
    mcp_server._config = DEFAULT_CONFIG

    await mcp_server.query_knowledge_base("test", enable_rerank=True)

    mock_retriever.retrieve.assert_called_once_with("test", enable_rerank=True)


def test_mcp_server_has_query_tool():
    """Test that the MCP server exposes the query_knowledge_base tool."""
    # FastMCP stores tools in the _tool_manager._tools dict
    assert hasattr(mcp_server.mcp._tool_manager, "_tools")
    tool_names = list(mcp_server.mcp._tool_manager._tools.keys())
    assert "query_knowledge_base" in tool_names


def test_mcp_server_has_config_tool():
    """Test that the MCP server exposes the get_config tool."""
    tool_names = list(mcp_server.mcp._tool_manager._tools.keys())
    assert "get_config" in tool_names


@pytest.mark.asyncio
async def test_initialize_retriever_uses_open_collection_when_collection_exists(monkeypatch):
    """Initialize retriever from an existing collection."""
    config = DEFAULT_CONFIG.update(collection_name="existing_collection")
    mock_collection = MagicMock()
    mock_retriever_instance = MagicMock()

    mcp_server._retriever = None
    mcp_server._config = DEFAULT_CONFIG

    monkeypatch.setattr(
        mcp_server, "_load_initial_config", MagicMock(return_value=config)
    )
    monkeypatch.setattr(
        mcp_server,
        "list_existing_collections",
        MagicMock(return_value=[config.collection_name]),
    )
    monkeypatch.setattr(mcp_server, "open_collection", lambda **_: mock_collection)
    init_vector_db_mock = MagicMock()
    monkeypatch.setattr(mcp_server, "initialize_vector_db", init_vector_db_mock)
    monkeypatch.setattr(
        mcp_server,
        "HybridRetriever",
        MagicMock(return_value=mock_retriever_instance),
    )

    await mcp_server._initialize_retriever()

    init_vector_db_mock.assert_not_called()
    assert mcp_server._retriever is mock_retriever_instance


@pytest.mark.asyncio
async def test_initialize_retriever_creates_collection_when_missing(monkeypatch):
    """Initialize retriever by creating a new collection if absent."""
    config = DEFAULT_CONFIG.update(collection_name="new_collection")
    docs = [{"id": "d1", "text": "x", "metadata": {"source": "test"}}]
    mock_collection = MagicMock()
    mock_retriever_instance = MagicMock()

    mcp_server._retriever = None
    mcp_server._config = DEFAULT_CONFIG

    monkeypatch.setattr(
        mcp_server, "_load_initial_config", MagicMock(return_value=config)
    )
    monkeypatch.setattr(
        mcp_server, "list_existing_collections", MagicMock(return_value=[])
    )
    monkeypatch.setattr(mcp_server, "get_sample_documents", lambda: docs)
    init_vector_db_mock = MagicMock(return_value=mock_collection)
    monkeypatch.setattr(mcp_server, "initialize_vector_db", init_vector_db_mock)
    open_collection_mock = MagicMock()
    monkeypatch.setattr(mcp_server, "open_collection", open_collection_mock)
    monkeypatch.setattr(
        mcp_server,
        "HybridRetriever",
        MagicMock(return_value=mock_retriever_instance),
    )

    await mcp_server._initialize_retriever()

    init_vector_db_mock.assert_called_once()
    open_collection_mock.assert_not_called()
    assert mcp_server._retriever is mock_retriever_instance


@pytest.mark.asyncio
async def test_main_uses_stdio_transport(monkeypatch):
    """main() runs stdio transport when configured."""
    monkeypatch.setattr(mcp_server, "_initialize_retriever", AsyncMock())
    monkeypatch.setattr(mcp_server, "_resolve_transport", lambda: "stdio")
    stdio_mock = AsyncMock()
    http_mock = AsyncMock()
    monkeypatch.setattr(mcp_server.mcp, "run_stdio_async", stdio_mock)
    monkeypatch.setattr(mcp_server.mcp, "run_streamable_http_async", http_mock)

    await mcp_server.main()

    stdio_mock.assert_awaited_once()
    http_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_main_uses_http_transport(monkeypatch):
    """main() runs streamable HTTP transport when configured."""
    monkeypatch.setattr(mcp_server, "_initialize_retriever", AsyncMock())
    monkeypatch.setattr(mcp_server, "_resolve_transport", lambda: "streamable-http")
    stdio_mock = AsyncMock()
    http_mock = AsyncMock()
    monkeypatch.setattr(mcp_server.mcp, "run_stdio_async", stdio_mock)
    monkeypatch.setattr(mcp_server.mcp, "run_streamable_http_async", http_mock)

    await mcp_server.main()

    http_mock.assert_awaited_once()
    stdio_mock.assert_not_awaited()


def test_load_initial_config_rejects_invalid_collection_name(monkeypatch):
    """Invalid COLLECTION_NAME env var raises ValueError before Chroma startup."""
    monkeypatch.setenv("COLLECTION_NAME", "my.col")  # dots not allowed

    with pytest.raises(ValueError, match="Invalid COLLECTION_NAME"):
        mcp_server._load_initial_config()


def test_load_initial_config_accepts_valid_collection_name(monkeypatch):
    """Valid COLLECTION_NAME env var is applied to the config."""
    monkeypatch.setenv("COLLECTION_NAME", "valid_col_1")

    config = mcp_server._load_initial_config()

    assert config.collection_name == "valid_col_1"


@pytest.mark.asyncio
async def test_query_knowledge_base_uses_cache_on_hit(mock_retriever):
    """query_knowledge_base serves from L1 cache on a hit without calling retrieve()."""
    cached_raw = [
        {
            "id": "cached1",
            "text": "Cached text",
            "metadata": {"source": "cached.txt"},
            "score": 0.90,
        }
    ]
    mock_cache = MagicMock()
    mock_cache.get.return_value = cached_raw  # cache hit

    mcp_server._retriever = mock_retriever
    mcp_server._config = DEFAULT_CONFIG
    mcp_server._cache = mock_cache

    result = await mcp_server.query_knowledge_base("cached query")

    mock_retriever.retrieve.assert_not_called()
    mock_cache.get.assert_called_once()
    assert result["total_results"] == 1
    assert result["results"][0]["id"] == "cached1"
    assert result["results"][0]["source"] == "cached.txt"


@pytest.mark.asyncio
async def test_query_knowledge_base_populates_cache_on_miss(mock_retriever):
    """query_knowledge_base calls retrieve() on a cache miss and writes the result."""
    mock_cache = MagicMock()
    mock_cache.get.return_value = None  # cache miss

    mcp_server._retriever = mock_retriever
    mcp_server._config = DEFAULT_CONFIG
    mcp_server._cache = mock_cache

    result = await mcp_server.query_knowledge_base("miss query")

    mock_retriever.retrieve.assert_called_once()
    mock_cache.set.assert_called_once()
    assert result["total_results"] == 1


@pytest.mark.asyncio
async def test_query_knowledge_base_fail_open_on_cache_error(mock_retriever):
    """query_knowledge_base falls back to retrieve() when the cache read raises."""
    mock_cache = MagicMock()
    mock_cache.get.side_effect = RuntimeError("Redis connection lost")

    mcp_server._retriever = mock_retriever
    mcp_server._config = DEFAULT_CONFIG
    mcp_server._cache = mock_cache

    result = await mcp_server.query_knowledge_base("error query")

    mock_retriever.retrieve.assert_called_once()
    assert result["total_results"] == 1


def test_build_corpus_version_token_with_retriever(mock_retriever):
    """_build_corpus_version_token reads collection count from the retriever."""
    mock_retriever.collection.count.return_value = 42
    mcp_server._retriever = mock_retriever
    mcp_server._cache_generation = 1

    token = mcp_server._build_corpus_version_token()

    assert token == "gen1.n42"


def test_build_corpus_version_token_without_retriever():
    """_build_corpus_version_token falls back gracefully when retriever is None."""
    mcp_server._retriever = None
    mcp_server._cache_generation = 0

    token = mcp_server._build_corpus_version_token()

    assert token == "gen0.n0"


@pytest.mark.asyncio
async def test_main_graceful_shutdown_calls_mcp_shutdown_and_clears_cache(monkeypatch):
    """Simulate a shutdown signal and ensure mcp.shutdown is called and cache cleared."""
    # Arrange
    monkeypatch.setattr(mcp_server, "_initialize_retriever", AsyncMock())
    monkeypatch.setattr(mcp_server, "_resolve_transport", lambda: "stdio")

    loop = asyncio.get_running_loop()
    # Replace add_signal_handler to invoke handler immediately to simulate SIGINT/SIGTERM
    monkeypatch.setattr(loop, "add_signal_handler", lambda sig, handler: handler())

    # run_stdio_async never completes so the server would run until shutdown is triggered
    async def never_complete():
        await asyncio.Event().wait()

    monkeypatch.setattr(mcp_server.mcp, "run_stdio_async", never_complete)

    # Provide an async shutdown method to be called by main()
    shutdown_mock = AsyncMock()
    setattr(mcp_server.mcp, "shutdown", shutdown_mock)

    # Populate cache and retriever so cleanup can be observed
    mcp_server._cache = MagicMock()
    mcp_server._retriever = MagicMock()

    # Act
    await mcp_server.main()

    # Assert
    shutdown_mock.assert_awaited_once()
    mcp_server._cache.clear.assert_called_once()
    assert mcp_server._retriever is None


@pytest.mark.asyncio
async def test_main_graceful_shutdown_uses_stop_when_shutdown_missing(monkeypatch):
    """If mcp.shutdown missing, main() should try fallback method like stop()."""
    # Arrange
    monkeypatch.setattr(mcp_server, "_initialize_retriever", AsyncMock())
    monkeypatch.setattr(mcp_server, "_resolve_transport", lambda: "stdio")

    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "add_signal_handler", lambda sig, handler: handler())

    async def never_complete():
        await asyncio.Event().wait()

    monkeypatch.setattr(mcp_server.mcp, "run_stdio_async", never_complete)

    # Ensure 'shutdown' is not callable; provide 'stop' as the fallback async method
    try:
        delattr(mcp_server.mcp, "shutdown")
    except Exception:
        pass
    stop_mock = AsyncMock()
    setattr(mcp_server.mcp, "stop", stop_mock)

    mcp_server._cache = MagicMock()
    mcp_server._retriever = MagicMock()

    # Act
    await mcp_server.main()

    # Assert
    stop_mock.assert_awaited_once()
    mcp_server._cache.clear.assert_called_once()
    assert mcp_server._retriever is None
