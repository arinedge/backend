"""add f&o symbols, expiries, instruments tables

Revision ID: 20260527001
Revises: 20260521001
Create Date: 2026-05-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260527001"
down_revision: Union[str, None] = "20260521001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "fno_symbols",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("symbol", sa.String(50), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("segment", sa.String(20), nullable=False),
        sa.Column("exchange", sa.String(10), nullable=False),
        sa.Column("asset_type", sa.String(20), nullable=False),
        sa.Column("underlying_key", sa.String(100), nullable=True),
        sa.Column("lot_size", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("tick_size", sa.Float(), nullable=False, server_default=sa.text("0.05")),
        sa.Column("freeze_quantity", sa.Float(), nullable=True),
        sa.Column("minimum_lot", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("qty_multiplier", sa.Float(), nullable=False, server_default=sa.text("1.0")),
        sa.Column("weekly", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol"),
    )
    op.create_index("ix_fno_symbols_symbol", "fno_symbols", ["symbol"])

    op.create_table(
        "fno_expiries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("symbol_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expiry_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expiry_timestamp", sa.BigInteger(), nullable=False),
        sa.Column("weekly", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["symbol_id"], ["fno_symbols.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_fno_expiries_symbol_id", "fno_expiries", ["symbol_id"])

    op.create_table(
        "fno_instruments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("symbol_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expiry_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("instrument_key", sa.String(100), nullable=False),
        sa.Column("exchange_token", sa.String(50), nullable=False),
        sa.Column("trading_symbol", sa.String(100), nullable=False),
        sa.Column("instrument_type", sa.String(10), nullable=False),
        sa.Column("strike_price", sa.Float(), nullable=True),
        sa.Column("lot_size", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("tick_size", sa.Float(), nullable=False, server_default=sa.text("0.05")),
        sa.Column("freeze_quantity", sa.Float(), nullable=True),
        sa.Column("minimum_lot", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("qty_multiplier", sa.Float(), nullable=False, server_default=sa.text("1.0")),
        sa.Column("asset_type", sa.String(20), nullable=False),
        sa.Column("underlying_type", sa.String(20), nullable=False),
        sa.Column("underlying_symbol", sa.String(50), nullable=False),
        sa.Column("asset_symbol", sa.String(50), nullable=False),
        sa.Column("underlying_key", sa.String(100), nullable=True),
        sa.Column("asset_key", sa.String(100), nullable=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("segment", sa.String(20), nullable=False),
        sa.Column("exchange", sa.String(10), nullable=False),
        sa.Column("weekly", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("instrument_key"),
        sa.ForeignKeyConstraint(["symbol_id"], ["fno_symbols.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["expiry_id"], ["fno_expiries.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_fno_instruments_instrument_key", "fno_instruments", ["instrument_key"])
    op.create_index("ix_fno_instruments_symbol_id", "fno_instruments", ["symbol_id"])
    op.create_index("ix_fno_instruments_expiry_id", "fno_instruments", ["expiry_id"])
    op.create_index("ix_fno_instruments_underlying_symbol", "fno_instruments", ["underlying_symbol"])


def downgrade() -> None:
    op.drop_table("fno_instruments")
    op.drop_table("fno_expiries")
    op.drop_table("fno_symbols")
