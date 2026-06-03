import uuid
from datetime import datetime
from typing import Any
from pydantic import BaseModel


class MarketDataPoint(BaseModel):
    symbol: str
    name: str
    instrument_key: str
    last_price: float
    change: float | None = None
    change_percent: float | None = None
    open_price: float | None = None
    high_price: float | None = None
    low_price: float | None = None
    close_price: float | None = None
    volume: int | None = None
    source: str = "live"
    fetched_at: datetime


class FiiDiiEntry(BaseModel):
    time_stamp: int
    buy_amount: float
    sell_amount: float
    buy_contracts: int
    sell_contracts: int
    net_amount: float


class FiiDiiSegment(BaseModel):
    segment: str
    latest: FiiDiiEntry | None = None


class FiiData(BaseModel):
    segments: list[FiiDiiSegment]
    total_buy: float = 0
    total_sell: float = 0
    total_net: float = 0


class DiiData(BaseModel):
    total_buy: float = 0
    total_sell: float = 0
    total_net: float = 0


class MarketDataResponse(BaseModel):
    status: str
    market_status: dict[str, Any]
    indices: list[MarketDataPoint]
    fii: FiiData | None = None
    dii: DiiData | None = None
    last_updated: datetime | None = None


class MarketStatusOut(BaseModel):
    exchange: str
    status: str
    last_checked_at: datetime
