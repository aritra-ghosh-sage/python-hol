"""Custom exceptions for the hybrid RAG library."""

__all__ = [
    "HybridRAGException",
    "RetrieverNotInitializedError",
    "RetrievalError",
    "VectorDBError",
]


class HybridRAGException(Exception):
    """Base exception for all hybrid RAG library errors."""

    pass


class RetrieverNotInitializedError(HybridRAGException):
    """Raised when retriever is accessed before initialization."""

    pass


class RetrievalError(HybridRAGException):
    """Raised when document retrieval fails."""

    pass


class VectorDBError(HybridRAGException):
    """Raised when vector database operations fail."""

    pass
