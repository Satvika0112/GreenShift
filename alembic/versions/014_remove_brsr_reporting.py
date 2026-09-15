"""remove_brsr_reporting

Revision ID: 014
Revises: 013
Create Date: 2026-09-15 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '014'
down_revision: Union[str, None] = '013'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop the BRSR (Business Responsibility and Sustainability Reporting)
    feature's tables. BRSR has been removed as a GreenShift feature; none of
    these tables are referenced by any other module."""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    for table in (
        'brsr_assessments',
        'brsr_validation_issues',
        'brsr_validation_runs',
        'brsr_metric_values',
        'brsr_metric_definitions',
        'brsr_reports',
        'brsr_company_profiles',
    ):
        if table in existing_tables:
            op.drop_table(table)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    if 'brsr_company_profiles' not in existing_tables:
        op.create_table(
            'brsr_company_profiles',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('tenant_id', sa.String(), nullable=False),
            sa.Column('company_name', sa.String(), nullable=True),
            sa.Column('cin', sa.String(21), nullable=True),
            sa.Column('sector', sa.String(), nullable=True),
            sa.Column('industry', sa.String(), nullable=True),
            sa.Column('listed_status', sa.String(), nullable=True),
            sa.Column('stock_exchange', sa.String(), nullable=True),
            sa.Column('isin', sa.String(12), nullable=True),
            sa.Column('locations', sa.JSON(), nullable=True),
            sa.Column('products_services', sa.JSON(), nullable=True),
            sa.Column('employees_count', sa.Integer(), nullable=True),
            sa.Column('workers_count', sa.Integer(), nullable=True),
            sa.Column('revenue', sa.Float(), nullable=True),
            sa.Column('revenue_currency', sa.String(3), nullable=True),
            sa.Column('net_worth', sa.Float(), nullable=True),
            sa.Column('net_worth_currency', sa.String(3), nullable=True),
            sa.Column('capital', sa.Float(), nullable=True),
            sa.Column('capital_currency', sa.String(3), nullable=True),
            sa.Column('reporting_boundary', sa.Text(), nullable=True),
            sa.Column('currency_conversions', sa.JSON(), nullable=True),
            sa.Column('source_type', sa.String(), nullable=False, server_default='COMPANY_PROVIDED'),
            sa.Column('updated_by', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['updated_by'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('tenant_id', name='uq_brsr_company_profiles_tenant_id'),
        )
        op.create_index('ix_brsr_company_profiles_tenant_id', 'brsr_company_profiles', ['tenant_id'], unique=True)

    if 'brsr_reports' not in existing_tables:
        op.create_table(
            'brsr_reports',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('tenant_id', sa.String(), nullable=False),
            sa.Column('financial_year', sa.String(10), nullable=False),
            sa.Column('reporting_period_start', sa.DateTime(timezone=True), nullable=False),
            sa.Column('reporting_period_end', sa.DateTime(timezone=True), nullable=False),
            sa.Column('framework_version', sa.String(20), nullable=False, server_default='BRSR-2023'),
            sa.Column('status', sa.String(20), nullable=False, server_default='DRAFT'),
            sa.Column('created_by', sa.Integer(), nullable=False),
            sa.Column('approved_by', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('validated_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('generated_at', sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['created_by'], ['users.id']),
            sa.ForeignKeyConstraint(['approved_by'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('tenant_id', 'financial_year', name='uq_brsr_reports_tenant_fy'),
            sa.CheckConstraint(
                "status IN ('DRAFT', 'DATA_COLLECTION', 'VALIDATED', 'APPROVED', 'GENERATED')",
                name='ck_brsr_reports_status_valid',
            ),
        )
        op.create_index('ix_brsr_reports_tenant_id', 'brsr_reports', ['tenant_id'])
        op.create_index('ix_brsr_reports_status', 'brsr_reports', ['status'])

    if 'brsr_metric_definitions' not in existing_tables:
        op.create_table(
            'brsr_metric_definitions',
            sa.Column('metric_code', sa.String(80), nullable=False),
            sa.Column('metric_name', sa.String(), nullable=False),
            sa.Column('principle', sa.Integer(), nullable=True),
            sa.Column('section', sa.String(20), nullable=False),
            sa.Column('brsr_core_attribute', sa.String(60), nullable=True),
            sa.Column('unit', sa.String(40), nullable=True),
            sa.Column('data_type', sa.String(20), nullable=False, server_default='NUMERIC'),
            sa.Column('required', sa.Boolean(), nullable=False, server_default='0'),
            sa.Column('calculation_method', sa.Text(), nullable=True),
            sa.Column('framework_version', sa.String(20), nullable=False, server_default='BRSR-2023'),
            sa.Column('effective_from', sa.DateTime(timezone=True), nullable=False),
            sa.Column('effective_to', sa.DateTime(timezone=True), nullable=True),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('greenshift_derivable', sa.Boolean(), nullable=False, server_default='0'),
            sa.PrimaryKeyConstraint('metric_code'),
            sa.CheckConstraint(
                "section IN ('SECTION_A', 'SECTION_B', 'SECTION_C', 'CORE')",
                name='ck_brsr_metric_def_section_valid',
            ),
        )
        op.create_index('ix_brsr_metric_definitions_section', 'brsr_metric_definitions', ['section'])
        op.create_index('ix_brsr_metric_definitions_brsr_core_attribute', 'brsr_metric_definitions', ['brsr_core_attribute'])

    if 'brsr_metric_values' not in existing_tables:
        op.create_table(
            'brsr_metric_values',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('report_id', sa.Integer(), nullable=False),
            sa.Column('metric_code', sa.String(80), nullable=False),
            sa.Column('value', sa.Float(), nullable=True),
            sa.Column('text_value', sa.Text(), nullable=True),
            sa.Column('unit', sa.String(40), nullable=True),
            sa.Column('currency', sa.String(3), nullable=True),
            sa.Column('source_type', sa.String(20), nullable=False, server_default='MISSING'),
            sa.Column('source_record', sa.String(), nullable=True),
            sa.Column('source_detail', sa.JSON(), nullable=True),
            sa.Column('quality', sa.String(20), nullable=False, server_default='MISSING'),
            sa.Column('estimated', sa.Boolean(), nullable=False, server_default='0'),
            sa.Column('estimation_method', sa.Text(), nullable=True),
            sa.Column('assumption', sa.Text(), nullable=True),
            sa.Column('data_gap', sa.Text(), nullable=True),
            sa.Column('reporting_currency', sa.String(3), nullable=True),
            sa.Column('exchange_rate', sa.Float(), nullable=True),
            sa.Column('exchange_rate_date', sa.DateTime(timezone=True), nullable=True),
            sa.Column('conversion_source', sa.String(), nullable=True),
            sa.Column('converted_value', sa.Float(), nullable=True),
            sa.Column('created_by', sa.Integer(), nullable=True),
            sa.Column('updated_by', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(['report_id'], ['brsr_reports.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['metric_code'], ['brsr_metric_definitions.metric_code']),
            sa.ForeignKeyConstraint(['created_by'], ['users.id']),
            sa.ForeignKeyConstraint(['updated_by'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('report_id', 'metric_code', name='uq_brsr_metric_values_report_metric'),
            sa.CheckConstraint(
                "source_type IN ('GREENSHIFT_DERIVED', 'COMPANY_PROVIDED', 'CALCULATED', 'ESTIMATED', 'EXTERNAL_SOURCE', 'MISSING')",
                name='ck_brsr_metric_values_source_type_valid',
            ),
            sa.CheckConstraint(
                "quality IN ('HIGH', 'MEDIUM', 'LOW', 'MISSING')",
                name='ck_brsr_metric_values_quality_valid',
            ),
        )
        op.create_index('ix_brsr_metric_values_report_id', 'brsr_metric_values', ['report_id'])
        op.create_index('ix_brsr_metric_values_metric_code', 'brsr_metric_values', ['metric_code'])

    if 'brsr_validation_runs' not in existing_tables:
        op.create_table(
            'brsr_validation_runs',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('report_id', sa.Integer(), nullable=False),
            sa.Column('run_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('run_by', sa.Integer(), nullable=True),
            sa.Column('status', sa.String(20), nullable=False),
            sa.Column('error_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('warning_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('info_count', sa.Integer(), nullable=False, server_default='0'),
            sa.ForeignKeyConstraint(['report_id'], ['brsr_reports.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['run_by'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_brsr_validation_runs_report_id', 'brsr_validation_runs', ['report_id'])

    if 'brsr_validation_issues' not in existing_tables:
        op.create_table(
            'brsr_validation_issues',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('run_id', sa.Integer(), nullable=False),
            sa.Column('metric_code', sa.String(80), nullable=True),
            sa.Column('severity', sa.String(10), nullable=False),
            sa.Column('code', sa.String(60), nullable=False),
            sa.Column('message', sa.Text(), nullable=False),
            sa.Column('suggested_resolution', sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(['run_id'], ['brsr_validation_runs.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.CheckConstraint("severity IN ('ERROR', 'WARNING', 'INFO')", name='ck_brsr_validation_issues_severity_valid'),
        )
        op.create_index('ix_brsr_validation_issues_run_id', 'brsr_validation_issues', ['run_id'])

    if 'brsr_assessments' not in existing_tables:
        op.create_table(
            'brsr_assessments',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('report_id', sa.Integer(), nullable=False),
            sa.Column('assessment_status', sa.String(30), nullable=True),
            sa.Column('assessor_name', sa.String(), nullable=True),
            sa.Column('assessor_type', sa.String(20), nullable=True),
            sa.Column('assessment_date', sa.DateTime(timezone=True), nullable=True),
            sa.Column('scope', sa.Text(), nullable=True),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('evidence_reference', sa.Text(), nullable=True),
            sa.Column('source_type', sa.String(), nullable=False, server_default='COMPANY_PROVIDED'),
            sa.Column('updated_by', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(['report_id'], ['brsr_reports.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['updated_by'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('report_id', name='uq_brsr_assessments_report_id'),
        )
        op.create_index('ix_brsr_assessments_report_id', 'brsr_assessments', ['report_id'], unique=True)
