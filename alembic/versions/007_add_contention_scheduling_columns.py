"""add_contention_scheduling_columns

Revision ID: 007_add_contention_scheduling_columns
Revises: 006_add_scheduler_explainability
Create Date: 2026-09-09 00:00:00.000000

Brings alembic head to parity with app.shared.models.ScheduleDecisionORM
(ADR-006 batch/contention-aware scheduling fields) which had previously
only been applied via SQLAlchemy create_all(), never through Alembic.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '007'
down_revision: Union[str, None] = '006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    if 'schedule_decisions' in existing_tables:
        columns = {c['name'] for c in insp.get_columns('schedule_decisions')}
        with op.batch_alter_table('schedule_decisions') as batch_op:
            if 'candidates_json' not in columns:
                batch_op.add_column(sa.Column('candidates_json', sa.JSON(), nullable=True))
            if 'rejected_candidates_json' not in columns:
                batch_op.add_column(sa.Column('rejected_candidates_json', sa.JSON(), nullable=True))
            if 'recommended_candidate_json' not in columns:
                batch_op.add_column(sa.Column('recommended_candidate_json', sa.JSON(), nullable=True))
            if 'scheduling_method' not in columns:
                batch_op.add_column(sa.Column('scheduling_method', sa.String(), nullable=True, server_default='single_greedy'))
            if 'slot_utilization_pct' not in columns:
                batch_op.add_column(sa.Column('slot_utilization_pct', sa.Float(), nullable=True))
            if 'demand_predicted' not in columns:
                batch_op.add_column(sa.Column('demand_predicted', sa.Float(), nullable=True))
            if 'spilled_from_preferred' not in columns:
                batch_op.add_column(sa.Column('spilled_from_preferred', sa.Boolean(), nullable=True, server_default='0'))
            if 'ml_advisor_used' not in columns:
                batch_op.add_column(sa.Column('ml_advisor_used', sa.Boolean(), nullable=True, server_default='0'))


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    if 'schedule_decisions' in existing_tables:
        columns = {c['name'] for c in insp.get_columns('schedule_decisions')}
        with op.batch_alter_table('schedule_decisions') as batch_op:
            if 'ml_advisor_used' in columns:
                batch_op.drop_column('ml_advisor_used')
            if 'spilled_from_preferred' in columns:
                batch_op.drop_column('spilled_from_preferred')
            if 'demand_predicted' in columns:
                batch_op.drop_column('demand_predicted')
            if 'slot_utilization_pct' in columns:
                batch_op.drop_column('slot_utilization_pct')
            if 'scheduling_method' in columns:
                batch_op.drop_column('scheduling_method')
            if 'recommended_candidate_json' in columns:
                batch_op.drop_column('recommended_candidate_json')
            if 'rejected_candidates_json' in columns:
                batch_op.drop_column('rejected_candidates_json')
            if 'candidates_json' in columns:
                batch_op.drop_column('candidates_json')
