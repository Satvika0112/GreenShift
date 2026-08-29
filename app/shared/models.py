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
    JOB_SUBMITTED        = "JOB_SUBMITTED"
    JOB_SCHEDULED        = "JOB_SCHEDULED"
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
    team_id              = Column(String, nullable=False)
    submitted_at         = Column(DateTime, nullable=False)
    deadline             = Column(DateTime, nullable=False)
    runtime_minutes      = Column(Integer, nullable=False)
    power_kw             = Column(Float, nullable=False)
    region               = Column(String, nullable=False)
    status               = Column(SAEnum(JobStatus), default=JobStatus.SUBMITTED, nullable=False)
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
    electricity_cost  = Column(Float, nullable=False)   # total cost in USD
    carbon_emission   = Column(Float, nullable=False)   # kg CO2
    reason            = Column(Text, nullable=False)
    budget_remaining  = Column(Float, nullable=True)
    created_at        = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Regional & Currency context
    region_id          = Column(String, nullable=True, default="IN-TG")
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
    """Cached carbon intensity data points with multi-level resilience metadata."""

    __tablename__ = "carbon_data"

    id                = Column(Integer, primary_key=True, autoincrement=True)
    timestamp         = Column(DateTime, nullable=False)
    region            = Column(String, nullable=False)
    carbon_gco2_kwh   = Column(Float, nullable=False)
    fetched_at        = Column(DateTime, nullable=False, default=datetime.utcnow)
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

    id            = Column(Integer, primary_key=True, autoincrement=True)
    timestamp     = Column(DateTime, nullable=False)
    region        = Column(String, nullable=False)
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
    # Extended fields (from real workloads dataset — all optional)
    job_id:              Optional[str]      = Field(None, description="Preserve original job ID from CSV")
    job_type:            Optional[str]      = Field(None, description="Workload type, e.g. DATA_PROCESSING")
    priority:            Optional[str]      = Field(None, description="CRITICAL/HIGH/MEDIUM/LOW")
    earliest_start_time: Optional[datetime] = Field(None, description="Job cannot start before this time")
    energy_kwh:          Optional[float]    = Field(None, description="Pre-computed energy consumption (kWh)")
    deferrable:          Optional[bool]     = Field(None, description="True = can be shifted for carbon savings")
    tariff_plan:         Optional[str]      = Field(None, description="Explicit tariff plan override")


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
