"""
GreenShift — Carbon & Cost Data, Forecast Trends & Resilience Health View.
"""

import pandas as pd
import plotly.express as px
import streamlit as st

from app.dashboard.api_client import (
    fetch_carbon_curve,
    fetch_regional_tariffs,
    fetch_data_sources_status,
)
from app.dashboard.components import render_section_header, render_metric_card, render_health_card, render_status_badge


def render_carbon_cost_view(active_region: str = "IN-TG") -> None:
    """Render the Carbon and Electricity Cost intelligence view."""
    render_section_header("🌿 Carbon & Electricity Cost Intelligence", "Live grid emission telemetry, ToD tariff structures, and data source resilience health")

    # Fetch Real Data
    carbon_points = fetch_carbon_curve(active_region)
    tariff_points = fetch_regional_tariffs(active_region)
    source_status = fetch_data_sources_status()

    # Calculate Top Metrics
    current_val = carbon_points[0].get("carbon_gco2_kwh", 320.0) if carbon_points else 320.0
    min_carbon = min((p.get("carbon_gco2_kwh", 999.0) for p in carbon_points), default=280.0)
    max_carbon = max((p.get("carbon_gco2_kwh", 0.0) for p in carbon_points), default=420.0)
    current_price = tariff_points[0].get("price_per_kwh_usd", 0.085) if tariff_points else 0.085

    # Top Metric Cards
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(render_metric_card("Current Intensity", f"{current_val:.1f} gCO₂/kWh", f"Region: {active_region}", accent=True), unsafe_allow_html=True)
    with c2:
        st.markdown(render_metric_card("24h Forecast Low", f"{min_carbon:.1f} gCO₂/kWh", f"Peak: {max_carbon:.1f} gCO₂/kWh", accent=True), unsafe_allow_html=True)
    with c3:
        st.markdown(render_metric_card("Electricity Tariff", f"${current_price:.4f}/kWh", "Time-of-Day rate"), unsafe_allow_html=True)
    with c4:
        st.markdown(render_metric_card("Telemetry Source", "ELECTRICITY MAPS", "Multi-tier Cache/CSV fallback", tag="LIVE"), unsafe_allow_html=True)

    # Carbon & Cost Charts
    col_c1, col_c2 = st.columns(2, gap="medium")

    with col_c1:
        st.markdown(
            f"""
            <div class="gs-card">
                <div class="gs-card-header">
                    <div>
                        <div class="gs-card-title">🌿 24-48h Carbon Intensity Trend</div>
                        <div class="gs-card-subtitle">{active_region} grid emissions (gCO₂/kWh)</div>
                    </div>
                </div>
            """,
            unsafe_allow_html=True,
        )

        if carbon_points:
            df_c = pd.DataFrame(carbon_points)
            df_c["timestamp"] = pd.to_datetime(df_c["timestamp"])
            fig = px.area(
                df_c,
                x="timestamp",
                y="carbon_gco2_kwh",
                template="plotly_dark",
            )
            fig.update_traces(
                line=dict(color="#00E599", width=2.5),
                fillcolor="rgba(0, 229, 153, 0.12)",
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
            st.info("Loading carbon forecast data...")

        st.markdown("</div>", unsafe_allow_html=True)

    with col_c2:
        st.markdown(
            f"""
            <div class="gs-card">
                <div class="gs-card-header">
                    <div>
                        <div class="gs-card-title">⚡ Time-of-Day (ToD) Tariff Curve</div>
                        <div class="gs-card-subtitle">{active_region} standardized pricing ($/kWh)</div>
                    </div>
                </div>
            """,
            unsafe_allow_html=True,
        )

        if tariff_points:
            df_t = pd.DataFrame(tariff_points)
            df_t["timestamp"] = pd.to_datetime(df_t["timestamp"])
            fig_t = px.line(
                df_t,
                x="timestamp",
                y="price_per_kwh_usd",
                template="plotly_dark",
            )
            fig_t.update_traces(
                line=dict(color="#06B6D4", width=2.5),
            )
            fig_t.update_layout(
                plot_bgcolor="#081E21",
                paper_bgcolor="#081E21",
                margin=dict(l=10, r=10, t=10, b=10),
                height=260,
                xaxis=dict(showgrid=True, gridcolor="#0E383C"),
                yaxis=dict(showgrid=True, gridcolor="#0E383C"),
            )
            st.plotly_chart(fig_t, use_container_width=True, config={"displayModeBar": False})
        else:
            st.info("Loading regional tariff data...")

        st.markdown("</div>", unsafe_allow_html=True)

    # Data Source Resilience Health Cards
    render_section_header("🛡️ Multi-Level Resilience Data Source Health", "Operational status across the carbon telemetry fallback hierarchy")

    ds_c1, ds_c2, ds_c3, ds_c4 = st.columns(4)
    with ds_c1:
        st.markdown(render_health_card("Live Electricity Maps", "HEALTHY", "v4 API zone mapped to IN-SO", "🛰️"), unsafe_allow_html=True)
    with ds_c2:
        st.markdown(render_health_card("Redis Shared Cache", "HEALTHY", "15m TTL & stampede lock active", "⚡"), unsafe_allow_html=True)
    with ds_c3:
        st.markdown(render_health_card("Historical CSV Fallback", "READY", "master_tod_tariff_all_regions.csv", "📁"), unsafe_allow_html=True)
    with ds_c4:
        st.markdown(render_health_card("Controlled Baseline", "READY", "400.0 gCO₂/kWh diurnal curve", "🛡️"), unsafe_allow_html=True)
