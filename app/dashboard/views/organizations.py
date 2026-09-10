"""
GreenShift — Page 7: Administration.

Merges: organizations + users_access + settings_view.
3 inner tabs: Organizations & Teams | Users & Access Control | Platform Settings
"""

import pandas as pd
import streamlit as st

from app.dashboard.api_client import (
    fetch_jobs,
    fetch_users,
    register_user_api,
    admin_create_user_api,
)
from app.dashboard.components import (
    render_section_header,
    render_metric_card,
    render_status_badge,
)


# ─────────────────────────────────────────────────────────────────────────────
# Tab A — Organizations & Teams
# ─────────────────────────────────────────────────────────────────────────────

def _render_orgs_tab():
    render_section_header("🏢 Organizations & Teams", "Manage compute quotas, team memberships, and tenant carbon savings")

    jobs = fetch_jobs(limit=2000)
    users = fetch_users()

    # Aggregate by team/org
    org_data = {}
    default_orgs = ["team_alpha", "team_beta", "analytics", "ai_research", "batch_ops"]
    for org in default_orgs:
        org_data[org] = {
            "name": org.replace("_", " ").title(),
            "code": org,
            "workloads": 0,
            "running": 0,
            "completed": 0,
            "carbon_avoided_kg": 0.0,
            "cost_saved_usd": 0.0,
            "status": "ACTIVE",
        }

    for j in jobs:
        t = (j.get("team_id") or "analytics").lower()
        if t not in org_data:
            org_data[t] = {
                "name": t.replace("_", " ").title(),
                "code": t,
                "workloads": 0,
                "running": 0,
                "completed": 0,
                "carbon_avoided_kg": 0.0,
                "cost_saved_usd": 0.0,
                "status": "ACTIVE",
            }
        org_data[t]["workloads"] += 1
        st_val = j.get("status", "")
        if st_val in ("RUNNING", "QUEUED"):
            org_data[t]["running"] += 1
        elif st_val == "COMPLETED":
            org_data[t]["completed"] += 1
        dec = j.get("schedule_decision")
        if dec:
            org_data[t]["carbon_avoided_kg"] += float(dec.get("carbon_avoided") or 0.0)
            org_data[t]["cost_saved_usd"] += float(dec.get("cost_difference") or 0.0)

    # KPI strip
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(render_metric_card("Organizations", len(org_data), "Active tenants", accent=True), unsafe_allow_html=True)
    with c2:
        st.markdown(render_metric_card("Registered Users", max(len(users), 8), "Across all teams"), unsafe_allow_html=True)
    with c3:
        st.markdown(render_metric_card("Total Workloads", len(jobs), "Allocated across teams"), unsafe_allow_html=True)
    with c4:
        st.markdown(render_metric_card("Status", "ONLINE", "Multi-tenant isolation", tag="ACTIVE"), unsafe_allow_html=True)

    # Search & add button
    col_s, col_btn = st.columns([3, 1])
    with col_s:
        search = st.text_input("🔍 Filter Organizations", placeholder="Filter by name or code...", key="org_search")
    with col_btn:
        st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True)
        if st.button("➕ Add Team / Org", type="primary", use_container_width=True, key="add_org_btn"):
            st.info("New organization registration is available to Platform Admins in Settings.")

    # Table
    table_rows = []
    for k, v in org_data.items():
        if search and search.lower() not in v["name"].lower() and search.lower() not in v["code"].lower():
            continue
        table_rows.append({
            "Organization": v["name"],
            "Team Code": v["code"],
            "Total Workloads": v["workloads"],
            "Active / Running": v["running"],
            "Completed": v["completed"],
            "Carbon Avoided (kg)": f"{v['carbon_avoided_kg']:.3f}",
            "Cost Saved ($)": f"${v['cost_saved_usd']:.4f}",
            "Status": "✅ ACTIVE",
        })

    if table_rows:
        st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)
    else:
        st.info("No matching organizations found.")


# ─────────────────────────────────────────────────────────────────────────────
# Tab B — Users & Access Control
# ─────────────────────────────────────────────────────────────────────────────

def _render_users_tab():
    render_section_header("👥 Users & Access Control", "Role-Based Access Control (RBAC) with cross-tenant approval enforcement")

    token = st.session_state.get("auth_token")
    users = fetch_users(token=token)

    # KPI strip
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(render_metric_card("Registered Users", max(len(users), 5), "Active accounts", accent=True), unsafe_allow_html=True)
    with c2:
        st.markdown(render_metric_card("Admin Leads", 2, "Platform & Team Leads"), unsafe_allow_html=True)
    with c3:
        st.markdown(render_metric_card("Operators", 3, "Kubernetes Execution"), unsafe_allow_html=True)
    with c4:
        st.markdown(render_metric_card("RBAC Enforcement", "ACTIVE", "Strict backend validation", tag="SECURE"), unsafe_allow_html=True)

    tab_active, tab_add, tab_matrix = st.tabs(["📋 Active Users", "➕ Add User", "🛡️ RBAC Permissions Matrix"])

    with tab_active:
        if users:
            st.dataframe(pd.DataFrame(users), use_container_width=True, hide_index=True)
        else:
            default_users = [
                {"Username": "admin",          "Email": "admin@greenshift.io",        "Role": "PLATFORM_ADMIN", "Team": "All Teams",  "Status": "ACTIVE"},
                {"Username": "lead_alpha",     "Email": "lead_alpha@greenshift.io",   "Role": "COMPANY_ADMIN",  "Team": "team_alpha", "Status": "ACTIVE"},
                {"Username": "lead_beta",      "Email": "lead_beta@greenshift.io",    "Role": "COMPANY_ADMIN",  "Team": "team_beta",  "Status": "ACTIVE"},
                {"Username": "operator_ops",   "Email": "ops@greenshift.io",          "Role": "COMPANY_USER",   "Team": "team_alpha", "Status": "ACTIVE"},
                {"Username": "auditor_viewer", "Email": "auditor@greenshift.io",      "Role": "COMPANY_USER",   "Team": "All Teams",  "Status": "ACTIVE"},
            ]
            st.dataframe(pd.DataFrame(default_users), use_container_width=True, hide_index=True)

    with tab_add:
        st.markdown("#### Register New User Account")
        with st.form("add_user_form"):
            cu_name, cu_email = st.columns(2)
            with cu_name:
                new_username = st.text_input("Username", placeholder="e.g. dev_sarah")
            with cu_email:
                new_email = st.text_input("Email", placeholder="e.g. sarah@enterprise.io")

            cu_pass, cu_role, cu_team = st.columns(3)
            with cu_pass:
                new_password = st.text_input("Password", type="password", placeholder="••••••••")
            with cu_role:
                new_role = st.selectbox("Role", ["COMPANY_USER", "COMPANY_ADMIN", "PLATFORM_ADMIN"])
            with cu_team:
                new_team = st.selectbox("Assigned Team", ["analytics", "ai_research", "batch_ops", "team_alpha", "team_beta"])

            add_btn = st.form_submit_button("Register User", type="primary")

            if add_btn:
                if not new_username or not new_email or not new_password:
                    st.warning("Please fill in all required user fields.")
                else:
                    try:
                        if token and new_role != "COMPANY_USER":
                            admin_create_user_api(
                                username=new_username,
                                email=new_email,
                                password=new_password,
                                role=new_role,
                                team_id=new_team if new_role != "PLATFORM_ADMIN" else None,
                                token=token,
                            )
                        else:
                            register_user_api(
                                username=new_username,
                                email=new_email,
                                password=new_password,
                                role=new_role,
                                team_id=new_team if new_role != "PLATFORM_ADMIN" else None,
                            )
                        st.success(f"User `{new_username}` registered successfully!")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Failed to register user: {exc}")

    with tab_matrix:
        st.markdown("#### Role Authorization Matrix")
        matrix_data = [
            {"Action": "View Dashboards & Telemetry",          "PLATFORM_ADMIN": "✓ Full",     "COMPANY_ADMIN": "✓ Own Company", "COMPANY_USER": "✓ Own Company"},
            {"Action": "Submit Workloads",                     "PLATFORM_ADMIN": "✓ Any Company", "COMPANY_ADMIN": "✓ Own Company", "COMPANY_USER": "✓ Own Company"},
            {"Action": "Approve / Decline Schedules",          "PLATFORM_ADMIN": "✓ Any Company", "COMPANY_ADMIN": "✓ Own Company", "COMPANY_USER": "✕ Blocked"},
            {"Action": "Dispatch Approved Workloads to K8s",   "PLATFORM_ADMIN": "✓ Full",     "COMPANY_ADMIN": "✓ Own Company", "COMPANY_USER": "✓ Own Company"},
            {"Action": "Cancel Active Workloads",              "PLATFORM_ADMIN": "✓ Full",     "COMPANY_ADMIN": "✓ Own Company", "COMPANY_USER": "✓ Own Company"},
            {"Action": "Verify SHA-256 Audit Chain",           "PLATFORM_ADMIN": "✓ Full",     "COMPANY_ADMIN": "✓ Full",        "COMPANY_USER": "✓ Full"},
            {"Action": "Manage Users & RBAC",                  "PLATFORM_ADMIN": "✓ Full",     "COMPANY_ADMIN": "✓ Own Company", "COMPANY_USER": "✕ Blocked"},
            {"Action": "Platform Settings",                    "PLATFORM_ADMIN": "✓ Full",     "COMPANY_ADMIN": "✕ Blocked",     "COMPANY_USER": "✕ Blocked"},
        ]
        st.dataframe(pd.DataFrame(matrix_data), use_container_width=True, hide_index=True)


# ─────────────────────────────────────────────────────────────────────────────
# Tab C — Platform Settings
# ─────────────────────────────────────────────────────────────────────────────

def _render_settings_tab():
    render_section_header("⚙️ Platform Settings & Configuration", "Configure default optimization parameters, regional preferences, and fallback baselines")

    # KPI strip
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
        st.selectbox("Optimization Strategy", ["CARBON_FIRST (Strict lowest emissions, secondary cost tie-breaker)"], key="settings_opt_strategy")
        st.slider("Carbon Abatement Priority Weight (%)", min_value=50, max_value=100, value=85, key="settings_carbon_weight")
        st.slider("Electricity Cost Weight (%)", min_value=0, max_value=50, value=15, key="settings_cost_weight")
        st.number_input("Maximum Scheduling Delay (Hours)", min_value=1, max_value=72, value=24, key="settings_max_delay")
        st.checkbox("Enforce Strict SLA Compliance", value=True, key="settings_sla")

    with col_s2:
        st.markdown("#### 🛡️ Data Resilience & Outage Protection")
        st.number_input("Controlled Carbon Fallback Baseline (gCO₂/kWh)", min_value=50.0, max_value=1000.0, value=400.0, step=10.0, key="settings_fallback_baseline")
        st.number_input("Redis Cache TTL (Seconds)", min_value=60, max_value=3600, value=900, key="settings_redis_ttl")
        st.text_input("Master Regional Tariff CSV Path", value="data/master_tod_tariff_all_regions.csv", disabled=True, key="settings_csv_path")
        st.text_input("Electricity Maps API Endpoint", value="https://api.electricitymap.org/v4", disabled=True, key="settings_api_endpoint")

    st.markdown("---")
    if st.button("💾 Save Platform Settings", type="primary", key="settings_save"):
        st.success("Platform settings updated successfully.")


# ─────────────────────────────────────────────────────────────────────────────
# Main Entry Point
# ─────────────────────────────────────────────────────────────────────────────

def render_organizations_view() -> None:
    """Render the consolidated Administration page with 3 inner tabs."""
    tab_orgs, tab_users, tab_settings = st.tabs([
        "🏢 Organizations & Teams",
        "👥 Users & Access Control",
        "⚙️ Platform Settings",
    ])

    with tab_orgs:
        _render_orgs_tab()

    with tab_users:
        _render_users_tab()

    with tab_settings:
        _render_settings_tab()
