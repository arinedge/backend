"""add nexus_option_snapshots table

Revision ID: 20260629001
Revises: 20260617003
Create Date: 2026-06-29
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "20260629001"
down_revision: Union[str, None] = "20260617003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "nexus_option_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("underlying_symbol", sa.String(length=20), nullable=False),
        sa.Column("snapshot_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("spot_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("expiry", sa.Date(), nullable=True),
        sa.Column("net_gamma", sa.Numeric(16, 4), nullable=True),
        sa.Column("total_gamma", sa.Numeric(16, 4), nullable=True),
        sa.Column("strike_details", JSONB(), nullable=True),
        sa.Column("gamma_flip_points", JSONB(), nullable=True),
        sa.Column("strike_count", sa.Integer(), nullable=True),
        sa.Column("stress_tier", sa.String(length=20), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_nopt_sym", "nexus_option_snapshots", ["underlying_symbol"])


def downgrade() -> None:
    op.drop_index("idx_nopt_sym", table_name="nexus_option_snapshots")
    op.drop_table("nexus_option_snapshots")
