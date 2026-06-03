from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict


class FnoSymbolOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    symbol: str
    name: str
    segment: str
    exchange: str
    asset_type: str
    lot_size: int
    tick_size: float
    freeze_quantity: float | None = None
    minimum_lot: int
    qty_multiplier: float
    weekly: bool
    is_active: bool


class FnoExpiryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    symbol_id: UUID
    expiry_date: datetime
    expiry_timestamp: int
    weekly: bool
    is_active: bool


class FnoInstrumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    instrument_key: str
    trading_symbol: str
    instrument_type: str
    strike_price: float | None = None
    lot_size: int
    tick_size: float
    freeze_quantity: float | None = None
    minimum_lot: int
    qty_multiplier: float
    asset_type: str
    underlying_type: str
    underlying_symbol: str
    name: str
    segment: str
    exchange: str
    expiry_date: datetime | None = None
    weekly: bool


class OptionChainItem(BaseModel):
    instrument_key: str
    trading_symbol: str
    instrument_type: str
    strike_price: float | None = None
    lot_size: int
    tick_size: float
    asset_type: str
    underlying_symbol: str
    name: str
    exchange: str
    # Live pricing fields
    last_price: float | None = None
    change: float | None = None
    change_percent: float | None = None
    bid: float | None = None
    ask: float | None = None
    volume: int | None = None
    oi: float | None = None
    oi_change: float | None = None
    iv: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    rho: float | None = None


class OptionChainResponse(BaseModel):
    underlying_symbol: str
    underlying_price: float | None = None
    expiry_date: datetime
    expiry_timestamp: int
    instruments: list[OptionChainItem]


class FnoSymbolsListResponse(BaseModel):
    symbols: list[FnoSymbolOut]
    total: int


class FnoExpiriesListResponse(BaseModel):
    expiries: list[FnoExpiryOut]
    total: int
