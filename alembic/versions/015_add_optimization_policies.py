"""add_optimization_policies

Revision ID: 015
Revises: 014
Create Date: 2026-09-15 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '015'
down_revision: Union[str, None] = '014'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    if 'optimization_policies' not in existing_tables:
        op.create_table(
            'optimization_policies',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('tenant_id', sa.String(), nullable=False),
            sa.Column('policy', sa.String(20), nullable=False, server_default='CARBON_FIRST'),
            sa.Column('carbon_tolerance_pct', sa.Float(), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('updated_by_user_id', sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['updated_by_user_id'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('tenant_id', name='uq_optimization_policies_tenant_id'),
            sa.CheckConstraint(
                "policy IN ('CARBON_FIRST', 'COST_FIRST', 'CARBON_CONSTRAINED')",
                name='ck_optimization_policies_policy_valid',
            ),
            sa.CheckConstraint(
                "carbon_tolerance_pct IS NULL OR (carbon_tolerance_pct >= 0 AND carbon_tolerance_pct <= 100)",
                name='ck_optimization_policies_tolerance_range',
            ),
        )
        op.create_index('ix_optimization_policies_tenant_id', 'optimization_policies', ['tenant_id'])

    # schedule_decisions.carbon_tolerance_pct — only meaningful when that
    # row's scheduler_objective == 'CARBON_CONSTRAINED'.
    sd_columns = {c['name'] for c in insp.get_columns('schedule_decisions')}
    if 'carbon_tolerance_pct' not in sd_columns:
        op.add_column('schedule_decisions', sa.Column('carbon_tolerance_pct', sa.Float(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    sd_columns = {c['name'] for c in insp.get_columns('schedule_decisions')}
    if 'carbon_tolerance_pct' in sd_columns:
        op.drop_column('schedule_decisions', 'carbon_tolerance_pct')

    if 'optimization_policies' in existing_tables:
        op.drop_index('ix_optimization_policies_tenant_id', table_name='optimization_policies')
        op.drop_table('optimization_policies')
