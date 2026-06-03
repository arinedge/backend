"""add waitlist_entries table

Revision ID: 20260513001
Revises: (previous revision)
Create Date: 2026-05-13
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260513001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "waitlist_entries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("trading_experience", sa.String(50), nullable=False),
        sa.Column("primary_interest", sa.String(50), nullable=False),
        sa.Column("queue_position", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_waitlist_entries_email"), "waitlist_entries", ["email"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_waitlist_entries_email"), table_name="waitlist_entries")
    op.drop_table("waitlist_entries")
