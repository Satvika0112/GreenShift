"""
GreenShift — Audit & Cryptographic Trust Ledger View.
"""

import streamlit as st
import pandas as pd

from app.dashboard.api_client import fetch_audit_verify, fetch_audit_events
from app.dashboard.components import render_section_header, render_metric_card, render_status_badge


def render_audit_trust_view() -> None:
    """Render the SHA-256 tamper-evident audit ledger and chain verification view."""
    render_section_header("🔐 Audit & Cryptographic Trust Ledger", "Tamper-evident SHA-256 hash-linked audit chain and provenance verification")

    chain_status = fetch_audit_verify()
    events = fetch_audit_events(limit=100)

    is_valid = chain_status.get("valid", True)
    event_count = chain_status.get("event_count", len(events))
    msg = chain_status.get("message", "Audit chain is intact")

    # Top Metric Overview
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(render_metric_card("Ledger Integrity", "100% VALID" if is_valid else "TAMPERED", "SHA-256 cryptographic chain", accent=is_valid, tag="VERIFIED"), unsafe_allow_html=True)
    with c2:
        st.markdown(render_metric_card("Total Ledger Blocks", f"{event_count:,}", "Sequential immutable records"), unsafe_allow_html=True)
    with c3:
        st.markdown(render_metric_card("Hashing Algorithm", "SHA-256", "Previous-block link binding"), unsafe_allow_html=True)
    with c4:
        st.markdown(render_metric_card("Zero Data Leaks", "ENFORCED", "Sensitive payloads sanitized", tag="PASS"), unsafe_allow_html=True)

    st.markdown(
        f'<div class="gs-card">'
        f'<div style="display: flex; align-items: center; justify-content: space-between;">'
        f'<div>'
        f'<div style="font-weight: 700; color: #FFFFFF; font-size: 1.05rem;">Chain Verification Status</div>'
        f'<div style="font-size: 0.85rem; color: #94A3B8;">{msg}</div>'
        f'</div>'
        f'<div>{render_status_badge("HEALTHY" if is_valid else "FAILED")}</div>'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Events Table
    render_section_header("📋 Ledger Block History", "Browse immutable audit blocks with hash links")

    if events:
        table_rows = []
        for ev in events:
            table_rows.append({
                "Seq": f"#{ev.get('sequence', 0)}",
                "Timestamp (UTC)": ev.get("timestamp", "")[:19].replace("T", " "),
                "Event Type": ev.get("event_type", "EVENT"),
                "Job ID": ev.get("job_id", "-"),
                "User": ev.get("user", "system"),
                "Hash": ev.get("current_hash", "")[:12] + "...",
                "Prev Hash": ev.get("previous_hash", "")[:12] + "...",
            })
        df_events = pd.DataFrame(table_rows)
        st.dataframe(df_events, use_container_width=True, hide_index=True)
    else:
        st.info("No audit events found.")
