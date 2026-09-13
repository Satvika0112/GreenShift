"""
GreenShift — BRSR Report Generation (PDF / Excel / CSV / JSON).

Every export pulls the same underlying data via app.brsr.service —
there is no separate "report data" computed just for export; what you see
on the BRSR pages is exactly what gets exported. Every export includes a
methodology appendix and the mandatory non-assurance disclaimer (see
ASSURANCE_DISCLAIMER) — GreenShift never claims to have independently
assessed or assured the disclosed information.
"""

import csv
import io
import json
from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.brsr.service import compute_overview, get_metric_values
from app.shared.models import BrsrAssessmentORM, BrsrCompanyProfileORM, BrsrMetricDefinitionORM, BrsrReportORM
from app.shared.timezone import ensure_utc

ASSURANCE_DISCLAIMER = (
    "GreenShift prepares traceable ESG information for reporting; it does not "
    "replace independent assessment or assurance. All GreenShift-derived figures "
    "are computed from the company's own operational data recorded in GreenShift "
    "and are traceable to source records via the Audit Trail; they are not "
    "independently assured unless the Assessment/Assurance section states "
    "otherwise (which itself is a company-provided disclosure, not a GreenShift claim)."
)

METHODOLOGY_NOTE = (
    "GreenShift-derived metrics (see each metric's 'source' and 'calculation method') "
    "are computed strictly from workload energy consumption and the scheduler's "
    "selected-slot grid carbon intensity for jobs executed through GreenShift within "
    "the stated reporting period. This is not the same as GreenShift's reported "
    "'carbon avoided' scheduling-optimization benefit, which is a separate, "
    "counterfactual efficiency metric (see Impact Reports) and is never used as a "
    "BRSR emissions figure. Company-provided metrics reflect the company's own "
    "disclosures and are marked COMPANY_PROVIDED throughout."
)


def _build_report_context(db: Session, report: BrsrReportORM) -> Dict[str, Any]:
    profile = db.query(BrsrCompanyProfileORM).filter(BrsrCompanyProfileORM.tenant_id == report.tenant_id).first()
    assessment = db.query(BrsrAssessmentORM).filter(BrsrAssessmentORM.report_id == report.id).first()
    values = get_metric_values(db, report.id)
    definitions = {d.metric_code: d for d in db.query(BrsrMetricDefinitionORM).all()}
    overview = compute_overview(db, report)

    sections: Dict[str, List[Dict[str, Any]]] = {"SECTION_A": [], "SECTION_B": [], "SECTION_C": [], "CORE": []}
    for v in values:
        defn = definitions.get(v.metric_code)
        if defn is None:
            continue
        row = {
            "metric_code": v.metric_code,
            "metric_name": defn.metric_name,
            "principle": defn.principle,
            "brsr_core_attribute": defn.brsr_core_attribute,
            "value": v.value,
            "text_value": v.text_value,
            "unit": v.unit,
            "currency": v.currency,
            "source_type": v.source_type,
            "source_record": v.source_record,
            "quality": v.quality,
            "estimated": v.estimated,
            "estimation_method": v.estimation_method,
            "assumption": v.assumption,
            "data_gap": v.data_gap,
        }
        sections.setdefault(defn.section, []).append(row)

    return {
        "company_profile": profile,
        "assessment": assessment,
        "report": report,
        "overview": overview,
        "sections": sections,
    }


# ─────────────────────────────────────────────────────────────────────────────
# JSON
# ─────────────────────────────────────────────────────────────────────────────

def generate_json(db: Session, report: BrsrReportORM) -> Dict[str, Any]:
    ctx = _build_report_context(db, report)
    profile = ctx["company_profile"]

    def _dt(v):
        # ensure_utc() guards against SQLite (dev/test) silently dropping
        # tzinfo on read — without it an exported timestamp would lack a UTC
        # offset and be ambiguous to whatever reads this JSON export.
        return ensure_utc(v).isoformat() if isinstance(v, datetime) else v

    return {
        "metadata": {
            "framework_version": report.framework_version,
            "financial_year": report.financial_year,
            "reporting_period_start": _dt(report.reporting_period_start),
            "reporting_period_end": _dt(report.reporting_period_end),
            "status": report.status,
            "generated_at": _dt(report.generated_at),
            "approved_at": _dt(report.approved_at),
            "approved_by": report.approved_by,
            "tenant_id": report.tenant_id,
        },
        "company_profile": {
            "company_name": profile.company_name if profile else None,
            "cin": profile.cin if profile else None,
            "sector": profile.sector if profile else None,
            "industry": profile.industry if profile else None,
            "listed_status": profile.listed_status if profile else None,
            "stock_exchange": profile.stock_exchange if profile else None,
            "isin": profile.isin if profile else None,
            "employees_count": profile.employees_count if profile else None,
            "workers_count": profile.workers_count if profile else None,
            "revenue": profile.revenue if profile else None,
            "revenue_currency": profile.revenue_currency if profile else None,
            "source_type": profile.source_type if profile else "MISSING",
        } if profile else {"source_type": "MISSING", "note": "Company profile not yet completed"},
        "sections": ctx["sections"],
        "data_quality_summary": ctx["overview"]["data_quality"],
        "completion_pct": ctx["overview"]["completion_pct"],
        "brsr_core_completion_pct": ctx["overview"]["brsr_core_completion_pct"],
        "assessment": {
            "assessment_status": ctx["assessment"].assessment_status if ctx["assessment"] else "NOT_ASSESSED",
            "assessor_name": ctx["assessment"].assessor_name if ctx["assessment"] else None,
            "assessor_type": ctx["assessment"].assessor_type if ctx["assessment"] else None,
            "scope": ctx["assessment"].scope if ctx["assessment"] else None,
        },
        "methodology": METHODOLOGY_NOTE,
        "assurance_disclaimer": ASSURANCE_DISCLAIMER,
    }


# ─────────────────────────────────────────────────────────────────────────────
# CSV
# ─────────────────────────────────────────────────────────────────────────────

def generate_csv(db: Session, report: BrsrReportORM) -> str:
    ctx = _build_report_context(db, report)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "section", "principle", "metric_code", "metric_name", "value", "text_value", "unit", "currency",
        "source_type", "source_record", "quality", "estimated", "estimation_method", "assumption", "data_gap",
    ])
    for section_name, rows in ctx["sections"].items():
        for row in rows:
            writer.writerow([
                section_name, row["principle"] or "", row["metric_code"], row["metric_name"],
                row["value"] if row["value"] is not None else "", row["text_value"] or "",
                row["unit"] or "", row["currency"] or "", row["source_type"], row["source_record"] or "",
                row["quality"], row["estimated"], row["estimation_method"] or "", row["assumption"] or "",
                row["data_gap"] or "",
            ])
    return buf.getvalue()


# ─────────────────────────────────────────────────────────────────────────────
# Excel (openpyxl)
# ─────────────────────────────────────────────────────────────────────────────

def generate_excel(db: Session, report: BrsrReportORM) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    ctx = _build_report_context(db, report)
    profile = ctx["company_profile"]
    wb = Workbook()

    ws = wb.active
    ws.title = "Company Profile"
    ws.append(["Field", "Value", "Source"])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    if profile:
        for field, label in [
            ("company_name", "Company Name"), ("cin", "CIN"), ("sector", "Sector"), ("industry", "Industry"),
            ("listed_status", "Listed Status"), ("stock_exchange", "Stock Exchange"), ("isin", "ISIN"),
            ("employees_count", "Employees"), ("workers_count", "Workers"),
            ("revenue", "Revenue"), ("revenue_currency", "Revenue Currency"),
        ]:
            ws.append([label, getattr(profile, field, None), profile.source_type])
    else:
        ws.append(["Company profile not yet completed", "", "MISSING"])

    section_titles = {"SECTION_A": "Section A", "SECTION_B": "Section B", "SECTION_C": "Principles", "CORE": "BRSR Core"}
    for section_key, title in section_titles.items():
        sheet = wb.create_sheet(title)
        sheet.append(["Principle", "Metric", "Value", "Unit", "Source Type", "Quality", "Estimated", "Data Gap"])
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        for row in ctx["sections"].get(section_key, []):
            sheet.append([
                row["principle"] or "", row["metric_name"],
                row["value"] if row["value"] is not None else (row["text_value"] or ""),
                row["unit"] or "", row["source_type"], row["quality"], row["estimated"], row["data_gap"] or "",
            ])

    meta = wb.create_sheet("Methodology")
    meta.append(["Financial Year", report.financial_year])
    meta.append(["Framework Version", report.framework_version])
    meta.append(["Status", report.status])
    meta.append([])
    meta.append(["Methodology"])
    meta.append([METHODOLOGY_NOTE])
    meta.append([])
    meta.append(["Assurance Disclaimer"])
    meta.append([ASSURANCE_DISCLAIMER])

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


# ─────────────────────────────────────────────────────────────────────────────
# PDF (reportlab)
# ─────────────────────────────────────────────────────────────────────────────

def generate_pdf(db: Session, report: BrsrReportORM) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    ctx = _build_report_context(db, report)
    profile = ctx["company_profile"]
    styles = getSampleStyleSheet()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=2 * cm, bottomMargin=2 * cm)
    story = []

    story.append(Paragraph("Business Responsibility and Sustainability Report", styles["Title"]))
    story.append(Paragraph(f"{profile.company_name if profile else 'Company profile not completed'}", styles["Heading2"]))
    story.append(Paragraph(
        f"Financial Year {report.financial_year} &nbsp;|&nbsp; Framework {report.framework_version} &nbsp;|&nbsp; Status {report.status}",
        styles["Normal"],
    ))
    story.append(Spacer(1, 12))

    story.append(Paragraph("Company Profile", styles["Heading2"]))
    profile_rows = [["Field", "Value"]]
    if profile:
        for label, val in [
            ("CIN", profile.cin), ("Sector", profile.sector), ("Industry", profile.industry),
            ("Listed Status", profile.listed_status), ("Stock Exchange", profile.stock_exchange),
            ("Employees", profile.employees_count), ("Workers", profile.workers_count),
            ("Revenue", f"{profile.revenue} {profile.revenue_currency}" if profile.revenue else "Not available"),
        ]:
            profile_rows.append([label, str(val) if val is not None else "Not available"])
    else:
        profile_rows.append(["Company profile", "Not yet completed"])
    story.append(_styled_table(profile_rows))
    story.append(Spacer(1, 12))

    for section_key, title in [("CORE", "BRSR Core"), ("SECTION_C", "Section C — Principle-wise Performance"),
                                ("SECTION_B", "Section B — Management & Process"), ("SECTION_A", "Section A — General Disclosures")]:
        rows = ctx["sections"].get(section_key, [])
        if not rows:
            continue
        story.append(Paragraph(title, styles["Heading2"]))
        table_rows = [["Metric", "Value", "Unit", "Source", "Quality"]]
        for row in rows:
            value_display = row["value"] if row["value"] is not None else (row["text_value"] or "Not available")
            table_rows.append([
                row["metric_name"], str(value_display), row["unit"] or "", row["source_type"], row["quality"],
            ])
        story.append(_styled_table(table_rows))
        story.append(Spacer(1, 12))

    story.append(Paragraph("Data Quality Summary", styles["Heading2"]))
    dq = ctx["overview"]["data_quality"]
    story.append(_styled_table([
        ["Quality", "Count"], ["High", str(dq["high"])], ["Medium", str(dq["medium"])],
        ["Low", str(dq["low"])], ["Missing", str(dq["missing"])],
    ]))
    story.append(Spacer(1, 12))

    story.append(Paragraph("Methodology", styles["Heading2"]))
    story.append(Paragraph(METHODOLOGY_NOTE, styles["Normal"]))
    story.append(Spacer(1, 12))

    story.append(Paragraph("Assessment / Assurance", styles["Heading2"]))
    assessment = ctx["assessment"]
    story.append(Paragraph(
        f"Status: {assessment.assessment_status if assessment else 'NOT_ASSESSED'}", styles["Normal"],
    ))
    story.append(Paragraph(ASSURANCE_DISCLAIMER, styles["Italic"]))

    doc.build(story)
    return buf.getvalue()


def _styled_table(rows: List[List[str]]) -> "Table":
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle

    table = Table(rows, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f4f6")]),
    ]))
    return table
