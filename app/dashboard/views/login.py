"""
GreenShift — Login & Identity Management View.
Two-column enterprise layout connecting to real JWT authentication backend.
"""

import streamlit as st
from app.dashboard.api_client import login_user_api


def render_login_view() -> None:
    """Render the dual-column Login interface."""
    col_hero, col_form = st.columns([1.1, 0.9], gap="large")

    with col_hero:
        st.markdown(
            """
            <div style="padding: 40px 20px 40px 0;">
                <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 24px;">
                    <span style="font-size: 2.2rem;">🌿</span>
                    <span style="font-size: 1.8rem; font-weight: 800; color: #FFFFFF; letter-spacing: -0.03em;">GreenShift</span>
                </div>
                <h1 style="font-size: 2.4rem; font-weight: 800; line-height: 1.2; color: #FFFFFF; margin-bottom: 20px;">
                    Carbon & cost-aware scheduling for <span style="color: #00E599;">deferrable compute.</span>
                </h1>
                <p style="font-size: 1.05rem; line-height: 1.6; color: #94A3B8; margin-bottom: 32px;">
                    Role-based enterprise workload management with scheduling, Kubernetes execution, auditability and sustainability insights.
                </p>
                <div style="display: flex; flex-direction: column; gap: 14px; margin-top: 24px;">
                    <div style="display: flex; align-items: center; gap: 12px;">
                        <span style="color: #00E599; font-size: 1.1rem;">✓</span>
                        <span style="color: #E2E8F0; font-size: 0.95rem;">Multi-region grid carbon telemetry (Electricity Maps)</span>
                    </div>
                    <div style="display: flex; align-items: center; gap: 12px;">
                        <span style="color: #00E599; font-size: 1.1rem;">✓</span>
                        <span style="color: #E2E8F0; font-size: 0.95rem;">Automated human-in-the-loop approval gates</span>
                    </div>
                    <div style="display: flex; align-items: center; gap: 12px;">
                        <span style="color: #00E599; font-size: 1.1rem;">✓</span>
                        <span style="color: #E2E8F0; font-size: 0.95rem;">Zero-data-leak SHA-256 tamper-evident trust ledger</span>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col_form:
        st.markdown(
            '<div style="padding: 12px 0 8px 0;">'
            '<h2 style="font-size: 1.4rem; font-weight: 700; color: #FFFFFF; margin-bottom: 6px;">Sign In</h2>'
            '<p style="font-size: 0.85rem; color: #94A3B8; margin-bottom: 18px;">Authenticate to access enterprise workload controls</p>'
            '</div>',
            unsafe_allow_html=True,
        )

        with st.form("login_form", clear_on_submit=False):
            # Quick persona/role selector for development and enterprise testing
            persona_mode = st.selectbox(
                "Select Quick Role Persona or Use Custom Credentials",
                [
                    "ADMIN — admin (Full Access)",
                    "TEAM_LEAD — lead_a (Team A)",
                    "TEAM_LEAD — lead_b (Team B)",
                    "OPERATOR — operator (Execution & Dispatch)",
                    "VIEWER — viewer (Read-Only)",
                    "Custom Username/Password",
                ],
            )

            username_input = ""
            password_input = ""

            if persona_mode.startswith("ADMIN"):
                username_input = "admin"
                password_input = "admin123"
            elif "lead_a" in persona_mode:
                username_input = "lead_a"
                password_input = "lead123"
            elif "lead_b" in persona_mode:
                username_input = "lead_b"
                password_input = "lead123"
            elif "OPERATOR" in persona_mode:
                username_input = "operator"
                password_input = "operator123"
            elif "VIEWER" in persona_mode:
                username_input = "viewer"
                password_input = "viewer123"
            else:
                username_input = st.text_input("Username or Email", placeholder="user@enterprise.io")
                password_input = st.text_input("Password", type="password", placeholder="••••••••")

            submit_btn = st.form_submit_button("Sign in", use_container_width=True, type="primary")

            if submit_btn:
                if not username_input or not password_input:
                    st.error("Please provide both username/email and password.")
                else:
                    try:
                        # Authenticate exclusively through backend API
                        auth_res = login_user_api(username_input, password_input)

                        if auth_res and "access_token" in auth_res:
                            user_data = auth_res.get("user", {})
                            st.session_state["auth_token"] = auth_res["access_token"]
                            st.session_state["user_role"] = user_data.get("role", "VIEWER")
                            st.session_state["username"] = user_data.get("username", username_input)
                            st.session_state["team_id"] = user_data.get("team_id", None)
                            st.session_state["is_authenticated"] = True
                            st.success(f"Welcome, {st.session_state['username']} ({st.session_state['user_role']})!")
                            st.rerun()
                        else:
                            st.error("Authentication failed: No access token returned.")
                    except Exception as exc:
                        st.error(f"Authentication failed: {exc}")


