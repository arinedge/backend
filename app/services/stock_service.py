import math
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, desc, text
from sqlalchemy.orm import Session

from app.models.stock_info import StockInfo
from app.services.stock_compare_service import StockCompareService, _safe_float
from app.utils.logger import get_logger

logger = get_logger(__name__)


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

    def _fetch_statement_snapshot(self, ticker: str, statement_type: str) -> tuple[dict[str, Any], str | None]:
        rows = self.db.execute(text("""
            WITH latest_period AS (
                SELECT MAX(fiscal_date) AS fiscal_date
                FROM stock_financials
                WHERE lower(ticker) = lower(:ticker)
                  AND statement_type = :statement_type
            )
            SELECT fiscal_date, line_item, value
            FROM stock_financials
            WHERE lower(ticker) = lower(:ticker)
              AND statement_type = :statement_type
              AND fiscal_date = (SELECT fiscal_date FROM latest_period)
        """), {"ticker": ticker, "statement_type": statement_type})

        payload: dict[str, Any] = {}
        fiscal_date = None
        for row in rows:
            fiscal_date = row.fiscal_date
            numeric = _safe_float(row.value)
            if numeric is not None:
                payload[row.line_item] = numeric
        return payload, (fiscal_date.isoformat() if fiscal_date else None)

    def _fetch_statement_history(self, ticker: str, statement_type: str, limit: int = 4) -> list[dict[str, Any]]:
        rows = self.db.execute(text("""
            SELECT fiscal_date, line_item, value
            FROM stock_financials
            WHERE lower(ticker) = lower(:ticker)
              AND statement_type = :statement_type
            ORDER BY fiscal_date DESC, line_item
        """), {"ticker": ticker, "statement_type": statement_type})

        periods: dict[str, dict[str, Any]] = {}
        for row in rows:
            fiscal_date = row.fiscal_date.isoformat() if row.fiscal_date else None
            if not fiscal_date:
                continue
            if fiscal_date not in periods:
                if len(periods) >= limit:
                    continue
                periods[fiscal_date] = {"fiscal_date": fiscal_date, "values": {}}
            numeric = _safe_float(row.value)
            if numeric is not None:
                periods[fiscal_date]["values"][row.line_item] = numeric
        return list(periods.values())

    def get_stock_financials(self, symbol: str) -> dict[str, Any] | None:
        ticker = f"{symbol.upper()}.NS"
        info = self.db.query(StockInfo).filter(
            func.lower(StockInfo.ticker) == ticker.lower()
        ).order_by(desc(StockInfo.fetched_at)).first()

        if not info:
            return None

        cs = self._get_compare_service()
        fin = cs._fetch_financials_eav(ticker) or {}
        income, annual_income_date = self._fetch_statement_snapshot(ticker, "income_statement")
        cashflow, annual_cashflow_date = self._fetch_statement_snapshot(ticker, "cashflow")
        balance_sheet, annual_balance_date = self._fetch_statement_snapshot(ticker, "balance_sheet")
        quarterly_income_history = self._fetch_statement_history(ticker, "quarterly_income", limit=4)
        quarterly_cashflow_history = self._fetch_statement_history(ticker, "quarterly_cashflow", limit=4)
        quarterly_balance_history = self._fetch_statement_history(ticker, "quarterly_balance_sheet", limit=4)
        latest_quarterly_income, latest_quarterly_income_date = self._fetch_statement_snapshot(ticker, "quarterly_income")
        latest_quarterly_cashflow, latest_quarterly_cashflow_date = self._fetch_statement_snapshot(ticker, "quarterly_cashflow")
        latest_quarterly_balance, latest_quarterly_balance_date = self._fetch_statement_snapshot(ticker, "quarterly_balance_sheet")

        result = {
            "symbol": _clean_ticker(info.ticker) or symbol.upper(),
            "company_name": info.company_name,
            "sector": info.sector,
            "industry": info.industry,
            "description": info.description,
            "market_cap": _safe_float(info.market_cap),
            "ratios": {
                "trailing_pe": _safe_float(info.trailing_pe),
                "forward_pe": _safe_float(info.forward_pe),
                "price_to_book": _safe_float(info.price_to_book),
                "dividend_yield": _safe_float(info.dividend_yield),
                "roe": _safe_float(info.roe),
                "roa": _safe_float(info.roa),
                "profit_margins": _safe_float(info.profit_margins),
                "revenue_growth": _safe_float(info.revenue_growth),
                "earnings_growth": _safe_float(info.earnings_growth),
                "eps": _safe_float(info.eps),
                "forward_eps": _safe_float(info.forward_eps),
            },
            "financials": income or {},
            "cash_flow": cashflow or {},
            "balance_sheet": balance_sheet or {},
            "quarterly_financials": latest_quarterly_income,
            "quarterly_cash_flow": latest_quarterly_cashflow,
            "quarterly_balance_sheet": latest_quarterly_balance,
            "quarterly_history": {
                "income_statement": quarterly_income_history,
                "cashflow": quarterly_cashflow_history,
                "balance_sheet": quarterly_balance_history,
            },
            "statement_dates": {
                "annual_income_statement": annual_income_date,
                "annual_cashflow": annual_cashflow_date,
                "annual_balance_sheet": annual_balance_date,
                "quarterly_income_statement": latest_quarterly_income_date,
                "quarterly_cashflow": latest_quarterly_cashflow_date,
                "quarterly_balance_sheet": latest_quarterly_balance_date,
            },
            "fetched_at": (
                info.fetched_at.replace(tzinfo=timezone.utc).isoformat()
                if info.fetched_at else None
            ),
        }

        return result

    def get_stock_live(self, symbol: str) -> dict[str, Any] | None:
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
        if not fno_data:
            sm_row = self.db.execute(
                text("""
                    SELECT close_price AS spot_price, volume, change_pct, rsi_14 AS rsi,
                           sma_20 AS moving_average_20, sma_50 AS moving_average_50
                    FROM stock_daily_metrics
                    WHERE symbol = :sym
                    ORDER BY trade_date DESC
                    LIMIT 1
                """),
                {"sym": symbol},
            ).fetchone()
            if sm_row:
                fno_data = dict(sm_row._mapping)

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

        return result

    def get_stocks_by_sector(self) -> dict[str, list[dict[str, Any]]]:
        rows = self.db.execute(text("""
            SELECT symbol, company_name, sector, industry, market_cap
            FROM stock_info
            WHERE sector IS NOT NULL AND sector != ''
            ORDER BY sector, company_name
        """))

        sectors: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            sec = row.sector
            if sec not in sectors:
                sectors[sec] = []
            sectors[sec].append({
                "symbol": row.symbol,
                "company_name": row.company_name,
                "slug": _slugify(row.symbol or ""),
                "market_cap": row.market_cap,
                "industry": row.industry,
            })
        return {"sectors": sectors}

    def get_stocks_by_industry(self) -> dict[str, list[dict[str, Any]]]:
        rows = self.db.execute(text("""
            SELECT symbol, company_name, sector, industry, market_cap
            FROM stock_info
            WHERE industry IS NOT NULL AND industry != ''
            ORDER BY industry, company_name
        """))

        industries: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            ind = row.industry
            if ind not in industries:
                industries[ind] = []
            industries[ind].append({
                "symbol": row.symbol,
                "company_name": row.company_name,
                "slug": _slugify(row.symbol or ""),
                "market_cap": row.market_cap,
                "sector": row.sector,
            })
        return {"industries": industries}

    def get_stock_pe_history(self, symbol: str, limit: int = 12) -> list[dict[str, Any]]:
        rows = self.db.execute(text("""
            SELECT report_date, symbol, pe, adjusted_pe
            FROM nse_pe_ratios
            WHERE lower(symbol) = lower(:symbol)
            ORDER BY report_date DESC
            LIMIT :limit
        """), {"symbol": symbol.upper(), "limit": limit})
        return [
            {
                "report_date": row.report_date.isoformat() if row.report_date else None,
                "symbol": row.symbol,
                "pe": _safe_float(row.pe),
                "adjusted_pe": _safe_float(row.adjusted_pe),
            }
            for row in rows
        ]
