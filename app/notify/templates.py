"""
GreenShift — Notification Email Templates.

Renders an event-specific, urgency-tagged (subject, body) pair using the
job's own real region/timezone/currency data — never a hardcoded "$"/USD
and never the browser/server's local time. Falls back to the notification's
own title/message (already correct, already tested) for any event this
module doesn't have a dedicated template for, so every notification remains
emailable even without a specific template.

Deliberately backend-only, plain text (matches app.notify.email's
no-HTML-injection-surface contract) — this is not a duplicate of the
frontend's utils/dateTime.ts / utils/currency.ts, it's the same underlying
region data (app.shared.timezone, ScheduleDecisionORM.currency/native_cost)
rendered server-side for an email client instead of a browser.

Subject urgency tagging follows the project's severity convention:
  INFO / IMPORTANT  -> no bracket ("[GreenShift] Workload Scheduled — JOB-1")
  HIGH (failure/decline outcomes), CRITICAL -> bracketed
    ("[GreenShift][HIGH] Scheduling Failed — JOB-1",
     "[GreenShift][CRITICAL] Workload Execution Failed — JOB-1")
  "Approval Required" is HIGH-urgency (routed to approvers, always emailed)
  but intentionally unbracketed — it's a call to action, not a failure report.
"""

from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.shared.models import ApprovalORM, EventType, JobORM, NotificationORM, ScheduleDecisionORM
from app.shared.timezone import format_regional_time

_APP_NAME = "GreenShift"


def _base_url() -> str:
    from app.shared.config import settings
    return settings.frontend_base_url or "http://localhost:3000"


def _subject(title: str, workload: str, bracket: Optional[str] = None) -> str:
    tag = f"[{bracket}]" if bracket else ""
    return f"[{_APP_NAME}]{tag} {title} — {workload}"


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


def _latest_approval(db: Session, job_id: str, decision: str) -> Optional[ApprovalORM]:
    return (
        db.query(ApprovalORM)
        .filter(ApprovalORM.job_id == job_id, ApprovalORM.decision == decision)
        .order_by(ApprovalORM.id.desc())
        .first()
    )


def _workload_name(job: JobORM) -> str:
    return job.workload_name or job.job_id


def _footer(job_id: Optional[str], path: str) -> str:
    link = f"{_base_url()}/{path.lstrip('/')}" if job_id else _base_url()
    return f"\nView in {_APP_NAME}: {link}\n\n— {_APP_NAME}, carbon-aware workload scheduling"


def _render_approval_required(db: Session, job: JobORM, decision: Optional[ScheduleDecisionORM]) -> Tuple[str, str]:
    subject = _subject("Approval required", _workload_name(job))
    lines = [
        "A workload schedule is awaiting your approval.",
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


def _render_schedule_proposed_submitter(db: Session, job: JobORM, decision: Optional[ScheduleDecisionORM]) -> Tuple[str, str]:
    subject = _subject("Schedule proposed", _workload_name(job))
    lines = [
        "A carbon-aware schedule was proposed for your workload and is now awaiting approval.",
        "",
        f"Workload:  {_workload_name(job)}",
        f"Job ID:    {job.job_id}",
        f"Region:    {job.region}",
    ]
    if decision is not None and decision.selected_start:
        lines.append(f"Proposed start: {format_regional_time(decision.selected_start, region=job.region)}")
        lines.append(f"Estimated carbon: {decision.carbon_emission:.3f} kg CO2" if decision.carbon_emission is not None else "Estimated carbon: unavailable")
        lines.append(f"Estimated cost: {_format_cost(decision.native_cost, decision.currency)}")
    body = "\n".join(lines) + _footer(job.job_id, f"workloads/{job.job_id}")
    return subject, body


def _render_job_scheduled(db: Session, job: JobORM, decision: Optional[ScheduleDecisionORM]) -> Tuple[str, str]:
    subject = _subject("Workload scheduled", _workload_name(job))
    lines = [
        "Your workload was scheduled and requires no approval.",
        "",
        f"Workload:  {_workload_name(job)}",
        f"Job ID:    {job.job_id}",
        f"Region:    {job.region}",
    ]
    if decision is not None and decision.selected_start:
        lines.append(f"Scheduled start: {format_regional_time(decision.selected_start, region=job.region)}")
        lines.append(f"Estimated carbon: {decision.carbon_emission:.3f} kg CO2" if decision.carbon_emission is not None else "Estimated carbon: unavailable")
        lines.append(f"Estimated cost: {_format_cost(decision.native_cost, decision.currency)}")
    body = "\n".join(lines) + _footer(job.job_id, f"workloads/{job.job_id}")
    return subject, body


def _render_schedule_approved(db: Session, job: JobORM, decision: Optional[ScheduleDecisionORM]) -> Tuple[str, str]:
    subject = _subject("Schedule approved", _workload_name(job))
    lines = [
        "The schedule for your workload was approved and is proceeding toward execution.",
        "",
        f"Workload:  {_workload_name(job)}",
        f"Job ID:    {job.job_id}",
        f"Region:    {job.region}",
    ]
    if decision is not None and decision.selected_start:
        lines.append(f"Scheduled start: {format_regional_time(decision.selected_start, region=job.region)}")
        lines.append(f"Estimated cost: {_format_cost(decision.native_cost, decision.currency)}")
    approval = _latest_approval(db, job.job_id, "APPROVED")
    if approval is not None and approval.approved_by:
        lines.append(f"Approved by: {approval.approved_by}")
    body = "\n".join(lines) + _footer(job.job_id, f"workloads/{job.job_id}")
    return subject, body


def _render_schedule_declined(db: Session, job: JobORM, decision: Optional[ScheduleDecisionORM] = None) -> Tuple[str, str]:
    subject = _subject("Schedule declined", _workload_name(job), bracket="HIGH")
    lines = [
        "The proposed schedule for your workload was declined.",
        "",
        f"Workload:  {_workload_name(job)}",
        f"Job ID:    {job.job_id}",
        f"Region:    {job.region}",
    ]
    approval = _latest_approval(db, job.job_id, "DECLINED")
    if approval is not None:
        lines.append(f"Declined by: {approval.approved_by or 'unavailable'}")
        lines.append(f"Reason:      {approval.reason or 'No reason provided'}")
    else:
        lines.append("Reason:      unavailable")
    body = "\n".join(lines) + _footer(job.job_id, f"workloads/{job.job_id}")
    return subject, body


def _render_scheduling_failed(db: Session, job: JobORM, decision: Optional[ScheduleDecisionORM] = None) -> Tuple[str, str]:
    subject = _subject("Scheduling failed", _workload_name(job), bracket="HIGH")
    lines = [
        "GreenShift could not find a feasible execution window for your workload.",
        "",
        f"Workload:  {_workload_name(job)}",
        f"Job ID:    {job.job_id}",
        f"Region:    {job.region}",
        f"Status:    {job.status.value if hasattr(job.status, 'value') else job.status}",
        f"Deadline:  {format_regional_time(job.deadline, region=job.region)}" if job.deadline else "Deadline:  unavailable",
        f"Carbon budget: {job.carbon_budget_kg:.3f} kg CO2" if job.carbon_budget_kg is not None else "Carbon budget: not set",
    ]
    body = "\n".join(lines) + _footer(job.job_id, f"workloads/{job.job_id}")
    return subject, body


def _render_execution_started(db: Session, job: JobORM, decision: Optional[ScheduleDecisionORM] = None) -> Tuple[str, str]:
    subject = _subject("Execution started", _workload_name(job))
    exec_row = getattr(job, "kubernetes_execution", None)
    lines = [
        "Your workload has been dispatched to Kubernetes and is now executing.",
        "",
        f"Workload:  {_workload_name(job)}",
        f"Job ID:    {job.job_id}",
        f"Region:    {job.region}",
    ]
    if exec_row is not None and exec_row.actual_start:
        lines.append(f"Started: {format_regional_time(exec_row.actual_start, region=job.region)}")
    body = "\n".join(lines) + _footer(job.job_id, f"workloads/{job.job_id}")
    return subject, body


def _render_execution_completed(db: Session, job: JobORM, decision: Optional[ScheduleDecisionORM] = None) -> Tuple[str, str]:
    subject = _subject("Execution completed", _workload_name(job))
    exec_row = getattr(job, "kubernetes_execution", None)
    lines = [
        "Your workload finished executing successfully.",
        "",
        f"Workload:  {_workload_name(job)}",
        f"Job ID:    {job.job_id}",
        f"Region:    {job.region}",
    ]
    if exec_row is not None and exec_row.actual_end:
        lines.append(f"Completed: {format_regional_time(exec_row.actual_end, region=job.region)}")
    if decision is not None:
        lines.append(f"Carbon avoided: {decision.carbon_avoided:.3f} kg CO2" if decision.carbon_avoided is not None else "Carbon avoided: unavailable")
    body = "\n".join(lines) + _footer(job.job_id, f"workloads/{job.job_id}")
    return subject, body


def _render_execution_failed(db: Session, job: JobORM, decision: Optional[ScheduleDecisionORM] = None) -> Tuple[str, str]:
    subject = _subject("Workload execution failed", _workload_name(job), bracket="CRITICAL")
    exec_row = getattr(job, "kubernetes_execution", None)
    lines = [
        "Your workload's execution failed.",
        "",
        f"Workload:  {_workload_name(job)}",
        f"Job ID:    {job.job_id}",
        f"Region:    {job.region}",
        f"Failure reason: {exec_row.error_message if exec_row and exec_row.error_message else 'unavailable'}",
        "",
        "Check Job Monitoring for full execution details.",
    ]
    body = "\n".join(lines) + _footer(job.job_id, f"workloads/{job.job_id}")
    return subject, body


def _render_critical_system_alert(db: Session, notif: NotificationORM) -> Tuple[str, str]:
    """Fallback template for account/security/system/infrastructure events
    that have no associated job (nothing to look up via job_id) — renders
    directly from the notification's own already-correct, already-audited
    title/message, with a bracketed subject reflecting its real severity."""
    bracket = "CRITICAL" if notif.severity == "CRITICAL" else ("HIGH" if notif.severity == "WARNING" else None)
    tag = f"[{bracket}]" if bracket else ""
    subject = f"[{_APP_NAME}]{tag} {notif.title}"
    body = notif.message + f"\n\n— {_APP_NAME}, carbon-aware workload scheduling"
    return subject, body


# event_type -> renderer(db, job, decision). Every job-scoped renderer
# shares this signature (decision may be None/unused) so dispatch never has
# to special-case argument counts. SCHEDULE_PROPOSED and JOB_CANCELLED are
# handled separately in render_email() since their template depends on the
# notification's category/dedup_key, not just its event_type.
_RENDERERS = {
    EventType.JOB_SCHEDULED: _render_job_scheduled,
    EventType.APPROVAL_GRANTED: _render_schedule_approved,
    EventType.APPROVAL_DECLINED: _render_schedule_declined,
    EventType.SCHEDULING_FAILED: _render_scheduling_failed,
    EventType.K8S_JOB_CREATED: _render_execution_started,
    EventType.K8S_JOB_COMPLETED: _render_execution_completed,
    EventType.K8S_JOB_FAILED: _render_execution_failed,
    # JOB_CANCELLED is handled separately in render_email() — its subject/
    # body differ between the submitter's copy and the admin fan-out copy.
}


def _cancelled_subject_and_body(job: JobORM, is_admin_copy: bool) -> Tuple[str, str]:
    subject = _subject("Workload cancelled", _workload_name(job), bracket="HIGH" if is_admin_copy else None)
    lines = [
        "A workload requiring your attention was cancelled." if is_admin_copy else "Your workload was cancelled.",
        "",
        f"Workload:  {_workload_name(job)}",
        f"Job ID:    {job.job_id}",
        f"Region:    {job.region}",
    ]
    body = "\n".join(lines) + _footer(job.job_id, f"workloads/{job.job_id}")
    return subject, body


def render_email(db: Session, notif: NotificationORM) -> Tuple[str, str]:
    """
    Returns (subject, body) for the given notification. Falls back to the
    notification's own (title, message) — already correct, already used
    for in-app display — whenever no richer template applies (unknown
    event_type, or the referenced job no longer exists).
    """
    job, decision = _job_context(db, notif.job_id)

    if job is None:
        # No job to enrich from — either a genuinely job-less event
        # (account/security/system) or a job that no longer exists.
        if notif.category in ("SECURITY", "ACCOUNT", "SYSTEM", "INFRASTRUCTURE"):
            try:
                return _render_critical_system_alert(db, notif)
            except Exception:
                pass
        return notif.title, notif.message

    try:
        if notif.event_type == EventType.SCHEDULE_PROPOSED:
            if notif.category == "APPROVAL":
                return _render_approval_required(db, job, decision)
            return _render_schedule_proposed_submitter(db, job, decision)

        if notif.event_type == EventType.JOB_CANCELLED:
            is_admin_copy = (notif.dedup_key or "").endswith(":admin")
            return _cancelled_subject_and_body(job, is_admin_copy)

        renderer = _RENDERERS.get(notif.event_type)
        if renderer is not None:
            return renderer(db, job, decision)
    except Exception:
        # A template rendering bug must never block delivery of the
        # already-correct fallback content.
        pass

    return notif.title, notif.message
