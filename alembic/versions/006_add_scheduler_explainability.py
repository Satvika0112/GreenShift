"""add_scheduler_explainability

Revision ID: 006_add_scheduler_explainability
Revises: 005_add_users_table
Create Date: 2026-09-06 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '006'
down_revision: Union[str, None] = '005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    if 'schedule_decisions' in existing_tables:
        columns = {c['name'] for c in insp.get_columns('schedule_decisions')}
        with op.batch_alter_table('schedule_decisions') as batch_op:
            if 'candidates_evaluated' not in columns:
                batch_op.add_column(sa.Column('candidates_evaluated', sa.Integer(), nullable=True, server_default='0'))
            if 'feasible_candidates_count' not in columns:
                batch_op.add_column(sa.Column('feasible_candidates_count', sa.Integer(), nullable=True, server_default='0'))
            if 'rejection_summary' not in columns:
                batch_op.add_column(sa.Column('rejection_summary', sa.JSON(), nullable=True))
            if 'scheduler_objective' not in columns:
                batch_op.add_column(sa.Column('scheduler_objective', sa.String(), nullable=True, server_default='CARBON_FIRST'))
            if 'deterministic_rank' not in columns:
                batch_op.add_column(sa.Column('deterministic_rank', sa.Integer(), nullable=True, server_default='1'))


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    if 'schedule_decisions' in existing_tables:
        columns = {c['name'] for c in insp.get_columns('schedule_decisions')}
        with op.batch_alter_table('schedule_decisions') as batch_op:
            if 'deterministic_rank' in columns:
                batch_op.drop_column('deterministic_rank')
            if 'scheduler_objective' in columns:
                batch_op.drop_column('scheduler_objective')
            if 'rejection_summary' in columns:
                batch_op.drop_column('rejection_summary')
            if 'feasible_candidates_count' in columns:
                batch_op.drop_column('feasible_candidates_count')
            if 'candidates_evaluated' in columns:
                batch_op.drop_column('candidates_evaluated')
