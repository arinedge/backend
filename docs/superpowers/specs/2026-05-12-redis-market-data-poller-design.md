# Redis Market Data Poller — Design Spec

## Context

The Portal Backend fetches Indian market indices (Nifty 50, SENSEX, Bank Nifty, India VIX) from Upstox API and stores them in PostgreSQL. Redis is used as a caching layer for market data with configurable TTL.

## Problem

1. Redis is currently configured for localhost (`127.0.0.1`) but a Redis server is available on `156.67.27.164` (Docker, password `arinedge`)
2. Market data poller runs every 10 seconds — too frequent for 1-minute data needs
3. Poller still loops every 10s during market-closed hours, wasting resources

## Changes

### 1. Redis Host Configuration

**File:** `.env`

Change `REDIS_HOST` from `127.0.0.1` to `156.67.27.164`. The port (`6379`), password (`arinedge`), and DB (`0`) are already set correctly.

This is a hot-reloadable env var — the `redis_cache.py` module reads `REDIS_HOST` from settings on first connection via `get_redis()`.

### 2. Poller Interval

**File:** `app/main.py`

Change `await asyncio.sleep(10)` to `await asyncio.sleep(60)` in `_market_data_poller()`.

The poller calls `fetch_and_store_market_data()` which internally calls `_should_fetch_live()`. When the market is closed (weekend, holiday, or outside NSE/BSE hours):
- `_should_fetch_live()` returns `False`
- `fetch_and_store_market_data()` returns cached Redis data without hitting the Upstox API
- No DB writes occur

So the poller still wakes every 60s but does zero I/O (Redis read + skip) when market is closed.

### 3. Timestamp & Timezone

No code changes needed. The existing `IST = timezone(timedelta(hours=5, minutes=30))` in `market_data_service.py` is used for all schedule comparisons regardless of the server's physical timezone (Europe).

## Files Changed

| File | Change |
|------|--------|
| `.env` | `REDIS_HOST=127.0.0.1` → `REDIS_HOST=156.67.27.164` |
| `app/main.py` | `asyncio.sleep(10)` → `asyncio.sleep(60)` |

## What Stays the Same

- Redis cache layer (`app/utils/redis_cache.py`) — unchanged
- Market hours detection (`_should_fetch_live`) — unchanged
- WebSocket broadcasting — unchanged
- PostgreSQL storage — unchanged
- All existing API endpoints — unchanged
