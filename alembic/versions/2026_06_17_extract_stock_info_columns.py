"""extract stock info columns from data JSON

Revision ID: 20260617002
Revises: 20260617001
Create Date: 2026-06-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260617002"
down_revision: Union[str, None] = "20260617001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("stock_info", sa.Column("sector", sa.String(200), nullable=True))
    op.add_column("stock_info", sa.Column("industry", sa.String(200), nullable=True))
    op.add_column("stock_info", sa.Column("market_cap", sa.Float(), nullable=True))
    op.add_column("stock_info", sa.Column("trailing_pe", sa.Float(), nullable=True))
    op.add_column("stock_info", sa.Column("forward_pe", sa.Float(), nullable=True))
    op.add_column("stock_info", sa.Column("price_to_book", sa.Float(), nullable=True))
    op.add_column("stock_info", sa.Column("dividend_yield", sa.Float(), nullable=True))
    op.add_column("stock_info", sa.Column("roe", sa.Float(), nullable=True))
    op.add_column("stock_info", sa.Column("roa", sa.Float(), nullable=True))
    op.add_column("stock_info", sa.Column("profit_margins", sa.Float(), nullable=True))
    op.add_column("stock_info", sa.Column("revenue_growth", sa.Float(), nullable=True))
    op.add_column("stock_info", sa.Column("earnings_growth", sa.Float(), nullable=True))
    op.add_column("stock_info", sa.Column("eps", sa.Float(), nullable=True))
    op.add_column("stock_info", sa.Column("forward_eps", sa.Float(), nullable=True))
    op.add_column("stock_info", sa.Column("description", sa.Text(), nullable=True))
    op.create_index("ix_stock_info_sector", "stock_info", ["sector"])
    op.create_index("ix_stock_info_industry", "stock_info", ["industry"])

    op.execute("""
        UPDATE stock_info SET
            sector = data->>'sector',
            industry = data->>'industry',
            market_cap = CAST(NULLIF(data->>'marketCap', '') AS FLOAT),
            trailing_pe = CAST(NULLIF(data->>'trailingPE', '') AS FLOAT),
            forward_pe = CAST(NULLIF(data->>'forwardPE', '') AS FLOAT),
            price_to_book = CAST(NULLIF(data->>'priceToBook', '') AS FLOAT),
            dividend_yield = CAST(NULLIF(data->>'dividendYield', '') AS FLOAT),
            roe = CAST(NULLIF(data->>'returnOnEquity', '') AS FLOAT),
            roa = CAST(NULLIF(data->>'returnOnAssets', '') AS FLOAT),
            profit_margins = CAST(NULLIF(data->>'profitMargins', '') AS FLOAT),
            revenue_growth = CAST(NULLIF(data->>'revenueGrowth', '') AS FLOAT),
            earnings_growth = CAST(NULLIF(data->>'earningsGrowth', '') AS FLOAT),
            eps = CAST(NULLIF(data->>'trailingEps', '') AS FLOAT),
            forward_eps = CAST(NULLIF(data->>'forwardEps', '') AS FLOAT),
            description = data->>'longBusinessSummary'
        WHERE data IS NOT NULL
    """)


def downgrade() -> None:
    op.drop_index("ix_stock_info_industry", table_name="stock_info")
    op.drop_index("ix_stock_info_sector", table_name="stock_info")
    op.drop_column("stock_info", "forward_eps")
    op.drop_column("stock_info", "eps")
    op.drop_column("stock_info", "earnings_growth")
    op.drop_column("stock_info", "revenue_growth")
    op.drop_column("stock_info", "profit_margins")
    op.drop_column("stock_info", "roa")
    op.drop_column("stock_info", "roe")
    op.drop_column("stock_info", "dividend_yield")
    op.drop_column("stock_info", "price_to_book")
    op.drop_column("stock_info", "forward_pe")
    op.drop_column("stock_info", "trailing_pe")
    op.drop_column("stock_info", "market_cap")
    op.drop_column("stock_info", "industry")
    op.drop_column("stock_info", "sector")
    op.drop_column("stock_info", "description")
