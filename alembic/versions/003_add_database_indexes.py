"""add_database_indexes
 
Revision ID: 003_add_database_indexes
Revises: 002_add_approvals_table
Create Date: 2026-09-06 17:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '003_add_database_indexes'
down_revision: Union[str, None] = '002_add_approvals_table'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    def get_index_names(table: str) -> set:
        if table in existing_tables:
            return {idx["name"] for idx in insp.get_indexes(table)}
        return set()

    # jobs table indexes
    if 'jobs' in existing_tables:
        job_idxs = get_index_names('jobs')
        if 'ix_jobs_team_status' not in job_idxs:
            op.create_index('ix_jobs_team_status', 'jobs', ['team_id', 'status'], unique=False)
        if 'ix_jobs_status_created' not in job_idxs:
            op.create_index('ix_jobs_status_created', 'jobs', ['status', 'created_at'], unique=False)

    # schedule_decisions table indexes
    if 'schedule_decisions' in existing_tables:
        sd_idxs = get_index_names('schedule_decisions')
        if 'ix_schedule_decisions_job_created' not in sd_idxs:
            op.create_index('ix_schedule_decisions_job_created', 'schedule_decisions', ['job_id', 'created_at'], unique=False)

    # approvals table indexes
    if 'approvals' in existing_tables:
        appr_idxs = get_index_names('approvals')
        if 'ix_approvals_job_decision' not in appr_idxs:
            op.create_index('ix_approvals_job_decision', 'approvals', ['job_id', 'decision'], unique=False)
        if 'ix_approvals_schedule_decision' not in appr_idxs:
            op.create_index('ix_approvals_schedule_decision', 'approvals', ['schedule_decision_id', 'decision'], unique=False)

    # kubernetes_executions table indexes
    if 'kubernetes_executions' in existing_tables:
        k8s_idxs = get_index_names('kubernetes_executions')
        if 'ix_k8s_executions_job_status' not in k8s_idxs:
            op.create_index('ix_k8s_executions_job_status', 'kubernetes_executions', ['job_id', 'gs_status'], unique=False)

    # audit_events table indexes
    if 'audit_events' in existing_tables:
        audit_idxs = get_index_names('audit_events')
        if 'ix_audit_events_job_sequence' not in audit_idxs:
            op.create_index('ix_audit_events_job_sequence', 'audit_events', ['job_id', 'sequence'], unique=False)

    # regional_tariffs table indexes
    if 'regional_tariffs' in existing_tables:
        tariff_idxs = get_index_names('regional_tariffs')
        if 'ix_regional_tariffs_region_plan_time' not in tariff_idxs:
            op.create_index('ix_regional_tariffs_region_plan_time', 'regional_tariffs', ['region_id', 'tariff_plan', 'timestamp'], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    if 'regional_tariffs' in existing_tables:
        op.drop_index('ix_regional_tariffs_region_plan_time', table_name='regional_tariffs')
    if 'audit_events' in existing_tables:
        op.drop_index('ix_audit_events_job_sequence', table_name='audit_events')
    if 'kubernetes_executions' in existing_tables:
        op.drop_index('ix_k8s_executions_job_status', table_name='kubernetes_executions')
    if 'approvals' in existing_tables:
        op.drop_index('ix_approvals_schedule_decision', table_name='approvals')
        op.drop_index('ix_approvals_job_decision', table_name='approvals')
    if 'schedule_decisions' in existing_tables:
        op.drop_index('ix_schedule_decisions_job_created', table_name='schedule_decisions')
    if 'jobs' in existing_tables:
        op.drop_index('ix_jobs_status_created', table_name='jobs')
        op.drop_index('ix_jobs_team_status', table_name='jobs')
