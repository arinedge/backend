"""add user_sessions, login_audit_events, user role

Revision ID: 2026_07_01_add_auth_tables
Revises: 2026_06_29_add_nexus_option_snapshots
Create Date: 2026-07-01 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "2026_07_01_add_auth_tables"
down_revision: Union[str, None] = "20260629001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add role column to users
    op.add_column("users", sa.Column("role", sa.String(20), server_default="user", nullable=False))

    # Create user_sessions table
    op.create_table(
        "user_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("refresh_token_hash", sa.String(128), nullable=False, unique=True, index=True),
        sa.Column("user_agent", sa.Text, nullable=True),
        sa.Column("ip_hash", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Create login_audit_events table
    op.create_table(
        "login_audit_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("event_type", sa.String(50), nullable=False, index=True),
        sa.Column("ip_hash", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.Text, nullable=True),
        sa.Column("success", sa.Boolean, default=False),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("login_audit_events")
    op.drop_table("user_sessions")
    op.drop_column("users", "role")
