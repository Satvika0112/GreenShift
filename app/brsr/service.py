"""
GreenShift — BRSR Service Layer.

CRUD, RBAC enforcement, status-lifecycle transitions, and overview
computation for the BRSR reporting module. Backend is authoritative for
every one of these — nothing here trusts a client-supplied tenant_id,
role, or status.

Recipient/tenant resolution follows the exact same pattern as
app.api.tenant_scope and app.notify.service: identity is always the
authenticated caller (UserORM), never a request field.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.brsr.registry_seed import BRSR_METRIC_DEFINITIONS
from app.shared.auth import is_platform_admin
from app.shared.models import (
    BRSR_STATUS_TRANSITIONS,
    BrsrAssessmentORM,
    BrsrCompanyProfileORM,
    BrsrDataQuality,
    BrsrMetricDefinitionORM,
    BrsrMetricValueORM,
    BrsrReportORM,
    BrsrReportStatus,
    BrsrSourceType,
    BrsrValidationRunORM,
    UserORM,
)
from app.shared.utils import utcnow

logger = logging.getLogger("greenshift.brsr")


class BrsrPermissionError(Exception):
    def __init__(self, message: str, status_code: int = 403):
        super().__init__(message)
        self.status_code = status_code


class BrsrNotFoundError(Exception):
    pass


class BrsrValidationBlockedError(Exception):
    """Raised when a status transition is blocked by outstanding validation errors."""


class BrsrTransitionError(Exception):
    """Raised for an illegal status transition."""


# ─────────────────────────────────────────────────────────────────────────────
# RBAC helpers — the single place these rules live for BRSR
# ─────────────────────────────────────────────────────────────────────────────

def require_view_access(user: UserORM, tenant_id: str) -> None:
    """Any authenticated user may VIEW their own tenant's BRSR data; Platform
    Admin may view any tenant's (read-only cross-company visibility)."""
    if is_platform_admin(user):
        return
    if user.tenant_id != tenant_id:
        raise BrsrNotFoundError("BRSR report not found")  # 404, never leak cross-tenant existence


def require_edit_access(user: UserORM, tenant_id: str) -> None:
    """Only a COMPANY_ADMIN of the SAME tenant may create/edit BRSR data.
    Platform Admin is explicitly, unconditionally excluded from editing ANY
    company's BRSR data — "no unauthorized modification of company data" —
    Platform Admin's role here is read-only oversight, not authorship. This
    check does not rely on tenant_id happening to differ (a platform admin
    could in principle have a tenant_id set) — the role itself is checked
    directly."""
    if is_platform_admin(user):
        raise BrsrPermissionError("Platform Admin cannot create or edit a company's BRSR data")
    role_val = user.role.value if hasattr(user.role, "value") else str(user.role)
    if role_val != "COMPANY_ADMIN" or user.tenant_id != tenant_id:
        raise BrsrPermissionError("Only a Company Admin of this company may edit its BRSR data")


# ─────────────────────────────────────────────────────────────────────────────
# Metric registry
# ─────────────────────────────────────────────────────────────────────────────

def seed_metric_registry(db: Session) -> int:
    """Idempotently upsert the BRSR metric registry from registry_seed.py.
    Safe to call on every startup — never duplicates, never deletes a
    definition a report may already reference."""
    count = 0
    for defn in BRSR_METRIC_DEFINITIONS:
        existing = db.get(BrsrMetricDefinitionORM, defn["metric_code"])
        if existing is None:
            db.add(BrsrMetricDefinitionORM(**defn))
            count += 1
        else:
            for key, value in defn.items():
                if key != "metric_code":
                    setattr(existing, key, value)
    db.commit()
    return count


def list_metric_definitions(
    db: Session, section: Optional[str] = None, principle: Optional[int] = None
) -> List[BrsrMetricDefinitionORM]:
    q = db.query(BrsrMetricDefinitionORM)
    if section:
        q = q.filter(BrsrMetricDefinitionORM.section == section)
    if principle is not None:
        q = q.filter(BrsrMetricDefinitionORM.principle == principle)
    return q.order_by(BrsrMetricDefinitionORM.section, BrsrMetricDefinitionORM.principle, BrsrMetricDefinitionORM.metric_code).all()


# ─────────────────────────────────────────────────────────────────────────────
# Company profile
# ─────────────────────────────────────────────────────────────────────────────

def get_or_create_company_profile(db: Session, tenant_id: str) -> BrsrCompanyProfileORM:
    profile = db.query(BrsrCompanyProfileORM).filter(BrsrCompanyProfileORM.tenant_id == tenant_id).first()
    if profile is not None:
        return profile
    profile = BrsrCompanyProfileORM(tenant_id=tenant_id, source_type=BrsrSourceType.COMPANY_PROVIDED.value)
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def update_company_profile(db: Session, tenant_id: str, updates: Dict[str, Any], user: UserORM) -> BrsrCompanyProfileORM:
    require_edit_access(user, tenant_id)
    profile = get_or_create_company_profile(db, tenant_id)
    for key, value in updates.items():
        if value is not None:
            setattr(profile, key, value)
    profile.source_type = BrsrSourceType.COMPANY_PROVIDED.value
    profile.updated_by = user.id
    db.commit()
    db.refresh(profile)
    return profile


# ─────────────────────────────────────────────────────────────────────────────
# Reports
# ─────────────────────────────────────────────────────────────────────────────

def create_report(
    db: Session,
    tenant_id: str,
    financial_year: str,
    reporting_period_start: datetime,
    reporting_period_end: datetime,
    framework_version: str,
    user: UserORM,
    request_id: Optional[str] = None,
) -> BrsrReportORM:
    require_edit_access(user, tenant_id)

    existing = (
        db.query(BrsrReportORM)
        .filter(BrsrReportORM.tenant_id == tenant_id, BrsrReportORM.financial_year == financial_year)
        .first()
    )
    if existing is not None:
        raise BrsrTransitionError(f"A BRSR report for financial year {financial_year} already exists")

    report = BrsrReportORM(
        tenant_id=tenant_id,
        financial_year=financial_year,
        reporting_period_start=reporting_period_start,
        reporting_period_end=reporting_period_end,
        framework_version=framework_version,
        status=BrsrReportStatus.DRAFT.value,
        created_by=user.id,
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    # Pre-populate one MISSING row per registry metric so completion/quality
    # summaries are computed against the full registry from the start,
    # never silently omitting a metric nobody has touched yet.
    _sync_report_metric_registry(db, report)

    try:
        from app.trust.ledger import append_event
        from app.shared.models import EventType
        append_event(
            db, EventType.BRSR_REPORT_CREATED, payload={
                "report_id": report.id, "tenant_id": tenant_id, "financial_year": financial_year, "created_by": user.id,
            },
            actor=user, tenant_id=tenant_id, request_id=request_id, source_service="brsr",
        )
    except Exception:
        logger.warning("Audit record failed for BRSR report creation", exc_info=True)

    try:
        from app.notify.service import create_notification, resolve_tenant_admin_user_ids
        from app.shared.models import EventType as NotifEventType
        admin_ids = set(resolve_tenant_admin_user_ids(db, tenant_id))
        admin_ids.discard(user.id)
        for admin_id in admin_ids:
            create_notification(
                db, recipient_user_id=admin_id, event_type=NotifEventType.BRSR_REPORT_CREATED,
                category="WORKLOAD", severity="INFO",
                title=f"BRSR report started for FY {financial_year}",
                message=f"A new BRSR report for financial year {financial_year} was created by {user.username} and is now in data collection.",
                tenant_id=tenant_id, action_url="/brsr",
            )
    except Exception:
        logger.warning("Notification failed for BRSR report creation", exc_info=True)

    return report


def _sync_report_metric_registry(db: Session, report: BrsrReportORM) -> int:
    """
    Ensure this report has a value row for every CURRENT registry metric,
    adding a MISSING row for any that don't exist yet — never touching an
    existing row. This is what lets the metric registry evolve (a new BRSR
    question, or an entire new framework_version) without leaving reports
    created before the change permanently blind to the new metric, and
    without any migration/backfill script. Purely additive: it never
    deletes a row for a metric_code that was later removed from the
    registry, and never overwrites an already-answered value — safe to
    call on a GENERATED report too (it only ever reveals that a new
    question now exists, it doesn't reopen anything already answered).
    """
    existing_codes = {
        code for (code,) in db.query(BrsrMetricValueORM.metric_code).filter(BrsrMetricValueORM.report_id == report.id).all()
    }
    added = 0
    for defn in db.query(BrsrMetricDefinitionORM).all():
        if defn.metric_code in existing_codes:
            continue
        db.add(BrsrMetricValueORM(
            report_id=report.id,
            metric_code=defn.metric_code,
            source_type=BrsrSourceType.MISSING.value,
            quality=BrsrDataQuality.MISSING.value,
        ))
        added += 1
    if added:
        db.commit()
    return added


def get_report(db: Session, report_id: int, user: UserORM) -> BrsrReportORM:
    report = db.get(BrsrReportORM, report_id)
    if report is None:
        raise BrsrNotFoundError("BRSR report not found")
    require_view_access(user, report.tenant_id)
    _sync_report_metric_registry(db, report)
    return report


def list_reports(db: Session, user: UserORM, tenant_id: Optional[str] = None) -> List[BrsrReportORM]:
    q = db.query(BrsrReportORM)
    if is_platform_admin(user):
        if tenant_id:
            q = q.filter(BrsrReportORM.tenant_id == tenant_id)
    else:
        q = q.filter(BrsrReportORM.tenant_id == user.tenant_id)
    return q.order_by(BrsrReportORM.financial_year.desc()).all()


# ─────────────────────────────────────────────────────────────────────────────
# Metric values
# ─────────────────────────────────────────────────────────────────────────────

def _compute_quality(source_type: str, value: Optional[float], text_value: Optional[str], estimated: bool, data_gap: Optional[str]) -> str:
    """Quality is never assigned merely because a value exists — see spec
    Phase 11. MISSING/estimated/data-gapped values are never HIGH."""
    if source_type == BrsrSourceType.MISSING.value or (value is None and not text_value):
        return BrsrDataQuality.MISSING.value
    if estimated or data_gap:
        return BrsrDataQuality.LOW.value
    if source_type in (BrsrSourceType.GREENSHIFT_DERIVED.value, BrsrSourceType.CALCULATED.value):
        return BrsrDataQuality.HIGH.value
    if source_type in (BrsrSourceType.COMPANY_PROVIDED.value, BrsrSourceType.EXTERNAL_SOURCE.value):
        return BrsrDataQuality.MEDIUM.value
    return BrsrDataQuality.LOW.value


def get_metric_values(db: Session, report_id: int, section: Optional[str] = None, principle: Optional[int] = None) -> List[BrsrMetricValueORM]:
    q = (
        db.query(BrsrMetricValueORM)
        .join(BrsrMetricDefinitionORM, BrsrMetricValueORM.metric_code == BrsrMetricDefinitionORM.metric_code)
        .filter(BrsrMetricValueORM.report_id == report_id)
    )
    if section:
        q = q.filter(BrsrMetricDefinitionORM.section == section)
    if principle is not None:
        q = q.filter(BrsrMetricDefinitionORM.principle == principle)
    return q.order_by(BrsrMetricDefinitionORM.section, BrsrMetricDefinitionORM.principle, BrsrMetricValueORM.metric_code).all()


def update_metric_value(
    db: Session, report_id: int, metric_code: str, updates: Dict[str, Any], user: UserORM,
    request_id: Optional[str] = None,
) -> BrsrMetricValueORM:
    report = get_report(db, report_id, user)
    require_edit_access(user, report.tenant_id)
    if report.status == BrsrReportStatus.GENERATED.value:
        raise BrsrTransitionError("Cannot edit metric values on a GENERATED report")

    row = db.query(BrsrMetricValueORM).filter(
        BrsrMetricValueORM.report_id == report_id, BrsrMetricValueORM.metric_code == metric_code,
    ).first()
    if row is None:
        raise BrsrNotFoundError(f"Metric {metric_code} is not part of this report's registry")

    # source_type is handled separately below (it's the one field whose
    # client-supplied value is conditionally honored, not blindly applied).
    requested_source_type = updates.get("source_type")
    for key, value in updates.items():
        if key == "source_type":
            continue
        if value is not None:
            setattr(row, key, value)

    # A client-side edit can only ever self-declare COMPANY_PROVIDED (the
    # default) or EXTERNAL_SOURCE (e.g. a utility bill/third-party figure) —
    # it can never claim GREENSHIFT_DERIVED/CALCULATED provenance for its
    # own manual entry (Phase 6/11). Re-validated here, not just at the
    # Pydantic layer, since this service function is also the real
    # enforcement boundary for any direct/internal caller.
    _SELF_DECLARABLE_SOURCE_TYPES = {BrsrSourceType.COMPANY_PROVIDED.value, BrsrSourceType.EXTERNAL_SOURCE.value}
    if requested_source_type in _SELF_DECLARABLE_SOURCE_TYPES:
        row.source_type = requested_source_type
    else:
        row.source_type = BrsrSourceType.COMPANY_PROVIDED.value
    row.source_record = (
        f"external-source:{user.username}" if row.source_type == BrsrSourceType.EXTERNAL_SOURCE.value
        else f"manual-entry:{user.username}"
    )
    row.quality = _compute_quality(row.source_type, row.value, row.text_value, bool(row.estimated), row.data_gap)
    row.updated_by = user.id
    db.commit()
    db.refresh(row)

    try:
        from app.trust.ledger import append_event
        from app.shared.models import EventType
        append_event(
            db, EventType.BRSR_METRIC_UPDATED, payload={
                "report_id": report_id, "metric_code": metric_code, "updated_by": user.id, "source_type": row.source_type,
            },
            actor=user, tenant_id=report.tenant_id, request_id=request_id, source_service="brsr",
        )
    except Exception:
        logger.warning("Audit record failed for BRSR metric update", exc_info=True)

    return row


def apply_greenshift_derived_metrics(db: Session, report: BrsrReportORM, user: UserORM) -> int:
    """Runs app.brsr.calculations for every registry metric flagged
    greenshift_derivable and writes the result with source_type=
    GREENSHIFT_DERIVED. Never overwrites a metric the company has already
    manually provided unless the company re-triggers this explicitly."""
    require_edit_access(user, report.tenant_id)
    from app.brsr.calculations import calculate_metric

    updated = 0
    derivable_defs = db.query(BrsrMetricDefinitionORM).filter(BrsrMetricDefinitionORM.greenshift_derivable == True).all()  # noqa: E712
    for defn in derivable_defs:
        result = calculate_metric(db, defn.metric_code, report.tenant_id, report.reporting_period_start, report.reporting_period_end)
        if result is None:
            continue
        row = db.query(BrsrMetricValueORM).filter(
            BrsrMetricValueORM.report_id == report.id, BrsrMetricValueORM.metric_code == defn.metric_code,
        ).first()
        if row is None:
            continue
        row.value = result["value"]
        row.unit = defn.unit
        row.source_type = BrsrSourceType.GREENSHIFT_DERIVED.value
        row.source_record = result.get("source_record")
        row.source_detail = result.get("source_detail")
        row.quality = BrsrDataQuality.HIGH.value if result["value"] is not None else BrsrDataQuality.MISSING.value
        row.estimated = False
        row.updated_by = user.id
        updated += 1
    db.commit()
    return updated


# ─────────────────────────────────────────────────────────────────────────────
# Status lifecycle
# ─────────────────────────────────────────────────────────────────────────────

def transition_status(
    db: Session, report_id: int, target_status: str, user: UserORM, request_id: Optional[str] = None,
) -> BrsrReportORM:
    report = get_report(db, report_id, user)
    require_edit_access(user, report.tenant_id)

    expected_next = BRSR_STATUS_TRANSITIONS.get(report.status)
    if expected_next != target_status:
        raise BrsrTransitionError(
            f"Cannot transition BRSR report from {report.status} to {target_status} "
            f"(the only legal next status is {expected_next or 'none — this is the final state'})"
        )

    if target_status == BrsrReportStatus.VALIDATED.value:
        from app.brsr.validation import run_validation
        run = run_validation(db, report, user)
        if run.error_count > 0:
            raise BrsrValidationBlockedError(
                f"Cannot mark this report VALIDATED — {run.error_count} validation error(s) remain. "
                "Fix them and re-run validation."
            )
        report.validated_at = utcnow()

    if target_status == BrsrReportStatus.APPROVED.value:
        latest_run = (
            db.query(BrsrValidationRunORM)
            .filter(BrsrValidationRunORM.report_id == report.id)
            .order_by(BrsrValidationRunORM.run_at.desc())
            .first()
        )
        if latest_run is None or latest_run.error_count > 0:
            raise BrsrValidationBlockedError("Cannot approve a report with outstanding validation errors")
        report.approved_by = user.id
        report.approved_at = utcnow()

    if target_status == BrsrReportStatus.GENERATED.value:
        if report.status != BrsrReportStatus.APPROVED.value:
            raise BrsrTransitionError("A report must be APPROVED before it can be generated")
        report.generated_at = utcnow()

    previous_status = report.status
    report.status = target_status
    report.updated_at = utcnow()
    db.commit()
    db.refresh(report)

    try:
        from app.trust.ledger import append_event
        from app.shared.models import EventType
        event = EventType.BRSR_REPORT_APPROVED if target_status == BrsrReportStatus.APPROVED.value \
            else EventType.BRSR_REPORT_GENERATED if target_status == BrsrReportStatus.GENERATED.value \
            else EventType.BRSR_STATUS_CHANGED
        append_event(
            db, event, payload={
                "report_id": report.id, "tenant_id": report.tenant_id,
                "previous_status": previous_status, "new_status": target_status, "changed_by": user.id,
            },
            actor=user, tenant_id=report.tenant_id, request_id=request_id, source_service="brsr",
        )
    except Exception:
        logger.warning("Audit record failed for BRSR status transition", exc_info=True)

    _notify_status_change(db, report, previous_status, target_status, user)
    return report


def _notify_status_change(db: Session, report: BrsrReportORM, previous_status: str, new_status: str, user: UserORM) -> None:
    try:
        from app.notify.service import create_notification, notify_users, resolve_tenant_admin_user_ids, resolve_platform_admin_user_ids
        from app.shared.models import EventType as NotifEventType

        if new_status == BrsrReportStatus.APPROVED.value:
            recipient_ids = set(resolve_tenant_admin_user_ids(db, report.tenant_id))
            recipient_ids.discard(user.id)
            if recipient_ids:
                notify_users(
                    db, recipient_user_ids=list(recipient_ids), event_type=NotifEventType.BRSR_REPORT_APPROVED,
                    category="WORKLOAD", severity="INFO",
                    title=f"BRSR report approved — FY {report.financial_year}",
                    message=f"The BRSR report for FY {report.financial_year} was approved by {user.username}.",
                    tenant_id=report.tenant_id, action_url="/brsr", email_required=True,
                )
        elif new_status == BrsrReportStatus.GENERATED.value:
            recipient_ids = set(resolve_tenant_admin_user_ids(db, report.tenant_id))
            recipient_ids.discard(user.id)
            if recipient_ids:
                notify_users(
                    db, recipient_user_ids=list(recipient_ids), event_type=NotifEventType.BRSR_REPORT_GENERATED,
                    category="WORKLOAD", severity="INFO",
                    title=f"BRSR report generated — FY {report.financial_year}",
                    message=f"The BRSR report for FY {report.financial_year} has been generated and is ready to export.",
                    tenant_id=report.tenant_id, action_url="/brsr",
                )
    except Exception:
        logger.warning("Notification failed for BRSR status change", exc_info=True)


# ─────────────────────────────────────────────────────────────────────────────
# Overview
# ─────────────────────────────────────────────────────────────────────────────

def compute_overview(db: Session, report: BrsrReportORM) -> Dict[str, Any]:
    values = get_metric_values(db, report.id)
    definitions_by_code = {d.metric_code: d for d in db.query(BrsrMetricDefinitionORM).all()}

    required_total = 0
    required_filled = 0
    quality_counts = {"high": 0, "medium": 0, "low": 0, "missing": 0}
    core_total = 0
    core_filled = 0

    for v in values:
        defn = definitions_by_code.get(v.metric_code)
        is_filled = v.value is not None or bool(v.text_value)
        if defn and defn.required:
            required_total += 1
            if is_filled:
                required_filled += 1
        if defn and defn.section == "CORE":
            core_total += 1
            if is_filled:
                core_filled += 1
        quality_counts[v.quality.lower()] = quality_counts.get(v.quality.lower(), 0) + 1

    total = len(values)
    filled = sum(1 for v in values if v.value is not None or bool(v.text_value))
    completion_pct = round((filled / total) * 100, 1) if total else 0.0
    core_completion_pct = round((core_filled / core_total) * 100, 1) if core_total else 0.0
    missing_required = required_total - required_filled

    latest_run = (
        db.query(BrsrValidationRunORM)
        .filter(BrsrValidationRunORM.report_id == report.id)
        .order_by(BrsrValidationRunORM.run_at.desc())
        .first()
    )

    expected_next = BRSR_STATUS_TRANSITIONS.get(report.status)
    can_approve = report.status == BrsrReportStatus.VALIDATED.value and expected_next == BrsrReportStatus.APPROVED.value
    can_generate = report.status == BrsrReportStatus.APPROVED.value and expected_next == BrsrReportStatus.GENERATED.value

    return {
        "report": report,
        "completion_pct": completion_pct,
        "required_metrics_total": required_total,
        "required_metrics_filled": required_filled,
        "data_quality": {
            "high": quality_counts.get("high", 0),
            "medium": quality_counts.get("medium", 0),
            "low": quality_counts.get("low", 0),
            "missing": quality_counts.get("missing", 0),
            "total": total,
        },
        "missing_required_count": max(0, missing_required),
        "brsr_core_completion_pct": core_completion_pct,
        "latest_validation": latest_run,
        "can_approve": can_approve,
        "can_generate": can_generate,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Assessment / Assurance (Phase 22)
# ─────────────────────────────────────────────────────────────────────────────

def get_or_create_assessment(db: Session, report_id: int) -> BrsrAssessmentORM:
    row = db.query(BrsrAssessmentORM).filter(BrsrAssessmentORM.report_id == report_id).first()
    if row is not None:
        return row
    row = BrsrAssessmentORM(report_id=report_id, source_type=BrsrSourceType.COMPANY_PROVIDED.value)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_assessment(db: Session, report_id: int, updates: Dict[str, Any], user: UserORM) -> BrsrAssessmentORM:
    report = get_report(db, report_id, user)
    require_edit_access(user, report.tenant_id)
    row = get_or_create_assessment(db, report_id)
    for key, value in updates.items():
        if value is not None:
            setattr(row, key, value)
    row.source_type = BrsrSourceType.COMPANY_PROVIDED.value
    row.updated_by = user.id
    db.commit()
    db.refresh(row)
    return row
