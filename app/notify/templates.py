"""
GreenShift — Notification Email Templates.

Renders a richer, event-specific (subject, body) pair for the six lifecycle
events the notification email system supports, using the job's own real
region/timezone/currency data — never a hardcoded "$"/USD and never the
browser/server's local time. Falls back to the notification's own
title/message (already correct, already tested) for any event this module
doesn't have a dedicated template for, so every notification remains
emailable even without a specific template.

Deliberately backend-only, plain text (matches app.notify.email's
no-HTML-injection-surface contract) — this is not a duplicate of the
frontend's utils/dateTime.ts / utils/currency.ts, it's the same underlying
region data (app.shared.timezone, ScheduleDecisionORM.currency/native_cost)
rendered server-side for an email client instead of a browser.
"""

from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.shared.models import EventType, JobORM, NotificationORM, ScheduleDecisionORM
from app.shared.timezone import format_regional_time

_APP_NAME = "GreenShift"


def _base_url() -> str:
    from app.shared.config import settings
    return settings.frontend_base_url or "http://localhost:3000"


def _format_cost(native_cost: Optional[float], currency: Optional[str]) -> str:
    """Native-currency amount as plain text (e.g. "12.50 INR") — never a
    hardcoded "$"/USD, and no invented currency symbol (email clients can't
    be relied on to render every Unicode currency glyph consistently)."""
    if native_cost is None or not currency:
        return "unavailable"
    return f"{native_cost:.2f} {currency}"


def _job_context(db: Session, job_id: Optional[str]) -> Tuple[Optional[JobORM], Optional[ScheduleDecisionORM]]:
    if not job_id:
        return None, None
    job = db.get(JobORM, job_id)
    if job is None:
        return None, None
    decision = (
        db.query(ScheduleDecisionORM)
        .filter(ScheduleDecisionORM.job_id == job_id)
        .order_by(ScheduleDecisionORM.id.desc())
        .first()
    )
    return job, decision


def _workload_name(job: JobORM) -> str:
    return job.workload_name or job.job_id


def _footer(job_id: Optional[str], path: str) -> str:
    link = f"{_base_url()}/{path.lstrip('/')}" if job_id else _base_url()
    return f"\nView in {_APP_NAME}: {link}\n\n— {_APP_NAME}, carbon-aware workload scheduling"


def _render_approval_required(job: JobORM, decision: Optional[ScheduleDecisionORM]) -> Tuple[str, str]:
    subject = f"[{_APP_NAME}] Approval required — {_workload_name(job)}"
    lines = [
        f"A workload schedule is awaiting your approval.",
        "",
        f"Workload:  {_workload_name(job)}",
        f"Job ID:    {job.job_id}",
        f"Region:    {job.region}",
    ]
    if decision is not None and decision.selected_start:
        lines.append(f"Proposed start: {format_regional_time(decision.selected_start, region=job.region)}")
        lines.append(f"Estimated carbon: {decision.carbon_emission:.3f} kg CO2" if decision.carbon_emission is not None else "Estimated carbon: unavailable")
        lines.append(f"Estimated cost: {_format_cost(decision.native_cost, decision.currency)}")
    lines.append(f"Deadline:  {format_regional_time(job.deadline, region=job.region)}" if job.deadline else "Deadline:  unavailable")
    body = "\n".join(lines) + _footer(job.job_id, "approvals")
    return subject, body


def _render_schedule_approved(job: JobORM, decision: Optional[ScheduleDecisionORM]) -> Tuple[str, str]:
    subject = f"[{_APP_NAME}] Schedule approved — {_workload_name(job)}"
    lines = [
        f"The schedule for your workload was approved and is proceeding toward execution.",
        "",
        f"Workload:  {_workload_name(job)}",
        f"Job ID:    {job.job_id}",
        f"Region:    {job.region}",
    ]
    if decision is not None and decision.selected_start:
        lines.append(f"Scheduled start: {format_regional_time(decision.selected_start, region=job.region)}")
        lines.append(f"Estimated cost: {_format_cost(decision.native_cost, decision.currency)}")
    body = "\n".join(lines) + _footer(job.job_id, f"workloads/{job.job_id}")
    return subject, body


def _render_schedule_declined(job: JobORM, decision: Optional[ScheduleDecisionORM] = None) -> Tuple[str, str]:
    subject = f"[{_APP_NAME}] Schedule declined — {_workload_name(job)}"
    lines = [
        f"The proposed schedule for your workload was declined.",
        "",
        f"Workload:  {_workload_name(job)}",
        f"Job ID:    {job.job_id}",
        f"Region:    {job.region}",
        "",
        "See the workload page for the decline reason.",
    ]
    body = "\n".join(lines) + _footer(job.job_id, f"workloads/{job.job_id}")
    return subject, body


def _render_workload_scheduled(job: JobORM, decision: Optional[ScheduleDecisionORM]) -> Tuple[str, str]:
    subject = f"[{_APP_NAME}] Workload scheduled — {_workload_name(job)}"
    lines = [
        f"A carbon-aware schedule was found for your workload and is now ready for review.",
        "",
        f"Workload:  {_workload_name(job)}",
        f"Job ID:    {job.job_id}",
        f"Region:    {job.region}",
    ]
    if decision is not None and decision.selected_start:
        lines.append(f"Recommended start: {format_regional_time(decision.selected_start, region=job.region)}")
        lines.append(f"Estimated carbon: {decision.carbon_emission:.3f} kg CO2" if decision.carbon_emission is not None else "Estimated carbon: unavailable")
        lines.append(f"Estimated cost: {_format_cost(decision.native_cost, decision.currency)}")
    body = "\n".join(lines) + _footer(job.job_id, "approvals")
    return subject, body


def _render_execution_completed(job: JobORM, decision: Optional[ScheduleDecisionORM] = None) -> Tuple[str, str]:
    subject = f"[{_APP_NAME}] Execution completed — {_workload_name(job)}"
    exec_row = getattr(job, "kubernetes_execution", None)
    lines = [
        f"Your workload finished executing successfully.",
        "",
        f"Workload:  {_workload_name(job)}",
        f"Job ID:    {job.job_id}",
        f"Region:    {job.region}",
    ]
    if exec_row is not None and exec_row.actual_end:
        lines.append(f"Completed: {format_regional_time(exec_row.actual_end, region=job.region)}")
    body = "\n".join(lines) + _footer(job.job_id, f"workloads/{job.job_id}")
    return subject, body


def _render_execution_failed(job: JobORM, decision: Optional[ScheduleDecisionORM] = None) -> Tuple[str, str]:
    subject = f"[{_APP_NAME}] Execution failed — {_workload_name(job)}"
    lines = [
        f"Your workload's execution failed.",
        "",
        f"Workload:  {_workload_name(job)}",
        f"Job ID:    {job.job_id}",
        f"Region:    {job.region}",
        "",
        "Check Job Monitoring for execution details.",
    ]
    body = "\n".join(lines) + _footer(job.job_id, f"workloads/{job.job_id}")
    return subject, body


# event_type -> renderer(job, decision). Every renderer shares this same
# signature (decision may be None/unused) so dispatch never has to special-
# case argument counts. SCHEDULE_PROPOSED is handled separately in
# render_email() since its template depends on the notification's category
# (APPROVAL, sent to approvers, vs. SCHEDULING, sent to the submitter).
_RENDERERS = {
    EventType.APPROVAL_GRANTED: _render_schedule_approved,
    EventType.APPROVAL_DECLINED: _render_schedule_declined,
    EventType.K8S_JOB_COMPLETED: _render_execution_completed,
    EventType.K8S_JOB_FAILED: _render_execution_failed,
}


def render_email(db: Session, notif: NotificationORM) -> Tuple[str, str]:
    """
    Returns (subject, body) for the given notification. Falls back to the
    notification's own (title, message) — already correct, already used
    for in-app display — whenever no richer template applies (unknown
    event_type, or the referenced job no longer exists).
    """
    job, decision = _job_context(db, notif.job_id)
    if job is None:
        return notif.title, notif.message

    try:
        if notif.event_type == EventType.SCHEDULE_PROPOSED:
            if notif.category == "APPROVAL":
                return _render_approval_required(job, decision)
            return _render_workload_scheduled(job, decision)

        renderer = _RENDERERS.get(notif.event_type)
        if renderer is not None:
            return renderer(job, decision)
    except Exception:
        # A template rendering bug must never block delivery of the
        # already-correct fallback content.
        pass

    return notif.title, notif.message
