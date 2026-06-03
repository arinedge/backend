"""add_greeks_iv_to_market_data

Revision ID: 8659ed22bb8b
Revises: 20260527001
Create Date: 2026-05-27 13:25:17.761054
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '8659ed22bb8b'
down_revision: Union[str, None] = '20260527001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('market_data', sa.Column('iv', sa.Float(), nullable=True))
    op.add_column('market_data', sa.Column('delta', sa.Float(), nullable=True))
    op.add_column('market_data', sa.Column('gamma', sa.Float(), nullable=True))
    op.add_column('market_data', sa.Column('theta', sa.Float(), nullable=True))
    op.add_column('market_data', sa.Column('vega', sa.Float(), nullable=True))
    op.add_column('market_data', sa.Column('rho', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('market_data', 'rho')
    op.drop_column('market_data', 'vega')
    op.drop_column('market_data', 'theta')
    op.drop_column('market_data', 'gamma')
    op.drop_column('market_data', 'delta')
    op.drop_column('market_data', 'iv')
