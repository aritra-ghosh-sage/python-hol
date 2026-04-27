"""Tests for HybridRetrieverConfig configuration class."""

import pytest

from hybrid_rag.config import DEFAULT_CONFIG, HybridRetrieverConfig


class TestHybridRetrieverConfig:
    """Test the HybridRetrieverConfig class."""

    def test_default_config_has_collection_name(self):
        """DEFAULT_CONFIG includes collection_name with correct default value."""
        assert hasattr(DEFAULT_CONFIG, "collection_name")
        assert DEFAULT_CONFIG.collection_name == "hybrid_rag_collection"

    def test_config_creation_with_collection_name(self):
        """HybridRetrieverConfig can be created with collection_name parameter."""
        config = HybridRetrieverConfig(collection_name="test_collection")
        assert config.collection_name == "test_collection"

    def test_config_creation_without_collection_name_uses_default(self):
        """HybridRetrieverConfig uses default collection_name when not specified."""
        config = HybridRetrieverConfig()
        assert config.collection_name == "hybrid_rag_collection"

    def test_config_update_with_collection_name(self):
        """config.update() supports collection_name parameter."""
        config = HybridRetrieverConfig(collection_name="original")
        updated = config.update(collection_name="updated")

        assert updated.collection_name == "updated"
        # Original should be unchanged (immutable pattern)
        assert config.collection_name == "original"

    def test_config_update_with_collection_name_and_other_params(self):
        """config.update() supports collection_name along with other parameters."""
        config = HybridRetrieverConfig()
        updated = config.update(
            collection_name="custom_collection",
            semantic_weight=0.8,
            keyword_weight=0.2,
        )

        assert updated.collection_name == "custom_collection"
        assert updated.semantic_weight == 0.8
        assert updated.keyword_weight == 0.2

    def test_config_to_dict_includes_collection_name(self):
        """config.to_dict() includes collection_name in the returned dictionary."""
        config = HybridRetrieverConfig(collection_name="test_dict")
        config_dict = config.to_dict()

        assert "collection_name" in config_dict
        assert config_dict["collection_name"] == "test_dict"

    def test_config_to_dict_with_default_collection_name(self):
        """config.to_dict() includes default collection_name."""
        config = HybridRetrieverConfig()
        config_dict = config.to_dict()

        assert "collection_name" in config_dict
        assert config_dict["collection_name"] == "hybrid_rag_collection"

    def test_config_to_dict_includes_all_fields(self):
        """config.to_dict() includes collection_name along with all other fields."""
        config = HybridRetrieverConfig(collection_name="complete_test")
        config_dict = config.to_dict()

        expected_fields = {
            "semantic_top_k",
            "keyword_top_k",
            "final_top_k",
            "semantic_weight",
            "keyword_weight",
            "enable_rerank",
            "pre_rerank_top_k",
            "collection_name",
        }
        assert set(config_dict.keys()) == expected_fields
        assert config_dict["collection_name"] == "complete_test"

    def test_config_update_with_unknown_param_raises_type_error(self):
        """config.update() raises TypeError for unknown parameters."""
        config = HybridRetrieverConfig()

        with pytest.raises(TypeError, match="Unknown configuration parameter"):
            config.update(unknown_param="value")

    def test_config_immutability_with_collection_name(self):
        """Updating collection_name returns new instance, original unchanged."""
        original = HybridRetrieverConfig(collection_name="original")
        updated = original.update(collection_name="updated")

        assert original.collection_name == "original"
        assert updated.collection_name == "updated"
        assert id(original) != id(updated)

    def test_collection_name_type_is_string(self):
        """collection_name field is of type string."""
        config = HybridRetrieverConfig()
        assert isinstance(config.collection_name, str)

    def test_collection_name_empty_string_raises_value_error(self):
        """collection_name rejects empty strings."""
        with pytest.raises(ValueError, match="collection_name must be a non-empty string"):
            HybridRetrieverConfig(collection_name="")

    def test_collection_name_whitespace_only_raises_value_error(self):
        """collection_name rejects whitespace-only strings."""
        with pytest.raises(ValueError, match="collection_name must be a non-empty string"):
            HybridRetrieverConfig(collection_name="   ")

    def test_collection_name_with_hyphens_and_underscores(self):
        """collection_name accepts hyphens and underscores."""
        config = HybridRetrieverConfig(collection_name="test_collection-v2")
        assert config.collection_name == "test_collection-v2"

    def test_default_config_all_fields_match_expected_values(self):
        """DEFAULT_CONFIG has all expected field values including collection_name."""
        assert DEFAULT_CONFIG.semantic_weight == 0.7
        assert DEFAULT_CONFIG.keyword_weight == 0.3
        assert DEFAULT_CONFIG.enable_rerank is True
        assert DEFAULT_CONFIG.collection_name == "hybrid_rag_collection"
        # Also check default values for fields not specified in DEFAULT_CONFIG
        assert DEFAULT_CONFIG.semantic_top_k == 10
        assert DEFAULT_CONFIG.keyword_top_k == 10
        assert DEFAULT_CONFIG.final_top_k == 5
        assert DEFAULT_CONFIG.pre_rerank_top_k == 50

    def test_config_update_only_collection_name(self):
        """config.update() can update only collection_name without other params."""
        config = HybridRetrieverConfig()
        original_semantic_weight = config.semantic_weight
        updated = config.update(collection_name="new_name")

        assert updated.collection_name == "new_name"
        # Other fields should remain unchanged
        assert updated.semantic_weight == original_semantic_weight

