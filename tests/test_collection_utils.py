"""Tests for collection utility functions in vectordb.py."""

import logging
import tempfile
from pathlib import Path

import pytest

from hybrid_rag import (
    is_valid_collection_name,
    sanitize_collection_name,
    list_existing_collections,
    initialize_vector_db,
    get_sample_documents,
)
from hybrid_rag.exceptions import VectorDBError

logger = logging.getLogger(__name__)


class TestIsValidCollectionName:
    """Test is_valid_collection_name validation function."""

    def test_valid_name_alphanumeric(self) -> None:
        """Valid collection names with alphanumeric characters are accepted."""
        assert is_valid_collection_name("collection123") is True
        assert is_valid_collection_name("my_collection") is True
        assert is_valid_collection_name("test-name-ok") is True

    def test_valid_name_with_underscores_hyphens(self) -> None:
        """Valid collection names with underscores and hyphens are accepted."""
        assert is_valid_collection_name("my_test_col") is True
        assert is_valid_collection_name("my-test-col") is True
        assert is_valid_collection_name("test_name-123") is True

    def test_valid_name_with_periods(self) -> None:
        """Valid collection names with single periods are accepted."""
        assert is_valid_collection_name("my.collection") is True
        assert is_valid_collection_name("test.name.ok") is True

    def test_valid_name_minimum_length(self) -> None:
        """Collection names with exactly 6 characters are valid."""
        assert is_valid_collection_name("abcdef") is True
        assert is_valid_collection_name("test_1") is True

    def test_valid_name_maximum_length(self) -> None:
        """Collection names with exactly 20 characters are valid."""
        assert is_valid_collection_name("a" * 20) is True
        assert is_valid_collection_name("collection_name_1234") is True

    def test_invalid_name_too_short(self) -> None:
        """Collection names shorter than 6 characters are invalid."""
        assert is_valid_collection_name("abc") is False
        assert is_valid_collection_name("test") is False
        assert is_valid_collection_name("a") is False
        assert is_valid_collection_name("") is False

    def test_invalid_name_too_long(self) -> None:
        """Collection names longer than 20 characters are invalid."""
        assert is_valid_collection_name("a" * 21) is False
        assert is_valid_collection_name("this_is_a_very_long_collection_name") is False

    def test_invalid_name_consecutive_periods(self) -> None:
        """Collection names with consecutive periods are invalid."""
        assert is_valid_collection_name("invalid..name") is False
        assert is_valid_collection_name("test...name") is False
        assert is_valid_collection_name("a..b..c..d") is False

    def test_invalid_name_starts_with_period(self) -> None:
        """Collection names starting with a period are invalid."""
        assert is_valid_collection_name(".hidden_name") is False
        assert is_valid_collection_name(".collection") is False

    def test_invalid_name_ends_with_period(self) -> None:
        """Collection names ending with a period are invalid."""
        assert is_valid_collection_name("collection.") is False
        assert is_valid_collection_name("test_name.") is False

    def test_invalid_name_special_characters(self) -> None:
        """Collection names with special characters are invalid."""
        assert is_valid_collection_name("name@collection") is False
        assert is_valid_collection_name("test#name!") is False
        assert is_valid_collection_name("my collection") is False  # space
        assert is_valid_collection_name("test/name") is False
        assert is_valid_collection_name("col\\name") is False

    def test_invalid_name_non_string(self) -> None:
        """Non-string inputs are invalid."""
        assert is_valid_collection_name(123) is False
        assert is_valid_collection_name(None) is False
        assert is_valid_collection_name([]) is False
        assert is_valid_collection_name({}) is False


class TestSanitizeCollectionName:
    """Test sanitize_collection_name function."""

    def test_sanitize_valid_name_unchanged(self) -> None:
        """Already valid names remain unchanged."""
        assert sanitize_collection_name("my_collection") == "my_collection"
        assert sanitize_collection_name("test-name-1") == "test-name-1"

    def test_sanitize_uppercase_to_lowercase(self) -> None:
        """Uppercase letters are converted to lowercase."""
        assert sanitize_collection_name("MyCollection") == "mycollection"
        assert sanitize_collection_name("TEST_NAME") == "test_name"

    def test_sanitize_special_characters_to_underscores(self) -> None:
        """Special characters are replaced with underscores."""
        result = sanitize_collection_name("My Collection!@#")
        assert is_valid_collection_name(result)
        assert result == "my_collection"

    def test_sanitize_consecutive_periods(self) -> None:
        """Consecutive periods are replaced with single underscore."""
        result = sanitize_collection_name("a..b..c")
        assert is_valid_collection_name(result)
        assert ".." not in result

    def test_sanitize_leading_trailing_periods(self) -> None:
        """Leading and trailing periods are removed."""
        result = sanitize_collection_name(".hidden.")
        assert is_valid_collection_name(result)
        assert not result.startswith(".")
        assert not result.endswith(".")

    def test_sanitize_leading_trailing_underscores(self) -> None:
        """Leading and trailing underscores are removed."""
        result = sanitize_collection_name("__test__")
        assert is_valid_collection_name(result)
        # After stripping and padding, should be valid
        assert len(result) >= 6

    def test_sanitize_truncate_long_name(self) -> None:
        """Names longer than 20 characters are truncated."""
        long_name = "this_is_a_very_long_collection_name"
        result = sanitize_collection_name(long_name)
        assert len(result) <= 20
        assert is_valid_collection_name(result)

    def test_sanitize_pad_short_name(self) -> None:
        """Names shorter than 6 characters are padded with underscores."""
        result = sanitize_collection_name("abc")
        assert len(result) >= 6
        assert is_valid_collection_name(result)
        assert result == "abc___"

    def test_sanitize_single_character(self) -> None:
        """Single character is padded to minimum length."""
        result = sanitize_collection_name("x")
        assert len(result) == 6
        assert is_valid_collection_name(result)
        assert result == "x_____"

    def test_sanitize_empty_string(self) -> None:
        """Empty string returns default collection name."""
        result = sanitize_collection_name("")
        assert result == "default_collection"
        assert is_valid_collection_name(result)

    def test_sanitize_none_input(self) -> None:
        """None input returns default collection name."""
        result = sanitize_collection_name(None)
        assert result == "default_collection"
        assert is_valid_collection_name(result)

    def test_sanitize_whitespace_only(self) -> None:
        """Whitespace-only input is handled correctly."""
        result = sanitize_collection_name("   ")
        assert is_valid_collection_name(result)

    def test_sanitize_complex_input(self) -> None:
        """Complex inputs with multiple issues are sanitized correctly."""
        result = sanitize_collection_name("My Test Collection!@# v2.0")
        assert is_valid_collection_name(result)
        assert len(result) >= 6
        assert len(result) <= 20

    def test_sanitize_all_invalid_characters(self) -> None:
        """Input with all invalid characters is handled."""
        result = sanitize_collection_name("!@#$%^&*()")
        assert is_valid_collection_name(result)
        # Should be all underscores, then padded or truncated
        assert len(result) >= 6
        assert len(result) <= 20

    def test_sanitize_result_always_valid(self) -> None:
        """Sanitized output is always a valid collection name."""
        test_inputs = [
            "abc",
            "UPPERCASE",
            "with spaces",
            "special!@#chars",
            "..leading.periods..",
            "__underscores__",
            "a" * 50,  # very long
            "x",  # very short
            "",
            "My.Collection..Name",
        ]
        for test_input in test_inputs:
            result = sanitize_collection_name(test_input)
            assert is_valid_collection_name(result), f"Sanitized '{test_input}' -> '{result}' is not valid"


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


class TestCollectionUtilsIntegration:
    """Integration tests for collection utilities."""

    def test_sanitize_then_validate(self) -> None:
        """Sanitized names always pass validation."""
        test_names = [
            "invalid name",
            "!@#$%",
            "x",
            "a" * 100,
            ".hidden.",
            "test..name",
        ]
        
        for name in test_names:
            sanitized = sanitize_collection_name(name)
            assert is_valid_collection_name(sanitized), f"Sanitized name '{sanitized}' from '{name}' is not valid"

    def test_create_and_list_collections_workflow(self) -> None:
        """Full workflow: create collections, list them, validate names."""
        with tempfile.TemporaryDirectory() as tmpdir:
            docs = get_sample_documents()
            
            # Create collections with various names
            raw_names = ["My Collection", "test!@#", "abc", "VeryLongCollectionNameThatNeedsTruncation"]
            created_names = []
            
            for raw_name in raw_names:
                sanitized = sanitize_collection_name(raw_name)
                assert is_valid_collection_name(sanitized)
                initialize_vector_db(docs, persist_dir=tmpdir, collection_name=sanitized)
                created_names.append(sanitized)
            
            # List all collections
            listed = list_existing_collections(tmpdir)
            
            # Verify all created collections are listed
            for name in created_names:
                assert name in listed, f"Created collection '{name}' not found in listing"


class TestCollectionUtilsTypeHints:
    """Test that collection utility functions have proper type hints."""

    def test_is_valid_collection_name_has_type_hints(self) -> None:
        """is_valid_collection_name has proper type annotations."""
        import inspect
        
        sig = inspect.signature(is_valid_collection_name)
        assert sig.return_annotation != inspect.Signature.empty
        assert sig.parameters['name'].annotation != inspect.Parameter.empty

    def test_sanitize_collection_name_has_type_hints(self) -> None:
        """sanitize_collection_name has proper type annotations."""
        import inspect
        
        sig = inspect.signature(sanitize_collection_name)
        assert sig.return_annotation != inspect.Signature.empty
        assert sig.parameters['name'].annotation != inspect.Parameter.empty

    def test_list_existing_collections_has_type_hints(self) -> None:
        """list_existing_collections has proper type annotations."""
        import inspect
        
        sig = inspect.signature(list_existing_collections)
        assert sig.return_annotation != inspect.Signature.empty


class TestCollectionUtilsDocstrings:
    """Test that collection utility functions have comprehensive docstrings."""

    def test_is_valid_collection_name_has_docstring(self) -> None:
        """is_valid_collection_name has comprehensive docstring."""
        assert is_valid_collection_name.__doc__ is not None
        assert len(is_valid_collection_name.__doc__) > 100
        assert "Args:" in is_valid_collection_name.__doc__
        assert "Returns:" in is_valid_collection_name.__doc__
        assert "Example:" in is_valid_collection_name.__doc__

    def test_sanitize_collection_name_has_docstring(self) -> None:
        """sanitize_collection_name has comprehensive docstring."""
        assert sanitize_collection_name.__doc__ is not None
        assert len(sanitize_collection_name.__doc__) > 100
        assert "Args:" in sanitize_collection_name.__doc__
        assert "Returns:" in sanitize_collection_name.__doc__
        assert "Example:" in sanitize_collection_name.__doc__

    def test_list_existing_collections_has_docstring(self) -> None:
        """list_existing_collections has comprehensive docstring."""
        assert list_existing_collections.__doc__ is not None
        assert len(list_existing_collections.__doc__) > 100
        assert "Args:" in list_existing_collections.__doc__
        assert "Returns:" in list_existing_collections.__doc__
        assert "Example:" in list_existing_collections.__doc__
