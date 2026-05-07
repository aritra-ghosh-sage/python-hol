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


async def test_query_knowledge_base_empty_query():
    """Test that empty queries are rejected."""
    mcp_server._retriever = MagicMock()

    with pytest.raises(ValueError, match="Query must be between 1 and 500 characters"):
        await mcp_server.query_knowledge_base("")


async def test_query_knowledge_base_oversized_query():
    """Test that oversized queries are rejected."""
    mcp_server._retriever = MagicMock()

    with pytest.raises(ValueError, match="Query must be between 1 and 500 characters"):
        await mcp_server.query_knowledge_base("x" * 501)


async def test_query_knowledge_base_not_initialized():
    """Test that querying without initialization raises error."""
    mcp_server._retriever = None

    with pytest.raises(ValueError, match="Retriever not initialized"):
        await mcp_server.query_knowledge_base("test")


async def test_get_config():
    """Test that get_config returns current configuration."""
    mcp_server._config = DEFAULT_CONFIG

    result = await mcp_server.get_config()

    assert isinstance(result, dict)
    assert "semantic_top_k" in result
    assert "keyword_top_k" in result
    assert "final_top_k" in result
    assert "enable_rerank" in result


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


async def test_initialize_retriever_uses_open_collection_when_collection_exists(monkeypatch):
    """Initialize retriever from an existing collection."""
    config = DEFAULT_CONFIG.update(collection_name="existing_collection")
    mock_collection = MagicMock()
    mock_retriever_instance = MagicMock()

    mcp_server._retriever = None
    mcp_server._config = DEFAULT_CONFIG

    monkeypatch.setattr(
        mcp_server, "resolve_startup_config", MagicMock(return_value=config)
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


async def test_initialize_retriever_creates_collection_when_missing(monkeypatch):
    """Initialize retriever by creating a new collection if absent."""
    config = DEFAULT_CONFIG.update(collection_name="new_collection")
    docs = [{"id": "d1", "text": "x", "metadata": {"source": "test"}}]
    mock_collection = MagicMock()
    mock_retriever_instance = MagicMock()

    mcp_server._retriever = None
    mcp_server._config = DEFAULT_CONFIG

    monkeypatch.setattr(
        mcp_server, "resolve_startup_config", MagicMock(return_value=config)
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


def test_resolve_startup_config_rejects_invalid_collection_name(monkeypatch):
    """Invalid COLLECTION_NAME env var raises ValueError before Chroma startup."""
    monkeypatch.setenv("COLLECTION_NAME", "my.col")  # dots not allowed

    with pytest.raises(ValueError, match="Invalid COLLECTION_NAME"):
        mcp_server.resolve_startup_config(mcp_server.KNOWLEDGE_DB_DIRECTORY)


def test_resolve_startup_config_accepts_valid_collection_name(monkeypatch):
    """Valid COLLECTION_NAME env var is applied when the collection exists in ChromaDB."""
    monkeypatch.setenv("COLLECTION_NAME", "valid_col_1")
    monkeypatch.setattr(
        "hybrid_rag.persistence.list_existing_collections", lambda _: ["valid_col_1"]
    )

    config = mcp_server.resolve_startup_config(mcp_server.KNOWLEDGE_DB_DIRECTORY)

    assert config.collection_name == "valid_col_1"


def test_resolve_startup_config_falls_back_when_collection_missing(monkeypatch):
    """COLLECTION_NAME not in ChromaDB is ignored; result is the config.json-level fallback."""
    monkeypatch.setenv("COLLECTION_NAME", "missing_col")
    monkeypatch.setattr(
        "hybrid_rag.persistence.list_existing_collections", lambda _: []
    )

    config = mcp_server.resolve_startup_config(mcp_server.KNOWLEDGE_DB_DIRECTORY)

    # Both config.json's collection and the env var collection are absent from
    # the mocked empty list, so the result is DEFAULT_CONFIG.
    assert config == DEFAULT_CONFIG


def test_resolve_startup_config_uses_disk_config_when_collection_verified(monkeypatch):
    """config.json is used when its collection_name exists in ChromaDB and no env var is set."""
    monkeypatch.delenv("COLLECTION_NAME", raising=False)
    monkeypatch.setattr(
        "hybrid_rag.persistence.list_existing_collections", lambda _: ["rag_collection"]
    )
    monkeypatch.setattr(
        "hybrid_rag.persistence.load_config_from_disk",
        lambda _: DEFAULT_CONFIG.update(semantic_weight=0.9, keyword_weight=0.1),
    )

    config = mcp_server.resolve_startup_config(mcp_server.KNOWLEDGE_DB_DIRECTORY)

    assert config.collection_name == "rag_collection"
    assert config.semantic_weight == 0.9


def test_resolve_startup_config_writes_back_env_var_collection_to_disk(monkeypatch):
    """Applying COLLECTION_NAME env var also persists the collection_name to config.json."""
    monkeypatch.setenv("COLLECTION_NAME", "env_coll_1")
    monkeypatch.setattr(
        "hybrid_rag.persistence.list_existing_collections", lambda _: ["env_coll_1"]
    )
    saved = []
    monkeypatch.setattr(
        "hybrid_rag.persistence.save_config_to_disk",
        lambda cfg, _dir: saved.append(cfg.collection_name),
    )

    config = mcp_server.resolve_startup_config(mcp_server.KNOWLEDGE_DB_DIRECTORY)

    assert config.collection_name == "env_coll_1"
    assert saved == ["env_coll_1"]


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


async def test_main_surfaces_mcp_task_exception(monkeypatch):
    """main() should propagate exceptions from the MCP transport task."""
    monkeypatch.setattr(mcp_server, "_initialize_retriever", AsyncMock())
    monkeypatch.setattr(mcp_server, "_resolve_transport", lambda: "stdio")

    loop = asyncio.get_running_loop()
    monkeypatch.setattr(
        type(loop), "add_signal_handler", lambda self, sig, handler: None
    )

    async def raise_error():
        raise RuntimeError("transport crashed")

    monkeypatch.setattr(mcp_server.mcp, "run_stdio_async", raise_error)

    with pytest.raises(RuntimeError, match="transport crashed"):
        await mcp_server.main()


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
    """build_corpus_version_token reads collection count from the retriever."""
    from hybrid_rag.cache_utils import build_corpus_version_token

    mock_retriever.collection.count.return_value = 42

    token = build_corpus_version_token(mock_retriever, cache_generation=1)

    assert token == "gen1.n42"


def test_build_corpus_version_token_without_retriever():
    """build_corpus_version_token falls back gracefully when retriever is None."""
    from hybrid_rag.cache_utils import build_corpus_version_token

    token = build_corpus_version_token(None, cache_generation=0)

    assert token == "gen0.n0"


async def test_main_graceful_shutdown_calls_mcp_shutdown_and_clears_cache(monkeypatch):
    """Simulate a shutdown signal and ensure mcp.shutdown is called and cache cleared."""
    # Arrange
    monkeypatch.setattr(mcp_server, "_initialize_retriever", AsyncMock())
    monkeypatch.setattr(mcp_server, "_resolve_transport", lambda: "stdio")

    loop = asyncio.get_running_loop()
    # Replace add_signal_handler to invoke handler immediately to simulate SIGINT/SIGTERM
    monkeypatch.setattr(type(loop), "add_signal_handler", lambda self, sig, handler: handler())

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


async def test_main_graceful_shutdown_uses_stop_when_shutdown_missing(monkeypatch):
    """If mcp.shutdown missing, main() should try fallback method like stop()."""
    # Arrange
    monkeypatch.setattr(mcp_server, "_initialize_retriever", AsyncMock())
    monkeypatch.setattr(mcp_server, "_resolve_transport", lambda: "stdio")

    loop = asyncio.get_running_loop()
    monkeypatch.setattr(type(loop), "add_signal_handler", lambda self, sig, handler: handler())

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


class TestResolveTransport:
    """Unit tests for _resolve_transport."""

    def test_unset_env_defaults_to_stdio(self, monkeypatch):
        monkeypatch.delenv("MCP_TRANSPORT", raising=False)
        assert mcp_server._resolve_transport() == "stdio"

    def test_http_value_returns_streamable_http(self, monkeypatch):
        for value in ("http", "streamable-http", "streamable_http", "HTTP", "Streamable-HTTP"):
            monkeypatch.setenv("MCP_TRANSPORT", value)
            assert mcp_server._resolve_transport() == "streamable-http"

    def test_invalid_value_raises_value_error(self, monkeypatch):
        monkeypatch.setenv("MCP_TRANSPORT", "grpc")
        with pytest.raises(ValueError, match="Unsupported MCP_TRANSPORT"):
            mcp_server._resolve_transport()
