"""add_trust_audit_context

Revision ID: 012
Revises: 011
Create Date: 2026-09-12 00:00:00.000000

Adds actor/tenant/team/request-correlation columns to audit_events, a new
audit_anchors table for multi-anchor history, and database-level append-only
protection (triggers) on audit_events. Idempotent: safe to run against a
database that already has some/all of these objects (existing dev/prod DBs),
and a no-op contribution on a brand-new DB where
app.shared.models.AuditEventORM's after_create DDL listeners already created
the same triggers via Base.metadata.create_all().
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '012'
down_revision: Union[str, None] = '011'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_AUDIT_EVENT_COLUMNS = [
    ("tenant_id", sa.String()),
    ("team_id", sa.String()),
    ("actor_user_id", sa.String()),
    ("actor_username", sa.String()),
    ("actor_role", sa.String()),
    ("actor_type", sa.String()),
    ("request_id", sa.String()),
    ("source_service", sa.String()),
]


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    dialect = bind.dialect.name

    if insp.has_table("audit_events"):
        existing_cols = {c["name"] for c in insp.get_columns("audit_events")}
        for col_name, col_type in _NEW_AUDIT_EVENT_COLUMNS:
            if col_name not in existing_cols:
                op.add_column("audit_events", sa.Column(col_name, col_type, nullable=True))

        existing_indexes = {ix["name"] for ix in insp.get_indexes("audit_events")}
        if "ix_audit_events_tenant_sequence" not in existing_indexes:
            op.create_index("ix_audit_events_tenant_sequence", "audit_events", ["tenant_id", "sequence"])
        if "ix_audit_events_team_sequence" not in existing_indexes:
            op.create_index("ix_audit_events_team_sequence", "audit_events", ["team_id", "sequence"])
        if "ix_audit_events_actor_user_id" not in existing_indexes:
            op.create_index("ix_audit_events_actor_user_id", "audit_events", ["actor_user_id"])
        if "ix_audit_events_request_id" not in existing_indexes:
            op.create_index("ix_audit_events_request_id", "audit_events", ["request_id"])

    if not insp.has_table("audit_anchors"):
        op.create_table(
            "audit_anchors",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("sequence", sa.Integer(), nullable=False),
            sa.Column("root_hash", sa.String(64), nullable=False),
            sa.Column("event_count", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_by_user_id", sa.String(), nullable=True),
            sa.Column("label", sa.String(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_audit_anchors_sequence", "audit_anchors", ["sequence"])
        op.create_index("ix_audit_anchors_created_at", "audit_anchors", ["created_at"])

    # Append-only DB protection. Idempotent per-dialect; matches the same
    # DDL app.shared.models registers via after_create for fresh schemas.
    if dialect == "sqlite":
        bind.execute(sa.text(
            """
            CREATE TRIGGER IF NOT EXISTS trg_audit_events_no_update
            BEFORE UPDATE ON audit_events
            BEGIN
                SELECT RAISE(ABORT, 'audit_events is append-only: UPDATE is not permitted');
            END;
            """
        ))
        bind.execute(sa.text(
            """
            CREATE TRIGGER IF NOT EXISTS trg_audit_events_no_delete
            BEFORE DELETE ON audit_events
            BEGIN
                SELECT RAISE(ABORT, 'audit_events is append-only: DELETE is not permitted');
            END;
            """
        ))
    elif dialect == "postgresql":
        bind.execute(sa.text(
            """
            CREATE OR REPLACE FUNCTION fn_audit_events_append_only()
            RETURNS TRIGGER AS $$
            BEGIN
                RAISE EXCEPTION 'audit_events is append-only: % is not permitted', TG_OP;
            END;
            $$ LANGUAGE plpgsql;
            """
        ))
        bind.execute(sa.text("DROP TRIGGER IF EXISTS trg_audit_events_append_only ON audit_events;"))
        bind.execute(sa.text(
            """
            CREATE TRIGGER trg_audit_events_append_only
            BEFORE UPDATE OR DELETE ON audit_events
            FOR EACH ROW EXECUTE FUNCTION fn_audit_events_append_only();
            """
        ))


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "sqlite":
        bind.execute(sa.text("DROP TRIGGER IF EXISTS trg_audit_events_no_update;"))
        bind.execute(sa.text("DROP TRIGGER IF EXISTS trg_audit_events_no_delete;"))
    elif dialect == "postgresql":
        bind.execute(sa.text("DROP TRIGGER IF EXISTS trg_audit_events_append_only ON audit_events;"))
        bind.execute(sa.text("DROP FUNCTION IF EXISTS fn_audit_events_append_only();"))

    op.drop_table("audit_anchors")

    insp = sa.inspect(bind)
    if insp.has_table("audit_events"):
        existing_indexes = {ix["name"] for ix in insp.get_indexes("audit_events")}
        for ix_name in (
            "ix_audit_events_tenant_sequence", "ix_audit_events_team_sequence",
            "ix_audit_events_actor_user_id", "ix_audit_events_request_id",
        ):
            if ix_name in existing_indexes:
                op.drop_index(ix_name, table_name="audit_events")

        existing_cols = {c["name"] for c in insp.get_columns("audit_events")}
        for col_name, _ in _NEW_AUDIT_EVENT_COLUMNS:
            if col_name in existing_cols:
                op.drop_column("audit_events", col_name)
