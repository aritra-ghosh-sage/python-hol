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
import re
from typing import cast

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
from langchain_text_splitters import RecursiveCharacterTextSplitter

from .constants import KNOWLEDGE_DB_DIRECTORY, DEFAULT_EMBEDDING_MODEL
from .exceptions import VectorDBError

# Note 6: __all__ declares the public surface area of this module.
# Any name NOT listed here is considered an implementation detail and
# should not be relied upon by external callers.
__all__ = [
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


def chunk_text(
    text: str, chunk_size: int = 400, chunk_overlap: int = 50
) -> list[str]:
    """Split text into overlapping chunks using recursive character splitting.

    Uses recursive splitting strategy to maintain semantic boundaries by splitting
    on progressively smaller delimiters (newlines, spaces, etc.) when needed.

    Args:
        text: The text string to split into chunks.
        chunk_size: Target size of each chunk in characters. Defaults to 400.
                    Values above ~400 risk exceeding the embedding model's effective
                    token window (~256 tokens for BAAI/bge-small-en-v1.5 and
                    all-MiniLM-L6-v2), causing silent tail truncation.
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
) -> Collection:
    """Initialize ChromaDB, embed and store the provided documents, and return the collection.

    Creates a persistent ChromaDB collection with sentence-transformer embeddings.
    Uses cosine distance metric for similarity calculations. Splits documents into
    chunks before storing for better embedding performance. Uses local embeddings
    to avoid external API dependencies.

    Args:
        documents: List of document dictionaries with 'id', 'source', and 'text' keys.
        persist_dir: Directory path to persist the ChromaDB collection.
                     Defaults to KNOWLEDGE_DB_DIRECTORY.
        collection_name: Name of the ChromaDB collection to create or retrieve.
                        Defaults to "rag_collection".

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
        # Note 12: PersistentClient writes the HNSW index and metadata to disk
        # at persist_dir, so the collection survives process restarts. In
        # contrast, chromadb.Client() (in-memory) is only suitable for
        # short-lived tests because all data is lost when the process exits.
        client = chromadb.PersistentClient(path=persist_dir)

        # Note 13: Deleting and recreating the collection on each call ensures
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

        # Note 14: SentenceTransformerEmbeddingFunction is a ChromaDB-provided
        # wrapper that calls the sentence-transformers library to produce dense
        # vector embeddings. By passing DEFAULT_EMBEDDING_MODEL here, all
        # embeddings in the collection use the same model — a requirement for
        # meaningful cosine similarity comparisons.
        # Initialize local sentence-transformers embedding function
        # Using local embeddings to avoid HF Inference API issues
        logger.debug("Initializing SentenceTransformer embeddings")
        embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=DEFAULT_EMBEDDING_MODEL
        )
        # Note 15: cast() is a type-annotation-only operation — it has no
        # runtime effect. It is used here to satisfy mypy, which cannot infer
        # the generic type parameter of EmbeddingFunction automatically from
        # the concrete subclass returned by SentenceTransformerEmbeddingFunction.
        typed_embedding_function = cast(
            EmbeddingFunction[Embeddable], embedding_function
        )

        # Note 16: "hnsw:space": "cosine" configures the HNSW index to use
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

        # Note 17: Accumulating all IDs, texts, and metadata into lists before
        # calling collection.add() in a single batch is more efficient than
        # adding one chunk at a time. ChromaDB can embed the entire batch in
        # one model forward pass, which is faster than N separate calls.
        # Process and add documents to collection
        doc_ids: list[str] = []
        doc_texts: list[str] = []
        # Note 18: dict[str, str | int] is used instead of dict[str, str]
        # because chunk_index is an integer. Union types (str | int, available
        # since Python 3.10) express this without importing Optional or Union.
        doc_metadatas: list[dict[str, str | int]] = []
        id_counter = 0

        for doc in documents:
            if "text" not in doc or "source" not in doc:
                raise ValueError("Each document must have 'text' and 'source' fields")

            # Note 19: urlparse() parses a URL string into its components
            # (scheme, netloc, path, etc.). Checking both scheme ("http"/"https")
            # AND netloc (non-empty hostname) guards against strings like
            # "http://" or "https:" that parse as HTTP but lack a real host.
            parsed = urlparse(doc["source"])
            is_url = parsed.scheme in ("http", "https") and bool(parsed.netloc)
            # Note 20: url_meta is either {"source_url": <url>} or {} (empty
            # dict). Using a conditional expression here avoids setting
            # source_url to None, which ChromaDB silently rejects or stores
            # incorrectly. The empty dict fallback means the key is simply
            # absent from metadata for non-URL sources — cleaner than a None
            # sentinel value (CON-005).
            url_meta: dict[str, str] = {"source_url": doc["source"]} if is_url else {}

            chunks = chunk_text(doc["text"].strip())
            # Note 21: chunk_idx is reset to 0 for each document (defined
            # inside the outer loop). This was the T2 bug: the old code used
            # id_counter as chunk_index, which was a global counter across all
            # documents. Document 2's first chunk would get chunk_index=N
            # instead of 0, making per-document chunk ordering impossible.
            chunk_idx = 0
            for chunk in chunks:
                doc_ids.append(f"doc_{id_counter}")
                doc_texts.append(chunk)
                # Note 22: The ** (double-star) operator unpacks url_meta into
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
                    }
                )
                id_counter += 1
                chunk_idx += 1

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
) -> Collection:
    """Open an existing ChromaDB collection without modifying its contents.

    Attaches the same SentenceTransformer embedding function used by
    initialize_vector_db so that semantic queries work correctly.

    Args:
        persist_dir: Directory path where the ChromaDB collection is persisted.
        collection_name: Name of the collection to open.

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
        embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=DEFAULT_EMBEDDING_MODEL
        )
        typed_embedding_function = cast(EmbeddingFunction[Embeddable], embedding_function)
        # Note 23: get_collection (not get_or_create_collection) is used here
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
        # Note 24: `raise VectorDBError(...) from e` preserves the original
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
    # Note 25: re.fullmatch() anchors the pattern to the *entire* string,
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
    # Note 26: re.sub() replaces every character NOT in the allowed set
    # [a-zA-Z0-9_-] with an underscore. The negated character class [^...]
    # matches any character that is not listed. This covers spaces, dots,
    # forward slashes, and any Unicode characters that appear in real-world
    # document IDs or file paths.
    sanitized = re.sub(r"[^a-zA-Z0-9_\-]", "_", name)
    # Note 27: Slice syntax [:20] truncates to at most 20 characters. In Python,
    # slicing beyond the string length does not raise an error — it simply
    # returns the full string if it is shorter than the requested length.
    sanitized = sanitized[:20]
    if len(sanitized) < 6:
        # Note 28: String multiplication ("_" * n) creates a padding string
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
        # Note 29: List comprehension [c.name for c in ...] extracts only the
        # name attribute from each Collection object. Returning only names
        # (strings) keeps the return type simple and avoids leaking ChromaDB
        # internal Collection objects into the caller's domain.
        return [c.name for c in client.list_collections()]
    except Exception as e:
        logger.error(f"Failed to list collections in {persist_dir}: {e}")
        raise VectorDBError(
            f"Failed to list collections in '{persist_dir}': {e}"
        ) from e
