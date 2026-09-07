"""
GreenShift — Human-in-the-Loop Approval Gate View.
"""

import streamlit as st
import pandas as pd

from app.dashboard.api_client import (
    fetch_pending_approvals,
    fetch_declined_approvals,
    approve_job_api,
    decline_job_api,
)
from app.dashboard.components import render_section_header, render_metric_card, render_status_badge


def render_approvals_view() -> None:
    """Render the Human Approval Gate with Approve/Decline actions and declined history."""
    render_section_header("🛡️ Human Approval Gate", "Authorize or decline proposed scheduling windows with role-based governance")

    token = st.session_state.get("auth_token")
    curr_user = st.session_state.get("username", "operator_user")

    pending_list = fetch_pending_approvals()
    declined_list = fetch_declined_approvals()

    # Top Metric Overview
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(render_metric_card("Pending Approvals", len(pending_list), "Awaiting team lead review", accent=True), unsafe_allow_html=True)
    with c2:
        st.markdown(render_metric_card("Declined Schedules", len(declined_list), "Blocked from dispatch"), unsafe_allow_html=True)
    with c3:
        st.markdown(render_metric_card("Approval Gate Policy", "STRICT", "Backend enforced"), unsafe_allow_html=True)
    with c4:
        st.markdown(render_metric_card("Operator Access", st.session_state.get("user_role", "OPERATOR"), "Active RBAC role", tag="ACTIVE"), unsafe_allow_html=True)

    tab_pending, tab_declined = st.tabs(["⏳ Pending Approvals", "🛑 Declined History"])

    with tab_pending:
        if not pending_list:
            st.info("No workloads currently awaiting human approval. All scheduled jobs are up to date.")
        else:
            for item in pending_list:
                job_id = item.get("job_id")
                schedule_id = item.get("schedule_id", 0)
                team_id = item.get("team_id", "N/A")
                region = item.get("region", "IN-TG")
                start_time = item.get("selected_start", "N/A")
                deadline = item.get("deadline", "N/A")
                runtime = item.get("runtime_minutes", 30)
                carbon_intensity = item.get("carbon_intensity", 0.0)
                cost_usd = item.get("electricity_cost_usd", 0.0)
                carbon_emission = item.get("carbon_emission_kg", 0.0)
                reason = item.get("reason", "Lowest carbon intensity window")

                st.markdown(
                    f'<div class="gs-card" style="margin-bottom: 12px;">'
                    f'<div class="gs-card-header">'
                    f'<div>'
                    f'<div class="gs-card-title">Job: <code>{job_id}</code></div>'
                    f'<div class="gs-card-subtitle">Team: <strong>{team_id}</strong> | Region: <strong>{region}</strong> | Runtime: <strong>{runtime} min</strong></div>'
                    f'</div>'
                    f'<div>{render_status_badge("PENDING_APPROVAL")}</div>'
                    f'</div>'
                    f'<div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 14px; font-size: 0.85rem;">'
                    f'<div>Proposed Start: <strong style="color: #00E599;">{str(start_time)[:16]} UTC</strong></div>'
                    f'<div>Carbon: <strong>{carbon_intensity:.1f} gCO₂/kWh</strong></div>'
                    f'<div>Cost: <strong>${cost_usd:.4f}</strong></div>'
                    f'<div>Emissions: <strong>{carbon_emission:.4f} kg</strong></div>'
                    f'</div>'
                    f'<div style="font-size: 0.82rem; color: #94A3B8; background: #041315; padding: 10px 14px; border-radius: 6px;">'
                    f'<strong>Scheduler Reason:</strong> {reason}'
                    f'</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

                col_app, col_dec_reason, col_dec_btn = st.columns([1, 2, 1])
                with col_app:
                    if st.button(f"✓ APPROVE", key=f"app_{job_id}", type="primary", use_container_width=True):
                        try:
                            approve_job_api(job_id, schedule_id, reason="Approved by Team Lead", token=token)
                            st.success(f"Job `{job_id}` approved successfully!")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Approval failed: {exc}")

                with col_dec_reason:
                    custom_decline_reason = st.text_input(
                        "Decline Reason",
                        value="Window conflicts with maintenance",
                        key=f"reason_{job_id}",
                        label_visibility="collapsed",
                    )

                with col_dec_btn:
                    if st.button(f"✕ DECLINE", key=f"dec_{job_id}", use_container_width=True):
                        try:
                            decline_job_api(job_id, schedule_id, reason=custom_decline_reason, token=token)
                            st.warning(f"Job `{job_id}` declined.")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Decline failed: {exc}")

                st.markdown('<div style="margin-bottom: 20px;"></div>', unsafe_allow_html=True)

    with tab_declined:
        if not declined_list:
            st.info("No declined workloads in audit history.")
        else:
            table_rows = []
            for d in declined_list:
                table_rows.append({
                    "Job ID": d.get("job_id"),
                    "Team": d.get("team_id"),
                    "Declined At": d.get("declined_at", "")[:19].replace("T", " "),
                    "Declined By": d.get("declined_by", "operator"),
                    "Decline Reason": d.get("reason", "N/A"),
                    "Status": "DECLINED",
                })
            df_dec = pd.DataFrame(table_rows)
            st.dataframe(df_dec, use_container_width=True, hide_index=True)
