"""Tests for enhanced whitespace normalization with FAQ/Confluence structure preservation.

Tests verify that _normalize_whitespace() correctly:
  - Removes excessive blank lines from noisy HTML/pasted content
  - Preserves code block indentation and structure
  - Preserves table formatting and alignment
  - Preserves markdown/HTML list hierarchy
  - Preserves Q&A formatting
  - Handles mixed content correctly
"""

from hybrid_rag.vectordb import _normalize_whitespace


class TestWhitespaceNormalizationCodeBlocks:
    """Tests for code block preservation during normalization."""

    def test_markdown_code_block_preserves_indentation(self) -> None:
        """Markdown code blocks (triple backticks) must preserve exact indentation.

        Code blocks delimited by ``` should not have internal whitespace
        collapsed, as indentation is semantic in code.

        Args:
            (none)

        Returns:
            None

        Raises:
            AssertionError: if code block indentation is collapsed.
        """
        text = (
            "Here's how to configure:\n"
            "\n"
            "```python\n"
            "def configure():\n"
            "    settings = {\n"
            "        'chunk_size': 400,\n"
            "        'overlap': 50\n"
            "    }\n"
            "    return settings\n"
            "```\n"
            "\n"
            "Done!"
        )
        result = _normalize_whitespace(text)

        # Code block should survive with indentation intact
        assert "def configure():" in result
        assert "    settings = {" in result, "Indentation inside code block must be preserved"
        assert "        'chunk_size': 400," in result

    def test_bash_code_block_preserves_line_continuation(self) -> None:
        """Bash code blocks with line continuation \\ must preserve structure.

        Command lines continued with \\ should not have the backslash
        separated from its intended context.

        Args:
            (none)

        Returns:
            None

        Raises:
            AssertionError: if line continuation backslash is separated.
        """
        text = (
            "To fetch data:\n"
            "\n"
            "```bash\n"
            "curl -X GET https://api.example.com/docs \\\n"
            "  -H \"Authorization: Bearer TOKEN\" \\\n"
            "  -H \"Accept: application/json\"\n"
            "```"
        )
        result = _normalize_whitespace(text)

        # Backslash continuation should remain with command
        assert "\\" in result, "Line continuation backslash must be preserved"
        lines = result.split("\n")
        bash_lines = [line for line in lines if "curl" in line or "Authorization" in line]
        assert any("\\" in line for line in bash_lines), "Backslash should be in code block"

    def test_preformatted_text_preserves_leading_spaces(self) -> None:
        """HTML <pre> blocks must preserve leading whitespace (indentation).

        Configuration examples and formatted text rely on visual alignment.

        Args:
            (none)

        Returns:
            None

        Raises:
            AssertionError: if <pre> content is normalized.
        """
        text = (
            "<pre>\n"
            "Configuration:\n"
            "  embedding_model: BAAI/bge-small-en-v1.5\n"
            "  chunk_size: 400\n"
            "  chunk_overlap: 50\n"
            "</pre>"
        )
        result = _normalize_whitespace(text)

        # Leading spaces should be preserved in preformatted section
        assert "  embedding_model:" in result, "Preformatted indentation must be preserved"
        assert "  chunk_size:" in result

    def test_indented_code_blocks_preserve_structure(self) -> None:
        """Indented code blocks (4-space indent) must preserve structure.

        Some markdown formats use 4-space indentation to denote code.

        Args:
            (none)

        Returns:
            None

        Raises:
            AssertionError: if indented code is collapsed.
        """
        text = (
            "Example usage:\n"
            "\n"
            "    from hybrid_rag import HybridRetriever\n"
            "    retriever = HybridRetriever()\n"
            "    results = retriever.retrieve(query)"
        )
        result = _normalize_whitespace(text)

        # Indented code should keep structure
        assert "    from hybrid_rag" in result, "Indented code block indentation must be preserved"


class TestWhitespaceNormalizationTables:
    """Tests for table structure preservation."""

    def test_markdown_table_preserves_pipe_alignment(self) -> None:
        """Markdown tables must preserve pipe alignment for readability.

        Tables with | delimiters should only have excessive blank lines
        removed, not internal spacing collapsed.

        Args:
            (none)

        Returns:
            None

        Raises:
            AssertionError: if table spacing is heavily altered.
        """
        text = (
            "| Feature | Status |\n"
            "|---------|--------|\n"
            "| Semantic Search | ✓ |\n"
            "| Keyword Search | ✓ |\n"
            "| Reranking | ✓ |"
        )
        result = _normalize_whitespace(text)

        # Table structure should survive
        lines = result.split("\n")
        assert len(lines) == 5, "Table should have all 5 rows"
        # Each line should still have pipes
        assert all("|" in line for line in lines if line.strip()), "Table pipes must be preserved"

    def test_html_table_preserved(self) -> None:
        """HTML tables must survive normalization.

        <table> content should be handled carefully.

        Args:
            (none)

        Returns:
            None

        Raises:
            AssertionError: if table rows are lost.
        """
        text = (
            "<table>\n"
            "<tr><td>Issue</td><td>Solution</td></tr>\n"
            "<tr><td>Timeout</td><td>Add index</td></tr>\n"
            "<tr><td>Low quality</td><td>Retune weights</td></tr>\n"
            "</table>"
        )
        result = _normalize_whitespace(text)

        # HTML structure should survive
        assert "<table>" in result
        assert "<tr>" in result
        assert "Timeout" in result
        assert "Low quality" in result


class TestWhitespaceNormalizationLists:
    """Tests for list hierarchy preservation."""

    def test_markdown_list_preserves_nesting(self) -> None:
        """Markdown lists must preserve indentation for hierarchy.

        Nested lists with indentation should not be flattened.

        Args:
            (none)

        Returns:
            None

        Raises:
            AssertionError: if list nesting is destroyed.
        """
        text = (
            "Prerequisites:\n"
            "\n"
            "- Python 3.9+\n"
            "- pip install hybrid-rag\n"
            "  - Requires: ChromaDB\n"
            "  - Optional: Redis\n"
            "- Set environment variables"
        )
        result = _normalize_whitespace(text)

        # Nesting structure should be detectable (indented items under parents)
        lines = result.split("\n")
        # Find "Requires" and "Optional" lines — should be indented
        requires_line = next(line for line in lines if "Requires:" in line)
        optional_line = next(line for line in lines if "Optional:" in line)

        # These should maintain indentation relative to parent list
        assert requires_line.startswith("  "), "Nested list item must be indented"
        assert optional_line.startswith("  "), "Nested list item must be indented"

    def test_numbered_list_preserves_indentation(self) -> None:
        """Numbered lists must preserve indentation in nested items.

        Args:
            (none)

        Returns:
            None

        Raises:
            AssertionError: if indentation is lost.
        """
        text = (
            "Steps:\n"
            "\n"
            "1. Initialize retriever\n"
            "   - Set embedding model\n"
            "   - Configure chunk size\n"
            "2. Ingest documents\n"
            "3. Run queries"
        )
        result = _normalize_whitespace(text)

        lines = result.split("\n")
        # Items with "Set embedding" should be indented under step 1
        embedding_line = next((line for line in lines if "Set embedding" in line), None)
        assert embedding_line is not None, "Nested item should survive"
        assert embedding_line.startswith("   "), "Nested item should maintain indentation"


class TestWhitespaceNormalizationQAFormat:
    """Tests for Q&A formatting preservation."""

    def test_qa_format_preserves_question_answer_separation(self) -> None:
        """Q&A format must preserve separation between questions and answers.

        Multi-paragraph answers should maintain some structure.

        Args:
            (none)

        Returns:
            None

        Raises:
            AssertionError: if Q&A structure is lost.
        """
        text = (
            "Q: What does hybrid RAG mean?\n"
            "\n"
            "A: It combines semantic search with keyword search.\n"
            "Semantic uses embeddings; keyword uses BM25.\n"
            "\n"
            "Q: When should I use it?\n"
            "\n"
            "A: Use when your documents are technical or domain-specific."
        )
        result = _normalize_whitespace(text)

        # Q and A labels should survive
        assert "Q:" in result
        assert "A:" in result
        # Some separation between Q&A pairs should be detectable
        q_lines = [i for i, line in enumerate(result.split("\n")) if "Q:" in line]
        a_lines = [i for i, line in enumerate(result.split("\n")) if "A:" in line]
        assert len(q_lines) == 2, "Both questions should be present"
        assert len(a_lines) == 2, "Both answers should be present"


class TestWhitespaceNormalizationMixedContent:
    """Tests for mixed content (code + tables + lists)."""

    def test_mixed_content_preserves_all_structures(self) -> None:
        """Mixed content must preserve code, tables, and lists together.

        Args:
            (none)

        Returns:
            None

        Raises:
            AssertionError: if any structure is corrupted.
        """
        text = (
            "# Setup Guide\n"
            "\n"
            "## Prerequisites\n"
            "\n"
            "- Python 3.9+\n"
            "- Redis (optional)\n"
            "\n"
            "## Configuration\n"
            "\n"
            "```python\n"
            "config = {\n"
            "    'model': 'BAAI/bge-small-en-v1.5',\n"
            "    'chunk_size': 400\n"
            "}\n"
            "```\n"
            "\n"
            "| Setting | Value |\n"
            "|---------|-------|\n"
            "| Model | BAAI/bge-small |\n"
            "| Chunk Size | 400 |"
        )
        result = _normalize_whitespace(text)

        # All structures should survive
        assert "- Python 3.9+" in result, "List items must survive"
        assert "'model':" in result, "Code block must survive"
        assert "|" in result, "Table must survive"


class TestWhitespaceNormalizationCleanupNoisy:
    """Tests for cleanup of noisy HTML/pasted content."""

    def test_removes_excessive_blank_lines(self) -> None:
        """Normalization must remove excessive blank lines from pasted HTML.

        Multiple consecutive blank lines should collapse to single newline.

        Args:
            (none)

        Returns:
            None

        Raises:
            AssertionError: if blank lines remain.
        """
        text = (
            "Tiles\n"
            "\n"
            "\n"
            "\n"
            "Get started\n"
            "\n"
            "\n"
            "Manage preferences"
        )
        result = _normalize_whitespace(text)

        # No double newlines should exist
        assert "\n\n" not in result, "Excessive blank lines must be removed"
        # Content should still be present
        assert "Tiles" in result
        assert "Get started" in result

    def test_collapses_excessive_spaces_in_normal_text(self) -> None:
        """Normal text should have multiple spaces collapsed to single space.

        Args:
            (none)

        Returns:
            None

        Raises:
            AssertionError: if excessive spaces remain.
        """
        text = "Word1    Word2     Word3"
        result = _normalize_whitespace(text)

        # Should collapse to single spaces
        assert "    " not in result, "Multiple spaces should be collapsed"
        assert result == "Word1 Word2 Word3"

    def test_noisy_html_extraction_example(self) -> None:
        """Real example from issue #94: noisy HTML-extracted text.

        Args:
            (none)

        Returns:
            None

        Raises:
            AssertionError: if normalization doesn't improve clarity.
        """
        text = (
            " \n \n \n \n \n \n \n \n \n \n \n \n \n \n Tiles"
            " \n \n \n \n \n \n \n \n Get started"
            " \n \n \n \n \n \n \n \n \n Manage your preferences"
            " \n \n \n \n \n \n \n \n \n Sage Ai and Copilot"
            " \n \n \n \n \n \n \n \n \n Administration"
        )
        result = _normalize_whitespace(text)

        # No excessive whitespace patterns
        assert "\n \n" not in result, "Excessive newlines must be removed"
        # All content preserved
        assert "Tiles" in result
        assert "Get started" in result
        assert "Manage your preferences" in result
        assert "Administration" in result
