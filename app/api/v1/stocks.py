from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.stock_info import StockInfo
from app.services.stock_service import StockService
from app.services.stock_workspace_service import StockWorkspaceService
from app.utils.logger import get_logger
from app.utils.redis_cache import cache_get, cache_set

router = APIRouter(tags=["Stocks"])
logger = get_logger(__name__)


async def _cached(key: str, ttl: int, factory):
    cached = await cache_get(key)
    if cached is not None:
        return cached
    payload = await run_in_threadpool(factory)
    await cache_set(key, payload, ttl=ttl)
    return payload


@router.get("/last-updated")
def get_last_updated(db: Session = Depends(get_db)):
    ts = db.query(func.max(StockInfo.fetched_at)).scalar()
    return {"last_updated_at": ts.isoformat() if ts else None}


@router.get("/search")
def search_stocks(
    query: str = Query(default="", max_length=100),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """Search the NSE stock universe used by chart and stock-detail clients."""
    term = query.strip()
    normalized = term.upper().removesuffix(".NS")
    pattern = f"%{term}%"

    stock_query = db.query(StockInfo).filter(
        or_(StockInfo.symbol.isnot(None), StockInfo.ticker.isnot(None))
    )
    if term:
        stock_query = stock_query.filter(
            or_(
                StockInfo.symbol.ilike(pattern),
                StockInfo.ticker.ilike(pattern),
                StockInfo.company_name.ilike(pattern),
            )
        ).order_by(
            case(
                (func.upper(StockInfo.symbol) == normalized, 0),
                (func.upper(StockInfo.ticker) == normalized, 0),
                (func.upper(StockInfo.symbol).like(f"{normalized}%"), 1),
                (func.upper(StockInfo.ticker).like(f"{normalized}%"), 1),
                (func.upper(StockInfo.company_name).like(f"{normalized}%"), 2),
                else_=3,
            ),
            StockInfo.market_cap.desc().nullslast(),
            StockInfo.company_name.asc().nullslast(),
        )
    else:
        stock_query = stock_query.order_by(
            StockInfo.market_cap.desc().nullslast(),
            StockInfo.company_name.asc().nullslast(),
        )

    rows = stock_query.limit(limit * 4).all()
    results = []
    seen: set[str] = set()
    for row in rows:
        raw_symbol = (row.symbol or row.ticker or "").strip().upper()
        symbol = raw_symbol.removesuffix(".NS")
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        data = row.data if isinstance(row.data, dict) else {}
        results.append({
            "symbol": symbol,
            "ticker": f"{symbol}.NS",
            "company_name": row.company_name or data.get("longName") or data.get("shortName") or symbol,
            "exchange": "NSE",
            "sector": row.sector,
            "industry": row.industry,
        })
        if len(results) >= limit:
            break

    return {"query": term, "count": len(results), "results": results}


@router.get("/dashboard")
async def get_stocks_dashboard(db: Session = Depends(get_db)):
    service = StockWorkspaceService(db)
    return await _cached("stocks:v2:dashboard", 60, service.dashboard)


@router.get("/{symbol}/workspace")
async def get_stock_workspace(symbol: str, db: Session = Depends(get_db)):
    service = StockWorkspaceService(db)
    payload = await _cached(
        f"stocks:v3:{symbol.upper()}:workspace", 300,
        lambda: service.workspace(symbol),
    )
    if payload is None:
        raise HTTPException(status_code=404, detail="Stock could not be resolved")
    return payload


@router.get("/{symbol}/tabs/{tab}")
async def get_stock_workspace_tab(symbol: str, tab: str, db: Session = Depends(get_db)):
    allowed = {"overview", "financials", "ownership", "news-events", "fno", "deals", "peers", "nexus-risk"}
    if tab not in allowed:
        raise HTTPException(status_code=404, detail="Unknown stock workspace tab")
    ttl = 60 if tab in {"fno", "nexus-risk"} else 300 if tab in {"overview", "news-events"} else 21600
    service = StockWorkspaceService(db)
    return await _cached(
        f"stocks:v6:{symbol.upper()}:tab:{tab}", ttl,
        lambda: service.tab(symbol, tab),
    )


@router.get("/{symbol}/chart")
async def get_stock_chart(
    symbol: str,
    from_ts: int | None = Query(default=None, alias="from"),
    to_ts: int | None = Query(default=None, alias="to"),
    limit: int = Query(default=5000, ge=1, le=10000),
    db: Session = Depends(get_db),
):
    service = StockWorkspaceService(db)
    key = f"stocks:v1:{symbol.upper()}:chart:{from_ts or 0}:{to_ts or 0}:{limit}"
    return await _cached(key, 3600, lambda: service.chart(symbol, from_ts, to_ts, limit))


@router.get("/{symbol}/financials")
def get_stock_financials(symbol: str, db: Session = Depends(get_db)):
    service = StockService(db)
    try:
        result = service.get_stock_financials(symbol)
    except Exception:
        logger.exception("Stock financials failed for %s", symbol)
        return {
            "symbol": symbol.upper(),
            "error": "Financial data is temporarily unavailable",
            "status": "unavailable",
        }
    if result is None:
        return {"error": f"No financial data found for {symbol}"}
    return result


@router.get("/{symbol}/live")
def get_stock_live(symbol: str, db: Session = Depends(get_db)):
    service = StockService(db)
    try:
        result = service.get_stock_live(symbol)
    except Exception:
        logger.exception("Stock live data failed for %s", symbol)
        return {
            "symbol": symbol.upper(),
            "error": "Live data is temporarily unavailable",
            "status": "unavailable",
        }
    if result is None:
        return {"error": f"No live data found for {symbol}"}
    return result


@router.get("/by-sector")
def get_stocks_by_sector(db: Session = Depends(get_db)):
    service = StockService(db)
    return service.get_stocks_by_sector()


@router.get("/by-industry")
def get_stocks_by_industry(db: Session = Depends(get_db)):
    service = StockService(db)
    return service.get_stocks_by_industry()
