"""
GreenShift — Scheduling Decision Explainability Helpers.

Shared, presentation-only helpers consumed by BOTH
app.dashboard.views.scheduling_engine and app.dashboard.views.workloads so
the two views never diverge into independent implementations of "why did
GreenShift choose this window" (Dashboard Scheduling Consistency &
Explainability Hardening Pass).

Every value here is derived directly from the real ScheduleDecision fields
the backend already returns — GET /api/v1/jobs/{job_id}'s
"schedule_decision" object (app/api/routers/ingest.py::get_job_detail),
itself sourced from ScheduleDecisionORM, whose candidates_json /
rejected_candidates_json columns are populated by the actual scheduler
(app/decide/scheduler.py's candidates_list / rejected_candidates_list) and
whose carbon_reduction_pct / cost_reduction_pct are computed by
app/decide/impact_calculator.py. Nothing in this module recomputes
scheduler business logic, estimates a value from a time offset, or
invents a fallback — a value that cannot be derived from real fields is
reported as None so callers render "N/A" (or an equivalent explicit empty
state), never a fabricated number.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

NA = "N/A"

# The scheduler's per-candidate electricity_cost (app.decide.scheduler
# CandidateEvaluation.electricity_cost / candidates_json) is always USD —
# see the "Currency Consistency Hardening" comments throughout
# app/decide/scheduler.py and app/shared/models.py. Candidate-level native
# currency conversion is not computed by the scheduler for every
# candidate slot (only for the winning one, via native_cost/currency on
# the decision itself) — so candidate rows are honestly labeled USD
# instead of silently mislabeling them with the decision's native currency
# or fabricating a conversion this module has no authoritative rate for.
CANDIDATE_COST_CURRENCY = "USD"

# Maps the scheduler's real structured rejection codes
# (app.decide.scheduler.CandidateRejectionReason) to a short human label.
# Presentation-only translation — the underlying code is always the
# authoritative value; an unrecognized code still renders (title-cased)
# rather than being silently swallowed into a generic label.
_REJECTION_LABELS = {
    "DEADLINE_VIOLATION": "Misses Deadline",
    "SLA_VIOLATION": "Misses Deadline",
    "CARBON_BUDGET_EXCEEDED": "Exceeds Carbon Budget",
    "CARBON_THRESHOLD": "Exceeds Carbon Budget",
    "INSUFFICIENT_CPU": "Insufficient CPU",
    "INSUFFICIENT_RAM": "Insufficient RAM",
    "INSUFFICIENT_MEMORY": "Insufficient RAM",
    "INSUFFICIENT_GPU": "Insufficient GPU",
    "GPU_UNAVAILABLE": "Insufficient GPU",
    "REGION_INELIGIBLE": "Outside Allowed Region",
    "POLICY_RESTRICTION": "Outside Allowed Region",
    "CARBON_DATA_UNAVAILABLE": "Carbon Data Unavailable",
    "COST_DATA_UNAVAILABLE": "Cost Data Unavailable",
    "COST_THRESHOLD": "Cost Threshold Exceeded",
}


def humanize_rejection_reason(code: Optional[str]) -> str:
    """Translate one real scheduler rejection code into a short human
    label. Never invents a reason: a missing code renders N/A, and an
    unrecognized code is shown as its own title-cased text rather than
    being coerced into an unrelated label like "Higher Carbon"."""
    if not code:
        return NA
    return _REJECTION_LABELS.get(code, code.replace("_", " ").title())


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def format_scheduler_objective(dec: Dict[str, Any]) -> str:
    """
    The optimization policy actually applied to this decision — mirrors
    frontend/src/components/decision/GreenShiftRecommendation.tsx's
    policySubtitle logic (never a hardcoded 'CARBON_FIRST' string).
    """
    objective = dec.get("scheduler_objective") or dec.get("objective")
    if not objective:
        return NA
    if objective == "CARBON_CONSTRAINED":
        tol = dec.get("carbon_tolerance_pct")
        if tol is not None:
            try:
                return f"CARBON_CONSTRAINED ({float(tol):g}% tolerance)"
            except (TypeError, ValueError):
                pass
        return "CARBON_CONSTRAINED"
    return str(objective)


def compute_decision_factors(dec: Dict[str, Any], deadline_iso: Optional[str]) -> Dict[str, Optional[float]]:
    """
    Derive the real Decision Factors from the actual ScheduleDecision.

    - carbon_abatement_pct: the backend's own carbon_reduction_pct
      (app.decide.impact_calculator.calculate_impact), gated on a real,
      positive baseline_carbon_emission existing — None (N/A) otherwise,
      never a fabricated score.
    - cost_score_pct: the backend's own cost_reduction_pct, gated on a
      real, positive baseline_cost existing. Reported as-is, including
      negative values (GreenShift's pick cost more than baseline under a
      carbon-prioritizing policy) — never clamped to hide that.
    - slot_headroom_pct: 100 - slot_utilization_pct, only when the
      contention-aware batch scheduler actually populated it (None for
      single-job greedy scheduling, which has no capacity registry).
    - sla_buffer_hours: deadline - selected_end in hours — a plain
      subtraction of two real timestamps already on the job/decision, not
      a normalized/invented 0-100 score.
    """
    baseline_carbon = dec.get("baseline_carbon_emission")
    carbon_reduction_pct = dec.get("carbon_reduction_pct")
    carbon_abatement_pct = (
        carbon_reduction_pct
        if baseline_carbon is not None and baseline_carbon > 0 and carbon_reduction_pct is not None
        else None
    )

    baseline_cost = dec.get("baseline_cost")
    cost_reduction_pct = dec.get("cost_reduction_pct")
    cost_score_pct = (
        cost_reduction_pct
        if baseline_cost is not None and baseline_cost > 0 and cost_reduction_pct is not None
        else None
    )

    slot_util = dec.get("slot_utilization_pct")
    slot_headroom_pct = (100.0 - slot_util) if slot_util is not None else None

    deadline_dt = _parse_iso(deadline_iso)
    selected_end_dt = _parse_iso(dec.get("selected_end"))
    sla_buffer_hours = (
        (deadline_dt - selected_end_dt).total_seconds() / 3600.0
        if deadline_dt is not None and selected_end_dt is not None
        else None
    )

    return {
        "carbon_abatement_pct": carbon_abatement_pct,
        "cost_score_pct": cost_score_pct,
        "slot_headroom_pct": slot_headroom_pct,
        "sla_buffer_hours": sla_buffer_hours,
    }


def build_candidate_rows(dec: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Build candidate comparison rows directly from the scheduler's own
    per-candidate evaluation data — GET /api/v1/jobs/{id}'s
    schedule_decision.candidates / .rejected_candidates, sourced from
    ScheduleDecisionORM.candidates_json / rejected_candidates_json, which
    app.decide.scheduler._execute_schedule_job populates from its actual
    per-slot evaluation loop. Never a synthetic +/-1h/+/-2h sweep with an
    hour-offset carbon or cost formula.

    Returns [] when the backend has no candidate data for this decision
    (older decisions predating this instrumentation, or a non-deferrable
    single-slot job that only ever evaluated one candidate) — callers
    must render an explicit "No candidate data available" state, never
    fall back to inventing candidates.
    """
    feasible = dec.get("candidates") or []
    rejected = dec.get("rejected_candidates") or []
    if not feasible and not rejected:
        return []

    selected_start = dec.get("selected_start")
    rows: List[Dict[str, Any]] = []

    for cand in feasible:
        is_selected = bool(selected_start) and cand.get("slot_start") == selected_start
        rows.append({
            "slot_start": cand.get("slot_start"),
            "slot_end": cand.get("slot_end"),
            "carbon_intensity": cand.get("carbon_intensity"),
            "carbon_emission": cand.get("carbon_emission"),
            "electricity_cost": cand.get("electricity_cost"),
            "feasible": True,
            "is_selected": is_selected,
            "decision_label": "SELECTED" if is_selected else "Feasible (not selected)",
        })

    for cand in rejected:
        reasons = cand.get("rejection_reasons") or []
        primary = cand.get("primary_rejection_reason") or (reasons[0] if reasons else None)
        rows.append({
            "slot_start": cand.get("slot_start"),
            "slot_end": cand.get("slot_end"),
            "carbon_intensity": cand.get("carbon_intensity"),
            "carbon_emission": cand.get("carbon_emission"),
            "electricity_cost": cand.get("electricity_cost"),
            "feasible": False,
            "is_selected": False,
            "decision_label": humanize_rejection_reason(primary),
        })

    rows.sort(key=lambda r: r.get("slot_start") or "")
    return rows


def format_candidate_table(dec: Dict[str, Any]) -> List[Dict[str, str]]:
    """Formats build_candidate_rows() output into the exact string columns
    both dashboard views display, so neither view re-derives its own
    formatting rules for the same real data."""
    rows = build_candidate_rows(dec)
    formatted: List[Dict[str, str]] = []
    for r in rows:
        start = (r.get("slot_start") or "")[:16].replace("T", " ")
        end = (r.get("slot_end") or "")[:16].replace("T", " ")
        c_int = r.get("carbon_intensity")
        c_cost = r.get("electricity_cost")
        formatted.append({
            "Candidate Window (UTC)": f"{start} → {end}" if start or end else NA,
            "Carbon Intensity": f"{c_int:.1f} gCO₂/kWh" if c_int is not None else NA,
            "Electricity Cost": f"{c_cost:.4f} {CANDIDATE_COST_CURRENCY}" if c_cost is not None else NA,
            "Feasible": "✓ Yes" if r.get("feasible") else "✗ No",
            "Decision": r.get("decision_label", NA),
        })
    return formatted
