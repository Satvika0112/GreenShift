"""
GreenShift — Page 2: Workloads.

Merges: workloads + scheduling_engine + job_monitoring + approvals.
4 inner tabs: Queue & List | Scheduling Decisions | Live Monitoring | Approval Queue
"""

import pandas as pd
import plotly.express as px
import streamlit as st

from app.dashboard.api_client import (
    fetch_jobs,
    fetch_job_detail,
    fetch_schedule_decisions,
    fetch_pending_approvals,
    fetch_declined_approvals,
    schedule_job_api,
    approve_job_api,
    decline_job_api,
    dispatch_job_api,
    cancel_job_api,
    fetch_fleet_impact_api,
)
from app.dashboard.components import (
    render_metric_card,
    render_section_header,
    render_status_badge,
    render_execution_timeline,
    render_decision_factor,
)
from app.dashboard.scheduling_explainability import (
    NA,
    compute_decision_factors,
    format_candidate_table,
    format_scheduler_objective,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _nav_to_submit():
    """Route user to Submit Workload page."""
    st.session_state["current_page"] = "➕ Submit Workload"
    st.rerun()


def _empty_state_submit(msg: str = "No workloads found."):
    st.info(msg)
    if st.button("➕ Submit your first workload", key=f"cta_submit_{msg[:20]}", type="primary"):
        _nav_to_submit()


# ─────────────────────────────────────────────────────────────────────────────
# Tab A — Queue & List
# ─────────────────────────────────────────────────────────────────────────────

def _render_queue_tab():
    render_section_header("📋 Workload Management", "Track, filter, and inspect enterprise compute jobs across all regions")

    jobs = fetch_jobs(limit=1000)

    # Search + filters
    f1, f2, f3, f4 = st.columns(4)
    with f1:
        search_query = st.text_input("🔍 Search Workloads", placeholder="Search by Job ID or name...", key="wl_search")
    with f2:
        status_options = ["ALL", "SUBMITTED", "VALIDATED", "PENDING_APPROVAL", "APPROVED", "SCHEDULED", "QUEUED", "DISPATCHING", "RUNNING", "COMPLETED", "DECLINED", "FAILED", "CANCELLED"]
        selected_status = st.selectbox("Status Filter", status_options, index=0, key="wl_status")
    with f3:
        region_options = ["ALL", "IN-TG", "IN-GJ", "IN-HP", "IN-WB", "US-CA", "US-TX", "US-NY", "SE", "AU-SA-Large", "AU-SA-Small"]
        selected_region = st.selectbox("Region Filter", region_options, index=0, key="wl_region")
    with f4:
        priority_options = ["ALL", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
        selected_priority = st.selectbox("Priority Filter", priority_options, index=0, key="wl_priority")

    # Filter
    filtered_jobs = []
    for j in jobs:
        if search_query:
            q = search_query.lower()
            if q not in j.get("job_id", "").lower() and q not in j.get("workload_name", "").lower():
                continue
        if selected_status != "ALL" and j.get("status") != selected_status:
            continue
        if selected_region != "ALL" and j.get("region") != selected_region:
            continue
        if selected_priority != "ALL" and j.get("priority", "MEDIUM").upper() != selected_priority:
            continue
        filtered_jobs.append(j)

    st.markdown(f"**Showing {len(filtered_jobs)} of {len(jobs)} workloads**")

    if not filtered_jobs:
        _empty_state_submit("No workloads match your filters — or no workloads exist yet.")
        return

    # Table
    table_data = []
    for j in filtered_jobs:
        dec = j.get("schedule_decision") or {}
        table_data.append({
            "Job ID": j.get("job_id"),
            "Type": j.get("job_type", "Batch"),
            "Team": j.get("team_id", "analytics"),
            "Priority": j.get("priority", "MEDIUM"),
            "Status": j.get("status", "SUBMITTED"),
            "Region": j.get("region", "IN-TG"),
            "Runtime (min)": j.get("runtime_minutes", 30),
            "Power (kW)": j.get("power_kw", 1.0),
            "Energy (kWh)": round(j.get("power_kw", 1.0) * j.get("runtime_minutes", 30) / 60, 3),
            "Deferrable": j.get("deferrable", True),
            "Deadline": (j.get("deadline") or "")[:16].replace("T", " "),
        })

    df = pd.DataFrame(table_data)
    st.dataframe(df, use_container_width=True, hide_index=True)

    # Inspector
    st.markdown("---")
    render_section_header("🔍 Workload Detail Inspector", "Inspect scheduling decision, timeline, and resource specs for a job")

    inspect_job_id = st.selectbox("Select Workload to Inspect", [j.get("job_id") for j in filtered_jobs], key="wl_inspect_sel")
    if inspect_job_id:
        job_detail = fetch_job_detail(inspect_job_id)
        dec = job_detail.get("schedule_decision") or {}
        current_st = job_detail.get("status", "SUBMITTED")
        token = st.session_state.get("auth_token")

        st.markdown(
            f'<div class="gs-card-header" style="margin-bottom:12px;">'
            f'<div>'
            f'<div class="gs-card-title">{job_detail.get("workload_name", inspect_job_id)}</div>'
            f'<div class="gs-card-subtitle">ID: <code>{inspect_job_id}</code> | Team: {job_detail.get("team_id")} | Region: {job_detail.get("region")}</div>'
            f'</div>'
            f'<div>{render_status_badge(current_st)}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        st.markdown(render_execution_timeline(current_st), unsafe_allow_html=True)

        col_spec, col_sched = st.columns(2)
        with col_spec:
            st.markdown("#### ⚙️ Resource Specifications")
            st.markdown(f"- **CPU Request:** `{job_detail.get('cpu_request', '500m')}`")
            st.markdown(f"- **Memory Request:** `{job_detail.get('memory_request', '512Mi')}`")
            st.markdown(f"- **Power Demand:** `{job_detail.get('power_kw', 1.0)} kW`")
            st.markdown(f"- **Container Image:** `{job_detail.get('container_image', 'greenshift/job:v1')}`")
            st.markdown(f"- **Earliest Start:** `{job_detail.get('earliest_start_time', 'Immediate')}`")
            st.markdown(f"- **Deadline:** `{job_detail.get('deadline', 'N/A')}`")
        with col_sched:
            st.markdown("#### 🌿 Scheduling Decision")
            if dec:
                _ci = dec.get("carbon_intensity")
                _ca = dec.get("carbon_avoided")
                st.markdown(f"- **Selected Window:** `{(dec.get('selected_start') or '')[:16]} → {(dec.get('selected_end') or '')[:16]}`")
                st.markdown(f"- **Carbon Intensity:** `{f'{_ci} gCO₂/kWh' if _ci is not None else NA}`")
                _native_cost, _currency = dec.get("native_cost"), dec.get("currency")
                _electricity_cost = dec.get("electricity_cost")
                if _native_cost is not None and _currency:
                    _cost_display = f"{_native_cost:.4f} {_currency}"
                elif _electricity_cost is not None:
                    _cost_display = f"{_electricity_cost:.4f} USD"
                else:
                    _cost_display = NA
                st.markdown(f"- **Electricity Cost:** `{_cost_display}`")
                st.markdown(f"- **Carbon Avoided:** `{f'{_ca:.4f} kg' if _ca is not None else NA}`")
                st.markdown(f"- **Optimization Reason:** *{dec.get('reason') or NA}*")
            else:
                st.caption("No scheduling decision generated yet.")

        # Action Gate
        st.markdown("---")
        if current_st in ("SUBMITTED", "VALIDATED"):
            st.markdown(f"⚡ **Workload is {current_st} — ready for Carbon-First scheduling.**")
            ca1, ca2 = st.columns([1.5, 1])
            with ca1:
                if st.button("🚀 Run Scheduling Engine Now", key=f"sched_{inspect_job_id}", type="primary"):
                    try:
                        with st.spinner("Computing optimal low-carbon window..."):
                            sched_res = schedule_job_api(inspect_job_id, token=token)
                            st.success(f"Scheduled! Window: {sched_res.get('selected_start', '')[:16]} UTC")
                            st.rerun()
                    except Exception as exc:
                        st.error(f"Scheduling failed: {exc}")
            with ca2:
                if st.button("🚫 Cancel Workload", key=f"cncl_{inspect_job_id}"):
                    try:
                        cancel_job_api(inspect_job_id, token=token)
                        st.warning(f"Workload `{inspect_job_id}` cancelled.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Cancel failed: {exc}")

        elif current_st == "PENDING_APPROVAL":
            st.markdown("🛡️ **Workload awaiting Human Approval before dispatch.**")
            ca1, ca2, ca3 = st.columns(3)
            with ca1:
                if st.button("✓ Approve Schedule", key=f"app_{inspect_job_id}", type="primary", use_container_width=True):
                    try:
                        approve_job_api(inspect_job_id, schedule_id=dec.get("id", 0), token=token)
                        st.success(f"Workload `{inspect_job_id}` approved!")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Approval failed: {exc}")
            with ca2:
                if st.button("✕ Decline Schedule", key=f"dec_{inspect_job_id}", use_container_width=True):
                    try:
                        decline_job_api(inspect_job_id, schedule_id=dec.get("id", 0), reason="Declined by operator", token=token)
                        st.warning(f"Workload `{inspect_job_id}` declined.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Decline failed: {exc}")
            with ca3:
                if st.button("🚫 Cancel", key=f"cncl_pa_{inspect_job_id}", use_container_width=True):
                    try:
                        cancel_job_api(inspect_job_id, token=token)
                        st.warning(f"Workload `{inspect_job_id}` cancelled.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Cancel failed: {exc}")

        elif current_st == "APPROVED":
            st.markdown("🚀 **Workload is APPROVED — ready for Kubernetes dispatch.**")
            cd1, cd2 = st.columns([1.5, 1])
            with cd1:
                if st.button("☸️ Dispatch to Kubernetes Cluster", key=f"disp_{inspect_job_id}", type="primary"):
                    try:
                        with st.spinner("Dispatching workload to cluster..."):
                            disp_res = dispatch_job_api(inspect_job_id, token=token)
                            st.success(f"Dispatched! Status: {disp_res.get('gs_status', 'QUEUED')} | Pod: {disp_res.get('pod_name', 'gs-pod')}")
                            st.rerun()
                    except Exception as exc:
                        st.error(f"Dispatch failed: {exc}")
            with cd2:
                if st.button("🚫 Cancel Workload", key=f"cncl_app_{inspect_job_id}"):
                    try:
                        cancel_job_api(inspect_job_id, token=token)
                        st.warning(f"Workload `{inspect_job_id}` cancelled.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Cancel failed: {exc}")

        elif current_st in ("QUEUED", "RUNNING", "DISPATCHING"):
            st.markdown(f"ℹ️ Workload is executing in Kubernetes. Status: **{current_st}**.")
            if st.button("⟳ Refresh Live Status", key=f"refresh_{inspect_job_id}"):
                st.cache_data.clear()
                st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# Tab B — Scheduling Decisions
# ─────────────────────────────────────────────────────────────────────────────

def _render_scheduling_tab():
    render_section_header("⚙️ Scheduling Engine & Explainability", "Deep inspection into Carbon-First mathematical optimization and candidate slot evaluation")

    jobs = fetch_jobs(limit=100)
    # GET /api/v1/jobs flattens schedule_decision fields directly onto the
    # job item (there is no "schedule_decision" key on this list endpoint —
    # see app/api/routers/ingest.py) — "selected_start" is the real signal
    # a decision exists.
    scheduled_jobs = [j for j in jobs if j.get("selected_start") is not None]
    if not scheduled_jobs:
        scheduled_jobs = [j for j in jobs if j.get("status") not in ("SUBMITTED", "VALIDATED")][:10]
    if not scheduled_jobs:
        scheduled_jobs = jobs[:10]

    if not scheduled_jobs:
        st.info("No workloads with scheduling decisions found. Submit a workload to evaluate candidate slots.")
        if st.button("➕ Submit a workload", key="sched_cta", type="primary"):
            _nav_to_submit()
        return

    col_list, col_details = st.columns([1, 2.2], gap="large")

    with col_list:
        st.markdown("#### Select Workload")
        job_options = {j.get("job_id"): f"{j.get('job_id')} ({j.get('region', 'IN-TG')})" for j in scheduled_jobs}
        selected_job_id = st.radio("Evaluated Jobs", list(job_options.keys()), format_func=lambda x: job_options[x], key="sched_sel")

    with col_details:
        job_data = fetch_job_detail(selected_job_id) if selected_job_id else {}
        dec = job_data.get("schedule_decision") or {}

        if not dec:
            st.info("No scheduling decision available for this workload yet.")
            return

        st.markdown(
            f'<div class="gs-card-header" style="margin-bottom:12px;">'
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
        # currency (matches the React app's utils/workloadDisplay.formatCost) —
        # electricity_cost is always USD internally and must never be shown as "$"
        # for an INR/AUD/SEK region.
        native_cost, currency = dec.get("native_cost"), dec.get("currency")
        if native_cost is not None and currency:
            cost_display = f"{native_cost:.4f} {currency}"
        elif cost_usd is not None:
            cost_display = f"{cost_usd:.4f} USD"
        else:
            cost_display = NA

        ms1, ms2, ms3 = st.columns(3)
        with ms1:
            carbon_str = f"{carbon_intensity:.1f} gCO₂/kWh" if carbon_intensity is not None else NA
            avoided_str = f"{carbon_avoided:.4f} kg avoided" if carbon_avoided is not None else NA
            st.markdown(render_metric_card("Carbon Intensity", carbon_str, avoided_str, accent=True), unsafe_allow_html=True)
        with ms2:
            st.markdown(render_metric_card("Electricity Cost", cost_display, "Time-of-Day rate applied"), unsafe_allow_html=True)
        with ms3:
            runtime_min = job_data.get("runtime_minutes")
            duration_str = f"Duration: {runtime_min} min" if runtime_min is not None else NA
            st.markdown(render_metric_card("Scheduling Window", sel_start or NA, duration_str), unsafe_allow_html=True)

        baseline_carbon = dec.get("baseline_carbon_emission")
        carbon_bullet = (
            f"• Carbon intensity in this slot avoided <strong>{carbon_avoided:.4f} kg CO₂</strong> "
            f"({dec.get('carbon_reduction_pct'):.1f}% reduction) versus the immediate-execution baseline.<br>"
            if baseline_carbon is not None and baseline_carbon > 0
            and carbon_avoided is not None and dec.get("carbon_reduction_pct") is not None
            else ""
        )
        st.markdown("#### 💡 Why this slot was selected:")
        st.markdown(
            f'<div style="background:#041315;border:1px solid #0E383C;border-left:4px solid #00E599;padding:14px 18px;border-radius:8px;margin-bottom:20px;">'
            f'<div style="color:#FFFFFF;font-weight:600;margin-bottom:6px;">✓ Primary Objective: {reason}</div>'
            f'<div style="font-size:0.85rem;color:#94A3B8;">'
            f'{carbon_bullet}'
            f'• Hard deadline and cluster capacity constraints were satisfied at decision time '
            f'(a schedule is only ever stored for a workload that passed every hard constraint).</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # Decision Factors — same derivation as
        # app.dashboard.views.scheduling_engine (both views consume
        # app.dashboard.scheduling_explainability.compute_decision_factors
        # so they can never disagree); N/A when source data is unavailable,
        # never a fabricated 88/74/82/95.
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
        sla_hours = factors["sla_buffer_hours"]
        sla_str = f"{sla_hours:.1f}h before deadline" if sla_hours is not None else NA
        st.markdown(render_metric_card("SLA Margin / Buffer", sla_str, "Actual remaining time before the job's deadline"), unsafe_allow_html=True)

        # Candidate Slot Comparison Table — the scheduler's own recorded
        # candidate evaluations (candidates_json / rejected_candidates_json),
        # never a synthetic +/-1h/+/-2h sweep with a fabricated formula.
        st.markdown("#### 🔍 Candidate Slot Comparison")
        table_rows = format_candidate_table(dec)
        if not table_rows:
            st.info("No candidate data available for this decision.")
        else:
            st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

    # ── Baseline vs GreenShift Impact ──────────────────────────────────────────
    st.markdown("---")
    render_section_header("📈 Baseline vs GreenShift Impact", "Comparative fleet-wide and per-job analysis of carbon and cost savings delivered by DECIDE optimizer")

    fleet_impact = fetch_fleet_impact_api()
    if fleet_impact and fleet_impact.get("total_jobs_with_decisions", 0) > 0:
        tot_jobs = fleet_impact.get("total_jobs_with_decisions", 0)
        c_avoided = float(fleet_impact.get("total_carbon_avoided_kg", 0.0))
        c_pct = float(fleet_impact.get("avg_carbon_reduction_pct", 0.0))
        cost_usd = float(fleet_impact.get("total_cost_saved_usd", 0.0))
        # Currency-separated native savings (never a single cross-region sum —
        # the fleet can span multiple currencies). Rendered as "amount CODE"
        # pairs, the same "never fabricate a symbol" convention used in
        # app.notify.templates._format_cost.
        cost_by_currency = fleet_impact.get("cost_saved_by_currency") or {}
        native_currency_str = " · ".join(f"{amt:,.2f} {cur}" for cur, amt in cost_by_currency.items()) or "—"
        cost_pct = float(fleet_impact.get("avg_cost_reduction_pct", 0.0))
        sla_pct = float(fleet_impact.get("sla_compliance_pct", 100.0))
        pos_jobs = int(fleet_impact.get("jobs_with_positive_carbon_savings", 0))
        pos_pct = (pos_jobs / tot_jobs * 100.0) if tot_jobs else 0.0

        st.subheader("🌐 Fleet-Wide Optimization Impact")
        f1, f2, f3, f4 = st.columns(4)
        with f1:
            st.markdown(render_metric_card("Carbon Avoided", f"{c_avoided:,.1f} kg CO₂", f"-{c_pct:.1f}% mean reduction", accent=True), unsafe_allow_html=True)
        with f2:
            st.markdown(render_metric_card("Cost Saved", f"${cost_usd:,.2f} USD · {native_currency_str}", f"-{cost_pct:.1f}% mean savings"), unsafe_allow_html=True)
        with f3:
            st.markdown(render_metric_card("SLA Compliance", f"{sla_pct:.1f}%", f"{fleet_impact.get('sla_met_count', tot_jobs)} / {tot_jobs} met SLA"), unsafe_allow_html=True)
        with f4:
            st.markdown(render_metric_card("Positive Carbon Savings", f"{pos_jobs} / {tot_jobs}", f"{pos_pct:.1f}% of all workloads"), unsafe_allow_html=True)

        st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

        # Charts row: Regional Grouped Bar + Histogram
        c_row1, c_row2 = st.columns(2)

        with c_row1:
            by_reg = fleet_impact.get("by_region", {})
            if by_reg:
                reg_names = []
                b_c_vals = []
                gs_c_vals = []
                for r_name, r_data in by_reg.items():
                    c_av = float(r_data.get("total_carbon_avoided_kg", 0.0))
                    r_pct = float(r_data.get("avg_carbon_reduction_pct", 0.0))
                    # Baseline carbon isn't stored per-region — it is
                    # recovered exactly (not estimated) from the two real
                    # aggregate fields the backend does return:
                    # carbon_avoided = baseline - selected, and
                    # reduction_pct = carbon_avoided / baseline * 100, so
                    # baseline = carbon_avoided / (reduction_pct / 100).
                    # When reduction_pct is 0 (no carbon was ever avoided
                    # in this region) that division is undefined — the
                    # region is left out of this chart entirely rather
                    # than filled in with a fabricated multiplier.
                    if r_pct <= 0:
                        continue
                    base_est = c_av / (r_pct / 100.0)
                    gs_est = max(0.0, base_est - c_av)
                    reg_names.append(r_name)
                    b_c_vals.append(round(base_est, 1))
                    gs_c_vals.append(round(gs_est, 1))

                df_reg = pd.DataFrame({
                    "Region": reg_names * 2,
                    "Carbon (kg CO₂)": b_c_vals + gs_c_vals,
                    "Mode": ["Baseline (Immediate)"] * len(reg_names) + ["GreenShift (Optimal)"] * len(reg_names),
                })
                fig_reg = px.bar(
                    df_reg,
                    x="Region",
                    y="Carbon (kg CO₂)",
                    color="Mode",
                    barmode="group",
                    title="Regional Carbon: Baseline vs. GreenShift",
                    template="plotly_dark",
                    color_discrete_map={"Baseline (Immediate)": "#EF4444", "GreenShift (Optimal)": "#00E599"},
                )
                fig_reg.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#f0f6fc"), height=280, margin=dict(l=10, r=10, t=40, b=10))
                st.plotly_chart(fig_reg, use_container_width=True, config={"displayModeBar": False})

        with c_row2:
            dist_data = fleet_impact.get("carbon_reduction_distribution", [])
            if dist_data:
                fig_dist = px.histogram(
                    x=dist_data,
                    nbins=25,
                    title="Carbon Reduction % Distribution Across Fleet",
                    labels={"x": "Carbon Reduction (%)", "y": "Workload Count"},
                    template="plotly_dark",
                    color_discrete_sequence=["#00E599"],
                )
                fig_dist.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#f0f6fc"), height=280, margin=dict(l=10, r=10, t=40, b=10))
                st.plotly_chart(fig_dist, use_container_width=True, config={"displayModeBar": False})

        # Time-of-Day Shift
        tod_b = fleet_impact.get("baseline_hour_distribution", {})
        tod_gs = fleet_impact.get("greenshift_hour_distribution", {})
        if tod_b or tod_gs:
            hours = list(range(24))
            b_counts = [int(tod_b.get(str(h), tod_b.get(h, 0))) for h in hours]
            gs_counts = [int(tod_gs.get(str(h), tod_gs.get(h, 0))) for h in hours]
            df_tod = pd.DataFrame({
                "Hour (UTC)": [f"{h:02d}:00" for h in hours] * 2,
                "Workloads": b_counts + gs_counts,
                "Schedule Mode": ["Baseline (Arrival)"] * 24 + ["GreenShift (Optimized)"] * 24,
            })
            fig_tod = px.bar(
                df_tod,
                x="Hour (UTC)",
                y="Workloads",
                color="Schedule Mode",
                barmode="group",
                title="Time-of-Day Shift: Peak to Clean Hours Distribution",
                template="plotly_dark",
                color_discrete_map={"Baseline (Arrival)": "#F59E0B", "GreenShift (Optimized)": "#00E599"},
            )
            fig_tod.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#f0f6fc"), height=260, margin=dict(l=10, r=10, t=40, b=10))
            st.plotly_chart(fig_tod, use_container_width=True, config={"displayModeBar": False})

        st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

    st.subheader("🔍 Individual Workload Drilldown")
    all_jobs_for_impact = fetch_jobs(limit=200)
    impact_jobs = [j for j in all_jobs_for_impact if j.get("schedule_decision")]

    if not impact_jobs:
        st.info("No scheduling decisions available yet for impact comparison.")
    else:
        imp_sel = st.selectbox("Select Job for Impact Analysis", [j.get("job_id") for j in impact_jobs], key="impact_sel")
        if imp_sel:
            imp_job = fetch_job_detail(imp_sel)
            imp_dec = imp_job.get("schedule_decision") or {}
            imp_energy_kwh = imp_job.get("energy_kwh")

            # Every value below is a real ScheduleDecision field — no
            # fabricated fallback (former: 0.012/0.01/310.0/*1.3/*1.2).
            carbon_avoided_i = imp_dec.get("carbon_avoided")
            cost_diff_i = imp_dec.get("cost_difference")
            carbon_intensity_i = imp_dec.get("carbon_intensity")
            cost_i = imp_dec.get("electricity_cost")
            baseline_cost_i = imp_dec.get("baseline_cost")
            baseline_emission_i = imp_dec.get("baseline_carbon_emission")
            # Baseline carbon intensity isn't stored directly — only
            # baseline_carbon_emission (kg) is. Deriving intensity from it
            # is an exact unit conversion (kg = kWh * gCO2/kWh / 1000,
            # inverted), not an estimate, and only computed when both real
            # inputs exist.
            baseline_intensity_i = (
                (baseline_emission_i * 1000.0 / imp_energy_kwh)
                if baseline_emission_i is not None and imp_energy_kwh is not None and imp_energy_kwh > 0
                else None
            )

            im1, im2, im3, im4 = st.columns(4)
            with im1:
                st.markdown(render_metric_card("Carbon Avoided", f"{carbon_avoided_i:.4f} kg" if carbon_avoided_i is not None else NA, "vs immediate baseline", accent=True), unsafe_allow_html=True)
            with im2:
                st.markdown(render_metric_card("Cost Reduction", f"{cost_diff_i:.4f} USD" if cost_diff_i is not None else NA, "vs arrival scheduling"), unsafe_allow_html=True)
            with im3:
                st.markdown(render_metric_card("GreenShift Carbon Intensity", f"{carbon_intensity_i:.1f} gCO₂/kWh" if carbon_intensity_i is not None else NA, "Scheduled optimal window"), unsafe_allow_html=True)
            with im4:
                st.markdown(render_metric_card("Baseline Carbon Intensity", f"{baseline_intensity_i:.1f} gCO₂/kWh" if baseline_intensity_i is not None else NA, "Immediate arrival slot (derived: baseline emission ÷ energy)"), unsafe_allow_html=True)

            # Comparison bar charts — rendered only when both real values
            # needed for that comparison exist; otherwise an explicit
            # unavailable state, never a fabricated baseline.
            fig_col1, fig_col2 = st.columns(2)
            with fig_col1:
                if carbon_intensity_i is not None and baseline_intensity_i is not None:
                    fig_c = px.bar(
                        x=["Baseline (Immediate)", "GreenShift (Optimal)"],
                        y=[baseline_intensity_i, carbon_intensity_i],
                        labels={"x": "Scheduling Mode", "y": "gCO₂/kWh"},
                        title="Carbon Intensity Comparison",
                        template="plotly_dark",
                        color_discrete_sequence=["#EF4444", "#00E599"],
                    )
                    fig_c.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#f0f6fc"), height=280, margin=dict(l=10, r=10, t=40, b=10), showlegend=False)
                    st.plotly_chart(fig_c, use_container_width=True, config={"displayModeBar": False})
                else:
                    st.info("Carbon intensity comparison unavailable — missing baseline emission or energy data for this workload.")

            with fig_col2:
                if cost_i is not None and baseline_cost_i is not None:
                    fig_co = px.bar(
                        x=["Baseline (Immediate)", "GreenShift (Optimal)"],
                        y=[baseline_cost_i, cost_i],
                        labels={"x": "Scheduling Mode", "y": "Total Electricity Cost (USD)"},
                        title="Electricity Cost Comparison",
                        template="plotly_dark",
                        color_discrete_sequence=["#EF4444", "#00E599"],
                    )
                    fig_co.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#f0f6fc"), height=280, margin=dict(l=10, r=10, t=40, b=10), showlegend=False)
                    st.plotly_chart(fig_co, use_container_width=True, config={"displayModeBar": False})
                else:
                    st.info("Cost comparison unavailable — missing baseline cost data for this workload.")


# ─────────────────────────────────────────────────────────────────────────────
# Tab C — Live Monitoring
# ─────────────────────────────────────────────────────────────────────────────

def _render_monitoring_tab():
    render_section_header("🖥️ Job Monitoring & Kubernetes Dispatch", "Monitor active execution pods, lifecycle state transitions, and trigger authorized dispatches")

    # Quick Actions top bar
    st.markdown(
        '<div class="gs-card" style="margin-bottom:14px;">'
        '<div class="gs-card-title" style="margin-bottom:10px;">⚡ Quick Actions</div>',
        unsafe_allow_html=True,
    )
    qa1, qa2, qa3 = st.columns([1.5, 1.5, 1])
    with qa1:
        quick_job_id = st.text_input("Job ID for Quick Action", placeholder="e.g. JOB-ABC12345", key="quick_job_id", label_visibility="collapsed")
    with qa2:
        token = st.session_state.get("auth_token")
        if st.button("🚀 Schedule Selected Job", key="quick_schedule", use_container_width=True):
            if quick_job_id:
                try:
                    res = schedule_job_api(quick_job_id.strip(), token=token)
                    st.success(f"Job scheduled! Window: {res.get('selected_start', '')[:16]}")
                except Exception as exc:
                    st.error(f"Schedule failed: {exc}")
            else:
                st.warning("Enter a Job ID first.")
    with qa3:
        if st.button("☸️ Dispatch Selected Job", key="quick_dispatch", use_container_width=True):
            if quick_job_id:
                try:
                    res = dispatch_job_api(quick_job_id.strip(), token=token)
                    st.success(f"Dispatched! Pod: {res.get('pod_name', 'gs-pod')} | Status: {res.get('gs_status', 'QUEUED')}")
                except Exception as exc:
                    st.error(f"Dispatch failed: {exc}")
            else:
                st.warning("Enter a Job ID first.")
    st.markdown("</div>", unsafe_allow_html=True)

    jobs = fetch_jobs(limit=500)
    if not jobs:
        st.info("No active or historical workloads to monitor.")
        if st.button("➕ Submit your first workload", key="mon_cta", type="primary"):
            _nav_to_submit()
        return

    col_nav, col_main = st.columns([1, 2.2], gap="large")

    with col_nav:
        st.markdown("#### Filter Workloads")
        status_filter = st.selectbox(
            "Filter Lifecycle Status",
            ["ALL", "APPROVED", "QUEUED", "DISPATCHING", "RUNNING", "COMPLETED", "PENDING_APPROVAL", "DECLINED", "FAILED", "CANCELLED"],
            key="mon_status_filter",
        )
        filtered = [j for j in jobs if status_filter == "ALL" or j.get("status") == status_filter]
        st.caption(f"Found {len(filtered)} workloads")
        job_ids = [j.get("job_id") for j in filtered]
        selected_id = st.selectbox("Select Job to Inspect", job_ids, key="mon_sel") if job_ids else None

    with col_main:
        if not selected_id:
            st.info("Select a workload from the left panel to inspect execution status.")
            return

        job_info = fetch_job_detail(selected_id)
        current_status = job_info.get("status", "SUBMITTED")
        dec = job_info.get("schedule_decision") or {}

        st.markdown(
            f'<div class="gs-card-header" style="margin-bottom:12px;">'
            f'<div>'
            f'<div class="gs-card-title">{job_info.get("workload_name", selected_id)}</div>'
            f'<div class="gs-card-subtitle">Job ID: <code>{selected_id}</code> | Team: {job_info.get("team_id")} | Region: {job_info.get("region")}</div>'
            f'</div>'
            f'<div>{render_status_badge(current_status)}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        st.markdown("#### Lifecycle Progress")
        st.markdown(render_execution_timeline(current_status), unsafe_allow_html=True)

        mm1, mm2, mm3, mm4 = st.columns(4)
        with mm1:
            st.markdown(render_metric_card("Power", f"{job_info.get('power_kw', 1.0)} kW", "Demand"), unsafe_allow_html=True)
        with mm2:
            st.markdown(render_metric_card("Runtime", f"{job_info.get('runtime_minutes', 30)} min", "Duration"), unsafe_allow_html=True)
        with mm3:
            _mm_ci = dec.get("carbon_intensity")
            st.markdown(render_metric_card("Carbon", f"{_mm_ci:.1f}" if _mm_ci is not None else NA, "gCO₂/kWh", accent=True), unsafe_allow_html=True)
        with mm4:
            _native_cost, _currency = dec.get("native_cost"), dec.get("currency")
            _mm_cost = dec.get("electricity_cost")
            if _native_cost is not None and _currency:
                _cost_display = f"{_native_cost:.4f} {_currency}"
            elif _mm_cost is not None:
                _cost_display = f"{_mm_cost:.4f} USD"
            else:
                _cost_display = NA
            st.markdown(render_metric_card("Cost", _cost_display, "Estimated"), unsafe_allow_html=True)

        ms1, ms2 = st.columns(2)
        with ms1:
            st.markdown("#### ☸️ Container & Cluster Specs")
            st.markdown(f"- **Image:** `{job_info.get('container_image', 'greenshift/job:v1')}`")
            st.markdown(f"- **CPU / Memory:** `{job_info.get('cpu_request', '500m')} / {job_info.get('memory_request', '512Mi')}`")
            st.markdown(f"- **Target Region:** `{job_info.get('region', 'IN-TG')}`")
            st.markdown(f"- **Deadline:** `{job_info.get('deadline', 'N/A')}`")
        with ms2:
            st.markdown("#### ⏱️ Timing & SLA Compliance")
            st.markdown(f"- **Submitted At:** `{job_info.get('submitted_at') or NA}`")
            _ms_start = (dec.get("selected_start") or "")[:16]
            _ms_end = (dec.get("selected_end") or "")[:16]
            st.markdown(f"- **Scheduled Window:** `{_ms_start or NA} → {_ms_end or NA}`")
            _ms_ca = dec.get("carbon_avoided")
            st.markdown(f"- **Carbon Avoided:** `{f'{_ms_ca:.4f} kg' if _ms_ca is not None else NA}`")
            # sla_met is a real backend field (app.decide.impact_calculator
            # .calculate_impact) — never hardcoded to "MET" regardless of
            # the actual outcome.
            _sla_met = dec.get("sla_met")
            if _sla_met is True:
                _sla_str = "MET (Within Deadline)"
            elif _sla_met is False:
                _sla_str = "MISSED (Past Deadline)"
            else:
                _sla_str = NA
            st.markdown(f"- **SLA Status:** `{_sla_str}`")

        st.markdown("---")
        col_act1, col_act2 = st.columns([1.5, 1])
        with col_act1:
            if current_status == "APPROVED":
                st.markdown("✅ **Workload is Approved and ready for Kubernetes dispatch.**")
            elif current_status in ("QUEUED", "RUNNING"):
                st.markdown(f"ℹ️ Workload executing in Kubernetes. Current status: **{current_status}**.")
            elif current_status == "COMPLETED":
                st.markdown("✅ Workload execution has **COMPLETED** successfully.")
            elif current_status == "DISPATCHING":
                st.markdown("🚀 Workload is currently **DISPATCHING** to cluster...")
            elif current_status in ("SUBMITTED", "VALIDATED"):
                st.markdown(f"⚡ Workload is **{current_status}** and ready for Carbon-First scheduling.")
            elif current_status == "PENDING_APPROVAL":
                st.markdown("⚠️ Workload requires **Human Approval** before dispatch.")
            elif current_status == "DECLINED":
                st.markdown("🛑 Workload was **DECLINED**. Dispatch is strictly blocked.")
            elif current_status in ("CANCELLED", "FAILED"):
                st.markdown(f"{'⚠️' if current_status == 'CANCELLED' else '❌'} Workload **{current_status}**.")

        with col_act2:
            if current_status == "APPROVED":
                if st.button("🚀 Dispatch to Kubernetes", type="primary", use_container_width=True, key=f"mon_disp_{selected_id}"):
                    try:
                        with st.spinner("Dispatching to Kubernetes cluster..."):
                            disp_res = dispatch_job_api(selected_id, token=token)
                            p_name = disp_res.get("pod_name") or disp_res.get("kubernetes_job_name", "gs-pod")
                            st.success(f"Dispatched! Status: {disp_res.get('gs_status', 'QUEUED')} | Pod: {p_name}")
                            st.rerun()
                    except Exception as exc:
                        st.error(f"Dispatch Blocked / Failed: {exc}")
            elif current_status in ("SUBMITTED", "VALIDATED"):
                if st.button("🚀 Schedule Workload Now", type="primary", use_container_width=True, key=f"mon_sched_{selected_id}"):
                    try:
                        sched_res = schedule_job_api(selected_id, token=token)
                        st.success(f"Workload scheduled! Status: {sched_res.get('status', 'SCHEDULED')}")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Scheduling failed: {exc}")
            elif current_status == "PENDING_APPROVAL":
                curr_role = st.session_state.get("user_role", "COMPANY_USER")
                if curr_role in ("PLATFORM_ADMIN", "COMPANY_ADMIN"):
                    if st.button("✓ Approve Schedule", type="primary", use_container_width=True, key=f"mon_app_{selected_id}"):
                        try:
                            approve_job_api(selected_id, schedule_id=dec.get("id", 0), token=token)
                            st.success(f"Workload `{selected_id}` APPROVED!")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Approval failed: {exc}")
                else:
                    st.caption("Awaiting lead approval")
            elif current_status in ("QUEUED", "RUNNING", "DISPATCHING"):
                if st.button("⟳ Refresh Live Status", use_container_width=True, key=f"mon_refresh_{selected_id}"):
                    st.cache_data.clear()
                    st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# Tab D — Approval Queue
# ─────────────────────────────────────────────────────────────────────────────

def _render_approvals_tab():
    render_section_header("🛡️ Human Approval Gate", "Authorize or decline proposed scheduling windows with role-based governance")

    token = st.session_state.get("auth_token")
    pending_list = fetch_pending_approvals()
    declined_list = fetch_declined_approvals()

    a1, a2, a3, a4 = st.columns(4)
    with a1:
        st.markdown(render_metric_card("Pending Approvals", len(pending_list), "Awaiting team lead review", accent=True), unsafe_allow_html=True)
    with a2:
        st.markdown(render_metric_card("Declined Schedules", len(declined_list), "Blocked from dispatch"), unsafe_allow_html=True)
    with a3:
        st.markdown(render_metric_card("Approval Gate Policy", "STRICT", "Backend enforced"), unsafe_allow_html=True)
    with a4:
        st.markdown(render_metric_card("Operator Access", st.session_state.get("user_role", "COMPANY_USER"), "Active RBAC role", tag="ACTIVE"), unsafe_allow_html=True)

    tab_pending, tab_declined = st.tabs(["⏳ Pending Approvals", "🛑 Declined History"])

    with tab_pending:
        if not pending_list:
            st.info("No workloads currently awaiting human approval. All scheduled jobs are up to date.")
        else:
            for item in pending_list:
                job_id = item.get("job_id")
                schedule_id = item.get("schedule_id", 0)
                team_id = item.get("team_id", "N/A")
                region = item.get("region", "IN-TG")
                start_time = item.get("selected_start")
                runtime = item.get("runtime_minutes")
                carbon_intensity = item.get("carbon_intensity")
                carbon_emission = item.get("carbon_emission_kg")
                native_cost, item_currency = item.get("native_cost"), item.get("currency")
                cost_usd = item.get("electricity_cost_usd")
                if native_cost is not None and item_currency:
                    cost_display = f"{native_cost:.4f} {item_currency}"
                elif cost_usd is not None:
                    cost_display = f"{cost_usd:.4f} USD"
                else:
                    cost_display = NA
                # reason is optional on PendingApprovalItem — a missing
                # value is shown as N/A, never a fabricated generic
                # explanation that may not even match the applied policy
                # (e.g. a COST_FIRST decision falsely described as
                # "lowest carbon").
                reason = item.get("reason") or NA

                st.markdown(
                    f'<div class="gs-card" style="margin-bottom:12px;">'
                    f'<div class="gs-card-header">'
                    f'<div>'
                    f'<div class="gs-card-title">Job: <code>{job_id}</code></div>'
                    f'<div class="gs-card-subtitle">Team: <strong>{team_id}</strong> | Region: <strong>{region}</strong> | Runtime: <strong>{f"{runtime} min" if runtime is not None else NA}</strong></div>'
                    f'</div>'
                    f'<div>{render_status_badge("PENDING_APPROVAL")}</div>'
                    f'</div>'
                    f'<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:14px;font-size:0.85rem;">'
                    f'<div>Proposed Start: <strong style="color:#00E599;">{(str(start_time)[:16] + " UTC") if start_time else NA}</strong></div>'
                    f'<div>Carbon: <strong>{f"{carbon_intensity:.1f} gCO₂/kWh" if carbon_intensity is not None else NA}</strong></div>'
                    f'<div>Cost: <strong>{cost_display}</strong></div>'
                    f'<div>Emissions: <strong>{f"{carbon_emission:.4f} kg" if carbon_emission is not None else NA}</strong></div>'
                    f'</div>'
                    f'<div style="font-size:0.82rem;color:#94A3B8;background:#041315;padding:10px 14px;border-radius:6px;">'
                    f'<strong>Scheduler Reason:</strong> {reason}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

                col_app, col_dec_reason, col_dec_btn = st.columns([1, 2, 1])
                with col_app:
                    if st.button("✓ APPROVE", key=f"pend_app_{job_id}", type="primary", use_container_width=True):
                        try:
                            approve_job_api(job_id, schedule_id, reason="Approved by Team Lead", token=token)
                            st.success(f"Job `{job_id}` approved!")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Approval failed: {exc}")
                with col_dec_reason:
                    custom_decline_reason = st.text_input(
                        "Decline Reason",
                        value="Window conflicts with maintenance",
                        key=f"dec_reason_{job_id}",
                        label_visibility="collapsed",
                    )
                with col_dec_btn:
                    if st.button("✕ DECLINE", key=f"pend_dec_{job_id}", use_container_width=True):
                        try:
                            decline_job_api(job_id, schedule_id, reason=custom_decline_reason, token=token)
                            st.warning(f"Job `{job_id}` declined.")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Decline failed: {exc}")
                st.markdown('<div style="margin-bottom:20px;"></div>', unsafe_allow_html=True)

    with tab_declined:
        if not declined_list:
            st.info("No declined workloads in audit history.")
        else:
            table_rows = []
            for d in declined_list:
                table_rows.append({
                    "Job ID": d.get("job_id"),
                    "Team": d.get("team_id"),
                    "Declined At": (d.get("declined_at") or "")[:19].replace("T", " ") or NA,
                    "Declined By": d.get("declined_by") or NA,
                    "Decline Reason": d.get("reason") or NA,
                    "Status": "DECLINED",
                })
            st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)


# ─────────────────────────────────────────────────────────────────────────────
# Main Render Entry Point
# ─────────────────────────────────────────────────────────────────────────────

def render_workloads_view() -> None:
    """Render the consolidated Workloads page with 4 inner tabs."""
    tab_q, tab_s, tab_m, tab_a = st.tabs([
        "📋 Queue & List",
        "⚙️ Scheduling Decisions",
        "🖥️ Live Monitoring",
        "🛡️ Approval Queue",
    ])

    with tab_q:
        _render_queue_tab()

    with tab_s:
        _render_scheduling_tab()

    with tab_m:
        _render_monitoring_tab()

    with tab_a:
        _render_approvals_tab()
