"""add stock compare cache

Revision ID: 20260617001
Revises: 8659ed22bb8b
Create Date: 2026-06-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260617001"
down_revision: Union[str, None] = "8659ed22bb8b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stock_compare_cache",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("comparison_slug", sa.String(length=200), nullable=False),
        sa.Column("stock1_slug", sa.String(length=100), nullable=False),
        sa.Column("stock2_slug", sa.String(length=100), nullable=False),
        sa.Column("request_payload", postgresql.JSONB(), nullable=True),
        sa.Column("response_payload", postgresql.JSONB(), nullable=True),
        sa.Column("response_status", sa.String(length=20), nullable=False, server_default="success"),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("comparison_slug"),
    )
    op.create_index("ix_stock_compare_cache_comparison_slug", "stock_compare_cache", ["comparison_slug"])
    op.create_index("ix_stock_compare_cache_stock1_slug", "stock_compare_cache", ["stock1_slug"])
    op.create_index("ix_stock_compare_cache_stock2_slug", "stock_compare_cache", ["stock2_slug"])
    op.create_index("ix_stock_compare_cache_expires_at", "stock_compare_cache", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_stock_compare_cache_expires_at", table_name="stock_compare_cache")
    op.drop_index("ix_stock_compare_cache_stock2_slug", table_name="stock_compare_cache")
    op.drop_index("ix_stock_compare_cache_stock1_slug", table_name="stock_compare_cache")
    op.drop_index("ix_stock_compare_cache_comparison_slug", table_name="stock_compare_cache")
    op.drop_table("stock_compare_cache")

