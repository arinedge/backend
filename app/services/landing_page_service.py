from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import desc, func, select, text
from sqlalchemy.orm import Session

from app.models.stock_info import StockInfo
from app.schemas.compare import DataQuality, RelatedLink, SeoEligibility, StockIdentity
from app.schemas.landing import LandingEntity, LandingResponse, LandingSectionStatus
from app.services.stock_compare_service import StockCompareService, _safe_datetime, _safe_float, _safe_int
from app.services.stock_service import StockService
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _sector_slug(value: str) -> str:
    slug = value.strip().lower().replace("&", " and ")
    return "-".join(part for part in "".join(ch if ch.isalnum() else " " for ch in slug).split() if part)


class LandingPageService:
    def __init__(self, db: Session):
        self.db = db
        self.compare = StockCompareService(db)
        self.stocks = StockService(db)

    def _get_table(self, name: str):
        return self.compare._get_table(name)

    def _serialize_value(self, value: Any) -> Any:
        if isinstance(value, datetime):
            return _safe_datetime(value)
        if hasattr(value, "isoformat") and not isinstance(value, str):
            try:
                return value.isoformat()
            except Exception:
                return value
        return value

    def _serialize_row(self, row: dict[str, Any] | Any) -> dict[str, Any]:
        if isinstance(row, dict):
            return {key: self._serialize_value(value) for key, value in row.items()}
        return {}

    def _query_rows(
        self,
        table_name: str,
        *,
        filters: dict[str, Any] | None = None,
        order_by: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        table = self._get_table(table_name)
        if table is None:
            return []
        stmt = select(table)
        columns = table.c
        for key, value in (filters or {}).items():
            if key not in columns or value is None:
                continue
            column = columns[key]
            if isinstance(value, (list, tuple, set)):
                normalized = [item for item in value if item is not None]
                if normalized:
                    stmt = stmt.where(func.lower(column).in_([str(item).lower() for item in normalized]))
            elif isinstance(value, str):
                stmt = stmt.where(func.lower(column) == value.lower())
            else:
                stmt = stmt.where(column == value)
        if order_by and order_by in columns:
            stmt = stmt.order_by(desc(columns[order_by]))
        if limit > 0:
            stmt = stmt.limit(limit)
        rows = self.db.execute(stmt).mappings().all()
        return [self._serialize_row(dict(row)) for row in rows]

    def _query_first(
        self,
        table_name: str,
        *,
        filters: dict[str, Any] | None = None,
        order_by: str | None = None,
    ) -> dict[str, Any] | None:
        rows = self._query_rows(table_name, filters=filters, order_by=order_by, limit=1)
        return rows[0] if rows else None

    def _news_slug(self, title: str) -> str:
        return _sector_slug(title)

    def _enrich_stock_identity(self, stock: StockIdentity) -> StockIdentity:
        needs_enrichment = not any([stock.sector, stock.industry, stock.market_cap, stock.description, stock.short_name, stock.isin])
        if not needs_enrichment or not stock.symbol:
            return stock

        ticker = f"{stock.symbol.upper()}.NS"
        stock_info = (
            self.db.query(StockInfo)
            .filter(func.lower(StockInfo.ticker) == ticker.lower())
            .order_by(desc(StockInfo.fetched_at))
            .first()
        )
        if not stock_info:
            return stock

        source_tables = list(stock.source_tables)
        if "stock_info" not in source_tables:
            source_tables.append("stock_info")

        return stock.model_copy(
            update={
                "company_name": stock.company_name or stock_info.company_name,
                "short_name": stock.short_name,
                "description": stock.description or stock_info.description,
                "isin": stock.isin,
                "sector": stock.sector or stock_info.sector,
                "industry": stock.industry or stock_info.industry,
                "market_cap": stock.market_cap if stock.market_cap is not None else _safe_float(stock_info.market_cap),
                "source_tables": source_tables,
            }
        )

    def _resolve_stock(self, stock_input: str) -> StockIdentity | None:
        stock, _, _ = self.compare.resolver.resolve_stock(stock_input)
        if stock:
            stock = self._enrich_stock_identity(stock)
            logger.info(
                "landing resolve success input=%s symbol=%s slug=%s sector=%s industry=%s source_tables=%s",
                stock_input,
                stock.symbol,
                stock.slug,
                stock.sector,
                stock.industry,
                stock.source_tables,
            )
        else:
            logger.warning("landing resolve failed input=%s", stock_input)
        return stock

    def _ticker(self, stock: StockIdentity) -> str | None:
        return f"{stock.symbol}.NS" if stock and stock.symbol else None

    def _build_quality(
        self,
        *,
        available: list[str],
        missing: list[str],
        last_updated: str | None,
        warnings: list[str],
    ) -> DataQuality:
        if len(available) >= 3:
            status = "complete"
        elif len(available) >= 2:
            status = "partial"
        elif len(available) == 1:
            status = "limited"
        else:
            status = "missing"
        completeness_score = int(round((len(available) / max(len(available) + len(missing), 1)) * 100))
        return DataQuality(
            status=status,
            completeness_score=completeness_score,
            available_sections=available,
            missing_sections=missing,
            last_updated=last_updated,
            warnings=warnings,
        )

    def _build_seo(self, canonical_path: str, quality: DataQuality, reason: str) -> SeoEligibility:
        indexable = quality.status in {"complete", "partial"}
        return SeoEligibility(
            indexable=indexable,
            sitemap_eligible=indexable,
            noindex_recommended=not indexable,
            reason=reason,
            minimum_content_passed=indexable,
        )

    def get_stock_financials(self, symbol: str) -> LandingResponse:
        logger.info("landing financials requested symbol=%s", symbol)
        stock = self._resolve_stock(symbol)
        canonical_path = f"/stocks/{symbol.lower()}/financials"
        if not stock:
            quality = self._build_quality(
                available=[],
                missing=["identity", "financial_statements"],
                last_updated=None,
                warnings=["Stock could not be resolved"],
            )
            return LandingResponse(
                canonical_path=canonical_path,
                entity=LandingEntity(),
                sections={
                    "financial_statements": LandingSectionStatus(
                        status="missing",
                        summary="No verified stock identity or financial data was found.",
                    )
                },
                data_quality=quality,
                seo_eligibility=self._build_seo(canonical_path, quality, "Stock could not be resolved"),
            )

        payload = self.stocks.get_stock_financials(stock.symbol or symbol)
        sections: dict[str, LandingSectionStatus] = {}
        available: list[str] = []
        missing: list[str] = []

        financial_payload = payload.get("financials") if payload else {}
        balance_payload = payload.get("balance_sheet") if payload else {}
        cash_payload = payload.get("cash_flow") if payload else {}
        quarterly_income_payload = payload.get("quarterly_financials") if payload else {}
        quarterly_balance_payload = payload.get("quarterly_balance_sheet") if payload else {}
        quarterly_cash_payload = payload.get("quarterly_cash_flow") if payload else {}
        quarterly_history = payload.get("quarterly_history") if payload else {}
        statement_dates = payload.get("statement_dates") if payload else {}

        if financial_payload:
            available.append("annual_income_statement")
        else:
            missing.append("annual_income_statement")
        if balance_payload:
            available.append("annual_balance_sheet")
        else:
            missing.append("annual_balance_sheet")
        if cash_payload:
            available.append("annual_cashflow")
        else:
            missing.append("annual_cashflow")
        if quarterly_income_payload:
            available.append("quarterly_income_statement")
        else:
            missing.append("quarterly_income_statement")
        if quarterly_balance_payload:
            available.append("quarterly_balance_sheet")
        else:
            missing.append("quarterly_balance_sheet")
        if quarterly_cash_payload:
            available.append("quarterly_cashflow")
        else:
            missing.append("quarterly_cashflow")

        sections["financial_statements"] = LandingSectionStatus(
            status="available" if available else "missing",
            summary="Latest annual and quarterly statement snapshots pulled from verified financial rows.",
            payload={
                "annual_income_statement": financial_payload or {},
                "annual_balance_sheet": balance_payload or {},
                "annual_cashflow": cash_payload or {},
                "quarterly_income_statement": quarterly_income_payload or {},
                "quarterly_balance_sheet": quarterly_balance_payload or {},
                "quarterly_cashflow": quarterly_cash_payload or {},
                "quarterly_history": quarterly_history or {},
                "statement_dates": statement_dates or {},
                "fetched_at": payload.get("fetched_at") if payload else None,
            },
        )

        if payload and payload.get("fetched_at"):
            available.append("freshness")
        else:
            missing.append("freshness")

        quality = self._build_quality(
            available=available,
            missing=missing,
            last_updated=payload.get("fetched_at") if payload else None,
            warnings=[] if available else ["No verified stock_financials rows found for the latest snapshot"],
        )
        canonical_path = f"/stocks/{stock.slug}/financials"
        reason = "Verified financial statements available" if available else "No verified statement rows available"
        logger.info(
            "landing financials built symbol=%s slug=%s available=%s missing=%s quality=%s",
            stock.symbol,
            stock.slug,
            available,
            missing,
            quality.status,
        )
        return LandingResponse(
            canonical_path=canonical_path,
            entity=LandingEntity(stock=stock),
            sections=sections,
            related_links=[
                RelatedLink(label="Overview", path=stock.canonical_path),
                RelatedLink(label="Key ratios", path=f"/stocks/{stock.slug}/key-ratios"),
                RelatedLink(label="Price history", path=f"/stocks/{stock.slug}/price-history"),
                RelatedLink(label="Competitors", path=f"/stocks/{stock.slug}/competitors"),
            ],
            faq=[
                {"q": f"Does {stock.company_name} have verified financial rows?", "a": "This endpoint returns only the latest verified statement snapshots present in the database."},
                {"q": "Are missing values estimated?", "a": "No. Missing sections remain missing and are not backfilled with invented numbers."},
            ],
            schema_payload={"page_type": "stock_financials", "stock_slug": stock.slug},
            data_quality=quality,
            seo_eligibility=self._build_seo(canonical_path, quality, reason),
        )

    def get_stock_overview(self, symbol: str) -> LandingResponse:
        logger.info("landing overview requested symbol=%s", symbol)
        stock = self._resolve_stock(symbol)
        canonical_path = f"/stocks/{symbol.lower()}"
        if not stock:
            quality = self._build_quality(
                available=[],
                missing=["identity", "overview"],
                last_updated=None,
                warnings=["Stock could not be resolved"],
            )
            return LandingResponse(
                canonical_path=canonical_path,
                sections={"overview": LandingSectionStatus(status="missing", summary="Stock could not be resolved.")},
                data_quality=quality,
                seo_eligibility=self._build_seo(canonical_path, quality, "Stock could not be resolved"),
            )

        ticker = self._ticker(stock)
        live = self.stocks.get_stock_live(stock.symbol or symbol) or {}
        stock_info = self.compare._fetch_stock_info(ticker) if ticker else None
        prices = self.compare._fetch_stock_prices(ticker, limit=90) if ticker else []
        news = self.compare._fetch_news(stock)
        fin = self.stocks.get_stock_financials(stock.symbol or symbol) or {}

        available: list[str] = ["identity"]
        missing: list[str] = []
        if stock_info:
            available.append("snapshot")
        else:
            missing.append("snapshot")
        if prices:
            available.append("price_history")
        else:
            missing.append("price_history")
        if fin.get("ratios") or fin.get("financials"):
            available.append("financial_context")
        else:
            missing.append("financial_context")
        if news.get("items"):
            available.append("news")
        else:
            missing.append("news")
        if live.get("fno"):
            available.append("fno")
        else:
            missing.append("fno")

        last_dates = [p.get("date") for p in prices if p.get("date")]
        latest_price_date = max(last_dates) if last_dates else None
        fetched_at = fin.get("fetched_at")
        last_updated = fetched_at or latest_price_date
        quality = self._build_quality(
            available=available,
            missing=missing,
            last_updated=str(last_updated) if last_updated else None,
            warnings=[],
        )
        canonical_path = stock.canonical_path
        logger.info(
            "landing overview built symbol=%s slug=%s sections=%s quality=%s last_updated=%s",
            stock.symbol,
            stock.slug,
            available,
            quality.status,
            quality.last_updated,
        )
        sections = {
            "overview": LandingSectionStatus(
                status="available",
                summary="Resolved stock identity and latest landing-page context.",
                payload={
                    "description": stock.description,
                    "sector": stock.sector,
                    "industry": stock.industry,
                    "market_cap": stock.market_cap,
                },
            ),
            "price_snapshot": LandingSectionStatus(
                status="available" if live.get("latest_price") else "missing",
                summary="Latest available close and recent price history.",
                payload={"latest_price": live.get("latest_price"), "recent_prices": prices[:30]},
            ),
            "financial_snapshot": LandingSectionStatus(
                status="available" if fin.get("financials") or fin.get("ratios") else "missing",
                summary="Latest financial and ratio snapshot from stock_info and stock_financials.",
                payload={"ratios": fin.get("ratios") or {}, "financials": fin.get("financials") or {}},
            ),
            "news": LandingSectionStatus(
                status="available" if news.get("items") else "missing",
                summary="Recent related news mentions when available.",
                payload=news,
            ),
            "fno": LandingSectionStatus(
                status="available" if live.get("fno") else "missing",
                summary="Latest F&O positioning snapshot when the stock is F&O eligible.",
                payload=live.get("fno") or {},
            ),
        }
        return LandingResponse(
            canonical_path=canonical_path,
            entity=LandingEntity(stock=stock),
            sections=sections,
            related_links=[
                RelatedLink(label="Financials", path=f"/stocks/{stock.slug}/financials"),
                RelatedLink(label="Key ratios", path=f"/stocks/{stock.slug}/key-ratios"),
                RelatedLink(label="Price history", path=f"/stocks/{stock.slug}/price-history"),
                RelatedLink(label="Sector page", path=f"/sector/{_sector_slug(stock.sector)}", enabled=bool(stock.sector)),
            ],
            faq=[
                {"q": f"What does the {stock.company_name} overview include?", "a": "The overview combines resolved identity, recent prices, financial context, recent news, and F&O context when available."},
                {"q": "Are advisory calls generated here?", "a": "No. This response is descriptive and leaves missing data explicitly missing."},
            ],
            schema_payload={"page_type": "stock_overview", "stock_slug": stock.slug},
            data_quality=quality,
            seo_eligibility=self._build_seo(canonical_path, quality, "Stock overview has enough primary data" if quality.status in {"complete", "partial"} else "Stock overview is too sparse"),
        )

    def get_stock_ratios(self, symbol: str) -> LandingResponse:
        logger.info("landing ratios requested symbol=%s", symbol)
        stock = self._resolve_stock(symbol)
        canonical_path = f"/stocks/{symbol.lower()}/key-ratios"
        if not stock:
            quality = self._build_quality(
                available=[],
                missing=["identity", "ratios"],
                last_updated=None,
                warnings=["Stock could not be resolved"],
            )
            return LandingResponse(
                canonical_path=canonical_path,
                sections={"ratios": LandingSectionStatus(status="missing", summary="Stock could not be resolved.")},
                data_quality=quality,
                seo_eligibility=self._build_seo(canonical_path, quality, "Stock could not be resolved"),
            )

        fin = self.stocks.get_stock_financials(stock.symbol or symbol) or {}
        ratios = fin.get("ratios") or {}
        balance_sheet = fin.get("balance_sheet") or {}
        cash_flow = fin.get("cash_flow") or {}
        pe_history = self.stocks.get_stock_pe_history(stock.symbol or symbol, limit=12)
        latest_pe = pe_history[0] if pe_history else {}
        payload = {
            "pe_ratio": latest_pe.get("pe"),
            "adjusted_pe": latest_pe.get("adjusted_pe"),
            "pe_report_date": latest_pe.get("report_date"),
            **ratios,
            "free_cash_flow": cash_flow.get("Free Cash Flow"),
            "total_debt": balance_sheet.get("Total Debt"),
            "cash_and_equivalents": balance_sheet.get("Cash And Cash Equivalents"),
            "quarterly_periods_available": len((fin.get("quarterly_history") or {}).get("income_statement") or []),
            "pe_history": pe_history,
        }
        primary_ratio_fields = [
            "pe_ratio",
            "trailing_pe",
            "forward_pe",
            "price_to_book",
            "dividend_yield",
            "roe",
            "roa",
            "profit_margins",
            "revenue_growth",
            "earnings_growth",
            "eps",
            "forward_eps",
        ]
        primary_ratio_count = sum(1 for key in primary_ratio_fields if payload.get(key) is not None)
        available = ["identity"] + (["ratios"] if primary_ratio_count >= 5 else [])
        if pe_history:
            available.append("pe_history")
        missing = [] if primary_ratio_count >= 5 else ["ratios"]
        if not pe_history:
            missing.append("pe_history")
        quality = self._build_quality(
            available=available,
            missing=missing,
            last_updated=latest_pe.get("report_date") or fin.get("fetched_at"),
            warnings=[] if primary_ratio_count >= 5 else ["Fewer than five primary ratio fields are available"],
        )
        logger.info(
            "landing ratios built symbol=%s slug=%s ratio_fields=%s quality=%s",
            stock.symbol,
            stock.slug,
            primary_ratio_count,
            quality.status,
        )
        return LandingResponse(
            canonical_path=f"/stocks/{stock.slug}/key-ratios",
            entity=LandingEntity(stock=stock),
            sections={
                "ratios": LandingSectionStatus(
                    status="available" if primary_ratio_count >= 5 else "partial",
                    summary="Latest ratio snapshot from stock_info with live PE history and balance-sheet context.",
                    payload=payload,
                )
            },
            related_links=[
                RelatedLink(label="Overview", path=stock.canonical_path),
                RelatedLink(label="Financials", path=f"/stocks/{stock.slug}/financials"),
                RelatedLink(label="Price history", path=f"/stocks/{stock.slug}/price-history"),
            ],
            faq=[
                {"q": f"What ratio fields are available for {stock.company_name}?", "a": "This endpoint returns the latest verified valuation, profitability, growth, and selected balance-sheet or cash-flow context fields present in the database."},
            ],
            schema_payload={"page_type": "stock_ratios", "stock_slug": stock.slug},
            data_quality=quality,
            seo_eligibility=self._build_seo(f"/stocks/{stock.slug}/key-ratios", quality, "Ratio page has sufficient primary fields" if primary_ratio_count >= 5 else "Ratio page is sparse"),
        )

    def get_stock_price_history(self, symbol: str) -> LandingResponse:
        logger.info("landing price-history requested symbol=%s", symbol)
        stock = self._resolve_stock(symbol)
        canonical_path = f"/stocks/{symbol.lower()}/price-history"
        if not stock:
            quality = self._build_quality(
                available=[],
                missing=["identity", "price_history"],
                last_updated=None,
                warnings=["Stock could not be resolved"],
            )
            return LandingResponse(
                canonical_path=canonical_path,
                sections={"price_history": LandingSectionStatus(status="missing", summary="Stock could not be resolved.")},
                data_quality=quality,
                seo_eligibility=self._build_seo(canonical_path, quality, "Stock could not be resolved"),
            )

        ticker = self._ticker(stock)
        prices = self.compare._fetch_stock_prices(ticker, limit=260) if ticker else []
        returns = self.compare._calc_returns(prices) if prices else {}
        available = ["identity"] + (["price_history"] if len(prices) >= 90 else [])
        missing = [] if len(prices) >= 90 else ["price_history"]
        last_updated = str(prices[0].get("date")) if prices else None
        quality = self._build_quality(
            available=available,
            missing=missing,
            last_updated=last_updated,
            warnings=[] if len(prices) >= 90 else ["Fewer than 90 price rows are available"],
        )
        logger.info(
            "landing price-history built symbol=%s slug=%s rows=%s quality=%s",
            stock.symbol,
            stock.slug,
            len(prices),
            quality.status,
        )
        return LandingResponse(
            canonical_path=f"/stocks/{stock.slug}/price-history",
            entity=LandingEntity(stock=stock),
            sections={
                "price_history": LandingSectionStatus(
                    status="available" if len(prices) >= 90 else "partial",
                    summary="Recent verified price history and derived return ranges.",
                    payload={
                        "prices": prices,
                        "summary": returns,
                    },
                )
            },
            related_links=[
                RelatedLink(label="Overview", path=stock.canonical_path),
                RelatedLink(label="Financials", path=f"/stocks/{stock.slug}/financials"),
                RelatedLink(label="Key ratios", path=f"/stocks/{stock.slug}/key-ratios"),
            ],
            faq=[
                {"q": f"How much history is available for {stock.company_name}?", "a": "This endpoint returns up to the latest 260 verified stock_price rows for the resolved ticker."},
            ],
            schema_payload={"page_type": "stock_price_history", "stock_slug": stock.slug},
            data_quality=quality,
            seo_eligibility=self._build_seo(f"/stocks/{stock.slug}/price-history", quality, "Price-history page has enough rows" if len(prices) >= 90 else "Price-history page is sparse"),
        )

    def get_stock_bull_bear(self, symbol: str) -> LandingResponse:
        logger.info("landing bull-bear requested symbol=%s", symbol)
        stock = self._resolve_stock(symbol)
        canonical_path = f"/stocks/{symbol.lower()}/bull-case-bear-case"
        if not stock:
            quality = self._build_quality(
                available=[],
                missing=["identity", "bull_bear"],
                last_updated=None,
                warnings=["Stock could not be resolved"],
            )
            return LandingResponse(
                canonical_path=canonical_path,
                sections={"bull_bear": LandingSectionStatus(status="missing", summary="Stock could not be resolved.")},
                data_quality=quality,
                seo_eligibility=self._build_seo(canonical_path, quality, "Stock could not be resolved"),
            )

        ticker = self._ticker(stock)
        fin = self.stocks.get_stock_financials(stock.symbol or symbol) or {}
        info = self.compare._fetch_stock_info(ticker) if ticker else None
        analysis = self.compare._fetch_stock_analysis(ticker) if ticker else None
        prices = self.compare._fetch_stock_prices(ticker, limit=90) if ticker else []
        news = self.compare._fetch_news(stock)

        support_points: list[str] = []
        risk_points: list[str] = []

        if fin.get("ratios", {}).get("revenue_growth") is not None:
            growth = fin["ratios"]["revenue_growth"]
            if growth and growth > 0:
                support_points.append(f"Revenue growth is positive at {growth:.2%}.")
            else:
                risk_points.append("Revenue growth is weak or negative in the latest snapshot.")
        if fin.get("ratios", {}).get("earnings_growth") is not None:
            earnings_growth = fin["ratios"]["earnings_growth"]
            if earnings_growth and earnings_growth > 0:
                support_points.append(f"Earnings growth is positive at {earnings_growth:.2%}.")
            else:
                risk_points.append("Earnings growth is weak or negative in the latest snapshot.")
        if fin.get("ratios", {}).get("roe") is not None:
            roe = fin["ratios"]["roe"]
            if roe and roe >= 0.12:
                support_points.append(f"Return on equity is healthy at {roe:.2%}.")
            else:
                risk_points.append("Return on equity is modest relative to typical quality thresholds.")

        latest_close = _safe_float(prices[0].get("close")) if prices else None
        oldest_close = _safe_float(prices[-1].get("close")) if prices else None
        if latest_close is not None and oldest_close not in (None, 0):
            return_pct = ((latest_close - oldest_close) / oldest_close) * 100
            if return_pct > 0:
                support_points.append(f"Price has risen {return_pct:.2f}% over the sampled history window.")
            else:
                risk_points.append(f"Price has fallen {abs(return_pct):.2f}% over the sampled history window.")

        latest_news = news.get("latest") or []
        if latest_news:
            support_points.append("Recent news mentions exist, which adds current-event context to the page.")
        else:
            risk_points.append("Recent news context is limited in the current dataset.")

        for point in (analysis or {}).get("bull_case", [])[:2]:
            if isinstance(point, str) and point.strip():
                support_points.append(point.strip())
        for point in (analysis or {}).get("bear_case", [])[:2]:
            if isinstance(point, str) and point.strip():
                risk_points.append(point.strip())
        for point in (analysis or {}).get("red_flags", [])[:2]:
            if isinstance(point, str) and point.strip():
                risk_points.append(point.strip())

        support_points = support_points[:6]
        risk_points = risk_points[:6]
        available = ["identity"]
        if len(support_points) >= 2:
            available.append("supportive_context")
        if len(risk_points) >= 2:
            available.append("risk_context")
        missing = []
        if "supportive_context" not in available:
            missing.append("supportive_context")
        if "risk_context" not in available:
            missing.append("risk_context")
        quality = self._build_quality(
            available=available,
            missing=missing,
            last_updated=fin.get("fetched_at"),
            warnings=[] if len(support_points) >= 2 and len(risk_points) >= 2 else ["Bull/bear context is thinner than the target threshold"],
        )
        logger.info(
            "landing bull-bear built symbol=%s slug=%s support_points=%s risk_points=%s quality=%s",
            stock.symbol,
            stock.slug,
            len(support_points),
            len(risk_points),
            quality.status,
        )
        return LandingResponse(
            canonical_path=f"/stocks/{stock.slug}/bull-case-bear-case",
            entity=LandingEntity(stock=stock),
            sections={
                "bull_bear": LandingSectionStatus(
                    status="available" if len(support_points) >= 2 and len(risk_points) >= 2 else "partial",
                    summary="Supportive context and risk context from financial, price, and event signals.",
                    payload={
                        "supportive_context": support_points,
                        "risk_context": risk_points,
                        "what_to_monitor": [
                            "Revenue and earnings trend changes",
                            "Event/news flow around the company and sector",
                            "Price trend and volatility shifts",
                        ],
                    },
                )
            },
            related_links=[
                RelatedLink(label="Overview", path=stock.canonical_path),
                RelatedLink(label="Financials", path=f"/stocks/{stock.slug}/financials"),
                RelatedLink(label="Risk signals", path=f"/stocks/{stock.slug}/risk-signals"),
            ],
            faq=[
                {"q": f"Is the {stock.company_name} bull/bear page a recommendation?", "a": "No. It is a research-context page with supportive and risk factors only."},
            ],
            schema_payload={"page_type": "stock_bull_bear", "stock_slug": stock.slug},
            data_quality=quality,
            seo_eligibility=self._build_seo(f"/stocks/{stock.slug}/bull-case-bear-case", quality, "Bull/bear page has enough real supportive and risk points" if len(support_points) >= 2 and len(risk_points) >= 2 else "Bull/bear page is too thin"),
        )

    def get_stock_risk_signals(self, symbol: str) -> LandingResponse:
        logger.info("landing risk-signals requested symbol=%s", symbol)
        stock = self._resolve_stock(symbol)
        canonical_path = f"/stocks/{symbol.lower()}/risk-signals"
        if not stock:
            quality = self._build_quality(
                available=[],
                missing=["identity", "risk_signals"],
                last_updated=None,
                warnings=["Stock could not be resolved"],
            )
            return LandingResponse(
                canonical_path=canonical_path,
                sections={"risk_signals": LandingSectionStatus(status="missing", summary="Stock could not be resolved.")},
                data_quality=quality,
                seo_eligibility=self._build_seo(canonical_path, quality, "Stock could not be resolved"),
            )

        ticker = self._ticker(stock)
        metrics_table = self.compare._get_table("stock_daily_metrics")
        anomaly_table = self.compare._get_table("nexus_anomaly_scores")
        signal_table = self.compare._get_table("nexus_signal_instances")

        risk_snapshot: dict[str, Any] = {}
        if metrics_table is not None and ticker:
            cols = metrics_table.c
            row = self.db.execute(
                select(metrics_table)
                .where(func.lower(cols["symbol"]) == (stock.symbol or "").lower())
                .order_by(desc(cols["trade_date"]))
                .limit(1)
            ).mappings().first()
            if row:
                risk_snapshot = {
                    "trade_date": str(row.get("trade_date", "")),
                    "risk_score": _safe_float(row.get("risk_score")),
                    "realized_vol_20": _safe_float(row.get("realized_vol_20")),
                    "news_volume_anomaly": _safe_float(row.get("news_volume_anomaly")),
                    "news_sentiment": _safe_float(row.get("news_sentiment")),
                    "trend_regime": row.get("trend_regime"),
                    "volatility_regime": row.get("volatility_regime"),
                    "liquidity_regime": row.get("liquidity_regime"),
                }

        anomaly_items: list[dict[str, Any]] = []
        if anomaly_table is not None and stock.symbol:
            cols = anomaly_table.c
            rows = self.db.execute(
                select(anomaly_table)
                .where(func.lower(cols["symbol"]) == stock.symbol.lower())
                .order_by(desc(cols["computed_at"]))
                .limit(5)
            ).mappings().all()
            anomaly_items = [
                {
                    "signal_family": row.get("signal_family"),
                    "metric_name": row.get("metric_name"),
                    "anomaly_score": _safe_float(row.get("anomaly_score")),
                    "zscore": _safe_float(row.get("zscore")),
                    "computed_at": _safe_datetime(row.get("computed_at")),
                }
                for row in rows
            ]

        if not anomaly_items:
            fallback_rows = self.db.execute(
                text("""
                    SELECT signal_code AS metric_name, severity AS signal_family,
                           confidence AS anomaly_score, NULL AS zscore, title, summary,
                           created_at AS computed_at
                    FROM scanner_signals
                    WHERE symbol = :sym
                    ORDER BY created_at DESC
                """),
                {"sym": symbol},
            ).fetchall()
            anomaly_items = [
                {
                    "signal_family": row.signal_family,
                    "metric_name": row.metric_name,
                    "anomaly_score": _safe_float(row.anomaly_score),
                    "zscore": _safe_float(row.zscore),
                    "computed_at": _safe_datetime(row.computed_at),
                    "title": row.title,
                    "summary": row.summary,
                }
                for row in fallback_rows
            ]

        signal_items: list[dict[str, Any]] = []
        if signal_table is not None and stock.symbol:
            cols = signal_table.c
            rows = self.db.execute(
                select(signal_table)
                .where(func.lower(cols["underlying_symbol"]) == stock.symbol.lower())
                .order_by(desc(cols["event_time"]))
                .limit(5)
            ).mappings().all()
            signal_items = [
                {
                    "signal_code": row.get("signal_code"),
                    "severity": row.get("severity"),
                    "confidence": _safe_float(row.get("confidence")),
                    "title": row.get("title"),
                    "summary": row.get("summary"),
                    "event_time": _safe_datetime(row.get("event_time")),
                }
                for row in rows
            ]

        risk_sources = 0
        if risk_snapshot:
            risk_sources += 1
        if anomaly_items:
            risk_sources += 1
        if signal_items:
            risk_sources += 1
        available = ["identity"] + (["risk_signals"] if risk_sources >= 2 else [])
        missing = [] if risk_sources >= 2 else ["risk_signals"]
        quality = self._build_quality(
            available=available,
            missing=missing,
            last_updated=risk_snapshot.get("trade_date") or (signal_items[0]["event_time"] if signal_items else None),
            warnings=[] if risk_sources >= 2 else ["Fewer than two real risk sources are available"],
        )
        logger.info(
            "landing risk-signals built symbol=%s slug=%s risk_sources=%s quality=%s",
            stock.symbol,
            stock.slug,
            risk_sources,
            quality.status,
        )
        return LandingResponse(
            canonical_path=f"/stocks/{stock.slug}/risk-signals",
            entity=LandingEntity(stock=stock),
            sections={
                "risk_signals": LandingSectionStatus(
                    status="available" if risk_sources >= 2 else "partial",
                    summary="Current risk context from daily metrics, anomaly scores, and signal instances.",
                    payload={
                        "risk_snapshot": risk_snapshot,
                        "anomalies": anomaly_items,
                        "signals": signal_items,
                    },
                )
            },
            related_links=[
                RelatedLink(label="Overview", path=stock.canonical_path),
                RelatedLink(label="Bull vs bear context", path=f"/stocks/{stock.slug}/bull-case-bear-case"),
                RelatedLink(label="Price history", path=f"/stocks/{stock.slug}/price-history"),
            ],
            faq=[
                {"q": f"What do ArinEdge risk signals for {stock.company_name} represent?", "a": "They summarize available volatility, anomaly, and event-driven risk context from the current database snapshot."},
            ],
            schema_payload={"page_type": "stock_risk_signals", "stock_slug": stock.slug},
            data_quality=quality,
            seo_eligibility=self._build_seo(f"/stocks/{stock.slug}/risk-signals", quality, "Risk page has at least two real risk sources" if risk_sources >= 2 else "Risk page is too sparse"),
        )

    def get_sector_overview(self, slug: str) -> LandingResponse:
        logger.info("landing sector requested slug=%s", slug)
        sector_rows = self.stocks.get_stocks_by_sector().get("sectors", {})
        matched_name = None
        matched_stocks: list[dict[str, Any]] = []
        for name, stocks in sector_rows.items():
            if _sector_slug(name) == slug:
                matched_name = name
                matched_stocks = stocks
                break

        canonical_path = f"/sector/{slug}"
        if not matched_name:
            quality = self._build_quality(
                available=[],
                missing=["sector_identity", "stocks"],
                last_updated=None,
                warnings=["Sector slug could not be matched"],
            )
            return LandingResponse(
                canonical_path=canonical_path,
                sections={"sector": LandingSectionStatus(status="missing", summary="Sector slug could not be matched.")},
                data_quality=quality,
                seo_eligibility=self._build_seo(canonical_path, quality, "Sector could not be resolved"),
            )

        sorted_stocks = sorted(
            matched_stocks,
            key=lambda row: (row.get("market_cap") is None, -(row.get("market_cap") or 0)),
        )
        available = ["sector_identity", "stocks"]
        quality = self._build_quality(
            available=available,
            missing=[],
            last_updated=_safe_datetime(datetime.utcnow()),
            warnings=[],
        )
        logger.info(
            "landing sector built slug=%s name=%s stock_count=%s quality=%s",
            slug,
            matched_name,
            len(sorted_stocks),
            quality.status,
        )
        sections = {
            "sector": LandingSectionStatus(
                status="available",
                summary="Resolved sector and its listed stocks from stock_info.",
                payload={
                    "sector_name": matched_name,
                    "stock_count": len(sorted_stocks),
                    "stocks": sorted_stocks[:100],
                },
            )
        }
        return LandingResponse(
            canonical_path=canonical_path,
            entity=LandingEntity(sector={"name": matched_name, "slug": slug, "stock_count": len(sorted_stocks)}),
            sections=sections,
            related_links=[
                RelatedLink(label=row["company_name"], path=f"/stocks/{row['slug']}")
                for row in sorted_stocks[:10]
            ],
            faq=[
                {"q": f"How is the {matched_name} sector page built?", "a": "It is built from current stock_info sector labels and includes only resolved listed stocks."},
                {"q": "Are sector slugs hardcoded?", "a": "No. The landing API resolves the slug from the current sector label values."},
            ],
            schema_payload={"page_type": "sector", "sector_slug": slug},
            data_quality=quality,
            seo_eligibility=self._build_seo(canonical_path, quality, "Sector page has resolved primary stock data"),
        )

    def get_stock_competitors(self, symbol: str) -> LandingResponse:
        logger.info("landing competitors requested symbol=%s", symbol)
        stock = self._resolve_stock(symbol)
        canonical_path = f"/stocks/{symbol.lower()}/competitors"
        if not stock:
            quality = self._build_quality(
                available=[],
                missing=["identity", "peers"],
                last_updated=None,
                warnings=["Stock could not be resolved"],
            )
            return LandingResponse(
                canonical_path=canonical_path,
                sections={"peers": LandingSectionStatus(status="missing", summary="Stock could not be resolved.")},
                data_quality=quality,
                seo_eligibility=self._build_seo(canonical_path, quality, "Stock could not be resolved"),
            )

        industry_groups = self.stocks.get_stocks_by_industry().get("industries", {})
        sector_groups = self.stocks.get_stocks_by_sector().get("sectors", {})
        industry_peers = industry_groups.get(stock.industry or "", [])
        sector_peers = sector_groups.get(stock.sector or "", [])
        base_market_cap = stock.market_cap or 0

        def _peer_filter(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            cleaned = []
            for row in rows:
                peer_symbol = row.get("symbol")
                if not peer_symbol or str(peer_symbol).upper() == (stock.symbol or "").upper():
                    continue
                cleaned.append(
                    {
                        "symbol": row.get("symbol"),
                        "company_name": row.get("company_name"),
                        "slug": row.get("slug") or _sector_slug(str(peer_symbol)),
                        "sector": row.get("sector") or stock.sector,
                        "industry": row.get("industry") or stock.industry,
                        "market_cap": _safe_float(row.get("market_cap")),
                        "market_cap_gap": abs((_safe_float(row.get("market_cap")) or 0) - base_market_cap) if base_market_cap else None,
                    }
                )
            cleaned.sort(key=lambda item: (item["market_cap_gap"] is None, item["market_cap_gap"] or 0))
            return cleaned[:12]

        direct_peers = _peer_filter(industry_peers)
        sector_only_peers = _peer_filter(sector_peers)
        available = ["identity"]
        if direct_peers:
            available.append("industry_peers")
        if sector_only_peers:
            available.append("sector_peers")
        missing = [name for name in ("industry_peers", "sector_peers") if name not in available]
        quality = self._build_quality(
            available=available,
            missing=missing,
            last_updated=None,
            warnings=[] if len(direct_peers) >= 3 or len(sector_only_peers) >= 3 else ["Peer coverage is limited for this symbol"],
        )
        return LandingResponse(
            canonical_path=f"/stocks/{stock.slug}/competitors",
            entity=LandingEntity(stock=stock),
            sections={
                "peers": LandingSectionStatus(
                    status="available" if direct_peers or sector_only_peers else "partial",
                    summary="Listed peers selected from current industry and sector groups.",
                    payload={
                        "industry_peers": direct_peers,
                        "sector_peers": sector_only_peers[:12],
                    },
                )
            },
            related_links=[
                RelatedLink(label="Overview", path=stock.canonical_path),
                RelatedLink(label="Financials", path=f"/stocks/{stock.slug}/financials"),
                RelatedLink(label="Key ratios", path=f"/stocks/{stock.slug}/key-ratios"),
            ],
            faq=[
                {"q": f"How are peers for {stock.company_name} selected?", "a": "Peers are selected from current industry and sector mappings, prioritizing listed names with closer market-cap range."}
            ],
            schema_payload={"page_type": "stock_competitors", "stock_slug": stock.slug},
            data_quality=quality,
            seo_eligibility=self._build_seo(f"/stocks/{stock.slug}/competitors", quality, "Competitor page has peer coverage" if quality.status in {"complete", "partial"} else "Competitor page is too thin"),
        )

    def get_stock_fno_positioning(self, symbol: str) -> LandingResponse:
        logger.info("landing fno-positioning requested symbol=%s", symbol)
        stock = self._resolve_stock(symbol)
        canonical_path = f"/stocks/{symbol.lower()}/fno-positioning"
        if not stock:
            quality = self._build_quality(available=[], missing=["identity", "fno"], last_updated=None, warnings=["Stock could not be resolved"])
            return LandingResponse(canonical_path=canonical_path, sections={"fno": LandingSectionStatus(status="missing", summary="Stock could not be resolved.")}, data_quality=quality, seo_eligibility=self._build_seo(canonical_path, quality, "Stock could not be resolved"))

        live = self.stocks.get_stock_live(stock.symbol or symbol) or {}
        fno = live.get("fno") or {}
        available = ["identity"] + (["fno"] if fno else [])
        missing = [] if fno else ["fno"]
        quality = self._build_quality(available=available, missing=missing, last_updated=(live.get("latest_price") or {}).get("date"), warnings=[] if fno else ["No F&O snapshot is available for this symbol"])
        return LandingResponse(
            canonical_path=f"/stocks/{stock.slug}/fno-positioning",
            entity=LandingEntity(stock=stock),
            sections={"fno_positioning": LandingSectionStatus(status="available" if fno else "missing", summary="Latest F&O positioning snapshot and strike concentration.", payload=fno)},
            related_links=[RelatedLink(label="OI analysis", path=f"/stocks/{stock.slug}/oi-analysis"), RelatedLink(label="PCR", path=f"/stocks/{stock.slug}/put-call-ratio"), RelatedLink(label="Overview", path=stock.canonical_path)],
            faq=[{"q": f"Does {stock.company_name} have F&O context?", "a": "This page shows the latest options positioning snapshot only when current F&O rows are available."}],
            schema_payload={"page_type": "stock_fno_positioning", "stock_slug": stock.slug},
            data_quality=quality,
            seo_eligibility=self._build_seo(f"/stocks/{stock.slug}/fno-positioning", quality, "F&O snapshot available" if fno else "No F&O snapshot available"),
        )

    def get_stock_oi_analysis(self, symbol: str) -> LandingResponse:
        logger.info("landing oi-analysis requested symbol=%s", symbol)
        stock = self._resolve_stock(symbol)
        canonical_path = f"/stocks/{symbol.lower()}/oi-analysis"
        if not stock:
            quality = self._build_quality(available=[], missing=["identity", "oi"], last_updated=None, warnings=["Stock could not be resolved"])
            return LandingResponse(canonical_path=canonical_path, sections={"oi_analysis": LandingSectionStatus(status="missing", summary="Stock could not be resolved.")}, data_quality=quality, seo_eligibility=self._build_seo(canonical_path, quality, "Stock could not be resolved"))

        live = self.stocks.get_stock_live(stock.symbol or symbol) or {}
        fno = live.get("fno") or {}
        call_rows = fno.get("top_call_oi") or []
        put_rows = fno.get("top_put_oi") or []
        available = ["identity"] + (["oi"] if call_rows or put_rows else [])
        missing = [] if call_rows or put_rows else ["oi"]
        quality = self._build_quality(available=available, missing=missing, last_updated=(live.get("latest_price") or {}).get("date"), warnings=[] if call_rows or put_rows else ["No strike-level OI snapshot is available"])
        return LandingResponse(
            canonical_path=f"/stocks/{stock.slug}/oi-analysis",
            entity=LandingEntity(stock=stock),
            sections={"oi_analysis": LandingSectionStatus(status="available" if call_rows or put_rows else "missing", summary="Top call and put open-interest concentrations.", payload={"top_call_oi": call_rows, "top_put_oi": put_rows, "spot_price": fno.get("spot_price"), "expiry": fno.get("expiry")})},
            related_links=[RelatedLink(label="F&O positioning", path=f"/stocks/{stock.slug}/fno-positioning"), RelatedLink(label="PCR", path=f"/stocks/{stock.slug}/put-call-ratio")],
            faq=[{"q": "What does OI concentration show?", "a": "It shows where current call and put open interest is concentrated in the latest available options snapshot."}],
            schema_payload={"page_type": "stock_open_interest", "stock_slug": stock.slug},
            data_quality=quality,
            seo_eligibility=self._build_seo(f"/stocks/{stock.slug}/oi-analysis", quality, "OI snapshot available" if call_rows or put_rows else "No OI snapshot available"),
        )

    def get_stock_pcr(self, symbol: str) -> LandingResponse:
        logger.info("landing pcr requested symbol=%s", symbol)
        stock = self._resolve_stock(symbol)
        canonical_path = f"/stocks/{symbol.lower()}/put-call-ratio"
        if not stock:
            quality = self._build_quality(available=[], missing=["identity", "pcr"], last_updated=None, warnings=["Stock could not be resolved"])
            return LandingResponse(canonical_path=canonical_path, sections={"pcr": LandingSectionStatus(status="missing", summary="Stock could not be resolved.")}, data_quality=quality, seo_eligibility=self._build_seo(canonical_path, quality, "Stock could not be resolved"))
        live = self.stocks.get_stock_live(stock.symbol or symbol) or {}
        fno = live.get("fno") or {}
        pcr = fno.get("pcr_oi")
        available = ["identity"] + (["pcr"] if pcr is not None else [])
        missing = [] if pcr is not None else ["pcr"]
        quality = self._build_quality(available=available, missing=missing, last_updated=(live.get("latest_price") or {}).get("date"), warnings=[] if pcr is not None else ["PCR value is not available for this symbol"])
        return LandingResponse(
            canonical_path=f"/stocks/{stock.slug}/put-call-ratio",
            entity=LandingEntity(stock=stock),
            sections={"pcr": LandingSectionStatus(status="available" if pcr is not None else "missing", summary="Latest OI-based put-call ratio context.", payload={"pcr_oi": pcr, "atm_iv": fno.get("atm_iv"), "spot_price": fno.get("spot_price"), "net_gamma": fno.get("net_gamma")})},
            related_links=[RelatedLink(label="OI analysis", path=f"/stocks/{stock.slug}/oi-analysis"), RelatedLink(label="F&O positioning", path=f"/stocks/{stock.slug}/fno-positioning")],
            faq=[{"q": "What PCR value is shown here?", "a": "This page uses the latest available OI-based put-call ratio from the options snapshot."}],
            schema_payload={"page_type": "stock_pcr", "stock_slug": stock.slug},
            data_quality=quality,
            seo_eligibility=self._build_seo(f"/stocks/{stock.slug}/put-call-ratio", quality, "PCR snapshot available" if pcr is not None else "No PCR snapshot available"),
        )

    def get_stock_gamma_exposure(self, symbol: str) -> LandingResponse:
        logger.info("landing gamma-exposure requested symbol=%s", symbol)
        stock = self._resolve_stock(symbol)
        canonical_path = f"/stocks/{symbol.lower()}/gamma-exposure"
        if not stock:
            quality = self._build_quality(available=[], missing=["identity", "gamma"], last_updated=None, warnings=["Stock could not be resolved"])
            return LandingResponse(canonical_path=canonical_path, sections={"gamma_exposure": LandingSectionStatus(status="missing", summary="Stock could not be resolved.")}, data_quality=quality, seo_eligibility=self._build_seo(canonical_path, quality, "Stock could not be resolved"))
        live = self.stocks.get_stock_live(stock.symbol or symbol) or {}
        fno = live.get("fno") or {}
        net_gamma = fno.get("net_gamma")
        total_gamma = fno.get("total_gamma")
        available = ["identity"] + (["gamma"] if net_gamma is not None or total_gamma is not None else [])
        missing = [] if len(available) > 1 else ["gamma"]
        quality = self._build_quality(available=available, missing=missing, last_updated=(live.get("latest_price") or {}).get("date"), warnings=[] if len(available) > 1 else ["Gamma snapshot is not available for this symbol"])
        return LandingResponse(
            canonical_path=f"/stocks/{stock.slug}/gamma-exposure",
            entity=LandingEntity(stock=stock),
            sections={"gamma_exposure": LandingSectionStatus(status="available" if len(available) > 1 else "missing", summary="Latest gamma snapshot from the options positioning data.", payload={"spot_price": fno.get("spot_price"), "net_gamma": net_gamma, "total_gamma": total_gamma, "top_call_oi": fno.get("top_call_oi") or [], "top_put_oi": fno.get("top_put_oi") or []})},
            related_links=[RelatedLink(label="F&O positioning", path=f"/stocks/{stock.slug}/fno-positioning"), RelatedLink(label="OI analysis", path=f"/stocks/{stock.slug}/oi-analysis"), RelatedLink(label="PCR", path=f"/stocks/{stock.slug}/put-call-ratio")],
            faq=[{"q": "What gamma values are shown here?", "a": "This page uses the latest available net-gamma and total-gamma values from the options snapshot when those fields are present."}],
            schema_payload={"page_type": "stock_gamma_exposure", "stock_slug": stock.slug},
            data_quality=quality,
            seo_eligibility=self._build_seo(f"/stocks/{stock.slug}/gamma-exposure", quality, "Gamma snapshot available" if len(available) > 1 else "No gamma snapshot available"),
        )

    def get_stock_events(self, symbol: str) -> LandingResponse:
        logger.info("landing stock-events requested symbol=%s", symbol)
        stock = self._resolve_stock(symbol)
        canonical_path = f"/stocks/{symbol.lower()}/events"
        if not stock:
            quality = self._build_quality(available=[], missing=["identity", "events"], last_updated=None, warnings=["Stock could not be resolved"])
            return LandingResponse(canonical_path=canonical_path, sections={"events": LandingSectionStatus(status="missing", summary="Stock could not be resolved.")}, data_quality=quality, seo_eligibility=self._build_seo(canonical_path, quality, "Stock could not be resolved"))
        symbol_filters = {"symbol": stock.symbol, "ticker": stock.symbol}
        actions = self._query_rows("nse_corporate_actions", filters={"symbol": stock.symbol}, order_by="ex_date", limit=20)
        news = self.compare._fetch_news(stock)
        available = ["identity"]
        if actions:
            available.append("corporate_actions")
        if news.get("items"):
            available.append("news")
        missing = [name for name in ("corporate_actions", "news") if name not in available]
        quality = self._build_quality(available=available, missing=missing, last_updated=(actions[0].get("ex_date") if actions else None), warnings=[] if actions or news.get("items") else ["No current event rows were found for this symbol"])
        return LandingResponse(
            canonical_path=f"/stocks/{stock.slug}/events",
            entity=LandingEntity(stock=stock),
            sections={"events": LandingSectionStatus(status="available" if actions or news.get("items") else "missing", summary="Corporate actions and recent news context for the stock.", payload={"corporate_actions": actions, "recent_news": (news.get("items") or [])[:10]})},
            related_links=[RelatedLink(label="Corporate actions", path=f"/stocks/{stock.slug}/corporate-actions"), RelatedLink(label="Overview", path=stock.canonical_path)],
            faq=[{"q": f"What events are included for {stock.company_name}?", "a": "This page includes recent corporate-action rows and current related news mentions when available."}],
            schema_payload={"page_type": "stock_events", "stock_slug": stock.slug},
            data_quality=quality,
            seo_eligibility=self._build_seo(f"/stocks/{stock.slug}/events", quality, "Event coverage available" if actions or news.get("items") else "No event coverage available"),
        )

    def get_stock_bulk_block_deals(self, symbol: str) -> LandingResponse:
        logger.info("landing bulk-block-deals requested symbol=%s", symbol)
        stock = self._resolve_stock(symbol)
        canonical_path = f"/stocks/{symbol.lower()}/bulk-block-deals"
        if not stock:
            quality = self._build_quality(available=[], missing=["identity", "deals"], last_updated=None, warnings=["Stock could not be resolved"])
            return LandingResponse(canonical_path=canonical_path, sections={"deals": LandingSectionStatus(status="missing", summary="Stock could not be resolved.")}, data_quality=quality, seo_eligibility=self._build_seo(canonical_path, quality, "Stock could not be resolved"))
        bulk = self._query_rows("nse_bulk_deals", filters={"symbol": stock.symbol}, order_by="trade_date", limit=20)
        block = self._query_rows("nse_block_deals", filters={"symbol": stock.symbol}, order_by="trade_date", limit=20)
        available = ["identity"] + (["deals"] if bulk or block else [])
        missing = [] if bulk or block else ["deals"]
        quality = self._build_quality(available=available, missing=missing, last_updated=(bulk[0].get("trade_date") if bulk else (block[0].get("trade_date") if block else None)), warnings=[] if bulk or block else ["No recent bulk or block deals were found"])
        return LandingResponse(
            canonical_path=f"/stocks/{stock.slug}/bulk-block-deals",
            entity=LandingEntity(stock=stock),
            sections={"deals": LandingSectionStatus(status="available" if bulk or block else "missing", summary="Recent bulk and block deals for the stock.", payload={"bulk_deals": bulk, "block_deals": block})},
            related_links=[RelatedLink(label="Corporate actions", path=f"/stocks/{stock.slug}/corporate-actions"), RelatedLink(label="Events", path=f"/stocks/{stock.slug}/events")],
            faq=[{"q": "How recent are the deals shown here?", "a": "This page lists the latest available bulk-deal and block-deal rows for the stock."}],
            schema_payload={"page_type": "stock_bulk_block_deals", "stock_slug": stock.slug},
            data_quality=quality,
            seo_eligibility=self._build_seo(f"/stocks/{stock.slug}/bulk-block-deals", quality, "Recent deals available" if bulk or block else "No recent deals available"),
        )

    def get_stock_corporate_actions(self, symbol: str) -> LandingResponse:
        logger.info("landing corporate-actions requested symbol=%s", symbol)
        stock = self._resolve_stock(symbol)
        canonical_path = f"/stocks/{symbol.lower()}/corporate-actions"
        if not stock:
            quality = self._build_quality(available=[], missing=["identity", "corporate_actions"], last_updated=None, warnings=["Stock could not be resolved"])
            return LandingResponse(canonical_path=canonical_path, sections={"corporate_actions": LandingSectionStatus(status="missing", summary="Stock could not be resolved.")}, data_quality=quality, seo_eligibility=self._build_seo(canonical_path, quality, "Stock could not be resolved"))
        actions = self._query_rows("nse_corporate_actions", filters={"symbol": stock.symbol}, order_by="ex_date", limit=40)
        available = ["identity"] + (["corporate_actions"] if actions else [])
        missing = [] if actions else ["corporate_actions"]
        quality = self._build_quality(available=available, missing=missing, last_updated=(actions[0].get("ex_date") if actions else None), warnings=[] if actions else ["No corporate-action rows were found"])
        return LandingResponse(
            canonical_path=f"/stocks/{stock.slug}/corporate-actions",
            entity=LandingEntity(stock=stock),
            sections={"corporate_actions": LandingSectionStatus(status="available" if actions else "missing", summary="Corporate-action rows such as dividends, splits, bonus issues, or rights.", payload={"actions": actions})},
            related_links=[RelatedLink(label="Events", path=f"/stocks/{stock.slug}/events"), RelatedLink(label="Overview", path=stock.canonical_path)],
            faq=[{"q": "What corporate actions are shown?", "a": "This page uses the latest available NSE corporate-action rows for the stock."}],
            schema_payload={"page_type": "stock_corporate_actions", "stock_slug": stock.slug},
            data_quality=quality,
            seo_eligibility=self._build_seo(f"/stocks/{stock.slug}/corporate-actions", quality, "Corporate actions available" if actions else "No corporate actions available"),
        )

    def get_sector_fno_positioning(self, slug: str) -> LandingResponse:
        logger.info("landing sector-fno requested slug=%s", slug)
        sector = self.get_sector_overview(slug)
        sector_entity = sector.entity.sector or {}
        sector_name = sector_entity.get("name")
        stocks = ((sector.sections.get("sector") or LandingSectionStatus()).payload or {}).get("stocks", [])
        fno_candidates = []
        for row in stocks[:25]:
            live = self.stocks.get_stock_live(row.get("symbol")) or {}
            if live.get("fno"):
                fno_candidates.append({"symbol": row.get("symbol"), "company_name": row.get("company_name"), **(live.get("fno") or {})})
        available = ["sector_identity"] + (["fno"] if fno_candidates else [])
        missing = [] if fno_candidates else ["fno"]
        quality = self._build_quality(available=available, missing=missing, last_updated=None, warnings=[] if fno_candidates else ["No sector-level F&O snapshots were found"])
        return LandingResponse(
            canonical_path=f"/sector/{slug}/fno-positioning",
            entity=LandingEntity(sector={"name": sector_name, "slug": slug, "stock_count": len(stocks)}),
            sections={"sector_fno_positioning": LandingSectionStatus(status="available" if fno_candidates else "missing", summary="Current F&O snapshots for stocks in the sector.", payload={"stocks": fno_candidates[:15]})},
            related_links=[RelatedLink(label="Sector overview", path=f"/sector/{slug}")] + [RelatedLink(label=row.get("symbol"), path=f"/stocks/{row.get('slug')}/fno-positioning") for row in stocks[:8]],
            faq=[{"q": f"What does sector F&O positioning show for {sector_name or slug}?", "a": "It shows the latest available per-stock options snapshots for names in the sector."}],
            schema_payload={"page_type": "sector_fno_positioning", "sector_slug": slug},
            data_quality=quality,
            seo_eligibility=self._build_seo(f"/sector/{slug}/fno-positioning", quality, "Sector F&O coverage available" if fno_candidates else "No sector F&O coverage available"),
        )

    def get_sector_risk_signals(self, slug: str) -> LandingResponse:
        logger.info("landing sector-risk requested slug=%s", slug)
        sector = self.get_sector_overview(slug)
        sector_entity = sector.entity.sector or {}
        sector_name = sector_entity.get("name")
        if not sector_name:
            return sector
        metrics_rows = self._query_rows("stock_daily_metrics", filters={"sector": sector_name}, order_by="trade_date", limit=20)
        signal_rows = self._query_rows("nexus_signal_instances", filters={"sector": sector_name}, order_by="event_time", limit=20)
        anomaly_rows = self._query_rows("nexus_anomaly_scores", filters={"sector": sector_name}, order_by="computed_at", limit=20)
        available = ["sector_identity"]
        if metrics_rows:
            available.append("metrics")
        if signal_rows or anomaly_rows:
            available.append("signals")
        missing = [name for name in ("metrics", "signals") if name not in available]
        quality = self._build_quality(available=available, missing=missing, last_updated=(metrics_rows[0].get("trade_date") if metrics_rows else None), warnings=[] if metrics_rows or signal_rows or anomaly_rows else ["No sector risk rows were found"])
        return LandingResponse(
            canonical_path=f"/sector/{slug}/risk-signals",
            entity=LandingEntity(sector={"name": sector_name, "slug": slug}),
            sections={"sector_risk_signals": LandingSectionStatus(status="available" if metrics_rows or signal_rows or anomaly_rows else "missing", summary="Sector-level volatility, anomaly, and signal context.", payload={"daily_metrics": metrics_rows, "signal_instances": signal_rows, "anomaly_scores": anomaly_rows})},
            related_links=[RelatedLink(label="Sector overview", path=f"/sector/{slug}")],
            faq=[{"q": "What sector risk signals are shown?", "a": "This page combines recent sector metrics with current signal and anomaly rows when available."}],
            schema_payload={"page_type": "sector_risk_signals", "sector_slug": slug},
            data_quality=quality,
            seo_eligibility=self._build_seo(f"/sector/{slug}/risk-signals", quality, "Sector risk coverage available" if metrics_rows or signal_rows or anomaly_rows else "No sector risk coverage available"),
        )

    def get_market_flow_fii_dii(self) -> LandingResponse:
        logger.info("landing market-flow fii-dii requested")
        fii = self._query_rows("fii_activity", order_by="trade_date", limit=20)
        dii = self._query_rows("dii_activity", order_by="trade_date", limit=20)
        cash = self._query_rows("category_turnover_cash", order_by="trade_date", limit=20)
        fo = self._query_rows("category_turnover_fo", order_by="trade_date", limit=20)
        available = []
        if fii or dii:
            available.append("flows")
        if cash:
            available.append("cash_turnover")
        if fo:
            available.append("fo_turnover")
        missing = [name for name in ("flows", "cash_turnover", "fo_turnover") if name not in available]
        quality = self._build_quality(available=available, missing=missing, last_updated=(fii[0].get("trade_date") if fii else (dii[0].get("trade_date") if dii else None)), warnings=[] if available else ["No FII or DII flow rows were found"])
        return LandingResponse(
            canonical_path="/fii-dii",
            sections={"market_flow": LandingSectionStatus(status="available" if available else "missing", summary="Latest FII and DII flow context across cash and derivatives.", payload={"fii_activity": fii, "dii_activity": dii, "category_turnover_cash": cash, "category_turnover_fo": fo})},
            related_links=[RelatedLink(label="FII activity", path="/fii-activity"), RelatedLink(label="DII activity", path="/dii-activity"), RelatedLink(label="Market breadth", path="/market-breadth")],
            faq=[{"q": "What does the FII/DII page include?", "a": "It includes the latest available FII and DII rows plus cash and derivatives turnover context when present."}],
            schema_payload={"page_type": "fii_dii"},
            data_quality=quality,
            seo_eligibility=self._build_seo("/fii-dii", quality, "FII/DII flow coverage available" if available else "No FII/DII flow coverage available"),
        )

    def get_participant_oi(self) -> LandingResponse:
        logger.info("landing participant-oi requested")
        oi_rows = self._query_rows("participant_oi", order_by="trade_date", limit=40)
        volume_rows = self._query_rows("participant_volume", order_by="trade_date", limit=40)
        fii_derivatives = self._query_rows("fii_derivatives_stats", order_by="trade_date", limit=40)
        available = []
        if oi_rows:
            available.append("participant_oi")
        if volume_rows:
            available.append("participant_volume")
        if fii_derivatives:
            available.append("fii_derivatives")
        missing = [name for name in ("participant_oi", "participant_volume", "fii_derivatives") if name not in available]
        quality = self._build_quality(available=available, missing=missing, last_updated=(oi_rows[0].get("trade_date") if oi_rows else None), warnings=[] if available else ["No participant OI rows were found"])
        return LandingResponse(
            canonical_path="/participant-oi",
            sections={"participant_oi": LandingSectionStatus(status="available" if available else "missing", summary="Participant open-interest, volume, and derivatives stats.", payload={"participant_oi": oi_rows, "participant_volume": volume_rows, "fii_derivatives_stats": fii_derivatives})},
            related_links=[RelatedLink(label="FII/DII", path="/fii-dii"), RelatedLink(label="Market breadth", path="/market-breadth")],
            faq=[{"q": "What participant categories are shown?", "a": "This page returns the latest available participant OI, volume, and FII derivatives rows from the current dataset."}],
            schema_payload={"page_type": "participant_oi"},
            data_quality=quality,
            seo_eligibility=self._build_seo("/participant-oi", quality, "Participant OI coverage available" if available else "No participant OI coverage available"),
        )

    def get_market_breadth(self) -> LandingResponse:
        logger.info("landing market-breadth requested")
        daily = self._query_rows("market_intelligence_daily", order_by="date", limit=20)
        context = self._query_rows("market_daily_context", order_by="trade_date", limit=20)
        available = []
        if daily:
            available.append("market_intelligence")
        if context:
            available.append("daily_context")
        missing = [name for name in ("market_intelligence", "daily_context") if name not in available]
        quality = self._build_quality(available=available, missing=missing, last_updated=(daily[0].get("date") if daily else (context[0].get("trade_date") if context else None)), warnings=[] if available else ["No market breadth rows were found"])
        return LandingResponse(
            canonical_path="/market-breadth",
            sections={"market_breadth": LandingSectionStatus(status="available" if available else "missing", summary="Advance-decline, regime, and risk-on or risk-off context.", payload={"market_intelligence_daily": daily, "market_daily_context": context})},
            related_links=[RelatedLink(label="Sector rotation", path="/sector-rotation"), RelatedLink(label="FII/DII", path="/fii-dii")],
            faq=[{"q": "What does market breadth show?", "a": "It shows the latest available advance-decline, index, volatility, and regime context from the daily market tables."}],
            schema_payload={"page_type": "market_breadth"},
            data_quality=quality,
            seo_eligibility=self._build_seo("/market-breadth", quality, "Market breadth coverage available" if available else "No market breadth coverage available"),
        )

    def get_sector_rotation(self) -> LandingResponse:
        logger.info("landing sector-rotation requested")
        daily = self._query_rows("market_intelligence_daily", order_by="date", limit=10)
        index_perf = self._query_rows("nse_index_performances", order_by="snapshot_date", limit=30)
        stock_metrics = self._query_rows("stock_daily_metrics", order_by="trade_date", limit=40)
        available = []
        if daily:
            available.append("market_intelligence")
        if index_perf:
            available.append("index_performance")
        if stock_metrics:
            available.append("stock_metrics")
        missing = [name for name in ("market_intelligence", "index_performance", "stock_metrics") if name not in available]
        quality = self._build_quality(available=available, missing=missing, last_updated=(daily[0].get("date") if daily else None), warnings=[] if available else ["No sector rotation rows were found"])
        return LandingResponse(
            canonical_path="/sector-rotation",
            sections={"sector_rotation": LandingSectionStatus(status="available" if available else "missing", summary="Leading and lagging sector context from current market tables.", payload={"market_intelligence_daily": daily, "index_performances": index_perf, "stock_daily_metrics": stock_metrics})},
            related_links=[RelatedLink(label="Market breadth", path="/market-breadth"), RelatedLink(label="Sector hub", path="/sector/financial-services")],
            faq=[{"q": "How is sector rotation shown?", "a": "This page combines recent sector-strength rows, index performance, and stock-level sector metrics when present."}],
            schema_payload={"page_type": "sector_rotation"},
            data_quality=quality,
            seo_eligibility=self._build_seo("/sector-rotation", quality, "Sector rotation coverage available" if available else "No sector rotation coverage available"),
        )

    def get_event_impact(self, slug: str) -> LandingResponse:
        logger.info("landing event-impact requested slug=%s", slug)
        articles = self._query_rows("market_news", order_by="published_at", limit=50)
        matched = [row for row in articles if slug in self._news_slug(str(row.get("title") or ""))]
        article = matched[0] if matched else None
        if not article:
            quality = self._build_quality(available=[], missing=["event", "entities"], last_updated=None, warnings=["Event slug could not be matched"])
            return LandingResponse(canonical_path=f"/events/{slug}", sections={"event": LandingSectionStatus(status="missing", summary="Event slug could not be matched.")}, data_quality=quality, seo_eligibility=self._build_seo(f"/events/{slug}", quality, "Event slug could not be matched"))
        article_id = article.get("id")
        mentions = self._query_rows("article_entity_mentions", filters={"article_id": article_id}, order_by=None, limit=50)
        extractions = self._query_rows("news_extraction", filters={"news_id": article_id}, order_by="completed_at", limit=10)
        listed_symbols = [row.get("nse_symbol") for row in mentions if row.get("nse_symbol")]
        available = ["event"]
        if mentions:
            available.append("mentions")
        if extractions:
            available.append("extraction")
        missing = [name for name in ("mentions", "extraction") if name not in available]
        quality = self._build_quality(available=available, missing=missing, last_updated=article.get("published_at"), warnings=[] if mentions else ["No entity mentions were found for this event"])
        return LandingResponse(
            canonical_path=f"/events/{slug}",
            sections={"event": LandingSectionStatus(status="available", summary="Resolved event article with current mention coverage.", payload={"article": article, "mentions": mentions, "extractions": extractions, "listed_symbols": listed_symbols})},
            related_links=[RelatedLink(label=str(sym), path=f"/stocks/{str(sym).lower()}") for sym in listed_symbols[:8]],
            faq=[{"q": "How are affected stocks linked to this event?", "a": "Affected stocks come from the current article-entity mention rows tied to the matched event article."}],
            schema_payload={"page_type": "event_impact", "event_slug": slug},
            data_quality=quality,
            seo_eligibility=self._build_seo(f"/events/{slug}", quality, "Event page has mention coverage" if mentions else "Event page is thin"),
        )

    def get_affected_stocks(self, slug: str) -> LandingResponse:
        event = self.get_event_impact(slug)
        payload = ((event.sections.get("event") or LandingSectionStatus()).payload or {})
        mentions = payload.get("mentions") or []
        quality = event.data_quality
        return LandingResponse(
            canonical_path=f"/stocks-affected/{slug}",
            sections={"affected_stocks": LandingSectionStatus(status="available" if mentions else "missing", summary="Stocks linked to the matched event article.", payload={"article": payload.get("article"), "mentions": mentions})},
            related_links=event.related_links,
            faq=[{"q": "Why is a stock listed on this page?", "a": "A stock appears here only when it is linked through the current article-entity mentions for the matched event."}],
            schema_payload={"page_type": "affected_stocks", "event_slug": slug},
            data_quality=quality,
            seo_eligibility=self._build_seo(f"/stocks-affected/{slug}", quality, "Affected-stock coverage available" if mentions else "No affected-stock coverage available"),
        )

    def get_ipo_hub(self) -> LandingResponse:
        logger.info("landing ipo-hub requested")
        details = self._query_rows("ipo_details", order_by="bidding_start_date", limit=50)
        listings = self._query_rows("ipo_listings", order_by="listing_date", limit=30)
        available = []
        if details:
            available.append("ipo_details")
        if listings:
            available.append("ipo_listings")
        missing = [name for name in ("ipo_details", "ipo_listings") if name not in available]
        quality = self._build_quality(available=available, missing=missing, last_updated=(details[0].get("bidding_start_date") if details else None), warnings=[] if available else ["No IPO rows were found"])
        return LandingResponse(
            canonical_path="/ipos",
            sections={"ipos": LandingSectionStatus(status="available" if available else "missing", summary="Open, upcoming, and recently listed IPO rows.", payload={"ipo_details": details, "ipo_listings": listings})},
            related_links=[RelatedLink(label=str(row.get("symbol") or row.get("name")), path=f"/ipos/{str(row.get('symbol') or '').lower()}") for row in details[:8] if row.get("symbol")],
            faq=[{"q": "What IPO data is shown?", "a": "This page shows the latest available IPO detail and listing rows from the current database snapshot."}],
            schema_payload={"page_type": "ipo_hub"},
            data_quality=quality,
            seo_eligibility=self._build_seo("/ipos", quality, "IPO coverage available" if available else "No IPO coverage available"),
        )

    def get_ipo_detail(self, symbol: str) -> LandingResponse:
        logger.info("landing ipo-detail requested symbol=%s", symbol)
        details = self._query_rows("ipo_details", filters={"symbol": symbol.upper()}, order_by="bidding_start_date", limit=5)
        listings = self._query_rows("ipo_listings", filters={"symbol": symbol.upper()}, order_by="listing_date", limit=5)
        available = []
        if details:
            available.append("ipo_details")
        if listings:
            available.append("ipo_listings")
        missing = [name for name in ("ipo_details", "ipo_listings") if name not in available]
        quality = self._build_quality(available=available, missing=missing, last_updated=(details[0].get("bidding_start_date") if details else None), warnings=[] if available else ["IPO symbol could not be matched"])
        return LandingResponse(
            canonical_path=f"/ipos/{symbol.lower()}",
            sections={"ipo": LandingSectionStatus(status="available" if available else "missing", summary="IPO detail and listing rows for the matched symbol.", payload={"ipo_details": details, "ipo_listings": listings})},
            related_links=[RelatedLink(label="IPO hub", path="/ipos")],
            faq=[{"q": "What fields are included in the IPO page?", "a": "The IPO detail page returns the current issue, price-band, date, listing, and document-link fields when available."}],
            schema_payload={"page_type": "ipo_detail", "ipo_symbol": symbol.lower()},
            data_quality=quality,
            seo_eligibility=self._build_seo(f"/ipos/{symbol.lower()}", quality, "IPO detail coverage available" if available else "No IPO detail coverage available"),
        )

    def get_signal_catalog(self) -> LandingResponse:
        logger.info("landing signals requested")
        catalog = self._query_rows("signal_catalog", order_by=None, limit=100)
        recent = self._query_rows("scanner_signals", order_by="signal_date", limit=30)
        available = []
        if catalog:
            available.append("catalog")
        if recent:
            available.append("recent_examples")
        missing = [name for name in ("catalog", "recent_examples") if name not in available]
        quality = self._build_quality(available=available, missing=missing, last_updated=(recent[0].get("signal_date") if recent else None), warnings=[] if available else ["No signal-catalog rows were found"])
        return LandingResponse(
            canonical_path="/signals",
            sections={"signals": LandingSectionStatus(status="available" if available else "missing", summary="Signal catalog and recent scanner examples.", payload={"signal_catalog": catalog, "recent_signals": recent})},
            related_links=[RelatedLink(label=str(row.get("signal_code")), path=f"/signals/{str(row.get('signal_code')).lower()}") for row in catalog[:12] if row.get("signal_code")],
            faq=[{"q": "What is included in the signal catalog?", "a": "The catalog includes enabled signal definitions and recent scanner-signal examples when those rows are available."}],
            schema_payload={"page_type": "signal_catalog"},
            data_quality=quality,
            seo_eligibility=self._build_seo("/signals", quality, "Signal catalog coverage available" if available else "No signal catalog coverage available"),
        )

    def get_signal_detail(self, signal_code: str) -> LandingResponse:
        logger.info("landing signal-detail requested signal_code=%s", signal_code)
        catalog = self._query_rows("signal_catalog", filters={"signal_code": signal_code.upper()}, order_by=None, limit=5)
        recent = self._query_rows("scanner_signals", filters={"signal_code": signal_code.upper()}, order_by="signal_date", limit=30)
        available = []
        if catalog:
            available.append("catalog")
        if recent:
            available.append("recent_examples")
        missing = [name for name in ("catalog", "recent_examples") if name not in available]
        quality = self._build_quality(available=available, missing=missing, last_updated=(recent[0].get("signal_date") if recent else None), warnings=[] if available else ["Signal code could not be matched"])
        return LandingResponse(
            canonical_path=f"/signals/{signal_code.lower()}",
            sections={"signal": LandingSectionStatus(status="available" if available else "missing", summary="Signal definition and recent scanner examples.", payload={"signal_catalog": catalog, "recent_signals": recent})},
            related_links=[RelatedLink(label="Signal catalog", path="/signals")],
            faq=[{"q": "What does this signal page show?", "a": "It shows the catalog entry for the signal code plus recent scanner-signal rows when present."}],
            schema_payload={"page_type": "signal_detail", "signal_code": signal_code.lower()},
            data_quality=quality,
            seo_eligibility=self._build_seo(f"/signals/{signal_code.lower()}", quality, "Signal detail coverage available" if available else "No signal detail coverage available"),
        )

    def get_nexus_signal_detail(self, signal_code: str) -> LandingResponse:
        logger.info("landing nexus-signal requested signal_code=%s", signal_code)
        catalog = self._query_rows("nexus_signal_catalog", filters={"signal_code": signal_code.upper()}, order_by=None, limit=5)
        instances = self._query_rows("nexus_signal_instances", filters={"signal_code": signal_code.upper()}, order_by="event_time", limit=30)
        accuracy = self._query_rows("nexus_signal_accuracy", filters={"signal_type": signal_code.upper()}, order_by="window_end", limit=10)
        available = []
        if catalog:
            available.append("catalog")
        if instances:
            available.append("instances")
        if accuracy:
            available.append("accuracy")
        missing = [name for name in ("catalog", "instances", "accuracy") if name not in available]
        quality = self._build_quality(available=available, missing=missing, last_updated=(instances[0].get("event_time") if instances else None), warnings=[] if available else ["Nexus signal code could not be matched"])
        return LandingResponse(
            canonical_path=f"/nexus-signals/{signal_code.lower()}",
            sections={"nexus_signal": LandingSectionStatus(status="available" if available else "missing", summary="Nexus signal definition, recent instances, and accuracy context.", payload={"nexus_signal_catalog": catalog, "recent_instances": instances, "accuracy": accuracy})},
            related_links=[RelatedLink(label="Signals", path="/signals")],
            faq=[{"q": "What does the Nexus signal page include?", "a": "It includes the latest available catalog row, recent instances, and accuracy rows for the matched Nexus signal code."}],
            schema_payload={"page_type": "nexus_signal_detail", "signal_code": signal_code.lower()},
            data_quality=quality,
            seo_eligibility=self._build_seo(f"/nexus-signals/{signal_code.lower()}", quality, "Nexus signal coverage available" if available else "No Nexus signal coverage available"),
        )

    def get_stock_insider_trading(self, symbol: str) -> list[dict[str, Any]]:
        logger.info("landing insider-trading requested symbol=%s", symbol)
        rows = self.db.execute(
            text("SELECT * FROM stock_insider_trades WHERE symbol = :sym ORDER BY filing_date DESC NULLS LAST"),
            {"sym": f"{symbol}.NS"},
        ).fetchall()
        return [dict(row._mapping) for row in rows]
