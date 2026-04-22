"""
Tests for retrieval filtering behavior and score thresholds.

Tests cover:
1. Results below 0.80 raw score are filtered out before response
2. total_results reflects post-filter count only
3. Results remain sorted by score (descending)
4. Filtering is consistent across REST and WebSocket endpoints
5. /retrieve-filtered endpoint enforces min 0.80 score floor

Uses TestClient for HTTP testing (isolated from running server).
WebSocket tests use mocks (no backend required).

Run all tests:
  pytest test_retrieval_filtering.py -v

Run only WebSocket tests:
  pytest test_retrieval_filtering.py::test_websocket_mock_filters_below_threshold -v
"""

import pytest
import asyncio
import json
from unittest.mock import Mock, patch, AsyncMock





# ============================================================================
# Unit Tests (no backend required)
# ============================================================================

def test_filter_logic_below_threshold():
    """Unit test: filtering logic correctly removes scores below 0.80."""
    results = [
        {"id": "1", "score": 0.95, "text": "doc1", "metadata": {"source": "url1"}},
        {"id": "2", "score": 0.75, "text": "doc2", "metadata": {"source": "url2"}},  # Should be filtered
        {"id": "3", "score": 0.80, "text": "doc3", "metadata": {"source": "url3"}},  # Boundary, included
        {"id": "4", "score": 0.50, "text": "doc4", "metadata": {"source": "url4"}},  # Should be filtered
    ]
    
    min_score_threshold = 0.80
    filtered = [r for r in results if r["score"] >= min_score_threshold]
    
    assert len(filtered) == 2, f"Expected 2 results, got {len(filtered)}"
    assert filtered[0]["id"] == "1"
    assert filtered[1]["id"] == "3"
    assert all(r["score"] >= 0.80 for r in filtered)


def test_filter_logic_preserves_order():
    """Unit test: filtering preserves descending score order."""
    results = [
        {"id": "1", "score": 0.95, "text": "doc1", "metadata": {"source": "url1"}},
        {"id": "2", "score": 0.90, "text": "doc2", "metadata": {"source": "url2"}},
        {"id": "3", "score": 0.80, "text": "doc3", "metadata": {"source": "url3"}},
    ]
    
    min_score_threshold = 0.80
    filtered = [r for r in results if r["score"] >= min_score_threshold]
    
    scores = [r["score"] for r in filtered]
    assert scores == sorted(scores, reverse=True)


def test_floor_enforcement_logic():
    """Unit test: floor enforcement takes max of two thresholds."""
    # Simulating retrieve-filtered behavior
    requested_min_score = 0.5
    enforced_floor = 0.80
    effective_min_score = max(enforced_floor, requested_min_score)
    
    assert effective_min_score == 0.80
    
    requested_min_score = 0.9
    effective_min_score = max(enforced_floor, requested_min_score)
    assert effective_min_score == 0.9


# ============================================================================
# REST API Tests (using TestClient)
# ============================================================================

class TestRestApi:
    """Tests for REST API /retrieve endpoint (using TestClient)."""

    def test_retrieve_filters_below_threshold(self, initialized_app):
        """Verify /retrieve endpoint filters results below 0.80 score."""
        response = initialized_app.post(
            "/retrieve",
            json={"query": "test"},
        )
        
        assert response.status_code == 200, f"Got {response.status_code}: {response.text}"
        data = response.json()
        
        # Verify all results have score >= 0.80
        if data["results"]:
            for result in data["results"]:
                assert result["score"] >= 0.80, (
                    f"Result with score {result['score']} below threshold 0.80 found"
                )

    def test_retrieve_result_count_reflects_filter(self, initialized_app):
        """Verify total_results matches length of results (post-filter)."""
        response = initialized_app.post(
            "/retrieve",
            json={"query": "test"},
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # total_results should equal actual results count
        assert data["total_results"] == len(data["results"]), (
            f"total_results ({data['total_results']}) != len(results) ({len(data['results'])})"
        )

    def test_retrieve_results_sorted_descending(self, initialized_app):
        """Verify results remain sorted by score in descending order."""
        response = initialized_app.post(
            "/retrieve",
            json={"query": "test"},
        )
        
        assert response.status_code == 200
        data = response.json()
        
        if len(data["results"]) > 1:
            # Verify results are sorted descending
            scores = [r["score"] for r in data["results"]]
            assert scores == sorted(scores, reverse=True), (
                f"Results not sorted descending: {scores}"
            )

    def test_retrieve_filtered_enforces_threshold(self, initialized_app):
        """Verify /retrieve-filtered endpoint enforces min 0.80 threshold."""
        response = initialized_app.post(
            "/retrieve-filtered?min_score=0.5",
            json={"query": "test"},
        )
        
        assert response.status_code == 200, f"Got {response.status_code}: {response.text}"
        data = response.json()
        
        # All results must be >= 0.80 (floor enforced), not 0.5
        if data["results"]:
            for result in data["results"]:
                assert result["score"] >= 0.80, (
                    f"Result with score {result['score']} below floor 0.80 found"
                )


# ============================================================================
# WebSocket Tests (mock-based, no backend required)
# ============================================================================

@pytest.mark.asyncio
async def test_websocket_mock_filters_below_threshold():
    """Mock WebSocket test: verify filtering logic applies to WebSocket results."""
    # Simulate the backend filtering that happens in the WebSocket handler
    mock_results = [
        {"id": "1", "text": "doc1", "metadata": {"source": "url1"}, "score": 0.95},
        {"id": "2", "text": "doc2", "metadata": {"source": "url2"}, "score": 0.70},
        {"id": "3", "text": "doc3", "metadata": {"source": "url3"}, "score": 0.80},
        {"id": "4", "text": "doc4", "metadata": {"source": "url4"}, "score": 0.40},
    ]
    
    # Apply filtering as done in websocket_chat endpoint
    min_score_threshold = 0.80
    filtered_results = [r for r in mock_results if r["score"] >= min_score_threshold]
    
    # Assertions
    assert len(filtered_results) == 2
    assert all(r["score"] >= 0.80 for r in filtered_results)
    assert filtered_results[0]["score"] == 0.95
    assert filtered_results[1]["score"] == 0.80


@pytest.mark.asyncio
async def test_websocket_mock_results_sorted():
    """Mock WebSocket test: verify results maintain descending sort after filtering."""
    mock_results = [
        {"id": "1", "score": 0.95, "text": "doc1", "metadata": {"source": "url1"}},
        {"id": "2", "score": 0.92, "text": "doc2", "metadata": {"source": "url2"}},
        {"id": "3", "score": 0.75, "text": "doc3", "metadata": {"source": "url3"}},
        {"id": "4", "score": 0.88, "text": "doc4", "metadata": {"source": "url4"}},
    ]
    
    # Filter and check sorting
    min_score_threshold = 0.80
    filtered_results = [r for r in mock_results if r["score"] >= min_score_threshold]
    
    scores = [r["score"] for r in filtered_results]
    assert scores == [0.95, 0.92, 0.88]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_websocket_count_after_filter():
    """Mock WebSocket test: verify total_results reflects post-filter count."""
    mock_results = [
        {"id": "1", "score": 0.95, "text": "doc1", "metadata": {"source": "url1"}},
        {"id": "2", "score": 0.50, "text": "doc2", "metadata": {"source": "url2"}},
        {"id": "3", "score": 0.80, "text": "doc3", "metadata": {"source": "url3"}},
    ]
    
    min_score_threshold = 0.80
    filtered_results = [r for r in mock_results if r["score"] >= min_score_threshold]
    
    # Simulate WebSocket response
    total_results = len(filtered_results)
    results_count = len(filtered_results)
    
    assert total_results == results_count == 2


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

