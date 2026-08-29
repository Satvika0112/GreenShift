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

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

API_URL = os.environ.get("GREENSHIFT_API_URL", "http://localhost:8000")
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
                    st.success("Scheduled!")
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
# Main Navigation — 9 Target Architecture Tabs
# ─────────────────────────────────────────────────────────────────────────────

tabs = st.tabs([
    "📊 Overview",
    "📋 Jobs",
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

    counts = {"SUBMITTED": 0, "SCHEDULED": 0, "QUEUED": 0, "RUNNING": 0, "COMPLETED": 0, "FAILED": 0}
    for j in all_jobs:
        s = j.get("status", "SUBMITTED")
        if s in counts:
            counts[s] += 1

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("📬 Total Workloads", len(all_jobs))
    m2.metric("📅 Scheduled", counts["SCHEDULED"])
    m3.metric("⏳ Queued", counts["QUEUED"])
    m4.metric("🏃 Running", counts["RUNNING"])
    m5.metric("✅ Completed", counts["COMPLETED"])
    m6.metric("❌ Failed", counts["FAILED"])

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
    st.markdown("### 📋 Workload Inventory (560 Real Workloads)")
    if not all_jobs:
        st.info("No workloads loaded. Use **Load 560 Workloads (CSV)** in the sidebar.")
    else:
        df = pd.DataFrame(all_jobs)
        cols_to_show = [c for c in ["job_id", "job_type", "priority", "status", "region", "runtime_minutes", "power_kw", "energy_kwh", "deferrable", "deadline"] if c in df.columns]
        st.dataframe(df[cols_to_show], use_container_width=True, hide_index=True)


# ── 3. CARBON ────────────────────────────────────────────────────────────────
with tabs[2]:
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


# ── 4. ELECTRICITY COST ──────────────────────────────────────────────────────
with tabs[3]:
    st.markdown("### ⚡ Electricity Cost & Time-of-Day Tariffs")
    c_r, c_p = st.columns(2)
    with c_r:
        cost_region = st.selectbox(
            "Region",
            ["IN-TG", "IN-GJ", "IN-HP", "IN-WB"],
            format_func=lambda x: {
                "IN-TG": "Telangana (IN-TG)",
                "IN-GJ": "Gujarat (IN-GJ)",
                "IN-HP": "Himachal Pradesh (IN-HP)",
                "IN-WB": "West Bengal (IN-WB)",
            }.get(x, x),
            key="cost_reg_select",
        )
    with c_p:
        plan_options = {
            "IN-TG": ["HT-I(A)", "HT-II(A)"],
            "IN-GJ": ["HTP-I"],
            "IN-HP": ["Large Industry - EHT"],
            "IN-WB": ["Industries (Rate E-BT)"],
        }.get(cost_region, [])
        cost_plan = st.selectbox("Tariff Plan", plan_options, key="cost_plan_select")

    tariffs = fetch_regional_tariffs(cost_region, tariff_plan=cost_plan)
    if tariffs:
        df_t = pd.DataFrame(tariffs)
        df_t["timestamp"] = pd.to_datetime(df_t["timestamp"])
        fig_t = px.bar(
            df_t,
            x="local_timestamp",
            y="electricity_rate",
            color="tod_block",
            title=f"Hourly Tariff Curve — {cost_plan} (₹ INR / kWh)",
            labels={"electricity_rate": "Effective Rate (₹/kWh)", "local_timestamp": "Local Time (IST)", "tod_block": "ToD Block"},
        )
        fig_t.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color="#f0f6fc")
        st.plotly_chart(fig_t, use_container_width=True)
    else:
        st.info("No tariff data found for selected plan.")


# ── 5. REGIONAL DATA ─────────────────────────────────────────────────────────
with tabs[4]:
    st.markdown("### 🌍 Regional Data Layer & Canonical Common Schema")
    reg_inv = fetch_regional_inventory()
    inv_list = reg_inv.get("inventory", [])

    if inv_list:
        df_inv = pd.DataFrame(inv_list)
        st.dataframe(
            df_inv[["region_id", "region_name", "tariff_plan", "category", "voltage", "currency", "rate_min", "rate_max", "is_flat", "source_file", "carbon_source"]],
            use_container_width=True,
            hide_index=True,
        )

        st.divider()
        st.markdown("#### 📖 Supported Regional Characteristics")
        col_tg, col_gj, col_hp, col_wb = st.columns(4)
        with col_tg:
            st.markdown("""
            **🇮🇳 Telangana (`IN-TG`)**
            - **Timezone**: `Asia/Kolkata`
            - **Currency**: `INR` (₹)
            - **Plans**:
              - *HT-I(A)*: Industry General (11 kV)
              - *HT-II(A)*: Commercial & Others
            - **Grid Zone**: `IN-SO` (Southern Grid)
            """)
        with col_gj:
            st.markdown("""
            **🇮🇳 Gujarat (`IN-GJ`)**
            - **Timezone**: `Asia/Kolkata`
            - **Currency**: `INR` (₹)
            - **Plans**:
              - *HTP-I*: High Tension (up to 500 kVA)
            - **Grid Zone**: `IN-WE` (Western Grid)
            """)
        with col_hp:
            st.markdown("""
            **🇮🇳 Himachal Pradesh (`IN-HP`)**
            - **Timezone**: `Asia/Kolkata`
            - **Currency**: `INR` (₹)
            - **Plans**:
              - *Large Industry - EHT*: Flat energy tariff (66 kV)
            - **Grid Zone**: `IN-NO` (Northern Grid)
            """)
        with col_wb:
            st.markdown("""
            **🇮🇳 West Bengal (`IN-WB`)**
            - **Timezone**: `Asia/Kolkata`
            - **Currency**: `INR` (₹)
            - **Plans**:
              - *Industries (Rate E-BT)*: Normal-TOD (11 kV)
            - **Grid Zone**: `IN-EA` (Eastern Grid)
            """)


# ── 6. KUBERNETES ────────────────────────────────────────────────────────────
with tabs[5]:
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


# ── 7. BASELINE VS GREENSHIFT IMPACT ─────────────────────────────────────────
with tabs[6]:
    st.markdown("### 📈 Baseline vs GreenShift Impact Analysis")
    target_job_id = st.selectbox("Select Scheduled Job", [j["job_id"] for j in all_jobs if j.get("status") in ("SCHEDULED", "QUEUED", "RUNNING", "COMPLETED")], key="impact_job_select")

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


# ── 8. AUDIT ─────────────────────────────────────────────────────────────────
with tabs[7]:
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


# ── 9. EXPORT ────────────────────────────────────────────────────────────────
with tabs[8]:
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
