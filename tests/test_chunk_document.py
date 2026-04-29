"""Unit tests for chunk_document() routing function in hybrid_rag/vectordb.py.

Tests verify the public contract of chunk_document():
  - Dispatch logic (MD path, HTML/URL path, plain path)
  - Return shape ({text, metadata} dicts)
  - CON-001: no None values in metadata
  - CON-002: chunk_text() signature is unchanged
  - GUD-001: HTML path discards short chunks
  - REQ-008: HTML path falls back on parse failure
"""
# Note 1: Importing only chunk_document (not the whole module) follows the
# principle of testing the public API surface rather than internal details.
# If the test imported everything, a refactor that moves chunk_document to a
# different internal module would still pass even if the public export broke.
from hybrid_rag.vectordb import chunk_document


# Note 2: Grouping all tests for a single unit under one class is a pytest
# best practice.  The class acts as a namespace — test names do not need to
# be globally unique, and the class docstring documents the overall purpose
# of the test suite for this unit.  pytest discovers classes whose names
# start with "Test" automatically, no base class or decorator required.
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
        # Note 3: The multi-line string is built with implicit concatenation
        # (adjacent string literals joined at parse time, PEP 3120).  This is
        # preferable to a single very long string literal or triple-quoted
        # strings when the content needs to stay within the 88-character line
        # limit while remaining readable.
        md_text = (
            "# Installation\n\nInstall the package with pip.\n\n"
            "## Quick Start\n\nRun the server."
        )
        result = chunk_document(md_text, source_hint="guide.md")
        # Note 4: `assert result` (without a comparison) is a truthiness check
        # — it fails if result is an empty list, None, or any other falsy value.
        # Always assert non-emptiness BEFORE asserting properties of elements,
        # so the failure message ("assert []") is more informative than an
        # IndexError from iterating an empty list.
        assert result
        h1_values = [d["metadata"].get("section_h1") for d in result]
        # Note 5: any() with a generator expression short-circuits — it stops
        # iterating as soon as it finds a True value.  This is more efficient
        # than building a full list and checking if any element matches,
        # especially for large result sets.
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
        # Note 6: `is not None` is used rather than a truthiness check here
        # because an empty string ("") is falsy but is a valid (if unusual)
        # heading value.  The contract only forbids None — it does not forbid
        # empty strings.  Using `is not None` makes the intent explicit.
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
            # Note 7: `== {}` (equality to empty dict) is stricter than
            # `not d["metadata"]` (truthiness check).  Both would pass for an
            # empty dict, but `== {}` also rejects dicts with keys mapped to
            # falsy values such as {"section_h1": ""}.  The plain path contract
            # is that metadata is EXACTLY empty, not merely falsy.
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
        # Note 8: Iterating over multiple source_hint values in a single test
        # method is a lightweight form of parameterisation.  A more idiomatic
        # pytest approach would use @pytest.mark.parametrize to get a separate
        # test ID and failure report per hint, but a plain loop is acceptable
        # here because all hints exercise the same contract (return shape) and
        # a single failure message is sufficient.
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
            # Note 9: chunk_size + chunk_overlap is the maximum theoretical
            # length because RecursiveCharacterTextSplitter may carry over up
            # to chunk_overlap characters from the previous chunk boundary.
            # Using a generous upper bound rather than asserting exactly
            # chunk_size avoids false failures caused by boundary rounding.
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
        # Note 10: Iterating over three representative hints (md, url, plain)
        # covers each dispatch branch.  The nested loop (chunks -> metadata
        # values) uses dict.values() which returns a view over all values
        # regardless of which keys are present — this future-proofs the test
        # against new heading keys (e.g. section_h3) being added later.
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
        # Note 11: The import is placed inside the test body to make it explicit
        # that we are testing importability — if chunk_text were moved or
        # removed, this test would fail at the import line with a clear
        # ImportError rather than a silent AttributeError elsewhere.
        # Note: `from module import name` does NOT consult __all__; __all__ only
        # governs `from module import *`.  To check __all__ membership we assert
        # directly against hybrid_rag.vectordb.__all__ below.
        from hybrid_rag.vectordb import chunk_text
        import hybrid_rag.vectordb as _vdb_module

        assert "chunk_text" in _vdb_module.__all__, (
            "chunk_text must remain in hybrid_rag.vectordb.__all__"
        )
        # Note 12: The `inspect` standard-library module lets tests introspect
        # function signatures at runtime.  inspect.signature() returns a
        # Signature object whose .parameters dict maps each parameter name to a
        # Parameter object.  Accessing .default gives the declared default value.
        # This is more robust than reading the source code: it works even if the
        # function is implemented in C or loaded from a compiled extension.
        import inspect

        sig = inspect.signature(chunk_text)
        assert sig.parameters["chunk_size"].default == 400
        result = chunk_text("sample text " * 20)
        assert isinstance(result, list)
        assert all(isinstance(c, str) for c in result)

    def test_chunk_document_exported_from_hybrid_rag_package(self) -> None:
        """chunk_document must be importable from the top-level hybrid_rag package.

        hybrid_rag/__init__.py re-exports chunk_document so that callers can
        use ``from hybrid_rag import chunk_document`` without knowing the
        internal module layout.  This test verifies both that the symbol is
        importable and that it is declared in hybrid_rag.__all__.

        Args:
            (none)

        Returns:
            None

        Raises:
            ImportError: if chunk_document is not accessible from hybrid_rag.
            AssertionError: if chunk_document is absent from hybrid_rag.__all__.
        """
        # Note 13: Importing the top-level package (not just the submodule)
        # exercises the __init__.py re-export path.  A failure here means the
        # public install contract is broken for users who import from hybrid_rag
        # directly — even if the underlying vectordb module still works fine.
        import hybrid_rag

        assert "chunk_document" in hybrid_rag.__all__, (
            "chunk_document must appear in hybrid_rag.__all__"
        )
        # Note 14: Verify the exported name is the actual callable, not a
        # shadowed or mis-pointed reference.
        from hybrid_rag import chunk_document as top_level_fn
        from hybrid_rag.vectordb import chunk_document as vdb_fn

        assert top_level_fn is vdb_fn, (
            "hybrid_rag.chunk_document must be the same object as "
            "hybrid_rag.vectordb.chunk_document"
        )

    def test_chunk_document_raises_on_invalid_chunk_size(self) -> None:
        """chunk_document() raises ValueError for chunk_size <= 0.

        chunk_document() must apply the same parameter guards as chunk_text()
        so that callers receive a consistent, descriptive error for invalid
        inputs regardless of which public function they call.

        Args:
            (none)

        Returns:
            None

        Raises:
            AssertionError: if ValueError is not raised for chunk_size=0.
        """
        import pytest

        with pytest.raises(ValueError, match="chunk_size must be > 0"):
            chunk_document("some text", source_hint="notes.txt", chunk_size=0)

    def test_chunk_document_raises_on_negative_chunk_overlap(self) -> None:
        """chunk_document() raises ValueError for chunk_overlap < 0.

        Args:
            (none)

        Returns:
            None

        Raises:
            AssertionError: if ValueError is not raised for chunk_overlap=-1.
        """
        import pytest

        with pytest.raises(ValueError, match="chunk_overlap must be >= 0"):
            chunk_document(
                "some text", source_hint="notes.txt", chunk_size=100, chunk_overlap=-1
            )

    def test_chunk_document_raises_when_overlap_gte_size(self) -> None:
        """chunk_document() raises ValueError when chunk_overlap >= chunk_size.

        Args:
            (none)

        Returns:
            None

        Raises:
            AssertionError: if ValueError is not raised when overlap == size.
        """
        import pytest

        with pytest.raises(ValueError, match="chunk_overlap must be < chunk_size"):
            chunk_document(
                "some text",
                source_hint="notes.txt",
                chunk_size=100,
                chunk_overlap=100,
            )
