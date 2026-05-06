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


# ---------------------------------------------------------------------------
# Test class 4: config hydration — env var and config.json precedence
# ---------------------------------------------------------------------------


class TestInitializeRetrieverConfigHydration:
    """initialize_retriever() applies the correct config hydration cascade."""

    def _patch_base(self, monkeypatch: pytest.MonkeyPatch, tmp_path_str: str) -> None:
        _reset_api_state()
        monkeypatch.setattr("api.KNOWLEDGE_DB_DIRECTORY", tmp_path_str)
        monkeypatch.setattr("api.HybridRetriever", MagicMock(return_value=MagicMock()))
        monkeypatch.setattr("api._build_corpus_version_token", lambda: "gen0.n0")
        monkeypatch.setattr("api.open_collection", MagicMock(return_value=MagicMock()))
        monkeypatch.setattr("api.initialize_vector_db", MagicMock(return_value=MagicMock()))
        monkeypatch.setattr("api.get_sample_documents", MagicMock(return_value=[]))
        # list_existing_collections is called twice: once inside resolve_startup_config
        # (hybrid_rag.persistence) and once in api.initialize_retriever for open/create.
        monkeypatch.setattr("api.list_existing_collections", MagicMock(return_value=[]))

    def test_env_var_overrides_disk_config_when_collection_exists(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """COLLECTION_NAME env var wins when its collection exists in ChromaDB."""
        self._patch_base(monkeypatch, str(tmp_path))
        monkeypatch.setenv("COLLECTION_NAME", "env_coll_1")
        from hybrid_rag import DEFAULT_CONFIG
        mock_save = MagicMock()
        monkeypatch.setattr(
            "hybrid_rag.persistence.list_existing_collections",
            MagicMock(return_value=["env_coll_1", "rag_collection"]),
        )
        monkeypatch.setattr(
            "hybrid_rag.persistence.load_config_from_disk",
            MagicMock(return_value=DEFAULT_CONFIG),
        )
        monkeypatch.setattr("hybrid_rag.persistence.save_config_to_disk", mock_save)

        api.initialize_retriever()

        assert api._config.collection_name == "env_coll_1"
        mock_save.assert_called_once()
        assert mock_save.call_args[0][0].collection_name == "env_coll_1"

    def test_env_var_ignored_when_collection_absent(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """COLLECTION_NAME env var is ignored when its collection is not in ChromaDB."""
        self._patch_base(monkeypatch, str(tmp_path))
        monkeypatch.setenv("COLLECTION_NAME", "ghost_col_1")
        monkeypatch.setattr(
            "hybrid_rag.persistence.list_existing_collections",
            MagicMock(return_value=["rag_collection"]),
        )
        monkeypatch.setattr(
            "hybrid_rag.persistence.load_config_from_disk", MagicMock(return_value=None)
        )

        api.initialize_retriever()

        assert api._config.collection_name == "rag_collection"

    def test_disk_config_used_when_collection_verified_and_no_env_var(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """config.json collection_name is used when verified and no env var is set."""
        self._patch_base(monkeypatch, str(tmp_path))
        monkeypatch.delenv("COLLECTION_NAME", raising=False)
        from hybrid_rag import DEFAULT_CONFIG
        disk_cfg = DEFAULT_CONFIG.update(semantic_weight=0.9, keyword_weight=0.1)
        monkeypatch.setattr(
            "hybrid_rag.persistence.list_existing_collections",
            MagicMock(return_value=["rag_collection"]),
        )
        monkeypatch.setattr(
            "hybrid_rag.persistence.load_config_from_disk", MagicMock(return_value=disk_cfg)
        )

        api.initialize_retriever()

        assert api._config.semantic_weight == 0.9

    def test_default_config_used_when_disk_collection_absent(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """Falls back to DEFAULT_CONFIG when config.json collection is not in ChromaDB."""
        self._patch_base(monkeypatch, str(tmp_path))
        monkeypatch.delenv("COLLECTION_NAME", raising=False)
        from hybrid_rag import DEFAULT_CONFIG, HybridRetrieverConfig
        stale_cfg = HybridRetrieverConfig(collection_name="old_col_99")
        monkeypatch.setattr(
            "hybrid_rag.persistence.list_existing_collections",
            MagicMock(return_value=[]),
        )
        monkeypatch.setattr(
            "hybrid_rag.persistence.load_config_from_disk", MagicMock(return_value=stale_cfg)
        )

        api.initialize_retriever()

        assert api._config == DEFAULT_CONFIG

    def test_invalid_env_var_raises_before_chromadb(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """Invalid COLLECTION_NAME format raises ValueError without touching ChromaDB."""
        self._patch_base(monkeypatch, str(tmp_path))
        monkeypatch.setenv("COLLECTION_NAME", "bad.name!")
        mock_list = MagicMock()
        monkeypatch.setattr("hybrid_rag.persistence.list_existing_collections", mock_list)

        with pytest.raises(ValueError, match="Invalid COLLECTION_NAME"):
            api.initialize_retriever()

        mock_list.assert_not_called()
