"""initial_postgresql_schema

Revision ID: 001_initial_postgresql_schema
Revises: 
Create Date: 2026-09-06 10:25:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Full JobStatus enum values, matching app.shared.models.JobStatus.
# NOTE: widened from the original 6-value set — the original set never
# actually supported a clean `alembic upgrade head` (migration 004's
# check constraint already required PENDING_APPROVAL/APPROVED/DECLINED,
# which this enum did not contain), so this is a same-migration fix
# rather than a later ALTER TYPE.
JOB_STATUS_VALUES = (
    'SUBMITTED', 'VALIDATED', 'SCHEDULED', 'PENDING_APPROVAL', 'APPROVED',
    'READY', 'CLAIMING', 'DECLINED', 'REJECTED', 'QUEUED', 'DISPATCHING',
    'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED',
)


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    # ─── Table: tenants ───────────────────────────────────────────
    if 'tenants' not in existing_tables:
        op.create_table(
            'tenants',
            sa.Column('id', sa.String(), nullable=False),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('name'),
        )
        existing_tables.add('tenants')

    # ─── Table: jobs ──────────────────────────────────────────────
    if 'jobs' not in existing_tables:
        op.create_table(
            'jobs',
            sa.Column('job_id', sa.String(), nullable=False),
            sa.Column('workload_name', sa.String(), nullable=True),
            sa.Column('team_id', sa.String(), nullable=False),
            sa.Column('tenant_id', sa.String(), nullable=True),
            sa.Column('submitted_at', sa.DateTime(), nullable=False),
            sa.Column('deadline', sa.DateTime(), nullable=False),
            sa.Column('runtime_minutes', sa.Integer(), nullable=False),
            sa.Column('power_kw', sa.Float(), nullable=False),
            sa.Column('region', sa.String(), nullable=False),
            sa.Column('timezone', sa.String(), nullable=True, server_default='UTC'),
            sa.Column('status', sa.Enum(*JOB_STATUS_VALUES, name='jobstatus'), nullable=False),
            sa.Column('container_image', sa.String(), nullable=False),
            sa.Column('cpu_request', sa.String(), nullable=True, server_default='500m'),
            sa.Column('memory_request', sa.String(), nullable=True, server_default='512Mi'),
            sa.Column('carbon_budget_kg', sa.Float(), nullable=True),
            sa.Column('job_type', sa.String(), nullable=True),
            sa.Column('priority', sa.String(), nullable=True),
            sa.Column('earliest_start_time', sa.DateTime(), nullable=True),
            sa.Column('energy_kwh', sa.Float(), nullable=True),
            sa.Column('deferrable', sa.Boolean(), nullable=True),
            sa.Column('claimed_by', sa.String(), nullable=True),
            sa.Column('claimed_at', sa.DateTime(), nullable=True),
            sa.Column('lease_expires_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
            sa.PrimaryKeyConstraint('job_id')
        )
        op.create_index('ix_jobs_deadline', 'jobs', ['deadline'], unique=False)
        op.create_index('ix_jobs_region', 'jobs', ['region'], unique=False)
        op.create_index('ix_jobs_status', 'jobs', ['status'], unique=False)
        op.create_index('ix_jobs_submitted_at', 'jobs', ['submitted_at'], unique=False)
        op.create_index('ix_jobs_team_id', 'jobs', ['team_id'], unique=False)
        op.create_index('ix_jobs_tenant_id', 'jobs', ['tenant_id'], unique=False)
        op.create_index('ix_jobs_created_at', 'jobs', ['created_at'], unique=False)
        op.create_index('idx_jobs_dispatch_queue', 'jobs', ['status', 'priority', 'deadline'], unique=False)
        op.create_index('idx_jobs_claim_lease', 'jobs', ['status', 'lease_expires_at'], unique=False)

    # ─── Table: schedule_decisions ────────────────────────────────
    if 'schedule_decisions' not in existing_tables:
        op.create_table(
            'schedule_decisions',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('job_id', sa.String(), nullable=False),
            sa.Column('selected_start', sa.DateTime(), nullable=False),
            sa.Column('selected_end', sa.DateTime(), nullable=False),
            sa.Column('carbon_intensity', sa.Float(), nullable=False),
            sa.Column('electricity_cost', sa.Float(), nullable=False),
            sa.Column('carbon_emission', sa.Float(), nullable=False),
            sa.Column('optimization_score', sa.Float(), nullable=True),
            sa.Column('reason', sa.Text(), nullable=False),
            sa.Column('budget_remaining', sa.Float(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('region_id', sa.String(), nullable=True),
            sa.Column('tariff_plan', sa.String(), nullable=True),
            sa.Column('currency', sa.String(), nullable=True),
            sa.Column('native_cost', sa.Float(), nullable=True),
            sa.Column('baseline_native_cost', sa.Float(), nullable=True),
            sa.Column('tariff_inr_per_kwh', sa.Float(), nullable=True),
            sa.Column('tariff_category', sa.String(), nullable=True),
            sa.Column('baseline_start', sa.DateTime(), nullable=True),
            sa.Column('baseline_end', sa.DateTime(), nullable=True),
            sa.Column('baseline_carbon_emission', sa.Float(), nullable=True),
            sa.Column('baseline_cost', sa.Float(), nullable=True),
            sa.Column('carbon_avoided', sa.Float(), nullable=True),
            sa.Column('cost_difference', sa.Float(), nullable=True),
            sa.Column('carbon_reduction_pct', sa.Float(), nullable=True),
            sa.Column('cost_reduction_pct', sa.Float(), nullable=True),
            sa.Column('scheduling_delay_hours', sa.Float(), nullable=True),
            sa.Column('sla_met', sa.Boolean(), nullable=True),
            sa.ForeignKeyConstraint(['job_id'], ['jobs.job_id'], ),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('job_id')
        )
        op.create_index('ix_schedule_decisions_job_id', 'schedule_decisions', ['job_id'], unique=True)
        op.create_index('ix_schedule_decisions_region_id', 'schedule_decisions', ['region_id'], unique=False)
        op.create_index('ix_schedule_decisions_selected_end', 'schedule_decisions', ['selected_end'], unique=False)
        op.create_index('ix_schedule_decisions_selected_start', 'schedule_decisions', ['selected_start'], unique=False)

    # ─── Table: kubernetes_executions ─────────────────────────────
    if 'kubernetes_executions' not in existing_tables:
        op.create_table(
            'kubernetes_executions',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('job_id', sa.String(), nullable=False),
            sa.Column('kubernetes_job_name', sa.String(), nullable=False),
            sa.Column('kubernetes_namespace', sa.String(), nullable=False),
            sa.Column('pod_name', sa.String(), nullable=True),
            sa.Column('planned_start', sa.DateTime(), nullable=False),
            sa.Column('actual_start', sa.DateTime(), nullable=True),
            sa.Column('planned_end', sa.DateTime(), nullable=True),
            sa.Column('actual_end', sa.DateTime(), nullable=True),
            sa.Column('k8s_status', sa.String(), nullable=True),
            sa.Column('gs_status', sa.Enum(*JOB_STATUS_VALUES, name='jobstatus'), nullable=False),
            sa.Column('error_message', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['job_id'], ['jobs.job_id'], ),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('job_id')
        )
        op.create_index('ix_kubernetes_executions_gs_status', 'kubernetes_executions', ['gs_status'], unique=False)
        op.create_index('ix_kubernetes_executions_job_id', 'kubernetes_executions', ['job_id'], unique=True)
        op.create_index('ix_kubernetes_executions_kubernetes_job_name', 'kubernetes_executions', ['kubernetes_job_name'], unique=False)
        op.create_index('ix_kubernetes_executions_planned_start', 'kubernetes_executions', ['planned_start'], unique=False)

    # ─── Table: audit_events ──────────────────────────────────────
    if 'audit_events' not in existing_tables:
        op.create_table(
            'audit_events',
            sa.Column('event_id', sa.String(), nullable=False),
            sa.Column('timestamp', sa.DateTime(), nullable=False),
            sa.Column('event_type', sa.Enum('JOB_SUBMITTED', 'JOB_SCHEDULED', 'K8S_JOB_CREATED', 'K8S_JOB_STARTED', 'K8S_JOB_COMPLETED', 'K8S_JOB_FAILED', 'BUDGET_UPDATED', 'EXPORT_GENERATED', 'CARBON_API_SUCCESS', 'CARBON_CACHE_UPDATED', 'CARBON_CACHE_USED', 'CARBON_CACHE_STALE', 'CARBON_CSV_USED', 'CARBON_FALLBACK_USED', name='eventtype'), nullable=False),
            sa.Column('job_id', sa.String(), nullable=True),
            sa.Column('payload_hash', sa.String(length=64), nullable=False),
            sa.Column('previous_hash', sa.String(length=64), nullable=False),
            sa.Column('current_hash', sa.String(length=64), nullable=False),
            sa.Column('payload_json', sa.Text(), nullable=False),
            sa.Column('sequence', sa.Integer(), nullable=False),
            sa.PrimaryKeyConstraint('event_id'),
            sa.UniqueConstraint('sequence', name='uq_audit_events_sequence')
        )
        op.create_index('ix_audit_events_event_type', 'audit_events', ['event_type'], unique=False)
        op.create_index('ix_audit_events_job_id', 'audit_events', ['job_id'], unique=False)
        op.create_index('ix_audit_events_sequence', 'audit_events', ['sequence'], unique=True)
        op.create_index('ix_audit_events_timestamp', 'audit_events', ['timestamp'], unique=False)

    # ─── Table: carbon_data ───────────────────────────────────────
    if 'carbon_data' not in existing_tables:
        op.create_table(
            'carbon_data',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('timestamp', sa.DateTime(), nullable=False),
            sa.Column('region', sa.String(), nullable=False),
            sa.Column('carbon_gco2_kwh', sa.Float(), nullable=False),
            sa.Column('fetched_at', sa.DateTime(), nullable=False),
            sa.Column('source', sa.String(), nullable=False),
            sa.Column('expires_at', sa.DateTime(), nullable=True),
            sa.Column('em_zone', sa.String(), nullable=True),
            sa.Column('confidence_status', sa.String(), nullable=True),
            sa.Column('is_fallback', sa.Boolean(), nullable=False),
            sa.Column('fallback_reason', sa.String(), nullable=True),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('ix_carbon_data_fetched_at', 'carbon_data', ['fetched_at'], unique=False)
        op.create_index('ix_carbon_data_region', 'carbon_data', ['region'], unique=False)
        op.create_index('ix_carbon_data_region_timestamp', 'carbon_data', ['region', 'timestamp'], unique=False)
        op.create_index('ix_carbon_data_timestamp', 'carbon_data', ['timestamp'], unique=False)

    # ─── Table: tariff_data ───────────────────────────────────────
    if 'tariff_data' not in existing_tables:
        op.create_table(
            'tariff_data',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('timestamp', sa.DateTime(), nullable=False),
            sa.Column('region', sa.String(), nullable=False),
            sa.Column('price_per_kwh', sa.Float(), nullable=False),
            sa.Column('fetched_at', sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('ix_tariff_data_region', 'tariff_data', ['region'], unique=False)
        op.create_index('ix_tariff_data_region_timestamp', 'tariff_data', ['region', 'timestamp'], unique=False)
        op.create_index('ix_tariff_data_timestamp', 'tariff_data', ['timestamp'], unique=False)

    # ─── Table: regional_tariffs ──────────────────────────────────
    if 'regional_tariffs' not in existing_tables:
        op.create_table(
            'regional_tariffs',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('region_id', sa.String(), nullable=False),
            sa.Column('country', sa.String(), nullable=False),
            sa.Column('region_name', sa.String(), nullable=False),
            sa.Column('tariff_plan', sa.String(), nullable=False),
            sa.Column('timestamp', sa.DateTime(), nullable=False),
            sa.Column('local_timestamp', sa.DateTime(), nullable=False),
            sa.Column('timezone', sa.String(), nullable=False),
            sa.Column('season', sa.String(), nullable=True),
            sa.Column('tod_block', sa.String(), nullable=True),
            sa.Column('time_period', sa.String(), nullable=False),
            sa.Column('base_energy_rate', sa.Float(), nullable=True),
            sa.Column('tod_adder', sa.Float(), nullable=True),
            sa.Column('electricity_rate', sa.Float(), nullable=False),
            sa.Column('currency', sa.String(), nullable=False),
            sa.Column('is_peak_hour', sa.Boolean(), nullable=False),
            sa.Column('is_solar_hour', sa.Boolean(), nullable=False),
            sa.Column('is_night_hour', sa.Boolean(), nullable=False),
            sa.Column('category', sa.String(), nullable=True),
            sa.Column('voltage', sa.String(), nullable=True),
            sa.Column('tariff_year', sa.String(), nullable=True),
            sa.Column('effective_from', sa.String(), nullable=True),
            sa.Column('effective_to', sa.String(), nullable=True),
            sa.Column('source', sa.String(), nullable=False),
            sa.Column('demand_charge', sa.Float(), nullable=True),
            sa.Column('fixed_charge', sa.Float(), nullable=True),
            sa.Column('price_per_kwh_usd', sa.Float(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('ix_regional_tariffs_region_id', 'regional_tariffs', ['region_id'], unique=False)
        op.create_index('ix_regional_tariffs_tariff_plan', 'regional_tariffs', ['tariff_plan'], unique=False)
        op.create_index('ix_regional_tariffs_timestamp', 'regional_tariffs', ['timestamp'], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    if 'regional_tariffs' in existing_tables:
        op.drop_table('regional_tariffs')
    if 'tariff_data' in existing_tables:
        op.drop_table('tariff_data')
    if 'carbon_data' in existing_tables:
        op.drop_table('carbon_data')
    if 'audit_events' in existing_tables:
        op.drop_table('audit_events')
    if 'kubernetes_executions' in existing_tables:
        op.drop_table('kubernetes_executions')
    if 'schedule_decisions' in existing_tables:
        op.drop_table('schedule_decisions')
    if 'jobs' in existing_tables:
        op.drop_table('jobs')
    if 'tenants' in existing_tables:
        op.drop_table('tenants')
