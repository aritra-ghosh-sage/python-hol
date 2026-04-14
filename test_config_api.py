#!/usr/bin/env python
"""Quick test script to verify the config update API endpoint works."""

import json
import logging
import sys
from typing import Any, Dict

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def create_session():
    """Create a requests session with retries."""
    session = requests.Session()
    retry = Retry(connect=3, backoff_factor=0.5, status_forcelist=(500, 502, 503, 504))
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    return session


def test_api(base_url: str = "http://localhost:8000", wait_for_startup: bool = False) -> int:
    """Test the config update API endpoints.
    
    Args:
        base_url: Base URL of the API
        wait_for_startup: Whether to wait for API startup
        
    Returns:
        Exit code (0 for success, 1 for failure)
    """
    session = create_session()
    
    # Wait for API startup if requested
    if wait_for_startup:
        logger.info("Waiting for API to start up...")
        import time
        for attempt in range(30):
            try:
                response = session.get(f"{base_url}/health", timeout=1)
                if response.status_code == 200:
                    logger.info("✓ API is ready")
                    break
            except requests.RequestException:
                if attempt < 29:
                    time.sleep(1)
                else:
                    logger.error("✗ API failed to start")
                    return 1
    
    try:
        # Test 1: Health check
        logger.info("\n" + "=" * 60)
        logger.info("Test 1: Health Check")
        logger.info("=" * 60)
        response = session.get(f"{base_url}/health")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        logger.info(f"✓ Health check: {response.json()}")
        
        # Test 2: Get current config
        logger.info("\n" + "=" * 60)
        logger.info("Test 2: Get Current Configuration")
        logger.info("=" * 60)
        response = session.get(f"{base_url}/config")
        assert response.status_code == 200
        config = response.json()
        logger.info(f"✓ Current config:")
        logger.info(f"  semantic_weight: {config['semantic_weight']}")
        logger.info(f"  keyword_weight: {config['keyword_weight']}")
        logger.info(f"  enable_rerank: {config['enable_rerank']}")
        
        # Test 3: Update configuration (valid)
        logger.info("\n" + "=" * 60)
        logger.info("Test 3: Update Configuration (Valid)")
        logger.info("=" * 60)
        update_data = {
            "semantic_weight": 0.8,
            "keyword_weight": 0.2,
            "enable_rerank": False,
        }
        logger.info(f"Updating with: {update_data}")
        response = session.put(
            f"{base_url}/config",
            json=update_data,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        updated_config = response.json()
        logger.info(f"✓ Configuration updated:")
        logger.info(f"  semantic_weight: {updated_config['semantic_weight']}")
        logger.info(f"  keyword_weight: {updated_config['keyword_weight']}")
        logger.info(f"  enable_rerank: {updated_config['enable_rerank']}")
        
        # Verify values changed
        assert updated_config["semantic_weight"] == 0.8
        assert updated_config["keyword_weight"] == 0.2
        assert updated_config["enable_rerank"] is False
        logger.info("✓ Values correctly updated")
        
        # Test 4: Update configuration (invalid - weights don't sum)
        logger.info("\n" + "=" * 60)
        logger.info("Test 4: Update Configuration (Invalid Weights)")
        logger.info("=" * 60)
        invalid_data = {
            "semantic_weight": 0.6,
            "keyword_weight": 0.6,
        }
        logger.info(f"Attempting to update with invalid weights: {invalid_data}")
        response = session.put(
            f"{base_url}/config",
            json=invalid_data,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 400, f"Expected 400, got {response.status_code}"
        logger.info(f"✓ Correctly rejected invalid update: {response.json()['detail']}")
        
        # Test 5: Update configuration (invalid - unknown parameter)
        logger.info("\n" + "=" * 60)
        logger.info("Test 5: Update Configuration (Unknown Parameter)")
        logger.info("=" * 60)
        invalid_data = {"invalid_param": 123}
        logger.info(f"Attempting to update with unknown parameter: {invalid_data}")
        response = session.put(
            f"{base_url}/config",
            json=invalid_data,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 400, f"Expected 400, got {response.status_code}"
        logger.info(f"✓ Correctly rejected unknown parameter: {response.json()['detail']}")
        
        # Test 6: Partial update (only update one value)
        logger.info("\n" + "=" * 60)
        logger.info("Test 6: Partial Configuration Update")
        logger.info("=" * 60)
        partial_data = {"semantic_top_k": 15}
        logger.info(f"Partially updating with: {partial_data}")
        response = session.put(
            f"{base_url}/config",
            json=partial_data,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 200
        updated_config = response.json()
        logger.info(f"✓ Partial update successful")
        logger.info(f"  semantic_top_k: {updated_config['semantic_top_k']}")
        assert updated_config["semantic_top_k"] == 15
        
        # Test 7: Verify config persists
        logger.info("\n" + "=" * 60)
        logger.info("Test 7: Verify Configuration Persistence")
        logger.info("=" * 60)
        response = session.get(f"{base_url}/config")
        assert response.status_code == 200
        current_config = response.json()
        logger.info(f"✓ Current config persists:")
        logger.info(f"  semantic_top_k: {current_config['semantic_top_k']}")
        assert current_config["semantic_top_k"] == 15
        
        logger.info("\n" + "=" * 60)
        logger.info("✓ ALL TESTS PASSED")
        logger.info("=" * 60)
        return 0
        
    except AssertionError as e:
        logger.error(f"✗ Test failed: {e}")
        return 1
    except Exception as e:
        logger.error(f"✗ Unexpected error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Test config update API endpoints")
    parser.add_argument("--url", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--wait", action="store_true", help="Wait for API startup")
    args = parser.parse_args()
    
    sys.exit(test_api(args.url, args.wait))
