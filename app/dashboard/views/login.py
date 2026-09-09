"""
GreenShift — Login & Identity Management View.
Two-column enterprise layout connecting to real JWT authentication backend.
"""

import streamlit as st
from app.dashboard.api_client import login_user_api, register_user_api


def render_login_view() -> None:
    """Render the dual-column Login and User Registration interface."""
    col_hero, col_form = st.columns([1.1, 0.9], gap="large")

    with col_hero:
        st.markdown(
            """
            <div style="padding: 30px 20px 30px 0;">
                <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 20px;">
                    <span style="font-size: 2.4rem;">🌿</span>
                    <span style="font-size: 2rem; font-weight: 800; color: #FFFFFF; letter-spacing: -0.03em;">GreenShift</span>
                </div>
                <h1 style="font-size: 2.3rem; font-weight: 800; line-height: 1.25; color: #FFFFFF; margin-bottom: 18px;">
                    Carbon & cost-aware scheduling for <span style="color: #00E599;">deferrable compute.</span>
                </h1>
                <p style="font-size: 1.02rem; line-height: 1.6; color: #94A3B8; margin-bottom: 28px;">
                    Role-based enterprise workload management with automated scheduling, Kubernetes execution, auditability and sustainability insights.
                </p>
                <div style="display: flex; flex-direction: column; gap: 14px; margin-top: 20px;">
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
                    <div style="display: flex; align-items: center; gap: 12px;">
                        <span style="color: #00E599; font-size: 1.1rem;">✓</span>
                        <span style="color: #E2E8F0; font-size: 0.95rem;">Simulated local execution & production Kubernetes dispatcher</span>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col_form:
        auth_tab_login, auth_tab_signup = st.tabs(["🔑 Sign In", "📝 Create Account"])

        # ─── TAB 1: SIGN IN ──────────────────────────────────────────────────
        with auth_tab_login:
            st.markdown(
                '<div style="padding: 10px 0 6px 0;">'
                '<h2 style="font-size: 1.35rem; font-weight: 700; color: #FFFFFF; margin-bottom: 4px;">Sign In</h2>'
                '<p style="font-size: 0.85rem; color: #94A3B8; margin-bottom: 14px;">Authenticate to access enterprise workload controls</p>'
                '</div>',
                unsafe_allow_html=True,
            )

            with st.form("login_form", clear_on_submit=False):
                persona_mode = st.selectbox(
                    "Select Role",
                    [
                        "ADMIN — admin (Full Platform Access)",
                        "TEAM_LEAD — lead_a (Team A Lead)",
                        "TEAM_LEAD — lead_b (Team B Lead)",
                        "OPERATOR — operator (Dispatch & Execution)",
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

                submit_btn = st.form_submit_button("Sign In →", use_container_width=True, type="primary")

                if submit_btn:
                    if not username_input or not password_input:
                        st.error("Please provide both username/email and password.")
                    else:
                        try:
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

        # ─── TAB 2: SIGN UP / REGISTER ───────────────────────────────────────
        with auth_tab_signup:
            st.markdown(
                '<div style="padding: 10px 0 6px 0;">'
                '<h2 style="font-size: 1.35rem; font-weight: 700; color: #FFFFFF; margin-bottom: 4px;">Create Account</h2>'
                '<p style="font-size: 0.85rem; color: #94A3B8; margin-bottom: 14px;">Register a new user identity with the GreenShift cluster</p>'
                '</div>',
                unsafe_allow_html=True,
            )

            with st.form("signup_form", clear_on_submit=False):
                reg_username = st.text_input("Username", placeholder="e.g. jdoe")
                reg_email = st.text_input("Work Email", placeholder="jdoe@company.com")
                c_pw1, c_pw2 = st.columns(2)
                with c_pw1:
                    reg_pw = st.text_input("Password", type="password", placeholder="Min 6 characters")
                with c_pw2:
                    reg_pw_confirm = st.text_input("Confirm Password", type="password", placeholder="Repeat password")

                reg_team = st.selectbox("Primary Team / Unit", ["analytics", "ai_research", "batch_ops", "operations", "data_platform"])
                signup_btn = st.form_submit_button("Create Account & Sign In →", use_container_width=True, type="primary")

                if signup_btn:
                    if not reg_username or not reg_email or not reg_pw:
                        st.error("Please fill in all required fields (username, email, password).")
                    elif len(reg_username.strip()) < 3:
                        st.error("Username must be at least 3 characters long.")
                    elif len(reg_pw) < 6:
                        st.error("Password must be at least 6 characters long.")
                    elif reg_pw != reg_pw_confirm:
                        st.error("Passwords do not match. Please re-enter matching passwords.")
                    else:
                        try:
                            # 1. Register with backend
                            reg_res = register_user_api(
                                username=reg_username.strip(),
                                email=reg_email.strip(),
                                password=reg_pw,
                                role="VIEWER",
                                team_id=reg_team,
                            )
                            # 2. Immediately authenticate the newly registered user
                            auth_res = login_user_api(reg_username.strip(), reg_pw)
                            if auth_res and "access_token" in auth_res:
                                user_data = auth_res.get("user", {})
                                st.session_state["auth_token"] = auth_res["access_token"]
                                st.session_state["user_role"] = user_data.get("role", "VIEWER")
                                st.session_state["username"] = user_data.get("username", reg_username.strip())
                                st.session_state["team_id"] = user_data.get("team_id", reg_team)
                                st.session_state["is_authenticated"] = True
                                st.success(f"Account `{reg_username}` created! Redirecting to Dashboard...")
                                st.rerun()
                            else:
                                st.success("Account created successfully! Please sign in using the Sign In tab.")
                        except Exception as exc:
                            st.error(f"Registration failed: {exc}")



