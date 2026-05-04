"""Tests for configuration persistence functionality."""

import json
import tempfile
from pathlib import Path

import pytest

from hybrid_rag import (
    HybridRetrieverConfig,
    load_config_from_disk,
    save_config_to_disk,
)


class TestConfigPersistence:
    """Test configuration save/load functionality."""

    def test_save_config_creates_directory(self):
        """Test that save_config_to_disk creates directory if it doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            persist_dir = str(Path(tmpdir) / "new_dir")
            config = HybridRetrieverConfig(
                semantic_weight=0.8, keyword_weight=0.2, enable_rerank=False
            )

            save_config_to_disk(config, persist_dir)

            assert Path(persist_dir).exists()
            config_file = Path(persist_dir) / "config.json"
            assert config_file.exists()

    def test_save_load_roundtrip(self):
        """Test saving and loading config preserves values."""
        with tempfile.TemporaryDirectory() as tmpdir:
            original_config = HybridRetrieverConfig(
                semantic_top_k=15,
                keyword_top_k=12,
                final_top_k=8,
                semantic_weight=0.75,
                keyword_weight=0.25,
                enable_rerank=False,
                pre_rerank_top_k=40,
                collection_name="test_collection",
            )

            save_config_to_disk(original_config, tmpdir)
            loaded_config = load_config_from_disk(tmpdir)

            assert loaded_config is not None
            assert loaded_config.semantic_top_k == original_config.semantic_top_k
            assert loaded_config.keyword_top_k == original_config.keyword_top_k
            assert loaded_config.final_top_k == original_config.final_top_k
            assert loaded_config.semantic_weight == original_config.semantic_weight
            assert loaded_config.keyword_weight == original_config.keyword_weight
            assert loaded_config.enable_rerank == original_config.enable_rerank
            assert loaded_config.pre_rerank_top_k == original_config.pre_rerank_top_k
            assert loaded_config.collection_name == original_config.collection_name

    def test_load_nonexistent_config_returns_none(self):
        """Test loading from directory without config.json returns None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            loaded_config = load_config_from_disk(tmpdir)
            assert loaded_config is None

    def test_load_invalid_json_returns_none(self):
        """Test loading invalid JSON returns None and logs warning."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "config.json"
            config_file.write_text("{ invalid json }")

            loaded_config = load_config_from_disk(tmpdir)
            assert loaded_config is None

    def test_load_invalid_config_values_returns_none(self):
        """Test loading config with invalid values returns None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "config.json"
            # Invalid: weights don't sum to 1.0
            invalid_config = {
                "semantic_weight": 0.9,
                "keyword_weight": 0.5,  # Sum is 1.4, not ~1.0
                "enable_rerank": True,
            }
            config_file.write_text(json.dumps(invalid_config))

            loaded_config = load_config_from_disk(tmpdir)
            assert loaded_config is None

    def test_save_config_atomic_write(self):
        """Test that save_config_to_disk uses atomic write (temp file + rename)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = HybridRetrieverConfig(
                semantic_weight=0.6, keyword_weight=0.4
            )

            save_config_to_disk(config, tmpdir)

            config_file = Path(tmpdir) / "config.json"
            assert config_file.exists()
            # Temp file should not exist after successful save
            temp_file = Path(tmpdir) / "config.tmp"
            assert not temp_file.exists()

    def test_load_config_with_all_defaults(self):
        """Test loading config that uses all default values."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Save config with default values
            default_config = HybridRetrieverConfig()
            save_config_to_disk(default_config, tmpdir)

            loaded_config = load_config_from_disk(tmpdir)
            assert loaded_config is not None
            assert loaded_config.semantic_weight == 0.65
            assert loaded_config.keyword_weight == 0.35
            assert loaded_config.enable_rerank is True
            assert loaded_config.collection_name == "rag_collection"

    def test_config_to_dict_from_dict_roundtrip(self):
        """Test HybridRetrieverConfig.to_dict() and from_dict() methods."""
        original_config = HybridRetrieverConfig(
            semantic_top_k=20,
            semantic_weight=0.9,
            keyword_weight=0.1,
            collection_name="custom_coll",
        )

        config_dict = original_config.to_dict()
        assert isinstance(config_dict, dict)
        assert config_dict["semantic_top_k"] == 20
        assert config_dict["semantic_weight"] == 0.9

        restored_config = HybridRetrieverConfig.from_dict(config_dict)
        assert restored_config.semantic_top_k == original_config.semantic_top_k
        assert restored_config.semantic_weight == original_config.semantic_weight
        assert restored_config.keyword_weight == original_config.keyword_weight
        assert restored_config.collection_name == original_config.collection_name
