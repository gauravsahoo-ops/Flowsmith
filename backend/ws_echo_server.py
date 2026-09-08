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
    async with websockets.serve(echo, "localhost", 8765):
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
