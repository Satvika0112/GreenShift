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

DEFAULT_TENANT = {
    "id": "tenant-default",
    "name": "GreenShift Dev Org",
}

DEFAULT_USERS = [
    {
        "username": "admin",
        "email": "admin@greenshift.dev",
        "password": "GreenShift-Admin-ChangeMeNow!",
        "role": UserRole.ADMIN,
        "team_id": "platform",
    },
    {
        "username": "operator",
        "email": "operator@greenshift.dev",
        "password": "GreenShift-Operator-ChangeMeNow!",
        "role": UserRole.OPERATOR,
        "team_id": "platform",
    },
    {
        "username": "viewer",
        "email": "viewer@greenshift.dev",
        "password": "GreenShift-Viewer-ChangeMeNow!",
        "role": UserRole.VIEWER,
        "team_id": "general",
    },
]


def ensure_tables():
    """Create all tables if they do not exist."""
    Base.metadata.create_all(bind=engine)
    print("✓ Tables ensured")


def seed_tenant(db: Session) -> TenantORM:
    """Create the default tenant if it doesn't exist."""
    tenant = db.get(TenantORM, DEFAULT_TENANT["id"])
    if tenant:
        print(f"  → Tenant '{tenant.id}' already exists — skipped")
        return tenant

    tenant = TenantORM(
        id=DEFAULT_TENANT["id"],
        name=DEFAULT_TENANT["name"],
        is_active=True,
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    print(f"  ✓ Created tenant: {tenant.id} ({tenant.name})")
    return tenant


def seed_users(db: Session, tenant_id: str) -> list:
    """Create default users if they don't exist."""
    created = []
    for u in DEFAULT_USERS:
        existing = db.query(UserORM).filter(UserORM.email == u["email"]).first()
        if existing:
            # Backfill tenant_id if missing
            if not existing.tenant_id:
                existing.tenant_id = tenant_id
                db.commit()
                print(f"  → Backfilled tenant_id for user '{existing.username}'")
            else:
                print(f"  → User '{existing.username}' already exists — skipped")
            continue

        user = UserORM(
            username=u["username"],
            email=u["email"],
            hashed_password=hash_password(u["password"]),
            role=u["role"],
            team_id=u["team_id"],
            tenant_id=tenant_id,
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
        print("\n[1/3] Seeding tenant...")
        tenant = seed_tenant(db)

        print(f"\n[2/3] Seeding users for tenant '{tenant.id}'...")
        created_users = seed_users(db, tenant.id)

        print(f"\n[3/3] Backfilling existing jobs...")
        jobs_updated = backfill_job_tenant_ids(db, tenant.id)

        print("\n" + "=" * 50)
        print("✅ Provisioning complete!")
        print(f"   Tenant: {tenant.id}")
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
