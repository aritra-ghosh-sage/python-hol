"""Configuration classes and models for hybrid retrieval."""

from dataclasses import dataclass, field, replace
from typing import Any, Dict, Optional

__all__ = ["HybridRetrieverConfig", "DEFAULT_CONFIG"]


@dataclass
class HybridRetrieverConfig:
    """Configuration parameters for hybrid retrieval combining semantic and keyword search.

    This configuration controls the behavior of the hybrid retrieval pipeline including
    semantic search, keyword search, score fusion, and optional reranking.

    Attributes:
        semantic_top_k: Number of results to retrieve from semantic search. Defaults to 10.
        keyword_top_k: Number of results to retrieve from keyword search. Defaults to 10.
        final_top_k: Maximum number of final deduplicated results to return. Defaults to 5.
        semantic_weight: Weight factor for semantic search scores in fusion (0-1). Defaults to 0.65.
        keyword_weight: Weight factor for keyword search scores in fusion (0-1). Defaults to 0.35.
        enable_rerank: Whether to apply cross-encoder reranking for better ranking. Defaults to True.
        pre_rerank_top_k: Number of candidates to rerank before selecting final_top_k. Defaults to 50.

    Raises:
        ValueError: If weights don't sum to approximately 1.0 or are not in valid range.
    """

    semantic_top_k: int = 10
    keyword_top_k: int = 10
    final_top_k: int = 5

    semantic_weight: float = 0.65
    keyword_weight: float = 0.35

    enable_rerank: bool = True
    pre_rerank_top_k: int = 50

    def __post_init__(self) -> None:
        """Validate configuration parameters after initialization."""
        if not (0 < self.semantic_top_k):
            raise ValueError("semantic_top_k must be > 0")
        if not (0 < self.keyword_top_k):
            raise ValueError("keyword_top_k must be > 0")
        if not (0 < self.final_top_k):
            raise ValueError("final_top_k must be > 0")

        weight_sum = self.semantic_weight + self.keyword_weight
        if not (0.99 <= weight_sum <= 1.01):
            raise ValueError(
                f"semantic_weight + keyword_weight must equal 1.0, got {weight_sum}"
            )

        if not (0 <= self.semantic_weight <= 1):
            raise ValueError("semantic_weight must be in range [0, 1]")
        if not (0 <= self.keyword_weight <= 1):
            raise ValueError("keyword_weight must be in range [0, 1]")

        if not (0 < self.pre_rerank_top_k):
            raise ValueError("pre_rerank_top_k must be > 0")

    def update(self, **kwargs: Any) -> "HybridRetrieverConfig":
        """Create a new config instance with updated values.

        Validates all parameters before returning a new instance.
        Original config is not modified (immutable update pattern).

        Args:
            **kwargs: Configuration parameters to update. Valid keys are:
                - semantic_top_k, keyword_top_k, final_top_k
                - semantic_weight, keyword_weight
                - enable_rerank, pre_rerank_top_k

        Returns:
            New HybridRetrieverConfig instance with updated values.

        Raises:
            ValueError: If any parameter is invalid or validation fails.
            TypeError: If an unknown parameter is provided.

        Example:
            >>> config = HybridRetrieverConfig()
            >>> new_config = config.update(semantic_weight=0.8, keyword_weight=0.2)
            >>> new_config.semantic_weight
            0.8
        """
        # Validate that only known parameters are provided
        valid_params = {
            "semantic_top_k",
            "keyword_top_k",
            "final_top_k",
            "semantic_weight",
            "keyword_weight",
            "enable_rerank",
            "pre_rerank_top_k",
        }
        unknown_params = set(kwargs.keys()) - valid_params
        if unknown_params:
            raise TypeError(
                f"Unknown configuration parameter(s): {', '.join(unknown_params)}"
            )

        # Create new instance with updated values
        updated_config = replace(self, **kwargs)
        # __post_init__ is called automatically, so validation happens here
        return updated_config

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary.

        Returns:
            Dictionary representation of the configuration.

        Example:
            >>> config = HybridRetrieverConfig()
            >>> config_dict = config.to_dict()
            >>> config_dict["semantic_weight"]
            0.65
        """
        return {
            "semantic_top_k": self.semantic_top_k,
            "keyword_top_k": self.keyword_top_k,
            "final_top_k": self.final_top_k,
            "semantic_weight": self.semantic_weight,
            "keyword_weight": self.keyword_weight,
            "enable_rerank": self.enable_rerank,
            "pre_rerank_top_k": self.pre_rerank_top_k,
        }


# Default configuration instance
DEFAULT_CONFIG = HybridRetrieverConfig(
    semantic_weight=0.7,
    keyword_weight=0.3,
    enable_rerank=True,
)
