import json
import traceback
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request as FastAPIRequest
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.models.broker import Broker
from app.schemas.fno import (
    FnoSymbolOut,
    FnoExpiryOut,
    FnoInstrumentOut,
    OptionChainResponse,
    OptionChainItem,
    FnoSymbolsListResponse,
    FnoExpiriesListResponse,
)
from app.services.fno_service import FnoService
from app.services.market_data_service import MarketDataService
from app.services.upstox import UpstoxClient
from app.utils.logger import get_logger
from app.utils.redis_cache import get_redis, cache_set

logger = get_logger(__name__)
router = APIRouter(tags=["F&O"])

UPSTOX_UNDERLYING_KEYS: dict[str, str] = {
    "NIFTY": "NSE_INDEX|Nifty 50",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
    "SENSEX": "BSE_INDEX|SENSEX",
}


@router.get("/symbols", response_model=FnoSymbolsListResponse)
def list_symbols(
    search: str | None = Query(None, description="Search by symbol name"),
    segment: str | None = Query(None, description="Filter by segment (NSE_FO, BSE_FO, etc)"),
    asset_type: str | None = Query(None, description="Filter by asset type (INDEX, STOCK, ETF, etc)"),
    nifty50: bool = Query(False, description="Limit to Nifty 50 constituents + NIFTY/BANKNIFTY/SENSEX"),
    db: Session = Depends(get_db),
):
    try:
        symbols = FnoService.get_symbols(db, search=search, segment=segment, asset_type=asset_type, nifty50=nifty50)
        return FnoSymbolsListResponse(
            symbols=[FnoSymbolOut.model_validate(s) for s in symbols],
            total=len(symbols),
        )
    except Exception:
        logger.error("Failed to list FNO symbols:\n%s", traceback.format_exc())
        raise HTTPException(status_code=500, detail="Failed to list symbols")


@router.get("/symbols/{symbol}/expiries", response_model=FnoExpiriesListResponse)
def list_expiries(
    symbol: str,
    db: Session = Depends(get_db),
):
    try:
        expiries = FnoService.get_expiries_by_symbol_name(db, symbol)
        return FnoExpiriesListResponse(
            expiries=[FnoExpiryOut.model_validate(e) for e in expiries],
            total=len(expiries),
        )
    except Exception:
        logger.error("Failed to list expiries for %s:\n%s", symbol, traceback.format_exc())
        raise HTTPException(status_code=500, detail="Failed to list expiries")


@router.get("/option-chain", response_model=OptionChainResponse)
async def get_option_chain(
    underlying_symbol: str = Query(..., description="Underlying symbol (e.g., NIFTY, BANKNIFTY)"),
    expiry: int = Query(..., description="Expiry timestamp in milliseconds"),
    db: Session = Depends(get_db),
):
    try:
        # Try full cached response first
        cache_key = f"fno:option_chain:{underlying_symbol.upper()}:{expiry}"
        try:
            r = await get_redis()
            if r:
                cached = await r.get(cache_key)
                if cached:
                    return JSONResponse(content=json.loads(cached), media_type="application/json")
        except Exception:
            pass
        instruments, expiry_date, expiry_ts = FnoService.get_option_chain(
            db, underlying_symbol, expiry
        )
        if not instruments:
            raise HTTPException(
                status_code=404,
                detail=f"No option chain found for {underlying_symbol} at expiry {expiry}",
            )

        instrument_keys = [i.instrument_key for i in instruments if i.instrument_key]
        try:
            mkt_db = SessionLocal()
            try:
                mkt_service = MarketDataService(mkt_db)
                prices = await mkt_service.get_latest_option_prices(instrument_keys)
            finally:
                mkt_db.close()
        except Exception as e:
            logger.warning("Failed to fetch live option prices: %s", e)
            prices = {}

        # Estimate underlying price: prefer Upstox spot price, fallback to straddle midpoint
        underlying_price: float | None = None

        # Fallback to Upstox REST API if most prices are missing
        if len(prices) < len(instrument_keys) * 0.3:
            upstream_key = UPSTOX_UNDERLYING_KEYS.get(underlying_symbol.upper())
            if upstream_key:
                try:
                    expiry_date_str = datetime.fromtimestamp(expiry / 1000).strftime("%Y-%m-%d")
                    broker = db.query(Broker).filter(
                        Broker.is_active == True, Broker.access_token.isnot(None)
                    ).first()
                    if broker:
                        client = UpstoxClient(broker.access_token)
                        chain_data = await client.get_option_chain(upstream_key, expiry_date_str)
                        rest_prices, rest_underlying = _parse_upstox_chain(chain_data)
                        if rest_prices:
                            prices.update(rest_prices)
                            await _cache_option_prices(rest_prices)
                            if rest_underlying is not None:
                                underlying_price = rest_underlying
                            logger.info("Fetched %d prices from Upstox REST option chain", len(rest_prices))
                except Exception as e:
                    logger.warning("Upstox REST option chain fallback failed: %s", e)

        items = []
        for i in instruments:
            live = prices.get(i.instrument_key, {})
            items.append(OptionChainItem(
                instrument_key=i.instrument_key,
                trading_symbol=i.trading_symbol,
                instrument_type=i.instrument_type,
                strike_price=i.strike_price,
                lot_size=i.lot_size,
                tick_size=i.tick_size,
                asset_type=i.asset_type,
                underlying_symbol=i.underlying_symbol,
                name=i.name,
                exchange=i.exchange,
                last_price=live.get("last_price"),
                change=live.get("change"),
                change_percent=live.get("change_percent"),
                bid=live.get("bid"),
                ask=live.get("ask"),
                volume=live.get("volume"),
                oi=live.get("oi"),
                oi_change=live.get("oi_change"),
                iv=live.get("iv"),
                delta=live.get("delta"),
                gamma=live.get("gamma"),
                theta=live.get("theta"),
                vega=live.get("vega"),
                rho=live.get("rho"),
            ))

        if not underlying_price:
            straddle: list[tuple[float, float | None, float | None]] = []
            for inst in instruments:
                if inst.instrument_key in prices:
                    p = prices[inst.instrument_key]
                    straddle.append((inst.strike_price, p.get("last_price"), inst.instrument_type))
            if straddle:
                ce_prices = {s: lp for s, lp, t in straddle if t == "CE" and lp is not None}
                pe_prices = {s: lp for s, lp, t in straddle if t == "PE" and lp is not None}
                common = sorted(set(ce_prices.keys()) & set(pe_prices.keys()))
                if common:
                    diffs = [(s, abs(ce_prices[s] - pe_prices[s])) for s in common]
                    underlying_price = min(diffs, key=lambda x: x[1])[0]

        result = OptionChainResponse(
            underlying_symbol=underlying_symbol,
            underlying_price=underlying_price,
            expiry_date=expiry_date,
            expiry_timestamp=expiry_ts,
            instruments=items,
        )

        # Cache full response to Redis for 10 min
        try:
            r = await get_redis()
            if r:
                await r.setex(cache_key, 600, result.model_dump_json())
        except Exception:
            pass

        return result
    except HTTPException:
        raise
    except Exception:
        logger.error(
            "Failed to get option chain for %s expiry=%s:\n%s",
            underlying_symbol, expiry, traceback.format_exc(),
        )
        raise HTTPException(status_code=500, detail="Failed to get option chain")


class SubscribeRequest(BaseModel):
    underlying_symbol: str
    expiry: int

class SubscribeResponse(BaseModel):
    subscribed: int
    instrument_keys: list[str]

@router.post("/subscribe", response_model=SubscribeResponse)
async def subscribe_option_chain(
    req: SubscribeRequest,
    request: FastAPIRequest,
    db: Session = Depends(get_db),
):
    try:
        instruments, _, _ = FnoService.get_option_chain(
            db, req.underlying_symbol, req.expiry
        )
        if not instruments:
            raise HTTPException(status_code=404, detail="No instruments found")

        keys = [i.instrument_key for i in instruments if i.instrument_key]

        upstox_ws = getattr(request.app.state, "upstox_ws", None)
        if upstox_ws:
            await upstox_ws.subscribe_option_keys(keys)
            logger.info("Subscribed %d keys to Upstox WS", len(keys))
        else:
            logger.warning("Upstox WS not available")

        return SubscribeResponse(subscribed=len(keys), instrument_keys=keys)
    except HTTPException:
        raise
    except Exception:
        logger.error("Failed to subscribe:\n%s", traceback.format_exc())
        raise HTTPException(status_code=500, detail="Failed to subscribe")


@router.get("/instruments/{instrument_key}", response_model=FnoInstrumentOut)
def get_instrument(
    instrument_key: str,
    db: Session = Depends(get_db),
):
    try:
        instrument = FnoService.get_instrument_by_key(db, instrument_key)
        if not instrument:
            raise HTTPException(status_code=404, detail="Instrument not found")
        return FnoInstrumentOut.model_validate(instrument)
    except HTTPException:
        raise
    except Exception:
        logger.error(
            "Failed to get instrument %s:\n%s", instrument_key, traceback.format_exc()
        )
        raise HTTPException(status_code=500, detail="Failed to get instrument")


@router.get("/stats")
def get_stats(db: Session = Depends(get_db)):
    try:
        return FnoService.get_stats(db)
    except Exception:
        logger.error("Failed to get FNO stats:\n%s", traceback.format_exc())
        raise HTTPException(status_code=500, detail="Failed to get stats")


def _parse_upstox_chain(chain_data: list[dict]) -> tuple[dict[str, dict], float | None]:
    """Parse Upstox option chain REST response into (prices_dict, underlying_spot_price)."""
    prices: dict[str, dict] = {}
    underlying_spot_price: float | None = None
    for strike_data in chain_data:
        for opt_type in ("call_options", "put_options"):
            opt = strike_data.get(opt_type)
            if not opt:
                continue
            inst_key = opt.get("instrument_key")
            if not inst_key:
                continue
            md = opt.get("market_data") or {}
            greeks = opt.get("option_greeks") or {}
            prev_oi = md.get("prev_oi") or 0
            current_oi = md.get("oi") or 0
            oi_change = current_oi - prev_oi
            prices[inst_key] = {
                "last_price": md.get("ltp"),
                "volume": md.get("volume"),
                "oi": current_oi,
                "oi_change": oi_change if oi_change != 0 else None,
                "bid": md.get("bid_price"),
                "ask": md.get("ask_price"),
                "iv": greeks.get("iv"),
                "delta": greeks.get("delta"),
                "gamma": greeks.get("gamma"),
                "theta": greeks.get("theta"),
                "vega": greeks.get("vega"),
                "rho": None,
                "change": None,
                "change_percent": None,
            }
            if underlying_spot_price is None:
                underlying_spot_price = strike_data.get("underlying_spot_price")
    return prices, underlying_spot_price


async def _cache_option_prices(prices: dict[str, dict]) -> None:
    """Cache REST-fetched prices to Redis for subsequent requests."""
    try:
        r = await get_redis()
        if not r:
            return
        pipe = r.pipeline()
        for ik, data in prices.items():
            pipe.setex(f"market_data:tick:option:{ik}", 600, json.dumps(data))
        await pipe.execute()
        logger.debug("Cached %d option prices to Redis", len(prices))
    except Exception as e:
        logger.warning("Failed to cache option prices to Redis: %s", e)
