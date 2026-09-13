"""
GreenShift — Page 3: Submit Workload.

Fix: Job ID and Workload Name are read-only (auto-generated).
All 4 form sections preserved. All API calls preserved.
"""

from datetime import datetime, timedelta, timezone
import uuid
import streamlit as st

from app.dashboard.api_client import submit_job_api, schedule_job_api, approve_job_api
from app.dashboard.components import render_section_header, render_metric_card, render_decision_factor


def render_submit_workload_view() -> None:
    """Render multi-section workload submission form connected to DECIDE scheduler."""
    render_section_header("➕ Submit Workload", "Configure deferrable compute requirements for Carbon-First multi-region scheduling")

    now = datetime.now(timezone.utc)
    # Auto-generate IDs (read-only — shown after submission or as disabled fields)
    default_job_id = f"JOB-{uuid.uuid4().hex[:8].upper()}"

    with st.form("workload_submission_form"):
        # Section 1: Organization & Identity
        st.markdown("#### 1. Tenant & Organization Details")
        c_team, c_type, c_prio = st.columns(3)
        with c_team:
            team_id = st.selectbox("Team / Organization", ["analytics", "ai_research", "batch_ops", "team_alpha", "team_beta"])
        with c_type:
            job_type = st.selectbox("Job Workload Type", ["Batch Simulation", "Model Training", "Data Processing", "Rendering", "CI/CD Pipeline"])
        with c_prio:
            priority = st.selectbox("Workload Priority", ["MEDIUM", "LOW", "HIGH", "CRITICAL"])

        st.markdown("---")

        # Section 2: Workload Specifications
        st.markdown("#### 2. Workload Specifications")

        c_id, c_name, c_reg = st.columns(3)
        with c_id:
            st.text_input(
                "Job ID",
                value=default_job_id,
                disabled=True,
                help="Auto-generated on submission",
            )
            st.caption("Auto-generated on submission")
        with c_name:
            st.text_input(
                "Workload Name",
                value=f"Simulation-{default_job_id}",
                disabled=True,
                help="Auto-generated on submission",
            )
            st.caption("Auto-generated on submission")
        with c_reg:
            region = st.selectbox(
                "Target Region",
                ["IN-TG", "IN-GJ", "IN-HP", "IN-WB", "US-CA", "US-TX", "US-NY", "SE", "AU-SA-Large", "AU-SA-Small"],
            )

        c_time1, c_time2, c_run = st.columns(3)
        with c_time1:
            earliest_start_hours = st.number_input("Earliest Start Delay (hours from now)", min_value=0, max_value=48, value=0)
        with c_time2:
            deadline_hours = st.number_input("Deadline Window (hours from now)", min_value=1, max_value=72, value=12)
        with c_run:
            runtime_minutes = st.number_input("Estimated Runtime (minutes)", min_value=5, max_value=1440, value=30)

        st.markdown("---")

        # Section 3: Kubernetes Resource Requirements
        st.markdown("#### 3. Kubernetes Resource Requirements")
        c_pwr, c_cpu, c_mem, c_img = st.columns(4)
        with c_pwr:
            power_kw = st.number_input("Power Demand (kW)", min_value=0.1, max_value=500.0, value=2.5, step=0.5)
        with c_cpu:
            cpu_request = st.text_input("CPU Request", value="500m")
        with c_mem:
            memory_request = st.text_input("Memory Request", value="512Mi")
        with c_img:
            container_image = st.text_input("Container Image", value="greenshift/simulation:v1")

        st.markdown("---")

        # Section 4: Scheduling Objective & Constraints
        st.markdown("#### 4. Scheduling Objective & Constraints")
        c_obj, c_defer = st.columns(2)
        with c_obj:
            st.selectbox("Optimization Policy", ["CARBON_FIRST (Lowest Emissions, Cost as Tie-Breaker)"])
        with c_defer:
            deferrable = st.checkbox("Deferrable Workload (Allow shift to optimal window)", value=True)

        submit_btn = st.form_submit_button(
            "🚀 Submit & Optimize Schedule",
            type="primary",
            use_container_width=True,
        )

    if submit_btn:
        earliest_start = now + timedelta(hours=earliest_start_hours)
        deadline = now + timedelta(hours=deadline_hours)
        workload_name = f"Simulation-{default_job_id}"

        payload = {
            "job_id": default_job_id,
            "workload_name": workload_name,
            "job_type": job_type,
            "team_id": team_id,
            "region": region,
            "priority": priority,
            "runtime_minutes": int(runtime_minutes),
            "power_kw": float(power_kw),
            "cpu_request": cpu_request,
            "memory_request": memory_request,
            "container_image": container_image,
            "earliest_start_time": earliest_start.isoformat(),
            "deadline": deadline.isoformat(),
            "deferrable": deferrable,
        }

        with st.spinner("Submitting workload to Ingest layer and computing Carbon-First schedule..."):
            token = st.session_state.get("auth_token")
            try:
                # 1. Ingest Job
                job_res = submit_job_api(payload, token=token)
                # 2. Trigger Scheduler
                sched_res = schedule_job_api(default_job_id, record_audit=True, token=token)
                st.session_state["recent_submission"] = {
                    "job_id": default_job_id,
                    "workload_name": workload_name,
                    "region": region,
                    "sched_res": sched_res,
                    "status": sched_res.get("status", "SCHEDULED"),
                }
                st.rerun()
            except Exception as exc:
                st.error(f"Error submitting or scheduling workload: {exc}")

    # Display most recent submission results & immediate action gate
    if "recent_submission" in st.session_state:
        sub = st.session_state["recent_submission"]
        sub_job_id = sub["job_id"]
        sub_name = sub["workload_name"]
        sub_region = sub["region"]
        sched_res = sub["sched_res"]

        st.markdown("---")
        st.success(f"✅ Workload `{sub_job_id}` successfully registered and optimized!")
        st.info(f"**Job ID:** `{sub_job_id}` | **Name:** `{sub_name}` | **Region:** `{sub_region}`")

        render_section_header("🎯 Recommended Execution Schedule", "DECIDE Carbon-First Optimization Result")

        dec_status = sub.get("status", sched_res.get("status", "SCHEDULED"))
        sel_start = sched_res.get("selected_start", "")[:16].replace("T", " ")
        sel_end = sched_res.get("selected_end", "")[:16].replace("T", " ")
        carbon_intensity = sched_res.get("carbon_intensity", 0.0)
        cost_usd = sched_res.get("electricity_cost", 0.0)
        carbon_avoided = sched_res.get("carbon_avoided", 0.0)
        reason = sched_res.get("reason", "Lowest carbon intensity window found")

        st.markdown(
            f'<div class="gs-card-header" style="margin-bottom:12px;">'
            f'<div>'
            f'<div class="gs-card-title">Optimal Time Window: <span style="color:#00E599;margin-left:6px;">{sel_start} → {sel_end} UTC</span></div>'
            f'<div class="gs-card-subtitle">Region: {sub_region} | Status: <strong>{dec_status}</strong></div>'
            f'</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        mc1, mc2, mc3 = st.columns(3)
        with mc1:
            st.markdown(render_metric_card("Carbon Intensity", f"{carbon_intensity:.1f} gCO₂/kWh", "Grid forecast", accent=True), unsafe_allow_html=True)
        with mc2:
            # Currency Consistency: prefer the execution region's real
            # native_cost + currency over the USD-normalized
            # electricity_cost — a "$" cost must never be shown for an
            # INR/AUD/SEK region.
            _native_cost, _currency = sched_res.get("native_cost"), sched_res.get("currency")
            _cost_display = (
                f"{_native_cost:.4f} {_currency}" if _native_cost is not None and _currency
                else f"{cost_usd:.4f} USD"
            )
            st.markdown(render_metric_card("Electricity Cost", _cost_display, "Time-of-Day tariff"), unsafe_allow_html=True)
        with mc3:
            st.markdown(render_metric_card("Carbon Avoided", f"{carbon_avoided:.4f} kg", "Saved vs immediate baseline", accent=True), unsafe_allow_html=True)

        st.markdown(
            f'<div style="margin-top:16px;padding:12px 16px;background:#041315;border-radius:8px;border-left:3px solid #00E599;">'
            f'<span style="font-weight:700;color:#FFFFFF;">Why this slot? </span>'
            f'<span style="color:#94A3B8;">{reason}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

        token = st.session_state.get("auth_token")
        curr_role = st.session_state.get("user_role", "COMPANY_USER")

        st.markdown("---")
        if dec_status in ("APPROVED", "QUEUED", "RUNNING", "COMPLETED"):
            st.success(f"Workload status is currently **{dec_status}**.")
            ca1, ca2 = st.columns(2)
            with ca1:
                if st.button("📋 View in Workloads Monitor", key="view_in_workloads", type="primary"):
                    st.session_state["current_page"] = "📋 Workloads"
                    st.rerun()
            with ca2:
                if st.button("➕ Submit Another Workload", key="clear_sub"):
                    del st.session_state["recent_submission"]
                    st.rerun()
        elif curr_role in ("PLATFORM_ADMIN", "COMPANY_ADMIN"):
            # NOTE: Approval and dispatch are deliberately two separate, independently
            # reviewed steps — never combine them into one "Approve & Dispatch" action.
            # Dispatch only becomes available once the job shows APPROVED above, via
            # the Workloads Monitor / automated dispatcher.
            st.markdown("#### ⚡ Human Approval Gate")
            c_imm1, c_imm3 = st.columns([1.5, 1])
            with c_imm1:
                if st.button("✓ Approve Schedule Now", key=f"imm_app_{sub_job_id}", type="primary"):
                    try:
                        approve_job_api(sub_job_id, schedule_id=sched_res.get("id", 0), token=token)
                        st.session_state["recent_submission"]["status"] = "APPROVED"
                        st.success(f"Workload `{sub_job_id}` APPROVED! It will dispatch automatically at its scheduled window, or can be dispatched from the Workloads Monitor.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Approval failed: {exc}")
            with c_imm3:
                if st.button("✕ Dismiss", key="dismiss_sub"):
                    del st.session_state["recent_submission"]
                    st.rerun()
        else:
            st.info("ℹ️ This workload is awaiting Human Approval by a Company Admin or Platform Admin before dispatch.")

