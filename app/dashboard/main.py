"""
Agent 5 — PRESENT
GreenShift Streamlit Dashboard — 4 Indian Regional Grids Architecture.

Pages:
  1. 📊 Overview
  2. 📋 Jobs
  3. 🌿 Carbon
  4. ⚡ Electricity Cost
  5. 🌍 Regional Data
  6. ☸️ Kubernetes
  7. 📈 Baseline vs GreenShift Impact
  8. 🔐 Audit
  9. 📥 Export
"""

import os
import time
import json
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, List

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import httpx

from app.shared.timezone import resolve_region_timezone, format_regional_time

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

API_URL = os.environ.get("API_BASE_URL", os.environ.get("GREENSHIFT_API_URL", "http://localhost:8000"))
REFRESH_INTERVAL = 30  # seconds

st.set_page_config(
    page_title="GreenShift — Carbon- & Cost-Aware Kubernetes Platform",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# Styling
# ─────────────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    .main { background-color: #0d1117; }

    .metric-card {
        background: linear-gradient(135deg, #161b22 0%, #0d1117 100%);
        border: 1px solid #30363d;
        border-radius: 10px;
        padding: 16px;
        text-align: center;
    }

    .green-badge {
        background: linear-gradient(90deg, #2ea043, #238636);
        color: white;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.85em;
        font-weight: 600;
        display: inline-block;
    }

    .red-badge {
        background: linear-gradient(90deg, #da3633, #b62324);
        color: white;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.85em;
        font-weight: 600;
        display: inline-block;
    }

    .blue-badge {
        background: linear-gradient(90deg, #1f6feb, #1158c7);
        color: white;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.85em;
        font-weight: 600;
        display: inline-block;
    }

    .region-card {
        background: #161b22;
        border: 1px solid #30363d;
        border-radius: 8px;
        padding: 16px;
        margin-bottom: 12px;
    }

    h1, h2, h3 { color: #f0f6fc; }
    .stMetric label { color: #8b949e !important; }
    .stMetric .metric-value { color: #f0f6fc !important; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# API Helpers
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=REFRESH_INTERVAL)
def fetch_jobs(status_filter: Optional[str] = None, limit: int = 1000) -> list:
    try:
        params = {"limit": limit}
        if status_filter:
            params["status"] = status_filter
        r = httpx.get(f"{API_URL}/api/v1/jobs", params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
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
        r = httpx.get(f"{API_URL}/api/v1/audit/verify", timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {"valid": False, "message": "API unreachable"}


@st.cache_data(ttl=REFRESH_INTERVAL)
def fetch_audit_events(limit: int = 50) -> list:
    try:
        r = httpx.get(f"{API_URL}/api/v1/audit/events", params={"limit": limit}, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        return []


@st.cache_data(ttl=REFRESH_INTERVAL)
def fetch_carbon_curve(region: str) -> list:
    try:
        r = httpx.get(f"{API_URL}/api/v1/carbon", params={"region": region}, timeout=10)
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception:
        return []


@st.cache_data(ttl=REFRESH_INTERVAL)
def fetch_regional_tariffs(region: str, tariff_plan: Optional[str] = None) -> list:
    try:
        params = {"region": region}
        if tariff_plan:
            params["tariff_plan"] = tariff_plan
        r = httpx.get(f"{API_URL}/api/v1/regional/tariffs", params=params, timeout=10)
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception:
        return []


@st.cache_data(ttl=REFRESH_INTERVAL)
def fetch_regions() -> list:
    try:
        r = httpx.get(f"{API_URL}/api/v1/regions", timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        return []


@st.cache_data(ttl=REFRESH_INTERVAL)
def fetch_regional_inventory() -> dict:
    try:
        r = httpx.get(f"{API_URL}/api/v1/regional/inventory", timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}


@st.cache_data(ttl=REFRESH_INTERVAL)
def fetch_kubernetes_state() -> dict:
    try:
        r = httpx.get(f"{API_URL}/api/v1/kubernetes/state", timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}


@st.cache_data(ttl=REFRESH_INTERVAL)
def fetch_data_sources_status() -> dict:
    try:
        r = httpx.get(f"{API_URL}/api/v1/data-sources/status", timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}


@st.cache_data(ttl=REFRESH_INTERVAL)
def fetch_pending_approvals() -> list:
    try:
        r = httpx.get(f"{API_URL}/api/v1/approvals/pending", timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        return []


def approve_job_api(job_id: str, schedule_id: int, reason: str = "Schedule acceptable", approved_by: str = "operator") -> dict:
    payload = {
        "schedule_id": schedule_id,
        "reason": reason,
        "approved_by": approved_by,
    }
    r = httpx.post(f"{API_URL}/api/v1/approval/{job_id}/approve", json=payload, timeout=15)
    r.raise_for_status()
    return r.json()


def decline_job_api(job_id: str, schedule_id: int, reason: str = "Window declined", approved_by: str = "operator") -> dict:
    payload = {
        "schedule_id": schedule_id,
        "reason": reason,
        "approved_by": approved_by,
    }
    r = httpx.post(f"{API_URL}/api/v1/approval/{job_id}/decline", json=payload, timeout=15)
    r.raise_for_status()
    return r.json()


# ─────────────────────────────────────────────────────────────────────────────
# Header
# ─────────────────────────────────────────────────────────────────────────────

col_logo, col_title, col_refresh = st.columns([1, 8, 2])
with col_logo:
    st.markdown("# 🌿")
with col_title:
    st.markdown("## GreenShift — Carbon- & Cost-Aware Kubernetes Platform")
    st.caption("Indian Regional Data Layer: Telangana (IN-TG), Gujarat (IN-GJ), Himachal Pradesh (IN-HP), West Bengal (IN-WB) | Electricity Maps Live Telemetry")
with col_refresh:
    if st.button("⟳ Refresh"):
        st.cache_data.clear()
        st.rerun()

st.divider()

# ─────────────────────────────────────────────────────────────────────────────
# Sidebar — Actions & Pipeline Controls
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("### 📥 Bulk Workload Ingest")
    if st.button("📂 Load 560 Workloads (CSV)"):
        try:
            r = httpx.post(f"{API_URL}/api/v1/jobs/bulk-load", timeout=30)
            res = r.json()
            st.success(f"✅ Loaded {res.get('jobs_loaded', 0)} jobs!")
            st.cache_data.clear()
            st.rerun()
        except Exception as exc:
            st.error(f"Bulk load failed: {exc}")

    st.divider()
    st.markdown("### ⚙️ Quick Actions")
    action_job_id = st.text_input("Job ID", placeholder="e.g. GS-JOB-000001")
    col_sch, col_disp = st.columns(2)
    with col_sch:
        if st.button("📅 Schedule"):
            if action_job_id:
                try:
                    r = httpx.post(f"{API_URL}/api/v1/schedule/{action_job_id}", timeout=30)
                    r.raise_for_status()
                    st.success("Scheduled (Pending Approval)!")
                    st.cache_data.clear()
                    st.rerun()
                except Exception as exc:
                    st.error(f"{exc}")
    with col_disp:
        if st.button("☸️ Dispatch"):
            if action_job_id:
                try:
                    r = httpx.post(f"{API_URL}/api/v1/dispatch/{action_job_id}", timeout=30)
                    r.raise_for_status()
                    st.success("Dispatched!")
                    st.cache_data.clear()
                    st.rerun()
                except Exception as exc:
                    st.error(f"{exc}")


# ─────────────────────────────────────────────────────────────────────────────
# Main Navigation — 10 Target Architecture Tabs
# ─────────────────────────────────────────────────────────────────────────────

tabs = st.tabs([
    "📊 Overview",
    "📋 Jobs",
    "✋ Pending Approvals",
    "🌿 Carbon",
    "⚡ Electricity Cost",
    "🌍 Regional Data",
    "☸️ Kubernetes",
    "📈 Baseline vs GreenShift Impact",
    "🔐 Audit",
    "📥 Export",
])

all_jobs = fetch_jobs()

# ── 1. OVERVIEW ──────────────────────────────────────────────────────────────
with tabs[0]:
    audit_res = fetch_audit_verify()
    k8s_state = fetch_kubernetes_state()

    counts = {
        "SUBMITTED": 0,
        "SCHEDULED": 0,
        "PENDING_APPROVAL": 0,
        "APPROVED": 0,
        "DECLINED": 0,
        "QUEUED": 0,
        "RUNNING": 0,
        "COMPLETED": 0,
        "FAILED": 0,
    }
    for j in all_jobs:
        s = j.get("status", "SUBMITTED")
        if s in counts:
            counts[s] += 1

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("📬 Total Workloads", len(all_jobs))
    m2.metric("✋ Pending Approval", counts["PENDING_APPROVAL"])
    m3.metric("✅ Approved", counts["APPROVED"])
    m4.metric("⏳ Queued", counts["QUEUED"])
    m5.metric("🏃 Running", counts["RUNNING"])
    m6.metric("🏁 Completed", counts["COMPLETED"])

    st.divider()

    c1, c2, c3, c4 = st.columns(4)
    data_status = fetch_data_sources_status()
    carbon_info = data_status.get("carbon", {})

    with c1:
        st.markdown("### 🌍 Regional Data")
        st.markdown("#### `4 Indian Regions`")
        st.caption("Telangana, Gujarat, Himachal Pradesh, West Bengal")
    with c2:
        st.markdown("### 🌿 Carbon Resilience")
        c_src = carbon_info.get("source", "electricity_maps").upper()
        if c_src == "ELECTRICITY_MAPS":
            badge = '<span class="green-badge">● LIVE API</span>'
        elif c_src in ("CACHE", "CACHE_STALE"):
            badge = '<span class="blue-badge">● CACHE</span>'
        else:
            badge = '<span class="red-badge">● FALLBACK</span>'
        st.markdown(f"#### Source: {badge}", unsafe_allow_html=True)
        st.caption(f"Cache TTL: {carbon_info.get('cache_ttl_seconds', 900)}s | Fallback: {'Active' if carbon_info.get('is_fallback') else 'Inactive'}")
    with c3:
        st.markdown("### ☸️ Cluster Health")
        health = k8s_state.get("cluster_health", "UNKNOWN")
        badge = '<span class="green-badge">HEALTHY</span>' if health == "HEALTHY" else f'<span class="blue-badge">{health}</span>'
        st.markdown(f"#### Status: {badge}", unsafe_allow_html=True)
        st.caption(f"Free CPU: {k8s_state.get('free_cpu_cores', 0):.1f} cores | RAM: {k8s_state.get('free_memory_mib', 0)/1024:.1f} GiB")
    with c4:
        st.markdown("### 🔐 Audit Ledger")
        if audit_res.get("valid"):
            st.markdown('<span class="green-badge">✓ SHA-256 VALID</span>', unsafe_allow_html=True)
        else:
            st.markdown('<span class="red-badge">✗ FAILED</span>', unsafe_allow_html=True)
        st.caption(audit_res.get("message", ""))

    if all_jobs:
        st.divider()
        fig = px.pie(
            values=list(counts.values()),
            names=list(counts.keys()),
            title="Workload Pipeline Status Distribution",
            color_discrete_sequence=px.colors.qualitative.Prism,
            hole=0.4,
        )
        fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color="#f0f6fc")
        st.plotly_chart(fig, use_container_width=True)


# ── 2. JOBS ──────────────────────────────────────────────────────────────────
with tabs[1]:
    st.markdown("### 📋 Workload Inventory — Canonical Workload Dataset")
    if not all_jobs:
        st.info("No workloads loaded. Use **Load Workloads (CSV)** in the sidebar.")
    else:
        df = pd.DataFrame(all_jobs)
        
        # Summary KPI Cards
        j_col1, j_col2, j_col3, j_col4 = st.columns(4)
        j_col1.metric("Total Jobs", len(df))
        j_col2.metric("Deferrable Workloads", int(df["deferrable"].sum()) if "deferrable" in df.columns else 0)
        j_col3.metric("Total Power Draw", f"{df['power_kw'].sum():.1f} kW" if "power_kw" in df.columns else "N/A")
        j_col4.metric("Avg Runtime", f"{df['runtime_minutes'].mean():.1f} mins" if "runtime_minutes" in df.columns else "N/A")

        # Distribution Breakdowns
        b_c1, b_c2, b_c3 = st.columns(3)
        with b_c1:
            if "region" in df.columns:
                st.caption("**Jobs by Region**")
                st.dataframe(df["region"].value_counts().reset_index(), use_container_width=True, hide_index=True)
        with b_c2:
            if "job_type" in df.columns:
                st.caption("**Jobs by Workload Type**")
                st.dataframe(df["job_type"].value_counts().reset_index(), use_container_width=True, hide_index=True)
        with b_c3:
            if "priority" in df.columns:
                st.caption("**Jobs by Priority**")
                st.dataframe(df["priority"].value_counts().reset_index(), use_container_width=True, hide_index=True)

        st.divider()

        # Detailed Table
        cols_to_show = [
            c for c in [
                "job_id", "team_id", "job_type", "priority", "status", "region",
                "submitted_at", "earliest_start_time", "deadline", "runtime_minutes",
                "power_kw", "energy_kwh", "deferrable", "carbon_budget_kg",
                "cpu_request", "memory_request", "container_image"
            ] if c in df.columns
        ]
        st.dataframe(df[cols_to_show], use_container_width=True, hide_index=True)


# ── 3. PENDING APPROVALS ─────────────────────────────────────────────────────
with tabs[2]:
    st.markdown("### ✋ Human Approval Gate — Proposed Schedules")
    st.caption("A job must NEVER be dispatched to Kubernetes until an authorized user explicitly approves the proposed schedule.")

    pending_list = fetch_pending_approvals()

    if not pending_list:
        st.info("✅ No workloads currently pending approval. When jobs are scheduled, their proposed execution windows will appear here for review.")
    else:
        st.write(f"**Found {len(pending_list)} workload(s) awaiting approval:**")
        
        for item in pending_list:
            job_id = item.get("job_id")
            sched_id = item.get("schedule_id")
            workload_name = item.get("workload_name") or job_id
            region = item.get("region", "IN-TG")
            tz_name = item.get("timezone", "Asia/Kolkata")
            start_utc = item.get("selected_start_utc", "")
            start_local = item.get("selected_start_local", "")
            end_utc = item.get("selected_end_utc", "")
            end_local = item.get("selected_end_local", "")
            deadline_utc = item.get("deadline_utc", "")
            deadline_local = item.get("deadline_local", "")
            carbon_kg = item.get("carbon_emission_kg", 0.0)
            carbon_intensity = item.get("carbon_intensity", 0.0)
            cost_usd = item.get("electricity_cost_usd", 0.0)
            runtime_mins = item.get("runtime_minutes", 0)
            power_kw = item.get("power_kw", 0.0)
            status_val = item.get("status", "PENDING_APPROVAL")

            with st.container():
                st.markdown(f"#### 🏷️ `{job_id}` — {workload_name}")
                col_info1, col_info2, col_info3 = st.columns(3)

                with col_info1:
                    st.markdown(f"**Team:** `{item.get('team_id')}`")
                    st.markdown(f"**Proposed Region:** `{region}`")
                    st.markdown(f"**IANA Timezone:** `{tz_name}`")
                    st.markdown(f"**Current Status:** `<span class='blue-badge'>{status_val}</span>`", unsafe_allow_html=True)

                with col_info2:
                    st.markdown(f"**Start (UTC):** `{start_utc}`")
                    st.markdown(f"**Start (Local):** `{start_local}`")
                    st.markdown(f"**End (UTC):** `{end_utc}`")
                    st.markdown(f"**End (Local):** `{end_local}`")
                    st.markdown(f"**Deadline (UTC):** `{deadline_utc}`")
                    st.markdown(f"**Deadline (Local):** `{deadline_local}`")

                with col_info3:
                    st.markdown(f"**Runtime:** `{runtime_mins} mins` | **Power:** `{power_kw} kW`")
                    st.markdown(f"**Carbon Estimate:** `{carbon_kg:.4f} kg CO₂` ({carbon_intensity:.1f} gCO₂/kWh)")
                    st.markdown(f"**Electricity Cost:** `${cost_usd:.4f}`")
                    if item.get("tariff_plan"):
                        st.markdown(f"**Tariff Plan:** `{item.get('tariff_plan')}`")

                # Action Controls
                act_col1, act_col2 = st.columns([1, 2])
                with act_col1:
                    if st.button("✅ APPROVE", key=f"btn_approve_{job_id}_{sched_id}"):
                        try:
                            res = approve_job_api(job_id=job_id, schedule_id=sched_id, reason="Approved via Dashboard", approved_by="dashboard_operator")
                            st.success(f"Job {job_id} APPROVED successfully! Status: APPROVED (Will dispatch at {start_utc} UTC)")
                            st.cache_data.clear()
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Approval failed: {exc}")

                with act_col2:
                    decline_reason = st.text_input("Reason for decline", placeholder="e.g. Inconvenient execution window", key=f"text_decline_{job_id}_{sched_id}")
                    if st.button("❌ DECLINE", key=f"btn_decline_{job_id}_{sched_id}"):
                        try:
                            res = decline_job_api(job_id=job_id, schedule_id=sched_id, reason=decline_reason or "Declined via Dashboard", approved_by="dashboard_operator")
                            st.warning(f"Job {job_id} DECLINED. Status: DECLINED (Workload will not dispatch)")
                            st.cache_data.clear()
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Decline failed: {exc}")

                st.divider()



# ── 4. CARBON ────────────────────────────────────────────────────────────────
with tabs[3]:
    st.markdown("### 🌿 Carbon Intensity & Multi-Level Data Resilience")
    col_reg, col_stat = st.columns([4, 6])
    with col_reg:
        sel_region = st.selectbox(
            "Grid Region",
            ["IN-TG", "IN-GJ", "IN-HP", "IN-WB"],
            format_func=lambda x: {
                "IN-TG": "Telangana (IN-TG / Southern Grid)",
                "IN-GJ": "Gujarat (IN-GJ / Western Grid)",
                "IN-HP": "Himachal Pradesh (IN-HP / Northern Grid)",
                "IN-WB": "West Bengal (IN-WB / Eastern Grid)",
            }.get(x, x),
            key="carbon_reg_select",
        )

    c_points = fetch_carbon_curve(sel_region)
    with col_stat:
        if c_points:
            sample = c_points[0]
            src = sample.get("source", "electricity_maps").upper()
            is_fb = sample.get("is_fallback", False)
            fb_rsn = sample.get("fallback_reason")

            stat_badge = (
                '<span class="green-badge">● LIVE API</span>' if src == "ELECTRICITY_MAPS"
                else '<span class="blue-badge">● FRESH CACHE</span>' if src == "CACHE"
                else '<span class="blue-badge">● STALE CACHE</span>' if src == "CACHE_STALE"
                else '<span class="blue-badge">● CSV DATASET</span>' if src == "CSV"
                else '<span class="red-badge">● CONTROLLED FALLBACK</span>'
            )
            st.markdown(f"**Data Resilience Source:** {stat_badge}", unsafe_allow_html=True)
            if fb_rsn:
                st.caption(f"⚠️ Notice: {fb_rsn}")
            elif sample.get("cache_age_seconds"):
                st.caption(f"Cache age: {sample.get('cache_age_seconds'):.1f}s (TTL: 900s)")

    if c_points:
        df_c = pd.DataFrame(c_points)
        df_c["timestamp"] = pd.to_datetime(df_c["timestamp"])
        fig_c = px.line(
            df_c,
            x="timestamp",
            y="carbon_gco2_kwh",
            title=f"Carbon Intensity Forecast ({sel_region}) — gCO₂eq / kWh",
            labels={"carbon_gco2_kwh": "gCO2/kWh", "timestamp": "UTC Time"},
            markers=True,
        )
        fig_c.update_traces(line_color="#3fb950")
        fig_c.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color="#f0f6fc")
        st.plotly_chart(fig_c, use_container_width=True)
    else:
        st.info(f"No carbon data available for {sel_region}.")


# ── 5. ELECTRICITY COST ──────────────────────────────────────────────────────
with tabs[4]:
    st.markdown("### ⚡ Electricity Cost & Time-of-Day Tariffs")
    st.info("📊 **Tariff Data Source**: Master ToD Regional Tariff Dataset (`master_tod_tariff_all_regions.csv`)")

    from app.shared.tariff_service import get_available_regions, get_currency_for_region
    avail_regions = get_available_regions()

    col_r1, col_r2 = st.columns([1, 1])
    with col_r1:
        cost_region = st.selectbox(
            "Select Region",
            avail_regions,
            format_func=lambda x: {
                "IN-TG": "🇮🇳 Telangana (IN-TG)",
                "IN-GJ": "🇮🇳 Gujarat (IN-GJ)",
                "IN-WB": "🇮🇳 West Bengal (IN-WB)",
                "IN-PB": "🇮🇳 Punjab (IN-PB)",
                "US-CA": "🇺🇸 California (US-CA)",
                "US-NY": "🇺🇸 New York (US-NY)",
                "US-TX": "🇺🇸 Texas (US-TX)",
                "SE": "🇸🇪 Sweden (SE)",
                "AU-SA-Large": "🇦🇺 South Australia Large (AU-SA-Large)",
                "AU-SA-Small": "🇦🇺 South Australia Small (AU-SA-Small)",
            }.get(x, x),
            key="cost_reg_select",
        )
    with col_r2:
        reg_tz = resolve_region_timezone(cost_region)
        reg_curr = get_currency_for_region(cost_region)
        st.markdown(f"**Timezone**: `{reg_tz}` | **Currency**: `{reg_curr}`")
        curr_sym = {"INR": "₹", "USD": "$", "SEK": "kr ", "AUD": "A$"}.get(reg_curr, "")

    tariffs = fetch_regional_tariffs(cost_region)
    if tariffs:
        df_t = pd.DataFrame(tariffs)
        df_t["timestamp"] = pd.to_datetime(df_t["timestamp"])

        cur_row = df_t.iloc[0] if not df_t.empty else {}
        cur_rate = cur_row.get("electricity_rate", 0.0)
        cur_tod = cur_row.get("tod_block", "Normal")
        cur_base = cur_row.get("base_energy_rate", cur_rate)
        cur_adder = cur_row.get("tod_adder", 0.0)
        cur_type = cur_row.get("category", "ToD")
        cur_season = cur_row.get("season", "All-Year")

        m_c1, m_c2, m_c3, m_c4 = st.columns(4)
        m_c1.metric("Current Rate", f"{curr_sym}{cur_rate:.4f} / kWh")
        m_c2.metric("Base Charge", f"{curr_sym}{cur_base:.4f}")
        m_c3.metric("Adder Charge", f"{curr_sym}{cur_adder:+.4f}")
        m_c4.metric("ToD Block", cur_tod)

        fig_t = px.bar(
            df_t,
            x="local_timestamp",
            y="electricity_rate",
            color="tod_block",
            title=f"Hourly Tariff Curve — {cost_region} ({reg_curr}) | Tariff Type: {cur_type} | Season: {cur_season}",
            labels={"electricity_rate": f"Effective Rate ({reg_curr}/kWh)", "local_timestamp": f"Local Time ({reg_tz})", "tod_block": "ToD Block"},
        )
        fig_t.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color="#f0f6fc")
        st.plotly_chart(fig_t, use_container_width=True)
    else:
        st.info("No tariff data found for selected region.")


# ── 6. REGIONAL DATA ─────────────────────────────────────────────────────────
with tabs[5]:
    st.markdown("### 🌍 Regional Data Layer — Master ToD Tariff Dataset")
    st.markdown("**Single Source of Truth**: `data/master_tod_tariff_all_regions.csv` across all 10 supported regional grids.")
    reg_inv = fetch_regional_inventory()
    inv_list = reg_inv.get("inventory", [])

    if inv_list:
        df_inv = pd.DataFrame(inv_list)
        show_cols = [c for c in ["region_id", "country", "region_name", "tariff_plan", "category", "currency", "timezone", "season", "rate_min", "rate_max", "source_file", "carbon_source"] if c in df_inv.columns]
        st.dataframe(
            df_inv[show_cols],
            use_container_width=True,
            hide_index=True,
        )

        st.divider()
        st.markdown("#### 📖 Supported Regional Grid Profiles")
        st.caption("All tariffs load from `data/master_tod_tariff_all_regions.csv` with automatic UTC-to-local timezone conversion across India, US, Sweden, and Australia.")


# ── 7. KUBERNETES ────────────────────────────────────────────────────────────
with tabs[6]:
    st.markdown("### ☸️ Kubernetes State Collector & Node Telemetry")
    k8s = fetch_kubernetes_state()
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Nodes (Ready / Total)", f"{k8s.get('ready_nodes', 0)} / {k8s.get('total_nodes', 0)}")
    k2.metric("CPU (Free / Allocatable)", f"{k8s.get('free_cpu_cores', 0):.1f} / {k8s.get('allocatable_cpu_cores', 0):.1f} cores")
    k3.metric("RAM (Free / Allocatable)", f"{k8s.get('free_memory_mib', 0)/1024:.1f} / {k8s.get('allocatable_memory_mib', 0)/1024:.1f} GiB")
    k4.metric("GPUs (Free / Total)", f"{k8s.get('free_gpus', 0)} / {k8s.get('total_gpus', 0)}")

    nodes = k8s.get("nodes", [])
    if nodes:
        st.divider()
        st.markdown("#### Node Inventory")
        df_nodes = pd.DataFrame(nodes)
        st.dataframe(df_nodes[["name", "status", "cpu_allocatable_cores", "memory_allocatable_mib", "gpu_allocatable", "roles"]], use_container_width=True, hide_index=True)

    st.divider()
    st.markdown("#### 🚀 Dynamic Kubernetes Workload Executions")
    if all_jobs:
        k8s_job_rows = []
        for j in all_jobs:
            reg = j.get("region", "IN-TG")
            tz_str = resolve_region_timezone(reg)
            sel_utc = j.get("selected_start")
            sel_local = "Pending"
            if sel_utc:
                try:
                    dt_val = datetime.fromisoformat(sel_utc)
                    sel_local = format_regional_time(dt_val, region=reg)
                except Exception:
                    sel_local = sel_utc

            carb_val = f"{j.get('carbon_emission', 0):.4f} kg" if j.get("carbon_emission") is not None else "N/A"
            cost_val = f"${j.get('electricity_cost', 0):.4f}" if j.get("electricity_cost") is not None else "N/A"

            k8s_job_rows.append({
                "Job ID": j.get("job_id"),
                "Region": reg,
                "IANA Timezone": tz_str,
                "Schedule Time (UTC)": sel_utc or "Pending",
                "Schedule Time (Local)": sel_local,
                "GreenShift Status": j.get("status"),
                "Kubernetes Job Name": j.get("kubernetes_job_name") or "None",
                "Kubernetes Status": j.get("k8s_status") or "None",
                "Pod Name": j.get("pod_name") or "None",
                "Actual Start": j.get("actual_start") or "N/A",
                "Actual End": j.get("actual_end") or "N/A",
                "Carbon Value": carb_val,
                "Cost Value": cost_val,
            })

        df_k8s_jobs = pd.DataFrame(k8s_job_rows)
        st.dataframe(df_k8s_jobs, use_container_width=True, hide_index=True)
    else:
        st.info("No workloads found.")


# ── 8. BASELINE VS GREENSHIFT IMPACT ─────────────────────────────────────────
with tabs[7]:
    st.markdown("### 📈 Baseline vs GreenShift Impact Analysis")
    target_job_id = st.selectbox("Select Scheduled Job", [j["job_id"] for j in all_jobs if j.get("status") in ("SCHEDULED", "APPROVED", "QUEUED", "RUNNING", "COMPLETED")], key="impact_job_select")

    if target_job_id:
        job_info = fetch_job_detail(target_job_id)
        sd = job_info.get("schedule_decision", {})

        if sd:
            imp1, imp2, imp3, imp4 = st.columns(4)
            carb_red = sd.get("carbon_reduction_pct", 0.0) or 0.0
            cost_red = sd.get("cost_reduction_pct", 0.0) or 0.0
            carb_av = sd.get("carbon_avoided", 0.0) or 0.0
            cost_av = sd.get("cost_difference", 0.0) or 0.0

            imp1.metric("🌱 Carbon Avoided", f"{carb_av:.4f} kg", f"-{carb_red:.1f}%")
            imp2.metric("💰 Cost Avoided (USD)", f"${cost_av:.4f}", f"-{cost_red:.1f}%")
            imp3.metric("⏱️ Scheduling Delay", f"{sd.get('scheduling_delay_hours', 0.0):.2f} hrs")
            sla_ok = sd.get("sla_met", True)
            imp4.metric("🎯 SLA Compliance", "MET" if sla_ok else "BREACHED")

            st.divider()

            # Side by side comparison table
            comp_data = {
                "Metric": ["Start Time", "End Time", "Carbon Emission (kg CO₂)", "Electricity Cost (USD)", "Native Cost (INR)", "Carbon Intensity (gCO₂/kWh)"],
                "Baseline (Immediate)": [
                    sd.get("baseline_start", "N/A"),
                    sd.get("baseline_end", "N/A"),
                    f"{sd.get('baseline_carbon_emission', 0):.4f} kg",
                    f"${sd.get('baseline_cost', 0):.4f}",
                    f"₹{sd.get('baseline_native_cost', 0):.4f}",
                    "Baseline Slot",
                ],
                "GreenShift (Optimized)": [
                    sd.get("selected_start", "N/A"),
                    sd.get("selected_end", "N/A"),
                    f"{sd.get('carbon_emission', 0):.4f} kg",
                    f"${sd.get('electricity_cost', 0):.4f}",
                    f"₹{sd.get('native_cost', 0):.4f}",
                    f"{sd.get('carbon_intensity', 0):.1f} gCO2/kWh",
                ],
            }
            st.dataframe(pd.DataFrame(comp_data), use_container_width=True, hide_index=True)

            # Visual Bar Charts
            bc1, bc2 = st.columns(2)
            with bc1:
                fig_c_comp = go.Figure(data=[
                    go.Bar(name='Baseline', x=['Carbon Emissions (kg CO₂)'], y=[sd.get('baseline_carbon_emission', 0)], marker_color='#f85149'),
                    go.Bar(name='GreenShift', x=['Carbon Emissions (kg CO₂)'], y=[sd.get('carbon_emission', 0)], marker_color='#2ea043'),
                ])
                fig_c_comp.update_layout(barmode='group', title="Carbon Emissions Comparison", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color="#f0f6fc")
                st.plotly_chart(fig_c_comp, use_container_width=True)

            with bc2:
                fig_cost_comp = go.Figure(data=[
                    go.Bar(name='Baseline', x=['Electricity Cost (USD)'], y=[sd.get('baseline_cost', 0)], marker_color='#f85149'),
                    go.Bar(name='GreenShift', x=['Electricity Cost (USD)'], y=[sd.get('electricity_cost', 0)], marker_color='#2ea043'),
                ])
                fig_cost_comp.update_layout(barmode='group', title="Electricity Cost Comparison ($ USD)", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color="#f0f6fc")
                st.plotly_chart(fig_cost_comp, use_container_width=True)
        else:
            st.info("Job selected does not have a schedule decision record.")
    else:
        st.info("No scheduled jobs found.")


# ── 9. AUDIT ─────────────────────────────────────────────────────────────────
with tabs[8]:
    st.markdown("### 🔐 Tamper-Evident SHA-256 Audit Ledger")
    aud = fetch_audit_verify()
    if aud.get("valid"):
        st.success(f"✅ {aud.get('message')}")
    else:
        st.error(f"❌ {aud.get('message')}")

    events = fetch_audit_events(limit=100)
    if events:
        df_ev = pd.DataFrame(events)
        st.dataframe(df_ev[["sequence", "event_type", "job_id", "timestamp", "current_hash", "previous_hash"]], use_container_width=True, hide_index=True)


# ── 10. EXPORT ───────────────────────────────────────────────────────────────
with tabs[9]:
    st.markdown("### 📥 Export & BRSR ESG Reports")
    st.caption("Generate verifiable audit records and CSV exports for sustainability reporting.")

    col_e1, col_e2 = st.columns(2)
    with col_e1:
        if all_jobs:
            df_export = pd.DataFrame(all_jobs)
            csv_data = df_export.to_csv(index=False).encode('utf-8')
            st.download_button(
                "📥 Download Workloads Dataset (CSV)",
                data=csv_data,
                file_name="greenshift_workloads_export.csv",
                mime="text/csv",
            )
    with col_e2:
        try:
            r = httpx.get(f"{API_URL}/api/v1/report/brsr", timeout=10)
            if r.status_code == 200:
                report_data = r.json()
                st.download_button(
                    "📥 Download BRSR ESG Report (JSON)",
                    data=json.dumps(report_data, indent=2),
                    file_name="greenshift_brsr_report.json",
                    mime="application/json",
                )
        except Exception:
            pass
