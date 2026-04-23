"""WebSocket connectivity test with pytest support."""
import pytest
import asyncio
import websockets
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


@pytest.mark.asyncio
async def test_ws_connection_and_basic_message():
    """Test WebSocket connection and receipt of status/results messages."""
    uri = "ws://localhost:8000/ws/chat"
    
    try:
        async with websockets.connect(uri) as websocket:
            print("✓ WebSocket connected!")
            
            # Send a test query
            await websocket.send(json.dumps({"query": "test", "enable_rerank": False}))
            
            # Receive status message
            status_response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
            status_data = json.loads(status_response)
            print(f"✓ Received message type: {status_data.get('type')}")
            
            if status_data.get('type') == 'status':
                print(f"✓ Status message: {status_data.get('message')}")
                assert True
            else:
                pytest.fail(f"Expected status message, got {status_data.get('type')}")
                
    except asyncio.TimeoutError:
        pytest.fail("WebSocket request timed out - backend may not be running")
    except (ConnectionRefusedError, OSError):
        pytest.skip("Backend not running on localhost:8000")
    except Exception as e:
        err_str = str(e).lower()
        if "connect call failed" in err_str or "connection refused" in err_str or "connect" in err_str:
            pytest.skip(f"Backend not running on localhost:8000: {e}")
        pytest.fail(f"WebSocket error: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])

