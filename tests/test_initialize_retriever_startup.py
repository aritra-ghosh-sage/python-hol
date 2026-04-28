"""Unit tests for initialize_retriever() startup path branches.

Tests the three branches of initialize_retriever() in api.py:
  1. Existing collection — open_collection() is called; initialize_vector_db() is not.
  2. New collection — initialize_vector_db() is called; open_collection() is not.
  3. open_collection() raises VectorDBError — the exception propagates unchanged.

All tests use monkeypatching to avoid loading any real ChromaDB or
sentence-transformer model. Each test completes in <10 ms.
"""

from unittest.mock import MagicMock

import pytest

import api
from hybrid_rag import HybridRetrieverConfig, VectorDBError

# ---------------------------------------------------------------------------
# Shared sample data used by the new-collection test class.
# ---------------------------------------------------------------------------
_SAMPLE_DOCS = [{"id": "doc1", "text": "sample", "metadata": {"source": "test"}}]


# ---------------------------------------------------------------------------
# Shared setup helpers
# ---------------------------------------------------------------------------


def _reset_api_state() -> None:
    """Reset mutable api globals to a clean pre-startup state."""
    api._retriever = None
    api._config = None


def _patch_common(monkeypatch: pytest.MonkeyPatch, tmp_path_str: str) -> None:
    """Apply patches common to all three test classes.

    Patches:
    - api.KNOWLEDGE_DB_DIRECTORY  → tmp_path_str (avoids touching the real DB)
    - api.HybridRetriever         → MagicMock (no model download)
    - api._build_corpus_version_token → returns "gen0.n0" (avoids real DB call)
    """
    monkeypatch.setattr("api.KNOWLEDGE_DB_DIRECTORY", tmp_path_str)
    monkeypatch.setattr("api.HybridRetriever", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(
        "api._build_corpus_version_token", lambda: "gen0.n0"
    )


# ---------------------------------------------------------------------------
# Test class 1: existing collection branch
# ---------------------------------------------------------------------------


class TestInitializeRetrieverExistingCollection:
    """initialize_retriever() uses open_collection() when the collection exists."""

    def test_open_collection_called_once_when_collection_exists(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """open_collection called exactly once; initialize_vector_db never called."""
        _reset_api_state()

        # Establish a deterministic config so collection_name is predictable.
        api._config = HybridRetrieverConfig()
        expected_collection_name = api._config.collection_name

        _patch_common(monkeypatch, str(tmp_path))

        # Collection is already present.
        monkeypatch.setattr(
            "api.list_existing_collections",
            MagicMock(return_value=[expected_collection_name]),
        )

        mock_open_collection = MagicMock(return_value=MagicMock())
        monkeypatch.setattr("api.open_collection", mock_open_collection)

        mock_init_vector_db = MagicMock()
        monkeypatch.setattr("api.initialize_vector_db", mock_init_vector_db)

        api.initialize_retriever()

        mock_open_collection.assert_called_once_with(
            persist_dir=str(tmp_path),
            collection_name=expected_collection_name,
        )
        assert mock_init_vector_db.call_count == 0

    def test_retriever_is_not_none_after_existing_collection_init(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """api._retriever is populated after initialization with existing collection."""
        _reset_api_state()

        api._config = HybridRetrieverConfig()
        expected_collection_name = api._config.collection_name

        _patch_common(monkeypatch, str(tmp_path))

        monkeypatch.setattr(
            "api.list_existing_collections",
            MagicMock(return_value=[expected_collection_name]),
        )
        monkeypatch.setattr("api.open_collection", MagicMock(return_value=MagicMock()))
        monkeypatch.setattr("api.initialize_vector_db", MagicMock())

        api.initialize_retriever()

        assert api._retriever is not None


# ---------------------------------------------------------------------------
# Test class 2: new collection branch
# ---------------------------------------------------------------------------


class TestInitializeRetrieverNewCollection:
    """initialize_retriever() seeds with sample docs when collection is absent."""

    def test_initialize_vector_db_called_once_when_collection_absent(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """initialize_vector_db called exactly once; open_collection never called."""
        _reset_api_state()

        api._config = HybridRetrieverConfig()
        expected_collection_name = api._config.collection_name

        _patch_common(monkeypatch, str(tmp_path))

        # No existing collections.
        monkeypatch.setattr(
            "api.list_existing_collections",
            MagicMock(return_value=[]),
        )

        mock_open_collection = MagicMock()
        monkeypatch.setattr("api.open_collection", mock_open_collection)

        mock_init_vector_db = MagicMock(return_value=MagicMock())
        monkeypatch.setattr("api.initialize_vector_db", mock_init_vector_db)

        monkeypatch.setattr(
            "api.get_sample_documents",
            MagicMock(return_value=_SAMPLE_DOCS),
        )

        api.initialize_retriever()

        mock_init_vector_db.assert_called_once_with(
            _SAMPLE_DOCS,
            persist_dir=str(tmp_path),
            collection_name=expected_collection_name,
        )
        assert mock_open_collection.call_count == 0

    def test_retriever_is_not_none_after_new_collection_init(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """api._retriever is populated after initialization with new collection."""
        _reset_api_state()

        api._config = HybridRetrieverConfig()

        _patch_common(monkeypatch, str(tmp_path))

        monkeypatch.setattr(
            "api.list_existing_collections",
            MagicMock(return_value=[]),
        )
        monkeypatch.setattr("api.open_collection", MagicMock())
        monkeypatch.setattr(
            "api.initialize_vector_db", MagicMock(return_value=MagicMock())
        )
        monkeypatch.setattr(
            "api.get_sample_documents",
            MagicMock(return_value=_SAMPLE_DOCS),
        )

        api.initialize_retriever()

        assert api._retriever is not None


# ---------------------------------------------------------------------------
# Test class 3: open_collection() raises VectorDBError
# ---------------------------------------------------------------------------


class TestInitializeRetrieverOpenCollectionError:
    """VectorDBError raised by open_collection() propagates out unchanged."""

    def test_vector_db_error_propagates_from_open_collection(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """initialize_retriever() re-raises VectorDBError from open_collection()."""
        _reset_api_state()

        api._config = HybridRetrieverConfig()
        expected_collection_name = api._config.collection_name

        _patch_common(monkeypatch, str(tmp_path))

        monkeypatch.setattr(
            "api.list_existing_collections",
            MagicMock(return_value=[expected_collection_name]),
        )
        monkeypatch.setattr(
            "api.open_collection",
            MagicMock(side_effect=VectorDBError("simulated corrupt collection")),
        )
        monkeypatch.setattr("api.initialize_vector_db", MagicMock())

        with pytest.raises(VectorDBError, match="simulated corrupt collection"):
            api.initialize_retriever()
