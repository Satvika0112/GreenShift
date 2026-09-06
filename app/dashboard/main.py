"""
GreenShift — Enterprise Carbon & Cost-Aware Scheduling Platform UI.

Main Entry Point for the Streamlit Enterprise Dashboard.
"""

import os
import sys
from pathlib import Path

# Ensure project root is present in sys.path for absolute imports
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit as st

from app.dashboard.styles import ENTERPRISE_CSS
from app.dashboard.api_client import (
    approve_job_api,
    decline_job_api,
    dispatch_job_api,
    fetch_jobs,
    fetch_job_detail,
    fetch_pending_approvals,
    fetch_system_health,
)
from app.dashboard.components import render_status_badge, render_section_header
from app.shared.auth import create_access_token

# Import Views
from app.dashboard.views.login import render_login_view
from app.dashboard.views.dashboard_overview import render_dashboard_overview
from app.dashboard.views.organizations import render_organizations_view
from app.dashboard.views.workloads import render_workloads_view
from app.dashboard.views.submit_workload import render_submit_workload_view
from app.dashboard.views.users_access import render_users_access_view
from app.dashboard.views.scheduling_engine import render_scheduling_engine_view
from app.dashboard.views.job_monitoring import render_job_monitoring_view
from app.dashboard.views.carbon_cost import render_carbon_cost_view
from app.dashboard.views.regions_resources import render_regions_resources_view
from app.dashboard.views.approvals import render_approvals_view
from app.dashboard.views.audit_trust import render_audit_trust_view
from app.dashboard.views.alerts_incidents import render_alerts_incidents_view
from app.dashboard.views.reports import render_reports_view
from app.dashboard.views.system_health import render_system_health_view
from app.dashboard.views.metrics_view import render_metrics_view
from app.dashboard.views.settings_view import render_settings_view

# ─────────────────────────────────────────────────────────────────────────────
# 1. Page Configuration & Theme Injection
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="GreenShift — Enterprise Carbon Scheduler",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Inject custom enterprise dark theme CSS
st.markdown(ENTERPRISE_CSS, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Session State Initialization
# ─────────────────────────────────────────────────────────────────────────────

if "auth_token" not in st.session_state:
    st.session_state["auth_token"] = create_access_token(user_id=1, username="admin", role="ADMIN")
if "user_role" not in st.session_state:
    st.session_state["user_role"] = "ADMIN"
if "username" not in st.session_state:
    st.session_state["username"] = "admin"
if "team_id" not in st.session_state:
    st.session_state["team_id"] = None
if "active_region" not in st.session_state:
    st.session_state["active_region"] = "IN-TG"
if "is_authenticated" not in st.session_state:
    st.session_state["is_authenticated"] = True


# ─────────────────────────────────────────────────────────────────────────────
# 3. Top Bar Header
# ─────────────────────────────────────────────────────────────────────────────

top_col_brand, top_col_reg, top_col_user, top_col_btn = st.columns([1.5, 1.2, 1.2, 0.6])

with top_col_brand:
    st.markdown(
        """
        <div style="display: flex; align-items: center; gap: 10px; padding: 4px 0;">
            <span style="font-size: 1.6rem;">🌿</span>
            <div>
                <div style="font-size: 1.15rem; font-weight: 800; color: #FFFFFF; letter-spacing: -0.02em;">GreenShift</div>
                <div style="font-size: 0.72rem; color: #94A3B8; margin-top: -2px;">Enterprise Carbon-Aware Scheduler</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with top_col_reg:
    region_choices = ["IN-TG", "IN-GJ", "IN-HP", "IN-WB", "US-CA", "US-TX", "US-NY", "SE", "AU-SA-Large", "AU-SA-Small"]
    sel_reg = st.selectbox("Active Grid Region", region_choices, index=region_choices.index(st.session_state.get("active_region", "IN-TG")), label_visibility="collapsed")
    st.session_state["active_region"] = sel_reg

with top_col_user:
    curr_role = st.session_state.get("user_role", "ADMIN")
    curr_user = st.session_state.get("username", "admin")
    st.markdown(
        f"""
        <div style="display: flex; align-items: center; justify-content: flex-end; gap: 8px; padding-top: 6px;">
            <span class="gs-badge green-badge">{curr_role}</span>
            <span style="font-size: 0.85rem; font-weight: 600; color: #FFFFFF;">{curr_user}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

with top_col_btn:
    if st.button("⟳ Refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

st.markdown("<hr style='border-color: #0E383C; margin: 8px 0 20px 0;'>", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Sidebar Navigation
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown(
        """
        <div style="padding: 12px 0 16px 0; border-bottom: 1px solid #0E383C; margin-bottom: 14px;">
            <div style="display: flex; align-items: center; gap: 8px;">
                <span style="font-size: 1.3rem;">🌿</span>
                <span style="font-size: 1.1rem; font-weight: 800; color: #FFFFFF;">GreenShift</span>
            </div>
            <div style="font-size: 0.72rem; color: #00E599; font-weight: 600; margin-top: 2px;">● CLUSTER ONLINE</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    nav_options = [
        # PRIMARY OPERATIONS
        "📊 Dashboard",
        "📋 Workloads",
        "➕ Submit Workload",
        "⚙️ Scheduling Engine",
        "🖥️ Job Monitoring",
        # SUSTAINABILITY
        "🌿 Carbon & Cost Data",
        "🌍 Regions & Resources",
        # GOVERNANCE
        "🛡️ Approvals",
        "🔐 Audit & Trust",
        "⚠️ Alerts & Incidents",
        # OPERATIONS
        "🩺 System Health",
        "📈 Metrics & Observability",
        # ADMINISTRATION
        "🏢 Organizations",
        "👥 Users & Access",
        "📑 Reports",
        "⚙️ Settings",
        "🔑 Switch Account / Login",
    ]

    selected_nav = st.radio("NAVIGATION", nav_options, index=0, label_visibility="collapsed")

    st.markdown("<div style='margin-top: 24px; padding-top: 14px; border-top: 1px solid #0E383C;'>", unsafe_allow_html=True)
    st.caption("Active User Persona Switcher")
    persona_quick = st.selectbox(
        "Quick Persona Switch",
        ["ADMIN (Full Access)", "TEAM_LEAD (team_alpha)", "TEAM_LEAD (team_beta)", "OPERATOR (Execution)", "VIEWER (Read-Only)"],
        index=0,
        label_visibility="collapsed",
    )

    if "ADMIN" in persona_quick:
        st.session_state["user_role"] = "ADMIN"
        st.session_state["username"] = "admin_user"
        st.session_state["team_id"] = None
    elif "team_alpha" in persona_quick:
        st.session_state["user_role"] = "TEAM_LEAD"
        st.session_state["username"] = "lead_team_alpha"
        st.session_state["team_id"] = "team_alpha"
    elif "team_beta" in persona_quick:
        st.session_state["user_role"] = "TEAM_LEAD"
        st.session_state["username"] = "lead_team_beta"
        st.session_state["team_id"] = "team_beta"
    elif "OPERATOR" in persona_quick:
        st.session_state["user_role"] = "OPERATOR"
        st.session_state["username"] = "operator_user"
        st.session_state["team_id"] = "team_alpha"
    elif "VIEWER" in persona_quick:
        st.session_state["user_role"] = "VIEWER"
        st.session_state["username"] = "viewer_user"
        st.session_state["team_id"] = None

    st.session_state["auth_token"] = create_access_token(
        user_id=1,
        username=st.session_state["username"],
        role=st.session_state["user_role"],
        team_id=st.session_state["team_id"],
    )

    st.caption(f"Role: {st.session_state['user_role']} | Team: {st.session_state['team_id'] or 'All'}")
    st.markdown("</div>", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# 5. Route to Selected View
# ─────────────────────────────────────────────────────────────────────────────

active_region = st.session_state.get("active_region", "IN-TG")

if selected_nav == "📊 Dashboard":
    render_dashboard_overview(active_region=active_region)
elif selected_nav == "📋 Workloads":
    render_workloads_view()
elif selected_nav == "➕ Submit Workload":
    render_submit_workload_view()
elif selected_nav == "⚙️ Scheduling Engine":
    render_scheduling_engine_view()
elif selected_nav == "🖥️ Job Monitoring":
    render_job_monitoring_view()
elif selected_nav == "🌿 Carbon & Cost Data":
    render_carbon_cost_view(active_region=active_region)
elif selected_nav == "🌍 Regions & Resources":
    render_regions_resources_view()
elif selected_nav == "🛡️ Approvals":
    render_approvals_view()
elif selected_nav == "🔐 Audit & Trust":
    render_audit_trust_view()
elif selected_nav == "⚠️ Alerts & Incidents":
    render_alerts_incidents_view()
elif selected_nav == "🩺 System Health":
    render_system_health_view()
elif selected_nav == "📈 Metrics & Observability":
    render_metrics_view()
elif selected_nav == "🏢 Organizations":
    render_organizations_view()
elif selected_nav == "👥 Users & Access":
    render_users_access_view()
elif selected_nav == "📑 Reports":
    render_reports_view()
elif selected_nav == "⚙️ Settings":
    render_settings_view()
elif selected_nav == "🔑 Switch Account / Login":
    render_login_view()
