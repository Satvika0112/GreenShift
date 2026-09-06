"""
GreenShift — Dedicated System Health & Production Readiness View.
"""

import streamlit as st
import pandas as pd

from app.dashboard.api_client import fetch_system_health, fetch_system_ready, fetch_system_live
from app.dashboard.components import render_section_header, render_metric_card, render_health_card, render_status_badge


def render_system_health_view() -> None:
    """Render the System Health, Liveness, and Readiness Probe monitoring view."""
    render_section_header("🩺 System Health & Production Readiness", "Real-time Kubernetes liveness/readiness probes and dependency health indicators")

    # Fetch Real Endpoints
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

    # Top Metric Overview
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

    # Dependency Cards Grid
    render_section_header("🔌 Core Dependency Status Probes", "Monitored subsystems determining application readiness and degraded operation")

    col_d1, col_d2 = st.columns(2, gap="medium")

    with col_d1:
        st.markdown(
            render_health_card(
                "Application Process (Liveness)",
                app_comp.get("status", "healthy"),
                "GET /live — Pure process check without external dependencies",
                "⚙️",
            ),
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
                f"Distributed cache & stampede lock. Status: {redis_comp.get('status')} ({redis_comp.get('reason', 'Ping OK')})",
                "⚡",
            ),
            unsafe_allow_html=True,
        )

    with col_d2:
        st.markdown(
            render_health_card(
                "Kubernetes Cluster Connectivity",
                k8s_comp.get("status", "healthy"),
                f"Batch API & state collector reachability. Mode: {k8s_comp.get('status')} ({k8s_comp.get('reason', 'API reachable')})",
                "☸️",
            ),
            unsafe_allow_html=True,
        )

        carbon_mode = carbon_comp.get("mode", carbon_comp.get("status", "healthy"))
        st.markdown(
            render_health_card(
                "Carbon Data Telemetry Hierarchy",
                carbon_comp.get("status", "healthy"),
                f"Active mode: {carbon_mode.upper()} — Electricity Maps API / Cache / CSV / Controlled fallback",
                "🌿",
            ),
            unsafe_allow_html=True,
        )

    # Readiness Policy Guide
    st.markdown(
        '<div class="gs-card" style="margin-top: 16px;">'
        '<div style="font-weight: 700; color: #FFFFFF; font-size: 1.0rem; margin-bottom: 8px;">🛡️ Production Readiness Behavior Rules:</div>'
        '<div style="font-size: 0.85rem; color: #94A3B8; line-height: 1.6;">'
        '• <strong>Database Down:</strong> Returns <code>HTTP 503 (not_ready)</code> to immediately withdraw instance from Kubernetes load balancing.<br>'
        '• <strong>Redis Offline:</strong> Returns <code>HTTP 200 (ready / overall_state: degraded)</code>; requests safely bypass cache.<br>'
        '• <strong>Kubernetes API Offline:</strong> Returns <code>HTTP 200 (ready / overall_state: degraded)</code>; local mock dispatch enabled.<br>'
        '• <strong>Carbon API Down:</strong> Returns <code>HTTP 200 (ready / carbon_data: fallback)</code>; historical CSV or diurnal curve activated.'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )
