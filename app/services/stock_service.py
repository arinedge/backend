from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, desc
from sqlalchemy.orm import Session

from app.models.stock_info import StockInfo
from app.services.stock_compare_service import StockCompareService
from app.utils.logger import get_logger
from app.utils.redis_cache import cache_get, cache_set

logger = get_logger(__name__)

FINANCIALS_CACHE_TTL = 86400  # 24 hours
LIVE_CACHE_TTL = 30  # 30 seconds


def _slugify(symbol: str) -> str:
    return symbol.lower().replace("&", "and")


def _clean_ticker(ticker: str | None) -> str | None:
    if ticker and ticker.endswith(".NS"):
        return ticker[:-3]
    return ticker


class StockService:
    def __init__(self, db: Session):
        self.db = db

    def _get_compare_service(self) -> StockCompareService:
        return StockCompareService(self.db)

    def get_stock_financials(self, symbol: str) -> dict[str, Any] | None:
        cache_key = f"stock:financials:{symbol.lower()}"
        cached = cache_get(cache_key)
        if cached:
            return cached

        ticker = f"{symbol.upper()}.NS"
        info = self.db.query(StockInfo).filter(
            func.lower(StockInfo.ticker) == ticker.lower()
        ).order_by(desc(StockInfo.fetched_at)).first()

        if not info:
            return None

        cs = self._get_compare_service()
        fin = cs._fetch_financials_eav(ticker) or {}
        income = cs._pivot_from_financials(fin, "income_statement", StockCompareService.FINANCIAL_LINE_ITEMS)
        cashflow = cs._pivot_from_financials(fin, "cashflow", StockCompareService.CASH_FLOW_ITEMS)
        bs = fin.get("balance_sheet", {})

        result = {
            "symbol": _clean_ticker(info.ticker) or symbol.upper(),
            "company_name": info.company_name,
            "sector": info.sector,
            "industry": info.industry,
            "description": info.description,
            "market_cap": info.market_cap,
            "ratios": {
                "trailing_pe": info.trailing_pe,
                "forward_pe": info.forward_pe,
                "price_to_book": info.price_to_book,
                "dividend_yield": info.dividend_yield,
                "roe": info.roe,
                "roa": info.roa,
                "profit_margins": info.profit_margins,
                "revenue_growth": info.revenue_growth,
                "earnings_growth": info.earnings_growth,
                "eps": info.eps,
                "forward_eps": info.forward_eps,
            },
            "financials": income or {},
            "cash_flow": cashflow or {},
            "balance_sheet": {
                k: v for k, v in bs.items() if isinstance(v, (int, float))
            },
            "fetched_at": (
                info.fetched_at.replace(tzinfo=timezone.utc).isoformat()
                if info.fetched_at else None
            ),
        }

        cache_set(cache_key, result, FINANCIALS_CACHE_TTL)
        return result

    def get_stock_live(self, symbol: str) -> dict[str, Any] | None:
        cache_key = f"stock:live:{symbol.lower()}"
        cached = cache_get(cache_key)
        if cached:
            return cached

        ticker = f"{symbol.upper()}.NS"
        info = self.db.query(StockInfo).filter(
            func.lower(StockInfo.ticker) == ticker.lower()
        ).order_by(desc(StockInfo.fetched_at)).first()

        if not info:
            return None

        cs = self._get_compare_service()
        prices = cs._fetch_stock_prices(ticker, limit=5) or []
        latest = prices[0] if prices else None

        fno_data = None
        is_fno = info.data.get("fno_available") if isinstance(info.data, dict) else False
        if is_fno:
            nexus = cs._fetch_nexus_options(symbol.upper())
            expiry = cs._fetch_nexus_expiry_intel(symbol.upper())
            if nexus:
                metrics = cs._compute_fno_metrics(nexus, expiry)
                fno_data = {
                    "spot_price": metrics.get("spot_price"),
                    "pcr_oi": metrics.get("pcr_oi"),
                    "atm_iv": metrics.get("avg_iv"),
                    "net_gamma": metrics.get("net_gamma"),
                    "total_gamma": metrics.get("total_gamma"),
                    "top_call_oi": [
                        {"strike": s.get("strike"), "oi": s.get("oi"), "iv": s.get("iv")}
                        for s in (metrics.get("top_call_oi") or [])[:5]
                    ],
                    "top_put_oi": [
                        {"strike": s.get("strike"), "oi": s.get("oi"), "iv": s.get("iv")}
                        for s in (metrics.get("top_put_oi") or [])[:5]
                    ],
                }

        result = {
            "symbol": _clean_ticker(info.ticker) or symbol.upper(),
            "latest_price": {
                "close": latest.get("close") if latest else None,
                "date": str(latest.get("date")) if latest else None,
                "change": latest.get("change") if latest else None,
                "change_pct": latest.get("change_pct") if latest else None,
                "volume": latest.get("volume") if latest else None,
            } if latest else None,
            "fno": fno_data,
        }

        cache_set(cache_key, result, LIVE_CACHE_TTL)
        return result

    def get_stocks_by_sector(self) -> dict[str, list[dict[str, Any]]]:
        rows = self.db.query(StockInfo).filter(
            StockInfo.sector.isnot(None),
            StockInfo.sector != "",
        ).order_by(StockInfo.sector, StockInfo.company_name).all()

        sectors: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            sec = row.sector
            if sec not in sectors:
                sectors[sec] = []
            sectors[sec].append({
                "symbol": _clean_ticker(row.ticker) or "",
                "company_name": row.company_name,
                "slug": _slugify(_clean_ticker(row.ticker) or ""),
                "market_cap": row.market_cap,
                "industry": row.industry,
            })
        return {"sectors": sectors}

    def get_stocks_by_industry(self) -> dict[str, list[dict[str, Any]]]:
        rows = self.db.query(StockInfo).filter(
            StockInfo.industry.isnot(None),
            StockInfo.industry != "",
        ).order_by(StockInfo.industry, StockInfo.company_name).all()

        industries: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            ind = row.industry
            if ind not in industries:
                industries[ind] = []
            industries[ind].append({
                "symbol": _clean_ticker(row.ticker) or "",
                "company_name": row.company_name,
                "slug": _slugify(_clean_ticker(row.ticker) or ""),
                "market_cap": row.market_cap,
                "sector": row.sector,
            })
        return {"industries": industries}
