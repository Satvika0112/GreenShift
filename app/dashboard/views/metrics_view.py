"""
GreenShift — Operational Metrics & Prometheus Observability View.
"""

import streamlit as st
import pandas as pd

from app.dashboard.api_client import fetch_metrics_summary, fetch_prometheus_metrics
from app.dashboard.components import render_section_header, render_metric_card


def render_metrics_view() -> None:
    """Render the operational metrics summary and Prometheus scraping view."""
    render_section_header("📈 Operational Metrics & Observability", "Real-time thread-safe metrics abstraction and OpenMetrics / Prometheus exposition")

    metrics_data = fetch_metrics_summary()

    sch = metrics_data.get("scheduler", {})
    carbon = metrics_data.get("carbon_api", {})
    appr = metrics_data.get("approval", {})
    disp = metrics_data.get("dispatch", {})

    # Top Metric Overview
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(render_metric_card("Scheduler Requests", f"{sch.get('scheduling_requests', 0):,}", f"{sch.get('average_scheduling_time_ms', 0.0):.2f} ms avg", accent=True), unsafe_allow_html=True)
    with c2:
        st.markdown(render_metric_card("Carbon Cache Hits", f"{carbon.get('cache_hits', 0):,}", f"{carbon.get('cache_hit_ratio_pct', 0.0):.1f}% hit ratio", accent=True), unsafe_allow_html=True)
    with c3:
        st.markdown(render_metric_card("Approvals Processed", f"{appr.get('approvals', 0) + appr.get('declines', 0):,}", f"{appr.get('pending_approvals', 0)} pending"), unsafe_allow_html=True)
    with c4:
        st.markdown(render_metric_card("K8s Dispatches", f"{disp.get('successful_dispatches', 0):,}", f"{disp.get('blocked_dispatches', 0)} blocked by gate"), unsafe_allow_html=True)

    tab_summary, tab_prom = st.tabs(["📊 Subsystem Metrics", "📋 Prometheus Exposition"])

    with tab_summary:
        col_m1, col_m2 = st.columns(2, gap="medium")

        with col_m1:
            # Scheduler Metrics
            st.markdown(
                f'<div class="gs-card">'
                f'<div class="gs-card-title" style="margin-bottom: 12px;">⚙️ Scheduler Engine Metrics</div>'
                f'<div style="font-size: 0.85rem; color: #94A3B8; line-height: 1.8;">'
                f'• <strong>Total Evaluated Requests:</strong> <span style="color: #FFFFFF;">{sch.get("scheduling_requests", 0)}</span><br>'
                f'• <strong>Successful Optimizations:</strong> <span style="color: #00E599;">{sch.get("successful_schedules", 0)}</span><br>'
                f'• <strong>Infeasible Rejections:</strong> <span style="color: #EF4444;">{sch.get("infeasible_schedules", 0)}</span><br>'
                f'• <strong>Average Optimization Latency:</strong> <span style="color: #06B6D4;">{sch.get("average_scheduling_time_ms", 0.0):.2f} ms</span><br>'
                f'• <strong>Total Computation Time:</strong> <span style="color: #FFFFFF;">{sch.get("total_scheduling_time_seconds", 0.0):.4f}s</span>'
                f'</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

            # Approvals Metrics
            st.markdown(
                f'<div class="gs-card">'
                f'<div class="gs-card-title" style="margin-bottom: 12px;">🛡️ Approval Gate Metrics</div>'
                f'<div style="font-size: 0.85rem; color: #94A3B8; line-height: 1.8;">'
                f'• <strong>Pending Workloads:</strong> <span style="color: #F59E0B;">{appr.get("pending_approvals", 0)}</span><br>'
                f'• <strong>Approvals Granted:</strong> <span style="color: #00E599;">{appr.get("approvals", 0)}</span><br>'
                f'• <strong>Schedules Declined:</strong> <span style="color: #EF4444;">{appr.get("declines", 0)}</span>'
                f'</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

        with col_m2:
            # Carbon API & Cache Metrics
            st.markdown(
                f'<div class="gs-card">'
                f'<div class="gs-card-title" style="margin-bottom: 12px;">🌿 Carbon Telemetry & Cache Metrics</div>'
                f'<div style="font-size: 0.85rem; color: #94A3B8; line-height: 1.8;">'
                f'• <strong>Cache Hits:</strong> <span style="color: #00E599;">{carbon.get("cache_hits", 0)}</span><br>'
                f'• <strong>Cache Misses:</strong> <span style="color: #94A3B8;">{carbon.get("cache_misses", 0)}</span><br>'
                f'• <strong>Hit Ratio:</strong> <span style="color: #00E599;">{carbon.get("cache_hit_ratio_pct", 0.0):.1f}%</span><br>'
                f'• <strong>Redis Outages / Degraded Events:</strong> <span style="color: #F59E0B;">{carbon.get("redis_unavailable_events", 0)}</span><br>'
                f'• <strong>Fallback Invocations (CSV/Baseline):</strong> <span style="color: #06B6D4;">{carbon.get("api_fallback_usage", 0)}</span>'
                f'</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

            # Dispatch Metrics
            st.markdown(
                f'<div class="gs-card">'
                f'<div class="gs-card-title" style="margin-bottom: 12px;">☸️ Kubernetes Dispatch Metrics</div>'
                f'<div style="font-size: 0.85rem; color: #94A3B8; line-height: 1.8;">'
                f'• <strong>Dispatch Attempts:</strong> <span style="color: #FFFFFF;">{disp.get("dispatch_attempts", 0)}</span><br>'
                f'• <strong>Successful Pod Dispatches:</strong> <span style="color: #00E599;">{disp.get("successful_dispatches", 0)}</span><br>'
                f'• <strong>Blocked by Policy / Unapproved:</strong> <span style="color: #F59E0B;">{disp.get("blocked_dispatches", 0)}</span><br>'
                f'• <strong>Execution Failures:</strong> <span style="color: #EF4444;">{disp.get("failed_dispatches", 0)}</span>'
                f'</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    with tab_prom:
        st.markdown("#### Prometheus Text Exposition Output (`GET /metrics`)")
        st.caption("Standard OpenMetrics format ready for Prometheus scraping at `/metrics` or `/api/v1/metrics`.")
        prom_raw = fetch_prometheus_metrics()
        st.code(prom_raw if prom_raw else "# No metrics exposed yet", language="promql")
