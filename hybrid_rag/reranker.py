"""Cross-encoder based document reranking module."""

import logging
import math
import os
from typing import Any

from dotenv import load_dotenv
from sentence_transformers import CrossEncoder

from .constants import DEFAULT_RERANKER_MODEL_PATH

load_dotenv()

__all__ = ["CrossEncoderReranker"]

logger = logging.getLogger(__name__)


class CrossEncoderReranker:
    """Reranker using cross-encoder model to score document relevance to query.

    The cross-encoder directly scores query-document pairs, providing more accurate
    relevance judgments than embedding similarity alone. Uses the ms-marco MiniLM
    cross-encoder model for efficient computation.

    On first initialization the model is downloaded from Hugging Face and saved to
    *model_path*. Every subsequent initialization loads the weights directly from
    disk, avoiding any network requests to Hugging Face.

    Attributes:
        model: The loaded cross-encoder model for predicting query-document relevance.

    Example:
        >>> reranker = CrossEncoderReranker()
        >>> docs = [{"text": "Document 1"}, {"text": "Document 2"}]
        >>> ranked = reranker.rerank("query text", docs)
    """

    _MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    def __init__(self, model_path: str = DEFAULT_RERANKER_MODEL_PATH) -> None:
        """Initialize the cross-encoder reranker, loading from local path when available.

        On first run the model is downloaded from Hugging Face and persisted to
        *model_path*. Subsequent calls load directly from disk, removing the
        dependency on the Hugging Face endpoint at inference time.

        Args:
            model_path: Directory path to store/load the cross-encoder model.
                Defaults to DEFAULT_RERANKER_MODEL_PATH.

        Raises:
            ImportError: If sentence-transformers is not installed.
        """
        try:
            hf_token = os.environ.get("HF_TOKEN")
            local_path = os.path.abspath(model_path)

            if os.path.isdir(local_path) and os.path.exists(
                os.path.join(local_path, "config.json")
            ):
                logger.info(
                    "Loading cross-encoder model from local path: %s", local_path
                )
                self.model = CrossEncoder(local_path, token=hf_token)
            else:
                logger.info(
                    "Downloading cross-encoder model '%s' and saving to %s",
                    self._MODEL_NAME,
                    local_path,
                )
                self.model = CrossEncoder(self._MODEL_NAME, token=hf_token)
                os.makedirs(local_path, exist_ok=True)
                self.model.save(local_path)
                logger.info(
                    "Cross-encoder model saved locally at %s; "
                    "future loads will use this path.",
                    local_path,
                )

            logger.info("Cross-encoder reranker initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize cross-encoder reranker: {e}")
            raise

    @staticmethod
    def _sigmoid(x: float) -> float:
        """Apply sigmoid function to normalize logits to [0, 1] range.

        Converts unbounded model logits to probabilities using the sigmoid function.

        Args:
            x: Raw logit score from cross-encoder model.

        Returns:
            Normalized score in [0, 1] range.

        Example:
            >>> CrossEncoderReranker._sigmoid(0)
            0.5
        """
        return 1 / (1 + math.exp(-x))

    def rerank(
        self, query: str, docs: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Rerank documents by computing cross-encoder scores and sorting.

        Scores each document relative to the query using the cross-encoder model,
        normalizes scores via sigmoid, and returns documents sorted by relevance.

        Args:
            query: The search query string used for scoring documents.
            docs: List of document dictionaries. Expected to have 'text' and 'score' keys.
                  The 'score' key will be overwritten with cross-encoder scores.

        Returns:
            List of documents sorted by cross-encoder relevance scores in descending order.

        Raises:
            ValueError: If docs list is empty or any document lacks a 'text' field.

        Example:
            >>> reranker = CrossEncoderReranker()
            >>> docs = [
            ...     {"id": "1", "text": "Sample text", "score": 0.5},
            ...     {"id": "2", "text": "Other text", "score": 0.3}
            ... ]
            >>> ranked = reranker.rerank("query", docs)
        """
        if not docs:
            logger.warning("No documents provided for reranking")
            return []

        try:
            # Create query-document pairs for the model
            pairs = [(query, d["text"]) for d in docs]
            logger.debug(f"Reranking {len(pairs)} document pairs")

            # Get raw scores from cross-encoder
            scores = self.model.predict(pairs)

            # Normalize scores and update documents
            for doc, score in zip(docs, scores):
                normalized_score = self._sigmoid(float(score))
                doc["score"] = normalized_score
                logger.debug(f"Document {doc.get('id')}: raw={score:.3f}, normalized={normalized_score:.3f}")

            # Sort by normalized score in descending order
            ranked_docs = sorted(docs, key=lambda x: x["score"], reverse=True)
            logger.debug(f"Reranking complete. Top score: {ranked_docs[0]['score']:.3f}")
            return ranked_docs

        except KeyError as e:
            logger.error(f"Missing required field in document: {e}")
            raise ValueError(f"Document missing required field: {e}") from e
        except Exception as e:
            logger.error(f"Reranking failed: {e}")
            raise
