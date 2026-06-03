import asyncio
import json
import websockets


async def test_ws():
    uri = "ws://localhost:8000/api/v1/market/ws"
    print(f"Connecting to {uri} ...")
    try:
        async with websockets.connect(uri) as ws:
            print("Connected!")
            print("Waiting for data (timeout=10s)...")
            try:
                data = await asyncio.wait_for(ws.recv(), timeout=10)
                parsed = json.loads(data)
                indices = parsed.get("indices", [])
                for idx in indices:
                    print(f"  {idx['symbol']}: {idx['last_price']} ({idx.get('change_percent', 'N/A')}%)")
                print(f"\nMarket status: {parsed.get('market_status', {})}")
                print(f"FII: {parsed.get('fii', {}).get('total_net', 'N/A')}")
                print("SUCCESS: WebSocket is passing data!")
            except asyncio.TimeoutError:
                print("TIMEOUT: No data received in 10 seconds")
    except Exception as e:
        print(f"FAILED: {e}")


if __name__ == "__main__":
    asyncio.run(test_ws())
