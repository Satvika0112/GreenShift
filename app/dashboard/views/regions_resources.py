"""
GreenShift — Regions & Resources View.
"""

import streamlit as st
import pandas as pd
import plotly.express as px

from app.dashboard.api_client import fetch_regional_inventory, fetch_kubernetes_state, fetch_jobs, fetch_regional_tariffs
from app.dashboard.components import render_section_header, render_metric_card, render_health_card, render_status_badge


def render_regions_resources_view() -> None:
    """Render the multi-region grid and compute cluster resource view."""
    render_section_header("🌍 Regions & Compute Resources", "Inspect multi-regional grid zones, live cluster capacity, and local ToD tariff schedules")

    k8s_state = fetch_kubernetes_state()
    inventory = fetch_regional_inventory()
    jobs = fetch_jobs(limit=1000)

    # Count jobs per region
    region_job_counts = {}
    for j in jobs:
        r = j.get("region", "IN-TG")
        region_job_counts[r] = region_job_counts.get(r, 0) + 1

    regions_data = [
        {"id": "IN-TG", "name": "Telangana (IN-TG)", "zone": "IN-SO", "currency": "INR", "rate": "₹7.15 - ₹8.75", "intensity": 280.0, "status": "ONLINE"},
        {"id": "IN-GJ", "name": "Gujarat (IN-GJ)", "zone": "IN-WE", "currency": "INR", "rate": "₹3.40 - ₹4.45", "intensity": 360.0, "status": "ONLINE"},
        {"id": "IN-HP", "name": "Himachal Pradesh (IN-HP)", "zone": "IN-NO", "currency": "INR", "rate": "₹3.80 - ₹5.20", "intensity": 180.0, "status": "ONLINE"},
        {"id": "IN-WB", "name": "West Bengal (IN-WB)", "zone": "IN-EA", "currency": "INR", "rate": "₹4.45 - ₹10.95", "intensity": 440.0, "status": "ONLINE"},
        {"id": "US-CA", "name": "California (US-CA)", "zone": "US-CAL-CISO", "currency": "USD", "rate": "$0.058 - $0.177", "intensity": 220.0, "status": "ONLINE"},
        {"id": "US-TX", "name": "Texas (US-TX)", "zone": "US-TEX-ERCO", "currency": "USD", "rate": "$0.061 flat", "intensity": 310.0, "status": "ONLINE"},
        {"id": "US-NY", "name": "New York (US-NY)", "zone": "US-NY-NYIS", "currency": "USD", "rate": "$0.208 flat", "intensity": 240.0, "status": "ONLINE"},
        {"id": "SE", "name": "Sweden (SE)", "zone": "SE", "currency": "SEK", "rate": "0.034 SEK", "intensity": 45.0, "status": "ONLINE"},
        {"id": "AU-SA-Large", "name": "South Australia (AU-SA)", "zone": "AUS-SA", "currency": "AUD", "rate": "$0.03 - $0.32", "intensity": 160.0, "status": "ONLINE"},
    ]

    # Display region cards grid
    cols = st.columns(3)
    for idx, reg in enumerate(regions_data):
        c = cols[idx % 3]
        with c:
            j_cnt = region_job_counts.get(reg["id"], 0)
            st.markdown(
                f'<div class="gs-card" style="margin-bottom: 14px;">'
                f'<div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">'
                f'<span style="font-weight: 700; color: #FFFFFF; font-size: 1.05rem;">{reg["name"]}</span>'
                f'<span class="gs-badge green-badge">{reg["status"]}</span>'
                f'</div>'
                f'<div style="font-size: 0.8rem; color: #94A3B8; margin-bottom: 10px;">Zone: <code>{reg["zone"]}</code> | Currency: {reg["currency"]}</div>'
                f'<div style="display: flex; align-items: center; justify-content: space-between; border-top: 1px solid #0E383C; padding-top: 8px; font-size: 0.82rem;">'
                f'<div>⚡ Carbon: <strong style="color: #00E599;">{reg["intensity"]} gCO₂/kWh</strong></div>'
                f'<div>Workloads: <strong style="color: #FFFFFF;">{j_cnt}</strong></div>'
                f'</div>'
                f'<div style="font-size: 0.78rem; color: #64748B; margin-top: 4px;">Tariff: {reg["rate"]}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    # Detailed Region Inspector
    st.markdown("---")
    render_section_header("🔍 Regional Resource Inspector", "Inspect cluster capacity & time-of-day tariff profile")

    selected_inspect_region = st.selectbox("Select Region to Inspect", [r["id"] for r in regions_data])
    tariffs = fetch_regional_tariffs(selected_inspect_region)

    col_k8s, col_tar = st.columns([1, 1.4], gap="medium")

    with col_k8s:
        st.markdown("#### ☸️ Cluster Resource Capacity")
        free_cpu = k8s_state.get("free_cpu_cores", 8.4)
        free_ram = k8s_state.get("free_memory_gib", 2.7)
        total_nodes = k8s_state.get("node_count", 1)
        cluster_health = k8s_state.get("health", "HEALTHY")

        st.markdown(render_metric_card("Cluster Nodes", total_nodes, f"State: {cluster_health}", accent=True), unsafe_allow_html=True)
        st.markdown(render_metric_card("Free CPU Capacity", f"{free_cpu} cores", "Available for dispatch"), unsafe_allow_html=True)
        st.markdown(render_metric_card("Free Memory", f"{free_ram} GiB", "Available for dispatch"), unsafe_allow_html=True)

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
                plot_bgcolor="#081E21",
                paper_bgcolor="#081E21",
                margin=dict(l=10, r=10, t=10, b=10),
                height=260,
            )
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        else:
            st.info("Loading tariff profile...")
