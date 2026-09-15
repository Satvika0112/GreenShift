"""
GreenShift — Scheduling Engine Explainability & Candidate Slot Comparison View.
"""

import pandas as pd
import streamlit as st

from app.dashboard.api_client import fetch_jobs, fetch_job_detail, fetch_schedule_decisions
from app.dashboard.components import (
    render_section_header,
    render_metric_card,
    render_decision_factor,
    render_status_badge,
)
from app.dashboard.scheduling_explainability import (
    NA,
    compute_decision_factors,
    format_candidate_table,
    format_scheduler_objective,
)


def render_scheduling_engine_view() -> None:
    """Render the DECIDE scheduling optimization and explainability view."""
    render_section_header("⚙️ Scheduling Engine & Explainability", "Deep inspection into Carbon-First mathematical optimization and candidate slot evaluation")

    jobs = fetch_jobs(limit=100)
    # GET /api/v1/jobs flattens schedule_decision fields directly onto the
    # job item (no "schedule_decision" key at all — see
    # app/api/routers/ingest.py's list endpoint) — "selected_start" is the
    # real signal a decision exists, not a key this list never has.
    scheduled_jobs = [j for j in jobs if j.get("selected_start") is not None]

    if not scheduled_jobs:
        scheduled_jobs = jobs[:10] if jobs else []

    if not scheduled_jobs:
        st.info("No workloads with scheduling decisions found. Submit a workload to evaluate candidate slots.")
        return

    col_list, col_details = st.columns([1, 2.2], gap="large")

    with col_list:
        st.markdown("#### Select Workload")
        job_options = {j.get("job_id"): f"{j.get('job_id')} ({j.get('region', 'IN-TG')})" for j in scheduled_jobs}
        selected_job_id = st.radio("Evaluated Jobs", list(job_options.keys()), format_func=lambda x: job_options[x])

    with col_details:
        job_data = fetch_job_detail(selected_job_id) if selected_job_id else {}
        dec = job_data.get("schedule_decision") or {}

        if not dec:
            st.info("No scheduling decision available for this workload yet.")
            return

        st.markdown(
            f'<div class="gs-card-header" style="margin-bottom: 12px;">'
            f'<div>'
            f'<div class="gs-card-title">Optimal Execution Window</div>'
            f'<div class="gs-card-subtitle">Workload: <code>{selected_job_id}</code> | Objective: <strong>{format_scheduler_objective(dec)}</strong></div>'
            f'</div>'
            f'<div>{render_status_badge(job_data.get("status", "SCHEDULED"))}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        sel_start = (dec.get("selected_start") or "")[:16].replace("T", " ")
        carbon_intensity = dec.get("carbon_intensity")
        cost_usd = dec.get("electricity_cost")
        carbon_avoided = dec.get("carbon_avoided")
        reason = dec.get("reason") or NA
        # Currency Consistency: prefer the execution region's real native_cost +
        # currency — electricity_cost is always USD internally and must never be
        # shown as "$" for an INR/AUD/SEK region.
        native_cost, currency = dec.get("native_cost"), dec.get("currency")
        if native_cost is not None and currency:
            cost_display = f"{native_cost:.4f} {currency}"
        elif cost_usd is not None:
            cost_display = f"{cost_usd:.4f} USD"
        else:
            cost_display = NA

        # Decision Metrics (Carbon, Cost, Window, Slot Contention) — every
        # value below is read directly off the real ScheduleDecision; a
        # missing field renders N/A rather than a fabricated placeholder.
        m1, m2, m3, m4 = st.columns(4)
        with m1:
            carbon_str = f"{carbon_intensity:.1f} gCO₂/kWh" if carbon_intensity is not None else NA
            avoided_str = f"{carbon_avoided:.4f} kg avoided" if carbon_avoided is not None else NA
            st.markdown(render_metric_card("Carbon Intensity", carbon_str, avoided_str, accent=True), unsafe_allow_html=True)
        with m2:
            st.markdown(render_metric_card("Electricity Cost", cost_display, "Time-of-Day rate applied"), unsafe_allow_html=True)
        with m3:
            runtime_min = job_data.get("runtime_minutes")
            duration_str = f"Duration: {runtime_min} min" if runtime_min is not None else NA
            st.markdown(render_metric_card("Scheduling Window", sel_start or NA, duration_str), unsafe_allow_html=True)
        with m4:
            slot_util = dec.get("slot_utilization_pct")
            util_str = f"{slot_util:.1f}%" if slot_util is not None else NA
            spilled = dec.get("spilled_from_preferred", False)
            spill_sub = "Spilled from peak" if spilled else ("Preferred slot fit" if slot_util is not None else NA)
            st.markdown(render_metric_card("Slot Capacity Util.", util_str, spill_sub), unsafe_allow_html=True)

        # Why this slot? Every bullet below is gated on the real data point
        # it describes actually being present — never asserted unconditionally.
        method = dec.get("scheduling_method") or NA
        ml_used = dec.get("ml_advisor_used", False)
        demand_pred = dec.get("demand_predicted")
        baseline_carbon = dec.get("baseline_carbon_emission")
        st.markdown("#### 💡 Why this slot was selected:")

        carbon_bullet = (
            f"• Carbon intensity in this slot avoided <strong>{carbon_avoided:.4f} kg CO₂</strong> "
            f"({dec.get('carbon_reduction_pct'):.1f}% reduction) versus the immediate-execution baseline.<br>"
            if baseline_carbon is not None and baseline_carbon > 0
            and carbon_avoided is not None and dec.get("carbon_reduction_pct") is not None
            else ""
        )
        contention_bullet = (
            f"• <strong>Contention-Aware Scheduling</strong>: Slot utilization at allocation was <strong>{util_str}</strong>. "
            + ("Workload was gently spilled to this slot because preferred slot reached capacity limit.<br>" if spilled else "Workload successfully accommodated in preferred low-carbon window.<br>")
            if slot_util is not None else ""
        )
        ml_bullet = (
            f"• <strong>ML Demand Forecaster (Layer 2)</strong>: Predicted future arrival pressure: <strong>{demand_pred:.3f}</strong> (5% soft penalty applied to preserve peak headroom).<br>"
            if ml_used and demand_pred is not None else ""
        )
        # A persisted ScheduleDecision only ever exists for a job that
        # passed every hard constraint (an infeasible slot raises before
        # any decision is stored — see app.decide.scheduler) — this
        # statement is a structural fact about this record's existence,
        # not an assumption.
        constraints_bullet = "• Hard deadline and cluster capacity constraints were satisfied at decision time."

        st.markdown(
            f'<div style="background: #041315; border: 1px solid #0E383C; border-left: 4px solid #00E599; padding: 14px 18px; border-radius: 8px; margin-bottom: 20px;">'
            f'<div style="color: #FFFFFF; font-weight: 600; margin-bottom: 6px;">✓ Method: <code>{method}</code> | {reason}</div>'
            f'<div style="font-size: 0.85rem; color: #94A3B8;">'
            f'{carbon_bullet}'
            f'{contention_bullet}'
            f'{ml_bullet}'
            f'{constraints_bullet}'
            f'</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # Decision Factors — every value is derived from the real decision
        # (app.dashboard.scheduling_explainability.compute_decision_factors);
        # a factor whose source data is unavailable renders N/A, never a
        # fabricated 88/74/82/95.
        factors = compute_decision_factors(dec, job_data.get("deadline"))
        st.markdown("#### 📊 Decision Factors")
        st.caption("Carbon Abatement = improvement vs. immediate-execution baseline · Cost Score = improvement vs. baseline electricity cost · SLA Margin = actual remaining buffer before deadline")

        carbon_pct = factors["carbon_abatement_pct"]
        st.markdown(
            render_decision_factor("Carbon Abatement Score", carbon_pct if carbon_pct is not None else 0.0, f"{carbon_pct:.1f}%" if carbon_pct is not None else NA),
            unsafe_allow_html=True,
        )
        cost_pct = factors["cost_score_pct"]
        st.markdown(
            render_decision_factor("Cost Reduction Score", cost_pct if cost_pct is not None else 0.0, f"{cost_pct:.1f}%" if cost_pct is not None else NA),
            unsafe_allow_html=True,
        )
        headroom_pct = factors["slot_headroom_pct"]
        st.markdown(
            render_decision_factor("Slot Capacity Headroom", headroom_pct if headroom_pct is not None else 0.0, f"{headroom_pct:.0f}% free" if headroom_pct is not None else NA),
            unsafe_allow_html=True,
        )
        # SLA Margin is a plain time buffer, not a normalized 0-100 score —
        # there is no established scoring convention for it in this project.
        sla_hours = factors["sla_buffer_hours"]
        sla_str = f"{sla_hours:.1f}h before deadline" if sla_hours is not None else NA
        st.markdown(render_metric_card("SLA Margin / Buffer", sla_str, "Actual remaining time before the job's deadline"), unsafe_allow_html=True)

        # Candidate Slot Comparison Table — built only from the scheduler's
        # own recorded candidate evaluations (candidates_json /
        # rejected_candidates_json), never a synthetic +/-1h/+/-2h sweep.
        st.markdown("#### 🔍 Candidate Slot Comparison")
        table_rows = format_candidate_table(dec)
        if not table_rows:
            st.info("No candidate data available for this decision.")
        else:
            st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)
