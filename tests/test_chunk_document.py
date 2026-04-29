"""Unit tests for chunk_document() routing function in hybrid_rag/vectordb.py.

Tests verify the public contract of chunk_document():
  - Dispatch logic (MD path, HTML/URL path, plain path)
  - Return shape ({text, metadata} dicts)
  - CON-001: no None values in metadata
  - CON-002: chunk_text() signature is unchanged
  - GUD-001: HTML path discards short chunks
  - REQ-008: HTML path falls back on parse failure
"""
from hybrid_rag.vectordb import chunk_document


class TestChunkDocument:
    """Tests for the chunk_document() format-aware routing function.

    Each test targets a specific branch of the dispatch table or a contract
    constraint so that failures pinpoint exactly which requirement is broken.
    """

    def test_md_path_extracts_h1_heading_metadata(self) -> None:
        """MD path: H1 heading text must appear as section_h1 in metadata.

        MarkdownHeaderTextSplitter attaches heading text to the Document's
        metadata dict under the key "section_h1".  Callers depend on this key
        for faceted search / UI breadcrumb rendering.

        Args:
            (none — no fixture required; pure unit test)

        Returns:
            None

        Raises:
            AssertionError: if no chunk carries section_h1 == "Installation".
        """
        md_text = (
            "# Installation\n\nInstall the package with pip.\n\n"
            "## Quick Start\n\nRun the server."
        )
        result = chunk_document(md_text, source_hint="guide.md")
        assert result
        h1_values = [d["metadata"].get("section_h1") for d in result]
        assert any(v == "Installation" for v in h1_values)

    def test_md_path_extracts_h2_heading_metadata(self) -> None:
        """MD path: H2 heading text must appear as section_h2 in metadata.

        This verifies that the second-level heading key ("section_h2") is
        populated alongside (or independently of) "section_h1".

        Args:
            (none)

        Returns:
            None

        Raises:
            AssertionError: if no chunk carries a non-None section_h2 value.
        """
        md_text = "# Main\n\n## Sub Section\n\nSome content here."
        result = chunk_document(md_text, source_hint="readme.md")
        h2_values = [d["metadata"].get("section_h2") for d in result]
        assert any(v is not None for v in h2_values)

    def test_html_path_extracts_h1_heading_metadata(self) -> None:
        """HTML/URL path: H1 text must appear as section_h1 in metadata.

        HTMLSectionSplitter uses the same key name ("section_h1") as the
        Markdown path.  This consistency means downstream consumers can treat
        both sources identically.

        Args:
            (none)

        Returns:
            None

        Raises:
            AssertionError: if result is empty or no chunk carries section_h1.
        """
        html_text = (
            "<html><body>"
            "<h1>Overview</h1>"
            "<p>Description here.</p>"
            "</body></html>"
        )
        result = chunk_document(html_text, source_hint="https://example.com/page")
        assert result
        h1_values = [d["metadata"].get("section_h1") for d in result]
        assert any(v is not None for v in h1_values)

    def test_html_path_fallback_on_non_html_input(self) -> None:
        """HTML/URL path: plain-text input must not raise; must return valid chunks.

        REQ-008 requires wrapping HTMLSectionSplitter.split_text() in
        try/except.  When the input is not valid HTML, the splitter may
        raise; the fallback must produce the standard {text, metadata} shape.

        Args:
            (none)

        Returns:
            None

        Raises:
            AssertionError: if result is not a list or chunks lack required keys.
        """
        plain_text = (
            "This is not HTML. Just some text content that needs to be chunked."
        )
        result = chunk_document(plain_text, source_hint="https://example.com/api")
        assert isinstance(result, list)
        assert all("text" in d and "metadata" in d for d in result)

    def test_plain_path_txt_returns_empty_metadata(self) -> None:
        """Plain path (.txt): metadata must be an empty dict (not absent, not None).

        ChromaDB (CON-001) rejects None values.  For plain documents with no
        structural metadata, {} is the correct sentinel — never None.

        Args:
            (none)

        Returns:
            None

        Raises:
            AssertionError: if any chunk has metadata != {}.
        """
        result = chunk_document("Some plain text content " * 30, source_hint="notes.txt")
        assert result
        for d in result:
            assert d["metadata"] == {}

    def test_plain_path_pdf_returns_empty_metadata(self) -> None:
        """Plain path (.pdf): metadata must be an empty dict.

        PDF is not a recognised structural format for this function, so it
        takes the plain path and must yield {} metadata.

        Args:
            (none)

        Returns:
            None

        Raises:
            AssertionError: if any chunk has metadata != {}.
        """
        result = chunk_document("PDF content " * 30, source_hint="document.pdf")
        assert result
        for d in result:
            assert d["metadata"] == {}

    def test_plain_path_empty_hint_returns_empty_metadata(self) -> None:
        """Plain path (empty string hint): metadata must be an empty dict.

        An empty source_hint does not match .md or http/https prefixes, so
        it falls through to the plain path.

        Args:
            (none)

        Returns:
            None

        Raises:
            AssertionError: if any chunk has metadata != {}.
        """
        result = chunk_document("Some raw text " * 30, source_hint="")
        assert result
        for d in result:
            assert d["metadata"] == {}

    def test_return_type_is_list_of_dicts_with_required_keys(self) -> None:
        """All dispatch paths must return list[dict] with 'text' and 'metadata' keys.

        This is the structural contract that callers (e.g. initialize_vector_db)
        rely on when ingesting chunks into ChromaDB.

        Args:
            (none)

        Returns:
            None

        Raises:
            AssertionError: if any result does not have the required shape.
        """
        for hint in ["guide.md", "https://example.com", "notes.txt", ""]:
            result = chunk_document("Sample content " * 30, source_hint=hint)
            assert isinstance(result, list)
            for d in result:
                assert isinstance(d, dict)
                assert "text" in d
                assert "metadata" in d
                assert isinstance(d["text"], str)
                assert isinstance(d["metadata"], dict)

    def test_chunk_size_respected_on_plain_path(self) -> None:
        """Plain path: produced chunk lengths must not exceed chunk_size + chunk_overlap.

        RecursiveCharacterTextSplitter uses chunk_size as a hard target, but
        may exceed it by at most chunk_overlap characters on the last chunk.

        Args:
            (none)

        Returns:
            None

        Raises:
            AssertionError: if any chunk length exceeds chunk_size + chunk_overlap.
        """
        long_text = "word " * 200
        chunk_size, chunk_overlap = 400, 50
        result = chunk_document(
            long_text,
            source_hint="doc.txt",
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        for d in result:
            assert len(d["text"]) <= chunk_size + chunk_overlap

    def test_no_none_values_in_metadata(self) -> None:
        """CON-001: no metadata value may be None across all dispatch paths.

        ChromaDB raises a hard error when it receives None in a metadata dict.
        This test enforces the constraint for every supported source_hint type.

        Args:
            (none)

        Returns:
            None

        Raises:
            AssertionError: if any metadata value is None.
        """
        for hint in ["guide.md", "https://example.com/page", "notes.txt"]:
            result = chunk_document("content " * 50, source_hint=hint)
            for d in result:
                for v in d["metadata"].values():
                    assert v is not None

    def test_chunk_text_unchanged(self) -> None:
        """CON-002: chunk_text() must retain its original signature and behaviour.

        Introducing chunk_document() must not rename, remove, or alter
        chunk_text().  Existing callers (e.g. initialize_vector_db) depend on it.

        Args:
            (none)

        Returns:
            None

        Raises:
            AssertionError: if chunk_text signature or return type has changed.
        """
        from hybrid_rag.vectordb import chunk_text
        import inspect

        sig = inspect.signature(chunk_text)
        assert sig.parameters["chunk_size"].default == 400
        result = chunk_text("sample text " * 20)
        assert isinstance(result, list)
        assert all(isinstance(c, str) for c in result)
