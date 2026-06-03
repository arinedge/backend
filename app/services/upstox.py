import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.utils.logger import get_logger

logger = get_logger(__name__)

UPSTOX_BASE_URL = "https://api.upstox.com/v2"


class UpstoxError(Exception):
    pass


class UpstoxClient:
    def __init__(self, access_token: str):
        self.access_token = access_token
        self.base_url = UPSTOX_BASE_URL
        self._headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
        }
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=self._headers,
                timeout=httpx.Timeout(30.0),
                limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
            )
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def get_market_status(self, exchange: str = "NSE") -> dict[str, Any]:
        client = await self._get_client()
        resp = await client.get(f"/market/status/{exchange}")
        if resp.status_code != 200:
            raise UpstoxError(
                f"Market status API failed ({resp.status_code}): {resp.text}"
            )
        data = resp.json()
        if data.get("status") != "success":
            raise UpstoxError(f"Market status API error: {data}")
        return data["data"]

    async def get_market_quotes(
        self, instrument_keys: list[str]
    ) -> dict[str, Any]:
        keys_str = ",".join(instrument_keys)
        client = await self._get_client()
        resp = await client.get(
            "/market-quote/quotes",
            params={"instrument_key": keys_str},
        )
        if resp.status_code != 200:
            raise UpstoxError(
                f"Market quote API failed ({resp.status_code}): {resp.text}"
            )
        data = resp.json()
        if data.get("status") != "success":
            raise UpstoxError(f"Market quote API error: {data}")
        return data["data"]

    async def get_market_holidays(self, date: str | None = None) -> list[dict[str, Any]]:
        path = "/market/holidays"
        if date:
            path += f"/{date}"
        client = await self._get_client()
        resp = await client.get(path)
        if resp.status_code != 200:
            raise UpstoxError(f"Holiday API failed ({resp.status_code}): {resp.text}")
        data = resp.json()
        if data.get("status") != "success":
            raise UpstoxError(f"Holiday API error: {data}")
        return data["data"]

    async def get_market_timings(self, date: str) -> list[dict[str, Any]]:
        client = await self._get_client()
        resp = await client.get(f"/market/timings/{date}")
        if resp.status_code != 200:
            raise UpstoxError(f"Timing API failed ({resp.status_code}): {resp.text}")
        data = resp.json()
        if data.get("status") != "success":
            raise UpstoxError(f"Timing API error: {data}")
        return data["data"]

    async def get_fii_data(self, interval: str = "1D") -> dict[str, Any]:
        client = await self._get_client()
        resp = await client.get(
            "/market/fii",
            params=[
                ("data_type", "NSE_FO|INDEX_FUTURES"),
                ("data_type", "NSE_FO|STOCK_FUTURES"),
                ("data_type", "NSE_FO|INDEX_OPTIONS"),
                ("data_type", "NSE_FO|STOCK_OPTIONS"),
                ("data_type", "NSE_EQ|CASH"),
                ("interval", interval),
            ],
        )
        if resp.status_code != 200:
            raise UpstoxError(f"FII API failed ({resp.status_code}): {resp.text}")
        data = resp.json()
        if data.get("status") != "success":
            raise UpstoxError(f"FII API error: {data}")
        return data["data"]

    async def get_dii_data(self, interval: str = "1D") -> dict[str, Any]:
        client = await self._get_client()
        resp = await client.get(
            "/market/dii",
            params={
                "data_type": "NSE_EQ|CASH",
                "interval": interval,
            },
        )
        if resp.status_code != 200:
            raise UpstoxError(f"DII API failed ({resp.status_code}): {resp.text}")
        data = resp.json()
        if data.get("status") != "success":
            raise UpstoxError(f"DII API error: {data}")
        return data["data"]

    async def get_option_chain(self, instrument_key: str, expiry_date: str) -> list[dict[str, Any]]:
        client = await self._get_client()
        resp = await client.get(
            "/option/chain",
            params={
                "instrument_key": instrument_key,
                "expiry_date": expiry_date,
            },
        )
        if resp.status_code != 200:
            raise UpstoxError(f"Option chain API failed ({resp.status_code}): {resp.text}")
        data = resp.json()
        if data.get("status") != "success":
            raise UpstoxError(f"Option chain API error: {data}")
        return data["data"]
