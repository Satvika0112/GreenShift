# GreenShift — Architecture Decisions

This document records significant technical decisions made during development.
Every agent must add entries here when making non-obvious implementation choices.

---

## ADR-001: Local Kubernetes Environment

**Date:** 2026-08-18
**Status:** Decided
**Decision:** Use Docker Desktop's built-in Kubernetes as the primary local development environment.

**Context:**
Two options were evaluated:
- Docker Desktop Kubernetes (built into Docker Desktop)
- Minikube

**Reasoning:**
- Docker Desktop Kubernetes requires zero additional installation for developers already using Docker Desktop.
- Docker Desktop Kubernetes shares the Docker image cache, so locally-built images are immediately available to Kubernetes without a registry push step.
- Minikube requires a separate `eval $(minikube docker-env)` step and more configuration.
- Both are fully supported. Minikube instructions are provided in the README as an alternative.

**Consequence:**
All manifests use `imagePullPolicy: IfNotPresent` to use locally-built images without a registry.

---

## ADR-002: Dispatcher Scheduling Mechanism

**Date:** 2026-08-18
**Status:** Decided
**Decision:** Use a time-aware dispatcher service (not Kubernetes CronJob) for the MVP.

**Context:**
Two options were evaluated:
- Kubernetes `CronJob` — schedule jobs via cron expressions
- Dispatcher service — holds the schedule in a DB, polls, and creates `Job` objects at the right time

**Reasoning:**
- CronJob cron expressions have 1-minute granularity, making precise scheduling difficult.
- CronJob management (creating, deleting CronJobs per schedule) adds significant complexity.
- The dispatcher-service approach allows sub-minute precision and is simpler to implement and test.
- The dispatcher stores `ScheduleDecision` in the DB and runs a polling loop every 30 seconds.
- When `now >= selected_start`, it calls the Kubernetes API to create the Job.

**Consequence:**
The dispatcher service must remain running. It is deployed as a Kubernetes Deployment.

---

## ADR-003: Database

**Date:** 2026-08-18
**Status:** Decided
**Decision:** Use SQLite for local development, PostgreSQL for production.

**Context:**
SQLite requires no separate service for development. PostgreSQL is used in the Kubernetes deployment.

**Reasoning:**
- SQLite is zero-config and keeps developer setup simple.
- Switching is handled by the `DATABASE_URL` environment variable.
- SQLAlchemy abstracts the difference.

**Consequence:**
All DB code must be compatible with both SQLite and PostgreSQL.

---

## ADR-004: Multi-Service Docker Strategy

**Date:** 2026-08-18
**Status:** Decided
**Decision:** One Dockerfile per service, sharing a common Python base.

**Context:**
Options: monolithic image OR per-service images.

**Reasoning:**
- Per-service images allow independent scaling and deployment.
- Each service has a different entry point and dependency set.
- Kubernetes orchestrates them independently.

**Consequence:**
Six Dockerfiles: `Dockerfile.api`, `Dockerfile.ingest`, `Dockerfile.scheduler`, `Dockerfile.dispatcher`, `Dockerfile.trust`, `Dockerfile.dashboard`.

---

## ADR-005: Audit Ledger Storage

**Date:** 2026-08-18
**Status:** Decided
**Decision:** Store audit events in the same database as the main application, in a dedicated `audit_events` table.

**Context:**
Options: separate audit DB, flat file, main DB table.

**Reasoning:**
- A dedicated table within the main DB is simple and transactional.
- SHA-256 chain is computed over the payload, not the storage mechanism.
- Tamper-evidence comes from the hash chain, not the storage.

**Consequence:**
Agent 4 owns the `audit_events` table schema.

---

*Last updated: Phase 0 — 2026-08-18*
