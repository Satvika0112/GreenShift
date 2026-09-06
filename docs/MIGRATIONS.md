# GreenShift — Database Migrations Guide (Alembic)

GreenShift uses **Alembic** alongside SQLAlchemy to manage schema migrations across PostgreSQL (production/staging) and SQLite (local testing & development).

---

## 1. Architecture & Single Source of Truth

- **ORM Schema Models**: Defined in [`app/shared/models.py`](file:///d:/Greenshift/app/shared/models.py).
- **Alembic Environment**: [`alembic/env.py`](file:///d:/Greenshift/alembic/env.py) reads connection parameters dynamically from [`app/shared/config.py`](file:///d:/Greenshift/app/shared/config.py) (`DATABASE_URL`).
- **Migrations Directory**: [`alembic/versions/`](file:///d:/Greenshift/alembic/versions/).

---

## 2. Running Migrations

### Upgrade Database to Latest Schema (Head)
```powershell
# Using Python Alembic CLI
alembic upgrade head
```

### Upgrade with Explicit Database URL Override
```powershell
$env:DATABASE_URL="postgresql://greenshift:secret@localhost:5432/greenshift"
alembic upgrade head
```

### Check Current Migration Revision
```powershell
alembic current
```

### View Migration History
```powershell
alembic history --verbose
```

### Downgrade / Rollback by One Step
```powershell
alembic downgrade -1
```

---

## 3. Creating New Migrations

### Auto-Generating Migrations from Model Changes
When adding or altering models in [`app/shared/models.py`](file:///d:/Greenshift/app/shared/models.py):

```powershell
alembic revision --autogenerate -m "describe your changes here"
```

This creates a new timestamped script in `alembic/versions/`.

### Reviewing Generated Migrations
Always inspect the generated file in `alembic/versions/` to verify:
1. Table/column existence checks for idempotency.
2. Dialect compatibility (SQLite batch mode and PostgreSQL native types).
3. Non-destructive changes (avoid dropping columns unless explicitly intended).

---

## 4. Programmatic Execution & Application Startup

During application startup (e.g. `init_db()` in [`app/shared/database.py`](file:///d:/Greenshift/app/shared/database.py)), migrations run automatically:

```python
from app.shared.database import init_db

# Runs table creation, Alembic migrations to head, and runtime index checks
init_db()
```

---

## 5. Migration History & Revisions

| Revision ID | Description | Down Revision |
|:---|:---|:---|
| `001_initial_postgresql_schema` | Core tables (`jobs`, `schedule_decisions`, `kubernetes_executions`, `audit_events`, `carbon_data`, `tariff_data`, `regional_tariffs`) | `None` (Genesis) |
| `002_add_approvals_table` | Human approval workflow table (`approvals`) | `001_initial_postgresql_schema` |
| `003_add_database_indexes` | Composite and performance indexes (`ix_jobs_team_status`, `ix_jobs_status_created`, `ix_approvals_job_decision`, etc.) | `002_add_approvals_table` |
