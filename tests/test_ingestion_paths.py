"""Test ingestion path wiring for chunk_document() integration.

Tests validate that:
1. chunk_document() is callable from hybrid_rag
2. initialize_vector_db() stores section metadata for Markdown sources
3. initialize_vector_db() does not store section metadata for plain text sources
4. URL/HTML ingestion stores section_h1/h2 heading metadata
"""

import tempfile

import pytest


class TestIngestionPathWiring:
    """Test the wiring of chunk_document() into both ingestion paths."""

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

    def test_url_html_ingestion_stores_heading_metadata(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """URL ingestion of HTML with <h1>/<h2> stores section_h1/h2 in ChromaDB metadata."""
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        import api
        from fastapi.testclient import TestClient

        html_content = (
            "<html><body>"
            "<h1>Overview</h1><p>Introduction paragraph with enough text to chunk.</p>"
            "<h2>Details</h2><p>More detail text here for chunking purposes indeed.</p>"
            "</body></html>"
        )

        mock_http_response = MagicMock()
        mock_http_response.status_code = 200
        mock_http_response.text = html_content

        captured_metadatas: list = []

        class _CapturingCollection:
            def count(self) -> int:
                return 0

            def get(self, where=None, limit=None, include=None):  # noqa: ANN001
                return {"ids": []}

            def add(self, ids, documents, metadatas=None) -> None:  # noqa: ANN001
                if metadatas:
                    captured_metadatas.extend(metadatas)

            def delete(self, ids) -> None:  # noqa: ANN001
                pass

        class _FakeRetriever:
            collection = _CapturingCollection()

            def retrieve(self, query, enable_rerank=None):  # noqa: ANN001
                return []

            def get_embedding_cache_stats(self):  # noqa: ANN201
                return {"hits": 0, "misses": 0, "hit_rate": 0.0, "size": 0, "capacity": 0}

        monkeypatch.setattr(api, "_retriever", _FakeRetriever())
        monkeypatch.setattr(
            api,
            "_config",
            SimpleNamespace(
                semantic_top_k=5,
                keyword_top_k=5,
                final_top_k=5,
                semantic_weight=0.5,
                keyword_weight=0.5,
                enable_rerank=False,
                pre_rerank_top_k=10,
            ),
        )
        monkeypatch.setattr(api, "_corpus_version", "gen0.n0")
        monkeypatch.setattr(api, "_cache_generation", 0)
        monkeypatch.setattr("api.requests.get", lambda *a, **kw: mock_http_response)
        # Bypass DNS resolution in the SSRF guard — this test exercises HTML metadata
        # extraction, not SSRF protection, so return the URL unchanged.
        monkeypatch.setattr("routers.documents._validate_url_for_ssrf", lambda url: url)

        client = TestClient(api.app)
        resp = client.post(
            "/documents",
            json={"source_type": "url", "content": "https://example.com/overview"},
        )

        assert resp.status_code in (200, 201), resp.text
        # At least one chunk should carry section_h1 = "Overview"
        assert any(
            m.get("section_h1") == "Overview" for m in captured_metadatas
        ), f"No section_h1='Overview' found in {captured_metadatas}"


class TestValidateUrlForSsrf:
    """Unit tests for _validate_url_for_ssrf."""

    def test_unspecified_ipv4_raises_400(self) -> None:
        from routers.documents import _validate_url_for_ssrf
        from fastapi import HTTPException
        import pytest
        with pytest.raises(HTTPException) as exc_info:
            _validate_url_for_ssrf("http://0.0.0.0/evil")
        assert exc_info.value.status_code == 400

    def test_userinfo_in_url_raises_400(self) -> None:
        from routers.documents import _validate_url_for_ssrf
        from fastapi import HTTPException
        import pytest
        with pytest.raises(HTTPException) as exc_info:
            _validate_url_for_ssrf("http://user:pass@example.com/path")
        assert exc_info.value.status_code == 400

    def test_userinfo_username_only_raises_400(self) -> None:
        from routers.documents import _validate_url_for_ssrf
        from fastapi import HTTPException
        import pytest
        with pytest.raises(HTTPException) as exc_info:
            _validate_url_for_ssrf("http://user@example.com/path")
        assert exc_info.value.status_code == 400
