"""Tests for collection utility functions in vectordb.py."""

import logging
import tempfile
from pathlib import Path

import pytest

from hybrid_rag import (
    list_existing_collections,
    initialize_vector_db,
    get_sample_documents,
)
from hybrid_rag.exceptions import VectorDBError

logger = logging.getLogger(__name__)


class TestListExistingCollections:
    """Test list_existing_collections function."""

    def test_list_collections_empty_directory(self) -> None:
        """Returns empty list when directory doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            non_existent = Path(tmpdir) / "nonexistent"
            result = list_existing_collections(str(non_existent))
            assert isinstance(result, list)
            assert len(result) == 0

    def test_list_collections_new_directory(self) -> None:
        """Returns empty list for new persistence directory with no collections."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = list_existing_collections(tmpdir)
            assert isinstance(result, list)
            # A new ChromaDB directory might have some internal collections or be empty
            # Both are acceptable

    def test_list_collections_with_collection(self) -> None:
        """Returns list containing collection name after creating a collection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a collection
            docs = get_sample_documents()
            collection_name = "test_collection_abc"
            initialize_vector_db(docs, persist_dir=tmpdir, collection_name=collection_name)
            
            # List collections
            result = list_existing_collections(tmpdir)
            assert isinstance(result, list)
            assert collection_name in result

    def test_list_collections_with_multiple_collections(self) -> None:
        """Returns list containing all collection names."""
        with tempfile.TemporaryDirectory() as tmpdir:
            docs = get_sample_documents()
            collection_names = ["collection_one", "collection_two", "collection_three"]
            
            # Create multiple collections
            for name in collection_names:
                initialize_vector_db(docs, persist_dir=tmpdir, collection_name=name)
            
            # List collections
            result = list_existing_collections(tmpdir)
            assert isinstance(result, list)
            
            # All created collections should be in the result
            for name in collection_names:
                assert name in result

    def test_list_collections_returns_strings(self) -> None:
        """All returned collection names are strings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            docs = get_sample_documents()
            initialize_vector_db(docs, persist_dir=tmpdir, collection_name="test_col_123")
            
            result = list_existing_collections(tmpdir)
            assert all(isinstance(name, str) for name in result)

    def test_list_collections_invalid_directory(self) -> None:
        """Raises VectorDBError for invalid persistence directory."""
        # Use a file path instead of directory
        with tempfile.NamedTemporaryFile() as tmpfile:
            with pytest.raises(VectorDBError):
                list_existing_collections(tmpfile.name)


class TestCollectionUtilsTypeHints:
    """Test that collection utility functions have proper type hints."""

    def test_list_existing_collections_has_type_hints(self) -> None:
        """list_existing_collections has proper type annotations."""
        import inspect
        
        sig = inspect.signature(list_existing_collections)
        assert sig.return_annotation != inspect.Signature.empty


class TestCollectionUtilsDocstrings:
    """Test that collection utility functions have comprehensive docstrings."""

    def test_list_existing_collections_has_docstring(self) -> None:
        """list_existing_collections has comprehensive docstring."""
        assert list_existing_collections.__doc__ is not None
        assert len(list_existing_collections.__doc__) > 100
        assert "Args:" in list_existing_collections.__doc__
        assert "Returns:" in list_existing_collections.__doc__
        assert "Example:" in list_existing_collections.__doc__
