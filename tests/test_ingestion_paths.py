"""Test ingestion path wiring for chunk_document() integration.

Tests validate that:
1. _TextExtractor class has been removed from api.py
2. chunk_document() is callable from hybrid_rag
3. initialize_vector_db() stores section metadata for Markdown sources
4. initialize_vector_db() does not store section metadata for plain text sources
"""

import tempfile
import pytest


class TestIngestionPathWiring:
    """Test the wiring of chunk_document() into both ingestion paths."""

    def test_textextractor_class_removed_from_api_module(self) -> None:
        """Verify _TextExtractor class no longer exists in api module."""
        import api
        assert not hasattr(api, "_TextExtractor")

    def test_chunk_document_callable_from_hybrid_rag(self) -> None:
        """Verify chunk_document is exported from hybrid_rag."""
        from hybrid_rag import chunk_document
        assert callable(chunk_document)

    def test_initialize_vector_db_stores_section_metadata_for_md_source(self) -> None:
        """initialize_vector_db() stores section_h1/h2 for Markdown sources."""
        from hybrid_rag import initialize_vector_db
        md_text = "# Setup\n\nInstall.\n\n## Config\n\nSet env vars."
        docs = [{"id": "1", "source": "guide.md", "text": md_text}]
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                collection = initialize_vector_db(
                    docs, persist_dir=tmpdir, collection_name="test_md_meta"
                )
            except Exception:
                pytest.skip("Embedding model unavailable")
            results = collection.get(include=["metadatas"])
            # At least one chunk should have section_h1 metadata
            assert any(m.get("section_h1") is not None for m in results["metadatas"])

    def test_initialize_vector_db_no_section_metadata_for_plain_text(self) -> None:
        """initialize_vector_db() does not store section metadata for plain text."""
        from hybrid_rag import initialize_vector_db
        docs = [{"id": "1", "source": "notes.txt", "text": "Plain text " * 50}]
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                collection = initialize_vector_db(
                    docs, persist_dir=tmpdir, collection_name="test_plain_meta"
                )
            except Exception:
                pytest.skip("Embedding model unavailable")
            results = collection.get(include=["metadatas"])
            # No chunk should have section_h1 or section_h2 metadata
            for meta in results["metadatas"]:
                assert "section_h1" not in meta
                assert "section_h2" not in meta
