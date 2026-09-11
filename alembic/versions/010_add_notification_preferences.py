"""add_notification_preferences

Revision ID: 010
Revises: 009
Create Date: 2026-09-11 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '010'
down_revision: Union[str, None] = '009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    if 'notification_preferences' not in existing_tables:
        op.create_table(
            'notification_preferences',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('email_workload', sa.Boolean(), nullable=False, server_default='1'),
            sa.Column('email_scheduling', sa.Boolean(), nullable=False, server_default='1'),
            sa.Column('email_approval', sa.Boolean(), nullable=False, server_default='1'),
            sa.Column('email_execution', sa.Boolean(), nullable=False, server_default='1'),
            sa.Column('email_system', sa.Boolean(), nullable=False, server_default='1'),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('user_id', name='uq_notification_preferences_user_id'),
        )
        op.create_index(
            'ix_notification_preferences_user_id', 'notification_preferences', ['user_id'], unique=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    if 'notification_preferences' in existing_tables:
        op.drop_table('notification_preferences')
