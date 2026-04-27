"""Vector database initialization and management."""

import logging
from typing import Any, cast

import chromadb
from chromadb.api.models.Collection import Collection
from chromadb.api.types import Embeddable, EmbeddingFunction
from chromadb.errors import NotFoundError
from chromadb.utils import embedding_functions
from langchain_text_splitters import RecursiveCharacterTextSplitter

from .constants import KNOWLEDGE_DB_DIRECTORY
from .exceptions import VectorDBError

__all__ = [
    "chunk_text",
    "initialize_vector_db",
    "get_sample_documents",
    "is_valid_collection_name",
    "sanitize_collection_name",
    "list_existing_collections",
]

logger = logging.getLogger(__name__)


def chunk_text(
    text: str, chunk_size: int = 500, chunk_overlap: int = 50
) -> list[str]:
    """Split text into overlapping chunks using recursive character splitting.

    Uses recursive splitting strategy to maintain semantic boundaries by splitting
    on progressively smaller delimiters (newlines, spaces, etc.) when needed.

    Args:
        text: The text string to split into chunks.
        chunk_size: Target size of each chunk in characters. Defaults to 500.
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
    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    if chunk_overlap < 0:
        raise ValueError("chunk_overlap must be >= 0")
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be < chunk_size")

    try:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size, chunk_overlap=chunk_overlap
        )
        chunks = splitter.split_text(text)
        logger.debug(
            f"Text split into {len(chunks)} chunks (size={chunk_size}, overlap={chunk_overlap})"
        )
        return chunks
    except Exception as e:
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
    documents: List[Dict[str, str]],
    persist_dir: str = KNOWLEDGE_DB_DIRECTORY,
    collection_name: str = "hybrid_rag_collection",
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
                        Defaults to "hybrid_rag_collection".

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
        client = chromadb.PersistentClient(path=persist_dir)

        # Delete existing collection if it exists
        try:
            client.delete_collection(name=collection_name)
            logger.debug(f"Deleted existing collection: {collection_name}")
        except NotFoundError:
            logger.debug(f"Collection {collection_name} did not exist, creating new one")

        # Initialize local sentence-transformers embedding function
        # Using local embeddings to avoid HF Inference API issues
        logger.debug("Initializing SentenceTransformer embeddings")
        embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"
        )
        typed_embedding_function = cast(
            EmbeddingFunction[Embeddable], embedding_function
        )

        # Create collection with cosine distance
        # Sentence-transformers produces normalized vectors, so cosine is appropriate
        collection = client.get_or_create_collection(
            name=collection_name,
            embedding_function=typed_embedding_function,
            metadata={"hnsw:space": "cosine"},
        )
        logger.debug(f"Created collection: {collection_name}")

        # Process and add documents to collection
        doc_ids: list[str] = []
        doc_texts: list[str] = []
        doc_metadatas: list[dict[str, str]] = []
        id_counter = 0

        for doc in documents:
            if "text" not in doc or "source" not in doc:
                raise ValueError("Each document must have 'text' and 'source' fields")

            chunks = chunk_text(doc["text"].strip())
            for chunk in chunks:
                doc_ids.append(f"doc_{id_counter}")
                doc_texts.append(chunk)
                doc_metadatas.append(
                    {"source": doc["source"], "text": doc["text"].strip()}
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
    import re

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
    import re

    sanitized = re.sub(r"[^a-zA-Z0-9_\-]", "_", name)
    sanitized = sanitized[:20]
    if len(sanitized) < 6:
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
        return [c.name for c in client.list_collections()]
    except Exception as e:
        logger.error(f"Failed to list collections in {persist_dir}: {e}")
        raise VectorDBError(
            f"Failed to list collections in '{persist_dir}': {e}"
        ) from e
