import asyncio
import json
import os
import sys

import requests

try:
    import websockets
except ImportError:
    print("Error: 'websockets' package is required for sanity testing.")
    print("Run: uv add websockets")
    sys.exit(1)

BASE_URL = os.getenv("API_URL", "http://localhost:8000")
WS_URL = os.getenv("WS_URL", "ws://localhost:8000/ws/chat")

def test_rest_endpoints():
    print("--- Testing REST Endpoints ---")
    
    # 1. Health
    try:
        resp = requests.get(f"{BASE_URL}/health")
        resp.raise_for_status()
        health = resp.json()
        print(f"[PASS] Health: {health}")
        if health.get("retriever_ready") != "yes":
            print("[FAIL] Retriever is not ready!")
    except Exception as e:
        print(f"[FAIL] Health check failed: {e}")

    # 2. Config
    try:
        resp = requests.get(f"{BASE_URL}/config")
        resp.raise_for_status()
        print("[PASS] Config retrieved successfully.")
    except Exception as e:
        print(f"[FAIL] Config check failed: {e}")

    # 3. Collections
    try:
        resp = requests.get(f"{BASE_URL}/collections")
        resp.raise_for_status()
        collections = resp.json()
        print(f"[PASS] Collections: {collections}")
    except Exception as e:
        print(f"[FAIL] Collections check failed: {e}")

async def test_websocket():
    print("\n--- Testing WebSocket Retrieval ---")
    try:
        async with websockets.connect(WS_URL) as ws:
            payload = {
                "query": "What is Hybrid RAG?",
                "enable_rerank": "false"
            }
            await ws.send(json.dumps(payload))
            
            # Wait for status
            response_text = await ws.recv()
            # Wait for the results
            response_text = await ws.recv()
            response = json.loads(response_text)
            
            if response.get("type") == "results":
                docs = response.get("results", [])
                print(f"[PASS] Received {len(docs)} documents via WebSocket.")
            elif response.get("type") == "error":
                print(f"[FAIL] WebSocket returned error: {response.get('message')}")
            else:
                print(f"[WARN] Received unexpected message type: {response.get('type')}")
                
    except Exception as e:
        print(f"[FAIL] WebSocket test failed: {e}")

if __name__ == "__main__":
    test_rest_endpoints()
    asyncio.run(test_websocket())
