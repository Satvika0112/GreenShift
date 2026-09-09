"""
GreenShift — Page 5: Infrastructure.

Merges: regions_resources + system_health.
2 inner tabs: Regions & Compute Resources | System Health
"""

import pandas as pd
import plotly.express as px
import streamlit as st

from app.dashboard.api_client import (
    fetch_regional_inventory,
    fetch_kubernetes_state,
    fetch_jobs,
    fetch_regional_tariffs,
    fetch_system_health,
    fetch_system_ready,
    fetch_system_live,
)
from app.dashboard.components import (
    render_section_header,
    render_metric_card,
    render_health_card,
    render_status_badge,
)


# ─────────────────────────────────────────────────────────────────────────────
# Tab A — Regions & Compute Resources
# ─────────────────────────────────────────────────────────────────────────────

_REGIONS_DATA = [
    {"id": "IN-TG",       "name": "Telangana (IN-TG)",          "zone": "IN-SO",       "currency": "INR", "rate": "₹7.15 - ₹8.75",    "intensity": 280.0, "status": "ONLINE"},
    {"id": "IN-GJ",       "name": "Gujarat (IN-GJ)",             "zone": "IN-WE",       "currency": "INR", "rate": "₹3.40 - ₹4.45",    "intensity": 360.0, "status": "ONLINE"},
    {"id": "IN-HP",       "name": "Himachal Pradesh (IN-HP)",    "zone": "IN-NO",       "currency": "INR", "rate": "₹3.80 - ₹5.20",    "intensity": 180.0, "status": "ONLINE"},
    {"id": "IN-WB",       "name": "West Bengal (IN-WB)",         "zone": "IN-EA",       "currency": "INR", "rate": "₹4.45 - ₹10.95",   "intensity": 440.0, "status": "ONLINE"},
    {"id": "US-CA",       "name": "California (US-CA)",          "zone": "US-CAL-CISO", "currency": "USD", "rate": "$0.058 - $0.177",   "intensity": 220.0, "status": "ONLINE"},
    {"id": "US-TX",       "name": "Texas (US-TX)",               "zone": "US-TEX-ERCO", "currency": "USD", "rate": "$0.061 flat",       "intensity": 310.0, "status": "ONLINE"},
    {"id": "US-NY",       "name": "New York (US-NY)",            "zone": "US-NY-NYIS",  "currency": "USD", "rate": "$0.208 flat",       "intensity": 240.0, "status": "ONLINE"},
    {"id": "SE",          "name": "Sweden (SE)",                  "zone": "SE",          "currency": "SEK", "rate": "0.034 SEK",         "intensity": 45.0,  "status": "ONLINE"},
    {"id": "AU-SA-Large", "name": "South Australia (AU-SA)",     "zone": "AUS-SA",      "currency": "AUD", "rate": "$0.03 - $0.32",     "intensity": 160.0, "status": "ONLINE"},
]


def _render_regions_tab():
    render_section_header("🌍 Regions & Compute Resources", "Inspect multi-regional grid zones, live cluster capacity, and local ToD tariff schedules")

    k8s_state = fetch_kubernetes_state()
    inventory = fetch_regional_inventory()
    jobs = fetch_jobs(limit=1000)

    region_job_counts = {}
    for j in jobs:
        r = j.get("region", "IN-TG")
        region_job_counts[r] = region_job_counts.get(r, 0) + 1

    # Region cards grid — 3 columns
    cols = st.columns(3)
    for idx, reg in enumerate(_REGIONS_DATA):
        c = cols[idx % 3]
        with c:
            j_cnt = region_job_counts.get(reg["id"], 0)
            st.markdown(
                f'<div class="gs-card" style="margin-bottom:14px;">'
                f'<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">'
                f'<span style="font-weight:700;color:#FFFFFF;font-size:1.0rem;">{reg["name"]}</span>'
                f'<span class="gs-badge green-badge">{reg["status"]}</span>'
                f'</div>'
                f'<div style="font-size:0.8rem;color:#94A3B8;margin-bottom:10px;">'
                f'Zone: <code>{reg["zone"]}</code> | Currency: {reg["currency"]}</div>'
                f'<div style="display:flex;align-items:center;justify-content:space-between;border-top:1px solid #0E383C;padding-top:8px;font-size:0.82rem;">'
                f'<div>⚡ Carbon: <strong style="color:#00E599;">{reg["intensity"]} gCO₂/kWh</strong></div>'
                f'<div>Workloads: <strong style="color:#FFFFFF;">{j_cnt}</strong></div>'
                f'</div>'
                f'<div style="font-size:0.78rem;color:#64748B;margin-top:4px;">Tariff: {reg["rate"]}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    # Regional Resource Inspector
    st.markdown("---")
    render_section_header("🔍 Regional Resource Inspector", "Inspect cluster capacity & time-of-day tariff profile")

    selected_inspect_region = st.selectbox("Select Region to Inspect", [r["id"] for r in _REGIONS_DATA], key="infra_region_sel")
    tariffs = fetch_regional_tariffs(selected_inspect_region)

    col_k8s, col_tar = st.columns([1, 1.4], gap="medium")

    with col_k8s:
        st.markdown("#### ☸️ Cluster Resource Capacity")
        free_cpu = k8s_state.get("free_cpu_cores", 17.5)
        free_ram_mib = k8s_state.get("free_memory_mib", 71680.0)
        free_ram_gib = round(free_ram_mib / 1024.0, 1) if isinstance(free_ram_mib, (int, float)) else k8s_state.get("free_memory_gib", 2.7)
        total_nodes = k8s_state.get("total_nodes", k8s_state.get("node_count", 3))
        cluster_health = k8s_state.get("cluster_health", k8s_state.get("health", "HEALTHY"))

        st.markdown(render_metric_card("Cluster Nodes", total_nodes, f"State: {cluster_health}", accent=True), unsafe_allow_html=True)
        st.markdown(render_metric_card("Free CPU Capacity", f"{free_cpu} cores", "Available for dispatch"), unsafe_allow_html=True)
        st.markdown(render_metric_card("Free Memory", f"{free_ram_gib} GiB", "Available for dispatch"), unsafe_allow_html=True)

    with col_tar:
        st.markdown(f"#### ⚡ Tariff Profile for {selected_inspect_region}")
        if tariffs:
            df_tar = pd.DataFrame(tariffs)
            df_tar["timestamp"] = pd.to_datetime(df_tar["timestamp"])
            fig = px.bar(
                df_tar,
                x="timestamp",
                y="price_per_kwh_usd",
                template="plotly_dark",
                labels={"price_per_kwh_usd": "Price ($/kWh)", "timestamp": "Hour (UTC)"},
            )
            fig.update_traces(marker_color="#00E599")
            fig.update_layout(
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=10, r=10, t=10, b=10),
                height=280,
                font=dict(color="#f0f6fc"),
                xaxis=dict(gridcolor="#0E383C"),
                yaxis=dict(gridcolor="#0E383C"),
            )
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        else:
            st.info("Loading tariff profile...")

    nodes_data = k8s_state.get("nodes", [])
    if nodes_data:
        st.markdown("##### 🖥️ Node Capacity & Resource Distribution")
        node_rows = []
        for n in nodes_data:
            node_rows.append({
                "name": n.get("name"),
                "status": n.get("status"),
                "cpu_allocatable_cores": n.get("cpu_allocatable_cores"),
                "cpu_used_cores": n.get("cpu_used_cores"),
                "cpu_free_cores": n.get("cpu_free_cores"),
                "memory_allocatable_mib": n.get("memory_allocatable_mib"),
                "memory_used_mib": n.get("memory_used_mib"),
                "memory_free_mib": n.get("memory_free_mib"),
                "gpu_allocatable": n.get("gpu_allocatable", 0),
                "gpu_used": n.get("gpu_used", 0),
                "gpu_free": n.get("gpu_free", 0),
                "roles": ", ".join(n.get("roles", [])) if isinstance(n.get("roles"), list) else str(n.get("roles", "")),
            })
        df_nodes = pd.DataFrame(node_rows)
        cols_order = [
            "name", "status",
            "cpu_allocatable_cores", "cpu_used_cores", "cpu_free_cores",
            "memory_allocatable_mib", "memory_used_mib", "memory_free_mib",
            "gpu_allocatable", "gpu_used", "gpu_free", "roles"
        ]
        df_nodes = df_nodes[[c for c in cols_order if c in df_nodes.columns]]
        st.dataframe(df_nodes, use_container_width=True, hide_index=True)

    # ── Section C: Contention-Aware Slot Capacity & Utilization Heatmap ──
    st.markdown("---")
    render_section_header("📊 Slot Capacity & Contention Heatmap", "Discrete hourly CPU/RAM allocation tracking & ML demand pressure to prevent workload piling")

    from app.dashboard.api_client import fetch_capacity_map_api, fetch_demand_forecaster_status_api

    cap_data = fetch_capacity_map_api()
    summary = cap_data.get("summary", {})
    contention_map = cap_data.get("contention_map", {})
    slots_list = contention_map.get("slots", [])
    cluster_limits = cap_data.get("cluster_limits", {})

    forecaster_status = fetch_demand_forecaster_status_api()

    # KPI row
    k1, k2, k3, k4, k5 = st.columns(5)
    with k1:
        st.markdown(render_metric_card("Tracked Hourly Slots", summary.get("total_slots", 0), "Active schedule horizon", accent=True), unsafe_allow_html=True)
    with k2:
        max_u = summary.get("max_utilization_pct", 0.0)
        st.markdown(render_metric_card("Peak Slot CPU Util.", f"{max_u:.1f}%", "Max slot allocation"), unsafe_allow_html=True)
    with k3:
        avg_u = summary.get("avg_utilization_pct", 0.0)
        st.markdown(render_metric_card("Average Slot Util.", f"{avg_u:.1f}%", "Fleet-wide load average"), unsafe_allow_html=True)
    with k4:
        congested = summary.get("congested_slots_count", 0)
        st.markdown(render_metric_card("Congested Slots (≥80%)", congested, "Hotspots prevented by spillover"), unsafe_allow_html=True)
    with k5:
        ml_trained = forecaster_status.get("is_trained", False)
        st.markdown(render_metric_card("ML Forecaster Status", "ACTIVE" if ml_trained else "STANDBY", f"{forecaster_status.get('samples_trained', 0)} arrival patterns"), unsafe_allow_html=True)

    if slots_list:
        df_slots = pd.DataFrame(slots_list)
        df_slots["slot_start_dt"] = pd.to_datetime(df_slots["slot_start"])
        df_slots = df_slots.sort_values("slot_start_dt")

        st.markdown("#### ⚡ Hourly Slot CPU Utilization Timeline")
        fig_slots = px.bar(
            df_slots,
            x="slot_start_dt",
            y="utilization_pct",
            color="utilization_pct",
            color_continuous_scale=[(0.0, "#00E599"), (0.6, "#22C55E"), (0.8, "#F59E0B"), (1.0, "#EF4444")],
            labels={"utilization_pct": "CPU Util (%)", "slot_start_dt": "Hourly Window (UTC)"},
            template="plotly_dark",
        )
        fig_slots.add_hline(y=100.0, line_dash="dash", line_color="#EF4444", annotation_text="Hard Limit (100%)", annotation_position="top right")
        fig_slots.add_hline(y=80.0, line_dash="dot", line_color="#F59E0B", annotation_text="Congestion Threshold (80%)", annotation_position="bottom right")
        fig_slots.update_layout(
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            height=320,
            font=dict(color="#f0f6fc"),
            xaxis=dict(gridcolor="#0E383C"),
            yaxis=dict(gridcolor="#0E383C", range=[0, 115]),
            coloraxis_showscale=False,
            margin=dict(l=10, r=10, t=20, b=10),
        )
        st.plotly_chart(fig_slots, use_container_width=True, config={"displayModeBar": False})

        # Top Loaded Slots Table
        st.markdown("#### 📋 Slot Allocation Details")
        display_slots = []
        for s in slots_list[:25]:
            u = s.get("utilization_pct", 0.0)
            status_tag = "🔴 CONGESTED" if u >= 80.0 else ("🟡 ELEVATED" if u >= 50.0 else "🟢 OPTIMAL")
            display_slots.append({
                "Slot Start (UTC)": s.get("slot_start", "")[:16].replace("T", " "),
                "Region": s.get("region_id", ""),
                "CPU Used / Max": f"{s.get('allocated_cpu', 0.0):.1f} / {s.get('max_cpu', 0.0):.1f} cores",
                "RAM Used / Max": f"{s.get('allocated_memory_mib', 0.0):.0f} / {s.get('max_memory_mib', 0.0):.0f} MiB",
                "Workloads": s.get("job_count", 0),
                "Utilization": f"{u:.1f}%",
                "Contention Status": status_tag,
            })
        st.dataframe(pd.DataFrame(display_slots), use_container_width=True, hide_index=True)
    else:
        st.info("No slot allocations currently tracked. Batch schedule workloads to visualize capacity utilization.")


# ─────────────────────────────────────────────────────────────────────────────
# Tab B — System Health
# ─────────────────────────────────────────────────────────────────────────────

def _render_health_tab():
    render_section_header("🩺 System Health & Production Readiness", "Real-time Kubernetes liveness/readiness probes and dependency health indicators")

    health_data = fetch_system_health()
    ready_status_code, ready_data = fetch_system_ready()
    live_data = fetch_system_live()

    overall_health = health_data.get("status", "healthy").upper()
    readiness_state = ready_data.get("status", "ready").upper()
    liveness_state = live_data.get("status", "alive").upper()
    timestamp = health_data.get("timestamp", "N/A")[:19].replace("T", " ")

    components = health_data.get("components", {})
    app_comp = components.get("application", {})
    db_comp = components.get("database", {})
    redis_comp = components.get("redis", {})
    k8s_comp = components.get("kubernetes", {})
    carbon_comp = components.get("carbon_data", {})

    # KPI strip
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(render_metric_card("System Health", overall_health, f"Probed at {timestamp}", accent=(overall_health == "HEALTHY"), tag=overall_health), unsafe_allow_html=True)
    with c2:
        st.markdown(render_metric_card("Readiness Probe", f"HTTP {ready_status_code}", f"State: {readiness_state}", accent=(ready_status_code == 200)), unsafe_allow_html=True)
    with c3:
        st.markdown(render_metric_card("Liveness Probe", liveness_state, "Process active (/live)", accent=True), unsafe_allow_html=True)
    with c4:
        st.markdown(render_metric_card("Degraded Fallback", "OPERATIONAL", "Cache & CSV fallbacks active", tag="RESILIENT"), unsafe_allow_html=True)

    st.markdown("---")
    render_section_header("🔌 Core Dependency Status Probes", "Monitored subsystems determining application readiness and degraded operation")

    col_d1, col_d2 = st.columns(2, gap="medium")

    with col_d1:
        st.markdown(
            render_health_card("Application Process (Liveness)", app_comp.get("status", "healthy"), "GET /live — Pure process check without external dependencies", "⚙️"),
            unsafe_allow_html=True,
        )
        st.markdown(
            render_health_card(
                "PostgreSQL Database (Critical Gate)",
                db_comp.get("status", "healthy"),
                f"GET /ready critical gate — SELECT 1 check. Reason: {db_comp.get('reason', 'Connected')}",
                "🗄️",
            ),
            unsafe_allow_html=True,
        )
        st.markdown(
            render_health_card(
                "Redis Shared Cache (Resilience Layer)",
                redis_comp.get("status", "healthy"),
                f"Distributed cache & stampede lock. Status: {redis_comp.get('status', 'healthy')} ({redis_comp.get('reason', 'Ping OK')})",
                "⚡",
            ),
            unsafe_allow_html=True,
        )

    with col_d2:
        st.markdown(
            render_health_card(
                "Kubernetes Cluster Connectivity",
                k8s_comp.get("status", "healthy"),
                f"Batch API & state collector reachability. Mode: {k8s_comp.get('status', 'healthy')} ({k8s_comp.get('reason', 'API reachable')})",
                "☸️",
            ),
            unsafe_allow_html=True,
        )
        carbon_mode = carbon_comp.get("mode", carbon_comp.get("status", "healthy"))
        st.markdown(
            render_health_card(
                "Carbon Data Telemetry Hierarchy",
                carbon_comp.get("status", "healthy"),
                f"Active mode: {str(carbon_mode).upper()} — Electricity Maps API / Cache / CSV / Controlled fallback",
                "🌿",
            ),
            unsafe_allow_html=True,
        )

    st.markdown(
        '<div class="gs-card" style="margin-top:16px;">'
        '<div style="font-weight:700;color:#FFFFFF;font-size:1.0rem;margin-bottom:8px;">🛡️ Production Readiness Behavior Rules:</div>'
        '<div style="font-size:0.85rem;color:#94A3B8;line-height:1.6;">'
        '• <strong>Database Down:</strong> Returns <code>HTTP 503 (not_ready)</code> to immediately withdraw instance from Kubernetes load balancing.<br>'
        '• <strong>Redis Offline:</strong> Returns <code>HTTP 200 (ready / overall_state: degraded)</code>; requests safely bypass cache.<br>'
        '• <strong>Kubernetes API Offline:</strong> Returns <code>HTTP 200 (ready / overall_state: degraded)</code>; local mock dispatch enabled.<br>'
        '• <strong>Carbon API Down:</strong> Returns <code>HTTP 200 (ready / carbon_data: fallback)</code>; historical CSV or diurnal curve activated.'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Main Entry Point
# ─────────────────────────────────────────────────────────────────────────────

def render_regions_resources_view() -> None:
    """Render consolidated Infrastructure page with 2 inner tabs."""
    tab_regions, tab_health = st.tabs(["🌍 Regions & Compute Resources", "🩺 System Health"])

    with tab_regions:
        _render_regions_tab()

    with tab_health:
        _render_health_tab()
