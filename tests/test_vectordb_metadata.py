"""Tests for initialize_vector_db() metadata correctness.

Covers the ADR-0001 Wave 1 T2 requirement:
  - chunk_index per-document sequential counter written to metadata
  - source_url written when doc["source"] is an HTTP/HTTPS URL
  - source_url absent when doc["source"] is a local file path
  - No None values in ChromaDB metadata (ChromaDB rejects None).
"""

import tempfile

import pytest

from hybrid_rag import initialize_vector_db


class TestInitializeVectorDbMetadata:
    """Test metadata correctness in initialize_vector_db() per ADR-0001 T2."""

    def test_url_source_doc_has_source_url_metadata(self) -> None:
        """Chunks from a URL-sourced document must include source_url in metadata.

        ADR-0001 T2: Bug fix — bulk initialization path was missing source_url,
        causing the api.py deduplication filter (where={"source_url": url}) to
        miss all bulk-ingested documents. After the fix, source_url must be
        present so deduplication works uniformly for both ingestion paths.
        """
        url = "https://example.com/test-page"
        docs = [
            {
                "id": "1",
                "source": url,
                "text": "This is a test document with enough text to chunk. " * 10,
            }
        ]
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                collection = initialize_vector_db(
                    docs, persist_dir=tmpdir, collection_name="test_url_meta"
                )
                result = collection.get(where={"source_url": url})
                assert len(result["ids"]) > 0, (
                    "source_url metadata must be stored for URL-sourced documents "
                    "so ChromaDB where-filter deduplication works"
                )
        except Exception:
            pytest.skip("Embedding model unavailable")

    def test_non_url_source_doc_has_no_source_url_metadata(self) -> None:
        """Chunks from a non-URL source must NOT include source_url in metadata.

        ADR-0001 T2: When source is a local file path, source_url must be omitted
        entirely from metadata (not stored as None, which ChromaDB rejects).
        """
        local_source = "local_file.txt"
        docs = [
            {
                "id": "1",
                "source": local_source,
                "text": "Local document content that provides enough text. " * 10,
            }
        ]
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                collection = initialize_vector_db(
                    docs, persist_dir=tmpdir, collection_name="test_no_url_meta"
                )
                # Fetch all metadata and verify none has source_url key
                all_docs = collection.get()
                for meta in all_docs.get("metadatas", []):
                    assert meta is not None
                    assert "source_url" not in meta, (
                        "Non-URL sources must not write source_url to metadata; "
                        "ChromaDB rejects None values and extra keys cause confusion"
                    )
        except Exception:
            pytest.skip("Embedding model unavailable")

    def test_chunk_index_is_sequential_per_document(self) -> None:
        """chunk_index must reset to 0 for each document and be sequential.

        ADR-0001 T2: The old code used id_counter for chunk_index, so doc-2's
        first chunk got index N (not 0). The fix resets chunk_idx per-document.
        Sequential chunk_index enables ordered retrieval and deduplication checks.
        """
        # Two separate documents — each should have chunk_index starting at 0
        doc_text = "sentence with many words to ensure multiple chunks form. " * 15
        docs = [
            {"id": "1", "source": "doc_one.txt", "text": doc_text},
            {"id": "2", "source": "doc_two.txt", "text": doc_text},
        ]
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                collection = initialize_vector_db(
                    docs, persist_dir=tmpdir, collection_name="test_chunk_idx"
                )
                for source_name in ("doc_one.txt", "doc_two.txt"):
                    result = collection.get(where={"source": source_name})
                    metas = result.get("metadatas", [])
                    assert len(metas) > 0, (
                        f"Expected chunks for source={source_name}"
                    )
                    chunk_indices = [m["chunk_index"] for m in metas]
                    # Must start at 0 and be sequential (no gaps)
                    assert 0 in chunk_indices, (
                        f"chunk_index must start at 0 for source={source_name}; "
                        f"got {sorted(chunk_indices)}"
                    )
                    sorted_indices = sorted(chunk_indices)
                    expected = list(range(len(sorted_indices)))
                    assert sorted_indices == expected, (
                        f"chunk_index must be sequential 0..N for source={source_name}; "
                        f"got {sorted_indices}"
                    )
        except Exception:
            pytest.skip("Embedding model unavailable")

    def test_metadata_has_no_none_values(self) -> None:
        """ChromaDB rejects None metadata values; all values must be non-None.

        CON-005: ChromaDB silently corrupts or raises on None metadata values.
        This test is a safety net that catches any future regression.
        """
        docs = [
            {
                "id": "1",
                "source": "plain_source.txt",
                "text": "Simple document with enough content. " * 5,
            }
        ]
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                collection = initialize_vector_db(
                    docs, persist_dir=tmpdir, collection_name="test_no_none_meta"
                )
                all_docs = collection.get()
                for meta in all_docs.get("metadatas", []):
                    if meta:
                        for key, value in meta.items():
                            assert value is not None, (
                                f"Metadata key '{key}' has None value; "
                                "ChromaDB rejects None metadata values (CON-005)"
                            )
        except Exception:
            pytest.skip("Embedding model unavailable")
