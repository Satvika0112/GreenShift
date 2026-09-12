"""
GreenShift — Shared Pydantic + SQLAlchemy Models

This is the single source of truth for all data models.
Every agent imports from here. Do NOT redefine models in individual agent modules.
"""

from __future__ import annotations

import enum
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship, foreign


# ─────────────────────────────────────────────────────────────────────────────
# SQLAlchemy Base & UTC Helper
# ─────────────────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    """Return current timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# Enumerations
# ─────────────────────────────────────────────────────────────────────────────

class JobStatus(str, enum.Enum):
    SUBMITTED        = "SUBMITTED"
    VALIDATED        = "VALIDATED"
    SCHEDULED        = "SCHEDULED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED         = "APPROVED"
    READY            = "READY"        # scheduled + selected_start <= now -> eligible for dispatch
    CLAIMING         = "CLAIMING"     # dispatcher worker holds atomic lease
    DECLINED         = "DECLINED"
    REJECTED         = "REJECTED"
    QUEUED           = "QUEUED"
    DISPATCHING      = "DISPATCHING"
    RUNNING          = "RUNNING"
    COMPLETED        = "COMPLETED"
    FAILED           = "FAILED"
    CANCELLED        = "CANCELLED"


class EventType(str, enum.Enum):
    JOB_SUBMITTED        = "JOB_SUBMITTED"
    JOB_VALIDATED        = "JOB_VALIDATED"
    JOB_SCHEDULED        = "JOB_SCHEDULED"
    SCHEDULE_PROPOSED    = "SCHEDULE_PROPOSED"
    APPROVAL_GRANTED     = "APPROVAL_GRANTED"
    APPROVAL_DECLINED    = "APPROVAL_DECLINED"
    DISPATCH_REQUESTED   = "DISPATCH_REQUESTED"
    DISPATCH_BLOCKED     = "DISPATCH_BLOCKED"
    DISPATCH_STARTED     = "DISPATCH_STARTED"
    DISPATCH_AUTHORIZED  = "DISPATCH_AUTHORIZED"
    K8S_JOB_CREATED      = "K8S_JOB_CREATED"
    K8S_JOB_STARTED      = "K8S_JOB_STARTED"
    K8S_JOB_COMPLETED    = "K8S_JOB_COMPLETED"
    K8S_JOB_FAILED       = "K8S_JOB_FAILED"
    JOB_CANCELLED        = "JOB_CANCELLED"
    BUDGET_UPDATED       = "BUDGET_UPDATED"
    EXPORT_GENERATED     = "EXPORT_GENERATED"
    SCHEDULING_FAILED    = "SCHEDULING_FAILED"
    EMAIL_DELIVERY_FAILED = "EMAIL_DELIVERY_FAILED"
    # ── Carbon Provenance & Resilience Events ──
    CARBON_API_SUCCESS   = "CARBON_API_SUCCESS"
    CARBON_CACHE_UPDATED = "CARBON_CACHE_UPDATED"
    CARBON_CACHE_USED    = "CARBON_CACHE_USED"
    CARBON_CACHE_STALE   = "CARBON_CACHE_STALE"
    CARBON_CSV_USED      = "CARBON_CSV_USED"
    CARBON_FALLBACK_USED = "CARBON_FALLBACK_USED"
    # ── Security & Authentication Events ──
    AUTH_LOGIN_SUCCESS   = "AUTH_LOGIN_SUCCESS"
    AUTH_LOGIN_FAILURE   = "AUTH_LOGIN_FAILURE"
    AUTH_ACCESS_DENIED   = "AUTH_ACCESS_DENIED"
    AUTH_USER_REGISTERED = "AUTH_USER_REGISTERED"
    AUTH_USER_ACTIVATED  = "AUTH_USER_ACTIVATED"
    AUTH_USER_DEACTIVATED = "AUTH_USER_DEACTIVATED"
    CONFIG_CHANGED       = "CONFIG_CHANGED"
    TENANT_CREATED       = "TENANT_CREATED"
    API_KEY_CREATED      = "API_KEY_CREATED"
    API_KEY_REVOKED      = "API_KEY_REVOKED"
    AUDIT_VERIFICATION_FAILED = "AUDIT_VERIFICATION_FAILED"
    JOB_RESUBMITTED      = "JOB_RESUBMITTED"
    # ── BRSR Reporting Events ──
    BRSR_REPORT_CREATED       = "BRSR_REPORT_CREATED"
    BRSR_STATUS_CHANGED       = "BRSR_STATUS_CHANGED"
    BRSR_METRIC_UPDATED       = "BRSR_METRIC_UPDATED"
    BRSR_VALIDATION_RUN       = "BRSR_VALIDATION_RUN"
    BRSR_REPORT_APPROVED      = "BRSR_REPORT_APPROVED"
    BRSR_REPORT_GENERATED     = "BRSR_REPORT_GENERATED"
    BRSR_REPORT_EXPORTED      = "BRSR_REPORT_EXPORTED"
    # ── Trust/Audit ledger events ──
    AUDIT_ANCHOR_CREATED      = "AUDIT_ANCHOR_CREATED"


class ActorType(str, enum.Enum):
    """Who/what performed an audited action. Never inferred from client input —
    USER means a real authenticated UserORM was resolved server-side; SYSTEM
    means the action originated from a background process with no human actor
    (scheduler loop, dispatcher poll, trust verification loop)."""
    USER   = "USER"
    SYSTEM = "SYSTEM"


class UserApprovalStatus(str, enum.Enum):
    APPROVED = "APPROVED"
    PENDING  = "PENDING"
    REJECTED = "REJECTED"


class UserRole(str, enum.Enum):
    """
    Canonical application roles. Exactly three are supported:

      PLATFORM_ADMIN — global platform administrator.
      COMPANY_ADMIN  — administrator of a single company/tenant.
      COMPANY_USER   — normal company user.

    Legacy values (ADMIN, TEAM_LEAD, OPERATOR, USER, VIEWER) are no longer
    active roles. Existing rows are normalized on startup — see
    app.shared.database.run_schema_migrations() and
    alembic/versions/009_consolidate_user_roles.py.
    """
    PLATFORM_ADMIN = "PLATFORM_ADMIN"
    COMPANY_ADMIN  = "COMPANY_ADMIN"
    COMPANY_USER   = "COMPANY_USER"


# ─────────────────────────────────────────────────────────────────────────────
# SQLAlchemy ORM — Tenant / Company
# ─────────────────────────────────────────────────────────────────────────────

class TenantORM(Base):
    """Multi-tenant organisation / Company."""

    __tablename__ = "tenants"

    id         = Column(String, primary_key=True)             # e.g. "tenant-acme"
    name       = Column(String, nullable=False, unique=True)  # e.g. "Acme Corp"
    is_active  = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    users    = relationship("UserORM", back_populates="tenant", foreign_keys="UserORM.tenant_id")
    api_keys = relationship("APIKeyORM", back_populates="tenant")
    jobs     = relationship("JobORM", back_populates="tenant", foreign_keys="JobORM.tenant_id")


# RULE 3: API keys can NEVER have an administrative role (PLATFORM_ADMIN / COMPANY_ADMIN)
API_KEY_ALLOWED_ROLES = {UserRole.COMPANY_USER}


# ─────────────────────────────────────────────────────────────────────────────
# SQLAlchemy ORM — User
# ─────────────────────────────────────────────────────────────────────────────

class UserORM(Base):
    """User account registry record for authentication and RBAC authorization."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "role IN ('PLATFORM_ADMIN', 'COMPANY_ADMIN', 'COMPANY_USER')",
            name="ck_users_role_valid",
        ),
    )

    id              = Column(Integer, primary_key=True, autoincrement=True)
    username        = Column(String(50), nullable=False, unique=True, index=True)
    email           = Column(String(255), nullable=False, unique=True, index=True)
    hashed_password = Column(String(255), nullable=False)
    role            = Column(SAEnum(UserRole), default=UserRole.COMPANY_USER, nullable=False, index=True)
    approval_status = Column(String(20), default="APPROVED", nullable=False, index=True)
    team_id         = Column(String, nullable=True, index=True)   # team within org
    tenant_id       = Column(String, ForeignKey("tenants.id"), nullable=True, index=True)  # org
    is_active       = Column(Boolean, default=True, nullable=False)
    created_at      = Column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    updated_at      = Column(DateTime(timezone=True), nullable=True, onupdate=utcnow)

    tenant = relationship("TenantORM", back_populates="users", foreign_keys=[tenant_id])

    @property
    def is_approved(self) -> bool:
        return (self.approval_status or "APPROVED") == "APPROVED"

    @property
    def company_name(self) -> Optional[str]:
        if self.tenant:
            return self.tenant.name
        return getattr(self, "_company_name", None)

    @company_name.setter
    def company_name(self, value: Optional[str]) -> None:
        self._company_name = value


# ─────────────────────────────────────────────────────────────────────────────
# SQLAlchemy ORM — APIKey
# ─────────────────────────────────────────────────────────────────────────────

class APIKeyORM(Base):
    """
    API key for CI/CD pipelines and automated systems.
    RULE 3: role can NEVER be an administrative role — enforced at creation time.
    """

    __tablename__ = "api_keys"

    id         = Column(String, primary_key=True)            # UUID
    key_hash   = Column(String, nullable=False, unique=True) # SHA-256 of raw key
    tenant_id  = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    role       = Column(SAEnum(UserRole), nullable=False, default=UserRole.COMPANY_USER)
    label      = Column(String, nullable=True)               # e.g. "CI pipeline"
    is_active  = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    last_used  = Column(DateTime(timezone=True), nullable=True)

    tenant = relationship("TenantORM", back_populates="api_keys")


# ─────────────────────────────────────────────────────────────────────────────
# SQLAlchemy ORM — Job
# ─────────────────────────────────────────────────────────────────────────────

class JobORM(Base):
    """Persistent job registry record."""

    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_team_status", "team_id", "status"),
        Index("ix_jobs_status_created", "status", "created_at"),
        Index("idx_jobs_dispatch_queue", "status", "priority", "deadline"),
        Index("idx_jobs_claim_lease", "status", "lease_expires_at"),
        CheckConstraint("runtime_minutes > 0", name="ck_jobs_runtime_minutes_positive"),
        CheckConstraint("power_kw > 0", name="ck_jobs_power_kw_positive"),
        CheckConstraint("carbon_budget_kg IS NULL OR carbon_budget_kg >= 0", name="ck_jobs_carbon_budget_non_negative"),
        CheckConstraint("energy_kwh IS NULL OR energy_kwh >= 0", name="ck_jobs_energy_kwh_non_negative"),
        CheckConstraint("status IN ('SUBMITTED', 'VALIDATED', 'SCHEDULED', 'PENDING_APPROVAL', 'APPROVED', 'READY', 'CLAIMING', 'DECLINED', 'REJECTED', 'QUEUED', 'DISPATCHING', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED')", name="ck_jobs_status_valid"),
    )

    job_id               = Column(String, primary_key=True)
    workload_name        = Column(String, nullable=True)   # workload name/identifier
    team_id              = Column(String, nullable=False, index=True)  # team within org — NOT removed
    tenant_id            = Column(String, ForeignKey("tenants.id"), nullable=True, index=True)  # org (nullable for backward compat)
    submitted_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)  # server-derived from authenticated identity
    submitted_at         = Column(DateTime(timezone=True), nullable=False, index=True)
    deadline             = Column(DateTime(timezone=True), nullable=False, index=True)
    runtime_minutes      = Column(Integer, nullable=False)
    power_kw             = Column(Float, nullable=False)
    region               = Column(String, nullable=False, index=True)
    timezone             = Column(String, nullable=True, default="UTC")
    status               = Column(SAEnum(JobStatus), default=JobStatus.SUBMITTED, nullable=False, index=True)
    container_image      = Column(String, nullable=False)
    cpu_request          = Column(String, default="500m")
    memory_request       = Column(String, default="512Mi")
    carbon_budget_kg     = Column(Float, nullable=True)
    # ── Real-dataset fields (added for workloads CSV integration) ──
    job_type             = Column(String, nullable=True)   # e.g. DATA_PROCESSING, ETL
    priority             = Column(String, nullable=True)   # CRITICAL / HIGH / MEDIUM / LOW
    earliest_start_time  = Column(DateTime(timezone=True), nullable=True) # job cannot start before this
    energy_kwh           = Column(Float, nullable=True)    # pre-computed or power_kw * runtime_h
    deferrable           = Column(Boolean, nullable=True)  # True = can be shifted for savings
    # ── Dispatch claiming metadata ──
    claimed_by           = Column(String, nullable=True)   # worker_id of the dispatcher that claimed this job
    claimed_at           = Column(DateTime(timezone=True), nullable=True)    # when the claim was made
    lease_expires_at     = Column(DateTime(timezone=True), nullable=True)    # claim auto-expires after this time
    created_at           = Column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    updated_at           = Column(DateTime(timezone=True), nullable=True, onupdate=utcnow)

    # Relationships
    schedule_decision = relationship(
        "ScheduleDecisionORM",
        back_populates="job",
        uselist=False,
        cascade="all, delete-orphan",
        foreign_keys="ScheduleDecisionORM.job_id",
    )
    schedule_decisions = relationship(
        "ScheduleDecisionORM",
        cascade="all, delete-orphan",
        order_by="ScheduleDecisionORM.created_at.desc()",
        viewonly=True,
    )
    kubernetes_execution = relationship(
        "KubernetesExecutionORM",
        back_populates="job",
        uselist=False,
        cascade="all, delete-orphan",
        foreign_keys="KubernetesExecutionORM.job_id",
    )
    executions = relationship(
        "KubernetesExecutionORM",
        cascade="all, delete-orphan",
        order_by="KubernetesExecutionORM.created_at.desc()",
        viewonly=True,
    )
    approvals = relationship(
        "ApprovalORM",
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="ApprovalORM.created_at.desc()",
    )
    audit_events = relationship(
        "AuditEventORM",
        primaryjoin="JobORM.job_id==foreign(AuditEventORM.job_id)",
        viewonly=True,
        order_by="AuditEventORM.sequence.asc()",
    )
    tenant = relationship(
        "TenantORM",
        back_populates="jobs",
        foreign_keys=[tenant_id],
    )

    @property
    def company_name(self) -> Optional[str]:
        if self.tenant:
            return self.tenant.name
        return getattr(self, "_company_name", None)

    @company_name.setter
    def company_name(self, value: Optional[str]) -> None:
        self._company_name = value


# ─────────────────────────────────────────────────────────────────────────────
# SQLAlchemy ORM — ScheduleDecision
# ─────────────────────────────────────────────────────────────────────────────

class ScheduleDecisionORM(Base):
    """Output of the DECIDE agent — the chosen execution window."""

    __tablename__ = "schedule_decisions"
    __table_args__ = (
        Index("ix_schedule_decisions_job_created", "job_id", "created_at"),
        CheckConstraint("selected_end > selected_start", name="ck_schedule_decisions_time_window"),
        CheckConstraint("carbon_emission >= 0", name="ck_schedule_decisions_carbon_emission_non_negative"),
        CheckConstraint("electricity_cost >= 0", name="ck_schedule_decisions_electricity_cost_non_negative"),
        CheckConstraint("carbon_intensity >= 0", name="ck_schedule_decisions_carbon_intensity_non_negative"),
    )

    id                = Column(Integer, primary_key=True, autoincrement=True)
    job_id            = Column(String, ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    selected_start    = Column(DateTime(timezone=True), nullable=False, index=True)
    selected_end      = Column(DateTime(timezone=True), nullable=False, index=True)
    carbon_intensity  = Column(Float, nullable=False)   # gCO2/kWh
    electricity_cost  = Column(Float, nullable=False)   # total cost in USD
    carbon_emission   = Column(Float, nullable=False)   # kg CO2
    optimization_score = Column(Float, nullable=True)
    reason            = Column(Text, nullable=False)
    budget_remaining  = Column(Float, nullable=True)
    created_at        = Column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)

    # Regional & Currency context
    region_id          = Column(String, nullable=True, default="IN-TG", index=True)
    tariff_plan        = Column(String, nullable=True)
    currency           = Column(String, nullable=True, default="USD")
    native_cost        = Column(Float, nullable=True)
    baseline_native_cost = Column(Float, nullable=True)

    # Tariff audit: raw INR/native rate before currency conversion
    tariff_inr_per_kwh = Column(Float, nullable=True)  # Legacy & INR rate at selected window
    tariff_category    = Column(String, nullable=True)  # "ht1a" / "ht2a" or plan identifier

    # Baseline comparison & Impact metrics
    baseline_start           = Column(DateTime(timezone=True), nullable=True)
    baseline_end             = Column(DateTime(timezone=True), nullable=True)
    baseline_carbon_emission = Column(Float, nullable=True)  # kg CO2
    baseline_cost            = Column(Float, nullable=True)    # $ USD
    carbon_avoided           = Column(Float, nullable=True)    # kg CO2
    cost_difference          = Column(Float, nullable=True)    # $ USD
    carbon_reduction_pct     = Column(Float, nullable=True)    # %
    cost_reduction_pct       = Column(Float, nullable=True)    # %
    scheduling_delay_hours   = Column(Float, nullable=True)    # hours delayed from earliest bound
    sla_met                  = Column(Boolean, nullable=True, default=True) # completion <= deadline

    # Decision Explainability
    candidates_evaluated      = Column(Integer, nullable=True, default=0)
    feasible_candidates_count = Column(Integer, nullable=True, default=0)
    rejection_summary         = Column(JSON, nullable=True)
    scheduler_objective       = Column(String, nullable=True, default="CARBON_FIRST")
    deterministic_rank        = Column(Integer, nullable=True, default=1)
    candidates_json           = Column(JSON, nullable=True)
    rejected_candidates_json  = Column(JSON, nullable=True)
    recommended_candidate_json = Column(JSON, nullable=True)

    # Contention-aware scheduling metadata
    scheduling_method       = Column(String, nullable=True, default="single_greedy")
    slot_utilization_pct    = Column(Float, nullable=True)
    demand_predicted        = Column(Float, nullable=True)
    spilled_from_preferred  = Column(Boolean, nullable=True, default=False)
    ml_advisor_used         = Column(Boolean, nullable=True, default=False)

    job = relationship("JobORM", back_populates="schedule_decision", foreign_keys=[job_id])
    approvals = relationship(
        "ApprovalORM",
        back_populates="schedule_decision",
        cascade="all, delete-orphan",
        order_by="ApprovalORM.created_at.desc()",
    )

    @property
    def decision_id(self) -> int:
        return self.id

    @property
    def estimated_emissions(self) -> float:
        return self.carbon_emission


# ─────────────────────────────────────────────────────────────────────────────
# SQLAlchemy ORM — Approval
# ─────────────────────────────────────────────────────────────────────────────

class ApprovalORM(Base):
    """Human approval record for a proposed schedule decision."""

    __tablename__ = "approvals"
    __table_args__ = (
        Index("ix_approvals_job_decision", "job_id", "decision"),
        Index("ix_approvals_schedule_decision", "schedule_decision_id", "decision"),
        CheckConstraint("decision IN ('APPROVED', 'DECLINED')", name="ck_approvals_decision_valid"),
    )

    id                   = Column(Integer, primary_key=True, autoincrement=True)
    job_id               = Column(String, ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False, index=True)
    schedule_decision_id = Column(Integer, ForeignKey("schedule_decisions.id", ondelete="CASCADE"), nullable=False, index=True)
    decision             = Column(String, nullable=False, index=True)   # "APPROVED" or "DECLINED"
    reason               = Column(Text, nullable=True)
    approved_by          = Column(String, nullable=True, default="admin")
    created_at           = Column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    updated_at           = Column(DateTime(timezone=True), nullable=True, onupdate=utcnow)

    # Relationships
    job = relationship("JobORM", back_populates="approvals")
    schedule_decision = relationship("ScheduleDecisionORM", back_populates="approvals")


# ─────────────────────────────────────────────────────────────────────────────
# SQLAlchemy ORM — KubernetesExecution
# ─────────────────────────────────────────────────────────────────────────────

class KubernetesExecutionORM(Base):
    """Kubernetes Job execution tracking — owned by DISPATCH agent."""

    __tablename__ = "kubernetes_executions"
    __table_args__ = (
        Index("ix_k8s_executions_job_status", "job_id", "gs_status"),
        CheckConstraint("planned_end IS NULL OR planned_start IS NULL OR planned_end > planned_start", name="ck_k8s_executions_planned_time_window"),
        CheckConstraint("actual_end IS NULL OR actual_start IS NULL OR actual_end >= actual_start", name="ck_k8s_executions_actual_time_window"),
        CheckConstraint("gs_status IN ('SUBMITTED', 'SCHEDULED', 'PENDING_APPROVAL', 'APPROVED', 'READY', 'CLAIMING', 'DECLINED', 'QUEUED', 'RUNNING', 'COMPLETED', 'FAILED')", name="ck_k8s_executions_status_valid"),
    )

    id                   = Column(Integer, primary_key=True, autoincrement=True)
    job_id               = Column(String, ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    kubernetes_job_name  = Column(String, nullable=False, index=True)
    kubernetes_namespace = Column(String, nullable=False, default="greenshift")
    pod_name             = Column(String, nullable=True)
    planned_start        = Column(DateTime(timezone=True), nullable=False, index=True)
    actual_start         = Column(DateTime(timezone=True), nullable=True)
    planned_end          = Column(DateTime(timezone=True), nullable=True)
    actual_end           = Column(DateTime(timezone=True), nullable=True)
    k8s_status           = Column(String, nullable=True)   # raw Kubernetes status
    gs_status            = Column(SAEnum(JobStatus), nullable=False, default=JobStatus.QUEUED, index=True)
    error_message        = Column(Text, nullable=True)
    created_at           = Column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    updated_at           = Column(DateTime(timezone=True), nullable=True, onupdate=utcnow)

    job = relationship("JobORM", back_populates="kubernetes_execution", foreign_keys=[job_id])

    @property
    def execution_id(self) -> int:
        return self.id


# ─────────────────────────────────────────────────────────────────────────────
# SQLAlchemy ORM — AuditEvent
# ─────────────────────────────────────────────────────────────────────────────

class AuditEventORM(Base):
    """Tamper-evident audit ledger — owned by TRUST agent.

    tenant_id/team_id/actor_*/request_id/source_service are denormalized
    columns for efficient RBAC-scoped querying, but they are never the sole
    source of truth: append_event() also folds them into payload_json before
    computing payload_hash, and verify_chain() cross-checks these columns
    against that hashed payload on every verification pass — so a direct DB
    edit of e.g. actor_role or tenant_id (bypassing the hash chain entirely)
    is still detected. See app/trust/ledger.py.
    """

    __tablename__ = "audit_events"
    __table_args__ = (
        UniqueConstraint("sequence", name="uq_audit_events_sequence"),
        Index("ix_audit_events_job_sequence", "job_id", "sequence"),
        Index("ix_audit_events_tenant_sequence", "tenant_id", "sequence"),
        Index("ix_audit_events_team_sequence", "team_id", "sequence"),
    )

    event_id       = Column(String, primary_key=True)
    timestamp      = Column(DateTime(timezone=True), nullable=False, index=True)
    event_type     = Column(SAEnum(EventType), nullable=False, index=True)
    job_id         = Column(String, nullable=True, index=True)
    payload_hash   = Column(String(64), nullable=False)   # SHA-256 hex
    previous_hash  = Column(String(64), nullable=False)   # SHA-256 hex (genesis = 0*64)
    current_hash   = Column(String(64), nullable=False)   # SHA-256 hex
    payload_json   = Column(Text, nullable=False)         # serialised event payload
    sequence       = Column(Integer, nullable=False, unique=True, index=True)  # monotonically increasing and globally unique

    # ── Actor identity & request context (P0) — always server-derived, never
    # accepted from client input. NULL is the honest value when genuinely
    # not applicable (e.g. team_id for a tenant-wide event, or every actor_*
    # field for a SYSTEM-originated background event). ──
    tenant_id      = Column(String, nullable=True, index=True)
    team_id        = Column(String, nullable=True, index=True)
    actor_user_id  = Column(String, nullable=True, index=True)
    actor_username = Column(String, nullable=True)
    actor_role     = Column(String, nullable=True)
    actor_type     = Column(String, nullable=True, index=True)  # ActorType.USER / SYSTEM
    request_id     = Column(String, nullable=True, index=True)
    source_service = Column(String, nullable=True)

    @property
    def payload(self) -> dict:
        if not self.payload_json:
            return {}
        try:
            return json.loads(self.payload_json)
        except Exception:
            return {}

    @property
    def reason(self) -> Optional[str]:
        """Human-readable reason/detail for this event, when the recording
        code supplied one (e.g. the scheduler's actual infeasibility reason
        for SCHEDULING_FAILED, or a dispatch-blocked reason) — never
        fabricated; None when the event genuinely has no reason to show."""
        return self.payload.get("reason")


# ── Append-only DB protection ────────────────────────────────────────────────
# Defense in depth beyond the hash chain: block UPDATE/DELETE on audit_events
# at the database level itself, so a compromised application layer (or a
# direct DB console) cannot silently rewrite history without also breaking
# the cryptographic chain. Registered as `after_create` DDL so it fires for
# every path that creates this table — Base.metadata.create_all() (fresh dev
# DB, the in-memory test DB) as well as being re-asserted idempotently by
# alembic/versions/012_add_trust_audit_context.py for an EXISTING table on a
# populated dev/prod DB (create_all() is a no-op there, so the DDL event
# would never fire again on ITS OWN — the migration issues the same DDL
# directly for that path).
from sqlalchemy import event as _sa_event
from sqlalchemy.schema import DDL as _DDL

_SQLITE_AUDIT_APPEND_ONLY_DDL = _DDL(
    """
    CREATE TRIGGER IF NOT EXISTS trg_audit_events_no_update
    BEFORE UPDATE ON audit_events
    BEGIN
        SELECT RAISE(ABORT, 'audit_events is append-only: UPDATE is not permitted');
    END;
    """
)
_SQLITE_AUDIT_APPEND_ONLY_DELETE_DDL = _DDL(
    """
    CREATE TRIGGER IF NOT EXISTS trg_audit_events_no_delete
    BEFORE DELETE ON audit_events
    BEGIN
        SELECT RAISE(ABORT, 'audit_events is append-only: DELETE is not permitted');
    END;
    """
)
_PG_AUDIT_APPEND_ONLY_DDL = _DDL(
    """
    CREATE OR REPLACE FUNCTION fn_audit_events_append_only()
    RETURNS TRIGGER AS $$
    BEGIN
        RAISE EXCEPTION 'audit_events is append-only: % is not permitted', TG_OP;
    END;
    $$ LANGUAGE plpgsql;

    DROP TRIGGER IF EXISTS trg_audit_events_append_only ON audit_events;
    CREATE TRIGGER trg_audit_events_append_only
    BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION fn_audit_events_append_only();
    """
)

_sa_event.listen(
    AuditEventORM.__table__, "after_create",
    _SQLITE_AUDIT_APPEND_ONLY_DDL.execute_if(dialect="sqlite"),
)
_sa_event.listen(
    AuditEventORM.__table__, "after_create",
    _SQLITE_AUDIT_APPEND_ONLY_DELETE_DDL.execute_if(dialect="sqlite"),
)
_sa_event.listen(
    AuditEventORM.__table__, "after_create",
    _PG_AUDIT_APPEND_ONLY_DDL.execute_if(dialect="postgresql"),
)


class AuditAnchorORM(Base):
    """A historical, DB-backed checkpoint of the audit chain's root hash.

    Complements (does not replace) the pre-existing external JSONL anchor
    file in app/trust/anchor.py — the file remains an additional
    tamper-evidence boundary outside the database itself, while this table
    is what makes "list historical anchors" and "verify a specific
    historical anchor" possible without re-parsing a flat file.
    """

    __tablename__ = "audit_anchors"

    id                 = Column(Integer, primary_key=True, autoincrement=True)
    sequence           = Column(Integer, nullable=False, index=True)
    root_hash          = Column(String(64), nullable=False)
    event_count        = Column(Integer, nullable=False)
    created_at         = Column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    created_by_user_id = Column(String, nullable=True)  # server-derived Platform Admin id — never client-supplied
    label              = Column(String, nullable=True)


# ─────────────────────────────────────────────────────────────────────────────
# SQLAlchemy ORM — CarbonDataPoint
# ─────────────────────────────────────────────────────────────────────────────

class CarbonDataPointORM(Base):
    """Cached carbon intensity data points with multi-level resilience metadata."""

    __tablename__ = "carbon_data"
    __table_args__ = (
        Index("ix_carbon_data_region_timestamp", "region", "timestamp"),
        CheckConstraint("carbon_gco2_kwh >= 0", name="ck_carbon_data_intensity_non_negative"),
    )

    id                = Column(Integer, primary_key=True, autoincrement=True)
    timestamp         = Column(DateTime(timezone=True), nullable=False, index=True)
    region            = Column(String, nullable=False, index=True)
    carbon_gco2_kwh   = Column(Float, nullable=False)
    fetched_at        = Column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    source            = Column(String, nullable=False, default="electricity_maps")
    expires_at        = Column(DateTime(timezone=True), nullable=True)
    em_zone           = Column(String, nullable=True)
    confidence_status = Column(String, nullable=True)
    is_fallback       = Column(Boolean, nullable=False, default=False)
    fallback_reason   = Column(String, nullable=True)


# ─────────────────────────────────────────────────────────────────────────────
# SQLAlchemy ORM — TariffDataPointORM
# ─────────────────────────────────────────────────────────────────────────────

class TariffDataPointORM(Base):
    """Cached tariff data points."""

    __tablename__ = "tariff_data"
    __table_args__ = (
        Index("ix_tariff_data_region_timestamp", "region", "timestamp"),
        CheckConstraint("price_per_kwh >= 0", name="ck_tariff_data_price_non_negative"),
    )

    id            = Column(Integer, primary_key=True, autoincrement=True)
    timestamp     = Column(DateTime(timezone=True), nullable=False, index=True)
    region        = Column(String, nullable=False, index=True)
    price_per_kwh = Column(Float, nullable=False)
    fetched_at    = Column(DateTime(timezone=True), nullable=False, default=utcnow)


# ─────────────────────────────────────────────────────────────────────────────
# SQLAlchemy ORM — RegionalTariffORM (Canonical Common Schema)
# ─────────────────────────────────────────────────────────────────────────────

class RegionalTariffORM(Base):
    """
    Canonical regional tariff data persistence layer.
    Supports India regions: Telangana (IN-TG), Gujarat (IN-GJ), Himachal Pradesh (IN-HP), West Bengal (IN-WB).
    """

    __tablename__ = "regional_tariffs"
    __table_args__ = (
        Index("ix_regional_tariffs_region_plan_time", "region_id", "tariff_plan", "timestamp"),
        CheckConstraint("electricity_rate >= 0", name="ck_regional_tariffs_rate_non_negative"),
        CheckConstraint("price_per_kwh_usd >= 0", name="ck_regional_tariffs_usd_rate_non_negative"),
    )


    id                 = Column(Integer, primary_key=True, autoincrement=True)
    region_id          = Column(String, nullable=False, index=True)   # IN-TG, IN-GJ, IN-HP, IN-WB
    country            = Column(String, nullable=False, default="India")
    region_name        = Column(String, nullable=False)               # Telangana, Gujarat, Himachal Pradesh, West Bengal
    tariff_plan        = Column(String, nullable=False, index=True)   # HT-I(A), HT-II(A), HTP-I, Large Industry - EHT, Industries (Rate E-BT)
    timestamp          = Column(DateTime(timezone=True), nullable=False, index=True) # UTC timestamp
    local_timestamp    = Column(DateTime(timezone=True), nullable=False)             # Local wall-clock timestamp (Asia/Kolkata)
    timezone           = Column(String, nullable=False, default="Asia/Kolkata")
    season             = Column(String, nullable=True)
    tod_block          = Column(String, nullable=True)                # Night, Solar, Peak, Normal, Off-Peak, Flat (No ToD)
    time_period        = Column(String, nullable=False)               # Normal, Peak, Off-Peak, Solar, Night, Flat
    base_energy_rate   = Column(Float, nullable=True)                 # Base energy charge INR/kWh
    tod_adder          = Column(Float, nullable=True)                 # ToD adder INR/kWh
    electricity_rate   = Column(Float, nullable=False)                # Effective rate INR/kWh
    currency           = Column(String, nullable=False, default="INR")
    is_peak_hour       = Column(Boolean, nullable=False, default=False)
    is_solar_hour      = Column(Boolean, nullable=False, default=False)
    is_night_hour      = Column(Boolean, nullable=False, default=False)
    category           = Column(String, nullable=True)                # Raw dataset category description
    voltage            = Column(String, nullable=True)                # Supply voltage (e.g. 11 kV, 66 kV)
    tariff_year        = Column(String, nullable=True)                # FY2026-27
    effective_from     = Column(String, nullable=True)
    effective_to       = Column(String, nullable=True)
    source             = Column(String, nullable=False)
    demand_charge      = Column(Float, nullable=True)
    fixed_charge       = Column(Float, nullable=True)
    price_per_kwh_usd  = Column(Float, nullable=False)                # Normalized USD rate for calculations
    created_at         = Column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)


# ─────────────────────────────────────────────────────────────────────────────
# SQLAlchemy ORM — Notification
# ─────────────────────────────────────────────────────────────────────────────

class NotificationORM(Base):
    """
    In-app / email notification record.

    Recipient is always server-derived (never client-supplied). Email delivery
    is tracked separately from in-app state so an email failure can never
    affect workload/business state — see app.notify.email.
    """

    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("recipient_user_id", "dedup_key", name="uq_notifications_recipient_dedup"),
        Index("ix_notifications_recipient_read", "recipient_user_id", "read_at"),
        Index("ix_notifications_email_pending", "email_status", "next_attempt_at"),
        CheckConstraint(
            "severity IN ('INFO', 'WARNING', 'CRITICAL')",
            name="ck_notifications_severity_valid",
        ),
        CheckConstraint(
            "email_status IN ('NOT_REQUIRED', 'PENDING', 'SENT', 'FAILED')",
            name="ck_notifications_email_status_valid",
        ),
    )

    id                 = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id          = Column(String, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True, index=True)
    recipient_user_id  = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    job_id             = Column(String, nullable=True, index=True)
    event_type         = Column(SAEnum(EventType), nullable=False, index=True)
    category           = Column(String(30), nullable=False, index=True)  # SCHEDULING/APPROVAL/EXECUTION/ACCOUNT/SECURITY/INFRASTRUCTURE
    severity           = Column(String(20), nullable=False, default="INFO")
    title              = Column(String, nullable=False)
    message            = Column(Text, nullable=False)
    action_url         = Column(String, nullable=True)
    created_at         = Column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    read_at            = Column(DateTime(timezone=True), nullable=True)

    # Idempotency: "<event_type>:<job_id-or-none>[:<suffix>]" — a second
    # identical event for the same recipient is a no-op, not a duplicate row.
    dedup_key          = Column(String, nullable=False)

    # Email delivery lifecycle — independent of the business transaction.
    email_required     = Column(Boolean, nullable=False, default=False)
    email_status       = Column(String(20), nullable=False, default="NOT_REQUIRED")
    email_attempts     = Column(Integer, nullable=False, default=0)
    email_sent_at      = Column(DateTime(timezone=True), nullable=True)
    email_failed_at    = Column(DateTime(timezone=True), nullable=True)
    last_error         = Column(Text, nullable=True)
    next_attempt_at    = Column(DateTime(timezone=True), nullable=True)

    @property
    def is_read(self) -> bool:
        return self.read_at is not None


class NotificationPreferenceORM(Base):
    """
    Per-user email notification preferences, one row per user (lazily
    created with all-enabled defaults on first read/write — see
    app.notify.service.get_or_create_preferences). Only the email channel
    is gated by preference; in-app notifications are never suppressed.

    `email_system` covers ACCOUNT/SECURITY/INFRASTRUCTURE categories and is
    intentionally not exposed as editable by NotificationPreferenceUpdateRequest —
    security-critical notifications cannot be silenced by the recipient.
    """

    __tablename__ = "notification_preferences"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    user_id          = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    email_workload   = Column(Boolean, nullable=False, default=True)
    email_scheduling = Column(Boolean, nullable=False, default=True)
    email_approval   = Column(Boolean, nullable=False, default=True)
    email_execution  = Column(Boolean, nullable=False, default=True)
    email_system     = Column(Boolean, nullable=False, default=True)
    created_at       = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at       = Column(DateTime(timezone=True), nullable=True, onupdate=utcnow)


# ─────────────────────────────────────────────────────────────────────────────
# SQLAlchemy ORM — BRSR (Business Responsibility and Sustainability Reporting)
#
# Architecture: one tenant-scoped report header (BrsrReportORM) drives a
# flexible metric registry (BrsrMetricDefinitionORM, global reference data —
# not tenant-scoped) whose answers are stored generically in
# BrsrMetricValueORM (one row per report+metric). This single generic value
# table serves Section A/B, all 9 principles, and all 9 BRSR Core categories
# alike — the registry's `section`/`principle`/`brsr_core_attribute` columns
# classify each answer, so adding/changing a metric never requires a schema
# change or new page component. A separate one-row-per-tenant company
# profile table holds the static company-identity fields BRSR always needs
# (CIN, sector, listed status, headcount, ...), since those aren't really
# "reporting period metrics" in the same sense.
# ─────────────────────────────────────────────────────────────────────────────

class BrsrReportStatus(str, enum.Enum):
    DRAFT            = "DRAFT"
    DATA_COLLECTION  = "DATA_COLLECTION"
    VALIDATED        = "VALIDATED"
    APPROVED         = "APPROVED"
    GENERATED        = "GENERATED"


# Only these forward transitions are legal — enforced server-side in
# app.brsr.service, never trusted from the client. Matches the linear
# lifecycle in the spec; there is deliberately no "reject/reopen" transition
# yet since BRSR doesn't ask for one — a report needing rework is edited
# in DATA_COLLECTION-equivalent state by re-deriving from DRAFT is out of
# scope until a real workflow need is demonstrated.
BRSR_STATUS_TRANSITIONS: Dict[str, str] = {
    BrsrReportStatus.DRAFT.value: BrsrReportStatus.DATA_COLLECTION.value,
    BrsrReportStatus.DATA_COLLECTION.value: BrsrReportStatus.VALIDATED.value,
    BrsrReportStatus.VALIDATED.value: BrsrReportStatus.APPROVED.value,
    BrsrReportStatus.APPROVED.value: BrsrReportStatus.GENERATED.value,
}


class BrsrSourceType(str, enum.Enum):
    GREENSHIFT_DERIVED = "GREENSHIFT_DERIVED"
    COMPANY_PROVIDED   = "COMPANY_PROVIDED"
    CALCULATED         = "CALCULATED"
    ESTIMATED          = "ESTIMATED"
    EXTERNAL_SOURCE    = "EXTERNAL_SOURCE"
    MISSING            = "MISSING"


class BrsrDataQuality(str, enum.Enum):
    HIGH    = "HIGH"
    MEDIUM  = "MEDIUM"
    LOW     = "LOW"
    MISSING = "MISSING"


class BrsrSection(str, enum.Enum):
    SECTION_A = "SECTION_A"   # General disclosures
    SECTION_B = "SECTION_B"   # Management & process (governance)
    SECTION_C = "SECTION_C"   # Principle-wise performance
    CORE      = "CORE"        # BRSR Core (9 attributes, subset of Section C)


class BrsrCompanyProfileORM(Base):
    """
    One row per tenant — static BRSR company-identity fields. Every field is
    COMPANY_PROVIDED by definition (there is no GreenShift-derivable company
    registration data), so provenance is tracked once at the row level
    rather than per-field as with BrsrMetricValueORM. Nothing here is ever
    inferred or defaulted from operational data — a field left blank stays
    NULL until a Company Admin enters it.
    """

    __tablename__ = "brsr_company_profiles"

    id                 = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id          = Column(String, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)

    company_name       = Column(String, nullable=True)
    cin                = Column(String(21), nullable=True)   # Corporate Identity Number (India) — 21 chars
    sector             = Column(String, nullable=True)
    industry           = Column(String, nullable=True)
    listed_status      = Column(String, nullable=True)       # "LISTED" / "UNLISTED"
    stock_exchange     = Column(String, nullable=True)
    isin               = Column(String(12), nullable=True)
    locations          = Column(JSON, nullable=True)         # [{"type": "registered_office"|"plant"|..., "address": "...", "state": "...", "country": "..."}]
    products_services  = Column(JSON, nullable=True)         # [{"name": "...", "nic_code": "...", "pct_turnover": ...}]
    employees_count    = Column(Integer, nullable=True)
    workers_count       = Column(Integer, nullable=True)
    revenue            = Column(Float, nullable=True)
    revenue_currency   = Column(String(3), nullable=True)
    net_worth          = Column(Float, nullable=True)
    net_worth_currency = Column(String(3), nullable=True)
    capital            = Column(Float, nullable=True)        # paid-up capital
    capital_currency   = Column(String(3), nullable=True)
    reporting_boundary = Column(Text, nullable=True)

    # Structured currency-conversion provenance for the monetary fields above
    # (Phase 14) — keyed by field name, e.g. {"revenue": {"original_value":
    # ..., "original_currency": "USD", "reporting_currency": "INR",
    # "converted_value": ..., "exchange_rate": ..., "exchange_rate_date":
    # ..., "conversion_source": "..."}}. Never auto-populated with a
    # fabricated rate — only ever written when the Company Admin/an
    # integration supplies a real rate + source.
    currency_conversions = Column(JSON, nullable=True)

    source_type = Column(String, nullable=False, default=BrsrSourceType.COMPANY_PROVIDED.value)
    updated_by  = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at  = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at  = Column(DateTime(timezone=True), nullable=True, onupdate=utcnow)


class BrsrReportORM(Base):
    """One BRSR report per tenant per financial year."""

    __tablename__ = "brsr_reports"
    __table_args__ = (
        UniqueConstraint("tenant_id", "financial_year", name="uq_brsr_reports_tenant_fy"),
        CheckConstraint(
            "status IN ('DRAFT', 'DATA_COLLECTION', 'VALIDATED', 'APPROVED', 'GENERATED')",
            name="ck_brsr_reports_status_valid",
        ),
    )

    id                     = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id              = Column(String, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    financial_year         = Column(String(10), nullable=False)   # e.g. "2025-26"
    reporting_period_start = Column(DateTime(timezone=True), nullable=False)
    reporting_period_end   = Column(DateTime(timezone=True), nullable=False)
    framework_version      = Column(String(20), nullable=False, default="BRSR-2023")
    status                 = Column(String(20), nullable=False, default=BrsrReportStatus.DRAFT.value, index=True)

    created_by  = Column(Integer, ForeignKey("users.id"), nullable=False)
    approved_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    created_at   = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at   = Column(DateTime(timezone=True), nullable=True, onupdate=utcnow)
    validated_at = Column(DateTime(timezone=True), nullable=True)
    approved_at  = Column(DateTime(timezone=True), nullable=True)
    generated_at = Column(DateTime(timezone=True), nullable=True)

    metric_values = relationship("BrsrMetricValueORM", back_populates="report", cascade="all, delete-orphan")


class BrsrMetricDefinitionORM(Base):
    """
    The metric/question registry (Phase 4) — global reference data, not
    tenant-scoped. A framework/version change (e.g. a future BRSR revision)
    is handled by adding new rows with a new `framework_version` and
    `effective_from`, never by rewriting application code.
    """

    __tablename__ = "brsr_metric_definitions"
    __table_args__ = (
        CheckConstraint(
            "section IN ('SECTION_A', 'SECTION_B', 'SECTION_C', 'CORE')",
            name="ck_brsr_metric_def_section_valid",
        ),
    )

    metric_code          = Column(String(80), primary_key=True)
    metric_name          = Column(String, nullable=False)
    principle            = Column(Integer, nullable=True)   # 1-9, null for Section A/B
    section              = Column(String(20), nullable=False, index=True)
    brsr_core_attribute  = Column(String(60), nullable=True, index=True)
    unit                 = Column(String(40), nullable=True)
    data_type            = Column(String(20), nullable=False, default="NUMERIC")  # NUMERIC/PERCENTAGE/TEXT/BOOLEAN
    required             = Column(Boolean, nullable=False, default=False)
    calculation_method   = Column(Text, nullable=True)
    framework_version    = Column(String(20), nullable=False, default="BRSR-2023")
    effective_from       = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    effective_to         = Column(DateTime(timezone=True), nullable=True)
    description          = Column(Text, nullable=True)
    # Whether app.brsr.calculations can auto-derive this metric from real
    # GreenShift operational data (jobs/energy/carbon). False for anything
    # that only a company can know (headcount, board composition, ...).
    greenshift_derivable = Column(Boolean, nullable=False, default=False)


class BrsrMetricValueORM(Base):
    """
    One answer to one registry metric for one report. Generic by design
    (Phase 3/4) — this single table backs Section A/B, every principle, and
    every BRSR Core category; which "page" a row belongs to is purely a
    property of its `metric_code`'s registry definition, not of this table.
    """

    __tablename__ = "brsr_metric_values"
    __table_args__ = (
        UniqueConstraint("report_id", "metric_code", name="uq_brsr_metric_values_report_metric"),
        CheckConstraint(
            "source_type IN ('GREENSHIFT_DERIVED', 'COMPANY_PROVIDED', 'CALCULATED', 'ESTIMATED', 'EXTERNAL_SOURCE', 'MISSING')",
            name="ck_brsr_metric_values_source_type_valid",
        ),
        CheckConstraint(
            "quality IN ('HIGH', 'MEDIUM', 'LOW', 'MISSING')",
            name="ck_brsr_metric_values_quality_valid",
        ),
    )

    id          = Column(Integer, primary_key=True, autoincrement=True)
    report_id   = Column(Integer, ForeignKey("brsr_reports.id", ondelete="CASCADE"), nullable=False, index=True)
    metric_code = Column(String(80), ForeignKey("brsr_metric_definitions.metric_code"), nullable=False, index=True)

    # A missing value is NULL, never a fabricated 0 — see BrsrSourceType.MISSING.
    value       = Column(Float, nullable=True)
    text_value  = Column(Text, nullable=True)     # narrative/boolean-as-text answers
    unit        = Column(String(40), nullable=True)
    currency    = Column(String(3), nullable=True)

    source_type   = Column(String(20), nullable=False, default=BrsrSourceType.MISSING.value)
    source_record = Column(String, nullable=True)     # short reference, e.g. "job:JOB-123" or "manual-entry"
    source_detail = Column(JSON, nullable=True)        # richer lineage payload (e.g. list of job_ids + calc inputs)

    quality            = Column(String(20), nullable=False, default=BrsrDataQuality.MISSING.value)
    estimated          = Column(Boolean, nullable=False, default=False)
    estimation_method  = Column(Text, nullable=True)
    assumption         = Column(Text, nullable=True)
    data_gap           = Column(Text, nullable=True)

    # Currency conversion provenance (Phase 14) — only populated when a real
    # rate + source is supplied; never fabricated.
    reporting_currency = Column(String(3), nullable=True)
    exchange_rate      = Column(Float, nullable=True)
    exchange_rate_date = Column(DateTime(timezone=True), nullable=True)
    conversion_source  = Column(String, nullable=True)
    converted_value    = Column(Float, nullable=True)

    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=utcnow)

    report = relationship("BrsrReportORM", back_populates="metric_values")


class BrsrValidationRunORM(Base):
    """One execution of the validation engine (Phase 10) against a report."""

    __tablename__ = "brsr_validation_runs"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    report_id  = Column(Integer, ForeignKey("brsr_reports.id", ondelete="CASCADE"), nullable=False, index=True)
    run_at     = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    run_by     = Column(Integer, ForeignKey("users.id"), nullable=True)
    status     = Column(String(20), nullable=False)   # PASSED / FAILED / WARNINGS
    error_count   = Column(Integer, nullable=False, default=0)
    warning_count = Column(Integer, nullable=False, default=0)
    info_count    = Column(Integer, nullable=False, default=0)

    issues = relationship("BrsrValidationIssueORM", back_populates="run", cascade="all, delete-orphan")


class BrsrValidationIssueORM(Base):
    """One finding from a validation run."""

    __tablename__ = "brsr_validation_issues"
    __table_args__ = (
        CheckConstraint("severity IN ('ERROR', 'WARNING', 'INFO')", name="ck_brsr_validation_issues_severity_valid"),
    )

    id           = Column(Integer, primary_key=True, autoincrement=True)
    run_id       = Column(Integer, ForeignKey("brsr_validation_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    metric_code  = Column(String(80), nullable=True, index=True)
    severity     = Column(String(10), nullable=False)
    code         = Column(String(60), nullable=False)
    message      = Column(Text, nullable=False)
    suggested_resolution = Column(Text, nullable=True)

    run = relationship("BrsrValidationRunORM", back_populates="issues")


class BrsrAssessmentORM(Base):
    """
    Assessment/Assurance record (Phase 22) — purely a record of
    company-provided assurance information. GreenShift itself never
    performs or claims independent assessment/assurance.
    """

    __tablename__ = "brsr_assessments"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    report_id           = Column(Integer, ForeignKey("brsr_reports.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    assessment_status   = Column(String(30), nullable=True)   # NOT_ASSESSED / INTERNAL_REVIEW / EXTERNAL_ASSURANCE
    assessor_name       = Column(String, nullable=True)
    assessor_type       = Column(String(20), nullable=True)   # INTERNAL / EXTERNAL
    assessment_date     = Column(DateTime(timezone=True), nullable=True)
    scope               = Column(Text, nullable=True)
    notes               = Column(Text, nullable=True)
    evidence_reference  = Column(Text, nullable=True)
    source_type         = Column(String, nullable=False, default=BrsrSourceType.COMPANY_PROVIDED.value)
    updated_by          = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at          = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at          = Column(DateTime(timezone=True), nullable=True, onupdate=utcnow)


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic Schemas — Request / Response & Regional Common Schema
# ─────────────────────────────────────────────────────────────────────────────

class RegionalTariffRecord(BaseModel):
    """Canonical Regional Tariff Data Schema."""

    model_config = ConfigDict(from_attributes=True)

    region_id:         str
    country:           str = "India"
    region_name:       str
    tariff_plan:       str
    timestamp:         datetime
    local_timestamp:   datetime
    timezone:          str = "Asia/Kolkata"
    season:            Optional[str] = None
    tod_block:         Optional[str] = None
    time_period:       str
    base_energy_rate:  Optional[float] = None
    tod_adder:         Optional[float] = None
    electricity_rate:  float
    currency:          str = "INR"
    is_peak_hour:      bool = False
    is_solar_hour:     bool = False
    is_night_hour:     bool = False
    category:          Optional[str] = None
    voltage:           Optional[str] = None
    tariff_year:       Optional[str] = None
    effective_from:    Optional[str] = None
    effective_to:      Optional[str] = None
    source:            str
    demand_charge:     Optional[float] = None
    fixed_charge:      Optional[float] = None
    price_per_kwh_usd: float


class JobSubmitRequest(BaseModel):
    """API request body for POST /api/v1/jobs"""

    # Core fields (required)
    workload_name:    Optional[str] = Field(None, max_length=200, description="User-facing workload name, preserved through the lifecycle")
    team_id:          str   = Field(..., min_length=1, max_length=100, description="Team identifier")
    deadline:         datetime = Field(..., description="Latest allowed start+runtime end time (UTC)")
    runtime_minutes:  int   = Field(..., gt=0, le=10080, description="Expected runtime in minutes (max 7 days = 10080 mins)")
    power_kw:         float = Field(..., gt=0, le=100000.0, description="Average power draw in kW (max 100 MW)")
    region:           str   = Field(..., min_length=2, max_length=50, description="Grid region code, e.g. IN-TG, IN-GJ, IN-HP, IN-WB")
    container_image:  str   = Field(..., min_length=1, max_length=255, description="Docker image to run as Kubernetes Job")
    cpu_request:      str   = Field(default="500m", description="Kubernetes CPU request")
    memory_request:   str   = Field(default="512Mi", description="Kubernetes memory request")
    carbon_budget_kg: Optional[float] = Field(None, ge=0.0, description="Max carbon budget in kg CO2")
    submit_time:         Optional[datetime] = Field(None, description="Original submit timestamp from workload dataset")
    job_id:              Optional[str]      = Field(None, max_length=100, description="Preserve original job ID from CSV")
    job_type:            Optional[str]      = Field(None, max_length=100, description="Workload type, e.g. DATA_PROCESSING")
    priority:            Optional[str]      = Field(None, description="CRITICAL/HIGH/MEDIUM/LOW")
    earliest_start_time: Optional[datetime] = Field(None, description="Job cannot start before this time")
    energy_kwh:          Optional[float]    = Field(None, ge=0.0, description="Pre-computed energy consumption (kWh)")
    deferrable:          Optional[bool]     = Field(None, description="True = can be shifted for carbon savings")
    tariff_plan:         Optional[str]      = Field(None, max_length=100, description="Explicit tariff plan override")
    timezone:            Optional[str]      = Field(None, max_length=100, description="Optional IANA timezone name, e.g. Asia/Kolkata, America/New_York")

    @field_validator("region")
    @classmethod
    def validate_region(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Region cannot be empty")
        cleaned = v.strip().upper()
        from app.ingest.regional_registry import get_region_config
        try:
            cfg = get_region_config(cleaned)
            return cfg.region_id
        except Exception as exc:
            raise ValueError(f"Unsupported or invalid region '{v}'. Must be a recognized grid zone (e.g. IN-TG, IN-GJ, IN-HP, IN-WB, US-CA, SE).") from exc

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        cleaned = v.strip().upper()
        allowed = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
        if cleaned not in allowed:
            raise ValueError(f"Invalid priority '{v}'. Allowed values: {', '.join(sorted(allowed))}")
        return cleaned

    @field_validator("cpu_request")
    @classmethod
    def validate_cpu_request(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("cpu_request cannot be empty")
        s = v.strip().lower()
        try:
            if s.endswith("m"):
                millicores = float(s[:-1])
                if millicores <= 0:
                    raise ValueError("cpu_request must be positive")
                if millicores > 256000:
                    raise ValueError("cpu_request exceeds maximum limit (256 cores)")
            else:
                cores = float(s)
                if cores <= 0:
                    raise ValueError("cpu_request must be positive")
                if cores > 256:
                    raise ValueError("cpu_request exceeds maximum limit (256 cores)")
        except ValueError as exc:
            if "must be positive" in str(exc) or "exceeds" in str(exc):
                raise
            raise ValueError(f"Invalid cpu_request format '{v}'. Expected format: '500m', '2', '1.5'") from exc
        return v.strip()

    @field_validator("memory_request")
    @classmethod
    def validate_memory_request(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("memory_request cannot be empty")
        s = v.strip()
        import re
        match = re.match(r"^([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z]*)$", s)
        if not match:
            raise ValueError(f"Invalid memory_request format '{v}'. Expected format: '512Mi', '4Gi', '1024Ki'")
        num_str, unit = match.groups()
        num = float(num_str)
        if num <= 0:
            raise ValueError("memory_request must be positive")
        unit_lower = unit.lower()
        valid_units = {"", "b", "k", "ki", "m", "mi", "g", "gi", "t", "ti"}
        if unit_lower not in valid_units:
            raise ValueError(f"Invalid memory unit '{unit}'. Allowed: Ki, Mi, Gi, Ti")
        mult = {"": 1/(1024**3), "b": 1/(1024**3), "k": 1/(1024**2), "ki": 1/(1024**2), "m": 1/1024, "mi": 1/1024, "g": 1.0, "gi": 1.0, "t": 1024.0, "ti": 1024.0}
        gib = num * mult.get(unit_lower, 1.0)
        if gib > 2048:
            raise ValueError("memory_request exceeds maximum limit (2048 GiB)")
        return v.strip()


class JobSubmitResponse(BaseModel):
    job_id:       str
    status:       JobStatus
    submitted_at: datetime
    name:         Optional[str] = None


class CarbonDataPoint(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    timestamp:          datetime
    region:             str
    carbon_gco2_kwh:    float
    source:             str = "electricity_maps"
    fetched_at:         Optional[datetime] = None
    expires_at:         Optional[datetime] = None
    is_fallback:        bool = False
    fallback_reason:    Optional[str] = None
    cache_age_seconds:  Optional[float] = None
    em_zone:            Optional[str] = None


class TariffDataPoint(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    timestamp:     datetime
    region:        str
    price_per_kwh: float


class ScheduleDecision(BaseModel):
    """Output of the DECIDE agent."""

    model_config = ConfigDict(from_attributes=True)

    id:               Optional[int] = None
    job_id:           str
    selected_start:   datetime
    selected_end:     datetime
    carbon_intensity: float   # gCO2/kWh at selected window
    electricity_cost: float   # total cost in USD (energy_kwh * price_per_kwh_usd)
    carbon_emission:  float   # kg CO2 = energy_kwh * carbon_gco2_kwh / 1000
    reason:           str
    budget_remaining: Optional[float] = None

    # Decision Explainability
    objective:                 Optional[str] = "CARBON_FIRST"
    scheduler_objective:       Optional[str] = "CARBON_FIRST"
    candidates_evaluated:      Optional[int] = 0
    feasible_candidates_count: Optional[int] = 0
    rejection_summary:         Optional[Dict[str, int]] = Field(default_factory=dict)
    rejection_reasons:         Optional[List[str]] = Field(default_factory=list)
    deterministic_ranking:     Optional[int] = 1
    deterministic_rank:        Optional[int] = 1
    recommended_candidate:     Optional[Dict[str, Any]] = None
    candidates:                Optional[List[Dict[str, Any]]] = Field(default_factory=list)
    rejected_candidates:       Optional[List[Dict[str, Any]]] = Field(default_factory=list)

    # Regional & Currency context
    region_id:            Optional[str] = "IN-TG"
    tariff_plan:          Optional[str] = None
    currency:             Optional[str] = "USD"
    native_cost:          Optional[float] = None
    baseline_native_cost: Optional[float] = None
    tariff_inr_per_kwh:   Optional[float] = None  # raw INR/native rate for backwards compatibility
    tariff_category:      Optional[str]   = None  # plan identifier

    # Baseline comparison & Impact metrics
    baseline_start:            Optional[datetime] = None
    baseline_end:              Optional[datetime] = None
    baseline_carbon_emission:  Optional[float]    = None
    baseline_cost:             Optional[float]    = None
    carbon_avoided:            Optional[float]    = None
    cost_difference:           Optional[float]    = None
    carbon_reduction_pct:      Optional[float]    = None
    cost_reduction_pct:        Optional[float]    = None
    scheduling_delay_hours:    Optional[float]    = None
    sla_met:                   Optional[bool]     = True

    # Contention-aware scheduling metadata
    scheduling_method:         Optional[str]      = "single_greedy"
    slot_utilization_pct:      Optional[float]    = None
    demand_predicted:          Optional[float]    = None
    spilled_from_preferred:    Optional[bool]     = False
    ml_advisor_used:           Optional[bool]     = False


class KubernetesExecution(BaseModel):
    """Status of a dispatched Kubernetes Job."""

    model_config = ConfigDict(from_attributes=True)

    job_id:               str
    kubernetes_job_name:  str
    kubernetes_namespace: str
    pod_name:             Optional[str]    = None
    planned_start:        datetime
    actual_start:         Optional[datetime] = None
    planned_end:          Optional[datetime] = None
    actual_end:           Optional[datetime] = None
    k8s_status:           Optional[str]    = None
    gs_status:            JobStatus


class AuditEvent(BaseModel):
    """A single audit ledger entry."""

    model_config = ConfigDict(from_attributes=True)

    event_id:      str
    timestamp:     datetime
    event_type:    EventType
    job_id:        Optional[str]
    payload_hash:  str
    previous_hash: str
    current_hash:  str
    sequence:      int

    tenant_id:      Optional[str] = None
    team_id:        Optional[str] = None
    actor_user_id:  Optional[str] = None
    actor_username: Optional[str] = None
    actor_role:     Optional[str] = None
    actor_type:     Optional[str] = None
    request_id:     Optional[str] = None
    source_service: Optional[str] = None
    reason:         Optional[str] = None


class AuditVerifyResponse(BaseModel):
    valid:       bool
    event_count: int
    message:     str

    # Structured failure diagnostics — populated only when valid is False.
    # Kept optional/additive so existing callers reading valid/event_count/
    # message are unaffected.
    failed_check:      Optional[str] = None
    failed_sequence:   Optional[int] = None
    expected_sequence: Optional[int] = None
    actual_sequence:   Optional[int] = None
    reason:            Optional[str] = None


class AuditAnchor(BaseModel):
    """A historical, DB-backed audit chain checkpoint."""

    model_config = ConfigDict(from_attributes=True)

    id:                 int
    sequence:           int
    root_hash:          str
    event_count:        int
    created_at:         datetime
    created_by_user_id: Optional[str] = None
    label:              Optional[str] = None


class AnchorVerifyResult(BaseModel):
    status:        str
    verified:      bool
    message:       str
    anchor:        Optional[Dict[str, Any]] = None
    total_anchors: Optional[int] = None
    failed_check:  Optional[str] = None


class DashboardSummary(BaseModel):
    """Aggregate summary for dashboard."""

    jobs: dict
    carbon: dict
    cost: dict
    audit: dict
    regional: Optional[dict] = None


class ApprovalRequest(BaseModel):
    """Request schema for approving or declining a proposed schedule."""

    schedule_id: int = Field(..., description="ID of the ScheduleDecisionORM")
    reason: Optional[str] = Field(None, description="Optional approval comment or required decline justification")


class ApprovalResponse(BaseModel):
    """Response schema for approval decision."""

    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = None
    job_id: str
    schedule_decision_id: int
    decision: str
    job_status: JobStatus
    reason: Optional[str] = None
    approved_by: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class PendingApprovalItem(BaseModel):
    """Detailed item for pending approval listing."""

    model_config = ConfigDict(from_attributes=True)

    job_id: str
    workload_name: Optional[str] = None
    job_type: Optional[str] = None
    priority: Optional[str] = None
    team_id: str
    region: str
    timezone: Optional[str] = "UTC"
    schedule_id: int
    selected_start_utc: datetime
    selected_start_local: datetime
    selected_end_utc: datetime
    selected_end_local: datetime
    runtime_minutes: int
    power_kw: float
    carbon_intensity: float
    carbon_emission_kg: float
    electricity_cost_usd: float
    deadline_utc: datetime
    deadline_local: datetime
    status: JobStatus
    tariff_plan: Optional[str] = None
    scheduler_objective: Optional[str] = "CARBON_FIRST"
    objective: Optional[str] = "CARBON_FIRST"
    reason: Optional[str] = None
    candidates_evaluated: Optional[int] = 0
    feasible_candidates_count: Optional[int] = 0
    rejection_summary: Optional[Dict[str, int]] = Field(default_factory=dict)
    rejection_reasons: Optional[List[str]] = Field(default_factory=list)
    deterministic_ranking: Optional[int] = 1
    deterministic_rank: Optional[int] = 1
    # ── Decision-support fields (Phase 5): all sourced directly from
    # existing ScheduleDecisionORM / JobORM columns — no new computation. ──
    carbon_budget_kg: Optional[float] = None
    currency: Optional[str] = "USD"
    native_cost: Optional[float] = None
    baseline_carbon_emission_kg: Optional[float] = None
    baseline_cost_usd: Optional[float] = None
    baseline_native_cost: Optional[float] = None
    baseline_start_utc: Optional[datetime] = None
    baseline_start_local: Optional[datetime] = None
    carbon_avoided_kg: Optional[float] = None
    cost_difference_usd: Optional[float] = None
    carbon_reduction_pct: Optional[float] = None
    sla_met: Optional[bool] = None


class ApprovalHistoryItem(BaseModel):
    """A single decided (approved or declined) schedule, for the Approvals
    History tab. Sourced from ApprovalORM joined with its job and schedule
    decision — no new storage, no separate audit ledger."""

    model_config = ConfigDict(from_attributes=True)

    job_id: str
    workload_name: Optional[str] = None
    decision: str  # "APPROVED" or "DECLINED"
    team_id: Optional[str] = None
    tenant_id: Optional[str] = None
    region: Optional[str] = None
    scheduled_start_utc: Optional[datetime] = None
    decided_by: Optional[str] = None
    decided_at: datetime
    reason: Optional[str] = None


class UserRegisterRequest(BaseModel):
    """Payload for user registration."""

    username: str = Field(..., min_length=3, max_length=50, description="Unique username")
    email: str = Field(..., description="User email address")
    password: str = Field(..., min_length=6, description="Plaintext password")
    role: Optional[UserRole] = Field(
        default=UserRole.COMPANY_USER,
        description="User role (ignored on public /auth/register where all users receive COMPANY_USER; honored only for authenticated admin user creation)",
    )
    team_id: Optional[str] = Field(default=None, description="Optional team identifier")
    tenant_id: Optional[str] = Field(default=None, description="Optional company / tenant identifier")


class UserLoginRequest(BaseModel):
    """Payload for user login."""

    username: Optional[str] = Field(None, description="Username or email")
    username_or_email: Optional[str] = Field(None, description="Username or email alias")
    email: Optional[str] = Field(None, description="Email alias")
    password: str = Field(..., description="User password")

    @model_validator(mode="before")
    @classmethod
    def resolve_username(cls, data: object) -> object:
        if isinstance(data, dict):
            u = data.get("username") or data.get("username_or_email") or data.get("email")
            if u:
                data["username"] = u
                data["username_or_email"] = u
                data["email"] = u
            elif not data.get("username"):
                raise ValueError("Username or email is required")
        return data


class UserResponse(BaseModel):
    """User profile response without exposing password hash."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    role: UserRole
    team_id: Optional[str] = None
    tenant_id: Optional[str] = None
    company_name: Optional[str] = None
    approval_status: Optional[str] = "APPROVED"
    is_active: bool
    created_at: datetime


class TokenResponse(BaseModel):
    """JWT authentication token response."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse


class CompanyResponse(BaseModel):
    """Company / Tenant profile response."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    is_active: bool
    created_at: datetime
    user_count: Optional[int] = 0
    workload_count: Optional[int] = 0


class CompanyCreateRequest(BaseModel):
    """Platform Admin request to create a new company/tenant."""
    id: Optional[str] = Field(None, description="Company identifier slug (e.g. tenant-acme)")
    name: str = Field(..., min_length=2, max_length=100, description="Company display name")
    is_active: bool = True


class CompanyUpdateRequest(BaseModel):
    """Update company details."""
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    is_active: Optional[bool] = None


class UserStatusUpdateRequest(BaseModel):
    """Admin request to update user approval, role, or active status."""
    approval_status: Optional[str] = Field(None, description="APPROVED, PENDING, REJECTED")
    is_active: Optional[bool] = Field(None, description="Account active state")
    role: Optional[UserRole] = Field(None, description="Assigned role")


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1 Multi-Tenant Auth Schemas
# ─────────────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    """Email + password login (tenant-aware)."""
    email: str = Field(..., description="User email address")
    password: str = Field(..., description="User password")


class LoginResponse(BaseModel):
    """Response from POST /auth/login."""
    access_token: str
    token_type: str = "bearer"
    tenant_id: Optional[str] = None
    role: str
    expires_in: int


class UserCreateRequest(BaseModel):
    """Company Admin / Platform Admin user creation within own tenant."""
    email: str = Field(..., description="User email address")
    password: str = Field(..., min_length=6, description="Password")
    role: UserRole = Field(default=UserRole.COMPANY_USER)
    username: Optional[str] = Field(None, description="Optional username; defaults to email prefix")
    team_id: Optional[str] = Field(None, description="Optional team within the tenant")
    tenant_id: Optional[str] = Field(None, description="Target tenant ID (Platform Admin only)")


class TenantUserResponse(BaseModel):
    """User profile response including tenant context."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    role: UserRole
    tenant_id: Optional[str] = None
    team_id: Optional[str] = None
    is_active: bool
    created_at: datetime


class APIKeyCreateRequest(BaseModel):
    """Company Admin / Platform Admin API key creation. Role must not be administrative."""
    label: Optional[str] = Field(None, description="Human-readable label e.g. 'CI pipeline'")
    role: UserRole = Field(default=UserRole.COMPANY_USER, description="Role for API key (cannot be PLATFORM_ADMIN/COMPANY_ADMIN)")
    tenant_id: Optional[str] = Field(None, description="Target tenant ID (Platform Admin only)")


class APIKeyCreateResponse(BaseModel):
    """Response from POST /admin/api-keys — raw key shown ONCE only."""
    key_id: str
    api_key: str   # raw key — shown only at creation time
    tenant_id: str
    role: str
    label: Optional[str] = None
    created_at: datetime


class APIKeyListItem(BaseModel):
    """API key list entry — never exposes raw key or hash."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    role: UserRole
    label: Optional[str] = None
    is_active: bool
    created_at: datetime
    last_used: Optional[datetime] = None


class TenantResponse(BaseModel):
    """Tenant info response."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    is_active: bool
    created_at: datetime


class NotificationResponse(BaseModel):
    """Notification list/detail item."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: Optional[str] = None
    event_type: EventType
    category: str
    severity: str
    title: str
    message: str
    action_url: Optional[str] = None
    created_at: datetime
    read_at: Optional[datetime] = None
    is_read: bool = False


class UnreadCountResponse(BaseModel):
    unread_count: int


class NotificationPreferenceResponse(BaseModel):
    """Current user's email notification preferences."""
    model_config = ConfigDict(from_attributes=True)

    email_workload: bool
    email_scheduling: bool
    email_approval: bool
    email_execution: bool
    # Security-critical — always true, included read-only for transparency.
    email_system: bool = True


class NotificationPreferenceUpdateRequest(BaseModel):
    """
    Partial update — only the categories a user may actually disable.
    `email_system` is deliberately not a field here: security/account/
    infrastructure notifications cannot be silenced by preference.
    """
    email_workload: Optional[bool] = None
    email_scheduling: Optional[bool] = None
    email_approval: Optional[bool] = None
    email_execution: Optional[bool] = None


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic Schemas — BRSR
# ─────────────────────────────────────────────────────────────────────────────

class BrsrCompanyProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tenant_id: str
    company_name: Optional[str] = None
    cin: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    listed_status: Optional[str] = None
    stock_exchange: Optional[str] = None
    isin: Optional[str] = None
    locations: Optional[List[Dict[str, Any]]] = None
    products_services: Optional[List[Dict[str, Any]]] = None
    employees_count: Optional[int] = None
    workers_count: Optional[int] = None
    revenue: Optional[float] = None
    revenue_currency: Optional[str] = None
    net_worth: Optional[float] = None
    net_worth_currency: Optional[str] = None
    capital: Optional[float] = None
    capital_currency: Optional[str] = None
    reporting_boundary: Optional[str] = None
    currency_conversions: Optional[Dict[str, Any]] = None
    source_type: str
    updated_at: Optional[datetime] = None


class BrsrCompanyProfileUpdateRequest(BaseModel):
    """
    Company Admin-editable fields only. There is deliberately no
    `tenant_id`/`source_type`/`updated_by` field here — recipient/company
    identity for a write is always the authenticated caller's own
    `tenant_id`, never anything the client supplies (see app/brsr/service.py).
    """
    company_name: Optional[str] = None
    cin: Optional[str] = Field(None, max_length=21)
    sector: Optional[str] = None
    industry: Optional[str] = None
    listed_status: Optional[str] = None
    stock_exchange: Optional[str] = None
    isin: Optional[str] = Field(None, max_length=12)
    locations: Optional[List[Dict[str, Any]]] = None
    products_services: Optional[List[Dict[str, Any]]] = None
    employees_count: Optional[int] = Field(None, ge=0)
    workers_count: Optional[int] = Field(None, ge=0)
    revenue: Optional[float] = Field(None, ge=0)
    revenue_currency: Optional[str] = Field(None, min_length=3, max_length=3)
    net_worth: Optional[float] = None
    net_worth_currency: Optional[str] = Field(None, min_length=3, max_length=3)
    capital: Optional[float] = Field(None, ge=0)
    capital_currency: Optional[str] = Field(None, min_length=3, max_length=3)
    reporting_boundary: Optional[str] = None

    @field_validator("listed_status")
    @classmethod
    def validate_listed_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("LISTED", "UNLISTED"):
            raise ValueError("listed_status must be 'LISTED' or 'UNLISTED'")
        return v


class BrsrReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: str
    financial_year: str
    reporting_period_start: datetime
    reporting_period_end: datetime
    framework_version: str
    status: str
    created_by: int
    approved_by: Optional[int] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    validated_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    generated_at: Optional[datetime] = None


class BrsrStatusTransitionRequest(BaseModel):
    target_status: str

    @field_validator("target_status")
    @classmethod
    def validate_target_status(cls, v: str) -> str:
        valid = {s.value for s in BrsrReportStatus}
        if v not in valid:
            raise ValueError(f"target_status must be one of {sorted(valid)}")
        return v


class BrsrReportCreateRequest(BaseModel):
    financial_year: str = Field(..., pattern=r"^\d{4}-\d{2}$", description="e.g. 2025-26")
    reporting_period_start: datetime
    reporting_period_end: datetime
    framework_version: str = "BRSR-2023"

    @model_validator(mode="after")
    def validate_period(self) -> "BrsrReportCreateRequest":
        if self.reporting_period_end <= self.reporting_period_start:
            raise ValueError("reporting_period_end must be after reporting_period_start")
        return self


class BrsrMetricDefinitionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    metric_code: str
    metric_name: str
    principle: Optional[int] = None
    section: str
    brsr_core_attribute: Optional[str] = None
    unit: Optional[str] = None
    data_type: str
    required: bool
    calculation_method: Optional[str] = None
    framework_version: str
    description: Optional[str] = None
    greenshift_derivable: bool


class BrsrMetricValueResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    report_id: int
    metric_code: str
    value: Optional[float] = None
    text_value: Optional[str] = None
    unit: Optional[str] = None
    currency: Optional[str] = None
    source_type: str
    source_record: Optional[str] = None
    source_detail: Optional[Dict[str, Any]] = None
    quality: str
    estimated: bool
    estimation_method: Optional[str] = None
    assumption: Optional[str] = None
    data_gap: Optional[str] = None
    reporting_currency: Optional[str] = None
    exchange_rate: Optional[float] = None
    exchange_rate_date: Optional[datetime] = None
    conversion_source: Optional[str] = None
    converted_value: Optional[float] = None
    updated_at: Optional[datetime] = None


class BrsrMetricValueWithDefinition(BrsrMetricValueResponse):
    """Metric value joined with its registry definition — the shape the
    BRSR Core/Environmental/Social/Governance UI pages actually consume."""
    metric_name: str
    principle: Optional[int] = None
    section: str
    brsr_core_attribute: Optional[str] = None
    data_type: str
    required: bool
    calculation_method: Optional[str] = None
    description: Optional[str] = None


class BrsrMetricValueUpdateRequest(BaseModel):
    """
    Company Admin-editable answer fields. `quality`/`report_id`/`metric_code`
    are always server-derived — quality is recomputed from completeness, not
    client-supplied, and the row identity comes from the URL, not the body.

    `source_type` is deliberately restricted to the two provenance tiers a
    Company Admin can honestly self-declare — COMPANY_PROVIDED (the default
    when omitted) or EXTERNAL_SOURCE (e.g. a utility bill or third-party
    auditor's figure). GREENSHIFT_DERIVED and CALCULATED remain permanently
    unreachable through this endpoint (see app/brsr/service.py::update_metric_value)
    — a client can never claim automated-derivation provenance for its own
    manual entry — and MISSING isn't a value someone "sets", it's the
    absence of one.
    """
    value: Optional[float] = None
    text_value: Optional[str] = None
    unit: Optional[str] = None
    currency: Optional[str] = Field(None, min_length=3, max_length=3)
    source_type: Optional[str] = None
    estimated: Optional[bool] = None
    estimation_method: Optional[str] = None
    assumption: Optional[str] = None
    data_gap: Optional[str] = None
    reporting_currency: Optional[str] = Field(None, min_length=3, max_length=3)
    exchange_rate: Optional[float] = Field(None, gt=0)
    exchange_rate_date: Optional[datetime] = None
    conversion_source: Optional[str] = None

    @field_validator("source_type")
    @classmethod
    def validate_source_type(cls, v: Optional[str]) -> Optional[str]:
        allowed = {"COMPANY_PROVIDED", "EXTERNAL_SOURCE"}
        if v is not None and v not in allowed:
            raise ValueError(f"source_type must be one of {sorted(allowed)} when set by a client")
        return v


class BrsrValidationIssueResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    metric_code: Optional[str] = None
    severity: str
    code: str
    message: str
    suggested_resolution: Optional[str] = None


class BrsrValidationRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    report_id: int
    run_at: datetime
    run_by: Optional[int] = None
    status: str
    error_count: int
    warning_count: int
    info_count: int
    issues: List[BrsrValidationIssueResponse] = []


class BrsrAssessmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    report_id: int
    assessment_status: Optional[str] = None
    assessor_name: Optional[str] = None
    assessor_type: Optional[str] = None
    assessment_date: Optional[datetime] = None
    scope: Optional[str] = None
    notes: Optional[str] = None
    evidence_reference: Optional[str] = None
    source_type: str
    updated_at: Optional[datetime] = None


class BrsrAssessmentUpdateRequest(BaseModel):
    assessment_status: Optional[str] = None
    assessor_name: Optional[str] = None
    assessor_type: Optional[str] = None
    assessment_date: Optional[datetime] = None
    scope: Optional[str] = None
    notes: Optional[str] = None
    evidence_reference: Optional[str] = None

    @field_validator("assessor_type")
    @classmethod
    def validate_assessor_type(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("INTERNAL", "EXTERNAL"):
            raise ValueError("assessor_type must be 'INTERNAL' or 'EXTERNAL'")
        return v


class BrsrDataQualitySummary(BaseModel):
    high: int = 0
    medium: int = 0
    low: int = 0
    missing: int = 0
    total: int = 0


class BrsrOverviewResponse(BaseModel):
    """Every number here is derived live from the database — never a fake
    progress percentage (Phase 16)."""
    report: BrsrReportResponse
    completion_pct: float
    required_metrics_total: int
    required_metrics_filled: int
    data_quality: BrsrDataQualitySummary
    missing_required_count: int
    brsr_core_completion_pct: float
    latest_validation: Optional[BrsrValidationRunResponse] = None
    can_approve: bool
    can_generate: bool
