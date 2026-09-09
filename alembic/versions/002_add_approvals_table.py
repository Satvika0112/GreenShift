"""add_approvals_table

Revision ID: 002_add_approvals_table
Revises: 001_initial_postgresql_schema
Create Date: 2026-09-06 10:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '002'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    # ─── Table: approvals ─────────────────────────────────────────
    if 'approvals' not in existing_tables:
        op.create_table(
            'approvals',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('job_id', sa.String(), nullable=False),
            sa.Column('schedule_decision_id', sa.Integer(), nullable=False),
            sa.Column('decision', sa.String(), nullable=False),
            sa.Column('reason', sa.Text(), nullable=True),
            sa.Column('approved_by', sa.String(), nullable=True, server_default='admin'),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['job_id'], ['jobs.job_id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['schedule_decision_id'], ['schedule_decisions.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('ix_approvals_job_id', 'approvals', ['job_id'], unique=False)
        op.create_index('ix_approvals_schedule_decision_id', 'approvals', ['schedule_decision_id'], unique=False)
        op.create_index('ix_approvals_decision', 'approvals', ['decision'], unique=False)
        op.create_index('ix_approvals_created_at', 'approvals', ['created_at'], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    if 'approvals' in existing_tables:
        op.drop_index('ix_approvals_created_at', table_name='approvals')
        op.drop_index('ix_approvals_decision', table_name='approvals')
        op.drop_index('ix_approvals_schedule_decision_id', table_name='approvals')
        op.drop_index('ix_approvals_job_id', table_name='approvals')
        op.drop_table('approvals')
