"""Vector database initialization and management.

Note 1: This module is the data-layer boundary for the hybrid RAG library.
All ChromaDB interactions — collection creation, document embedding, and
collection querying — are funnelled through the functions defined here,
keeping the rest of the library free of direct database calls.
"""

# Note 2: Python's standard-library imports are grouped first (PEP 8).
# Keeping imports in three groups (stdlib, third-party, local) makes it
# immediately clear which dependencies require installation versus which
# are built into Python.
import logging
import os
import re
from typing import Any, Callable, TypeVar, cast

_M = TypeVar("_M")

# Note 3: urlparse is added in ADR-0001 T2 to detect whether a document's
# "source" field is a real HTTP/HTTPS URL. This drives the conditional
# source_url metadata field in initialize_vector_db().
from urllib.parse import urlparse

# Note 4: chromadb is the vector database used for semantic (embedding-based)
# search. It stores document vectors alongside metadata and supports
# server-side "where" filters — a key advantage over FAISS which has no
# built-in metadata store.
import chromadb
from chromadb.api.models.Collection import Collection
from chromadb.api.types import Embeddable, EmbeddingFunction
from chromadb.errors import NotFoundError
from chromadb.utils import embedding_functions

# Note 5: RecursiveCharacterTextSplitter tries to split text at natural
# language boundaries (paragraphs, sentences, words) before falling back to
# raw character splits. This preserves more semantic context per chunk than
# a naive fixed-width character split.
from langchain_text_splitters import (
    HTMLSectionSplitter,
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

from .constants import KNOWLEDGE_DB_DIRECTORY, DEFAULT_EMBEDDING_MODEL, DEFAULT_EMBEDDING_MODEL_PATH
from .exceptions import VectorDBError

# Note 6: __all__ declares the public surface area of this module.
# Any name NOT listed here is considered an implementation detail and
# should not be relied upon by external callers.
__all__ = [
    "chunk_document",
    "chunk_text",
    "initialize_vector_db",
    "open_collection",
    "get_sample_documents",
    "is_valid_collection_name",
    "sanitize_collection_name",
    "list_existing_collections",
]

# Note 7: Module-level loggers (getLogger(__name__)) are the project standard.
# Using __name__ means log entries automatically carry the full dotted module
# path (e.g., "hybrid_rag.vectordb"), making log filtering and tracing easy.
logger = logging.getLogger(__name__)


def ensure_model_local(
    model_name: str,
    model_path: str,
    loader: Callable[[str], _M],
) -> str:
    """Guarantee a sentence-transformers-compatible model is available locally.

    Checks whether *model_path* already contains a saved model (detected by the
    presence of ``config.json``). If found, the local path is returned as-is. If
    not, the model is downloaded via *loader*, saved to *model_path*, and that
    path is returned. The save is atomic: uses a temporary directory and renames
    on completion to prevent partial writes.

    This single implementation is the only download-or-load workflow in the
    codebase; both the embedding model (SentenceTransformer) and the reranker
    (CrossEncoder) delegate here.

    Args:
        model_name: Hugging Face model identifier used when a local copy is absent.
        model_path: Directory to store/load the model.
        loader: Callable that accepts a model name/path and returns a model
            instance with a ``save(path)`` method (e.g. SentenceTransformer,
            CrossEncoder).

    Returns:
        Absolute path to the local model directory.

    Raises:
        Exception: If download or save fails (from loader or model.save()).
    """
    import shutil

    local_path = os.path.abspath(model_path)
    if os.path.isdir(local_path) and os.path.exists(
        os.path.join(local_path, "config.json")
    ):
        logger.info("Loading model from local path: %s", local_path)
    else:
        logger.info("Downloading model '%s' to %s", model_name, local_path)
        model = loader(model_name)
        tmp_path = local_path + ".tmp"
        try:
            shutil.rmtree(tmp_path, ignore_errors=True)
            os.makedirs(tmp_path, exist_ok=True)
            model.save(tmp_path)  # type: ignore[union-attr]
            os.rename(tmp_path, local_path)
        except Exception:
            shutil.rmtree(tmp_path, ignore_errors=True)
            raise
        logger.info("Model saved to %s; future loads will use this path.", local_path)
    return local_path


def _ensure_embedding_model_local(model_path: str) -> str:
    """Return a local path for the sentence-transformer embedding model.

    Thin wrapper around :func:`ensure_model_local` that binds the HF model
    name and loader for the embedding model.

    Args:
        model_path: Directory to store/load the sentence-transformer model.

    Returns:
        Absolute path to the local model directory.
    """
    from sentence_transformers import SentenceTransformer as _ST

    return ensure_model_local(DEFAULT_EMBEDDING_MODEL, model_path, _ST)


def _has_table_structure(text: str) -> bool:
    """Detect if text contains table markup (markdown or HTML).

    Tables require careful whitespace handling because alignment matters.

    Args:
        text: Text to check for table structure.

    Returns:
        True if text contains pipe-delimited (markdown) or <table> (HTML) markup.
    """
    lines = text.split("\n")
    pipe_rows = sum(1 for line in lines if "|" in line and line.strip())
    if pipe_rows >= 2:
        return True
    return "<table" in text.lower()


def _has_code_block(text: str) -> bool:
    """Detect if text contains code blocks that need structure preservation.

    Code blocks (markdown, preformatted) should not have indentation collapsed.

    Args:
        text: Text to check for code blocks.

    Returns:
        True if text contains markdown code fences (```), HTML <pre>, or 4-space indentation.
    """
    # Markdown code fences
    if "```" in text:
        return True
    # HTML preformatted
    if "<pre" in text.lower():
        return True
    # Indented code (4-space indent on non-empty line)
    for line in text.split("\n"):
        if line.startswith("    ") and line.strip():
            return True
    return False


def _has_list_structure(text: str) -> bool:
    """Detect if text contains markdown/HTML lists with nesting.

    Lists with indentation require careful whitespace handling.

    Args:
        text: Text to check for list structure.

    Returns:
        True if text contains list markers (-, *, +, numbers) with indentation.
    """
    has_list = False
    has_indented_list = False
    for line in text.split("\n"):
        stripped = line.lstrip()
        leading_spaces = len(line) - len(stripped)
        is_list = stripped.startswith(("- ", "* ", "+ ", "• ")) or re.match(
            r"^\d+\.\s", stripped
        )
        if is_list:
            has_list = True
            if leading_spaces > 0:
                has_indented_list = True
    return has_list and has_indented_list


def _normalize_whitespace_aggressive(text: str) -> str:
    """Aggressively normalize: collapse all whitespace, remove all blank lines.

    Used for noisy HTML/pasted content without structure concerns.
    """
    lines = (re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def _normalize_whitespace_preserve_structure(text: str) -> str:
    """Normalize while preserving semantic structures (lists, code, tables).

    Strategy:
      - Detect code blocks (```, <pre>, 4-space indent block) and preserve as-is
      - Detect tables (|, <table>) and preserve alignment
      - Detect lists (-, *, numbers) and preserve indentation (including nested)
      - Apply aggressive normalization to normal text
    """
    result = []
    in_code_block = False
    in_indented_code = False
    in_pre_block = False
    code_block_indent = 0
    lines_list = text.splitlines()

    for idx, line in enumerate(lines_list):
        stripped = line.lstrip()
        leading_spaces = len(line) - len(stripped)

        # Detect markdown code fence (toggle code block mode)
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            result.append(line)
            continue

        # Preserve content inside markdown code blocks exactly as-is
        if in_code_block:
            result.append(line)
            continue

        # Toggle HTML <pre> block mode
        if "<pre" in stripped.lower():
            in_pre_block = True
        if "</pre>" in stripped.lower():
            result.append(line)
            in_pre_block = False
            continue

        # Preserve content inside HTML <pre> blocks exactly as-is
        if in_pre_block:
            result.append(line)
            continue

        # Detect indented code block (4-space indent, context: surrounded by text)
        # Rule: 4+ spaces OR existing indented code block until dedent
        if not in_indented_code and leading_spaces >= 4 and stripped:
            # Start indented code block if preceded by non-empty line
            if idx > 0 and lines_list[idx - 1].strip():
                in_indented_code = True
                code_block_indent = leading_spaces
        elif in_indented_code:
            # Continue indented code block if still indented or blank
            if stripped and leading_spaces < code_block_indent:
                in_indented_code = False
            elif not stripped:
                # Blank line in indented code block
                result.append(line)
                continue

        if in_indented_code:
            # Preserve indented code exactly
            result.append(line)
            continue

        # Detect table rows (pipes) — preserve line structure
        if "|" in line and line.count("|") >= 2:
            result.append(line)
            continue

        # Detect HTML table elements
        if any(tag in line.lower() for tag in ["<table", "<tr", "<td", "<th", "</table>"]):
            result.append(line)
            continue

        # Detect list markers: -, *, +, numbered (1., 2., etc.)
        # Do this BEFORE stripping leading spaces to detect nested items
        is_list_item = (
            stripped.startswith(("- ", "* ", "+ ", "• ")) or
            re.match(r"^\d+\.\s", stripped)
        )

        # For ANY list item (including nested), preserve leading indentation
        # and only collapse internal whitespace
        if is_list_item:
            if stripped:
                collapsed_content = re.sub(r"[ \t]+", " ", stripped)
                result.append(" " * leading_spaces + collapsed_content)
            else:
                result.append(line)
            continue

        # For indented content that's not a list item (continuation of list, nested text),
        # preserve leading spaces but collapse internal whitespace
        if leading_spaces > 0 and stripped and not is_list_item:
            collapsed_content = re.sub(r"[ \t]+", " ", stripped)
            result.append(" " * leading_spaces + collapsed_content)
            continue

        # Q&A format: preserve "Q:" and "A:" patterns with minimal collapse
        if stripped.startswith(("Q:", "A:")) and leading_spaces == 0:
            collapsed = re.sub(r"[ \t]+", " ", line).strip()
            if collapsed:
                result.append(collapsed)
            continue

        # Normal text: aggressive normalization
        cleaned = re.sub(r"[ \t]+", " ", line).strip()
        if cleaned:
            result.append(cleaned)

    # Remove consecutive blank lines (but preserve some structure)
    final_result = []
    prev_blank = False
    for line in result:
        is_blank = not line.strip()
        if not (is_blank and prev_blank):
            final_result.append(line)
        prev_blank = is_blank

    return "\n".join(final_result)


def _normalize_whitespace(text: str) -> str:
    """Normalize whitespace in source text, preserving FAQ/Confluence structures.

    Smart normalization that:
      - Removes excessive blank lines and run-on spaces from noisy HTML/pasted content
      - Preserves code block indentation (markdown ```, HTML <pre>, 4-space indent)
      - Preserves table alignment (markdown |, HTML <table>)
      - Preserves list hierarchy (leading spaces before -, *, numbers)
      - Handles Q&A format

    This prevents noise patterns like "\\n \\n \\n \\n" from cluttering
    embeddings while keeping semantic structures intact.

    Args:
        text: Raw source text, potentially containing excessive whitespace
            and semantic structures.

    Returns:
        Cleaned text with excessive whitespace removed but structures preserved.

    Example:
        >>> _normalize_whitespace(" \\n \\n Tiles \\n \\n Get started")
        'Tiles\\nGet started'

        >>> code = "```python\\n    x = 1\\n    return x\\n```"
        >>> result = _normalize_whitespace(code)
        >>> "    x = 1" in result
        True
    """
    # Detect if text has structures we need to preserve carefully
    has_code = _has_code_block(text)
    has_table = _has_table_structure(text)
    has_lists = _has_list_structure(text)

    if has_code or has_table or has_lists:
        # Use structure-preserving normalization
        return _normalize_whitespace_preserve_structure(text)
    else:
        # Use aggressive normalization for simple text
        return _normalize_whitespace_aggressive(text)


def chunk_text(
    text: str, chunk_size: int = 400, chunk_overlap: int = 50
) -> list[str]:
    """Split text into overlapping chunks using recursive character splitting.

    Uses recursive splitting strategy to maintain semantic boundaries by splitting
    on progressively smaller delimiters (newlines, spaces, etc.) when needed.

    Args:
        text: The text string to split into chunks.
        chunk_size: Target size of each chunk in characters. Defaults to 400.
                    Values above ~400 risk exceeding the embedding model's max
                    sequence length (512 tokens for BAAI/bge-small-en-v1.5;
                    ~256 tokens for all-MiniLM-L6-v2), causing silent tail
                    truncation.
        chunk_overlap: Number of overlapping characters between consecutive chunks. Defaults to 50.

    Returns:
        List of text chunks created from the input text.

    Raises:
        ValueError: If chunk_size or chunk_overlap are invalid.

    Example:
        >>> chunks = chunk_text("Sample text " * 100, chunk_size=100, chunk_overlap=10)
        >>> len(chunks) > 1
        True
    """
    # Note 8: Guard clauses at the top of a function (early-return on invalid
    # input) are a readability pattern: the "happy path" logic that follows is
    # not nested inside conditions, so it reads sequentially without mental
    # bookkeeping. Each guard raises a specific ValueError with a clear message
    # rather than letting the error surface deep inside the splitter.
    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    if chunk_overlap < 0:
        raise ValueError("chunk_overlap must be >= 0")
    # Note 9: chunk_overlap must be strictly less than chunk_size, otherwise
    # consecutive chunks would overlap by 100% or more — meaning each chunk
    # is fully contained in the previous one, producing infinite or circular
    # splitting behaviour.
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be < chunk_size")

    try:
        # Note 10: RecursiveCharacterTextSplitter is instantiated fresh on each
        # call. The splitter object is lightweight (no model weights), so
        # creating it inline keeps the function stateless — safe to call from
        # any thread without locking.
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size, chunk_overlap=chunk_overlap
        )
        chunks = splitter.split_text(text)
        logger.debug(
            f"Text split into {len(chunks)} chunks (size={chunk_size}, overlap={chunk_overlap})"
        )
        return chunks
    except Exception as e:
        # Note 11: Re-raising after logging preserves the original traceback
        # (no information is lost). The bare `raise` without arguments is
        # preferred over `raise e` because the latter replaces the traceback
        # origin with this line number, making debugging harder.
        logger.error(f"Text chunking failed: {e}")
        raise


def chunk_document(
    text: str,
    source_hint: str,
    chunk_size: int = 400,
    chunk_overlap: int = 50,
) -> list[dict[str, Any]]:
    """Split a document into chunks, enriching metadata by detected format.

    Routes the input text through one of three splitting paths based on the
    ``source_hint`` value:

    * **Markdown** (``source_hint`` ends with ``.md``) — uses
      ``MarkdownHeaderTextSplitter`` to extract heading context (H1/H2) before
      applying a ``RecursiveCharacterTextSplitter`` size pass.
    * **HTML/URL** (``source_hint`` starts with ``http://`` or ``https://``) —
      uses ``HTMLSectionSplitter`` for section-aware splitting, falling back to
      plain splitting if the HTML parser raises.  Short chunks (< 20 chars)
      are discarded.
    * **Plain** (everything else) — uses ``RecursiveCharacterTextSplitter``
      directly; metadata is always ``{}``.

    Every returned dict contains ``"text"`` (str) and ``"metadata"`` (dict).
    Metadata values are *never* ``None`` — ChromaDB rejects ``None`` values
    (CON-001).  Heading keys (``section_h1``, ``section_h2``) are included
    only when the splitter found a non-empty value for them.

    Args:
        text: Raw document text to split.
        source_hint: File path or URL used to detect the document format.
            Examples: ``"guide.md"``, ``"https://docs.example.com/page"``,
            ``"notes.txt"``.
        chunk_size: Target chunk length in characters.  Defaults to 400.
        chunk_overlap: Overlap between consecutive chunks in characters.
            Defaults to 50.

    Returns:
        List of dicts, each with the shape::

            {
                "text": str,       # chunk content
                "metadata": dict,  # heading keys when available; {} for plain
            }

    Raises:
        ValueError: If ``chunk_size`` <= 0, ``chunk_overlap`` < 0, or
            ``chunk_overlap`` >= ``chunk_size``.

    Example:
        >>> chunks = chunk_document("# Hello\\n\\nWorld.", source_hint="doc.md")
        >>> chunks[0]["metadata"].get("section_h1")
        'Hello'
    """
    # Note 12: Guard clauses mirror the validation in chunk_text() so that
    # both public functions raise consistent ValueError messages for invalid
    # parameters.  Without these guards, invalid values would surface as opaque
    # errors deep inside RecursiveCharacterTextSplitter, making debugging harder
    # for callers.
    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    if chunk_overlap < 0:
        raise ValueError("chunk_overlap must be >= 0")
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be < chunk_size")
    # Normalize whitespace before chunking to remove noise from HTML-scraped
    # content while preserving code blocks, tables, and lists (Issue #94).
    text = _normalize_whitespace(text)
    # Note 13: The size_splitter is created ONCE here and passed down to every
    # private helper.  This is the "shared resource" pattern: all three paths
    # need identical size-cap behaviour, so building the splitter in one place
    # guarantees consistent chunk_size and chunk_overlap across paths.
    # Creating it once also avoids redundant object allocation inside helpers.
    size_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size, chunk_overlap=chunk_overlap
    )
    # Note 14: Normalising to lower-case before comparison is defensive
    # programming — it ensures "README.MD", "guide.Md", and "guide.md" all
    # match the Markdown branch.  Without this, users who pass mixed-case
    # paths would silently fall through to the plain path and lose heading
    # metadata, which would be a subtle, hard-to-diagnose bug.
    hint_lower = source_hint.lower()
    # Note 15: The dispatch table is a series of simple string checks rather
    # than a match/case statement or a dict of callables.  This keeps the
    # routing logic readable and easy to extend: adding a new format (e.g.
    # ".rst" for reStructuredText) only requires inserting one more `if`
    # block without touching existing branches.
    if hint_lower.endswith(".md"):
        # Note 16: endswith(".md") is used instead of a regex because file
        # extension checks are a simple suffix comparison — regex would add
        # overhead and complexity for no gain here.
        return _chunk_markdown(text, size_splitter)
    if hint_lower.startswith(("http://", "https://")):
        # Note 17: startswith() accepts a TUPLE of prefixes as a single
        # argument, which is more readable than `or` chaining:
        #   hint_lower.startswith("http://") or hint_lower.startswith("https://")
        # Both forms compile to the same bytecode, so the tuple form is
        # purely a style choice that scales better if more schemes are added.
        return _chunk_html(text, size_splitter)
    # Note 18: The plain path is the "catch-all" — anything that is not a
    # Markdown file and not a URL lands here.  This includes .txt, .pdf,
    # .csv, and even an empty string hint.  The function never raises for
    # an unrecognised format; it simply applies the least-structured path.
    return _chunk_plain(text, size_splitter)


def _chunk_markdown(
    text: str,
    size_splitter: RecursiveCharacterTextSplitter,
) -> list[dict[str, Any]]:
    """Split Markdown text using heading-aware then size-based splitting.

    MarkdownHeaderTextSplitter divides text at H1 and H2 headings, storing
    the heading text in doc.metadata.  A second pass with
    RecursiveCharacterTextSplitter ensures no resulting chunk exceeds the
    caller-configured size.

    Args:
        text: Raw Markdown string.
        size_splitter: Pre-configured RecursiveCharacterTextSplitter to apply
            after heading-based splitting.

    Returns:
        List of {text, metadata} dicts with optional section_h1/section_h2
        keys.
    """
    # Note 19: headers_to_split_on maps Markdown heading syntax to metadata key
    # names.  The LangChain convention is a list of (marker, metadata_key)
    # tuples.  "#" is an H1 and "##" is an H2.  These keys ("section_h1",
    # "section_h2") become the keys in doc.metadata after splitting — they are
    # project-defined names, not LangChain-defined, so they must be consistent
    # across all code that reads or writes them.
    headers_to_split_on = [("#", "section_h1"), ("##", "section_h2")]
    # Note 20: strip_headers=False keeps the heading line inside doc.page_content
    # (e.g., "# Installation\n\nInstall the package …").  Setting it to True
    # would remove the heading text from the content and put it only in metadata,
    # which can result in orphaned metadata with no textual context in the chunk.
    # Keeping the heading in the content preserves full context for the embedder.
    md_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=headers_to_split_on, strip_headers=False
    )
    # Note 21: md_splitter.split_text() returns a list of LangChain Document
    # objects.  Each Document has two fields:
    #   - page_content (str): the text section under the heading
    #   - metadata (dict): the heading keys that apply to this section
    # The Document class is from langchain_core.documents — it is LangChain's
    # universal container for text + metadata throughout the library.
    md_docs = md_splitter.split_text(text)
    result: list[dict[str, Any]] = []
    for doc in md_docs:
        # Note 22: A two-pass split strategy is used here.  The first pass
        # (MarkdownHeaderTextSplitter) creates semantically meaningful sections
        # by heading boundaries.  The second pass (size_splitter) ensures no
        # single section exceeds the model's context window.  Without the second
        # pass, a very long section under one heading would be ingested as a
        # single oversized chunk and risk silent truncation by the embedder.
        sub_chunks = size_splitter.split_text(doc.page_content)
        # Note 23: The dict comprehension filters doc.metadata to include only
        # recognised heading keys with truthy values.  The `doc.metadata or {}`
        # guard handles the edge case where MarkdownHeaderTextSplitter returns
        # a Document whose metadata is None (which can happen for text before
        # the first heading).  Without this guard, iterating over None would
        # raise a TypeError.
        #
        # The `and v` condition satisfies CON-001: any key whose value is None
        # or an empty string is excluded, ensuring ChromaDB never receives a
        # None metadata value that it would reject at write time.
        heading_meta: dict[str, Any] = {
            k: v
            for k, v in (doc.metadata or {}).items()
            if k in ("section_h1", "section_h2") and v
        }
        for chunk in sub_chunks:
            # Note 24: A shallow copy of heading_meta is returned for each
            # chunk so that a downstream caller mutating one chunk's metadata
            # dict cannot affect sibling chunks from the same heading section.
            # heading_meta only contains string key–value pairs, so a shallow
            # copy is sufficient — no nested mutable objects are present.
            result.append({"text": chunk, "metadata": heading_meta.copy()})
    return result


def _chunk_html(
    text: str,
    size_splitter: RecursiveCharacterTextSplitter,
) -> list[dict[str, Any]]:
    """Split HTML text using section-aware splitting with plain-path fallback.

    HTMLSectionSplitter divides text at H1/H2 tags. If the HTML parser raises
    (REQ-008), the function logs a warning and delegates to _chunk_plain().
    After the size pass, chunks shorter than 20 characters are discarded
    (GUD-001) because they are typically navigation artefacts or whitespace.

    Args:
        text: Raw HTML or URL-sourced text.
        size_splitter: Pre-configured RecursiveCharacterTextSplitter to apply
            after section splitting.

    Returns:
        List of {text, metadata} dicts.  Short chunks (< 20 stripped chars)
        are excluded.
    """
    # Note 25: HTMLSectionSplitter uses ("h1", "section_h1") tuples — the HTML
    # tag name ("h1") on the left, the metadata key ("section_h1") on the right.
    # Note the difference from the Markdown path where the marker is "#".
    # The metadata key names are intentionally IDENTICAL between paths so that
    # callers (e.g., API filters) need no format-specific logic to read headings.
    headers_to_split_on = [("h1", "section_h1"), ("h2", "section_h2")]
    html_splitter = HTMLSectionSplitter(headers_to_split_on=headers_to_split_on)
    # Note 26: REQ-008 mandates wrapping HTMLSectionSplitter.split_text() in a
    # broad try/except.  HTMLSectionSplitter depends on the `lxml` and
    # `beautifulsoup4` libraries at runtime.  If either is missing, or if the
    # input is malformed XML/HTML, the parser raises.  The fallback to
    # _chunk_plain() ensures callers always receive valid output — this is the
    # "fail-open" pattern: prefer a degraded result over a hard failure.
    try:
        html_docs = html_splitter.split_text(text)
    except Exception as exc:
        # Note 27: logger.warning() (not error) is appropriate here because the
        # situation is handled gracefully by the fallback.  `error` implies an
        # unrecoverable problem; `warning` signals a degraded code path that
        # callers should be aware of but that does not break the request.
        # Using the %-style format string (not an f-string) is the Python
        # logging convention — it defers string formatting until the message is
        # actually emitted, saving CPU cycles when the log level is suppressed.
        logger.warning(
            "HTMLSectionSplitter failed (%s); falling back to plain path", exc
        )
        return _chunk_plain(text, size_splitter)
    result: list[dict[str, Any]] = []
    for doc in html_docs:
        sub_chunks = size_splitter.split_text(doc.page_content)
        # Note 28: The heading_meta construction here is identical to the
        # Markdown path (see Note 23).  The same CON-001 constraint applies:
        # ChromaDB rejects None metadata values, so the `and v` filter is
        # essential.  Sharing this pattern across both format-aware paths
        # means the ChromaDB insertion code never needs format-specific checks.
        heading_meta: dict[str, Any] = {
            k: v
            for k, v in (doc.metadata or {}).items()
            if k in ("section_h1", "section_h2") and v
        }
        for chunk in sub_chunks:
            # Note 29: GUD-001 — chunks shorter than 20 stripped characters
            # are discarded.  HTML parsers often produce Document objects whose
            # page_content is a heading label alone (e.g., "Overview") after
            # the size-cap pass splits it off from its body text.  These micro-
            # chunks add noise to search results without contributing meaningful
            # context, so they are filtered out here.  The threshold of 20
            # characters is a heuristic chosen to eliminate single words and
            # short phrases while keeping all substantive content.
            if len(chunk.strip()) >= 20:
                # Note 30: A shallow copy is passed per chunk for the same
                # reason as in the Markdown path (see Note 24): this prevents
                # one chunk's metadata mutation from affecting siblings.
                result.append({"text": chunk, "metadata": heading_meta.copy()})
    return result


def _chunk_plain(
    text: str,
    size_splitter: RecursiveCharacterTextSplitter,
) -> list[dict[str, Any]]:
    """Split plain text using only RecursiveCharacterTextSplitter.

    No structural metadata is available for plain files (txt, pdf, csv, …),
    so metadata is always the empty dict.  An empty dict satisfies CON-001
    (ChromaDB accepts it) while clearly signalling "no heading context".

    Args:
        text: Any plain text string.
        size_splitter: Pre-configured RecursiveCharacterTextSplitter.

    Returns:
        List of {text, metadata: {}} dicts.
    """
    # Note 31: The list comprehension `[{"text": c, "metadata": {}} for c …]`
    # builds the output in a single expression.  It is equivalent to the loop:
    #
    #   result = []
    #   for c in size_splitter.split_text(text):
    #       result.append({"text": c, "metadata": {}})
    #   return result
    #
    # The comprehension form is preferred here because _chunk_plain has no
    # conditional logic — every chunk maps to the same shape — so the compact
    # form is easier to read at a glance.
    #
    # The `{}` (empty dict) for metadata is deliberate: plain files (txt, pdf,
    # csv …) carry no heading structure, so there is nothing meaningful to put
    # in metadata.  An empty dict is unambiguous — it signals "no structural
    # metadata" — whereas None or a missing key would require callers to handle
    # multiple shapes, violating the uniform return contract.
    return [{"text": c, "metadata": {}} for c in size_splitter.split_text(text)]


def get_sample_documents() -> list[dict[str, str]]:
    """Retrieve a list of sample Google Maps support documents.

    Provides sample documentation for testing and demonstration purposes.
    Each document contains support content about Google Maps features.

    Returns:
        List of document dictionaries with 'id', 'source' URL, and 'text' content.

    Example:
        >>> docs = get_sample_documents()
        >>> len(docs) == 4
        True
        >>> all("source" in d for d in docs)
        True
    """
    documents = [
        {
            "id": "1",
            "source": "https://support.google.com/maps/answer/144349",
            "text": """
    How to get started with Google Maps.
    Google Maps is a web mapping service. You can use Google Maps to search for places, get directions, view traffic conditions, and explore satellite imagery. To get started, visit maps.google.com and sign in with your Google account. You can search for locations, save places, and share maps with others. Google Maps works on desktop and mobile devices.
    """,
        },
        {
            "id": "2",
            "source": "https://support.google.com/maps/answer/6291838",
            "text": """
    How to use download areas and navigation offline in Google Maps.
    You can download specific areas of Google Maps to view them offline. This is useful when you don't have internet access. To download an area, open Google Maps, search for a location, and tap the location name at the bottom. Then tap Download and select the area size. Navigation offline allows you to get turn-by-turn directions without internet connection.
    """,
        },
        {
            "id": "3",
            "source": "https://support.google.com/maps/answer/2839911",
            "text": """
    How to Find & improve your location's accuracy in Google Maps.
    Your location accuracy depends on the GPS signal and network connectivity. To improve your location accuracy, ensure your device's location services are enabled. You can update your location manually by searching for a place and pinning it. In the map settings, you can enable high accuracy mode for better GPS signal. Your home and work locations can be updated in the settings menu for quicker navigation.
    """,
        },
        {
            "id": "4",
            "source": "https://support.google.com/maps/answer/6230175",
            "text": """
    Add, edit, or delete Google Maps reviews & ratings.
    You can contribute to Google Maps by adding reviews, photos, and ratings for places. To add a review, search for a location and tap the review icon. You can edit your existing reviews and ratings at any time. Your contributions help other users find quality businesses. You can also add or update place information, including hours, phone numbers, and addresses. To update your location information, search for the place and select "Suggest an edit".
    """,
        },
    ]

    logger.debug(f"Loaded {len(documents)} sample documents")
    return documents


def initialize_vector_db(
    documents: list[dict[str, str]],
    persist_dir: str = KNOWLEDGE_DB_DIRECTORY,
    collection_name: str = "rag_collection",
    embedding_model_path: str = DEFAULT_EMBEDDING_MODEL_PATH,
) -> Collection:
    """Initialize ChromaDB, embed and store the provided documents, and return the collection.

    Creates a persistent ChromaDB collection with sentence-transformer embeddings.
    Uses cosine distance metric for similarity calculations. Splits documents into
    chunks before storing for better embedding performance. Uses local embeddings
    to avoid external API dependencies.

    On first call the embedding model is downloaded from Hugging Face and saved to
    *embedding_model_path*. Subsequent calls load the model directly from disk,
    so no network access to Hugging Face is required after the initial download.

    Args:
        documents: List of document dictionaries with 'id', 'source', and 'text' keys.
        persist_dir: Directory path to persist the ChromaDB collection.
                     Defaults to KNOWLEDGE_DB_DIRECTORY.
        collection_name: Name of the ChromaDB collection to create or retrieve.
                        Defaults to "rag_collection".
        embedding_model_path: Local directory path to store/load the sentence-transformer
                              embedding model. Defaults to DEFAULT_EMBEDDING_MODEL_PATH.

    Returns:
        ChromaDB Collection object with embedded documents ready for querying.

    Raises:
        VectorDBError: If vector database initialization fails.
        ValueError: If documents list is empty or malformed.

    Example:
        >>> docs = get_sample_documents()
        >>> collection = initialize_vector_db(docs)
        >>> collection is not None
        True
    """
    if not documents:
        raise ValueError("Document list cannot be empty")

    try:
        logger.debug(f"Initializing ChromaDB client at {persist_dir}")
        # Note 32: PersistentClient writes the HNSW index and metadata to disk
        # at persist_dir, so the collection survives process restarts. In
        # contrast, chromadb.Client() (in-memory) is only suitable for
        # short-lived tests because all data is lost when the process exits.
        client = chromadb.PersistentClient(path=persist_dir)

        # Note 33: Deleting and recreating the collection on each call ensures
        # a clean slate — no stale embeddings from a previous run. The
        # NotFoundError catch handles the first-run case where no collection
        # exists yet. This is a "drop-and-recreate" strategy, appropriate for
        # full corpus re-ingestion scenarios.
        # Delete existing collection if it exists
        try:
            client.delete_collection(name=collection_name)
            logger.debug(f"Deleted existing collection: {collection_name}")
        except NotFoundError:
            logger.debug(f"Collection {collection_name} did not exist, creating new one")

        # Resolve the embedding model: load locally if available, else download
        # and save so future calls are fully offline.
        logger.debug("Resolving SentenceTransformer embedding model")
        model_source = _ensure_embedding_model_local(embedding_model_path)
        embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=model_source
        )
        # Note 35: cast() is a type-annotation-only operation — it has no
        # runtime effect. It is used here to satisfy mypy, which cannot infer
        # the generic type parameter of EmbeddingFunction automatically from
        # the concrete subclass returned by SentenceTransformerEmbeddingFunction.
        typed_embedding_function = cast(
            EmbeddingFunction[Embeddable], embedding_function
        )

        # Note 36: "hnsw:space": "cosine" configures the HNSW index to use
        # cosine distance. Sentence-transformer models output L2-normalised
        # vectors, so cosine distance is equivalent to Euclidean distance in
        # that space. Using cosine ensures similarity scores are directly
        # interpretable in the 0–1 range without additional normalisation.
        # Create collection with cosine distance
        # Sentence-transformers produces normalized vectors, so cosine is appropriate
        collection = client.get_or_create_collection(
            name=collection_name,
            embedding_function=typed_embedding_function,
            metadata={"hnsw:space": "cosine"},
        )
        logger.debug(f"Created collection: {collection_name}")

        # Note 37: Accumulating all IDs, texts, and metadata into lists before
        # calling collection.add() in a single batch is more efficient than
        # adding one chunk at a time. ChromaDB can embed the entire batch in
        # one model forward pass, which is faster than N separate calls.
        # Process and add documents to collection
        doc_ids: list[str] = []
        doc_texts: list[str] = []
        # Note 38: dict[str, str | int] is used instead of dict[str, str]
        # because chunk_index is an integer. Union types (str | int, available
        # since Python 3.10) express this without importing Optional or Union.
        doc_metadatas: list[dict[str, str | int]] = []
        id_counter = 0

        for doc in documents:
            if "text" not in doc or "source" not in doc:
                raise ValueError("Each document must have 'text' and 'source' fields")

            # Note 39: urlparse() parses a URL string into its components
            # (scheme, netloc, path, etc.). Checking both scheme ("http"/"https")
            # AND netloc (non-empty hostname) guards against strings like
            # "http://" or "https:" that parse as HTTP but lack a real host.
            parsed = urlparse(doc["source"])
            is_url = parsed.scheme in ("http", "https") and bool(parsed.netloc)
            # Note 40: url_meta is either {"source_url": <url>} or {} (empty
            # dict). Using a conditional expression here avoids setting
            # source_url to None, which ChromaDB silently rejects or stores
            # incorrectly. The empty dict fallback means the key is simply
            # absent from metadata for non-URL sources — cleaner than a None
            # sentinel value (CON-005).
            url_meta: dict[str, str] = {"source_url": doc["source"]} if is_url else {}

            chunk_dicts = chunk_document(doc["text"].strip(), source_hint=doc.get("source", ""),
                                          chunk_size=400, chunk_overlap=50)
            # Note 41: chunk_idx is reset to 0 for each document (defined
            # inside the outer loop). This was the T2 bug: the old code used
            # id_counter as chunk_index, which was a global counter across all
            # documents. Document 2's first chunk would get chunk_index=N
            # instead of 0, making per-document chunk ordering impossible.
            for chunk_idx, cd in enumerate(chunk_dicts):
                heading_meta = {k: v for k, v in cd["metadata"].items()
                                if k in ("section_h1", "section_h2") and v is not None}
                doc_ids.append(f"doc_{id_counter}")
                doc_texts.append(cd["text"])
                # Note 42: The ** (double-star) operator unpacks url_meta into
                # the literal dict, merging its key-value pairs in. If url_meta
                # is empty {}, the result has no extra keys. This is the
                # idiomatic Python way to conditionally include fields in a dict
                # without an explicit if/else block.
                doc_metadatas.append(
                    {
                        "source": doc["source"],
                        "text": doc["text"].strip(),
                        "chunk_index": chunk_idx,
                        **url_meta,
                        **heading_meta,
                    }
                )
                id_counter += 1

        # Add all documents to collection
        collection.add(documents=doc_texts, metadatas=doc_metadatas, ids=doc_ids)
        logger.info(
            f"Vector DB initialized: {id_counter} chunks from {len(documents)} documents"
        )

        return collection

    except ValueError as e:
        logger.error(f"Invalid input: {e}")
        raise
    except Exception as e:
        logger.error(f"Vector DB initialization failed: {e}")
        raise VectorDBError(f"Failed to initialize vector database: {e}") from e


def open_collection(
    persist_dir: str = KNOWLEDGE_DB_DIRECTORY,
    collection_name: str = "rag_collection",
    embedding_model_path: str = DEFAULT_EMBEDDING_MODEL_PATH,
) -> Collection:
    """Open an existing ChromaDB collection without modifying its contents.

    Attaches the same SentenceTransformer embedding function used by
    initialize_vector_db so that semantic queries work correctly.

    On first call the embedding model is downloaded from Hugging Face and saved to
    *embedding_model_path*. Subsequent calls load the model directly from disk.

    Args:
        persist_dir: Directory path where the ChromaDB collection is persisted.
        collection_name: Name of the collection to open.
        embedding_model_path: Local directory path to store/load the sentence-transformer
                              embedding model. Defaults to DEFAULT_EMBEDDING_MODEL_PATH.

    Returns:
        ChromaDB Collection object ready for querying.

    Raises:
        VectorDBError: If the collection does not exist or cannot be opened.

    Example:
        >>> collection = open_collection("./knowledge_db", "my_collection")
        >>> collection is not None
        True
    """
    try:
        client = chromadb.PersistentClient(path=persist_dir)
        model_source = _ensure_embedding_model_local(embedding_model_path)
        embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=model_source
        )
        typed_embedding_function = cast(EmbeddingFunction[Embeddable], embedding_function)
        # Note 43: get_collection (not get_or_create_collection) is used here
        # deliberately. open_collection should fail fast if the collection does
        # not exist — silently creating an empty collection would mask the real
        # error (caller passed a wrong name or the data was not ingested yet).
        collection = client.get_collection(
            name=collection_name,
            embedding_function=typed_embedding_function,
        )
        logger.info(
            "Opened existing collection '%s' (%d docs)", collection_name, collection.count()
        )
        return collection
    except Exception as e:
        # Note 44: `raise VectorDBError(...) from e` preserves the original
        # exception as the __cause__ attribute of the new exception. This
        # means the full original traceback is displayed when the VectorDBError
        # propagates, while callers see a clean domain-specific error type.
        raise VectorDBError(
            f"Failed to open collection '{collection_name}': {e}"
        ) from e


def is_valid_collection_name(name: str) -> bool:
    """Check whether a collection name meets ChromaDB naming requirements.

    A valid collection name is 6–20 characters long and contains only
    alphanumeric characters, underscores, or hyphens.

    Args:
        name: The collection name to validate.

    Returns:
        True if the name is valid, False otherwise.

    Example:
        >>> is_valid_collection_name("my_col")
        True
        >>> is_valid_collection_name("ab")
        False
        >>> is_valid_collection_name("has space")
        False
    """
    # Note 45: re.fullmatch() anchors the pattern to the *entire* string,
    # ensuring no invalid characters appear anywhere in the name. Without
    # fullmatch, re.match("pattern", "valid!extra") would succeed because
    # match() only requires the pattern to match at the beginning.
    if not (6 <= len(name) <= 20):
        return False
    return bool(re.fullmatch(r"[a-zA-Z0-9_\-]+", name))


def sanitize_collection_name(name: str) -> str:
    """Sanitize an arbitrary string into a valid ChromaDB collection name.

    Replaces disallowed characters with underscores, truncates to 20
    characters, and pads with underscores to reach the minimum length of 6.

    Args:
        name: The raw string to sanitize.

    Returns:
        A sanitized collection name that satisfies is_valid_collection_name.

    Example:
        >>> sanitize_collection_name("hello world!")
        'hello_world_'
        >>> sanitize_collection_name("ab")
        'ab____'
    """
    # Note 46: re.sub() replaces every character NOT in the allowed set
    # [a-zA-Z0-9_-] with an underscore. The negated character class [^...]
    # matches any character that is not listed. This covers spaces, dots,
    # forward slashes, and any Unicode characters that appear in real-world
    # document IDs or file paths.
    sanitized = re.sub(r"[^a-zA-Z0-9_\-]", "_", name)
    # Note 47: Slice syntax [:20] truncates to at most 20 characters. In Python,
    # slicing beyond the string length does not raise an error — it simply
    # returns the full string if it is shorter than the requested length.
    sanitized = sanitized[:20]
    if len(sanitized) < 6:
        # Note 48: String multiplication ("_" * n) creates a padding string
        # of n underscores. This ensures the final name meets ChromaDB's
        # minimum length requirement of 6 characters without introducing
        # semantically meaningful padding characters.
        sanitized = sanitized + "_" * (6 - len(sanitized))
    return sanitized


def list_existing_collections(persist_dir: str) -> list[str]:
    """List all ChromaDB collection names stored in the given directory.

    Args:
        persist_dir: Path to the ChromaDB persistence directory.

    Returns:
        List of collection name strings found in the directory.

    Raises:
        VectorDBError: If the ChromaDB client cannot be created or collections
            cannot be listed.

    Example:
        >>> names = list_existing_collections("./knowledge_db")
        >>> isinstance(names, list)
        True
    """
    try:
        client = chromadb.PersistentClient(path=persist_dir)
        # Note 49: List comprehension [c.name for c in ...] extracts only the
        # name attribute from each Collection object. Returning only names
        # (strings) keeps the return type simple and avoids leaking ChromaDB
        # internal Collection objects into the caller's domain.
        return [c.name for c in client.list_collections()]
    except Exception as e:
        logger.error(f"Failed to list collections in {persist_dir}: {e}")
        raise VectorDBError(
            f"Failed to list collections in '{persist_dir}': {e}"
        ) from e
