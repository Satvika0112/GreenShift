"""
GreenShift — Workload Management View.
"""

import pandas as pd
import streamlit as st

from app.dashboard.api_client import fetch_jobs, fetch_job_detail
from app.dashboard.components import render_metric_card, render_section_header, render_status_badge, render_execution_timeline


def render_workloads_view() -> None:
    """Render the Workload Management table and detail inspection view."""
    render_section_header("📋 Workload Management", "Track, filter, and inspect enterprise compute jobs across all regions")

    jobs = fetch_jobs(limit=1000)

    # Top Filters
    f1, f2, f3, f4 = st.columns(4)
    with f1:
        search_query = st.text_input("🔍 Search Workloads", placeholder="Search by Job ID or name...")
    with f2:
        status_options = ["ALL", "SUBMITTED", "PENDING_APPROVAL", "APPROVED", "SCHEDULED", "QUEUED", "RUNNING", "COMPLETED", "DECLINED", "FAILED"]
        selected_status = st.selectbox("Status Filter", status_options, index=0)
    with f3:
        region_options = ["ALL", "IN-TG", "IN-GJ", "IN-HP", "IN-WB", "US-CA", "US-TX", "US-NY", "SE", "AU-SA-Large", "AU-SA-Small"]
        selected_region = st.selectbox("Region Filter", region_options, index=0)
    with f4:
        priority_options = ["ALL", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
        selected_priority = st.selectbox("Priority Filter", priority_options, index=0)

    # Filter data
    filtered_jobs = []
    for j in jobs:
        # Search
        if search_query:
            q = search_query.lower()
            if q not in j.get("job_id", "").lower() and q not in j.get("workload_name", "").lower():
                continue
        # Status
        if selected_status != "ALL" and j.get("status") != selected_status:
            continue
        # Region
        if selected_region != "ALL" and j.get("region") != selected_region:
            continue
        # Priority
        if selected_priority != "ALL" and j.get("priority", "MEDIUM").upper() != selected_priority:
            continue

        filtered_jobs.append(j)

    st.markdown(f"**Showing {len(filtered_jobs)} of {len(jobs)} workloads**")

    # Table View
    if filtered_jobs:
        table_data = []
        for j in filtered_jobs:
            table_data.append({
                "Job ID": j.get("job_id"),
                "Workload Name": j.get("workload_name") or f"Job-{j.get('job_id')}",
                "Job Type": j.get("job_type", "Batch"),
                "Team": j.get("team_id", "analytics"),
                "Region": j.get("region", "IN-TG"),
                "Priority": j.get("priority", "MEDIUM"),
                "Runtime": f"{j.get('runtime_minutes', 30)} min",
                "Power (kW)": j.get("power_kw", 1.0),
                "Status": j.get("status", "SUBMITTED"),
                "Deadline": (j.get("deadline") or "")[:16].replace("T", " "),
            })

        df = pd.DataFrame(table_data)
        st.dataframe(df, use_container_width=True, hide_index=True)

        # Workload Inspector Drawer
        st.markdown("---")
        render_section_header("🔍 Workload Detail Inspector", "Inspect scheduling decision, timeline, and resource specs for a job")

        inspect_job_id = st.selectbox("Select Workload to Inspect", [j.get("job_id") for j in filtered_jobs])
        if inspect_job_id:
            job_detail = fetch_job_detail(inspect_job_id)
            if job_detail:
                st.markdown(
                    f"""
                    <div class="gs-card">
                        <div class="gs-card-header">
                            <div>
                                <div class="gs-card-title">{job_detail.get('workload_name', inspect_job_id)}</div>
                                <div class="gs-card-subtitle">ID: <code>{inspect_job_id}</code> | Team: {job_detail.get('team_id')} | Region: {job_detail.get('region')}</div>
                            </div>
                            <div>{render_status_badge(job_detail.get('status', ''))}</div>
                        </div>
                    """,
                    unsafe_allow_html=True,
                )

                # Lifecycle Timeline
                st.markdown(render_execution_timeline(job_detail.get("status", "")), unsafe_allow_html=True)

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
                    dec = job_detail.get("schedule_decision")
                    st.markdown("#### 🌿 Scheduling Decision")
                    if dec:
                        st.markdown(f"- **Selected Window:** `{dec.get('selected_start', '')[:16]} → {dec.get('selected_end', '')[:16]}`")
                        st.markdown(f"- **Carbon Intensity:** `{dec.get('carbon_intensity', 0.0)} gCO₂/kWh`")
                        st.markdown(f"- **Electricity Cost:** `${dec.get('electricity_cost', 0.0):.4f}`")
                        st.markdown(f"- **Carbon Avoided:** `{dec.get('carbon_avoided', 0.0):.4f} kg`")
                        st.markdown(f"- **Optimization Reason:** *{dec.get('reason', 'N/A')}*")
                    else:
                        st.caption("No scheduling decision generated yet.")

                st.markdown("</div>", unsafe_allow_html=True)
    else:
        st.info("No workloads found matching the current search & filter criteria.")
