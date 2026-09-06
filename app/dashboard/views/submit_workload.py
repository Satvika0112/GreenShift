"""
GreenShift — Submit Workload & Dynamic Scheduling Recommendation View.
"""

from datetime import datetime, timedelta, timezone
import uuid
import streamlit as st

from app.dashboard.api_client import submit_job_api, schedule_job_api
from app.dashboard.components import render_section_header, render_metric_card, render_decision_factor


def render_submit_workload_view() -> None:
    """Render multi-section workload submission form connected to DECIDE scheduler."""
    render_section_header("➕ Submit Workload", "Configure deferrable compute requirements for Carbon-First multi-region scheduling")

    now = datetime.now(timezone.utc)
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
            job_id = st.text_input("Job ID", value=default_job_id)
        with c_name:
            workload_name = st.text_input("Workload Name", value=f"Simulation-{job_id}")
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

        # Section 3: Execution Resource Requirements
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

        # Section 4: Scheduling Objective & Preferences
        st.markdown("#### 4. Scheduling Objective & Constraints")
        c_obj, c_defer = st.columns(2)
        with c_obj:
            st.selectbox("Optimization Policy", ["CARBON_FIRST (Lowest Emissions, Cost as Tie-Breaker)"])
        with c_defer:
            deferrable = st.checkbox("Deferrable Workload (Allow shift to optimal window)", value=True)

        submit_btn = st.form_submit_button("🚀 Submit & Optimize Schedule", type="primary", use_container_width=True)

    if submit_btn:
        earliest_start = now + timedelta(hours=earliest_start_hours)
        deadline = now + timedelta(hours=deadline_hours)

        payload = {
            "job_id": job_id,
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
                st.success(f"Workload `{job_id}` successfully registered!")

                # 2. Trigger Scheduler
                sched_res = schedule_job_api(job_id, record_audit=True, token=token)

                # 3. Display Recommended Window
                st.markdown("---")
                render_section_header("🎯 Recommended Execution Schedule", "DECIDE Carbon-First Optimization Result")

                dec_status = sched_res.get("status", "SCHEDULED")
                sel_start = sched_res.get("selected_start", "")[:16].replace("T", " ")
                sel_end = sched_res.get("selected_end", "")[:16].replace("T", " ")
                carbon_intensity = sched_res.get("carbon_intensity", 0.0)
                cost_usd = sched_res.get("electricity_cost", 0.0)
                carbon_avoided = sched_res.get("carbon_avoided", 0.0)
                reason = sched_res.get("reason", "Lowest carbon intensity window found")

                st.markdown(
                    f'<div class="gs-card-header" style="margin-bottom: 12px;">'
                    f'<div>'
                    f'<div class="gs-card-title">Optimal Time Window: <span style="color: #00E599; margin-left: 6px;">{sel_start} → {sel_end} UTC</span></div>'
                    f'<div class="gs-card-subtitle">Region: {region} | Status: {dec_status}</div>'
                    f'</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

                mc1, mc2, mc3 = st.columns(3)
                with mc1:
                    st.markdown(render_metric_card("Carbon Intensity", f"{carbon_intensity:.1f} gCO₂/kWh", "Grid forecast", accent=True), unsafe_allow_html=True)
                with mc2:
                    st.markdown(render_metric_card("Electricity Cost", f"${cost_usd:.4f}", "Time-of-Day tariff"), unsafe_allow_html=True)
                with mc3:
                    st.markdown(render_metric_card("Carbon Avoided", f"{carbon_avoided:.4f} kg", "Saved vs immediate baseline", accent=True), unsafe_allow_html=True)

                st.markdown(
                    f'<div style="margin-top: 16px; padding: 12px 16px; background: #041315; border-radius: 8px; border-left: 3px solid #00E599;">'
                    f'<span style="font-weight: 700; color: #FFFFFF;">Why this slot? </span>'
                    f'<span style="color: #94A3B8;">{reason}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

                if dec_status == "PENDING_APPROVAL":
                    st.info("ℹ️ This workload requires Human Approval before it can be dispatched to Kubernetes. Visit the Approvals tab to approve.")

            except Exception as exc:
                st.error(f"Error submitting or scheduling workload: {exc}")
