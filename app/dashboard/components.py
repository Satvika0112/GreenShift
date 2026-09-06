"""
GreenShift — Reusable Dashboard UI Components.

Includes:
  - render_status_badge: styled HTML badges matching tests and theme
  - render_metric_card: enterprise styled metric tile
  - render_health_card: component health indicator
  - render_execution_timeline: workload execution lifecycle steps
  - render_decision_factor: visual impact progress bars
  - render_empty_state: clean informative empty state
"""

from typing import Optional, Dict, Any
import streamlit as st


def render_status_badge(status: str) -> str:
    """Render a styled HTML badge for any workload status (preserving backward compatibility)."""
    s = (status or "").upper()
    if s in ("APPROVED", "COMPLETED", "HEALTHY", "READY", "LIVE"):
        return f'<span class="green-badge">{s.replace("_", " ")}</span>'
    elif s in ("PENDING", "PENDING_APPROVAL", "DEGRADED", "WARNING", "FALLBACK", "CACHED", "STALE_CACHE"):
        return f'<span class="amber-badge">{s.replace("_", " ")}</span>'
    elif s in ("DECLINED", "FAILED", "UNHEALTHY", "NOT_READY", "BLOCKED", "REJECTED"):
        return f'<span class="red-badge">{s.replace("_", " ")}</span>'
    elif s in ("QUEUED", "SCHEDULED", "SUBMITTED", "INFO"):
        return f'<span class="blue-badge">{s.replace("_", " ")}</span>'
    elif s in ("RUNNING", "EXECUTING", "IN_PROGRESS"):
        return f'<span class="purple-badge">{s.replace("_", " ")}</span>'
    else:
        return f'<span class="blue-badge">{s}</span>'


def render_metric_card(
    label: str,
    value: Any,
    subtext: Optional[str] = None,
    accent: bool = False,
    tag: Optional[str] = None,
) -> str:
    """Generate HTML for an enterprise styled metric tile."""
    accent_class = "gs-metric-accent" if accent else ""
    tag_html = f'<span class="gs-badge green-badge">{tag}</span>' if tag else ""
    sub_html = f'<div class="gs-metric-subtext">{subtext}</div>' if subtext else ""
    return f"""
    <div class="gs-metric-card">
        <div class="gs-metric-label">
            <span>{label}</span>
            {tag_html}
        </div>
        <div class="gs-metric-value {accent_class}">{value}</div>
        {sub_html}
    </div>
    """


def render_section_header(title: str, subtitle: Optional[str] = None, badge: Optional[str] = None) -> None:
    """Render a clean section header with optional subtitle and badge."""
    badge_html = f'<span class="gs-badge green-badge" style="margin-left: 8px;">{badge}</span>' if badge else ""
    sub_html = f'<div class="gs-card-subtitle">{subtitle}</div>' if subtitle else ""
    st.markdown(
        f"""
        <div style="margin-top: 18px; margin-bottom: 14px;">
            <div style="font-size: 1.15rem; font-weight: 700; color: #FFFFFF; display: flex; align-items: center;">
                {title} {badge_html}
            </div>
            {sub_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_health_card(name: str, status: str, details: Optional[str] = None, icon: str = "⚡") -> str:
    """Generate HTML for a dependency health card."""
    status_upper = status.upper()
    badge_html = render_status_badge(status_upper)
    det_html = f'<div style="font-size: 0.78rem; color: #94A3B8; margin-top: 6px;">{details}</div>' if details else ""
    return f"""
    <div class="gs-card" style="padding: 16px; margin-bottom: 12px;">
        <div style="display: flex; align-items: center; justify-content: space-between;">
            <div style="display: flex; align-items: center; gap: 10px;">
                <span style="font-size: 1.2rem;">{icon}</span>
                <div>
                    <div style="font-size: 0.95rem; font-weight: 700; color: #FFFFFF;">{name}</div>
                </div>
            </div>
            <div>{badge_html}</div>
        </div>
        {det_html}
    </div>
    """


def render_execution_timeline(status: str) -> str:
    """Generate interactive lifecycle steps timeline for workload monitoring."""
    s = (status or "").upper()
    steps = [
        ("SUBMITTED", "Submitted"),
        ("SCHEDULED", "Scheduled"),
        ("PENDING_APPROVAL", "Approval"),
        ("APPROVED", "Approved"),
        ("QUEUED", "Queued"),
        ("RUNNING", "Running"),
        ("COMPLETED", "Completed"),
    ]

    # Map status progress
    status_order = {
        "SUBMITTED": 0,
        "SCHEDULED": 1,
        "PENDING_APPROVAL": 2,
        "APPROVED": 3,
        "QUEUED": 4,
        "RUNNING": 5,
        "COMPLETED": 6,
        "DECLINED": 2,
        "FAILED": 5,
    }
    curr_idx = status_order.get(s, 0)
    is_declined = s == "DECLINED"
    is_failed = s == "FAILED"

    html = ['<div class="timeline-container">']
    for i, (code, label) in enumerate(steps):
        if is_declined and code in ("APPROVED", "QUEUED", "RUNNING", "COMPLETED"):
            cls = "timeline-step"
            icon_char = "○"
        elif is_declined and code == "PENDING_APPROVAL":
            cls = "timeline-step declined"
            icon_char = "✕"
        elif i < curr_idx:
            cls = "timeline-step completed"
            icon_char = "✓"
        elif i == curr_idx:
            if is_failed:
                cls = "timeline-step declined"
                icon_char = "✕"
            else:
                cls = "timeline-step active"
                icon_char = "●"
        else:
            cls = "timeline-step"
            icon_char = str(i + 1)

        html.append(f"""
        <div class="{cls}">
            <div class="timeline-icon">{icon_char}</div>
            <div class="timeline-label">{label}</div>
        </div>
        """)
    html.append('</div>')
    return "".join(html)


def render_decision_factor(label: str, score_pct: float, formatted_val: str) -> str:
    """Render a visual decision factor bar."""
    pct = max(0.0, min(100.0, float(score_pct)))
    return f"""
    <div class="factor-row">
        <div class="factor-label">{label}</div>
        <div class="factor-bar-bg">
            <div class="factor-bar-fill" style="width: {pct}%;"></div>
        </div>
        <div class="factor-val">{formatted_val}</div>
    </div>
    """


def render_empty_state(icon: str, title: str, description: str) -> None:
    """Render a clean informative empty state."""
    st.markdown(
        f"""
        <div class="gs-empty-state">
            <div class="gs-empty-icon">{icon}</div>
            <div class="gs-empty-title">{title}</div>
            <div class="gs-empty-desc">{description}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
