import asyncio, json, uuid
import httpx

TOKEN = "eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiI2MzA5NDAiLCJqdGkiOiI2OWZlZTJjNjA0MGZlMTc1ZmYzMGU5YmUiLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6dHJ1ZSwiaXNFeHRlbmRlZCI6dHJ1ZSwiaWF0IjoxNzc4MzExODc4LCJpc3MiOiJ1ZGFwaS1nYXRld2F5LXNlcnZpY2UiLCJleHAiOjE4MDk5MDAwMDB9.KOov70gaOZNudZHHiqMFGL9DEUG9or3eD96aBqtmojc"

async def test():
    async with httpx.AsyncClient() as client:
        # Try v3 paths
        for path in [
            "/v3/market-quote/stream",
            "/v3/market-quote/stream/authorize", 
            "/v2/market-quote/stream/v3/authorize",
            "/v3/feed/market-data-feed/authorize",
        ]:
            try:
                url = f"https://api.upstox.com{path}"
                resp = await client.get(url, headers={
                    "Authorization": f"Bearer {TOKEN}",
                    "Accept": "application/json",
                })
                print(f"GET {url} -> {resp.status_code}: {resp.text[:200]}")
            except Exception as e:
                print(f"GET {url} -> ERROR: {e}")

asyncio.run(test())
