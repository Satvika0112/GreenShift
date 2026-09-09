"""
GreenShift — Enterprise Carbon & Cost-Aware Scheduling Platform UI.

Main Entry Point for the Streamlit Enterprise Dashboard.
Consolidated 7-page navigation from legacy 16-page layout.
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

# Re-exports for backward compatibility and test runners
from app.dashboard.components import render_status_badge
from app.dashboard.api_client import (
    approve_job_api,
    decline_job_api,
    dispatch_job_api,
    fetch_pending_approvals,
    fetch_jobs,
)

# Import consolidated 7-page views
from app.dashboard.views.login import render_login_view
from app.dashboard.views.dashboard_overview import render_dashboard_overview
from app.dashboard.views.workloads import render_workloads_view
from app.dashboard.views.submit_workload import render_submit_workload_view
from app.dashboard.views.carbon_cost import render_carbon_cost_view
from app.dashboard.views.regions_resources import render_regions_resources_view
from app.dashboard.views.audit_trust import render_audit_trust_view
from app.dashboard.views.organizations import render_organizations_view


def main():
    # ─────────────────────────────────────────────────────────────────────────────
    # 1. Page Configuration & Theme Injection
    # ─────────────────────────────────────────────────────────────────────────────

    st.set_page_config(
        page_title="GreenShift — Enterprise Carbon Scheduler",
        page_icon="🌿",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.markdown(ENTERPRISE_CSS, unsafe_allow_html=True)


    # ─────────────────────────────────────────────────────────────────────────────
    # 2. Session State Initialization
    # ─────────────────────────────────────────────────────────────────────────────

    _DEFAULTS = {
        "is_authenticated": False,
        "auth_token": None,
        "user_role": None,
        "username": None,
        "team_id": None,
        "active_region": "IN-TG",
        "current_page": "📊 Dashboard",
    }
    for _k, _v in _DEFAULTS.items():
        if _k not in st.session_state:
            st.session_state[_k] = _v


    # ─────────────────────────────────────────────────────────────────────────────
    # 3. Authentication Check
    # ─────────────────────────────────────────────────────────────────────────────

    if not st.session_state.get("is_authenticated") or not st.session_state.get("auth_token"):
        render_login_view()
        st.stop()


    # ─────────────────────────────────────────────────────────────────────────────
    # 4. Sidebar — Grouped 7-Page Navigation
    # ─────────────────────────────────────────────────────────────────────────────

    _NAV_PAGES = [
        "📊 Dashboard",
        "📋 Workloads",
        "➕ Submit Workload",
        "🌿 Carbon & Cost Data",
        "🌐 Infrastructure",
        "🔐 Audit & Alerts",
        "⚙️ Administration",
    ]

    with st.sidebar:
        # Brand header
        st.markdown(
            '<div style="padding: 12px 0 6px 0;">'
            '<div style="display: flex; align-items: center; gap: 8px;">'
            '<span style="font-size: 1.4rem;">🌿</span>'
            '<span style="font-size: 1.1rem; font-weight: 800; color: #FFFFFF;">GreenShift</span>'
            '</div>'
            '<div style="font-size: 0.72rem; color: #00E599; font-weight: 600; margin-top: 2px; padding-bottom: 12px; border-bottom: 1px solid #0E383C;">● CLUSTER ONLINE</div>'
            '</div>',
            unsafe_allow_html=True,
        )

        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

        # ── OPERATIONS ──
        st.caption("OPERATIONS")
        for _page in ["📊 Dashboard", "📋 Workloads", "➕ Submit Workload"]:
            _active = st.session_state["current_page"] == _page
            _label = f"**{_page}**" if _active else _page
            if st.button(_label, key=f"nav_{_page}", use_container_width=True):
                st.session_state["current_page"] = _page
                st.rerun()

        st.markdown("<hr style='border-color:#0E383C;margin:10px 0;'>", unsafe_allow_html=True)

        # ── DATA & INTELLIGENCE ──
        st.caption("DATA & INTELLIGENCE")
        for _page in ["🌿 Carbon & Cost Data", "🌐 Infrastructure"]:
            _active = st.session_state["current_page"] == _page
            _label = f"**{_page}**" if _active else _page
            if st.button(_label, key=f"nav_{_page}", use_container_width=True):
                st.session_state["current_page"] = _page
                st.rerun()

        st.markdown("<hr style='border-color:#0E383C;margin:10px 0;'>", unsafe_allow_html=True)

        # ── GOVERNANCE ──
        st.caption("GOVERNANCE")
        for _page in ["🔐 Audit & Alerts", "⚙️ Administration"]:
            _active = st.session_state["current_page"] == _page
            _label = f"**{_page}**" if _active else _page
            if st.button(_label, key=f"nav_{_page}", use_container_width=True):
                st.session_state["current_page"] = _page
                st.rerun()

        st.markdown("<hr style='border-color:#0E383C;margin:14px 0 10px 0;'>", unsafe_allow_html=True)
        st.caption("Authenticated Identity")
        _curr_user = st.session_state.get("username", "user")
        _curr_role = st.session_state.get("user_role", "VIEWER")
        _curr_team = st.session_state.get("team_id") or "All"
        st.markdown(
            f'<div style="font-size:0.82rem;color:#94A3B8;line-height:1.7;">'
            f'👤 <strong style="color:#FFFFFF;">{_curr_user}</strong><br>'
            f'🔑 <span style="color:#00E599;">{_curr_role}</span> | 🏢 {_curr_team}'
            f'</div>',
            unsafe_allow_html=True,
        )


    # ─────────────────────────────────────────────────────────────────────────────
    # 5. Global Top Header Bar (every page)
    # ─────────────────────────────────────────────────────────────────────────────

    _region_choices = ["IN-TG", "IN-GJ", "IN-HP", "IN-WB", "US-CA", "US-TX", "US-NY", "SE", "AU-SA-Large", "AU-SA-Small"]

    hc1, hc2, hc3, hc4, hc5 = st.columns([1.4, 1.0, 1.0, 0.28, 0.28])

    with hc1:
        st.markdown(
            '<div style="display:flex;align-items:center;gap:10px;padding:4px 0;">'
            '<span style="font-size:1.5rem;">🌿</span>'
            '<div>'
            '<div style="font-size:1.1rem;font-weight:800;color:#FFFFFF;letter-spacing:-0.02em;">GreenShift</div>'
            '<div style="font-size:0.70rem;color:#94A3B8;margin-top:-2px;">Enterprise Carbon-Aware Scheduler</div>'
            '</div>'
            '</div>',
            unsafe_allow_html=True,
        )

    with hc2:
        _active_region = st.selectbox(
            "Region",
            _region_choices,
            index=_region_choices.index(st.session_state.get("active_region", "IN-TG"))
            if st.session_state.get("active_region") in _region_choices else 0,
            label_visibility="collapsed",
            key="global_region_selector",
        )
        st.session_state["active_region"] = _active_region

    with hc3:
        st.markdown(
            f'<div style="display:flex;align-items:center;justify-content:flex-end;gap:8px;padding-top:6px;">'
            f'<span class="gs-badge green-badge">{st.session_state.get("user_role","VIEWER")}</span>'
            f'<span style="font-size:0.85rem;font-weight:600;color:#FFFFFF;">{st.session_state.get("username","user")}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

    with hc4:
        if st.button("⟳", help="Refresh all data", use_container_width=True, key="global_refresh"):
            st.cache_data.clear()
            st.rerun()

    with hc5:
        if st.button("⏻", help="Logout", use_container_width=True, key="global_logout"):
            for _k in ["is_authenticated", "auth_token", "user_role", "username", "team_id"]:
                st.session_state[_k] = None if _k != "is_authenticated" else False
            st.rerun()

    st.markdown("<hr style='border-color:#0E383C;margin:6px 0 18px 0;'>", unsafe_allow_html=True)


    # ─────────────────────────────────────────────────────────────────────────────
    # 6. Route to Selected Page
    # ─────────────────────────────────────────────────────────────────────────────

    _active_region = st.session_state.get("active_region", "IN-TG")
    _current_page = st.session_state.get("current_page", "📊 Dashboard")

    if _current_page == "📊 Dashboard":
        render_dashboard_overview(active_region=_active_region)

    elif _current_page == "📋 Workloads":
        render_workloads_view()

    elif _current_page == "➕ Submit Workload":
        render_submit_workload_view()

    elif _current_page == "🌿 Carbon & Cost Data":
        render_carbon_cost_view(active_region=_active_region)

    elif _current_page == "🌐 Infrastructure":
        render_regions_resources_view()

    elif _current_page == "🔐 Audit & Alerts":
        render_audit_trust_view()

    elif _current_page == "⚙️ Administration":
        render_organizations_view()


if __name__ == "__main__":
    main()

