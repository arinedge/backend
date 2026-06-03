from datetime import date, datetime, timezone, timedelta
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.models.market_data import MarketData, MarketStatus, MarketHoliday, MarketTiming
from app.models.broker import Broker
from app.services.upstox import UpstoxClient, UpstoxError
from app.config import get_settings
from app.utils.logger import get_logger
from app.utils.redis_cache import cache_get, cache_set, cache_delete_pattern, get_redis

logger = get_logger(__name__)

TRACKED_INDICES: dict[str, dict[str, str]] = {
    "NSE_INDEX|Nifty 50": {"symbol": "NIFTY_50", "name": "Nifty 50"},
    "BSE_INDEX|SENSEX": {"symbol": "SENSEX", "name": "SENSEX"},
    "NSE_INDEX|Nifty Bank": {"symbol": "BANK_NIFTY", "name": "Nifty Bank"},
    "NSE_INDEX|India VIX": {"symbol": "INDIA_VIX", "name": "India VIX"},
}

EXCHANGES_TO_CHECK = ["NSE", "BSE"]

IST = timezone(timedelta(hours=5, minutes=30))


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class MarketDataService:
    def __init__(self, db: Session, broker: Broker | None = None):
        self.db = db
        self.broker = broker
        self.settings = get_settings()

    def _get_client(self) -> UpstoxClient | None:
        if not self.broker or not self.broker.access_token:
            logger.warning("No broker with valid access_token found")
            return None
        return UpstoxClient(self.broker.access_token)

    # ── Schedule helpers (holidays + timings stored in DB) ──────────────

    def _is_weekend(self, d: date | None = None) -> bool:
        return (d or date.today()).weekday() >= 5

    def _get_today_holiday(self) -> MarketHoliday | None:
        return (
            self.db.query(MarketHoliday)
            .filter(MarketHoliday.holiday_date == date.today())
            .first()
        )

    def _get_today_timing(self, exchange: str) -> MarketTiming | None:
        return (
            self.db.query(MarketTiming)
            .filter(
                MarketTiming.timing_date == date.today(),
                MarketTiming.exchange == exchange,
            )
            .first()
        )

    async def _ensure_today_schedule(self) -> None:
        """Fetch holidays + timings from Upstox if not already in DB for today."""
        client = self._get_client()
        if not client:
            return

        today = date.today()

        if not self._get_today_holiday():
            try:
                date_str = today.isoformat()
                holidays = await client.get_market_holidays(date_str)
                for h in holidays:
                    closed = h.get("closed_exchanges", [])
                    entry = MarketHoliday(
                        holiday_date=today,
                        description=h.get("description", ""),
                        holiday_type=h.get("holiday_type", ""),
                        closed_exchanges=closed,
                    )
                    self.db.add(entry)
                self.db.commit()
                logger.debug("Stored %d holiday entries for %s", len(holidays), date_str)
            except Exception as e:
                logger.warning("Failed to fetch/store holidays: %s", e)

        for exchange in EXCHANGES_TO_CHECK:
            if self._get_today_timing(exchange):
                continue
            try:
                date_str = today.isoformat()
                timings = await client.get_market_timings(date_str)
                for entry in timings:
                    if entry.get("exchange") == exchange:
                        t = MarketTiming(
                            timing_date=today,
                            exchange=exchange,
                            start_time=datetime.fromtimestamp(
                                entry["start_time"] / 1000, tz=timezone.utc
                            ),
                            end_time=datetime.fromtimestamp(
                                entry["end_time"] / 1000, tz=timezone.utc
                            ),
                        )
                        self.db.add(t)
                        self.db.commit()
                        logger.debug("Stored timing for %s on %s", exchange, date_str)
                        break
            except Exception as e:
                logger.warning("Failed to fetch/store timing for %s: %s", exchange, e)

    async def _should_fetch_live(self) -> bool:
        today = date.today()

        if self._is_weekend(today):
            logger.info("Weekend — skipping live fetch")
            return False

        await self._ensure_today_schedule()

        holiday = self._get_today_holiday()
        if holiday and holiday.holiday_type == "TRADING_HOLIDAY":
            closed = holiday.closed_exchanges or []
            if any(ex in closed for ex in EXCHANGES_TO_CHECK):
                logger.info("Trading holiday (%s) — using cache", holiday.description)
                return False

        now_utc = _now_utc()
        any_timing_found = False
        for exchange in EXCHANGES_TO_CHECK:
            timing = self._get_today_timing(exchange)
            if not timing:
                continue
            any_timing_found = True
            start_ist = timing.start_time.astimezone(IST)
            end_ist = timing.end_time.astimezone(IST)
            now_ist = now_utc.astimezone(IST)
            if start_ist <= now_ist <= end_ist:
                logger.debug("%s is open (%s-%s IST)", exchange, start_ist.strftime("%H:%M"), end_ist.strftime("%H:%M"))
                return True
            logger.info(
                "%s outside hours (%s-%s IST, now=%s)",
                exchange,
                start_ist.strftime("%H:%M"),
                end_ist.strftime("%H:%M"),
                now_ist.strftime("%H:%M"),
            )

        if any_timing_found:
            return False
        return True

    # ── Market status ──────────────────────────────────────────────────

    async def check_market_status(self) -> dict[str, Any]:
        cached = await cache_get("market_data:status")
        if cached is not None:
            return cached

        results: dict[str, Any] = {}
        client = self._get_client()
        if not client:
            return {ex: {"status": "UNKNOWN"} for ex in EXCHANGES_TO_CHECK}

        for exchange in EXCHANGES_TO_CHECK:
            try:
                data = await client.get_market_status(exchange)
                results[exchange] = data

                existing = (
                    self.db.query(MarketStatus)
                    .filter(MarketStatus.exchange == exchange)
                    .order_by(desc(MarketStatus.last_checked_at))
                    .first()
                )

                last_checked = _now_utc()
                if "last_updated" in data:
                    try:
                        last_checked = datetime.fromtimestamp(
                            data["last_updated"] / 1000, tz=timezone.utc
                        )
                    except (OSError, ValueError):
                        pass

                if existing:
                    existing.status = data["status"]
                    existing.last_checked_at = last_checked
                else:
                    self.db.add(MarketStatus(
                        exchange=exchange,
                        status=data["status"],
                        last_checked_at=last_checked,
                    ))
                self.db.commit()
            except Exception as e:
                logger.error("Failed to check market status for %s: %s", exchange, e)
                results[exchange] = {"status": "UNKNOWN", "error": str(e)}

        await cache_set("market_data:status", results, ttl=60)
        return results

    # ── Fetch & store live data ────────────────────────────────────────

    async def fetch_and_store_market_data(self, force: bool = False) -> list[dict[str, Any]]:
        if not force and not await self._should_fetch_live():
            return await self._get_cached_data()

        client = self._get_client()
        if not client:
            return await self._get_cached_data()

        try:
            keys = list(TRACKED_INDICES.keys())
            quotes = await client.get_market_quotes(keys)
        except UpstoxError as e:
            logger.error("Failed to fetch market quotes: %s", e)
            return await self._get_cached_data()

        now = _now_utc()
        results: list[dict[str, Any]] = []
        for inst_key, quote in quotes.items():
            mapped_key = inst_key.replace(":", "|")
            info = TRACKED_INDICES.get(inst_key) or TRACKED_INDICES.get(mapped_key)
            if not info:
                continue

            last_price = float(quote.get("last_price", 0))
            change = float(quote.get("net_change", 0))
            change_percent = 0.0
            prev_close = last_price - change
            if prev_close != 0:
                change_percent = round((change / prev_close) * 100, 2)

            ohlc = quote.get("ohlc", {})

            self.db.add(MarketData(
                instrument_key=inst_key,
                symbol=info["symbol"],
                name=info["name"],
                last_price=last_price,
                change=change,
                change_percent=change_percent,
                open_price=ohlc.get("open"),
                high_price=ohlc.get("high"),
                low_price=ohlc.get("low"),
                close_price=ohlc.get("close"),
                volume=quote.get("volume"),
                bid=quote.get("total_buy_quantity"),
                ask=quote.get("total_sell_quantity"),
                oi=quote.get("oi"),
                source="live",
                fetched_at=now,
            ))

            results.append({
                "symbol": info["symbol"],
                "name": info["name"],
                "instrument_key": inst_key,
                "last_price": last_price,
                "change": change,
                "change_percent": change_percent,
                "open_price": ohlc.get("open"),
                "high_price": ohlc.get("high"),
                "low_price": ohlc.get("low"),
                "close_price": ohlc.get("close"),
                "volume": quote.get("volume"),
                "source": "live",
                "fetched_at": now,
            })

        self.db.commit()
        logger.info("Stored %d live market data points", len(results))

        await cache_delete_pattern("market_data:*")
        if results:
            await cache_set(self._cache_key(), results, ttl=30)

        return results

    # ── Real-time WebSocket tick handler ──────────────────────────────

    async def process_ws_tick(self, tick: dict[str, Any]) -> dict[str, Any] | None:
        inst_key = tick["instrument_key"]
        mapped_key = inst_key.replace(":", "|")
        info = TRACKED_INDICES.get(inst_key) or TRACKED_INDICES.get(mapped_key)
        if not info:
            logger.warning("WS tick: unknown instrument %s", inst_key)
            return None

        now = _now_utc()
        last_price = tick.get("last_price", 0)
        change = tick.get("change", 0)
        change_percent = tick.get("change_percent", 0)

        self.db.add(MarketData(
            instrument_key=inst_key,
            symbol=info["symbol"],
            name=info["name"],
            last_price=last_price,
            change=change,
            change_percent=change_percent,
            open_price=tick.get("open_price"),
            high_price=tick.get("high_price"),
            low_price=tick.get("low_price"),
            close_price=tick.get("close_price"),
            volume=tick.get("volume"),
            source="live",
            fetched_at=now,
        ))

        result = {
            "symbol": info["symbol"],
            "name": info["name"],
            "instrument_key": inst_key,
            "last_price": last_price,
            "change": change,
            "change_percent": change_percent,
            "open_price": tick.get("open_price"),
            "high_price": tick.get("high_price"),
            "low_price": tick.get("low_price"),
            "close_price": tick.get("close_price"),
            "volume": tick.get("volume"),
            "source": "live",
            "fetched_at": now,
        }

        await cache_set(
            f"market_data:tick:{info['symbol']}", result, ttl=60
        )
        return result

    # ── Option tick handling ────────────────────────────────────────────

    async def process_option_tick(self, tick: dict[str, Any]) -> dict[str, Any] | None:
        inst_key = tick["instrument_key"]
        now = _now_utc()
        last_price = tick.get("last_price", 0)
        change = tick.get("change", 0)
        change_percent = tick.get("change_percent", 0)

        self.db.add(MarketData(
            instrument_key=inst_key,
            symbol=tick.get("underlying_symbol", ""),
            name=tick.get("trading_symbol", ""),
            last_price=last_price,
            change=change,
            change_percent=change_percent,
            open_price=tick.get("open_price"),
            high_price=tick.get("high_price"),
            low_price=tick.get("low_price"),
            close_price=tick.get("close_price"),
            volume=tick.get("volume"),
            bid=tick.get("bid"),
            ask=tick.get("ask"),
            oi=tick.get("oi"),
            oi_change=tick.get("oi_change"),
            iv=tick.get("iv"),
            delta=tick.get("delta"),
            gamma=tick.get("gamma"),
            theta=tick.get("theta"),
            vega=tick.get("vega"),
            rho=tick.get("rho"),
            source="live",
            fetched_at=now,
        ))

        self.db.commit()

        await cache_set(f"market_data:tick:option:{inst_key}", tick, ttl=60)
        logger.debug("Processed option tick for %s: LTP=%.2f OI=%s IV=%s", inst_key, last_price, tick.get("oi"), tick.get("iv"))
        return tick

    async def get_latest_option_prices(
        self, instrument_keys: list[str]
    ) -> dict[str, dict[str, Any]]:
        """Return latest tick per instrument_key from Redis cache (batched MGET)."""
        result: dict[str, dict[str, Any]] = {}
        if not instrument_keys:
            return result

        keys = [f"market_data:tick:option:{ik}" for ik in instrument_keys]
        values = [None] * len(keys)
        try:
            r = await get_redis()
            if r:
                vals = await r.mget(keys)
                values = list(vals) if vals else values
        except Exception:
            pass

        for ik, val in zip(instrument_keys, values):
            if val is not None:
                try:
                    import json
                    result[ik] = json.loads(val)
                except Exception:
                    pass

        return result

    async def rebuild_indices_cache(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for inst_key, info in TRACKED_INDICES.items():
            cached = await cache_get(f"market_data:tick:{info['symbol']}")
            if cached:
                results.append(cached)
            else:
                latest = (
                    self.db.query(MarketData)
                    .filter(MarketData.instrument_key == inst_key)
                    .order_by(desc(MarketData.fetched_at))
                    .first()
                )
                if latest:
                    results.append({
                        "symbol": latest.symbol,
                        "name": latest.name,
                        "instrument_key": latest.instrument_key,
                        "last_price": latest.last_price,
                        "change": latest.change,
                        "change_percent": latest.change_percent,
                        "open_price": latest.open_price,
                        "high_price": latest.high_price,
                        "low_price": latest.low_price,
                        "close_price": latest.close_price,
                        "volume": latest.volume,
                        "source": latest.source,
                        "fetched_at": latest.fetched_at,
                    })
        if results:
            await cache_set(self._cache_key(), results, ttl=30)
        return results

    # ── Redis-backed cache ────────────────────────────────────────────

    def _cache_key(self, suffix: str = "") -> str:
        return f"market_data:{suffix}" if suffix else "market_data:indices"

    async def _get_cached_data(self) -> list[dict[str, Any]]:
        cached = await cache_get(self._cache_key())
        if cached is not None:
            logger.debug("Serving market data from Redis cache")
            return cached

        results: list[dict[str, Any]] = []
        for inst_key, info in TRACKED_INDICES.items():
            latest = (
                self.db.query(MarketData)
                .filter(MarketData.instrument_key == inst_key)
                .order_by(desc(MarketData.fetched_at))
                .first()
            )
            if latest:
                results.append({
                    "symbol": latest.symbol,
                    "name": latest.name,
                    "instrument_key": latest.instrument_key,
                    "last_price": latest.last_price,
                    "change": latest.change,
                    "change_percent": latest.change_percent,
                    "open_price": latest.open_price,
                    "high_price": latest.high_price,
                    "low_price": latest.low_price,
                    "close_price": latest.close_price,
                    "volume": latest.volume,
                    "source": latest.source,
                    "fetched_at": latest.fetched_at,
                })

        if results:
            await cache_set(self._cache_key(), results, ttl=30)
        return results

    # ── FII / DII data ─────────────────────────────────────────────────

    async def _fetch_fii_data(self) -> dict[str, Any] | None:
        cached = await cache_get("market_data:fii")
        if cached is not None:
            return cached

        client = self._get_client()
        if not client:
            return None
        try:
            raw = await client.get_fii_data()
            segments = []
            total_buy = 0.0
            total_sell = 0.0
            for segment_key, records in raw.items():
                if not records:
                    continue
                latest = records[0]
                net = latest["buy_amount"] - latest["sell_amount"]
                total_buy += latest["buy_amount"]
                total_sell += latest["sell_amount"]
                segments.append({
                    "segment": segment_key,
                    "latest": {
                        "time_stamp": latest["time_stamp"],
                        "buy_amount": latest["buy_amount"],
                        "sell_amount": latest["sell_amount"],
                        "buy_contracts": latest["buy_contracts"],
                        "sell_contracts": latest["sell_contracts"],
                        "net_amount": net,
                    },
                })
            result = {
                "segments": segments,
                "total_buy": total_buy,
                "total_sell": total_sell,
                "total_net": total_buy - total_sell,
            }
            await cache_set("market_data:fii", result, ttl=3600)
            return result
        except Exception as e:
            logger.warning("Failed to fetch FII data: %s", e)
            return None

    async def _fetch_dii_data(self) -> dict[str, Any] | None:
        cached = await cache_get("market_data:dii")
        if cached is not None:
            return cached

        client = self._get_client()
        if not client:
            return None
        try:
            raw = await client.get_dii_data()
            records = raw.get("NSE_EQ|CASH", [])
            if not records:
                return None
            latest = records[0]
            buy = latest["buy_amount"]
            sell = latest["sell_amount"]
            result = {
                "total_buy": buy,
                "total_sell": sell,
                "total_net": buy - sell,
            }
            await cache_set("market_data:dii", result, ttl=3600)
            return result
        except Exception as e:
            logger.warning("Failed to fetch DII data: %s", e)
            return None

    # ── Public endpoint ────────────────────────────────────────────────

    async def get_latest_market_data(self) -> dict[str, Any]:
        indices = await self._get_cached_data()

        if not indices:
            logger.info("No cached data — force-fetching from API (one-time)")
            try:
                indices = await self.fetch_and_store_market_data(force=True)
                logger.info("Force-fetch got %d indices", len(indices))
            except Exception as e:
                logger.warning("One-time fetch failed: %s", e)
            if not indices:
                indices = await self._get_cached_data()

        if not indices and await self._should_fetch_live():
            indices = await self.fetch_and_store_market_data()

        statuses = await self.check_market_status()

        fii = await self._fetch_fii_data()
        dii = await self._fetch_dii_data()

        fetched_at = max(i["fetched_at"] for i in indices) if indices else None

        return {
            "status": "success",
            "market_status": statuses,
            "indices": indices,
            "fii": fii,
            "dii": dii,
            "last_updated": fetched_at,
        }
