"""Integration tests for API config persistence across restarts."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api import app, initialize_retriever
from hybrid_rag import KNOWLEDGE_DB_DIRECTORY


@pytest.fixture
def temp_knowledge_db():
    """Create a temporary knowledge database directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def client_with_temp_db(temp_knowledge_db):
    """Create test client with temporary database directory."""
    with patch("api.KNOWLEDGE_DB_DIRECTORY", temp_knowledge_db):
        with patch("hybrid_rag.KNOWLEDGE_DB_DIRECTORY", temp_knowledge_db):
            # Force re-initialization with temp directory
            with TestClient(app) as client:
                yield client


class TestConfigPersistenceAPI:
    """Test config persistence through the API layer."""

    def test_config_persists_after_update(self, client_with_temp_db, temp_knowledge_db):
        """Test that PUT /config persists settings to disk."""
        # Update config via API
        update_data = {
            "semantic_weight": 0.8,
            "keyword_weight": 0.2,
            "enable_rerank": False,
        }
        response = client_with_temp_db.put("/config", json=update_data)
        assert response.status_code == 200

        # Check that config.json was created
        config_file = Path(temp_knowledge_db) / "config.json"
        assert config_file.exists()

        # Verify content
        import json

        with open(config_file) as f:
            saved_config = json.load(f)

        assert saved_config["semantic_weight"] == 0.8
        assert saved_config["keyword_weight"] == 0.2
        assert saved_config["enable_rerank"] is False

    def test_config_loads_on_startup(self, temp_knowledge_db):
        """Test that persisted config is loaded on app startup."""
        # First, create a config file directly
        config_file = Path(temp_knowledge_db) / "config.json"
        config_file.parent.mkdir(parents=True, exist_ok=True)

        import json

        persisted_config = {
            "semantic_top_k": 10,
            "keyword_top_k": 10,
            "final_top_k": 5,
            "semantic_weight": 0.9,
            "keyword_weight": 0.1,
            "enable_rerank": False,
            "pre_rerank_top_k": 50,
            "collection_name": "rag_collection",
        }
        with open(config_file, "w") as f:
            json.dump(persisted_config, f)

        # Now initialize with patched directory
        with patch("api.KNOWLEDGE_DB_DIRECTORY", temp_knowledge_db):
            with patch("hybrid_rag.KNOWLEDGE_DB_DIRECTORY", temp_knowledge_db):
                with patch(
                    "hybrid_rag.persistence.KNOWLEDGE_DB_DIRECTORY", temp_knowledge_db
                ):
                    # Create new app instance to trigger startup
                    from api import app as new_app

                    client = TestClient(new_app)

                    # Query config
                    response = client.get("/config")
                    assert response.status_code == 200

                    data = response.json()
                    assert data["semantic_weight"] == 0.9
                    assert data["keyword_weight"] == 0.1
                    assert data["enable_rerank"] is False

    def test_default_config_when_no_persisted_file(self, client_with_temp_db):
        """Test that default config is used when no persisted file exists."""
        # Get config without any prior PUT
        response = client_with_temp_db.get("/config")
        assert response.status_code == 200

        data = response.json()
        # Should have default values
        assert data["semantic_weight"] == 0.7
        assert data["keyword_weight"] == 0.3
        assert data["enable_rerank"] is True

    def test_multiple_updates_persist_latest(self, client_with_temp_db, temp_knowledge_db):
        """Test that multiple config updates save the latest values."""
        # First update
        response = client_with_temp_db.put(
            "/config", json={"semantic_weight": 0.8, "keyword_weight": 0.2}
        )
        assert response.status_code == 200

        # Second update
        response = client_with_temp_db.put(
            "/config", json={"semantic_weight": 0.6, "keyword_weight": 0.4}
        )
        assert response.status_code == 200

        # Verify latest is persisted
        config_file = Path(temp_knowledge_db) / "config.json"
        import json

        with open(config_file) as f:
            saved_config = json.load(f)

        assert saved_config["semantic_weight"] == 0.6
        assert saved_config["keyword_weight"] == 0.4
