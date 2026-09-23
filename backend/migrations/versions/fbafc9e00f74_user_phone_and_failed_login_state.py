"""user phone and failed-login state

Revision ID: fbafc9e00f74
Revises: 9e47091dbc5f
Create Date: 2026-09-07 11:58:53.264148
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'fbafc9e00f74'
down_revision = '9e47091dbc5f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('phone', sa.String(length=32), nullable=True))
        # server_default so the column can be added to a table that already has
        # accounts in it -- a NOT NULL column with no default cannot be.
        batch_op.add_column(
            sa.Column('failed_login_count', sa.Integer(), nullable=False, server_default='0')
        )
        batch_op.add_column(sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('last_login_at')
        batch_op.drop_column('locked_until')
        batch_op.drop_column('failed_login_count')
        batch_op.drop_column('phone')
