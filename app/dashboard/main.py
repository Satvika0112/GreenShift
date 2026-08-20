"""
Agent 5 — PRESENT
GreenShift Streamlit Dashboard — Main Entry Point.

Displays:
  - Live job status (submitted, scheduled, running, completed, failed)
  - Kubernetes execution details
  - Carbon emissions comparison (GreenShift vs baseline)
  - Cost comparison
  - Team budget utilisation
  - Audit chain status
  - CSV export
"""

import os
import time
import json
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import httpx

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

API_URL = os.environ.get("GREENSHIFT_API_URL", "http://localhost:8000")
REFRESH_INTERVAL = 30  # seconds

st.set_page_config(
    page_title="GreenShift Dashboard",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# Styling
# ─────────────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
    /* Import Google Font */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&display=swap');

    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

    .main { background-color: #0e1117; }

    .metric-card {
        background: linear-gradient(135deg, #1a2332 0%, #0e1117 100%);
        border: 1px solid #2d3748;
        border-radius: 12px;
        padding: 20px;
        text-align: center;
    }

    .green-badge {
        background: linear-gradient(90deg, #00c851, #007f33);
        color: white;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.85em;
        font-weight: 600;
    }

    .red-badge {
        background: linear-gradient(90deg, #ff4444, #cc0000);
        color: white;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.85em;
        font-weight: 600;
    }

    .status-chip {
        display: inline-block;
        padding: 3px 10px;
        border-radius: 12px;
        font-size: 0.78em;
        font-weight: 600;
    }

    h1, h2, h3 { color: #e2e8f0; }
    .stMetric label { color: #a0aec0 !important; }
    .stMetric .metric-value { color: #e2e8f0 !important; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# API helpers
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=REFRESH_INTERVAL)
def fetch_jobs(status_filter: Optional[str] = None) -> list:
    try:
        params = {}
        if status_filter:
            params["status"] = status_filter
        r = httpx.get(f"{API_URL}/api/v1/jobs", params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.warning(f"Could not reach API: {exc}")
        return []


@st.cache_data(ttl=REFRESH_INTERVAL)
def fetch_job_detail(job_id: str) -> dict:
    try:
        r = httpx.get(f"{API_URL}/api/v1/jobs/{job_id}", timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}


@st.cache_data(ttl=REFRESH_INTERVAL)
def fetch_audit_verify() -> dict:
    try:
        r = httpx.get(f"{API_URL}/api/v1/trust/verify", timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {"valid": False, "message": "API unreachable"}


@st.cache_data(ttl=REFRESH_INTERVAL)
def fetch_carbon_curve(region: str) -> list:
    try:
        r = httpx.get(f"{API_URL}/api/v1/carbon", params={"region": region}, timeout=10)
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Header
# ─────────────────────────────────────────────────────────────────────────────

col_logo, col_title, col_refresh = st.columns([1, 8, 1])
with col_logo:
    st.markdown("# 🌿")
with col_title:
    st.markdown("## GreenShift — Carbon-Aware Kubernetes Scheduling")
    st.markdown("*Real-time carbon and cost savings from intelligent compute scheduling*")
with col_refresh:
    if st.button("⟳ Refresh"):
        st.cache_data.clear()
        st.rerun()

st.divider()

# ─────────────────────────────────────────────────────────────────────────────
# Sidebar — Job submission
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## ➕ Submit Job")
    with st.form("submit_job_form"):
        team_id = st.text_input("Team ID", value="AI-TEAM")
        region = st.selectbox("Grid Region", ["IN-WE", "IN-SO", "IN-EA", "IN-NO", "DE", "US-CAL-CISO"])
        deadline_offset = st.slider("Deadline (hours from now)", 2, 72, 24)
        runtime_minutes = st.slider("Runtime (minutes)", 5, 480, 30)
        power_kw = st.number_input("Power draw (kW)", min_value=0.1, max_value=100.0, value=0.5, step=0.1)
        container_image = st.text_input("Container image", value="greenshift/sample-workload:latest")
        carbon_budget = st.number_input("Carbon budget (kg CO2, 0=none)", min_value=0.0, value=0.1, step=0.01)
        cpu_request = st.text_input("CPU request", value="500m")
        memory_request = st.text_input("Memory request", value="512Mi")
        submitted = st.form_submit_button("🚀 Submit Job")

    if submitted:
        deadline = (datetime.now(timezone.utc) + timedelta(hours=deadline_offset)).isoformat()
        payload = {
            "team_id": team_id,
            "deadline": deadline,
            "runtime_minutes": runtime_minutes,
            "power_kw": power_kw,
            "region": region,
            "container_image": container_image,
            "cpu_request": cpu_request,
            "memory_request": memory_request,
            "carbon_budget_kg": carbon_budget if carbon_budget > 0 else None,
        }
        try:
            r = httpx.post(f"{API_URL}/api/v1/jobs", json=payload, timeout=10)
            r.raise_for_status()
            result = r.json()
            st.success(f"✅ Job submitted: **{result['job_id']}**")
            st.cache_data.clear()
        except Exception as exc:
            st.error(f"❌ Submission failed: {exc}")

    st.divider()
    st.markdown("## 🔍 Schedule Job")
    manual_job_id = st.text_input("Job ID to schedule")
    if st.button("Schedule now"):
        try:
            r = httpx.post(f"{API_URL}/api/v1/schedule/{manual_job_id}", timeout=30)
            r.raise_for_status()
            st.success("Scheduling triggered!")
            st.cache_data.clear()
        except Exception as exc:
            st.error(f"Error: {exc}")

    st.divider()
    st.markdown("## ⚡ Dispatch Job")
    dispatch_job_id = st.text_input("Job ID to dispatch")
    if st.button("Dispatch to Kubernetes"):
        try:
            r = httpx.post(f"{API_URL}/api/v1/dispatch/{dispatch_job_id}", timeout=30)
            r.raise_for_status()
            st.success("Dispatched to Kubernetes!")
            st.cache_data.clear()
        except Exception as exc:
            st.error(f"Error: {exc}")

# ─────────────────────────────────────────────────────────────────────────────
# Main content — tabs
# ─────────────────────────────────────────────────────────────────────────────

tab_overview, tab_jobs, tab_carbon, tab_kubernetes, tab_trust, tab_export = st.tabs([
    "📊 Overview", "📋 Jobs", "🌿 Carbon", "☸️ Kubernetes", "🔐 Audit", "📥 Export"
])

# ── TAB 1: Overview ──────────────────────────────────────────────────────────
with tab_overview:
    all_jobs = fetch_jobs()
    audit_result = fetch_audit_verify()

    # Status counts
    status_counts = {"SUBMITTED": 0, "SCHEDULED": 0, "QUEUED": 0, "RUNNING": 0, "COMPLETED": 0, "FAILED": 0}
    total_carbon_avoided = 0.0
    total_cost_saved = 0.0

    for j in all_jobs:
        s = j.get("status", "SUBMITTED")
        if s in status_counts:
            status_counts[s] += 1

    # Metrics row
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("📬 Submitted",  status_counts["SUBMITTED"])
    m2.metric("📅 Scheduled",  status_counts["SCHEDULED"])
    m3.metric("⏳ Queued",     status_counts["QUEUED"])
    m4.metric("🏃 Running",    status_counts["RUNNING"])
    m5.metric("✅ Completed",  status_counts["COMPLETED"])
    m6.metric("❌ Failed",     status_counts["FAILED"])

    st.divider()

    # Carbon + Cost savings (from scheduled jobs detail)
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("### 🌿 Carbon Avoided")
        st.markdown(f"#### `{total_carbon_avoided:.3f} kg CO₂`")
        st.caption("Across all scheduled jobs vs baseline")
    with c2:
        st.markdown("### 💰 Cost Saved")
        st.markdown(f"#### `${total_cost_saved:.4f}`")
        st.caption("GreenShift vs earliest-start baseline")
    with c3:
        st.markdown("### 🔐 Audit Chain")
        if audit_result.get("valid"):
            st.markdown('<span class="green-badge">✓ VALID</span>', unsafe_allow_html=True)
        else:
            st.markdown('<span class="red-badge">✗ BROKEN</span>', unsafe_allow_html=True)
        st.caption(audit_result.get("message", ""))

    # Jobs pie chart
    if all_jobs:
        st.divider()
        st.markdown("### Job Distribution")
        fig = px.pie(
            values=list(status_counts.values()),
            names=list(status_counts.keys()),
            color_discrete_map={
                "SUBMITTED":  "#4299e1",
                "SCHEDULED":  "#ed8936",
                "QUEUED":     "#a0aec0",
                "RUNNING":    "#48bb78",
                "COMPLETED":  "#38a169",
                "FAILED":     "#fc8181",
            },
            hole=0.4,
        )
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font_color="#e2e8f0",
            showlegend=True,
        )
        st.plotly_chart(fig, use_container_width=True)


# ── TAB 2: Jobs ──────────────────────────────────────────────────────────────
with tab_jobs:
    st.markdown("### All Jobs")
    jobs = fetch_jobs()
    if not jobs:
        st.info("No jobs found. Submit a job using the sidebar.")
    else:
        df = pd.DataFrame(jobs)
        st.dataframe(
            df,
            use_container_width=True,
            column_config={
                "status": st.column_config.TextColumn("Status"),
                "submitted_at": st.column_config.DatetimeColumn("Submitted"),
                "deadline": st.column_config.DatetimeColumn("Deadline"),
            },
        )

    st.divider()
    st.markdown("### Job Detail")
    selected_job_id = st.text_input("Enter Job ID for details")
    if selected_job_id:
        detail = fetch_job_detail(selected_job_id)
        if detail:
            st.json(detail)
        else:
            st.warning("Job not found")


# ── TAB 3: Carbon ─────────────────────────────────────────────────────────────
with tab_carbon:
    st.markdown("### Carbon Intensity Forecast")
    region_select = st.selectbox("Region", ["IN-WE", "IN-SO", "IN-EA", "IN-NO", "DE"])
    carbon_data = fetch_carbon_curve(region_select)
    if carbon_data:
        df_c = pd.DataFrame(carbon_data)
        df_c["timestamp"] = pd.to_datetime(df_c["timestamp"])
        fig = px.area(
            df_c, x="timestamp", y="carbon_gco2_kwh",
            title=f"Carbon Intensity — {region_select}",
            labels={"carbon_gco2_kwh": "gCO₂/kWh", "timestamp": "Time"},
            color_discrete_sequence=["#48bb78"],
        )
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(14,17,23,0.8)",
            font_color="#e2e8f0",
            xaxis=dict(gridcolor="#2d3748"),
            yaxis=dict(gridcolor="#2d3748"),
        )
        st.plotly_chart(fig, use_container_width=True)

    # Baseline comparison
    st.markdown("### Baseline vs GreenShift Emissions")
    jobs = fetch_jobs()
    scheduled = [j for j in jobs if j.get("status") in ("SCHEDULED", "QUEUED", "RUNNING", "COMPLETED")]
    if scheduled:
        comparison_data = []
        for j in scheduled:
            detail = fetch_job_detail(j["job_id"])
            sd = detail.get("schedule_decision")
            if sd:
                comparison_data.append({
                    "job_id": j["job_id"],
                    "baseline_kg": sd.get("baseline_carbon_emission", 0) or 0,
                    "greenshift_kg": sd.get("carbon_emission", 0) or 0,
                    "avoided_kg": sd.get("carbon_avoided", 0) or 0,
                })
        if comparison_data:
            df_comp = pd.DataFrame(comparison_data)
            fig2 = go.Figure(data=[
                go.Bar(name="Baseline", x=df_comp["job_id"], y=df_comp["baseline_kg"], marker_color="#fc8181"),
                go.Bar(name="GreenShift", x=df_comp["job_id"], y=df_comp["greenshift_kg"], marker_color="#48bb78"),
            ])
            fig2.update_layout(
                barmode="group",
                title="Carbon Emissions: Baseline vs GreenShift (kg CO₂)",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(14,17,23,0.8)",
                font_color="#e2e8f0",
                xaxis=dict(gridcolor="#2d3748"),
                yaxis=dict(gridcolor="#2d3748", title="kg CO₂"),
            )
            st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("No scheduled jobs to compare yet.")


# ── TAB 4: Kubernetes ─────────────────────────────────────────────────────────
with tab_kubernetes:
    st.markdown("### Kubernetes Job Execution")

    # K8s health
    try:
        kh = httpx.get(f"{API_URL}/api/v1/kubernetes/health", timeout=5)
        kh_data = kh.json()
        if kh_data.get("kubernetes_available"):
            st.success("☸️ Kubernetes API: **Connected**")
        else:
            st.warning("☸️ Kubernetes API: **Not reachable** (running in local mode)")
    except Exception:
        st.warning("☸️ Kubernetes API: **Unknown** (API unreachable)")

    st.divider()

    jobs = fetch_jobs()
    k8s_jobs = []
    for j in jobs:
        if j.get("status") in ("QUEUED", "RUNNING", "COMPLETED", "FAILED"):
            detail = fetch_job_detail(j["job_id"])
            k8s = detail.get("kubernetes")
            if k8s:
                k8s_jobs.append({
                    "job_id": j["job_id"],
                    "k8s_job_name": k8s.get("kubernetes_job_name"),
                    "namespace": k8s.get("kubernetes_namespace"),
                    "pod": k8s.get("pod_name"),
                    "planned_start": k8s.get("planned_start"),
                    "actual_start": k8s.get("actual_start"),
                    "actual_end": k8s.get("actual_end"),
                    "k8s_status": k8s.get("k8s_status"),
                    "gs_status": k8s.get("gs_status"),
                })

    if k8s_jobs:
        df_k8s = pd.DataFrame(k8s_jobs)
        st.dataframe(df_k8s, use_container_width=True)
    else:
        st.info("No dispatched Kubernetes jobs yet.")


# ── TAB 5: Audit Chain ────────────────────────────────────────────────────────
with tab_trust:
    st.markdown("### 🔐 Tamper-Evident Audit Ledger")
    audit = fetch_audit_verify()

    if audit.get("valid"):
        st.success(f"✅ **Audit Chain: VALID** — {audit.get('event_count', 0)} records verified")
    else:
        st.error(f"⚠️ **Audit Chain: BROKEN** — {audit.get('message', 'Unknown error')}")

    st.caption("Chain uses SHA-256. Any modification to any record is detectable.")
    st.divider()

    # Recent events
    try:
        r = httpx.get(f"{API_URL}/api/v1/trust/events", params={"limit": 50}, timeout=10)
        events_data = r.json().get("events", [])
        if events_data:
            df_events = pd.DataFrame(events_data)
            st.dataframe(
                df_events[["sequence", "event_type", "job_id", "timestamp", "current_hash"]],
                use_container_width=True,
            )
    except Exception as exc:
        st.warning(f"Could not load audit events: {exc}")

    # Job audit trail
    st.divider()
    audit_job_id = st.text_input("Job ID for audit trail")
    if audit_job_id:
        try:
            r = httpx.get(f"{API_URL}/api/v1/trust/jobs/{audit_job_id}", timeout=10)
            trail = r.json()
            st.json(trail)
        except Exception as exc:
            st.error(f"Error: {exc}")


# ── TAB 6: Export ─────────────────────────────────────────────────────────────
with tab_export:
    st.markdown("### 📥 Export Report")
    st.markdown("Download a CSV report of all jobs with carbon and cost metrics.")

    if st.button("📊 Generate Report"):
        jobs = fetch_jobs()
        rows = []
        for j in jobs:
            detail = fetch_job_detail(j["job_id"])
            sd = detail.get("schedule_decision", {}) or {}
            k8s = detail.get("kubernetes", {}) or {}
            rows.append({
                "job_id": j["job_id"],
                "team_id": j.get("team_id"),
                "status": j.get("status"),
                "region": j.get("region"),
                "runtime_minutes": j.get("runtime_minutes"),
                "power_kw": j.get("power_kw"),
                "deadline": j.get("deadline"),
                "selected_start": sd.get("selected_start"),
                "selected_end": sd.get("selected_end"),
                "carbon_intensity_gco2kwh": sd.get("carbon_intensity"),
                "electricity_cost_per_kwh": sd.get("electricity_cost"),
                "greenshift_carbon_kg": sd.get("carbon_emission"),
                "baseline_carbon_kg": sd.get("baseline_carbon_emission"),
                "carbon_avoided_kg": sd.get("carbon_avoided"),
                "greenshift_cost": sd.get("electricity_cost"),
                "baseline_cost": sd.get("baseline_cost"),
                "cost_saved": sd.get("cost_difference"),
                "k8s_job_name": k8s.get("kubernetes_job_name"),
                "k8s_status": k8s.get("k8s_status"),
                "actual_start": k8s.get("actual_start"),
                "actual_end": k8s.get("actual_end"),
            })
        if rows:
            df_export = pd.DataFrame(rows)
            csv = df_export.to_csv(index=False)
            st.download_button(
                label="⬇️ Download CSV",
                data=csv,
                file_name=f"greenshift_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv",
            )
            st.dataframe(df_export, use_container_width=True)
        else:
            st.info("No job data to export.")

# ─────────────────────────────────────────────────────────────────────────────
# Footer
# ─────────────────────────────────────────────────────────────────────────────
st.divider()
st.markdown(
    f"<div style='text-align:center; color:#4a5568; font-size:0.8em;'>"
    f"🌿 GreenShift v1.0 &nbsp;|&nbsp; "
    f"API: {API_URL} &nbsp;|&nbsp; "
    f"Auto-refresh every {REFRESH_INTERVAL}s &nbsp;|&nbsp; "
    f"Last updated: {datetime.now().strftime('%H:%M:%S')}"
    f"</div>",
    unsafe_allow_html=True,
)
