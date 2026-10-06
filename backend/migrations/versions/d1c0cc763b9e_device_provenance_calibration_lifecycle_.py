"""device provenance, calibration lifecycle, research recording

Revision ID: d1c0cc763b9e
Revises: 75b9b8c873bd
Create Date: 2026-10-06 15:26:40.512141

Enum columns are *not* re-typed here. Autogenerate proposed converting
audit_logs.action / devices.kind / sessions.mode from VARCHAR to Enum, which
is only an artefact of SQLite storing enums as VARCHAR; on PostgreSQL the
native types already exist and only need new values (ALTER TYPE ADD VALUE).
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'd1c0cc763b9e'
down_revision = '75b9b8c873bd'
branch_labels = None
depends_on = None

_NEW_VALUES = {
    "auditaction": ("DEVICE_REGISTERED", "DEVICE_KEY_REVOKED", "CALIBRATION_INVALIDATED",
                    "MARKER_CREATED", "RESEARCH_RECORDING_STARTED"),
    "devicekind": ("UNVERIFIED",),
    "sessionmode": ("UNVERIFIED",),
}


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            for type_name, values in _NEW_VALUES.items():
                for value in values:
                    op.execute(f"ALTER TYPE {type_name} ADD VALUE IF NOT EXISTS '{value}'")
        sa.Enum("STANDARD", "RESEARCH", name="recordingmode").create(bind, checkfirst=True)

    op.create_table('session_markers',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('session_id', sa.Integer(), nullable=False),
    sa.Column('t_session', sa.Float(), nullable=True),
    sa.Column('server_ts', sa.DateTime(timezone=True), nullable=False),
    sa.Column('label', sa.String(length=60), nullable=False),
    sa.Column('note', sa.String(length=300), nullable=True),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('session_markers', schema=None) as batch_op:
        batch_op.create_index('ix_marker_session_t', ['session_id', 't_session'], unique=False)

    with op.batch_alter_table('device_calibrations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('sequence', sa.Integer(), server_default='1', nullable=False))
        batch_op.add_column(sa.Column('t_start', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('t_end', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('invalidated_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('invalidation_reason', sa.String(length=200), nullable=True))

    with op.batch_alter_table('devices', schema=None) as batch_op:
        batch_op.add_column(sa.Column('key_hash', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('verified_hardware', sa.Boolean(), server_default=sa.false(), nullable=False))
        batch_op.add_column(sa.Column('registered_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('registered_by', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('hardware_notes', sa.String(length=500), nullable=True))
        batch_op.create_foreign_key('fk_devices_registered_by_users', 'users', ['registered_by'], ['id'], ondelete='SET NULL')

    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('recording_mode', sa.Enum('STANDARD', 'RESEARCH', name='recordingmode', create_type=False), server_default='STANDARD', nullable=False))
        batch_op.add_column(sa.Column('research_protocol', sa.JSON(), nullable=True))

    # Existing rows labelled HARDWARE/LIVE predate device authentication: they
    # only omitted the simulated flag. Re-label them honestly.
    op.execute("UPDATE devices SET kind = 'UNVERIFIED' WHERE kind = 'HARDWARE'")
    op.execute("UPDATE sessions SET mode = 'UNVERIFIED' WHERE mode = 'LIVE'")


def downgrade() -> None:
    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.drop_column('research_protocol')
        batch_op.drop_column('recording_mode')

    with op.batch_alter_table('devices', schema=None) as batch_op:
        batch_op.drop_constraint('fk_devices_registered_by_users', type_='foreignkey')
        batch_op.drop_column('hardware_notes')
        batch_op.drop_column('registered_by')
        batch_op.drop_column('registered_at')
        batch_op.drop_column('verified_hardware')
        batch_op.drop_column('key_hash')

    with op.batch_alter_table('device_calibrations', schema=None) as batch_op:
        batch_op.drop_column('invalidation_reason')
        batch_op.drop_column('invalidated_at')
        batch_op.drop_column('t_end')
        batch_op.drop_column('t_start')
        batch_op.drop_column('sequence')

    with op.batch_alter_table('session_markers', schema=None) as batch_op:
        batch_op.drop_index('ix_marker_session_t')
    op.drop_table('session_markers')
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TYPE IF EXISTS recordingmode")
    # PostgreSQL cannot drop enum values; UNVERIFIED etc. remain defined.
