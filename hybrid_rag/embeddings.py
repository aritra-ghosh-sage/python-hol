"""Embedding helpers for offline-safe initialization.

Provides a deterministic hash-based embedding fallback when the default
sentence-transformer model cannot be loaded (e.g., offline test runs).
"""

from __future__ import annotations

import hashlib
import logging
import os
from typing import List

import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_HASH_EMBEDDING_DIMENSIONS = 32


def get_embedding_backend() -> str:
    """Return the configured embedding backend name.

    Reads HYBRID_RAG_EMBEDDING_BACKEND and defaults to "sentence-transformer".

    Returns:
        Lowercase backend identifier string.
    """

    return os.getenv("HYBRID_RAG_EMBEDDING_BACKEND", "sentence-transformer").lower()


def hash_text_to_vector(text: str, dimensions: int = DEFAULT_HASH_EMBEDDING_DIMENSIONS) -> List[float]:
    """Generate a deterministic embedding vector from text.

    Args:
        text: Input text to embed.
        dimensions: Desired output vector length.

    Returns:
        List of float values in the range [0.0, 1.0].
    """

    values: List[float] = []
    salt = 0
    while len(values) < dimensions:
        digest = hashlib.sha256(f"{salt}:{text}".encode("utf-8")).digest()
        values.extend(byte / 255.0 for byte in digest)
        salt += 1
    return values[:dimensions]


class HashEmbeddingFunction:
    """Deterministic embedding function for ChromaDB fallback usage."""

    def __init__(self, dimensions: int = DEFAULT_HASH_EMBEDDING_DIMENSIONS) -> None:
        self._dimensions = dimensions

    def __call__(self, input: List[str]) -> List[List[float]]:
        return [hash_text_to_vector(text, self._dimensions) for text in input]

    def name(self) -> str:
        """Return an identifier for ChromaDB embedding compatibility."""
        return "hash-embedding"


class HashEmbeddingEncoder:
    """Deterministic encoder compatible with HybridRetriever."""

    def __init__(self, dimensions: int = DEFAULT_HASH_EMBEDDING_DIMENSIONS) -> None:
        self._dimensions = dimensions

    def encode(self, text: str) -> np.ndarray:
        return np.asarray(hash_text_to_vector(text, self._dimensions), dtype=float)
