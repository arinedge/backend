import csv
import json
import os
import traceback
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.models.fno import FnoSymbol, FnoExpiry, FnoInstrument
from app.utils.logger import get_logger

logger = get_logger(__name__)

FO_SEGMENTS = {"NSE_FO", "BSE_FO", "NCD_FO", "BCD_FO", "MCX_FO"}


class FnoService:

    @staticmethod
    def load_instruments_from_json(db: Session, json_path: str) -> dict[str, int]:
        with open(json_path) as f:
            raw_items = json.load(f)

        fo_items = [item for item in raw_items if item.get("segment") in FO_SEGMENTS]

        symbols_map: dict[str, FnoSymbol] = {}
        expiry_map: dict[tuple[str, int], FnoExpiry] = {}
        created_symbols = 0
        created_expiries = 0
        created_instruments = 0
        skipped = 0

        existing_keys = set(
            row[0] for row in db.execute(select(FnoInstrument.instrument_key)).all()
        )

        for item in fo_items:
            underlying = item.get("underlying_symbol", "")
            if not underlying:
                skipped += 1
                continue

            inst_key = item.get("instrument_key", "")
            if inst_key in existing_keys:
                skipped += 1
                continue

            if underlying not in symbols_map:
                symbol = db.execute(
                    select(FnoSymbol).where(FnoSymbol.symbol == underlying)
                ).scalar_one_or_none()
                if not symbol:
                    symbol = FnoSymbol(
                        symbol=underlying,
                        name=item.get("name", underlying),
                        segment=item.get("segment", ""),
                        exchange=item.get("exchange", ""),
                        asset_type=item.get("asset_type", ""),
                        underlying_key=item.get("underlying_key"),
                        lot_size=item.get("lot_size", 1),
                        tick_size=item.get("tick_size", 0.05),
                        freeze_quantity=item.get("freeze_quantity"),
                        minimum_lot=item.get("minimum_lot", 1),
                        qty_multiplier=item.get("qty_multiplier", 1.0),
                        weekly=item.get("weekly", False),
                    )
                    db.add(symbol)
                    db.flush()
                    created_symbols += 1
                symbols_map[underlying] = symbol

            symbol = symbols_map[underlying]
            expiry_ts = item.get("expiry", 0)
            expiry_key = (underlying, expiry_ts)

            if expiry_key not in expiry_map:
                expiry_obj = db.execute(
                    select(FnoExpiry).where(
                        FnoExpiry.symbol_id == symbol.id,
                        FnoExpiry.expiry_timestamp == expiry_ts,
                    )
                ).scalar_one_or_none()
                if not expiry_obj:
                    expiry_obj = FnoExpiry(
                        symbol_id=symbol.id,
                        expiry_date=datetime.fromtimestamp(expiry_ts / 1000, tz=timezone.utc),
                        expiry_timestamp=expiry_ts,
                        weekly=item.get("weekly", False),
                    )
                    db.add(expiry_obj)
                    db.flush()
                    created_expiries += 1
                expiry_map[expiry_key] = expiry_obj

            expiry = expiry_map[expiry_key]

            instrument = FnoInstrument(
                symbol_id=symbol.id,
                expiry_id=expiry.id,
                instrument_key=inst_key,
                exchange_token=item.get("exchange_token", ""),
                trading_symbol=item.get("trading_symbol", ""),
                instrument_type=item.get("instrument_type", ""),
                strike_price=item.get("strike_price"),
                lot_size=item.get("lot_size", 1),
                tick_size=item.get("tick_size", 0.05),
                freeze_quantity=item.get("freeze_quantity"),
                minimum_lot=item.get("minimum_lot", 1),
                qty_multiplier=item.get("qty_multiplier", 1.0),
                asset_type=item.get("asset_type", ""),
                underlying_type=item.get("underlying_type", ""),
                underlying_symbol=underlying,
                asset_symbol=item.get("asset_symbol", ""),
                underlying_key=item.get("underlying_key"),
                asset_key=item.get("asset_key"),
                name=item.get("name", ""),
                segment=item.get("segment", ""),
                exchange=item.get("exchange", ""),
                weekly=item.get("weekly", False),
            )
            db.add(instrument)
            created_instruments += 1

            if (created_instruments + skipped) % 5000 == 0:
                db.commit()
                logger.info(
                    "Progress: %d instruments processed (%d created, %d skipped)",
                    created_instruments + skipped, created_instruments, skipped,
                )

        db.commit()
        logger.info(
            "Import complete: %d symbols, %d expiries, %d instruments created (%d skipped)",
            created_symbols, created_expiries, created_instruments, skipped,
        )
        return {
            "symbols": created_symbols,
            "expiries": created_expiries,
            "instruments": created_instruments,
            "skipped": skipped,
        }

    @staticmethod
    def get_symbols(db: Session, search: str | None = None, segment: str | None = None, asset_type: str | None = None, nifty50: bool = False) -> list[FnoSymbol]:
        query = select(FnoSymbol).where(FnoSymbol.is_active == True)
        if search:
            query = query.where(FnoSymbol.symbol.ilike(f"%{search}%"))
        if segment:
            query = query.where(FnoSymbol.segment == segment)
        if asset_type:
            query = query.where(FnoSymbol.asset_type == asset_type)
        if nifty50:
            nifty_symbols = _load_nifty50_symbols()
            query = query.where(FnoSymbol.symbol.in_(nifty_symbols))
        query = query.order_by(FnoSymbol.symbol)
        return list(db.execute(query).scalars().all())

    @staticmethod
    def get_expiries(db: Session, symbol_id: str) -> list[FnoExpiry]:
        query = (
            select(FnoExpiry)
            .where(FnoExpiry.symbol_id == symbol_id, FnoExpiry.is_active == True)
            .order_by(FnoExpiry.expiry_date)
        )
        return list(db.execute(query).scalars().all())

    @staticmethod
    def get_expiries_by_symbol_name(db: Session, symbol: str) -> list[FnoExpiry]:
        symbol_obj = db.execute(
            select(FnoSymbol).where(FnoSymbol.symbol == symbol, FnoSymbol.is_active == True)
        ).scalar_one_or_none()
        if not symbol_obj:
            return []
        return FnoService.get_expiries(db, str(symbol_obj.id))

    @staticmethod
    def get_option_chain(
        db: Session, underlying_symbol: str, expiry_timestamp: int
    ) -> tuple[list[FnoInstrument], datetime | None, int | None]:
        symbol = db.execute(
            select(FnoSymbol).where(
                FnoSymbol.symbol == underlying_symbol,
                FnoSymbol.is_active == True,
            )
        ).scalar_one_or_none()
        if not symbol:
            return [], None, None

        expiry = db.execute(
            select(FnoExpiry).where(
                FnoExpiry.symbol_id == symbol.id,
                FnoExpiry.expiry_timestamp == expiry_timestamp,
                FnoExpiry.is_active == True,
            )
        ).scalar_one_or_none()
        if not expiry:
            return [], None, None

        instruments = list(
            db.execute(
                select(FnoInstrument).where(
                    FnoInstrument.expiry_id == expiry.id,
                    FnoInstrument.underlying_symbol == underlying_symbol,
                    FnoInstrument.instrument_type.in_(["CE", "PE"]),
                    FnoInstrument.is_active == True,
                ).order_by(FnoInstrument.strike_price)
            ).scalars().all()
        )
        return instruments, expiry.expiry_date, expiry.expiry_timestamp

    @staticmethod
    def get_instrument_by_key(db: Session, instrument_key: str) -> FnoInstrument | None:
        return db.execute(
            select(FnoInstrument).where(FnoInstrument.instrument_key == instrument_key)
        ).scalar_one_or_none()

    @staticmethod
    def get_stats(db: Session) -> dict:
        symbols = db.execute(select(func.count(FnoSymbol.id))).scalar()
        expiries = db.execute(select(func.count(FnoExpiry.id))).scalar()
        instruments = db.execute(select(func.count(FnoInstrument.id))).scalar()
        return {
            "symbols": symbols,
            "expiries": expiries,
            "instruments": instruments,
        }

NIFTY50_CSV = os.path.join(os.path.dirname(__file__), "..", "..", "support_files", "MW-NIFTY-50-27-May-2026.csv")
_ALWAYS_INCLUDE = {"NIFTY", "BANKNIFTY", "SENSEX"}
_NIFTY50_SYMBOLS_CACHE: frozenset[str] | None = None


def _load_nifty50_symbols() -> frozenset[str]:
    global _NIFTY50_SYMBOLS_CACHE
    if _NIFTY50_SYMBOLS_CACHE is not None:
        return _NIFTY50_SYMBOLS_CACHE
    symbols = set(_ALWAYS_INCLUDE)
    try:
        with open(NIFTY50_CSV, newline="") as f:
            reader = csv.reader(f)
            for _ in range(3):  # skip header rows
                try:
                    next(reader)
                except StopIteration:
                    break
            for row in reader:
                if row and row[0].strip():
                    sym = row[0].strip().strip('"')
                    if sym.upper() != "NIFTY 50":
                        symbols.add(sym.strip())
    except Exception as e:
        logger.warning("Failed to load Nifty 50 CSV: %s", e)
    _NIFTY50_SYMBOLS_CACHE = frozenset(symbols)
    logger.info("Loaded %d Nifty 50 symbols", len(symbols))
    return _NIFTY50_SYMBOLS_CACHE
