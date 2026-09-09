"""add_data_integrity_constraints

Revision ID: 004_add_data_integrity_constraints
Revises: 003_add_database_indexes
Create Date: 2026-09-06 17:31:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '004'
down_revision: Union[str, None] = '003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    # 1. Jobs constraints
    if 'jobs' in existing_tables:
        with op.batch_alter_table('jobs') as batch_op:
            batch_op.create_check_constraint(
                'ck_jobs_runtime_minutes_positive',
                'runtime_minutes > 0'
            )
            batch_op.create_check_constraint(
                'ck_jobs_power_kw_positive',
                'power_kw > 0'
            )
            batch_op.create_check_constraint(
                'ck_jobs_carbon_budget_non_negative',
                'carbon_budget_kg IS NULL OR carbon_budget_kg >= 0'
            )
            batch_op.create_check_constraint(
                'ck_jobs_energy_kwh_non_negative',
                'energy_kwh IS NULL OR energy_kwh >= 0'
            )
            batch_op.create_check_constraint(
                'ck_jobs_status_valid',
                "status IN ('SUBMITTED', 'VALIDATED', 'SCHEDULED', 'PENDING_APPROVAL', 'APPROVED', 'READY', 'CLAIMING', 'DECLINED', 'REJECTED', 'QUEUED', 'DISPATCHING', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED')"
            )

    # 2. Schedule Decisions constraints
    if 'schedule_decisions' in existing_tables:
        with op.batch_alter_table('schedule_decisions') as batch_op:
            batch_op.create_check_constraint(
                'ck_schedule_decisions_time_window',
                'selected_end > selected_start'
            )
            batch_op.create_check_constraint(
                'ck_schedule_decisions_carbon_emission_non_negative',
                'carbon_emission >= 0'
            )
            batch_op.create_check_constraint(
                'ck_schedule_decisions_electricity_cost_non_negative',
                'electricity_cost >= 0'
            )
            batch_op.create_check_constraint(
                'ck_schedule_decisions_carbon_intensity_non_negative',
                'carbon_intensity >= 0'
            )

    # 3. Approvals constraints
    if 'approvals' in existing_tables:
        with op.batch_alter_table('approvals') as batch_op:
            batch_op.create_check_constraint(
                'ck_approvals_decision_valid',
                "decision IN ('APPROVED', 'DECLINED')"
            )

    # 4. Kubernetes Executions constraints
    if 'kubernetes_executions' in existing_tables:
        with op.batch_alter_table('kubernetes_executions') as batch_op:
            batch_op.create_check_constraint(
                'ck_k8s_executions_planned_time_window',
                'planned_end IS NULL OR planned_start IS NULL OR planned_end > planned_start'
            )
            batch_op.create_check_constraint(
                'ck_k8s_executions_actual_time_window',
                'actual_end IS NULL OR actual_start IS NULL OR actual_end >= actual_start'
            )
            batch_op.create_check_constraint(
                'ck_k8s_executions_status_valid',
                "gs_status IN ('SUBMITTED', 'SCHEDULED', 'PENDING_APPROVAL', 'APPROVED', 'READY', 'CLAIMING', 'DECLINED', 'QUEUED', 'RUNNING', 'COMPLETED', 'FAILED')"
            )

    # 5. Carbon Data constraints
    if 'carbon_data' in existing_tables:
        with op.batch_alter_table('carbon_data') as batch_op:
            batch_op.create_check_constraint(
                'ck_carbon_data_intensity_non_negative',
                'carbon_gco2_kwh >= 0'
            )

    # 6. Tariff Data constraints
    if 'tariff_data' in existing_tables:
        with op.batch_alter_table('tariff_data') as batch_op:
            batch_op.create_check_constraint(
                'ck_tariff_data_price_non_negative',
                'price_per_kwh >= 0'
            )

    # 7. Regional Tariffs constraints
    if 'regional_tariffs' in existing_tables:
        with op.batch_alter_table('regional_tariffs') as batch_op:
            batch_op.create_check_constraint(
                'ck_regional_tariffs_rate_non_negative',
                'electricity_rate >= 0'
            )
            batch_op.create_check_constraint(
                'ck_regional_tariffs_usd_rate_non_negative',
                'price_per_kwh_usd >= 0'
            )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    if 'regional_tariffs' in existing_tables:
        with op.batch_alter_table('regional_tariffs') as batch_op:
            batch_op.drop_constraint('ck_regional_tariffs_usd_rate_non_negative', type_='check')
            batch_op.drop_constraint('ck_regional_tariffs_rate_non_negative', type_='check')

    if 'tariff_data' in existing_tables:
        with op.batch_alter_table('tariff_data') as batch_op:
            batch_op.drop_constraint('ck_tariff_data_price_non_negative', type_='check')

    if 'carbon_data' in existing_tables:
        with op.batch_alter_table('carbon_data') as batch_op:
            batch_op.drop_constraint('ck_carbon_data_intensity_non_negative', type_='check')

    if 'kubernetes_executions' in existing_tables:
        with op.batch_alter_table('kubernetes_executions') as batch_op:
            batch_op.drop_constraint('ck_k8s_executions_status_valid', type_='check')
            batch_op.drop_constraint('ck_k8s_executions_actual_time_window', type_='check')
            batch_op.drop_constraint('ck_k8s_executions_planned_time_window', type_='check')

    if 'approvals' in existing_tables:
        with op.batch_alter_table('approvals') as batch_op:
            batch_op.drop_constraint('ck_approvals_decision_valid', type_='check')

    if 'schedule_decisions' in existing_tables:
        with op.batch_alter_table('schedule_decisions') as batch_op:
            batch_op.drop_constraint('ck_schedule_decisions_carbon_intensity_non_negative', type_='check')
            batch_op.drop_constraint('ck_schedule_decisions_electricity_cost_non_negative', type_='check')
            batch_op.drop_constraint('ck_schedule_decisions_carbon_emission_non_negative', type_='check')
            batch_op.drop_constraint('ck_schedule_decisions_time_window', type_='check')

    if 'jobs' in existing_tables:
        with op.batch_alter_table('jobs') as batch_op:
            batch_op.drop_constraint('ck_jobs_status_valid', type_='check')
            batch_op.drop_constraint('ck_jobs_energy_kwh_non_negative', type_='check')
            batch_op.drop_constraint('ck_jobs_carbon_budget_non_negative', type_='check')
            batch_op.drop_constraint('ck_jobs_power_kw_positive', type_='check')
            batch_op.drop_constraint('ck_jobs_runtime_minutes_positive', type_='check')
