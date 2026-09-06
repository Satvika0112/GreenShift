"""
GreenShift — Main Dashboard Overview View.
Renders enterprise aggregated metrics, carbon intensity curves, job distribution, health summary, and audit stream.
"""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from app.dashboard.api_client import (
    fetch_dashboard_summary,
    fetch_carbon_curve,
    fetch_current_carbon,
    fetch_system_health,
    fetch_audit_events,
    fetch_jobs,
)
from app.dashboard.components import render_metric_card, render_health_card, render_section_header, render_status_badge


def render_dashboard_overview(active_region: str = "IN-TG") -> None:
    """Render the primary GreenShift operational dashboard."""
    # 1. Fetch Real Backend Data
    summary = fetch_dashboard_summary()
    jobs_summary = summary.get("jobs", {})
    carbon_summary = summary.get("carbon", {})
    cost_summary = summary.get("cost", {})

    total_jobs = jobs_summary.get("total", 0)
    scheduled_jobs = jobs_summary.get("SCHEDULED", 0) + jobs_summary.get("APPROVED", 0) + jobs_summary.get("PENDING_APPROVAL", 0)
    running_jobs = jobs_summary.get("RUNNING", 0) + jobs_summary.get("QUEUED", 0)
    completed_jobs = jobs_summary.get("COMPLETED", 0)
    carbon_avoided_kg = carbon_summary.get("carbon_avoided_kg", 0.0)
    cost_saved_usd = cost_summary.get("cost_difference", 0.0)

    # Calculate percentages
    baseline_carbon = carbon_summary.get("baseline_emissions_kg", 0.0)
    carbon_reduction_pct = (
        round((carbon_avoided_kg / baseline_carbon * 100.0), 1)
        if baseline_carbon > 0 else 0.0
    )

    # 2. Top Metric Cards Grid
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(render_metric_card("Total Workloads", f"{total_jobs:,}", f"{completed_jobs} completed", accent=True), unsafe_allow_html=True)
    with c2:
        st.markdown(render_metric_card("Active / Scheduled", f"{scheduled_jobs + running_jobs:,}", f"{running_jobs} currently running"), unsafe_allow_html=True)
    with c3:
        st.markdown(render_metric_card("Carbon Avoided", f"{carbon_avoided_kg:,.2f} kg", f"{carbon_reduction_pct}% reduction vs baseline", accent=True), unsafe_allow_html=True)
    with c4:
        st.markdown(render_metric_card("Electricity Cost Saved", f"${cost_saved_usd:,.2f}", "ToD tariff optimized", accent=True), unsafe_allow_html=True)

    # 3. Middle Section: Carbon Intensity Curve + Jobs Distribution
    col_curve, col_status = st.columns([1.5, 1], gap="medium")

    with col_curve:
        st.markdown(
            f'<div class="gs-card-header" style="margin-bottom: 8px;">'
            f'<div>'
            f'<div class="gs-card-title">🌿 Carbon Intensity Forecast</div>'
            f'<div class="gs-card-subtitle">Live regional telemetry for {active_region} (Electricity Maps)</div>'
            f'</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        carbon_points = fetch_carbon_curve(active_region)
        if carbon_points:
            df_carbon = pd.DataFrame(carbon_points)
            df_carbon["timestamp"] = pd.to_datetime(df_carbon["timestamp"])
            fig = px.line(
                df_carbon,
                x="timestamp",
                y="carbon_gco2_kwh",
                labels={"timestamp": "Time (UTC)", "carbon_gco2_kwh": "gCO₂/kWh"},
                template="plotly_dark",
            )
            fig.update_traces(
                line=dict(color="#00E599", width=2.5),
                fill="tozeroy",
                fillcolor="rgba(0, 229, 153, 0.08)",
            )
            fig.update_layout(
                plot_bgcolor="#081E21",
                paper_bgcolor="#081E21",
                margin=dict(l=10, r=10, t=10, b=10),
                height=260,
                xaxis=dict(showgrid=True, gridcolor="#0E383C"),
                yaxis=dict(showgrid=True, gridcolor="#0E383C"),
            )
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        else:
            st.info(f"Connecting to carbon telemetry feed for {active_region}...")

    with col_status:
        st.markdown(
            '<div class="gs-card-header" style="margin-bottom: 8px;">'
            '<div>'
            '<div class="gs-card-title">📊 Workload Status Distribution</div>'
            '<div class="gs-card-subtitle">Real-time lifecycle state counts</div>'
            '</div>'
            '</div>',
            unsafe_allow_html=True,
        )

        status_items = [
            ("SUBMITTED", jobs_summary.get("SUBMITTED", 0)),
            ("PENDING_APPROVAL", jobs_summary.get("PENDING_APPROVAL", 0)),
            ("APPROVED", jobs_summary.get("APPROVED", 0)),
            ("SCHEDULED", jobs_summary.get("SCHEDULED", 0)),
            ("QUEUED", jobs_summary.get("QUEUED", 0)),
            ("RUNNING", jobs_summary.get("RUNNING", 0)),
            ("COMPLETED", jobs_summary.get("COMPLETED", 0)),
            ("DECLINED", jobs_summary.get("DECLINED", 0)),
            ("FAILED", jobs_summary.get("FAILED", 0)),
        ]

        status_rows_html = []
        for s_code, s_count in status_items:
            if s_count > 0 or s_code in ("PENDING_APPROVAL", "APPROVED", "RUNNING", "COMPLETED"):
                status_rows_html.append(
                    f'<div style="display: flex; align-items: center; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid #0E383C;">'
                    f'<div>{render_status_badge(s_code)}</div>'
                    f'<div style="font-weight: 700; color: #FFFFFF; font-family: \'JetBrains Mono\', monospace;">{s_count}</div>'
                    f'</div>'
                )

        st.markdown(
            f'<div class="gs-card" style="padding: 12px 16px;">{"".join(status_rows_html)}</div>',
            unsafe_allow_html=True,
        )

    # 4. Lower Section: Platform Health Summary + Recent Activity Audit
    col_health, col_audit = st.columns([1, 1.2], gap="medium")

    with col_health:
        st.markdown(
            '<div class="gs-card-header" style="margin-bottom: 8px;">'
            '<div>'
            '<div class="gs-card-title">🩺 Platform Health & Dependencies</div>'
            '<div class="gs-card-subtitle">Real-time health status probe (/health)</div>'
            '</div>'
            '</div>',
            unsafe_allow_html=True,
        )

        health_data = fetch_system_health()
        components = health_data.get("components", {})

        app_st = components.get("application", {}).get("status", "healthy")
        db_st = components.get("database", {}).get("status", "healthy")
        redis_st = components.get("redis", {}).get("status", "healthy")
        k8s_st = components.get("kubernetes", {}).get("status", "healthy")
        carbon_st = components.get("carbon_data", {}).get("status", "healthy")

        st.markdown(render_health_card("Application Server", app_st, "FastAPI core scheduler process", "⚙️"), unsafe_allow_html=True)
        st.markdown(render_health_card("PostgreSQL Database", db_st, "Primary relational persistence & constraints", "🗄️"), unsafe_allow_html=True)
        st.markdown(render_health_card("Redis Carbon Cache", redis_st, "Telemetry cache-aside & stampede lock", "⚡"), unsafe_allow_html=True)
        st.markdown(render_health_card("Kubernetes Cluster", k8s_st, "Batch workload dispatcher & state collector", "☸️"), unsafe_allow_html=True)
        st.markdown(render_health_card("Carbon Telemetry API", carbon_st, "Electricity Maps multi-tier resilience hierarchy", "🌿"), unsafe_allow_html=True)

    with col_audit:
        st.markdown(
            '<div class="gs-card-header" style="margin-bottom: 8px;">'
            '<div>'
            '<div class="gs-card-title">🔐 Recent Tamper-Evident Activity</div>'
            '<div class="gs-card-subtitle">Cryptographic SHA-256 trust ledger feed</div>'
            '</div>'
            '</div>',
            unsafe_allow_html=True,
        )

        audit_events = fetch_audit_events(limit=6)
        if audit_events:
            audit_rows_html = []
            for ev in audit_events:
                ev_type = ev.get("event_type", "EVENT")
                ts = ev.get("timestamp", "")[:19].replace("T", " ")
                job_id = ev.get("job_id", "")
                audit_rows_html.append(
                    f'<div style="padding: 8px 0; border-bottom: 1px solid #0E383C; font-size: 0.82rem;">'
                    f'<div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 2px;">'
                    f'<span style="color: #00E599; font-weight: 600; font-family: \'JetBrains Mono\', monospace;">{ev_type}</span>'
                    f'<span style="color: #64748B; font-size: 0.75rem;">{ts}</span>'
                    f'</div>'
                    f'<div style="color: #94A3B8;">Job: <code style="color: #E2E8F0;">{job_id}</code> | Seq: #{ev.get("sequence", 0)}</div>'
                    f'</div>'
                )
            st.markdown(
                f'<div class="gs-card" style="padding: 12px 16px;">{"".join(audit_rows_html)}</div>',
                unsafe_allow_html=True,
            )
        else:
            st.caption("No audit events recorded yet.")

