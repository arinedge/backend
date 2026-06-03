import asyncio
import json
import uuid
import traceback
from collections.abc import Awaitable
from typing import Callable, Any

import httpx
from websockets.asyncio.client import connect as ws_connect

from app.proto.MarketDataFeed_pb2 import FeedResponse
from app.utils.logger import get_logger

logger = get_logger(__name__)

UPSTOX_V3_AUTH = "https://api.upstox.com/v3/feed/market-data-feed/authorize"
TRACKED_INDICES_WS: list[str] = [
    "NSE_INDEX|Nifty 50",
    "BSE_INDEX|SENSEX",
    "NSE_INDEX|Nifty Bank",
    "NSE_INDEX|India VIX",
]


class UpstoxWSClient:
    def __init__(self, access_token: str, on_tick: Callable[[dict[str, Any]], Awaitable[None]]):
        self.access_token = access_token
        self.on_tick = on_tick
        self._ws = None
        self._task: asyncio.Task | None = None
        self._running = False
        self._guid = uuid.uuid4().hex[:20]
        self._subscribed_option_keys: set[str] = set()

    async def subscribe_option_keys(self, keys: list[str]) -> None:
        """Subscribe to option instrument keys on the Upstox WS."""
        new_keys = [k for k in keys if k not in self._subscribed_option_keys]
        if not new_keys or not self._ws:
            return
        self._subscribed_option_keys.update(new_keys)
        sub_msg = {
            "guid": self._guid,
            "method": "sub",
            "data": {
                "mode": "full",
                "instrumentKeys": new_keys,
            },
        }
        await self._ws.send(json.dumps(sub_msg).encode())
        logger.info("Upstox WS subscribed to %d option keys (total: %d)", len(new_keys), len(self._subscribed_option_keys))

    async def unsubscribe_option_keys(self, keys: list[str]) -> None:
        """Unsubscribe from option instrument keys."""
        to_remove = [k for k in keys if k in self._subscribed_option_keys]
        if not to_remove or not self._ws:
            return
        for k in to_remove:
            self._subscribed_option_keys.discard(k)
        unsub_msg = {
            "guid": self._guid,
            "method": "unsub",
            "data": {
                "mode": "full",
                "instrumentKeys": to_remove,
            },
        }
        await self._ws.send(json.dumps(unsub_msg).encode())
        logger.info("Upstox WS unsubscribed from %d option keys", len(to_remove))

    async def _get_authorized_url(self) -> str:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                UPSTOX_V3_AUTH,
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "Accept": "application/json",
                },
            )
            if resp.status_code != 200:
                raise RuntimeError(f"Upstox authorize failed ({resp.status_code}): {resp.text}")
            data = resp.json()
            if data.get("status") != "success":
                raise RuntimeError(f"Upstox authorize error: {data}")
            uri = data.get("data", {}).get("authorizedRedirectUri")
            if not uri:
                raise RuntimeError(f"Upstox authorize: no URI in response: {data}")
            return uri

    async def start(self):
        self._running = True
        try:
            url = await self._get_authorized_url()
            logger.info("Upstox WS authorized, connecting...")
            async with ws_connect(url) as ws:
                self._ws = ws
                sub_msg = {
                    "guid": self._guid,
                    "method": "sub",
                    "data": {
                        "mode": "full",
                        "instrumentKeys": TRACKED_INDICES_WS,
                    },
                }
                await ws.send(json.dumps(sub_msg).encode())
                logger.info("Upstox WS subscribed to %d indices", len(TRACKED_INDICES_WS))
                await self._listen(ws)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Upstox WS error: %s\n%s", e, traceback.format_exc())

    async def _listen(self, ws):
        async for message in ws:
            if not self._running:
                break
            try:
                resp = FeedResponse()
                resp.ParseFromString(message)
                await self._handle_feed(resp)
            except Exception as e:
                logger.debug("Upstox WS parse error: %s", e)

    async def _handle_feed(self, resp: FeedResponse):
        if resp.type == 2:
            logger.debug("Upstox WS: market info received")
            return
        if resp.type != 1:
            return

        for inst_key, feed in resp.feeds.items():
            ff = feed.fullFeed
            if ff is None:
                continue
            union = ff.WhichOneof("FullFeedUnion")
            if union == "indexFF":
                idx = ff.indexFF
                ltpc = idx.ltpc
                ohlc_list = idx.marketOHLC.ohlc if idx.marketOHLC else []

                daily_ohlc = None
                for o in ohlc_list:
                    if o.interval == "1d":
                        daily_ohlc = o
                        break

                change = ltpc.ltp - ltpc.cp if ltpc.cp else 0
                change_percent = 0.0
                prev_close = ltpc.ltp - change
                if prev_close != 0:
                    change_percent = round((change / prev_close) * 100, 2)

                tick_data = {
                    "instrument_key": inst_key,
                    "last_price": ltpc.ltp,
                    "change": change,
                    "change_percent": change_percent,
                    "open_price": daily_ohlc.open if daily_ohlc else None,
                    "high_price": daily_ohlc.high if daily_ohlc else None,
                    "low_price": daily_ohlc.low if daily_ohlc else None,
                    "close_price": ltpc.cp,
                    "volume": daily_ohlc.vol if daily_ohlc else None,
                    "fetched_at": ltpc.ltt if ltpc.ltt else 0,
                    "source": "live",
                }
                asyncio.create_task(self.on_tick(tick_data))

            elif union == "marketFF":
                mff = ff.marketFF
                ltpc = mff.ltpc
                ohlc_list = mff.marketOHLC.ohlc if mff.marketOHLC else []

                daily_ohlc = None
                for o in ohlc_list:
                    if o.interval == "1d":
                        daily_ohlc = o
                        break

                bid_price = None
                bid_qty = None
                ask_price = None
                ask_qty = None
                if mff.marketLevel and mff.marketLevel.bidAskQuote:
                    quotes = mff.marketLevel.bidAskQuote
                    if len(quotes) > 0:
                        bid_price = quotes[0].bidP if quotes[0].bidP else None
                        bid_qty = quotes[0].bidQ if quotes[0].bidQ else None
                    if len(quotes) > 1:
                        ask_price = quotes[1].askP if quotes[1].askP else None
                        ask_qty = quotes[1].askQ if quotes[1].askQ else None
                    elif len(quotes) > 0:
                        ask_price = quotes[0].askP if quotes[0].askP else None
                        ask_qty = quotes[0].askQ if quotes[0].askQ else None

                delta = None
                gamma = None
                theta = None
                vega = None
                rho = None
                if mff.optionGreeks:
                    g = mff.optionGreeks
                    delta = round(g.delta, 4) if g.delta else None
                    gamma = round(g.gamma, 6) if g.gamma else None
                    theta = round(g.theta, 4) if g.theta else None
                    vega = round(g.vega, 4) if g.vega else None
                    rho = round(g.rho, 4) if g.rho else None

                change = ltpc.ltp - ltpc.cp if ltpc.cp else 0
                change_percent = 0.0
                prev_close = ltpc.ltp - change
                if prev_close != 0:
                    change_percent = round((change / prev_close) * 100, 2)

                tick_data = {
                    "instrument_key": inst_key,
                    "last_price": ltpc.ltp,
                    "change": change,
                    "change_percent": change_percent,
                    "open_price": daily_ohlc.open if daily_ohlc else None,
                    "high_price": daily_ohlc.high if daily_ohlc else None,
                    "low_price": daily_ohlc.low if daily_ohlc else None,
                    "close_price": ltpc.cp,
                    "volume": mff.vtt if mff.vtt else None,
                    "bid": bid_price,
                    "ask": ask_price,
                    "oi": mff.oi if mff.oi else None,
                    "iv": mff.iv if mff.iv else None,
                    "delta": delta,
                    "gamma": gamma,
                    "theta": theta,
                    "vega": vega,
                    "rho": rho,
                    "fetched_at": ltpc.ltt if ltpc.ltt else 0,
                    "source": "live",
                }
                asyncio.create_task(self.on_tick(tick_data))

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._ws:
            await self._ws.close()
            self._ws = None
        logger.info("Upstox WS stopped")
