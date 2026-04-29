"""Tests for chunk_text function in hybrid_rag/vectordb.py.

Covers the ADR-0001 Wave 1 T1 requirement: default chunk_size must be 400.
"""

import pytest

from hybrid_rag import chunk_text


class TestChunkTextDefaultChunkSize:
    """Test that chunk_text default chunk_size is 400."""

    def test_chunk_text_default_chunk_size_is_400(self) -> None:
        """Default chunk_size of 400 ensures no chunk exceeds 400 characters.

        ADR-0001 T1: chunk_size default must be 400 (reduced from 500) so that
        chunks fit within the effective token window of BAAI/bge-small-en-v1.5
        (~512 tokens, ~400 characters of technical English prose).
        """
        # 800 characters of text — forces multiple chunks at 400 char default
        long_text = "x" * 800
        chunks = chunk_text(long_text)
        assert len(chunks) > 0, "chunk_text must return at least one chunk"
        for chunk in chunks:
            assert len(chunk) <= 400, (
                f"Default chunk size must be 400; got chunk of length {len(chunk)}"
            )

    def test_chunk_text_explicit_chunk_size_overrides_default(self) -> None:
        """Explicit chunk_size parameter overrides the default.

        When the caller specifies chunk_size=200, all chunks must be at most 200
        characters. This verifies the override path is independent of the default.
        """
        long_text = "word " * 200  # ~1000 characters
        chunks = chunk_text(long_text, chunk_size=200)
        assert len(chunks) > 0, "chunk_text must return at least one chunk"
        for chunk in chunks:
            assert len(chunk) <= 200, (
                f"Explicit chunk_size=200 not honoured; got chunk of length {len(chunk)}"
            )

    def test_chunk_text_returns_list_of_strings(self) -> None:
        """chunk_text always returns a list of strings regardless of input length."""
        chunks = chunk_text("short text")
        assert isinstance(chunks, list)
        assert all(isinstance(c, str) for c in chunks)

    def test_chunk_text_invalid_chunk_size_raises(self) -> None:
        """chunk_size <= 0 raises ValueError (input validation)."""
        with pytest.raises(ValueError):
            chunk_text("some text", chunk_size=0)

    def test_chunk_text_invalid_overlap_raises(self) -> None:
        """chunk_overlap >= chunk_size raises ValueError."""
        with pytest.raises(ValueError):
            chunk_text("some text", chunk_size=100, chunk_overlap=100)
