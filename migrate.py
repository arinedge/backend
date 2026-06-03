"""Add missing columns safely with individual try/except per column."""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import text

from app.database import engine
from app.utils.logger import setup_logging, get_logger

setup_logging()
logger = get_logger("migrate")


def column_exists(conn, col: str) -> bool:
    result = conn.execute(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name='users' AND column_name=:col"
        ),
        {"col": col},
    )
    return result.scalar() is not None


def migrate():
    logger.info("Running migration: add missing columns")

    with engine.connect() as conn:
        columns = {
            "is_logged_in": "BOOLEAN NOT NULL DEFAULT FALSE",
            "last_login_at": "TIMESTAMPTZ",
            "login_count": "INTEGER NOT NULL DEFAULT 0",
        }

        for col, dtype in columns.items():
            if column_exists(conn, col):
                logger.info("Column '%s' already exists, skipping", col)
            else:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} {dtype}"))
                logger.info("Added column '%s'", col)

        conn.commit()

    logger.info("Migration complete.")


if __name__ == "__main__":
    migrate()
