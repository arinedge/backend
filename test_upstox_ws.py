import asyncio, json, uuid

async def test_direct():
    import httpx
    from websockets.asyncio.client import connect as ws_connect

    token = "eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiI2MzA5NDAiLCJqdGkiOiI2OWZlZTJjNjA0MGZlMTc1ZmYzMGU5YmUiLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6dHJ1ZSwiaXNFeHRlbmRlZCI6dHJ1ZSwiaWF0IjoxNzc4MzExODc4LCJpc3MiOiJ1ZGFwaS1nYXRld2F5LXNlcnZpY2UiLCJleHAiOjE4MDk5MDAwMDB9.KOov70gaOZNudZHHiqMFGL9DEUG9or3eD96aBqtmojc"

    # Test 1: Try different authorize URLs
    print("=== Test 1: Try different REST endpoints ===")
    async with httpx.AsyncClient() as client:
        for path in [
            "/v2/market-quote/stream",
            "/v2/market-quote/stream/authorize",
            "/v2/feed/market-data-feed/authorize",
            "/v2/feed/market-data-feed",
            "/v2/live-feed/authorize",
            "/v2/websocket/market/authorize",
        ]:
            try:
                url = f"https://api.upstox.com{path}"
                resp = await client.get(url, headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                })
                print(f"  {url} -> {resp.status_code}: {resp.text[:100]}")
            except Exception as e:
                print(f"  {url} -> ERROR: {e}")

    # Test 2: Direct WebSocket with different headers
    print("\n=== Test 2: Direct WebSocket ===")
    try:
        async with ws_connect(
            "wss://api.upstox.com/v2/market-quote/stream",
            additional_headers={
                "Authorization": f"Bearer {token}",
                "Accept": "*/*",
            },
        ) as ws:
            print("  Connected!")
            sub = json.dumps({"guid": uuid.uuid4().hex[:20], "method": "sub", "data": {"mode": "full", "instrumentKeys": ["NSE_INDEX|Nifty 50"]}})
            await ws.send(sub.encode())
            print("  Subscribed, waiting 5s...")
            msg = await asyncio.wait_for(ws.recv(), timeout=5)
            print(f"  Received: {len(msg)} bytes")
    except Exception as e:
        print(f"  FAILED: {e}")

asyncio.run(test_direct())
