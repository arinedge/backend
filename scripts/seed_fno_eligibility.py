#!/usr/bin/env python3
"""Seed fno_available flag in stock_info.data for all active F&O symbols."""

import sys
import json

from sqlalchemy import create_engine, text

from app.config import get_settings


def main():
    settings = get_settings()
    engine = create_engine(settings.DATABASE_URL)

    with engine.connect() as conn:
        result = conn.execute(text("SELECT symbol FROM fno_symbols WHERE is_active = true"))
        symbols = [row[0] for row in result]

        updated = 0
        for symbol in symbols:
            ticker = f"{symbol}.NS"
            row = conn.execute(
                text("SELECT id, data FROM stock_info WHERE ticker = :ticker"),
                {"ticker": ticker},
            ).fetchone()

            if row is None:
                continue

            stock_id, data = row
            if data and data.get("fno_available") is True:
                continue

            conn.execute(
                text(
                    "UPDATE stock_info SET data = jsonb_set(COALESCE(data::jsonb, '{}'::jsonb), '{fno_available}', 'true'::jsonb)::json WHERE id = :id"
                ),
                {"id": stock_id},
            )
            updated += 1

        conn.commit()

    print(f"Updated {updated} stocks with fno_available = true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
