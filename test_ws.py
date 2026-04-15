import asyncio
import websockets
import json

async def test_ws():
    uri = "ws://localhost:8000/ws/chat"
    try:
        async with websockets.connect(uri) as websocket:
            print("✓ WebSocket connected!")
            # Send a test query
            await websocket.send(json.dumps({"query": "test", "enable_rerank": False}))
            # Receive response
            response = await websocket.recv()
            data = json.loads(response)
            print(f"✓ Received message type: {data.get('type')}")
            if data.get('type') == 'status':
                print(f"✓ Status message: {data.get('message')}")
            return True
    except Exception as e:
        print(f"✗ Error: {e}")
        return False

asyncio.run(test_ws())
