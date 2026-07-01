"""add symbol and company_name to stock_info

Revision ID: 20260617003
Revises: 20260617002
Create Date: 2026-06-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260617003"
down_revision: Union[str, None] = "20260617002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("stock_info", sa.Column("symbol", sa.String(50), nullable=True))
    op.add_column("stock_info", sa.Column("company_name", sa.String(500), nullable=True))

    op.execute("""
        UPDATE stock_info SET
            symbol = CASE
                WHEN ticker LIKE '%.NS' THEN left(ticker, length(ticker) - 3)
                ELSE ticker
            END,
            company_name = COALESCE(NULLIF(data->>'shortName', ''), NULLIF(data->>'longName', ''))
        WHERE data IS NOT NULL
    """)


def downgrade() -> None:
    op.drop_column("stock_info", "company_name")
    op.drop_column("stock_info", "symbol")
