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

        monkeypatch.setattr(api, "list_existing_collections", lambda _: [ACTIVE_COLLECTION_NAME])

        response = fake_initialized_app.get("/collections")
        assert response.status_code == 200
        data = response.json()
        names = [c["name"] for c in data["collections"]]
        assert ACTIVE_COLLECTION_NAME in names

    def test_multiple_collections_all_appear(
        self, fake_initialized_app: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """All collections returned by list_existing_collections appear in response."""
        api._retriever.collection.name = ACTIVE_COLLECTION_NAME  # type: ignore[union-attr]
        all_names = [ACTIVE_COLLECTION_NAME, OTHER_COLLECTION_NAME]

        mock_other_coll = MagicMock()
        mock_other_coll.count.return_value = 3
        mock_chroma_client = MagicMock()
        mock_chroma_client.get_collection.return_value = mock_other_coll

        mock_chromadb = MagicMock()
        mock_chromadb.PersistentClient.return_value = mock_chroma_client

        monkeypatch.setattr(api, "list_existing_collections", lambda _: all_names)
        monkeypatch.setattr(api, "chromadb", mock_chromadb)

        response = fake_initialized_app.get("/collections")
        assert response.status_code == 200
        data = response.json()
        names = [c["name"] for c in data["collections"]]
        assert ACTIVE_COLLECTION_NAME in names
        assert OTHER_COLLECTION_NAME in names
        assert len(data["collections"]) == 2

    def test_collection_info_has_correct_name_and_count(
        self, fake_initialized_app: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Each CollectionInfo carries the correct name and count."""
        api._retriever.collection.name = ACTIVE_COLLECTION_NAME  # type: ignore[union-attr]
        api._retriever.collection.count.return_value = 7  # type: ignore[union-attr]

        monkeypatch.setattr(api, "list_existing_collections", lambda _: [ACTIVE_COLLECTION_NAME])

        response = fake_initialized_app.get("/collections")
        assert response.status_code == 200
        info = response.json()["collections"][0]
        assert info["name"] == ACTIVE_COLLECTION_NAME
        assert info["count"] == 7

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
        """VectorDBError from list_existing_collections surfaces as HTTP 500."""

        def _raise(_: str) -> list[str]:
            raise VectorDBError("disk read failure")

        monkeypatch.setattr(api, "list_existing_collections", _raise)

        response = fake_initialized_app.get("/collections")
        assert response.status_code == 500
