from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from statistics import median
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


NEUTRAL_ANALYSIS_KEYS = {
    "executive_summary", "bull_case", "bear_case", "opportunities", "red_flags",
    "business_quality_analysis", "growth_analysis", "financial_strength_analysis",
    "valuation_analysis", "price_context", "overall_assessment", "confidence_score",
}


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _rows(result) -> list[dict[str, Any]]:
    return [{key: _json_value(value) for key, value in row._mapping.items()} for row in result]


def _rsi_14(closes: list[float]) -> float | None:
    if len(closes) < 15:
        return None
    changes = [current - previous for previous, current in zip(closes, closes[1:])]
    gains = [max(change, 0.0) for change in changes]
    losses = [max(-change, 0.0) for change in changes]
    average_gain = sum(gains[:14]) / 14
    average_loss = sum(losses[:14]) / 14
    for gain, loss in zip(gains[14:], losses[14:]):
        average_gain = (average_gain * 13 + gain) / 14
        average_loss = (average_loss * 13 + loss) / 14
    if average_loss == 0:
        return 100.0 if average_gain > 0 else 50.0
    relative_strength = average_gain / average_loss
    return 100 - (100 / (1 + relative_strength))


def _return_since(prices: list[tuple[date, float]], days: int) -> float | None:
    if len(prices) < 2:
        return None
    latest_date, latest_close = prices[-1]
    target = latest_date - timedelta(days=days)
    reference = next((close for price_date, close in reversed(prices) if price_date <= target), None)
    if reference in (None, 0):
        return None
    return (latest_close / reference - 1) * 100


class StockWorkspaceService:
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def ticker(symbol: str) -> str:
        clean = symbol.strip().upper().removesuffix(".NS")
        return f"{clean}.NS"

    def identity(self, symbol: str) -> dict[str, Any] | None:
        ticker = self.ticker(symbol)
        row = self.db.execute(text("""
            SELECT symbol, ticker, company_name, sector, industry, market_cap,
                   trailing_pe, forward_pe, price_to_book, dividend_yield,
                   roe, roa, profit_margins, revenue_growth, earnings_growth,
                   eps, forward_eps, description, fetched_at
            FROM stock_info
            WHERE ticker = :ticker OR symbol = :symbol
            ORDER BY fetched_at DESC NULLS LAST
            LIMIT 1
        """), {"ticker": ticker, "symbol": ticker.removesuffix(".NS")}).mappings().first()
        if not row:
            return None
        payload = {key: _json_value(value) for key, value in row.items()}
        payload["symbol"] = (payload.get("symbol") or ticker).upper().removesuffix(".NS")
        payload["ticker"] = ticker
        return payload

    def dashboard(self) -> dict[str, Any]:
        latest_rank_date = self.db.execute(text("SELECT max(report_date) FROM nse_top_gainers_losers")).scalar()
        latest_high_low_date = self.db.execute(text("SELECT max(report_date) FROM nse_52_week_high_low")).scalar()
        latest_index_date = self.db.execute(text("SELECT max(snapshot_date) FROM nse_index_performances")).scalar()
        summary = self.db.execute(text("""
            SELECT
              (SELECT count(DISTINCT ticker) FROM stock_info) AS tracked_stocks,
              (SELECT count(DISTINCT symbol) FROM nse_fno_list) AS fno_stocks,
              (SELECT max(date) FROM stock_prices) AS prices_as_of,
              (SELECT max(published_at) FROM market_news) AS news_as_of
        """)).mappings().one()
        gainers = _rows(self.db.execute(text("""
            SELECT symbol, ltp, change_pct, report_date
            FROM nse_top_gainers_losers
            WHERE report_date = :d AND lower(category) = 'gainers'
            ORDER BY change_pct DESC NULLS LAST LIMIT 12
        """), {"d": latest_rank_date}))
        losers = _rows(self.db.execute(text("""
            SELECT symbol, ltp, change_pct, report_date
            FROM nse_top_gainers_losers
            WHERE report_date = :d AND lower(category) = 'losers'
            ORDER BY change_pct ASC NULLS LAST LIMIT 12
        """), {"d": latest_rank_date}))
        high_low = _rows(self.db.execute(text("""
            SELECT symbol, adj_52_week_high AS year_high, adj_52_week_low AS year_low,
                   report_date
            FROM nse_52_week_high_low WHERE report_date = :d
            ORDER BY symbol LIMIT 16
        """), {"d": latest_high_low_date}))
        indices = _rows(self.db.execute(text("""
            SELECT index_name, last_value, percent_change, advances, declines,
                   year_high, year_low, snapshot_date
            FROM nse_index_performances WHERE snapshot_date = :d
            ORDER BY index_name LIMIT 12
        """), {"d": latest_index_date}))
        news = _rows(self.db.execute(text("""
            SELECT id, title, link, source_name, published_at, category
            FROM market_news ORDER BY published_at DESC NULLS LAST LIMIT 10
        """)))
        volume_jumps = _rows(self.db.execute(text("""
            WITH recent AS (
              SELECT ticker, date, close, volume,
                     row_number() OVER (PARTITION BY ticker ORDER BY date DESC) AS rn,
                     avg(volume) OVER (
                       PARTITION BY ticker ORDER BY date
                       ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
                     ) AS average_volume_20
              FROM stock_prices
              WHERE date >= (SELECT max(date) FROM stock_prices) - INTERVAL '45 days'
            )
            SELECT replace(r.ticker,'.NS','') AS symbol, i.company_name, i.sector,
                   r.close, r.volume, r.average_volume_20,
                   r.volume / NULLIF(r.average_volume_20,0) AS volume_ratio
            FROM recent r
            LEFT JOIN stock_info i ON i.ticker=r.ticker
            WHERE r.rn=1 AND r.average_volume_20>0 AND r.volume>r.average_volume_20
            ORDER BY volume_ratio DESC NULLS LAST LIMIT 15
        """)))
        iv_spikes = _rows(self.db.execute(text("""
            SELECT instrument_key, price_current, price_change_pct,
                   metric_current AS iv, metric_previous AS previous_iv,
                   metric_change_pct AS iv_change_pct, snapshot_time
            FROM smartlist_options
            WHERE snapshot_date=(SELECT max(snapshot_date) FROM smartlist_options)
              AND category='IV_GAINERS'
            ORDER BY metric_change_pct DESC NULLS LAST LIMIT 15
        """)))
        sectors = _rows(self.db.execute(text("""
            SELECT index_name, percent_change, last_value, advances, declines, snapshot_date
            FROM nse_index_performances
            WHERE snapshot_date=:d
              AND (
                upper(index_name) LIKE 'NIFTY % INDEX'
                OR upper(index_name) ~ 'NIFTY (AUTO|BANK|ENERGY|FMCG|IT|MEDIA|METAL|PHARMA|PSU BANK|REALTY|HEALTHCARE|CONSUMER DURABLES|FINANCIAL SERVICES|OIL AND GAS)'
              )
            ORDER BY index_name LIMIT 30
        """), {"d": latest_index_date}))
        heatmap = _rows(self.db.execute(text("""
            SELECT m.symbol, coalesce(i.company_name,m.symbol) AS company_name,
                   coalesce(i.sector,'Unclassified') AS sector,
                   m.ltp, m.change_pct,
                   coalesce(i.market_cap, abs(m.change_pct) * 10000000) / 10000000.0 AS market_cap_cr
            FROM nse_top_gainers_losers m
            LEFT JOIN stock_info i ON i.symbol=m.symbol
            WHERE m.report_date=:d
            ORDER BY coalesce(i.market_cap,0) DESC NULLS LAST LIMIT 100
        """), {"d": latest_rank_date}))
        return {
            "as_of": _json_value(latest_rank_date),
            "summary": {key: _json_value(value) for key, value in summary.items()},
            "top_gainers": gainers,
            "top_losers": losers,
            "fifty_two_week": high_low,
            "indices": indices,
            "recent_news": news,
            "volume_jumps": volume_jumps,
            "iv_spikes": iv_spikes,
            "sector_performance": sectors,
            "market_heatmap": heatmap,
        }

    def chart(self, symbol: str, from_ts: int | None, to_ts: int | None, limit: int) -> dict[str, Any]:
        identity = self.identity(symbol)
        if not identity:
            return {"symbol": symbol.upper(), "bars": [], "status": "missing"}
        clauses = ["upper(ticker) = :ticker"]
        params: dict[str, Any] = {"ticker": self.ticker(symbol), "limit": limit}
        if from_ts is not None:
            clauses.append("date >= to_timestamp(:from_ts)::date")
            params["from_ts"] = from_ts
        if to_ts is not None:
            clauses.append("date <= to_timestamp(:to_ts)::date")
            params["to_ts"] = to_ts
        bars = _rows(self.db.execute(text(f"""
            SELECT date, open, high, low, close, volume
            FROM stock_prices WHERE {' AND '.join(clauses)}
            ORDER BY date ASC LIMIT :limit
        """), params))
        return {"symbol": identity["symbol"], "status": "available" if bars else "missing", "bars": bars}

    def workspace(self, symbol: str) -> dict[str, Any] | None:
        identity = self.identity(symbol)
        if not identity:
            return None
        sym, ticker = identity["symbol"], identity["ticker"]
        availability = self.db.execute(text("""
            SELECT
              EXISTS(SELECT 1 FROM stock_prices WHERE ticker=:ticker LIMIT 1) prices,
              EXISTS(SELECT 1 FROM stock_financials WHERE ticker=:ticker LIMIT 1) financials,
              (EXISTS(SELECT 1 FROM stock_holders WHERE ticker=:ticker LIMIT 1) OR
               EXISTS(SELECT 1 FROM stock_insider_transactions WHERE ticker=:ticker LIMIT 1)) ownership,
              EXISTS(SELECT 1 FROM market_news
                     WHERE title ILIKE :mention OR description ILIKE :mention
                        OR title ILIKE :company OR description ILIKE :company LIMIT 1) news,
              EXISTS(SELECT 1 FROM option_chain_snapshots WHERE underlying_symbol=:symbol LIMIT 1) fno,
              (EXISTS(SELECT 1 FROM nse_bulk_deals WHERE symbol=:symbol LIMIT 1) OR
               EXISTS(SELECT 1 FROM nse_block_deals WHERE symbol=:symbol LIMIT 1) OR
               EXISTS(SELECT 1 FROM nse_short_selling WHERE symbol=:symbol LIMIT 1) OR
               EXISTS(SELECT 1 FROM nse_corporate_actions WHERE symbol=:symbol LIMIT 1)) activity,
              EXISTS(SELECT 1 FROM stock_info WHERE sector=:sector AND ticker<>:ticker LIMIT 1) peers,
              (EXISTS(SELECT 1 FROM nexus_signal_instances WHERE underlying_symbol=:symbol LIMIT 1) OR
               EXISTS(SELECT 1 FROM scanner_signals WHERE symbol=:symbol LIMIT 1)) nexus
        """), {
            "ticker": ticker, "symbol": sym, "sector": identity.get("sector"),
            "mention": f"%{sym}%", "company": f"%{identity.get('company_name') or sym}%",
        }).mappings().one()
        latest = self.db.execute(text("""
            WITH max_price AS (
              SELECT max(date) AS date FROM stock_prices WHERE ticker=:ticker
            ),
            price_window AS (
              SELECT prices.date, prices.close, prices.volume,
                     lag(prices.close) OVER (ORDER BY prices.date) AS previous_close
              FROM stock_prices prices CROSS JOIN max_price
              WHERE prices.ticker=:ticker
                AND prices.date >= max_price.date - INTERVAL '370 days'
            ),
            latest_price AS (
              SELECT date, close, volume, previous_close
              FROM price_window ORDER BY date DESC LIMIT 1
            ),
            volume_history AS (
              SELECT volume
              FROM stock_prices
              WHERE ticker=:ticker
                AND date < (SELECT date FROM latest_price)
              ORDER BY date DESC LIMIT 20
            ),
            return_history AS (
              SELECT date, close / NULLIF(previous_close, 0) - 1 AS daily_return
              FROM price_window
              WHERE date >= (SELECT date FROM latest_price) - INTERVAL '1 year'
            )
            SELECT p.date, p.close, p.volume, p.previous_close,
                   p.close - p.previous_close AS change,
                   (p.close / NULLIF(p.previous_close, 0) - 1) * 100 AS change_pct,
                   (SELECT avg(volume) FROM volume_history) AS average_volume_20,
                   (SELECT count(*) FROM volume_history) AS volume_observations,
                   (SELECT stddev_samp(daily_return) * sqrt(252) * 100
                    FROM return_history WHERE daily_return IS NOT NULL) AS volatility_1y,
                   (SELECT count(daily_return)
                    FROM return_history WHERE daily_return IS NOT NULL) AS return_observations
            FROM latest_price p
        """), {"ticker": ticker}).mappings().first()
        market_context = self.db.execute(text("""
            SELECT
              (SELECT json_build_object(
                        'report_date', report_date,
                        'high', adj_52_week_high,
                        'low', adj_52_week_low
                      )
               FROM nse_52_week_high_low
               WHERE upper(symbol)=:symbol
               ORDER BY report_date DESC LIMIT 1) AS range_52w,
              (SELECT json_build_object(
                        'report_date', report_date,
                        'pe', pe,
                        'adjusted_pe', adjusted_pe
                      )
               FROM nse_pe_ratios
               WHERE upper(symbol)=:symbol
               ORDER BY report_date DESC LIMIT 1) AS pe_context
        """), {"symbol": sym}).mappings().one()
        nexus_signal = self.db.execute(text("""
            SELECT signal_code, signal_family, severity, confidence, anomaly_score,
                   title, summary, event_time, data_quality
            FROM nexus_signal_instances
            WHERE upper(underlying_symbol)=:symbol
            ORDER BY event_time DESC NULLS LAST
            LIMIT 1
        """), {"symbol": sym}).mappings().first()
        recent_prices = [
            (row.date, float(row.close))
            for row in reversed(self.db.execute(text("""
                SELECT date, close
                FROM stock_prices
                WHERE ticker=:ticker AND close IS NOT NULL
                ORDER BY date DESC
                LIMIT 400
            """), {"ticker": ticker}).all())
        ]
        recent_closes = [close for _, close in recent_prices]
        sma_20 = sum(recent_closes[-20:]) / 20 if len(recent_closes) >= 20 else None
        sma_50 = sum(recent_closes[-50:]) / 50 if len(recent_closes) >= 50 else None
        latest_close = recent_closes[-1] if recent_closes else None
        technical = {
            "rsi_14": _rsi_14(recent_closes),
            "sma_20": sma_20,
            "sma_50": sma_50,
            "price_vs_sma_50_pct": (
                (latest_close / sma_50 - 1) * 100
                if latest_close is not None and sma_50 not in (None, 0) else None
            ),
            "return_1m": _return_since(recent_prices, 30),
            "return_6m": _return_since(recent_prices, 182),
            "return_1y": _return_since(recent_prices, 365),
        }
        fno_snapshot = self.db.execute(text("""
            WITH latest_snapshot AS (
              SELECT snapshot_time
              FROM option_chain_snapshots
              WHERE underlying_symbol=:symbol
              ORDER BY id DESC
              LIMIT 1
            ),
            nearest_expiry AS (
              SELECT min(o.expiry) AS expiry
              FROM option_chain_snapshots o
              CROSS JOIN latest_snapshot s
              WHERE o.underlying_symbol=:symbol
                AND o.snapshot_time=s.snapshot_time
                AND o.expiry >= s.snapshot_time::date
            ),
            chain AS (
              SELECT o.*
              FROM option_chain_snapshots o
              CROSS JOIN latest_snapshot s
              CROSS JOIN nearest_expiry e
              WHERE o.underlying_symbol=:symbol
                AND o.snapshot_time=s.snapshot_time
                AND o.expiry=e.expiry
            ),
            atm AS (
              SELECT strike_price
              FROM chain
              ORDER BY abs(strike_price-underlying_spot_price)
              LIMIT 1
            )
            SELECT max(snapshot_time) AS snapshot_time,
                   max(expiry) AS expiry,
                   max(underlying_spot_price) AS spot_price,
                   sum(oi) FILTER (WHERE upper(option_type)='PE')
                     / NULLIF(sum(oi) FILTER (WHERE upper(option_type)='CE'), 0)::double precision AS pcr_oi,
                   avg(iv) FILTER (WHERE strike_price=(SELECT strike_price FROM atm)) AS atm_iv,
                   (array_agg(strike_price ORDER BY oi DESC)
                     FILTER (WHERE upper(option_type)='CE' AND oi IS NOT NULL))[1] AS call_wall,
                   (array_agg(strike_price ORDER BY oi DESC)
                     FILTER (WHERE upper(option_type)='PE' AND oi IS NOT NULL))[1] AS put_wall,
                   sum(oi) AS total_oi,
                   sum(change_in_oi) AS change_in_oi,
                   sum(volume) AS total_volume
            FROM chain
        """), {"symbol": sym}).mappings().first()
        activity = self.db.execute(text("""
            SELECT
              (SELECT count(*) FROM nse_block_deals
               WHERE lower(symbol)=lower(:symbol) AND trade_date >= CURRENT_DATE-INTERVAL '90 days') AS block_deals_90d,
              (SELECT count(*) FROM nse_bulk_deals
               WHERE lower(symbol)=lower(:symbol) AND trade_date >= CURRENT_DATE-INTERVAL '90 days') AS bulk_deals_90d,
              (SELECT json_build_object(
                        'trade_date', trade_date,
                        'client_name', client_name,
                        'side', buy_sell,
                        'quantity', quantity_traded,
                        'price', trade_price,
                        'type', 'block'
                      )
               FROM nse_block_deals
               WHERE lower(symbol)=lower(:symbol)
               ORDER BY trade_date DESC, id DESC LIMIT 1) AS latest_block_deal,
              (SELECT json_build_object(
                        'trade_date', trade_date,
                        'client_name', client_name,
                        'side', buy_sell,
                        'quantity', quantity_traded,
                        'price', trade_price,
                        'type', 'bulk'
                      )
               FROM nse_bulk_deals
               WHERE lower(symbol)=lower(:symbol)
               ORDER BY trade_date DESC, id DESC LIMIT 1) AS latest_bulk_deal,
              (SELECT json_build_object(
                        'trade_date', trade_date,
                        'quantity', quantity
                      )
               FROM nse_short_selling
               WHERE upper(symbol)=:symbol
               ORDER BY trade_date DESC, id DESC LIMIT 1) AS latest_short_selling
        """), {"symbol": sym}).mappings().one()
        events = self.db.execute(text("""
            SELECT
              (SELECT json_build_object(
                        'report_date', report_date,
                        'eps_estimate', eps_estimate
                      )
               FROM stock_earnings_dates
               WHERE upper(ticker)=:ticker
                 AND report_date >= CURRENT_DATE
               ORDER BY report_date ASC LIMIT 1) AS next_earnings,
              (SELECT json_build_object(
                        'report_date', report_date,
                        'eps_estimate', eps_estimate,
                        'eps_actual', eps_actual,
                        'surprise_pct', surprise_pct
                      )
               FROM stock_earnings_dates
               WHERE upper(ticker)=:ticker
                 AND eps_actual IS NOT NULL
               ORDER BY report_date DESC LIMIT 1) AS latest_earnings,
              (SELECT json_build_object(
                        'ex_date', ex_date,
                        'purpose', purpose,
                        'face_value', face_value
                      )
               FROM nse_corporate_actions
               WHERE upper(symbol)=:symbol
               ORDER BY created_at DESC NULLS LAST LIMIT 1) AS latest_corporate_action
        """), {"ticker": ticker, "symbol": sym}).mappings().one()

        latest_payload = (
            {key: _json_value(value) for key, value in latest.items()}
            if latest else None
        )
        price_change_pct = latest_payload.get("change_pct") if latest_payload else None
        average_volume = latest_payload.get("average_volume_20") if latest_payload else None
        current_volume = latest_payload.get("volume") if latest_payload else None
        volume_ratio = (
            current_volume / average_volume
            if current_volume is not None and average_volume not in (None, 0) else None
        )
        volatility = latest_payload.get("volatility_1y") if latest_payload else None
        volatility_band = (
            None if volatility is None
            else "Lower" if volatility < 20
            else "Moderate" if volatility < 35
            else "Higher"
        )
        range_52w = market_context.get("range_52w")
        range_position = None
        if latest_payload and range_52w:
            range_low = range_52w.get("low")
            range_high = range_52w.get("high")
            if range_low is not None and range_high is not None and range_high > range_low:
                range_position = max(
                    0,
                    min(100, (latest_payload["close"] - range_low) / (range_high - range_low) * 100),
                )
        snapshot = {
            "price": {
                "close": latest_payload.get("close") if latest_payload else None,
                "change": latest_payload.get("change") if latest_payload else None,
                "change_pct": price_change_pct,
                "date": latest_payload.get("date") if latest_payload else None,
            },
            "valuation": {
                "market_cap": identity.get("market_cap"),
                "trailing_pe": identity.get("trailing_pe"),
                "forward_pe": identity.get("forward_pe"),
                "price_to_book": identity.get("price_to_book"),
                "nse_pe": (market_context.get("pe_context") or {}).get("pe"),
                "nse_adjusted_pe": (market_context.get("pe_context") or {}).get("adjusted_pe"),
            },
            "fundamentals": {
                "roe": identity.get("roe"),
                "profit_margin": identity.get("profit_margins"),
                "revenue_growth": identity.get("revenue_growth"),
            },
            "range_52w": {
                "high": range_52w.get("high") if range_52w else None,
                "low": range_52w.get("low") if range_52w else None,
                "position_pct": range_position,
            },
            "risk": {
                "volatility_1y": volatility,
                "volatility_band": volatility_band,
                "return_observations": latest_payload.get("return_observations") if latest_payload else 0,
            },
            "liquidity": {
                "volume": current_volume,
                "average_volume_20": average_volume,
                "volume_ratio": volume_ratio,
                "volume_observations": latest_payload.get("volume_observations") if latest_payload else 0,
            },
            "intelligence": (
                {key: _json_value(value) for key, value in nexus_signal.items()}
                if nexus_signal else None
            ),
            "technical": technical,
            "fno": (
                {key: _json_value(value) for key, value in fno_snapshot.items()}
                if fno_snapshot and fno_snapshot.get("snapshot_time") else None
            ),
            "activity": {key: _json_value(value) for key, value in activity.items()},
            "events": {key: _json_value(value) for key, value in events.items()},
            "as_of": {
                "price": latest_payload.get("date") if latest_payload else None,
                "profile": identity.get("fetched_at"),
                "range_52w": range_52w.get("report_date") if range_52w else None,
                "pe_context": (market_context.get("pe_context") or {}).get("report_date"),
                "nexus": _json_value(nexus_signal.get("event_time")) if nexus_signal else None,
                "fno": _json_value(fno_snapshot.get("snapshot_time")) if fno_snapshot else None,
                "activity": _json_value(
                    (activity.get("latest_block_deal") or activity.get("latest_bulk_deal")
                     or activity.get("latest_short_selling") or {}).get("trade_date")
                ),
            },
        }
        descriptors = [
            ("overview", "Overview", True, None),
            ("chart", "Chart", availability.prices, "No historical prices"),
            ("financials", "Financials", availability.financials, "No financial statements"),
            ("ownership", "Ownership", availability.ownership, "No ownership rows"),
            ("news-events", "News & Events", availability.news, "No related news or events"),
            ("fno", "F&O", availability.fno, "This stock has no current F&O rows"),
            ("deals", "Deals & Activity", availability.activity, "No deals or corporate activity"),
            ("peers", "Peers", availability.peers, "No mapped sector peers"),
            ("nexus-risk", "Nexus & Risk", availability.nexus, "Nexus and scanner tables have no rows"),
        ]
        return {
            "identity": identity,
            "latest_price": latest_payload,
            "snapshot": snapshot,
            "tabs": [
                {"id": tab_id, "label": label, "available": available, "reason": None if available else reason}
                for tab_id, label, available, reason in descriptors
            ],
        }

    def tab(self, symbol: str, tab: str) -> dict[str, Any]:
        identity = self.identity(symbol)
        if not identity:
            return {"status": "missing", "reason": "Stock could not be resolved"}
        sym, ticker = identity["symbol"], identity["ticker"]
        if tab == "overview":
            analysis_row = self.db.execute(text("""
                SELECT summary, generated_at FROM stock_analysis
                WHERE upper(ticker) IN (:symbol,:ticker)
                ORDER BY generated_at DESC NULLS LAST LIMIT 1
            """), {"symbol": sym, "ticker": ticker}).mappings().first()
            analysis = {}
            if analysis_row and isinstance(analysis_row["summary"], dict):
                analysis = {k: v for k, v in analysis_row["summary"].items() if k in NEUTRAL_ANALYSIS_KEYS}
            market = self.db.execute(text("""
                SELECT
                  (SELECT json_build_object('report_date',report_date,'high',adj_52_week_high,'low',adj_52_week_low)
                   FROM nse_52_week_high_low WHERE upper(symbol)=:symbol ORDER BY report_date DESC LIMIT 1) AS range_52w,
                  (SELECT json_build_object('report_date',report_date,'pe',pe,'adjusted_pe',adjusted_pe)
                   FROM nse_pe_ratios WHERE upper(symbol)=:symbol ORDER BY report_date DESC LIMIT 1) AS pe_context,
                  (SELECT json_build_object('report_date',report_date,'category',category,'ltp',ltp,'change_pct',change_pct)
                   FROM nse_top_gainers_losers WHERE upper(symbol)=:symbol ORDER BY report_date DESC LIMIT 1) AS ranking
            """), {"symbol": sym}).mappings().one()
            return {"status": "available", "identity": identity, "analysis": analysis, "market_context": dict(market)}
        if tab == "financials":
            statements = _rows(self.db.execute(text("""
                SELECT statement_type, fiscal_date, line_item, value
                FROM stock_financials WHERE upper(ticker)=:ticker
                ORDER BY fiscal_date DESC, statement_type, line_item
            """), {"ticker": ticker}))
            earnings = _rows(self.db.execute(text("""
                SELECT report_date, eps_estimate, eps_actual, surprise_pct,
                       revenue_estimate, revenue_actual
                FROM stock_earnings_dates WHERE upper(ticker)=:ticker
                ORDER BY report_date DESC LIMIT 12
            """), {"ticker": ticker}))
            return {"status": "available" if statements else "missing", "statements": statements, "earnings": earnings}
        if tab == "ownership":
            holders = _rows(self.db.execute(text("""
                SELECT holder_type, holder_name, shares, date_reported, percent_held
                FROM stock_holders WHERE upper(ticker)=:ticker
                ORDER BY date_reported DESC NULLS LAST, percent_held DESC NULLS LAST LIMIT 60
            """), {"ticker": ticker}))
            insiders = _rows(self.db.execute(text("""
                SELECT insider_name, transaction_type, shares, price, transaction_date, created_at
                FROM stock_insider_transactions WHERE upper(ticker)=:ticker
                ORDER BY transaction_date DESC NULLS LAST, created_at DESC LIMIT 40
            """), {"ticker": ticker}))
            return {"status": "available" if holders or insiders else "missing", "holders": holders, "insider_transactions": insiders}
        if tab == "news-events":
            news = _rows(self.db.execute(text("""
                SELECT id, title, link, description, source_name, published_at, category
                FROM market_news
                WHERE title ILIKE :mention OR description ILIKE :mention
                   OR title ILIKE :company OR description ILIKE :company
                ORDER BY published_at DESC NULLS LAST LIMIT 40
            """), {"mention": f"%{sym}%", "company": f"%{identity.get('company_name') or sym}%"}))
            actions = _rows(self.db.execute(text("""
                SELECT ex_date, purpose, isin, face_value FROM nse_corporate_actions
                WHERE upper(symbol)=:symbol ORDER BY ex_date DESC LIMIT 30
            """), {"symbol": sym}))
            return {"status": "available" if news or actions else "missing", "news": news, "corporate_actions": actions}
        if tab == "fno":
            latest = self.db.execute(text("""
                SELECT max(snapshot_time) FROM option_chain_snapshots
                WHERE upper(underlying_symbol)=:symbol
            """), {"symbol": sym}).scalar()
            chain = _rows(self.db.execute(text("""
                SELECT expiry, strike_price, option_type, ltp, volume, oi, change_in_oi,
                       bid_price, ask_price, iv, delta, gamma, theta, vega,
                       underlying_spot_price, snapshot_time
                FROM option_chain_snapshots
                WHERE upper(underlying_symbol)=:symbol AND snapshot_time=:snapshot
                ORDER BY expiry, strike_price, option_type LIMIT 1000
            """), {"symbol": sym, "snapshot": latest})) if latest else []
            return {"status": "available" if chain else "missing", "snapshot_time": _json_value(latest), "chain": chain}
        if tab == "deals":
            payload = {}
            for key, table in (("bulk_deals", "nse_bulk_deals"), ("block_deals", "nse_block_deals"), ("short_selling", "nse_short_selling")):
                payload[key] = _rows(self.db.execute(text(f"""
                    SELECT * FROM {table} WHERE upper(symbol)=:symbol
                    ORDER BY trade_date DESC LIMIT 40
                """), {"symbol": sym}))
            payload["corporate_actions"] = _rows(self.db.execute(text("""
                SELECT ex_date, purpose, isin, face_value FROM nse_corporate_actions
                WHERE upper(symbol)=:symbol ORDER BY ex_date DESC LIMIT 40
            """), {"symbol": sym}))
            return {"status": "available" if any(payload.values()) else "missing", **payload}
        if tab == "peers":
            peers = _rows(self.db.execute(text("""
                WITH peer_universe AS (
                    SELECT DISTINCT ON (ticker)
                           symbol, ticker, company_name, sector, industry, market_cap,
                           trailing_pe, price_to_book, roe
                    FROM stock_info
                    WHERE ticker=:ticker OR sector=:sector
                    ORDER BY ticker, fetched_at DESC NULLS LAST
                ),
                selected_peers AS (
                    SELECT *
                    FROM peer_universe
                    ORDER BY CASE WHEN ticker=:ticker THEN 0 ELSE 1 END,
                             CASE WHEN industry=:industry THEN 0 ELSE 1 END,
                             market_cap DESC NULLS LAST
                    LIMIT 20
                )
                SELECT p.symbol, p.company_name, p.sector, p.industry,
                       (p.ticker=:ticker) AS is_selected,
                       p.market_cap / 10000000.0 AS market_cap_cr,
                       p.trailing_pe, p.price_to_book, p.roe,
                       perf.return_1w, perf.return_1m, perf.return_3m,
                       perf.return_6m, perf.return_1y, perf.return_5y,
                       risk.volatility_1y,
                       CASE
                         WHEN risk.volatility_1y IS NULL THEN NULL
                         WHEN risk.volatility_1y < 20 THEN 'Lower'
                         WHEN risk.volatility_1y < 35 THEN 'Moderate'
                         ELSE 'Higher'
                       END AS risk_band
                FROM selected_peers p
                LEFT JOIN LATERAL (
                    SELECT
                      CASE WHEN w1.close > 0 THEN (latest.close / w1.close - 1) * 100 END AS return_1w,
                      CASE WHEN m1.close > 0 THEN (latest.close / m1.close - 1) * 100 END AS return_1m,
                      CASE WHEN m3.close > 0 THEN (latest.close / m3.close - 1) * 100 END AS return_3m,
                      CASE WHEN m6.close > 0 THEN (latest.close / m6.close - 1) * 100 END AS return_6m,
                      CASE WHEN y1.close > 0 THEN (latest.close / y1.close - 1) * 100 END AS return_1y,
                      CASE WHEN y5.close > 0 THEN (latest.close / y5.close - 1) * 100 END AS return_5y
                    FROM LATERAL (
                      SELECT date, close FROM stock_prices
                      WHERE ticker=p.ticker ORDER BY date DESC LIMIT 1
                    ) latest
                    LEFT JOIN LATERAL (SELECT close FROM stock_prices WHERE ticker=p.ticker AND date<=latest.date-INTERVAL '7 days' ORDER BY date DESC LIMIT 1) w1 ON true
                    LEFT JOIN LATERAL (SELECT close FROM stock_prices WHERE ticker=p.ticker AND date<=latest.date-INTERVAL '1 month' ORDER BY date DESC LIMIT 1) m1 ON true
                    LEFT JOIN LATERAL (SELECT close FROM stock_prices WHERE ticker=p.ticker AND date<=latest.date-INTERVAL '3 months' ORDER BY date DESC LIMIT 1) m3 ON true
                    LEFT JOIN LATERAL (SELECT close FROM stock_prices WHERE ticker=p.ticker AND date<=latest.date-INTERVAL '6 months' ORDER BY date DESC LIMIT 1) m6 ON true
                    LEFT JOIN LATERAL (SELECT close FROM stock_prices WHERE ticker=p.ticker AND date<=latest.date-INTERVAL '1 year' ORDER BY date DESC LIMIT 1) y1 ON true
                    LEFT JOIN LATERAL (SELECT close FROM stock_prices WHERE ticker=p.ticker AND date<=latest.date-INTERVAL '5 years' ORDER BY date DESC LIMIT 1) y5 ON true
                ) perf ON true
                LEFT JOIN LATERAL (
                    SELECT stddev_samp(daily_return) * sqrt(252) * 100 AS volatility_1y
                    FROM (
                      SELECT close / lag(close) OVER (ORDER BY date) - 1 AS daily_return
                      FROM stock_prices
                      WHERE ticker=p.ticker AND date >= CURRENT_DATE - INTERVAL '1 year'
                    ) returns
                ) risk ON true
                ORDER BY CASE WHEN p.ticker=:ticker THEN 0 ELSE 1 END,
                         CASE WHEN p.industry=:industry THEN 0 ELSE 1 END,
                         p.market_cap DESC NULLS LAST
            """), {"sector": identity.get("sector"), "industry": identity.get("industry"), "ticker": ticker}))
            selected = next((row for row in peers if row.get("is_selected")), None)
            comparison_rows = [row for row in peers if not row.get("is_selected")]
            if selected:
                for row in comparison_rows:
                    available = [
                        (
                            row.get("return_1y") is not None and selected.get("return_1y") is not None,
                            row["return_1y"] > selected["return_1y"]
                            if row.get("return_1y") is not None and selected.get("return_1y") is not None else False,
                        ),
                        (
                            row.get("return_5y") is not None and selected.get("return_5y") is not None,
                            row["return_5y"] > selected["return_5y"]
                            if row.get("return_5y") is not None and selected.get("return_5y") is not None else False,
                        ),
                        (
                            row.get("volatility_1y") is not None and selected.get("volatility_1y") is not None,
                            row["volatility_1y"] < selected["volatility_1y"]
                            if row.get("volatility_1y") is not None and selected.get("volatility_1y") is not None else False,
                        ),
                    ]
                    outcomes = [outcome for is_available, outcome in available if is_available]
                    row["better_metric_count"] = sum(outcomes)
                    row["compared_metric_count"] = len(outcomes)
                    row["is_better_than_selected"] = len(outcomes) >= 2 and sum(outcomes) >= 2
                selected["better_metric_count"] = 0
                selected["compared_metric_count"] = 3
                selected["is_better_than_selected"] = False

            def peer_median(field: str) -> float | None:
                values = [float(row[field]) for row in comparison_rows if row.get(field) is not None]
                return median(values) if values else None

            def selected_rank(field: str, descending: bool = True) -> int | None:
                if not selected or selected.get(field) is None:
                    return None
                values = [
                    (row.get("symbol"), float(row[field]))
                    for row in peers if row.get(field) is not None
                ]
                values.sort(key=lambda item: item[1], reverse=descending)
                return next((index + 1 for index, (row_symbol, _) in enumerate(values) if row_symbol == selected["symbol"]), None)

            analysis = {
                "peer_count": len(comparison_rows),
                "market_cap": {
                    "selected": selected.get("market_cap_cr") if selected else None,
                    "peer_median": peer_median("market_cap_cr"),
                    "rank": selected_rank("market_cap_cr"),
                },
                "valuation": {
                    "selected": selected.get("trailing_pe") if selected else None,
                    "peer_median": peer_median("trailing_pe"),
                },
                "return_1y": {
                    "selected": selected.get("return_1y") if selected else None,
                    "peer_median": peer_median("return_1y"),
                    "rank": selected_rank("return_1y"),
                },
                "return_5y": {
                    "selected": selected.get("return_5y") if selected else None,
                    "peer_median": peer_median("return_5y"),
                    "rank": selected_rank("return_5y"),
                },
                "risk": {
                    "selected_volatility": selected.get("volatility_1y") if selected else None,
                    "peer_median_volatility": peer_median("volatility_1y"),
                    "band": selected.get("risk_band") if selected else None,
                    "rank": selected_rank("volatility_1y", descending=False),
                },
            }
            return {
                "status": "available" if peers else "missing",
                "selected_symbol": sym,
                "analysis": analysis,
                "peers": peers,
            }
        if tab == "nexus-risk":
            signals = _rows(self.db.execute(text("""
                SELECT signal_code, signal_family, severity, confidence, anomaly_score,
                       title, summary, event_time, data_quality
                FROM nexus_signal_instances WHERE upper(underlying_symbol)=:symbol
                ORDER BY event_time DESC LIMIT 30
            """), {"symbol": sym}))
            scanner = _rows(self.db.execute(text("""
                SELECT signal_code, severity, confidence, risk_score, title, summary,
                       signal_date, data_quality
                FROM scanner_signals WHERE upper(symbol)=:symbol
                ORDER BY signal_date DESC LIMIT 30
            """), {"symbol": sym}))
            return {"status": "available" if signals or scanner else "missing", "signals": signals, "scanner_signals": scanner}
        return {"status": "missing", "reason": "Unsupported tab"}
