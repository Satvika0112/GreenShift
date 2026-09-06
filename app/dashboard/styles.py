"""
GreenShift — Enterprise SaaS Dashboard CSS Design System.

Visual Specs:
  - Background: #06191B (dark teal/navy)
  - Sidebar: #041315 (very dark teal)
  - Cards: #081E21 / #0B2428
  - Borders: #0E383C / #164E54
  - Primary Accent: #00E599 / #10B981 (vibrant emerald green)
  - Text Primary: #F0FDF4 / #FFFFFF
  - Text Secondary: #94A3B8 / #64748B
  - Accents: Success (#00E599), Warning (#F59E0B), Error (#EF4444), Info (#06B6D4), Queued (#8B5CF6)
"""

ENTERPRISE_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap');

    /* Global reset and base typography */
    html, body, [class*="css"], .stApp {
        font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif !important;
        background-color: #06191B !important;
        color: #F0FDF4 !important;
    }

    /* Main container styling */
    .main .block-container {
        padding-top: 1.5rem !important;
        padding-bottom: 3rem !important;
        padding-left: 2.5rem !important;
        padding-right: 2.5rem !important;
        max-width: 1400px !important;
    }

    /* Sidebar customization */
    [data-testid="stSidebar"] {
        background-color: #041315 !important;
        border-right: 1px solid #0E383C !important;
    }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
        color: #94A3B8 !important;
    }

    /* Top Bar Header Container */
    .topbar-container {
        display: flex;
        align-items: center;
        justify-content: space-between;
        background: #081E21;
        border: 1px solid #0E383C;
        border-radius: 12px;
        padding: 12px 20px;
        margin-bottom: 24px;
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2);
    }
    .topbar-brand {
        display: flex;
        align-items: center;
        gap: 12px;
    }
    .topbar-title {
        font-size: 1.25rem;
        font-weight: 700;
        color: #FFFFFF;
        letter-spacing: -0.02em;
        margin: 0;
    }
    .topbar-subtitle {
        font-size: 0.8rem;
        color: #94A3B8;
        margin: 0;
    }
    .topbar-actions {
        display: flex;
        align-items: center;
        gap: 16px;
    }

    /* Metric Card Component */
    .gs-metric-card {
        background: #081E21;
        border: 1px solid #0E383C;
        border-radius: 12px;
        padding: 18px 20px;
        position: relative;
        overflow: hidden;
        transition: transform 0.15s ease, border-color 0.15s ease, box-shadow 0.15s ease;
        margin-bottom: 12px;
    }
    .gs-metric-card:hover {
        transform: translateY(-2px);
        border-color: #164E54;
        box-shadow: 0 6px 20px rgba(0, 229, 153, 0.05);
    }
    .gs-metric-card::before {
        content: '';
        position: absolute;
        top: 0;
        left: 0;
        width: 100%;
        height: 2px;
        background: linear-gradient(90deg, #00E599 0%, transparent 100%);
    }
    .gs-metric-label {
        font-size: 0.8rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: #94A3B8;
        margin-bottom: 6px;
        display: flex;
        align-items: center;
        justify-content: space-between;
    }
    .gs-metric-value {
        font-size: 1.75rem;
        font-weight: 800;
        color: #FFFFFF;
        letter-spacing: -0.03em;
        line-height: 1.1;
        margin-bottom: 4px;
        font-family: 'Plus Jakarta Sans', sans-serif;
    }
    .gs-metric-subtext {
        font-size: 0.78rem;
        color: #64748B;
        font-weight: 500;
    }
    .gs-metric-accent {
        color: #00E599 !important;
    }

    /* General Content Card */
    .gs-card {
        background: #081E21;
        border: 1px solid #0E383C;
        border-radius: 12px;
        padding: 20px 24px;
        margin-bottom: 20px;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
    }
    .gs-card-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 16px;
        padding-bottom: 12px;
        border-bottom: 1px solid #0E383C;
    }
    .gs-card-title {
        font-size: 1.05rem;
        font-weight: 700;
        color: #FFFFFF;
        margin: 0;
        display: flex;
        align-items: center;
        gap: 8px;
    }
    .gs-card-subtitle {
        font-size: 0.8rem;
        color: #94A3B8;
        margin-top: 2px;
    }

    /* Status Badges */
    .gs-badge {
        display: inline-flex;
        align-items: center;
        padding: 4px 10px;
        border-radius: 6px;
        font-size: 0.72rem;
        font-weight: 700;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        font-family: 'JetBrains Mono', monospace;
    }
    .green-badge, .badge-approved, .badge-completed, .badge-healthy, .badge-ready, .badge-live {
        background: rgba(0, 229, 153, 0.12);
        color: #00E599 !important;
        border: 1px solid rgba(0, 229, 153, 0.3);
    }
    .amber-badge, .badge-pending, .badge-pending_approval, .badge-degraded, .badge-warning, .badge-fallback {
        background: rgba(245, 158, 11, 0.12);
        color: #F59E0B !important;
        border: 1px solid rgba(245, 158, 11, 0.3);
    }
    .red-badge, .badge-declined, .badge-failed, .badge-unhealthy, .badge-not_ready, .badge-blocked {
        background: rgba(239, 68, 68, 0.12);
        color: #EF4444 !important;
        border: 1px solid rgba(239, 68, 68, 0.3);
    }
    .blue-badge, .badge-queued, .badge-info, .badge-scheduled {
        background: rgba(6, 182, 212, 0.12);
        color: #06B6D4 !important;
        border: 1px solid rgba(6, 182, 212, 0.3);
    }
    .purple-badge, .badge-running, .badge-executing {
        background: rgba(139, 92, 246, 0.12);
        color: #A78BFA !important;
        border: 1px solid rgba(139, 92, 246, 0.3);
    }

    /* Lifecycle Timeline */
    .timeline-container {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin: 24px 0;
        padding: 16px 20px;
        background: #041315;
        border: 1px solid #0E383C;
        border-radius: 10px;
    }
    .timeline-step {
        display: flex;
        flex-direction: column;
        align-items: center;
        position: relative;
        flex: 1;
    }
    .timeline-step:not(:last-child)::after {
        content: '';
        position: absolute;
        top: 14px;
        left: 50%;
        width: 100%;
        height: 2px;
        background: #0E383C;
        z-index: 1;
    }
    .timeline-step.completed:not(:last-child)::after {
        background: #00E599;
    }
    .timeline-icon {
        width: 28px;
        height: 28px;
        border-radius: 50%;
        background: #081E21;
        border: 2px solid #0E383C;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 0.75rem;
        color: #64748B;
        z-index: 2;
        margin-bottom: 6px;
    }
    .timeline-step.active .timeline-icon {
        border-color: #00E599;
        background: rgba(0, 229, 153, 0.2);
        color: #00E599;
    }
    .timeline-step.completed .timeline-icon {
        border-color: #00E599;
        background: #00E599;
        color: #041315;
        font-weight: bold;
    }
    .timeline-step.declined .timeline-icon {
        border-color: #EF4444;
        background: #EF4444;
        color: #FFFFFF;
        font-weight: bold;
    }
    .timeline-label {
        font-size: 0.72rem;
        font-weight: 600;
        color: #94A3B8;
        text-align: center;
    }
    .timeline-step.active .timeline-label {
        color: #00E599;
        font-weight: 700;
    }

    /* Decision Factor Progress Bar */
    .factor-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 10px;
    }
    .factor-label {
        font-size: 0.82rem;
        font-weight: 600;
        color: #E2E8F0;
        width: 180px;
    }
    .factor-bar-bg {
        flex: 1;
        height: 8px;
        background: #041315;
        border-radius: 4px;
        overflow: hidden;
        margin: 0 16px;
        border: 1px solid #0E383C;
    }
    .factor-bar-fill {
        height: 100%;
        border-radius: 4px;
        background: linear-gradient(90deg, #00E599, #06B6D4);
    }
    .factor-val {
        font-size: 0.82rem;
        font-weight: 700;
        color: #00E599;
        width: 80px;
        text-align: right;
        font-family: 'JetBrains Mono', monospace;
    }

    /* Streamlit widget overrides */
    .stTextInput>div>div>input,
    .stSelectbox>div>div>div,
    .stNumberInput>div>div>input,
    .stTextArea>div>div>textarea {
        background-color: #041315 !important;
        border: 1px solid #0E383C !important;
        color: #FFFFFF !important;
        border-radius: 8px !important;
    }
    .stTextInput>div>div>input:focus,
    .stSelectbox>div>div>div:focus,
    .stNumberInput>div>div>input:focus,
    .stTextArea>div>div>textarea:focus {
        border-color: #00E599 !important;
        box-shadow: 0 0 0 1px #00E599 !important;
    }

    /* Primary and Secondary Buttons */
    .stButton>button {
        background: #081E21 !important;
        border: 1px solid #0E383C !important;
        color: #FFFFFF !important;
        font-weight: 600 !important;
        border-radius: 8px !important;
        padding: 8px 18px !important;
        transition: all 0.15s ease !important;
    }
    .stButton>button:hover {
        border-color: #00E599 !important;
        color: #00E599 !important;
        transform: translateY(-1px) !important;
    }
    .stButton>button[kind="primary"],
    .stButton>button[data-testid="stBaseButton-primary"] {
        background: #00E599 !important;
        color: #041315 !important;
        border: 1px solid #00E599 !important;
        font-weight: 700 !important;
    }
    .stButton>button[kind="primary"]:hover,
    .stButton>button[data-testid="stBaseButton-primary"]:hover {
        background: #10B981 !important;
        color: #041315 !important;
        box-shadow: 0 4px 12px rgba(0, 229, 153, 0.3) !important;
    }

    /* Table styling */
    .dataframe, [data-testid="stDataFrame"] {
        border: 1px solid #0E383C !important;
        border-radius: 8px !important;
        background: #081E21 !important;
    }

    /* Tab styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background-color: transparent;
        border-bottom: 1px solid #0E383C;
        padding-bottom: 4px;
    }
    .stTabs [data-baseweb="tab"] {
        background-color: transparent;
        border-radius: 6px;
        color: #94A3B8;
        font-weight: 600;
        padding: 8px 16px;
        border: 1px solid transparent;
    }
    .stTabs [data-baseweb="tab"]:hover {
        color: #FFFFFF;
        background: #081E21;
    }
    .stTabs [aria-selected="true"] {
        background-color: #081E21 !important;
        color: #00E599 !important;
        border: 1px solid #0E383C !important;
    }

    /* Code & Mono blocks */
    code, pre {
        font-family: 'JetBrains Mono', monospace !important;
        background-color: #041315 !important;
        color: #00E599 !important;
        border-radius: 6px !important;
        border: 1px solid #0E383C !important;
    }

    /* Empty state styling */
    .gs-empty-state {
        text-align: center;
        padding: 40px 20px;
        background: #081E21;
        border: 1px dashed #0E383C;
        border-radius: 12px;
        margin: 16px 0;
    }
    .gs-empty-icon {
        font-size: 2.5rem;
        color: #64748B;
        margin-bottom: 12px;
    }
    .gs-empty-title {
        font-size: 1.1rem;
        font-weight: 700;
        color: #FFFFFF;
        margin-bottom: 6px;
    }
    .gs-empty-desc {
        font-size: 0.85rem;
        color: #94A3B8;
        max-width: 420px;
        margin: 0 auto;
    }
</style>
"""
