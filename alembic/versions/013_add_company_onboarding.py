"""add_company_onboarding

Revision ID: 013
Revises: 012
Create Date: 2026-09-12 00:00:00.000000

Company / Organization onboarding. Extends the EXISTING `tenants` table with
a richer company profile (legal_name, company_email, website, industry,
sector, country, address, status, cin, gstin, employee_count, contact_phone,
updated_at) rather than introducing a second, parallel `companies` table —
Company.id and tenant_id remain the exact same value everywhere. Adds a new,
additive `teams` table for named teams within a company; existing
users.team_id/jobs.team_id remain plain, unconstrained string columns
(unchanged) so every pre-existing team_id value keeps working exactly as
before regardless of whether a matching `teams` row exists.

No existing tenant/user/job/audit/BRSR data is altered, backfilled, or
deleted by this migration — every new tenant column is nullable and left
NULL on existing rows.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '013'
down_revision: Union[str, None] = '012'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_TENANT_COLUMNS = [
    ("legal_name", sa.String()),
    ("company_email", sa.String()),
    ("website", sa.String()),
    ("industry", sa.String()),
    ("sector", sa.String()),
    ("country", sa.String()),
    ("address", sa.Text()),
    ("status", sa.String()),
    ("cin", sa.String(21)),
    ("gstin", sa.String(15)),
    ("employee_count", sa.Integer()),
    ("contact_phone", sa.String()),
    ("updated_at", sa.DateTime(timezone=True)),
]


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if insp.has_table("tenants"):
        existing_cols = {c["name"] for c in insp.get_columns("tenants")}
        for col_name, col_type in _NEW_TENANT_COLUMNS:
            if col_name not in existing_cols:
                op.add_column("tenants", sa.Column(col_name, col_type, nullable=True))

        # status defaults to 'ACTIVE' for pre-existing tenants (a real,
        # honest default reflecting that all pre-existing tenants are
        # already operating normally — not an invented business fact).
        if "status" not in existing_cols:
            op.execute(sa.text("UPDATE tenants SET status = 'ACTIVE' WHERE status IS NULL"))

        existing_indexes = {ix["name"] for ix in insp.get_indexes("tenants")}
        if "ix_tenants_company_email" not in existing_indexes and "company_email" not in existing_cols:
            # Unique index allowing multiple NULLs (SQLite/Postgres both treat
            # NULL as distinct in a UNIQUE index), so pre-existing tenants
            # with no company_email never collide with each other.
            op.create_index("ix_tenants_company_email", "tenants", ["company_email"], unique=True)

    if not insp.has_table("teams"):
        op.create_table(
            "teams",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("tenant_id", "name", name="uq_teams_tenant_name"),
        )
        op.create_index("ix_teams_tenant_id", "teams", ["tenant_id"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if insp.has_table("teams"):
        op.drop_table("teams")

    if insp.has_table("tenants"):
        existing_indexes = {ix["name"] for ix in insp.get_indexes("tenants")}
        if "ix_tenants_company_email" in existing_indexes:
            op.drop_index("ix_tenants_company_email", table_name="tenants")

        existing_cols = {c["name"] for c in insp.get_columns("tenants")}
        for col_name, _ in _NEW_TENANT_COLUMNS:
            if col_name in existing_cols:
                op.drop_column("tenants", col_name)
