"""
GreenShift — BRSR Validation Engine.

A reusable, backend-only validation pass over one BRSR report. Every check
below returns structured issues (severity/code/message/affected
metric/suggested resolution) — never just a boolean pass/fail — so the
frontend can show the reader exactly what's wrong and why. A report with
any ERROR-level issue cannot be marked VALIDATED/APPROVED/GENERATED (see
app.brsr.service.transition_status).
"""

from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.shared.models import (
    BrsrCompanyProfileORM,
    BrsrMetricDefinitionORM,
    BrsrMetricValueORM,
    BrsrReportORM,
    BrsrValidationIssueORM,
    BrsrValidationRunORM,
    UserORM,
)
from app.shared.utils import utcnow

ERROR = "ERROR"
WARNING = "WARNING"
INFO = "INFO"

# metric pairs expected to represent the same underlying figure — a
# meaningful discrepancy between them signals a real data-entry problem.
_RECONCILIATION_PAIRS = [
    ("CORE_GHG_SCOPE2", "P6_SCOPE2_EMISSIONS"),
    ("CORE_ENERGY_CONSUMPTION", "P6_TOTAL_ENERGY_CONSUMPTION"),
    ("CORE_ENERGY_INTENSITY", "P6_ENERGY_INTENSITY"),
    ("CORE_EMISSION_INTENSITY", "P6_EMISSION_INTENSITY"),
]


def _issue(metric_code: Any, severity: str, code: str, message: str, resolution: Any = None) -> Dict[str, Any]:
    return {
        "metric_code": metric_code,
        "severity": severity,
        "code": code,
        "message": message,
        "suggested_resolution": resolution,
    }


def _validate_period(report: BrsrReportORM) -> List[Dict[str, Any]]:
    issues = []
    if report.reporting_period_end <= report.reporting_period_start:
        issues.append(_issue(
            None, ERROR, "INVALID_PERIOD",
            "reporting_period_end must be after reporting_period_start.",
            "Correct the reporting period dates before re-running validation.",
        ))
    try:
        fy_start_year = int(report.financial_year.split("-")[0])
        if report.reporting_period_start.year not in (fy_start_year, fy_start_year + 1):
            issues.append(_issue(
                None, WARNING, "PERIOD_FY_MISMATCH",
                f"Reporting period start year ({report.reporting_period_start.year}) does not match "
                f"financial year {report.financial_year}.",
                "Confirm the reporting period matches the stated financial year.",
            ))
    except (ValueError, IndexError):
        pass
    return issues


def _validate_company_profile(profile: "BrsrCompanyProfileORM | None") -> List[Dict[str, Any]]:
    issues = []
    if profile is None or not profile.company_name:
        issues.append(_issue(None, ERROR, "MISSING_COMPANY_PROFILE",
                              "Company profile is incomplete — company name is required.",
                              "Fill in the Company Profile page before validating."))
        return issues
    if profile.listed_status == "LISTED":
        if not profile.cin:
            issues.append(_issue(None, ERROR, "MISSING_CIN", "Listed companies must provide a CIN.",
                                  "Enter the Corporate Identity Number on the Company Profile page."))
        if not profile.isin:
            issues.append(_issue(None, WARNING, "MISSING_ISIN", "Listed companies should provide an ISIN.",
                                  "Enter the ISIN on the Company Profile page."))
        if not profile.stock_exchange:
            issues.append(_issue(None, WARNING, "MISSING_STOCK_EXCHANGE", "Listed companies should name their stock exchange(s).", None))
    return issues


def _validate_metric_values(
    values: List[BrsrMetricValueORM], definitions: Dict[str, BrsrMetricDefinitionORM]
) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    by_code = {v.metric_code: v for v in values}

    for v in values:
        defn = definitions.get(v.metric_code)
        if defn is None:
            continue
        is_filled = v.value is not None or bool(v.text_value)

        if defn.required and not is_filled:
            issues.append(_issue(
                v.metric_code, ERROR, "REQUIRED_FIELD_MISSING",
                f"'{defn.metric_name}' is required but has no value.",
                "Provide a value on the corresponding BRSR page, or record an explicit data gap if genuinely unavailable.",
            ))
        elif not defn.required and not is_filled:
            issues.append(_issue(
                v.metric_code, INFO, "OPTIONAL_FIELD_MISSING",
                f"'{defn.metric_name}' has not been provided (optional).",
                None,
            ))

        if is_filled and v.value is not None:
            if v.value < 0:
                issues.append(_issue(
                    v.metric_code, ERROR, "NEGATIVE_VALUE",
                    f"'{defn.metric_name}' has a negative value ({v.value}), which is not valid for this metric.",
                    "Correct the value — negative figures are not valid for this metric type.",
                ))
            if defn.data_type == "PERCENTAGE" and not (0 <= v.value <= 100):
                issues.append(_issue(
                    v.metric_code, ERROR, "PERCENTAGE_OUT_OF_RANGE",
                    f"'{defn.metric_name}' is a percentage but the value ({v.value}) is outside 0-100.",
                    "Enter a value between 0 and 100.",
                ))
            if defn.unit and not v.unit:
                issues.append(_issue(
                    v.metric_code, WARNING, "UNIT_NOT_SPECIFIED",
                    f"'{defn.metric_name}' has a value but no unit recorded (expected: {defn.unit}).",
                    f"Set the unit to '{defn.unit}'.",
                ))

        if v.source_type == "ESTIMATED" and not v.estimation_method:
            issues.append(_issue(
                v.metric_code, WARNING, "ESTIMATED_WITHOUT_METHOD",
                f"'{defn.metric_name}' is marked ESTIMATED but has no estimation method recorded.",
                "Describe how the estimate was derived.",
            ))
        if v.estimated and not v.assumption:
            issues.append(_issue(
                v.metric_code, WARNING, "ESTIMATE_WITHOUT_ASSUMPTION",
                f"'{defn.metric_name}' is flagged as estimated but no assumption is documented.",
                "Document the assumption behind this estimate.",
            ))
        if v.currency and v.reporting_currency and v.currency != v.reporting_currency and not v.exchange_rate:
            issues.append(_issue(
                v.metric_code, ERROR, "MISSING_EXCHANGE_RATE",
                f"'{defn.metric_name}' is in {v.currency} but no exchange rate to {v.reporting_currency} was provided.",
                "Provide the real exchange rate, its date, and its source — GreenShift never fabricates exchange rates.",
            ))

    for code_a, code_b in _RECONCILIATION_PAIRS:
        a, b = by_code.get(code_a), by_code.get(code_b)
        if a and b and a.value is not None and b.value is not None and b.value != 0:
            diff_pct = abs(a.value - b.value) / abs(b.value) * 100
            if diff_pct > 1.0:
                issues.append(_issue(
                    code_a, WARNING, "RECONCILIATION_MISMATCH",
                    f"'{code_a}' ({a.value}) and '{code_b}' ({b.value}) should represent the same underlying "
                    f"figure but differ by {diff_pct:.1f}%.",
                    "Confirm both figures were computed/entered consistently.",
                ))

    return issues


def run_validation(db: Session, report: BrsrReportORM, user: UserORM, request_id: "str | None" = None) -> BrsrValidationRunORM:
    from app.brsr.service import get_metric_values

    values = get_metric_values(db, report.id)
    definitions = {d.metric_code: d for d in db.query(BrsrMetricDefinitionORM).all()}
    profile = db.query(BrsrCompanyProfileORM).filter(BrsrCompanyProfileORM.tenant_id == report.tenant_id).first()

    issues: List[Dict[str, Any]] = []
    issues += _validate_period(report)
    issues += _validate_company_profile(profile)
    issues += _validate_metric_values(values, definitions)

    error_count = sum(1 for i in issues if i["severity"] == ERROR)
    warning_count = sum(1 for i in issues if i["severity"] == WARNING)
    info_count = sum(1 for i in issues if i["severity"] == INFO)
    status = "FAILED" if error_count else ("WARNINGS" if warning_count else "PASSED")

    run = BrsrValidationRunORM(
        report_id=report.id, run_at=utcnow(), run_by=user.id, status=status,
        error_count=error_count, warning_count=warning_count, info_count=info_count,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    for issue in issues:
        db.add(BrsrValidationIssueORM(run_id=run.id, **issue))
    db.commit()
    db.refresh(run)

    try:
        from app.trust.ledger import append_event
        from app.shared.models import EventType
        append_event(
            db, EventType.BRSR_VALIDATION_RUN, payload={
                "report_id": report.id, "run_id": run.id, "status": status,
                "error_count": error_count, "warning_count": warning_count, "run_by": user.id,
            },
            actor=user, tenant_id=report.tenant_id, request_id=request_id, source_service="brsr",
        )
    except Exception:
        pass

    try:
        from app.notify.service import notify_users, resolve_tenant_admin_user_ids
        from app.shared.models import EventType as NotifEventType
        if error_count > 0:
            recipient_ids = set(resolve_tenant_admin_user_ids(db, report.tenant_id))
            recipient_ids.discard(user.id)
            if recipient_ids:
                notify_users(
                    db, recipient_user_ids=list(recipient_ids), event_type=NotifEventType.BRSR_VALIDATION_RUN,
                    category="WORKLOAD", severity="WARNING",
                    title=f"BRSR validation failed — FY {report.financial_year}",
                    message=f"BRSR validation for FY {report.financial_year} found {error_count} error(s) that must be fixed before approval.",
                    tenant_id=report.tenant_id, action_url="/brsr",
                )
    except Exception:
        pass

    return run
