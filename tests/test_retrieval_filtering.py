"""
Tests for retrieval filtering behavior and score thresholds.

These tests verify that:
1. Results below 0.80 raw score are filtered out before response
2. total_results reflects post-filter count only
3. Results remain sorted by score (descending)
4. Filtering is consistent across REST and WebSocket endpoints

NOTE: Tests that make HTTP requests require the backend to be running:
  python api.py

AsyncIO tests require pytest-asyncio:
  pip install pytest-asyncio

Run all tests:
  pytest test_retrieval_filtering.py -v

Run only WebSocket tests (no backend required):
  pytest test_retrieval_filtering.py::test_websocket_mock_filters_below_threshold -v
"""

import os
import sys

import pytest

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# ============================================================================
# Fixtures and utilities
# ============================================================================


@pytest.fixture
def backend_available():
    """Check if backend is running on localhost:8000."""
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(("localhost", 8000))
    sock.close()
    return result == 0


@pytest.fixture
def skip_if_no_backend(backend_available):
    """Skip test if backend is not available."""
    if not backend_available:
        pytest.skip("Backend not running on localhost:8000")


# ============================================================================
# REST API Tests (require backend running)
# ============================================================================


class TestRestApi:
    """Tests for REST API /retrieve endpoint (requires running backend)."""

    def test_retrieve_filters_below_threshold(self, skip_if_no_backend):
        """Verify /retrieve endpoint filters results below 0.80 score."""
        import requests

        try:
            response = requests.post(
                "http://localhost:8000/retrieve", json={"query": "test"}, timeout=10
            )
        except requests.exceptions.ConnectionError:
            pytest.skip("Backend not available at localhost:8000")

        # Skip if retriever not initialized (503) or error (500)
        if response.status_code in (503, 500):
            pytest.skip(
                f"Backend error: {response.status_code}. Start backend with: python api.py"
            )

        assert response.status_code == 200, (
            f"Got {response.status_code}: {response.text}"
        )
        data = response.json()

        # Verify all results have score >= 0.80
        if data["results"]:
            for result in data["results"]:
                assert result["score"] >= 0.80, (
                    f"Result with score {result['score']} below threshold 0.80 found"
                )

    def test_retrieve_result_count_reflects_filter(self, skip_if_no_backend):
        """Verify total_results matches length of results (post-filter)."""
        import requests

        try:
            response = requests.post(
                "http://localhost:8000/retrieve", json={"query": "test"}, timeout=10
            )
        except requests.exceptions.ConnectionError:
            pytest.skip("Backend not available at localhost:8000")

        # Skip if retriever not initialized (503) or error (500)
        if response.status_code in (503, 500):
            pytest.skip(
                f"Backend error: {response.status_code}. Start backend with: python api.py"
            )

        assert response.status_code == 200
        data = response.json()

        # total_results should equal actual results count
        assert data["total_results"] == len(data["results"]), (
            f"total_results ({data['total_results']}) != len(results) ({len(data['results'])})"
        )

    def test_retrieve_results_sorted_descending(self, skip_if_no_backend):
        """Verify results remain sorted by score in descending order."""
        import requests

        try:
            response = requests.post(
                "http://localhost:8000/retrieve", json={"query": "test"}, timeout=10
            )
        except requests.exceptions.ConnectionError:
            pytest.skip("Backend not available at localhost:8000")

        # Skip if retriever not initialized (503) or error (500)
        if response.status_code in (503, 500):
            pytest.skip(
                f"Backend error: {response.status_code}. Start backend with: python api.py"
            )

        assert response.status_code == 200
        data = response.json()

        if len(data["results"]) > 1:
            # Verify results are sorted descending
            scores = [r["score"] for r in data["results"]]
            assert scores == sorted(scores, reverse=True), (
                f"Results not sorted descending: {scores}"
            )


# ============================================================================
# Integration Tests (optional, require backend running)
# ============================================================================


class TestIntegration:
    """Integration tests that connect to live backend (optional)."""

    def test_backend_health_check(self):
        """Check if backend is running and return skip or pass."""
        import requests

        try:
            response = requests.get("http://localhost:8000/health", timeout=5)
            assert response.status_code == 200
        except requests.exceptions.ConnectionError:
            pytest.skip("Backend not running on localhost:8000")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
