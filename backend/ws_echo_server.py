"""Simple WebSocket echo server for testing."""
import asyncio
import json
import websockets

async def echo(websocket):
    try:
        async for message in websocket:
            if isinstance(message, bytes):
                resp = {"echo": message.hex(), "server": "test", "type": "binary"}
            else:
                resp = {"echo": message, "server": "test", "type": "text"}
            await websocket.send(json.dumps(resp))
    except websockets.exceptions.ConnectionClosed:
        pass

async def main():
    import os, sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("WS_ECHO_PORT", 8765))
    async with websockets.serve(echo, "127.0.0.1", port):
        while True:
            await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
