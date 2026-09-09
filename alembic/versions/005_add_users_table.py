"""add_users_table

Revision ID: 005_add_users_table
Revises: 004_add_data_integrity_constraints
Create Date: 2026-09-06 17:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '005'
down_revision: Union[str, None] = '004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


USER_ROLE_VALUES = (
    'PLATFORM_ADMIN', 'COMPANY_ADMIN', 'COMPANY_USER', 'ADMIN',
    'TEAM_LEAD', 'OPERATOR', 'USER', 'VIEWER',
)


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
            sa.Column('role', sa.Enum(*USER_ROLE_VALUES, name='userrole'), nullable=False),
            sa.Column('approval_status', sa.String(length=20), nullable=False, server_default='APPROVED'),
            sa.Column('team_id', sa.String(), nullable=True),
            sa.Column('tenant_id', sa.String(), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint(
                "role IN ('PLATFORM_ADMIN', 'COMPANY_ADMIN', 'COMPANY_USER', 'ADMIN', 'TEAM_LEAD', 'OPERATOR', 'USER', 'VIEWER')",
                name='ck_users_role_valid',
            ),
            sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('ix_users_username', 'users', ['username'], unique=True)
        op.create_index('ix_users_email', 'users', ['email'], unique=True)
        op.create_index('ix_users_role', 'users', ['role'], unique=False)
        op.create_index('ix_users_approval_status', 'users', ['approval_status'], unique=False)
        op.create_index('ix_users_team_id', 'users', ['team_id'], unique=False)
        op.create_index('ix_users_tenant_id', 'users', ['tenant_id'], unique=False)
        op.create_index('ix_users_created_at', 'users', ['created_at'], unique=False)
        existing_tables.add('users')

    # ─── Table: api_keys (depends on the userrole enum created above) ──
    if 'api_keys' not in existing_tables:
        op.create_table(
            'api_keys',
            sa.Column('id', sa.String(), nullable=False),
            sa.Column('key_hash', sa.String(), nullable=False),
            sa.Column('tenant_id', sa.String(), nullable=False),
            sa.Column('role', sa.Enum(*USER_ROLE_VALUES, name='userrole'), nullable=False, server_default='OPERATOR'),
            sa.Column('label', sa.String(), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('last_used', sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('key_hash'),
        )
        op.create_index('ix_api_keys_tenant_id', 'api_keys', ['tenant_id'], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    if 'api_keys' in existing_tables:
        op.drop_index('ix_api_keys_tenant_id', table_name='api_keys')
        op.drop_table('api_keys')

    if 'users' in existing_tables:
        op.drop_index('ix_users_created_at', table_name='users')
        op.drop_index('ix_users_tenant_id', table_name='users')
        op.drop_index('ix_users_team_id', table_name='users')
        op.drop_index('ix_users_approval_status', table_name='users')
        op.drop_index('ix_users_role', table_name='users')
        op.drop_index('ix_users_email', table_name='users')
        op.drop_index('ix_users_username', table_name='users')
        op.drop_table('users')
