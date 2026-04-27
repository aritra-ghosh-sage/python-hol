"""Unit tests for collection name validation and sanitization utilities."""

import pytest

from hybrid_rag.exceptions import VectorDBError
from hybrid_rag.vectordb import is_valid_collection_name, open_collection, sanitize_collection_name


def test_is_valid_collection_name_accepts_minimum_length() -> None:
    assert is_valid_collection_name("abcdef") is True


def test_is_valid_collection_name_accepts_maximum_length() -> None:
    assert is_valid_collection_name("a" * 20) is True


def test_is_valid_collection_name_rejects_too_short() -> None:
    assert is_valid_collection_name("ab") is False


def test_is_valid_collection_name_rejects_too_long() -> None:
    assert is_valid_collection_name("a" * 21) is False


def test_is_valid_collection_name_accepts_underscores_hyphens() -> None:
    assert is_valid_collection_name("my_col-1") is True


def test_is_valid_collection_name_rejects_spaces() -> None:
    assert is_valid_collection_name("has space") is False


def test_is_valid_collection_name_rejects_periods() -> None:
    assert is_valid_collection_name("my.col") is False


def test_sanitize_replaces_invalid_chars() -> None:
    assert sanitize_collection_name("hello world!") == "hello_world_"


def test_sanitize_pads_short_names() -> None:
    assert sanitize_collection_name("ab") == "ab____"


def test_sanitize_truncates_long_names() -> None:
    assert len(sanitize_collection_name("a" * 25)) == 20


def test_sanitize_preserves_valid_names() -> None:
    assert sanitize_collection_name("my_col") == "my_col"


def test_open_collection_raises_for_nonexistent(tmp_path) -> None:
    with pytest.raises(VectorDBError):
        open_collection(str(tmp_path / "nonexistent_path_xyz_abc"), "missing_col_123")
