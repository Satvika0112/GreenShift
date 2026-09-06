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
    Boolean,
    Column,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship, foreign


# ─────────────────────────────────────────────────────────────────────────────
# SQLAlchemy Base
# ─────────────────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


# ─────────────────────────────────────────────────────────────────────────────
# Enumerations
# ─────────────────────────────────────────────────────────────────────────────

class JobStatus(str, enum.Enum):
    SUBMITTED        = "SUBMITTED"
    SCHEDULED        = "SCHEDULED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED         = "APPROVED"
    DECLINED         = "DECLINED"
    QUEUED           = "QUEUED"
    RUNNING          = "RUNNING"
    COMPLETED        = "COMPLETED"
    FAILED           = "FAILED"


class EventType(str, enum.Enum):
    JOB_SUBMITTED        = "JOB_SUBMITTED"
    JOB_SCHEDULED        = "JOB_SCHEDULED"
    SCHEDULE_PROPOSED    = "SCHEDULE_PROPOSED"
    APPROVAL_GRANTED     = "APPROVAL_GRANTED"
    APPROVAL_DECLINED    = "APPROVAL_DECLINED"
    DISPATCH_AUTHORIZED  = "DISPATCH_AUTHORIZED"
    K8S_JOB_CREATED      = "K8S_JOB_CREATED"
    K8S_JOB_STARTED      = "K8S_JOB_STARTED"
    K8S_JOB_COMPLETED    = "K8S_JOB_COMPLETED"
    K8S_JOB_FAILED       = "K8S_JOB_FAILED"
    BUDGET_UPDATED       = "BUDGET_UPDATED"
    EXPORT_GENERATED     = "EXPORT_GENERATED"
    # ── Carbon Provenance & Resilience Events ──
    CARBON_API_SUCCESS   = "CARBON_API_SUCCESS"
    CARBON_CACHE_UPDATED = "CARBON_CACHE_UPDATED"
    CARBON_CACHE_USED    = "CARBON_CACHE_USED"
    CARBON_CACHE_STALE   = "CARBON_CACHE_STALE"
    CARBON_CSV_USED      = "CARBON_CSV_USED"
    CARBON_FALLBACK_USED = "CARBON_FALLBACK_USED"


# ─────────────────────────────────────────────────────────────────────────────
# SQLAlchemy ORM — Job
# ─────────────────────────────────────────────────────────────────────────────

class JobORM(Base):
    """Persistent job registry record."""

    __tablename__ = "jobs"

    job_id               = Column(String, primary_key=True)
    workload_name        = Column(String, nullable=True)   # workload name/identifier
    team_id              = Column(String, nullable=False, index=True)
    submitted_at         = Column(DateTime, nullable=False, index=True)
    deadline             = Column(DateTime, nullable=False, index=True)
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
    earliest_start_time  = Column(DateTime, nullable=True) # job cannot start before this
    energy_kwh           = Column(Float, nullable=True)    # pre-computed or power_kw * runtime_h
    deferrable           = Column(Boolean, nullable=True)  # True = can be shifted for savings
    created_at           = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at           = Column(DateTime, nullable=True, onupdate=datetime.utcnow)

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
    )


# ─────────────────────────────────────────────────────────────────────────────
# SQLAlchemy ORM — ScheduleDecision
# ─────────────────────────────────────────────────────────────────────────────

class ScheduleDecisionORM(Base):
    """Output of the DECIDE agent — the chosen execution window."""

    __tablename__ = "schedule_decisions"

    id                = Column(Integer, primary_key=True, autoincrement=True)
    job_id            = Column(String, ForeignKey("jobs.job_id"), nullable=False, unique=True, index=True)
    selected_start    = Column(DateTime, nullable=False, index=True)
    selected_end      = Column(DateTime, nullable=False, index=True)
    carbon_intensity  = Column(Float, nullable=False)   # gCO2/kWh
    electricity_cost  = Column(Float, nullable=False)   # total cost in USD
    carbon_emission   = Column(Float, nullable=False)   # kg CO2
    optimization_score = Column(Float, nullable=True)
    reason            = Column(Text, nullable=False)
    budget_remaining  = Column(Float, nullable=True)
    created_at        = Column(DateTime, nullable=False, default=datetime.utcnow)

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
    baseline_start           = Column(DateTime, nullable=True)
    baseline_end             = Column(DateTime, nullable=True)
    baseline_carbon_emission = Column(Float, nullable=True)  # kg CO2
    baseline_cost            = Column(Float, nullable=True)    # $ USD
    carbon_avoided           = Column(Float, nullable=True)    # kg CO2
    cost_difference          = Column(Float, nullable=True)    # $ USD
    carbon_reduction_pct     = Column(Float, nullable=True)    # %
    cost_reduction_pct       = Column(Float, nullable=True)    # %
    scheduling_delay_hours   = Column(Float, nullable=True)    # hours delayed from earliest bound
    sla_met                  = Column(Boolean, nullable=True, default=True) # completion <= deadline

    job = relationship("JobORM", back_populates="schedule_decision")
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

    id                   = Column(Integer, primary_key=True, autoincrement=True)
    job_id               = Column(String, ForeignKey("jobs.job_id"), nullable=False, index=True)
    schedule_decision_id = Column(Integer, ForeignKey("schedule_decisions.id"), nullable=False, index=True)
    decision             = Column(String, nullable=False, index=True)   # "APPROVED" or "DECLINED"
    reason               = Column(Text, nullable=True)
    approved_by          = Column(String, nullable=True, default="admin")
    created_at           = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at           = Column(DateTime, nullable=True, onupdate=datetime.utcnow)

    # Relationships
    job = relationship("JobORM", back_populates="approvals")
    schedule_decision = relationship("ScheduleDecisionORM", back_populates="approvals")


# ─────────────────────────────────────────────────────────────────────────────
# SQLAlchemy ORM — KubernetesExecution
# ─────────────────────────────────────────────────────────────────────────────

class KubernetesExecutionORM(Base):
    """Kubernetes Job execution tracking — owned by DISPATCH agent."""

    __tablename__ = "kubernetes_executions"

    id                   = Column(Integer, primary_key=True, autoincrement=True)
    job_id               = Column(String, ForeignKey("jobs.job_id"), nullable=False, unique=True, index=True)
    kubernetes_job_name  = Column(String, nullable=False, index=True)
    kubernetes_namespace = Column(String, nullable=False, default="greenshift")
    pod_name             = Column(String, nullable=True)
    planned_start        = Column(DateTime, nullable=False, index=True)
    actual_start         = Column(DateTime, nullable=True)
    planned_end          = Column(DateTime, nullable=True)
    actual_end           = Column(DateTime, nullable=True)
    k8s_status           = Column(String, nullable=True)   # raw Kubernetes status
    gs_status            = Column(SAEnum(JobStatus), nullable=False, default=JobStatus.QUEUED, index=True)
    error_message        = Column(Text, nullable=True)
    created_at           = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at           = Column(DateTime, nullable=True, onupdate=datetime.utcnow)

    job = relationship("JobORM", back_populates="kubernetes_execution")

    @property
    def execution_id(self) -> int:
        return self.id


# ─────────────────────────────────────────────────────────────────────────────
# SQLAlchemy ORM — AuditEvent
# ─────────────────────────────────────────────────────────────────────────────

class AuditEventORM(Base):
    """Tamper-evident audit ledger — owned by TRUST agent."""

    __tablename__ = "audit_events"
    __table_args__ = (
        UniqueConstraint("sequence", name="uq_audit_events_sequence"),
    )

    event_id      = Column(String, primary_key=True)
    timestamp     = Column(DateTime, nullable=False, index=True)
    event_type    = Column(SAEnum(EventType), nullable=False, index=True)
    job_id        = Column(String, nullable=True, index=True)
    payload_hash  = Column(String(64), nullable=False)   # SHA-256 hex
    previous_hash = Column(String(64), nullable=False)   # SHA-256 hex (genesis = 0*64)
    current_hash  = Column(String(64), nullable=False)   # SHA-256 hex
    payload_json  = Column(Text, nullable=False)         # serialised event payload
    sequence      = Column(Integer, nullable=False, unique=True, index=True)  # monotonically increasing and globally unique


# ─────────────────────────────────────────────────────────────────────────────
# SQLAlchemy ORM — CarbonDataPoint
# ─────────────────────────────────────────────────────────────────────────────

class CarbonDataPointORM(Base):
    """Cached carbon intensity data points with multi-level resilience metadata."""

    __tablename__ = "carbon_data"
    __table_args__ = (
        Index("ix_carbon_data_region_timestamp", "region", "timestamp"),
    )

    id                = Column(Integer, primary_key=True, autoincrement=True)
    timestamp         = Column(DateTime, nullable=False, index=True)
    region            = Column(String, nullable=False, index=True)
    carbon_gco2_kwh   = Column(Float, nullable=False)
    fetched_at        = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    source            = Column(String, nullable=False, default="electricity_maps")
    expires_at        = Column(DateTime, nullable=True)
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
    )

    id            = Column(Integer, primary_key=True, autoincrement=True)
    timestamp     = Column(DateTime, nullable=False, index=True)
    region        = Column(String, nullable=False, index=True)
    price_per_kwh = Column(Float, nullable=False)
    fetched_at    = Column(DateTime, nullable=False, default=datetime.utcnow)


# ─────────────────────────────────────────────────────────────────────────────
# SQLAlchemy ORM — RegionalTariffORM (Canonical Common Schema)
# ─────────────────────────────────────────────────────────────────────────────

class RegionalTariffORM(Base):
    """
    Canonical regional tariff data persistence layer.
    Supports India regions: Telangana (IN-TG), Gujarat (IN-GJ), Himachal Pradesh (IN-HP), West Bengal (IN-WB).
    """

    __tablename__ = "regional_tariffs"

    id                 = Column(Integer, primary_key=True, autoincrement=True)
    region_id          = Column(String, nullable=False, index=True)   # IN-TG, IN-GJ, IN-HP, IN-WB
    country            = Column(String, nullable=False, default="India")
    region_name        = Column(String, nullable=False)               # Telangana, Gujarat, Himachal Pradesh, West Bengal
    tariff_plan        = Column(String, nullable=False, index=True)   # HT-I(A), HT-II(A), HTP-I, Large Industry - EHT, Industries (Rate E-BT)
    timestamp          = Column(DateTime, nullable=False, index=True) # UTC timestamp
    local_timestamp    = Column(DateTime, nullable=False)             # Local wall-clock timestamp (Asia/Kolkata)
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
    created_at         = Column(DateTime, nullable=False, default=datetime.utcnow)


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
    team_id:          str   = Field(..., description="Team identifier")
    deadline:         datetime = Field(..., description="Latest allowed start+runtime end time (UTC)")
    runtime_minutes:  int   = Field(..., gt=0, description="Expected runtime in minutes")
    power_kw:         float = Field(..., gt=0, description="Average power draw in kW")
    region:           str   = Field(..., description="Grid region code, e.g. IN-TG, IN-GJ, IN-HP, IN-WB")
    container_image:  str   = Field(..., description="Docker image to run as Kubernetes Job")
    cpu_request:      str   = Field(default="500m", description="Kubernetes CPU request")
    memory_request:   str   = Field(default="512Mi", description="Kubernetes memory request")
    carbon_budget_kg: Optional[float] = Field(None, description="Max carbon budget in kg CO2")
    submit_time:         Optional[datetime] = Field(None, description="Original submit timestamp from workload dataset")
    job_id:              Optional[str]      = Field(None, description="Preserve original job ID from CSV")
    job_type:            Optional[str]      = Field(None, description="Workload type, e.g. DATA_PROCESSING")
    priority:            Optional[str]      = Field(None, description="CRITICAL/HIGH/MEDIUM/LOW")
    earliest_start_time: Optional[datetime] = Field(None, description="Job cannot start before this time")
    energy_kwh:          Optional[float]    = Field(None, description="Pre-computed energy consumption (kWh)")
    deferrable:          Optional[bool]     = Field(None, description="True = can be shifted for carbon savings")
    tariff_plan:         Optional[str]      = Field(None, description="Explicit tariff plan override")
    timezone:            Optional[str]      = Field(None, description="Optional IANA timezone name, e.g. Asia/Kolkata, America/New_York")


class JobSubmitResponse(BaseModel):
    job_id:       str
    status:       JobStatus
    submitted_at: datetime


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
    regional: Optional[dict] = None


class ApprovalRequest(BaseModel):
    """Request schema for approving or declining a proposed schedule."""

    schedule_id: int = Field(..., description="ID of the ScheduleDecisionORM")
    reason: Optional[str] = Field(None, description="Optional approval comment or required decline justification")
    approved_by: Optional[str] = Field(default="admin", description="User identifier who took the decision")


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

