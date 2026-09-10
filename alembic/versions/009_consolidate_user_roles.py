"""consolidate_user_roles

Consolidates the application role model down to exactly three canonical
roles: PLATFORM_ADMIN, COMPANY_ADMIN, COMPANY_USER. Legacy role values
(ADMIN, TEAM_LEAD, OPERATOR, USER, VIEWER) are normalized on existing rows
before the enum/check-constraint is tightened, so no data is lost or
rejected.

Mapping (see app.shared.models.UserRole docstring for rationale):
  ADMIN (tenant_id IS NULL)  -> PLATFORM_ADMIN
  ADMIN (tenant_id NOT NULL) -> COMPANY_ADMIN
  TEAM_LEAD                  -> COMPANY_ADMIN
  OPERATOR, USER, VIEWER     -> COMPANY_USER
  api_keys.role (any legacy or administrative value) -> COMPANY_USER
    (API keys can never hold an administrative role — RULE 3)

Revision ID: 009
Revises: 008
Create Date: 2026-09-10 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '009'
down_revision: Union[str, None] = '008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CANONICAL_ROLE_VALUES = ('PLATFORM_ADMIN', 'COMPANY_ADMIN', 'COMPANY_USER')


def _normalize_role_data(bind) -> None:
    """Fold legacy role values into the three canonical roles. Idempotent."""
    bind.execute(sa.text(
        "UPDATE users SET role = 'PLATFORM_ADMIN' WHERE role = 'ADMIN' AND tenant_id IS NULL"
    ))
    bind.execute(sa.text(
        "UPDATE users SET role = 'COMPANY_ADMIN' WHERE role IN ('ADMIN', 'TEAM_LEAD')"
    ))
    bind.execute(sa.text(
        "UPDATE users SET role = 'COMPANY_USER' WHERE role IN ('OPERATOR', 'USER', 'VIEWER')"
    ))
    bind.execute(sa.text(
        "UPDATE api_keys SET role = 'COMPANY_USER' WHERE role IN "
        "('ADMIN', 'TEAM_LEAD', 'OPERATOR', 'USER', 'VIEWER', 'PLATFORM_ADMIN', 'COMPANY_ADMIN')"
    ))


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    if 'users' not in existing_tables or 'api_keys' not in existing_tables:
        return

    # 1. Normalize existing data while the wide (8-value) type/constraint
    #    still accepts every legacy value.
    _normalize_role_data(bind)

    if bind.dialect.name == 'postgresql':
        # 2. Drop the old CHECK constraint (references the 8-value list).
        op.drop_constraint('ck_users_role_valid', 'users', type_='check')

        # 3. Swap the native Postgres enum type for a 3-value one. Postgres
        #    cannot DROP a value from an enum type in place, so create a new
        #    type, cast both columns over to it, then replace the old type.
        op.execute("ALTER TYPE userrole RENAME TO userrole_old")
        new_role_enum = sa.Enum(*CANONICAL_ROLE_VALUES, name='userrole')
        new_role_enum.create(bind, checkfirst=True)

        op.execute(
            "ALTER TABLE users ALTER COLUMN role DROP DEFAULT"
        )
        op.execute(
            "ALTER TABLE users ALTER COLUMN role TYPE userrole "
            "USING role::text::userrole"
        )
        op.execute(
            "ALTER TABLE users ALTER COLUMN role SET DEFAULT 'COMPANY_USER'"
        )

        op.execute(
            "ALTER TABLE api_keys ALTER COLUMN role DROP DEFAULT"
        )
        op.execute(
            "ALTER TABLE api_keys ALTER COLUMN role TYPE userrole "
            "USING role::text::userrole"
        )
        op.execute(
            "ALTER TABLE api_keys ALTER COLUMN role SET DEFAULT 'COMPANY_USER'"
        )

        op.execute("DROP TYPE userrole_old")

        # 4. Recreate the CHECK constraint, now matching the tightened enum.
        op.create_check_constraint(
            'ck_users_role_valid',
            'users',
            "role IN ('PLATFORM_ADMIN', 'COMPANY_ADMIN', 'COMPANY_USER')",
        )
    else:
        # SQLite: no native enum type; role is a plain CHECK-constrained
        # column. SQLite cannot ALTER a CHECK constraint in place, so rebuild
        # the table the same way app.shared.database.run_schema_migrations()
        # does for its own (redundant, startup-time) safety-net copy of this
        # migration — kept in sync here so `alembic upgrade head` alone is
        # sufficient without relying on that runtime patch.
        import re
        row = bind.execute(sa.text(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='users'"
        )).fetchone()
        if row and row[0] and "TEAM_LEAD" in row[0]:
            # Capture existing index definitions so the rebuild below doesn't
            # silently drop any of them (a table rebuild drops all indexes
            # tied to the old table).
            index_rows = bind.execute(sa.text(
                "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name='users' AND sql IS NOT NULL"
            )).fetchall()

            bind.execute(sa.text("PRAGMA foreign_keys=OFF"))
            new_sql = re.sub(
                r"CONSTRAINT\s+ck_users_role_valid\s+CHECK\s*\(.*?\)\)",
                "CONSTRAINT ck_users_role_valid CHECK (role IN ('PLATFORM_ADMIN', 'COMPANY_ADMIN', 'COMPANY_USER'))",
                row[0],
                flags=re.DOTALL,
            )
            new_sql = new_sql.replace('CREATE TABLE "users"', 'CREATE TABLE "users_new"').replace('CREATE TABLE users', 'CREATE TABLE users_new')
            bind.execute(sa.text(new_sql))
            bind.execute(sa.text("INSERT INTO users_new SELECT * FROM users"))
            bind.execute(sa.text("DROP TABLE users"))
            bind.execute(sa.text("ALTER TABLE users_new RENAME TO users"))
            for (index_sql,) in index_rows:
                bind.execute(sa.text(index_sql))
            bind.execute(sa.text("PRAGMA foreign_keys=ON"))


def downgrade() -> None:
    # Role consolidation is a one-way data migration (legacy role identity
    # is not recoverable once folded into the canonical roles). Widening the
    # constraint back to the legacy set would not restore the original
    # per-row role, so downgrade is intentionally a no-op.
    pass
