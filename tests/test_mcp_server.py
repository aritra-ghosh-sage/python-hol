"""Tests for the MCP server."""

import pytest
from mcp.server.fastmcp import FastMCP
from unittest.mock import AsyncMock, MagicMock, patch

import mcp_server
from hybrid_rag import HybridRetrieverConfig, DEFAULT_CONFIG


@pytest.fixture
def mock_retriever():
    """Create a mock retriever."""
    retriever = MagicMock()
    retriever.retrieve.return_value = [
        {
            "query": "test query",
            "metadata": {"source": "test_doc.txt"},
            "score": 0.85,
        }
    ]
    return retriever


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
    assert result["results"][0]["score"] == 0.85


@pytest.mark.asyncio
async def test_query_knowledge_base_filters_low_scores(mock_retriever):
    """Test that results below min_score_threshold are filtered."""
    mock_retriever.retrieve.return_value = [
        {"query": "test", "metadata": {}, "score": 0.85},
        {"query": "test", "metadata": {}, "score": 0.30},  # Below threshold
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
