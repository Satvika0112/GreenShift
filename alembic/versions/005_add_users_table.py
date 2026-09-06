"""add_users_table

Revision ID: 005_add_users_table
Revises: 004_add_data_integrity_constraints
Create Date: 2026-09-06 17:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '005_add_users_table'
down_revision: Union[str, None] = '004_add_data_integrity_constraints'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    if 'users' not in existing_tables:
        op.create_table(
            'users',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('username', sa.String(length=50), nullable=False),
            sa.Column('email', sa.String(length=255), nullable=False),
            sa.Column('hashed_password', sa.String(length=255), nullable=False),
            sa.Column('role', sa.Enum('ADMIN', 'TEAM_LEAD', 'OPERATOR', 'VIEWER', name='userrole'), nullable=False),
            sa.Column('team_id', sa.String(), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint("role IN ('ADMIN', 'TEAM_LEAD', 'OPERATOR', 'VIEWER')", name='ck_users_role_valid'),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('ix_users_username', 'users', ['username'], unique=True)
        op.create_index('ix_users_email', 'users', ['email'], unique=True)
        op.create_index('ix_users_role', 'users', ['role'], unique=False)
        op.create_index('ix_users_team_id', 'users', ['team_id'], unique=False)
        op.create_index('ix_users_created_at', 'users', ['created_at'], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    if 'users' in existing_tables:
        op.drop_index('ix_users_created_at', table_name='users')
        op.drop_index('ix_users_team_id', table_name='users')
        op.drop_index('ix_users_role', table_name='users')
        op.drop_index('ix_users_email', table_name='users')
        op.drop_index('ix_users_username', table_name='users')
        op.drop_table('users')
