"""add referral fields to waitlist_entries

Revision ID: 20260514001
Revises: 20260513001
Create Date: 2026-05-14
"""

from typing import Sequence, Union
import secrets

from alembic import op
import sqlalchemy as sa


revision: str = "20260514001"
down_revision: Union[str, None] = "20260513001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "waitlist_entries",
        sa.Column("referral_code", sa.String(8), nullable=True),
    )
    op.add_column(
        "waitlist_entries",
        sa.Column("referred_by", sa.String(8), nullable=True),
    )
    op.add_column(
        "waitlist_entries",
        sa.Column(
            "referral_signups_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )

    # Generate unique referral codes for all existing rows
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id FROM waitlist_entries WHERE referral_code IS NULL")
    ).fetchall()
    for row in rows:
        code = secrets.token_hex(4)
        while conn.execute(
            sa.text("SELECT 1 FROM waitlist_entries WHERE referral_code = :code"),
            {"code": code},
        ).fetchone():
            code = secrets.token_hex(4)
        conn.execute(
            sa.text("UPDATE waitlist_entries SET referral_code = :code WHERE id = :id"),
            {"code": code, "id": row[0]},
        )

    op.alter_column("waitlist_entries", "referral_code", nullable=False)
    op.create_index(
        op.f("ix_waitlist_entries_referral_code"),
        "waitlist_entries",
        ["referral_code"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_waitlist_entries_referral_code"), table_name="waitlist_entries")
    op.drop_column("waitlist_entries", "referral_signups_count")
    op.drop_column("waitlist_entries", "referred_by")
    op.drop_column("waitlist_entries", "referral_code")
