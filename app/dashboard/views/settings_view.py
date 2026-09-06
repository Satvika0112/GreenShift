"""
GreenShift — Platform Settings & Configuration View.
"""

import streamlit as st

from app.dashboard.components import render_section_header, render_metric_card


def render_settings_view() -> None:
    """Render the Platform Settings & Scheduling Engine Configuration view."""
    render_section_header("⚙️ Platform Settings & Configuration", "Configure default optimization parameters, regional preferences, and fallback baselines")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(render_metric_card("Optimization Mode", "CARBON_FIRST", "Cost as tie-breaker", accent=True), unsafe_allow_html=True)
    with c2:
        st.markdown(render_metric_card("Default Grid Region", "IN-TG", "Telangana, India"), unsafe_allow_html=True)
    with c3:
        st.markdown(render_metric_card("Fallback Baseline", "400.0 gCO₂/kWh", "Controlled diurnal shaping"), unsafe_allow_html=True)
    with c4:
        st.markdown(render_metric_card("Cache TTL", "900s", "15-minute strict refresh", tag="ACTIVE"), unsafe_allow_html=True)

    st.markdown("---")

    col_s1, col_s2 = st.columns(2, gap="large")

    with col_s1:
        st.markdown("#### 🎯 Scheduler Optimization Weights")
        st.selectbox("Optimization Strategy", ["CARBON_FIRST (Strict lowest emissions, secondary cost tie-breaker)"])
        st.slider("Carbon Abatement Priority Weight (%)", min_value=50, max_value=100, value=85)
        st.slider("Electricity Cost Weight (%)", min_value=0, max_value=50, value=15)
        st.number_input("Maximum Scheduling Delay (Hours)", min_value=1, max_value=72, value=24)
        st.checkbox("Enforce Strict SLA Compliance", value=True)

    with col_s2:
        st.markdown("#### 🛡️ Data Resilience & Outage Protection")
        st.number_input("Controlled Carbon Fallback Baseline (gCO₂/kWh)", min_value=50.0, max_value=1000.0, value=400.0, step=10.0)
        st.number_input("Redis Cache TTL (Seconds)", min_value=60, max_value=3600, value=900)
        st.text_input("Master Regional Tariff CSV Path", value="data/master_tod_tariff_all_regions.csv", disabled=True)
        st.text_input("Electricity Maps API Endpoint", value="https://api.electricitymap.org/v4", disabled=True)

    st.markdown("---")
    if st.button("💾 Save Platform Settings", type="primary"):
        st.success("Platform settings updated successfully.")
