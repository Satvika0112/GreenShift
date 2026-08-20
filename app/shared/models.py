"""
GreenShift — Shared Pydantic + SQLAlchemy Models

This is the single source of truth for all data models.
Every agent imports from here. Do NOT redefine models in individual agent modules.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import (
    Column,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Boolean,
)
from sqlalchemy.orm import DeclarativeBase, relationship


# ─────────────────────────────────────────────────────────────────────────────
# SQLAlchemy Base
# ─────────────────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


# ─────────────────────────────────────────────────────────────────────────────
# Enumerations
# ─────────────────────────────────────────────────────────────────────────────

class JobStatus(str, enum.Enum):
    SUBMITTED = "SUBMITTED"
    SCHEDULED = "SCHEDULED"
    QUEUED    = "QUEUED"
    RUNNING   = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED    = "FAILED"


class EventType(str, enum.Enum):
    JOB_SUBMITTED      = "JOB_SUBMITTED"
    JOB_SCHEDULED      = "JOB_SCHEDULED"
    K8S_JOB_CREATED    = "K8S_JOB_CREATED"
    K8S_JOB_STARTED    = "K8S_JOB_STARTED"
    K8S_JOB_COMPLETED  = "K8S_JOB_COMPLETED"
    K8S_JOB_FAILED     = "K8S_JOB_FAILED"
    BUDGET_UPDATED     = "BUDGET_UPDATED"
    EXPORT_GENERATED   = "EXPORT_GENERATED"


# ─────────────────────────────────────────────────────────────────────────────
# SQLAlchemy ORM — Job
# ─────────────────────────────────────────────────────────────────────────────

class JobORM(Base):
    """Persistent job registry record."""

    __tablename__ = "jobs"

    job_id          = Column(String, primary_key=True)
    team_id         = Column(String, nullable=False)
    submitted_at    = Column(DateTime, nullable=False)
    deadline        = Column(DateTime, nullable=False)
    runtime_minutes = Column(Integer, nullable=False)
    power_kw        = Column(Float, nullable=False)
    region          = Column(String, nullable=False)
    status          = Column(SAEnum(JobStatus), default=JobStatus.SUBMITTED, nullable=False)
    container_image = Column(String, nullable=False)
    cpu_request     = Column(String, default="500m")
    memory_request  = Column(String, default="512Mi")
    carbon_budget_kg = Column(Float, nullable=True)

    # Relationships
    schedule_decision = relationship(
        "ScheduleDecisionORM",
        back_populates="job",
        uselist=False,
    )
    kubernetes_execution = relationship(
        "KubernetesExecutionORM",
        back_populates="job",
        uselist=False,
    )


# ─────────────────────────────────────────────────────────────────────────────
# SQLAlchemy ORM — ScheduleDecision
# ─────────────────────────────────────────────────────────────────────────────

class ScheduleDecisionORM(Base):
    """Output of the DECIDE agent — the chosen execution window."""

    __tablename__ = "schedule_decisions"

    id                = Column(Integer, primary_key=True, autoincrement=True)
    job_id            = Column(String, ForeignKey("jobs.job_id"), nullable=False, unique=True)
    selected_start    = Column(DateTime, nullable=False)
    selected_end      = Column(DateTime, nullable=False)
    carbon_intensity  = Column(Float, nullable=False)   # gCO2/kWh
    electricity_cost  = Column(Float, nullable=False)   # $/kWh
    carbon_emission   = Column(Float, nullable=False)   # kg CO2
    reason            = Column(Text, nullable=False)
    budget_remaining  = Column(Float, nullable=True)
    created_at        = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Baseline comparison
    baseline_start         = Column(DateTime, nullable=True)
    baseline_carbon_emission = Column(Float, nullable=True)  # kg CO2
    baseline_cost          = Column(Float, nullable=True)    # $
    carbon_avoided         = Column(Float, nullable=True)    # kg CO2
    cost_difference        = Column(Float, nullable=True)    # $

    job = relationship("JobORM", back_populates="schedule_decision")


# ─────────────────────────────────────────────────────────────────────────────
# SQLAlchemy ORM — KubernetesExecution
# ─────────────────────────────────────────────────────────────────────────────

class KubernetesExecutionORM(Base):
    """Kubernetes Job execution tracking — owned by DISPATCH agent."""

    __tablename__ = "kubernetes_executions"

    id                   = Column(Integer, primary_key=True, autoincrement=True)
    job_id               = Column(String, ForeignKey("jobs.job_id"), nullable=False, unique=True)
    kubernetes_job_name  = Column(String, nullable=False)
    kubernetes_namespace = Column(String, nullable=False, default="greenshift")
    pod_name             = Column(String, nullable=True)
    planned_start        = Column(DateTime, nullable=False)
    actual_start         = Column(DateTime, nullable=True)
    planned_end          = Column(DateTime, nullable=True)
    actual_end           = Column(DateTime, nullable=True)
    k8s_status           = Column(String, nullable=True)   # raw Kubernetes status
    gs_status            = Column(SAEnum(JobStatus), nullable=False, default=JobStatus.QUEUED)
    error_message        = Column(Text, nullable=True)
    created_at           = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at           = Column(DateTime, nullable=True)

    job = relationship("JobORM", back_populates="kubernetes_execution")


# ─────────────────────────────────────────────────────────────────────────────
# SQLAlchemy ORM — AuditEvent
# ─────────────────────────────────────────────────────────────────────────────

class AuditEventORM(Base):
    """Tamper-evident audit ledger — owned by TRUST agent."""

    __tablename__ = "audit_events"

    event_id      = Column(String, primary_key=True)
    timestamp     = Column(DateTime, nullable=False)
    event_type    = Column(SAEnum(EventType), nullable=False)
    job_id        = Column(String, nullable=True)
    payload_hash  = Column(String(64), nullable=False)   # SHA-256 hex
    previous_hash = Column(String(64), nullable=False)   # SHA-256 hex (genesis = 0*64)
    current_hash  = Column(String(64), nullable=False)   # SHA-256 hex
    payload_json  = Column(Text, nullable=False)         # serialised event payload
    sequence      = Column(Integer, nullable=False)      # monotonically increasing


# ─────────────────────────────────────────────────────────────────────────────
# SQLAlchemy ORM — CarbonDataPoint
# ─────────────────────────────────────────────────────────────────────────────

class CarbonDataPointORM(Base):
    """Cached carbon intensity data points."""

    __tablename__ = "carbon_data"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    timestamp       = Column(DateTime, nullable=False)
    region          = Column(String, nullable=False)
    carbon_gco2_kwh = Column(Float, nullable=False)
    fetched_at      = Column(DateTime, nullable=False, default=datetime.utcnow)


# ─────────────────────────────────────────────────────────────────────────────
# SQLAlchemy ORM — TariffDataPoint
# ─────────────────────────────────────────────────────────────────────────────

class TariffDataPointORM(Base):
    """Cached tariff data points."""

    __tablename__ = "tariff_data"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    timestamp     = Column(DateTime, nullable=False)
    region        = Column(String, nullable=False)
    price_per_kwh = Column(Float, nullable=False)
    fetched_at    = Column(DateTime, nullable=False, default=datetime.utcnow)


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic Schemas — Request / Response
# ─────────────────────────────────────────────────────────────────────────────

class JobSubmitRequest(BaseModel):
    """API request body for POST /api/v1/jobs"""

    team_id:          str   = Field(..., description="Team identifier")
    deadline:         datetime = Field(..., description="Latest allowed start+runtime end time (UTC)")
    runtime_minutes:  int   = Field(..., gt=0, description="Expected runtime in minutes")
    power_kw:         float = Field(..., gt=0, description="Average power draw in kW")
    region:           str   = Field(..., description="Grid region code, e.g. IN-WE")
    container_image:  str   = Field(..., description="Docker image to run as Kubernetes Job")
    cpu_request:      str   = Field(default="500m", description="Kubernetes CPU request")
    memory_request:   str   = Field(default="512Mi", description="Kubernetes memory request")
    carbon_budget_kg: Optional[float] = Field(None, description="Max carbon budget in kg CO2")


class JobSubmitResponse(BaseModel):
    job_id:       str
    status:       JobStatus
    submitted_at: datetime


class CarbonDataPoint(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    timestamp:       datetime
    region:          str
    carbon_gco2_kwh: float


class TariffDataPoint(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    timestamp:     datetime
    region:        str
    price_per_kwh: float


class ScheduleDecision(BaseModel):
    """Output of the DECIDE agent."""

    model_config = ConfigDict(from_attributes=True)

    job_id:           str
    selected_start:   datetime
    selected_end:     datetime
    carbon_intensity: float   # gCO2/kWh at selected window
    electricity_cost: float   # $/kWh at selected window
    carbon_emission:  float   # kg CO2 total
    reason:           str
    budget_remaining: Optional[float] = None

    # Baseline comparison (populated after scheduling)
    baseline_start:            Optional[datetime] = None
    baseline_carbon_emission:  Optional[float]    = None
    baseline_cost:             Optional[float]    = None
    carbon_avoided:            Optional[float]    = None
    cost_difference:           Optional[float]    = None


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


class AuditVerifyResponse(BaseModel):
    valid:       bool
    event_count: int
    message:     str


class DashboardSummary(BaseModel):
    """Aggregate summary for dashboard."""

    jobs: dict
    carbon: dict
    cost: dict
    audit: dict
