"""add nexus_expiry_intel, nexus_anomaly_scores, nexus_signal_instances, stock_analysis tables

Revision ID: 20260629002
Revises: 20260629001
Create Date: 2026-06-29
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "20260629002"
down_revision: Union[str, None] = "20260629001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "nexus_expiry_intel",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("underlying_symbol", sa.String(length=20), nullable=False),
        sa.Column("max_pain", sa.Numeric(12, 2), nullable=True),
        sa.Column("days_to_expiry", sa.Integer(), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_nei_sym", "nexus_expiry_intel", ["underlying_symbol"])

    op.create_table(
        "nexus_anomaly_scores",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("signal_family", sa.String(length=50), nullable=True),
        sa.Column("metric_name", sa.String(length=100), nullable=True),
        sa.Column("anomaly_score", sa.Numeric(8, 4), nullable=True),
        sa.Column("zscore", sa.Numeric(8, 4), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_nas_sym", "nexus_anomaly_scores", ["symbol"])

    op.create_table(
        "nexus_signal_instances",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("underlying_symbol", sa.String(length=20), nullable=False),
        sa.Column("signal_code", sa.String(length=50), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=True),
        sa.Column("confidence", sa.Numeric(8, 4), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("event_time", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_nsi_sym", "nexus_signal_instances", ["underlying_symbol"])

    op.create_table(
        "stock_analysis",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ticker", sa.String(length=20), nullable=False),
        sa.Column("summary", JSONB(), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_sa_ticker", "stock_analysis", ["ticker"])


def downgrade() -> None:
    op.drop_index("idx_nsi_sym", table_name="nexus_signal_instances")
    op.drop_table("nexus_signal_instances")

    op.drop_index("idx_nas_sym", table_name="nexus_anomaly_scores")
    op.drop_table("nexus_anomaly_scores")

    op.drop_index("idx_nei_sym", table_name="nexus_expiry_intel")
    op.drop_table("nexus_expiry_intel")

    op.drop_index("idx_sa_ticker", table_name="stock_analysis")
    op.drop_table("stock_analysis")
