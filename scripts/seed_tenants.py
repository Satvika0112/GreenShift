#!/usr/bin/env python3
"""
GreenShift — Tenant & User Provisioning Script

Creates the default tenant, admin user, and operator user.
Backfills tenant_id on all existing jobs.

Usage:
    python scripts/seed_tenants.py

Safety:
    - Idempotent: safe to run multiple times; existing records are skipped.
    - Prints a password-change warning on first run.
    - Never prints passwords to stdout in production.

RULE 4: This is the ONLY way to create tenants (no /admin/tenants API endpoint).
"""

import os
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
import uuid
from datetime import datetime, timezone

# Ensure project root is in path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Force SQLite for dev seeding unless DATABASE_URL is explicitly set
os.environ.setdefault("DATABASE_URL", "sqlite:///./greenshift.db")

from sqlalchemy.orm import Session

from app.shared.database import init_db, SessionLocal, engine
from app.shared.models import Base, TenantORM, UserORM, UserRole, JobORM
from app.shared.auth import hash_password

# ─── Default tenant and user definitions ──────────────────────────────────────

DEFAULT_TENANTS = [
    {"id": "tenant-default", "name": "GreenShift Dev Org"},
    {"id": "tenant-acme", "name": "Acme Compute Corp"},
    {"id": "tenant-globex", "name": "Globex Cloud Services"},
]

DEFAULT_USERS = [
    {
        "tenant_id": "tenant-default",
        "username": "admin",
        "email": "admin@greenshift.dev",
        "password": "GreenShift-Admin-ChangeMeNow!",
        "role": UserRole.ADMIN,
        "team_id": "platform",
    },
    {
        "tenant_id": "tenant-default",
        "username": "operator",
        "email": "operator@greenshift.dev",
        "password": "GreenShift-Operator-ChangeMeNow!",
        "role": UserRole.OPERATOR,
        "team_id": "platform",
    },
    {
        "tenant_id": "tenant-default",
        "username": "viewer",
        "email": "viewer@greenshift.dev",
        "password": "GreenShift-Viewer-ChangeMeNow!",
        "role": UserRole.VIEWER,
        "team_id": "general",
    },
    {
        "tenant_id": "tenant-acme",
        "username": "acme_admin",
        "email": "admin@acme.com",
        "password": "Acme-Admin-ChangeMeNow!",
        "role": UserRole.ADMIN,
        "team_id": "team-acme",
    },
    {
        "tenant_id": "tenant-globex",
        "username": "globex_admin",
        "email": "admin@globex.com",
        "password": "Globex-Admin-ChangeMeNow!",
        "role": UserRole.ADMIN,
        "team_id": "team-globex",
    },
]


def ensure_tables():
    """Create all tables if they do not exist."""
    Base.metadata.create_all(bind=engine)
    print("✓ Tables ensured")


def seed_tenants(db: Session) -> list:
    """Create default tenants if they do not exist."""
    tenants = []
    for dt in DEFAULT_TENANTS:
        tenant = db.get(TenantORM, dt["id"])
        if tenant:
            print(f"  → Tenant '{tenant.id}' already exists — skipped")
            tenants.append(tenant)
            continue

        tenant = TenantORM(
            id=dt["id"],
            name=dt["name"],
            is_active=True,
        )
        db.add(tenant)
        db.commit()
        db.refresh(tenant)
        print(f"  ✓ Created tenant: {tenant.id} ({tenant.name})")
        tenants.append(tenant)
    return tenants


def seed_users(db: Session) -> list:
    """Create default users and company admins if they don't exist."""
    created = []
    for u in DEFAULT_USERS:
        existing = db.query(UserORM).filter(UserORM.email == u["email"]).first()
        if existing:
            # Backfill tenant_id and approval_status if missing
            updated = False
            if not existing.tenant_id:
                existing.tenant_id = u["tenant_id"]
                updated = True
            if not getattr(existing, "approval_status", None):
                existing.approval_status = "APPROVED"
                updated = True
            if updated:
                db.commit()
                print(f"  → Updated tenant/approval for user '{existing.username}'")
            else:
                print(f"  → User '{existing.username}' already exists — skipped")
            continue

        user = UserORM(
            username=u["username"],
            email=u["email"],
            hashed_password=hash_password(u["password"]),
            role=u["role"],
            team_id=u["team_id"],
            tenant_id=u["tenant_id"],
            approval_status="APPROVED",
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        created.append(user)
        print(f"  ✓ Created user: {user.username} ({user.role.value}) — {user.email}")

    return created


def backfill_job_tenant_ids(db: Session, tenant_id: str) -> int:
    """
    Assign the default tenant_id to all existing jobs that have no tenant.
    This ensures backward compatibility for the 560 pre-existing jobs.
    """
    jobs = db.query(JobORM).filter(JobORM.tenant_id == None).all()  # noqa: E711
    if not jobs:
        print(f"  → No jobs need tenant backfill")
        return 0

    for job in jobs:
        job.tenant_id = tenant_id

    db.commit()
    print(f"  ✓ Backfilled tenant_id='{tenant_id}' on {len(jobs)} existing jobs")
    return len(jobs)


def main():
    print("\n🌱 GreenShift Tenant Provisioning Script")
    print("=" * 50)

    ensure_tables()
    db = SessionLocal()

    try:
        print("\n[1/3] Seeding tenants...")
        tenants = seed_tenants(db)

        print(f"\n[2/3] Seeding admin users across tenants...")
        created_users = seed_users(db)

        print(f"\n[3/3] Backfilling existing jobs...")
        jobs_updated = backfill_job_tenant_ids(db, "tenant-default")

        print("\n" + "=" * 50)
        print("✅ Provisioning complete!")
        print(f"   Tenants ensured: {len(tenants)}")
        print(f"   Users created: {len(created_users)}")
        print(f"   Jobs backfilled: {jobs_updated}")

        if created_users:
            print("\n⚠️  IMPORTANT: Change all default passwords immediately!")
            print("   Default passwords are insecure and must be rotated before production use.")
            print("   Use POST /auth/login then PATCH /users/me/password (or admin panel).\n")

    finally:
        db.close()


if __name__ == "__main__":
    main()
