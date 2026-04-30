"""Tests for GET /collections endpoint.

Verifies that get_collections() enumerates ALL collections on disk,
not just the single active collection.
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import api
from hybrid_rag.exceptions import VectorDBError


ACTIVE_COLLECTION_NAME = "rag_coll_test"
OTHER_COLLECTION_NAME = "other_coll_x"


class TestGetCollections:
    """Covers the GET /collections endpoint behaviour."""

    def test_active_collection_included_in_response(
        self, fake_initialized_app: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Active collection appears in the response."""
        api._retriever.collection.name = ACTIVE_COLLECTION_NAME  # type: ignore[union-attr]
        api._retriever.collection.count.return_value = 5  # type: ignore[union-attr]

        # Mock chromadb client to return the active collection
        mock_collection = MagicMock()
        mock_collection.name = ACTIVE_COLLECTION_NAME
        mock_chroma_client = MagicMock()
        mock_chroma_client.list_collections.return_value = [mock_collection]
        monkeypatch.setattr(api.chromadb, "PersistentClient", lambda path: mock_chroma_client)

        response = fake_initialized_app.get("/collections")
        assert response.status_code == 200
        data = response.json()
        names = [c["name"] for c in data["collections"]]
        assert ACTIVE_COLLECTION_NAME in names

    def test_multiple_collections_all_appear(
        self, fake_initialized_app: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """All collections returned by list_existing_collections appear in response with correct counts."""
        api._retriever.collection.name = ACTIVE_COLLECTION_NAME  # type: ignore[union-attr]
        api._retriever.collection.count.return_value = 10  # type: ignore[union-attr]

        # Mock collections
        mock_active = MagicMock()
        mock_active.name = ACTIVE_COLLECTION_NAME
        mock_other = MagicMock()
        mock_other.name = OTHER_COLLECTION_NAME

        mock_chroma_client = MagicMock()
        mock_chroma_client.list_collections.return_value = [mock_active, mock_other]

        # Mock get_collection for non-active collection
        mock_other_collection_handle = MagicMock()
        mock_other_collection_handle.count.return_value = 3
        mock_chroma_client.get_collection.return_value = mock_other_collection_handle

        monkeypatch.setattr(api.chromadb, "PersistentClient", lambda path: mock_chroma_client)

        response = fake_initialized_app.get("/collections")
        assert response.status_code == 200
        data = response.json()
        collections = data["collections"]

        # Verify both collections present
        assert len(collections) == 2
        names = [c["name"] for c in collections]
        assert ACTIVE_COLLECTION_NAME in names
        assert OTHER_COLLECTION_NAME in names

        # Verify correct counts
        for collection in collections:
            if collection["name"] == ACTIVE_COLLECTION_NAME:
                assert collection["count"] == 10
            elif collection["name"] == OTHER_COLLECTION_NAME:
                assert collection["count"] == 3

    def test_collection_info_has_correct_name_and_count(
        self, fake_initialized_app: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Each CollectionInfo carries the correct name and count."""
        api._retriever.collection.name = ACTIVE_COLLECTION_NAME  # type: ignore[union-attr]
        api._retriever.collection.count.return_value = 7  # type: ignore[union-attr]

        # Mock chromadb client to return the active collection
        mock_collection = MagicMock()
        mock_collection.name = ACTIVE_COLLECTION_NAME
        mock_chroma_client = MagicMock()
        mock_chroma_client.list_collections.return_value = [mock_collection]
        monkeypatch.setattr(api.chromadb, "PersistentClient", lambda path: mock_chroma_client)

        response = fake_initialized_app.get("/collections")
        assert response.status_code == 200
        info = response.json()["collections"][0]
        assert info["name"] == ACTIVE_COLLECTION_NAME
        assert info["count"] == 7

    def test_returns_500_when_collection_uninitialized(
        self, fake_initialized_app: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Returns HTTP 500 when the retriever's collection handle is None."""
        # Simulate uninitialized collection (retriever exists but collection is None)
        api._retriever.collection = None  # type: ignore[assignment]

        response = fake_initialized_app.get("/collections")
        assert response.status_code == 500

    def test_returns_503_when_retriever_uninitialized(
        self, fake_initialized_app: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Returns HTTP 503 when the retriever has not been initialized."""
        monkeypatch.setattr(api, "_retriever", None)

        response = fake_initialized_app.get("/collections")
        assert response.status_code == 503

    def test_vectordb_error_returns_500(
        self, fake_initialized_app: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """VectorDBError from chromadb client surfaces as HTTP 500."""
        api._retriever.collection.name = ACTIVE_COLLECTION_NAME  # type: ignore[union-attr]

        def _raise_on_persistent_client(path: str):
            raise VectorDBError("Failed to create ChromaDB client")

        monkeypatch.setattr(api.chromadb, "PersistentClient", _raise_on_persistent_client)

        response = fake_initialized_app.get("/collections")
        assert response.status_code == 500
