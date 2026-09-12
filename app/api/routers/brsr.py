"""
GreenShift — BRSR API Router.

Backend-authoritative for every RBAC/tenant-isolation decision — see
app.brsr.service.require_view_access / require_edit_access. No endpoint
here accepts a client-supplied tenant_id/company_id/role for authorization;
recipient/tenant identity is always the authenticated caller
(Depends(get_current_user)).
"""

import json
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.brsr import service as brsr_service
from app.brsr.report_generator import generate_csv, generate_excel, generate_json, generate_pdf
from app.brsr.service import (
    BrsrNotFoundError,
    BrsrPermissionError,
    BrsrTransitionError,
    BrsrValidationBlockedError,
)
from app.brsr.validation import run_validation
from app.shared.auth import get_current_user, is_platform_admin
from app.shared.database import get_db
from app.shared.models import (
    BrsrAssessmentResponse,
    BrsrAssessmentUpdateRequest,
    BrsrCompanyProfileResponse,
    BrsrCompanyProfileUpdateRequest,
    BrsrMetricDefinitionORM,
    BrsrMetricDefinitionResponse,
    BrsrMetricValueORM,
    BrsrMetricValueResponse,
    BrsrMetricValueUpdateRequest,
    BrsrMetricValueWithDefinition,
    BrsrOverviewResponse,
    BrsrReportCreateRequest,
    BrsrReportResponse,
    BrsrStatusTransitionRequest,
    BrsrValidationRunORM,
    BrsrValidationRunResponse,
    UserORM,
)

router = APIRouter(prefix="/brsr", tags=["BRSR"])


def _map_error(exc: Exception):
    if isinstance(exc, BrsrPermissionError):
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    if isinstance(exc, BrsrNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, (BrsrTransitionError, BrsrValidationBlockedError)):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    raise exc


def _with_definition(db: Session, row: BrsrMetricValueORM) -> BrsrMetricValueWithDefinition:
    defn = db.get(BrsrMetricDefinitionORM, row.metric_code)
    base = BrsrMetricValueResponse.model_validate(row, from_attributes=True).model_dump()
    return BrsrMetricValueWithDefinition(
        **base,
        metric_name=defn.metric_name, principle=defn.principle, section=defn.section,
        brsr_core_attribute=defn.brsr_core_attribute, data_type=defn.data_type,
        required=defn.required, calculation_method=defn.calculation_method, description=defn.description,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Metric registry
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/metric-definitions", response_model=List[BrsrMetricDefinitionResponse])
def api_list_metric_definitions(
    section: Optional[str] = Query(None),
    principle: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    return brsr_service.list_metric_definitions(db, section=section, principle=principle)


# ─────────────────────────────────────────────────────────────────────────────
# Company profile
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/company-profile", response_model=BrsrCompanyProfileResponse)
def api_get_company_profile(
    tenant_id: Optional[str] = Query(None, description="Platform Admin only — view another tenant's profile"),
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    target_tenant = tenant_id if (tenant_id and is_platform_admin(current_user)) else current_user.tenant_id
    if not target_tenant:
        raise HTTPException(status_code=400, detail="No tenant associated with this account")
    try:
        brsr_service.require_view_access(current_user, target_tenant)
    except BrsrNotFoundError as exc:
        _map_error(exc)
    return brsr_service.get_or_create_company_profile(db, target_tenant)


@router.put("/company-profile", response_model=BrsrCompanyProfileResponse)
def api_update_company_profile(
    body: BrsrCompanyProfileUpdateRequest,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="No tenant associated with this account")
    try:
        return brsr_service.update_company_profile(db, current_user.tenant_id, body.model_dump(exclude_unset=True), current_user)
    except (BrsrPermissionError, BrsrNotFoundError, BrsrTransitionError) as exc:
        _map_error(exc)


# ─────────────────────────────────────────────────────────────────────────────
# Reports
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/reports", response_model=List[BrsrReportResponse])
def api_list_reports(
    tenant_id: Optional[str] = Query(None, description="Platform Admin only"),
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    return brsr_service.list_reports(db, current_user, tenant_id=tenant_id)


@router.post("/reports", response_model=BrsrReportResponse, status_code=status.HTTP_201_CREATED)
def api_create_report(
    body: BrsrReportCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="No tenant associated with this account")
    try:
        return brsr_service.create_report(
            db, current_user.tenant_id, body.financial_year, body.reporting_period_start,
            body.reporting_period_end, body.framework_version, current_user,
            request_id=getattr(request.state, "request_id", None),
        )
    except (BrsrPermissionError, BrsrNotFoundError, BrsrTransitionError) as exc:
        _map_error(exc)


@router.get("/reports/{report_id}", response_model=BrsrReportResponse)
def api_get_report(report_id: int, db: Session = Depends(get_db), current_user: UserORM = Depends(get_current_user)):
    try:
        return brsr_service.get_report(db, report_id, current_user)
    except (BrsrPermissionError, BrsrNotFoundError) as exc:
        _map_error(exc)


@router.get("/reports/{report_id}/overview", response_model=BrsrOverviewResponse)
def api_get_overview(report_id: int, db: Session = Depends(get_db), current_user: UserORM = Depends(get_current_user)):
    try:
        report = brsr_service.get_report(db, report_id, current_user)
    except (BrsrPermissionError, BrsrNotFoundError) as exc:
        _map_error(exc)
    return brsr_service.compute_overview(db, report)


@router.get("/reports/{report_id}/metrics", response_model=List[BrsrMetricValueWithDefinition])
def api_get_metrics(
    report_id: int,
    section: Optional[str] = Query(None),
    principle: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
):
    try:
        report = brsr_service.get_report(db, report_id, current_user)
    except (BrsrPermissionError, BrsrNotFoundError) as exc:
        _map_error(exc)
    values = brsr_service.get_metric_values(db, report.id, section=section, principle=principle)
    return [_with_definition(db, v) for v in values]


@router.put("/reports/{report_id}/metrics/{metric_code}", response_model=BrsrMetricValueWithDefinition)
def api_update_metric(
    report_id: int, metric_code: str, body: BrsrMetricValueUpdateRequest, request: Request,
    db: Session = Depends(get_db), current_user: UserORM = Depends(get_current_user),
):
    try:
        row = brsr_service.update_metric_value(
            db, report_id, metric_code, body.model_dump(exclude_unset=True), current_user,
            request_id=getattr(request.state, "request_id", None),
        )
    except (BrsrPermissionError, BrsrNotFoundError, BrsrTransitionError) as exc:
        _map_error(exc)
    return _with_definition(db, row)


@router.post("/reports/{report_id}/apply-greenshift-data")
def api_apply_greenshift_data(report_id: int, db: Session = Depends(get_db), current_user: UserORM = Depends(get_current_user)):
    try:
        report = brsr_service.get_report(db, report_id, current_user)
        updated = brsr_service.apply_greenshift_derived_metrics(db, report, current_user)
    except (BrsrPermissionError, BrsrNotFoundError, BrsrTransitionError) as exc:
        _map_error(exc)
    return {"updated_metrics": updated}


@router.post("/reports/{report_id}/validate", response_model=BrsrValidationRunResponse)
def api_run_validation(report_id: int, request: Request, db: Session = Depends(get_db), current_user: UserORM = Depends(get_current_user)):
    try:
        report = brsr_service.get_report(db, report_id, current_user)
        brsr_service.require_edit_access(current_user, report.tenant_id)
    except (BrsrPermissionError, BrsrNotFoundError) as exc:
        _map_error(exc)
    return run_validation(db, report, current_user, request_id=getattr(request.state, "request_id", None))


@router.get("/reports/{report_id}/audit")
def api_get_report_audit_trail(report_id: int, db: Session = Depends(get_db), current_user: UserORM = Depends(get_current_user)):
    """BRSR-specific slice of the existing tamper-evident audit ledger —
    reuses AuditEventORM directly rather than a second audit system."""
    try:
        report = brsr_service.get_report(db, report_id, current_user)
    except (BrsrPermissionError, BrsrNotFoundError) as exc:
        _map_error(exc)

    from app.shared.models import AuditEventORM, EventType
    brsr_event_types = [e for e in EventType if e.value.startswith("BRSR_")]
    rows = (
        db.query(AuditEventORM)
        .filter(AuditEventORM.event_type.in_(brsr_event_types))
        .order_by(AuditEventORM.sequence.desc())
        .limit(200)
        .all()
    )
    return [
        {
            "event_id": r.event_id, "timestamp": r.timestamp, "event_type": r.event_type.value,
            "sequence": r.sequence, "payload": r.payload,
            "actor_username": r.actor_username, "actor_role": r.actor_role, "actor_type": r.actor_type,
            "request_id": r.request_id, "source_service": r.source_service,
        }
        for r in rows if r.payload.get("report_id") == report_id
    ]


@router.get("/reports/{report_id}/validation", response_model=Optional[BrsrValidationRunResponse])
def api_get_latest_validation(report_id: int, db: Session = Depends(get_db), current_user: UserORM = Depends(get_current_user)):
    try:
        report = brsr_service.get_report(db, report_id, current_user)
    except (BrsrPermissionError, BrsrNotFoundError) as exc:
        _map_error(exc)
    return (
        db.query(BrsrValidationRunORM)
        .filter(BrsrValidationRunORM.report_id == report.id)
        .order_by(BrsrValidationRunORM.run_at.desc())
        .first()
    )


@router.post("/reports/{report_id}/transition", response_model=BrsrReportResponse)
def api_transition_status(
    report_id: int, body: BrsrStatusTransitionRequest, request: Request,
    db: Session = Depends(get_db), current_user: UserORM = Depends(get_current_user),
):
    try:
        return brsr_service.transition_status(
            db, report_id, body.target_status, current_user,
            request_id=getattr(request.state, "request_id", None),
        )
    except (BrsrPermissionError, BrsrNotFoundError, BrsrTransitionError, BrsrValidationBlockedError) as exc:
        _map_error(exc)


# ─────────────────────────────────────────────────────────────────────────────
# Assessment / Assurance
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/reports/{report_id}/assessment", response_model=BrsrAssessmentResponse)
def api_get_assessment(report_id: int, db: Session = Depends(get_db), current_user: UserORM = Depends(get_current_user)):
    try:
        report = brsr_service.get_report(db, report_id, current_user)
    except (BrsrPermissionError, BrsrNotFoundError) as exc:
        _map_error(exc)
    return brsr_service.get_or_create_assessment(db, report.id)


@router.put("/reports/{report_id}/assessment", response_model=BrsrAssessmentResponse)
def api_update_assessment(
    report_id: int, body: BrsrAssessmentUpdateRequest, db: Session = Depends(get_db), current_user: UserORM = Depends(get_current_user),
):
    try:
        return brsr_service.update_assessment(db, report_id, body.model_dump(exclude_unset=True), current_user)
    except (BrsrPermissionError, BrsrNotFoundError, BrsrTransitionError) as exc:
        _map_error(exc)


# ─────────────────────────────────────────────────────────────────────────────
# Export
# ─────────────────────────────────────────────────────────────────────────────

_CONTENT_TYPES = {
    "pdf": "application/pdf",
    "excel": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv",
    "json": "application/json",
}


@router.get("/reports/{report_id}/export")
def api_export_report(
    report_id: int, request: Request, format: str = Query(..., pattern="^(pdf|excel|csv|json)$"),
    db: Session = Depends(get_db), current_user: UserORM = Depends(get_current_user),
):
    try:
        report = brsr_service.get_report(db, report_id, current_user)
    except (BrsrPermissionError, BrsrNotFoundError) as exc:
        _map_error(exc)

    if report.status != "GENERATED":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A report can only be exported once it has reached GENERATED status.",
        )

    if format == "pdf":
        content = generate_pdf(db, report)
        filename = f"brsr_{report.tenant_id}_{report.financial_year}.pdf"
    elif format == "excel":
        content = generate_excel(db, report)
        filename = f"brsr_{report.tenant_id}_{report.financial_year}.xlsx"
    elif format == "csv":
        content = generate_csv(db, report).encode("utf-8")
        filename = f"brsr_{report.tenant_id}_{report.financial_year}.csv"
    else:
        content = json.dumps(generate_json(db, report), indent=2, default=str).encode("utf-8")
        filename = f"brsr_{report.tenant_id}_{report.financial_year}.json"

    try:
        from app.trust.ledger import append_event
        from app.shared.models import EventType
        append_event(
            db, EventType.BRSR_REPORT_EXPORTED, payload={
                "report_id": report.id, "tenant_id": report.tenant_id, "format": format, "exported_by": current_user.id,
            },
            actor=current_user, tenant_id=report.tenant_id,
            request_id=getattr(request.state, "request_id", None), source_service="brsr",
        )
    except Exception:
        pass

    return Response(content=content, media_type=_CONTENT_TYPES[format], headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
    })
