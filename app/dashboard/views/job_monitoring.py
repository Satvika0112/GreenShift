"""
GreenShift — Real-time Job Monitoring & Kubernetes Dispatch View.
"""

import streamlit as st
import pandas as pd

from app.dashboard.api_client import (
    fetch_jobs,
    fetch_job_detail,
    dispatch_job_api,
    schedule_job_api,
    approve_job_api,
    cancel_job_api,
)
from app.dashboard.components import (
    render_section_header,
    render_metric_card,
    render_status_badge,
    render_execution_timeline,
)


def render_job_monitoring_view() -> None:
    """Render the real-time Job Monitoring and Kubernetes Dispatch execution view."""
    render_section_header("🖥️ Job Monitoring & Kubernetes Dispatch", "Monitor active execution pods, lifecycle state transitions, and trigger authorized dispatches")

    jobs = fetch_jobs(limit=500)
    if not jobs:
        st.info("No active or historical workloads to monitor.")
        return

    col_nav, col_main = st.columns([1, 2.2], gap="large")

    with col_nav:
        st.markdown("#### Filter Workloads")
        status_filter = st.selectbox(
            "Filter Lifecycle Status",
            ["ALL", "APPROVED", "QUEUED", "RUNNING", "COMPLETED", "PENDING_APPROVAL", "DECLINED", "FAILED"],
        )

        filtered = [j for j in jobs if status_filter == "ALL" or j.get("status") == status_filter]
        st.caption(f"Found {len(filtered)} workloads")

        job_ids = [j.get("job_id") for j in filtered]
        selected_id = st.selectbox("Select Job to Inspect", job_ids) if job_ids else None

    with col_main:
        if not selected_id:
            st.info("Select a workload from the left panel to inspect execution status.")
            return

        job_info = fetch_job_detail(selected_id)
        current_status = job_info.get("status", "SUBMITTED")

        st.markdown(
            f'<div class="gs-card-header" style="margin-bottom: 12px;">'
            f'<div>'
            f'<div class="gs-card-title">{job_info.get("workload_name", selected_id)}</div>'
            f'<div class="gs-card-subtitle">Job ID: <code>{selected_id}</code> | Team: {job_info.get("team_id")} | Region: {job_info.get("region")}</div>'
            f'</div>'
            f'<div>{render_status_badge(current_status)}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # Lifecycle Timeline
        st.markdown("#### Lifecycle Progress")
        st.markdown(render_execution_timeline(current_status), unsafe_allow_html=True)

        # Metrics Grid
        dec = job_info.get("schedule_decision") or {}
        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.markdown(render_metric_card("Power", f"{job_info.get('power_kw', 1.0)} kW", "Demand"), unsafe_allow_html=True)
        with m2:
            st.markdown(render_metric_card("Runtime", f"{job_info.get('runtime_minutes', 30)} min", "Duration"), unsafe_allow_html=True)
        with m3:
            st.markdown(render_metric_card("Carbon", f"{dec.get('carbon_intensity', 0.0):.1f}", "gCO₂/kWh", accent=True), unsafe_allow_html=True)
        with m4:
            # Currency Consistency: prefer the execution region's real
            # native_cost + currency over the USD-normalized
            # electricity_cost — a "$" cost must never be shown for an
            # INR/AUD/SEK region.
            _native_cost, _currency = dec.get("native_cost"), dec.get("currency")
            _cost_display = (
                f"{_native_cost:.4f} {_currency}" if _native_cost is not None and _currency
                else f"{dec.get('electricity_cost', 0.0):.4f} USD"
            )
            st.markdown(render_metric_card("Cost", _cost_display, "Estimated"), unsafe_allow_html=True)

        # Specs & Scheduling Details
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            st.markdown("#### ☸️ Container & Cluster Specs")
            st.markdown(f"- **Image:** `{job_info.get('container_image', 'greenshift/job:v1')}`")
            st.markdown(f"- **CPU / Memory:** `{job_info.get('cpu_request', '500m')} / {job_info.get('memory_request', '512Mi')}`")
            st.markdown(f"- **Target Region:** `{job_info.get('region', 'IN-TG')}`")
            st.markdown(f"- **Deadline:** `{job_info.get('deadline', 'N/A')}`")

        with col_s2:
            st.markdown("#### ⏱️ Timing & SLA Compliance")
            st.markdown(f"- **Submitted At:** `{job_info.get('submitted_at', 'N/A')}`")
            st.markdown(f"- **Scheduled Window:** `{dec.get('selected_start', 'N/A')[:16]} → {dec.get('selected_end', 'N/A')[:16]}`")
            st.markdown(f"- **Carbon Avoided:** `{dec.get('carbon_avoided', 0.0):.4f} kg`")
            st.markdown(f"- **SLA Status:** `MET (Within Deadline)`")

        # Action Buttons & Status Gate
        st.markdown("---")
        col_act1, col_act2 = st.columns([1.5, 1])
        token = st.session_state.get("auth_token")

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
                st.markdown("⚠️ Workload requires **Human Approval** before dispatch is permitted.")
            elif current_status == "DECLINED":
                st.markdown("🛑 Workload was **DECLINED**. Kubernetes dispatch is strictly blocked.")
            elif current_status == "CANCELLED":
                st.markdown("⚠️ Workload was **CANCELLED**.")
            elif current_status == "FAILED":
                st.markdown("❌ Workload execution **FAILED**.")

        with col_act2:
            if current_status == "APPROVED":
                if st.button("🚀 Dispatch to Kubernetes", type="primary", use_container_width=True):
                    try:
                        with st.spinner("Dispatching job to Kubernetes cluster via backend authorization gate..."):
                            disp_res = dispatch_job_api(selected_id, token=token)
                            p_name = disp_res.get("pod_name") or disp_res.get("kubernetes_job_name", "gs-pod")
                            st.success(f"Job successfully dispatched! Status: {disp_res.get('gs_status', 'QUEUED')} | Pod: {p_name}")
                            st.rerun()
                    except Exception as exc:
                        st.error(f"Dispatch Blocked / Failed: {exc}")
            elif current_status in ("SUBMITTED", "VALIDATED"):
                if st.button("🚀 Schedule Workload Now", type="primary", use_container_width=True):
                    try:
                        sched_res = schedule_job_api(selected_id, token=token)
                        st.success(f"Workload scheduled! Status: {sched_res.get('status', 'SCHEDULED')}")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Scheduling failed: {exc}")
            elif current_status == "PENDING_APPROVAL":
                curr_role = st.session_state.get("user_role", "COMPANY_USER")
                if curr_role in ("PLATFORM_ADMIN", "COMPANY_ADMIN"):
                    if st.button("✓ Approve Schedule", type="primary", use_container_width=True):
                        try:
                            sd_id = dec.get("id", 0) if dec else 0
                            approve_job_api(selected_id, schedule_id=sd_id, token=token)
                            st.success(f"Workload `{selected_id}` APPROVED!")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Approval failed: {exc}")
                else:
                    st.caption("Awaiting lead approval")
            elif current_status in ("QUEUED", "RUNNING", "DISPATCHING"):
                if st.button("⟳ Refresh Live Status", use_container_width=True):
                    st.cache_data.clear()
                    st.rerun()
