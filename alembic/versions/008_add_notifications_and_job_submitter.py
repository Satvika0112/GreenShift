"""add_notifications_and_job_submitter

Revision ID: 008
Revises: 007
Create Date: 2026-09-09 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '008'
down_revision: Union[str, None] = '007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EVENT_TYPE_VALUES = (
    'JOB_SUBMITTED', 'JOB_VALIDATED', 'JOB_SCHEDULED', 'SCHEDULE_PROPOSED',
    'APPROVAL_GRANTED', 'APPROVAL_DECLINED', 'DISPATCH_REQUESTED', 'DISPATCH_BLOCKED',
    'DISPATCH_STARTED', 'DISPATCH_AUTHORIZED', 'K8S_JOB_CREATED', 'K8S_JOB_STARTED',
    'K8S_JOB_COMPLETED', 'K8S_JOB_FAILED', 'JOB_CANCELLED', 'BUDGET_UPDATED',
    'EXPORT_GENERATED', 'CARBON_API_SUCCESS', 'CARBON_CACHE_UPDATED', 'CARBON_CACHE_USED',
    'CARBON_CACHE_STALE', 'CARBON_CSV_USED', 'CARBON_FALLBACK_USED', 'AUTH_LOGIN_SUCCESS',
    'AUTH_LOGIN_FAILURE', 'AUTH_ACCESS_DENIED', 'AUTH_USER_REGISTERED', 'AUTH_USER_ACTIVATED',
    'AUTH_USER_DEACTIVATED', 'CONFIG_CHANGED', 'TENANT_CREATED', 'API_KEY_CREATED',
    'API_KEY_REVOKED', 'AUDIT_VERIFICATION_FAILED', 'JOB_RESUBMITTED',
)


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    if 'jobs' in existing_tables:
        columns = {c['name'] for c in insp.get_columns('jobs')}
        if 'submitted_by_user_id' not in columns:
            with op.batch_alter_table('jobs') as batch_op:
                batch_op.add_column(sa.Column('submitted_by_user_id', sa.Integer(), nullable=True))
                batch_op.create_foreign_key(
                    'fk_jobs_submitted_by_user_id', 'users',
                    ['submitted_by_user_id'], ['id'], ondelete='SET NULL',
                )
            op.create_index('ix_jobs_submitted_by_user_id', 'jobs', ['submitted_by_user_id'], unique=False)

    if 'notifications' not in existing_tables:
        op.create_table(
            'notifications',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('tenant_id', sa.String(), nullable=True),
            sa.Column('recipient_user_id', sa.Integer(), nullable=False),
            sa.Column('job_id', sa.String(), nullable=True),
            # create_type=False: the 'eventtype' Postgres enum already exists
            # (created for audit_events in migration 001) — reuse it, don't
            # try to CREATE TYPE it again.
            sa.Column('event_type', sa.Enum(*EVENT_TYPE_VALUES, name='eventtype', create_type=False), nullable=False),
            sa.Column('category', sa.String(length=30), nullable=False),
            sa.Column('severity', sa.String(length=20), nullable=False, server_default='INFO'),
            sa.Column('title', sa.String(), nullable=False),
            sa.Column('message', sa.Text(), nullable=False),
            sa.Column('action_url', sa.String(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('dedup_key', sa.String(), nullable=False),
            sa.Column('email_required', sa.Boolean(), nullable=False, server_default='0'),
            sa.Column('email_status', sa.String(length=20), nullable=False, server_default='NOT_REQUIRED'),
            sa.Column('email_attempts', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('email_sent_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('email_failed_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('last_error', sa.Text(), nullable=True),
            sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint("severity IN ('INFO', 'WARNING', 'CRITICAL')", name='ck_notifications_severity_valid'),
            sa.CheckConstraint("email_status IN ('NOT_REQUIRED', 'PENDING', 'SENT', 'FAILED')", name='ck_notifications_email_status_valid'),
            sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['recipient_user_id'], ['users.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('recipient_user_id', 'dedup_key', name='uq_notifications_recipient_dedup'),
        )
        op.create_index('ix_notifications_tenant_id', 'notifications', ['tenant_id'], unique=False)
        op.create_index('ix_notifications_recipient_user_id', 'notifications', ['recipient_user_id'], unique=False)
        op.create_index('ix_notifications_job_id', 'notifications', ['job_id'], unique=False)
        op.create_index('ix_notifications_event_type', 'notifications', ['event_type'], unique=False)
        op.create_index('ix_notifications_category', 'notifications', ['category'], unique=False)
        op.create_index('ix_notifications_created_at', 'notifications', ['created_at'], unique=False)
        op.create_index('ix_notifications_recipient_read', 'notifications', ['recipient_user_id', 'read_at'], unique=False)
        op.create_index('ix_notifications_email_pending', 'notifications', ['email_status', 'next_attempt_at'], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    if 'notifications' in existing_tables:
        op.drop_table('notifications')

    if 'jobs' in existing_tables:
        columns = {c['name'] for c in insp.get_columns('jobs')}
        if 'submitted_by_user_id' in columns:
            with op.batch_alter_table('jobs') as batch_op:
                # Drop the index explicitly — SQLite batch mode reflects the
                # table to decide what to recreate, and won't know to skip an
                # index on a column being dropped unless told here. Dropping
                # the column itself removes the FK implicitly on both dialects.
                batch_op.drop_index('ix_jobs_submitted_by_user_id')
                batch_op.drop_column('submitted_by_user_id')
